"""Adsorption brick for the lego module.

Computes adsorption energies by:
  1. Separating the relaxed complete system into substrate + molecule.
  2. Running 3 parallel SCF calculations (complete, substrate, molecule).
  3. Computing E_ads = E_complete - E_substrate - E_molecule.

All logic is self-contained — no dependency on PS-TEROS.
"""

from typing import Dict, Set, Any

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task, WorkGraph

from .connections import ADSORPTION_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_total_energy
from ..types import StageContext, StageTasksResult


# ---------------------------------------------------------------------------
# Internal helper (pure Python, no AiiDA)
# ---------------------------------------------------------------------------

def _find_adsorbate_indices(pmg_struct, adsorbate_formula_str: str) -> set:
    """Find atom indices belonging to the adsorbate molecule.

    Uses a simple 1.8 Å distance-cutoff graph to find a connected component
    matching the requested chemical formula.

    Args:
        pmg_struct: ASE Atoms (complete adsorbed system).
        adsorbate_formula_str: Chemical formula of the adsorbate (e.g. 'H2O').

    Returns:
        Set of integer site indices belonging to the adsorbate.

    Raises:
        ValueError: If no component matching the formula can be found.
    """
    import networkx as nx
    from ase.formula import Formula

    adsorbate_comp = Formula(adsorbate_formula_str).count()
    n_adsorbate = int(sum(adsorbate_comp.values()))

    def find_matching_component(components):
        for comp_indices in components:
            comp_indices = sorted(comp_indices)
            if len(comp_indices) != n_adsorbate:
                continue
            local_comp: dict = {}
            for i in comp_indices:
                sym = pmg_struct[i].symbol
                local_comp[sym] = local_comp.get(sym, 0) + 1
            if local_comp == adsorbate_comp:
                return set(comp_indices)
        return None

    # Distance cutoff 1.8 Å (covalent bonds only)
    n = len(pmg_struct)
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            if pmg_struct.get_distance(i, j, mic=True) < 1.8:
                graph.add_edge(i, j)
    components = list(nx.connected_components(graph))
    result = find_matching_component(components)
    if result is not None:
        return result

    raise ValueError(
        f"Could not find adsorbate with formula '{adsorbate_formula_str}' "
        f"in structure.  Available molecular components by size: "
        f"{sorted([len(c) for c in components])}"
    )


# ---------------------------------------------------------------------------
# AiiDA calcfunctions
# ---------------------------------------------------------------------------

@task.calcfunction(outputs=['substrate', 'molecule', 'complete'])
def separate_adsorbate_structure(structure, adsorbate_formula):
    """Split a slab+adsorbate StructureData into three parts.

    Uses a simple 1.8 Å distance-cutoff connectivity graph to identify atoms
    belonging to the adsorbate.

    Args:
        structure: AiiDA StructureData — complete adsorbed system.
        adsorbate_formula: AiiDA Str — formula of the adsorbate (e.g. 'H2O').

    Returns:
        Dict with keys ``substrate``, ``molecule``, ``complete``
        (each an AiiDA StructureData).
    """
    from aiida.orm import StructureData

    formula_str = adsorbate_formula.value
    ase_struct = structure.get_ase()

    adsorbate_indices = _find_adsorbate_indices(ase_struct, formula_str)

    all_indices = set(range(len(ase_struct)))
    substrate_indices = sorted(all_indices - adsorbate_indices)
    molecule_indices = sorted(adsorbate_indices)

    substrate_ase = ase_struct[substrate_indices]
    molecule_ase = ase_struct[molecule_indices]

    return {
        'substrate': StructureData(ase=substrate_ase),
        'molecule': StructureData(ase=molecule_ase),
        'complete': StructureData(ase=ase_struct),
    }


@task.calcfunction(outputs=['result'])
def calculate_adsorption_energy(E_complete, E_substrate, E_molecule):
    """Compute E_ads = E_complete - E_substrate - E_molecule.

    Args:
        E_complete: AiiDA Float — total energy of the complete system (eV).
        E_substrate: AiiDA Float — total energy of the isolated substrate (eV).
        E_molecule: AiiDA Float — total energy of the isolated molecule (eV).

    Returns:
        Dict with key ``result`` (AiiDA Float, E_ads in eV).
    """
    e_ads = E_complete.value - E_substrate.value - E_molecule.value
    return {'result': orm.Float(e_ads)}


# ---------------------------------------------------------------------------
# Brick interface
# ---------------------------------------------------------------------------

def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate an adsorption stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined before this stage.

    Raises:
        ValueError: If required keys are missing or references are invalid.
    """
    name = stage['name']

    for key in ('structure_from', 'adsorbate_formula', 'base_incar'):
        if key not in stage:
            raise ValueError(
                f"Stage '{name}': adsorption stages require '{key}'"
            )

    structure_from = stage['structure_from']
    if structure_from != 'input' and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must be "
            f"'input' or a previous stage name"
        )


def create_stage_tasks(
    wg: WorkGraph,
    stage: Dict[str, Any],
    stage_name: str,
    context: StageContext,
) -> StageTasksResult:
    """Create adsorption stage tasks in the WorkGraph.

    Adds the following tasks:
      - ``separate_{stage_name}``   — splits structure into 3 parts
      - ``vasp_{stage_name}_complete``   ⎫
      - ``vasp_{stage_name}_substrate``  ⎬ — 3 parallel SCF calculations
      - ``vasp_{stage_name}_molecule``   ⎭
      - ``energy_{stage_name}_{comp}``   — energy extraction (×3)
      - ``ads_energy_{stage_name}``      — E_ads calcfunction

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Shared context dict (code, potential_family, …).

    Returns:
        Dict with task references for expose_stage_outputs / get_stage_results.
    """
    from . import resolve_structure_from
    from ..workgraph import _prepare_builder_inputs

    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    options = context['options']
    base_kpoints_spacing = context['base_kpoints_spacing']
    clean_workdir = context['clean_workdir']

    # ------------------------------------------------------------------ #
    # 1. Resolve complete (relaxed) structure                             #
    # ------------------------------------------------------------------ #
    structure_from = stage['structure_from']
    complete_structure = resolve_structure_from(structure_from, context)

    # ------------------------------------------------------------------ #
    # 2. Separate adsorbate from substrate                                #
    # ------------------------------------------------------------------ #
    sep_task = wg.add_task(
        separate_adsorbate_structure,
        name=f'separate_{stage_name}',
        structure=complete_structure,
        adsorbate_formula=orm.Str(stage['adsorbate_formula']),
    )

    # ------------------------------------------------------------------ #
    # 3. Build shared VASP input (same INCAR for all 3 SCFs)             #
    # ------------------------------------------------------------------ #
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    base_incar = stage['base_incar']
    kpoints_spacing = stage.get('kpoints_spacing', base_kpoints_spacing)
    kpoints_mesh = stage.get('kpoints', None)
    retrieve = stage.get('retrieve', None)

    builder_inputs = _prepare_builder_inputs(
        incar=base_incar,
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        retrieve=retrieve,
        restart_folder=None,
        clean_workdir=clean_workdir,
        kpoints_mesh=kpoints_mesh,
    )

    # ------------------------------------------------------------------ #
    # 4. Three parallel VASP SCF tasks                                   #
    # ------------------------------------------------------------------ #
    vasp_complete = wg.add_task(
        VaspTask,
        name=f'vasp_{stage_name}_complete',
        structure=sep_task.outputs.complete,
        code=code,
        **builder_inputs,
    )
    vasp_substrate = wg.add_task(
        VaspTask,
        name=f'vasp_{stage_name}_substrate',
        structure=sep_task.outputs.substrate,
        code=code,
        **builder_inputs,
    )
    vasp_molecule = wg.add_task(
        VaspTask,
        name=f'vasp_{stage_name}_molecule',
        structure=sep_task.outputs.molecule,
        code=code,
        **builder_inputs,
    )

    # ------------------------------------------------------------------ #
    # 5. Energy extraction tasks                                          #
    # ------------------------------------------------------------------ #
    energy_complete = wg.add_task(
        extract_total_energy,
        name=f'energy_{stage_name}_complete',
        energies=vasp_complete.outputs.misc,
        retrieved=vasp_complete.outputs.retrieved,
    )
    energy_substrate = wg.add_task(
        extract_total_energy,
        name=f'energy_{stage_name}_substrate',
        energies=vasp_substrate.outputs.misc,
        retrieved=vasp_substrate.outputs.retrieved,
    )
    energy_molecule = wg.add_task(
        extract_total_energy,
        name=f'energy_{stage_name}_molecule',
        energies=vasp_molecule.outputs.misc,
        retrieved=vasp_molecule.outputs.retrieved,
    )

    # ------------------------------------------------------------------ #
    # 6. Adsorption energy                                                #
    # ------------------------------------------------------------------ #
    ads_energy_task = wg.add_task(
        calculate_adsorption_energy,
        name=f'ads_energy_{stage_name}',
        E_complete=energy_complete.outputs.result,
        E_substrate=energy_substrate.outputs.result,
        E_molecule=energy_molecule.outputs.result,
    )

    return {
        'separate_task': sep_task,
        'vasp_complete': vasp_complete,
        'vasp_substrate': vasp_substrate,
        'vasp_molecule': vasp_molecule,
        'energy_complete': energy_complete,
        'energy_substrate': energy_substrate,
        'energy_molecule': energy_molecule,
        'ads_energy_task': ads_energy_task,
        'structure': complete_structure,  # pass-through for subsequent stages
    }


def expose_stage_outputs(
    wg: WorkGraph,
    stage_name: str,
    stage_tasks_result: StageTasksResult,
    namespace_map: Dict[str, str] = None,
) -> None:
    """Expose adsorption stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping ``'main'`` to a namespace string.
                       When provided, outputs are nested under that namespace.
                       When None, flat names with ``stage_name`` prefix are used.
    """
    ads_task = stage_tasks_result['ads_energy_task']
    vasp_complete = stage_tasks_result['vasp_complete']
    vasp_substrate = stage_tasks_result['vasp_substrate']
    vasp_molecule = stage_tasks_result['vasp_molecule']
    energy_complete = stage_tasks_result['energy_complete']
    energy_substrate = stage_tasks_result['energy_substrate']
    energy_molecule = stage_tasks_result['energy_molecule']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.adsorption_energy',
                ads_task.outputs.result)
        setattr(wg.outputs, f'{ns}.complete.energy',
                energy_complete.outputs.result)
        setattr(wg.outputs, f'{ns}.complete.misc',
                vasp_complete.outputs.misc)
        setattr(wg.outputs, f'{ns}.substrate.energy',
                energy_substrate.outputs.result)
        setattr(wg.outputs, f'{ns}.substrate.misc',
                vasp_substrate.outputs.misc)
        setattr(wg.outputs, f'{ns}.molecule.energy',
                energy_molecule.outputs.result)
        setattr(wg.outputs, f'{ns}.molecule.misc',
                vasp_molecule.outputs.misc)
    else:
        setattr(wg.outputs, f'{stage_name}_adsorption_energy',
                ads_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_complete_energy',
                energy_complete.outputs.result)
        setattr(wg.outputs, f'{stage_name}_complete_misc',
                vasp_complete.outputs.misc)
        setattr(wg.outputs, f'{stage_name}_substrate_energy',
                energy_substrate.outputs.result)
        setattr(wg.outputs, f'{stage_name}_substrate_misc',
                vasp_substrate.outputs.misc)
        setattr(wg.outputs, f'{stage_name}_molecule_energy',
                energy_molecule.outputs.result)
        setattr(wg.outputs, f'{stage_name}_molecule_misc',
                vasp_molecule.outputs.misc)


def get_stage_results(
    wg_node: Any,
    wg_pk: int,
    stage_name: str,
    namespace_map: Dict[str, str] = None,
) -> Dict[str, Any]:
    """Extract results from a completed adsorption stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the adsorption stage.
        namespace_map: Dict mapping ``'main'`` to a namespace string.

    Returns:
        Dict with keys: adsorption_energy, complete, substrate, molecule,
        pk, stage, type.
    """
    result: Dict[str, Any] = {
        'adsorption_energy': None,
        'complete': {'energy': None, 'misc': None},
        'substrate': {'energy': None, 'misc': None},
        'molecule': {'energy': None, 'misc': None},
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'adsorption',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            if stage_ns is not None:
                e_ads_node = getattr(stage_ns, 'adsorption_energy', None)
                if e_ads_node is not None:
                    result['adsorption_energy'] = float(e_ads_node)
                for comp in ('complete', 'substrate', 'molecule'):
                    comp_ns = getattr(stage_ns, comp, None)
                    if comp_ns is None:
                        continue
                    e_node = getattr(comp_ns, 'energy', None)
                    if e_node is not None:
                        result[comp]['energy'] = float(e_node)
                    m_node = getattr(comp_ns, 'misc', None)
                    if m_node is not None and hasattr(m_node, 'get_dict'):
                        result[comp]['misc'] = m_node.get_dict()
        else:
            # Flat naming
            e_attr = f'{stage_name}_adsorption_energy'
            if hasattr(outputs, e_attr):
                result['adsorption_energy'] = float(getattr(outputs, e_attr))
            for comp in ('complete', 'substrate', 'molecule'):
                e_attr = f'{stage_name}_{comp}_energy'
                m_attr = f'{stage_name}_{comp}_misc'
                if hasattr(outputs, e_attr):
                    result[comp]['energy'] = float(getattr(outputs, e_attr))
                if hasattr(outputs, m_attr):
                    node = getattr(outputs, m_attr)
                    if hasattr(node, 'get_dict'):
                        result[comp]['misc'] = node.get_dict()

    # Fallback: traverse WorkGraph links
    if result['adsorption_energy'] is None:
        _extract_adsorption_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_adsorption_from_workgraph(
    wg_node: Any,
    stage_name: str,
    result: Dict[str, Any],
) -> None:
    """Fallback: extract results by traversing WorkGraph links.

    Args:
        wg_node: The WorkGraph ProcessNode.
        stage_name: Name of the adsorption stage.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    called_work = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)

    # Extract adsorption energy from ads_energy calcfunction
    ads_task_name = f'ads_energy_{stage_name}'
    for link in called_calc.all():
        if link.link_label == ads_task_name or ads_task_name in link.link_label:
            created = link.node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result':
                    result['adsorption_energy'] = float(out_link.node)
                    break

    # Extract per-component energies and misc
    for comp in ('complete', 'substrate', 'molecule'):
        vasp_task_name = f'vasp_{stage_name}_{comp}'
        for link in called_work.all():
            if link.link_label == vasp_task_name or vasp_task_name in link.link_label:
                child = link.node
                if hasattr(child, 'outputs') and hasattr(child.outputs, 'misc'):
                    misc = child.outputs.misc
                    if hasattr(misc, 'get_dict'):
                        result[comp]['misc'] = misc.get_dict()

        energy_task_name = f'energy_{stage_name}_{comp}'
        for link in called_calc.all():
            if link.link_label == energy_task_name or energy_task_name in link.link_label:
                created = link.node.base.links.get_outgoing(link_type=LinkType.CREATE)
                for out_link in created.all():
                    if out_link.link_label == 'result':
                        result[comp]['energy'] = float(out_link.node)
                        break


def print_stage_results(
    index: int,
    stage_name: str,
    stage_result: Dict[str, Any],
) -> None:
    """Print formatted results for an adsorption stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type='adsorption')

    e_ads = stage_result.get('adsorption_energy')
    if e_ads is not None:
        console.print(
            f"      [bold]E_ads:[/bold] [energy]{e_ads:.6f}[/energy] eV"
        )
    else:
        console.print("      [bold]E_ads:[/bold] N/A")

    comp_labels = {
        'complete': 'Complete system',
        'substrate': 'Substrate',
        'molecule': 'Molecule',
    }
    for comp, comp_label in comp_labels.items():
        comp_result = stage_result.get(comp, {})
        energy = comp_result.get('energy')
        label = f"[cyan]{comp_label}[/cyan]"
        if energy is not None:
            console.print(
                f"      {label} [bold]Energy:[/bold] "
                f"[energy]{energy:.6f}[/energy] eV"
            )
        else:
            console.print(f"      {label} [bold]Energy:[/bold] N/A")

        misc = comp_result.get('misc')
        if misc is not None:
            run_status = misc.get('run_status', 'N/A')
            console.print(f"        [bold]Status:[/bold] {run_status}")
