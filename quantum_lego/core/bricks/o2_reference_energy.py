"""O2 reference energy brick for the lego module.

Computes an *effective* reference energy for O2 using the water-splitting reaction,
avoiding the well-known DFT error of directly computing the O2 molecule with
semi-local functionals (e.g., PBE).

Reference (see docs):
    quantum_lego/core/bricks/surface_thermo_docs/o2_dft/o2_dft.tex

Final equation (room temperature, 1 bar thermochemical corrections folded in):
    E_ref(O2) = 2 E_DFT(H2O) - 2 E_DFT(H2) + 5.52 eV

This brick:
  1) Runs VASP for H2 and H2O (molecule-in-a-box, gamma-only by default)
  2) Extracts their total energies
  3) Computes E_ref(O2)
  4) Exposes:
      - a dummy 2-atom O2 StructureData (for compatibility with formation_enthalpy)
      - the E_ref(O2) energy (Float, eV per O2 molecule)
      - a Dict with all relevant values used in the equation
"""

from __future__ import annotations

import typing as t

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task

from .connections import O2_REFERENCE_ENERGY_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_total_energy

# Constants from the o2_dft.tex derivation (298.15 K, 1 bar)
WATER_SPLITTING_DELTA_G_EXP_EV = 4.92
ZPE_H2O_EV = 0.56
TS_H2O_EV = 0.67
ZPE_H2_EV = 0.27
TS_H2_EV = 0.41
ZPE_O2_EV = 0.10
TS_O2_EV = 0.64

# 4.92 - 0.22 + 0.28 + 0.54 = 5.52 eV
WATER_SPLITTING_CONSTANT_EV = 5.52


@task.calcfunction
def compute_o2_reference_energy(h2_energy: orm.Float, h2o_energy: orm.Float) -> orm.Float:
    """Compute E_ref(O2) from DFT energies of H2 and H2O."""
    e_h2 = float(h2_energy.value)
    e_h2o = float(h2o_energy.value)
    e_o2 = 2.0 * e_h2o - 2.0 * e_h2 + WATER_SPLITTING_CONSTANT_EV
    return orm.Float(e_o2)


@task.calcfunction
def build_dummy_o2_structure() -> orm.StructureData:
    """Build a dummy O2 StructureData (2 O atoms in a large cubic box).

    This is used so the existing formation_enthalpy brick can compute the
    per-atom oxygen reference as E_ref(O2) / 2.
    """
    from ase import Atoms

    atoms = Atoms(
        symbols=['O', 'O'],
        positions=[(0.0, 0.0, 0.0), (0.0, 0.0, 1.21)],  # ~O=O bond length
        cell=(15.0, 15.0, 15.0),
        pbc=True,
    )
    atoms.center()
    return orm.StructureData(ase=atoms)


@task.calcfunction
def build_o2_reference_report(
    h2_energy: orm.Float,
    h2o_energy: orm.Float,
    o2_reference_energy: orm.Float,
) -> orm.Dict:
    """Return a Dict with all values used to compute E_ref(O2)."""
    e_h2 = float(h2_energy.value)
    e_h2o = float(h2o_energy.value)
    e_o2 = float(o2_reference_energy.value)

    return orm.Dict(
        dict={
            'method': 'water_splitting_reference',
            'equation': 'E_ref(O2) = 2E_DFT(H2O) - 2E_DFT(H2) + 5.52 eV',
            'o2_reference_energy_eV': e_o2,
            'o2_reference_energy_per_O_atom_eV': e_o2 / 2.0,
            'h2_energy_eV': e_h2,
            'h2o_energy_eV': e_h2o,
            'water_splitting_constant_eV': WATER_SPLITTING_CONSTANT_EV,
            'delta_G_exp_eV': WATER_SPLITTING_DELTA_G_EXP_EV,
            'thermochemical_corrections_eV': {
                'H2O': {'ZPE': ZPE_H2O_EV, 'TS': TS_H2O_EV},
                'H2': {'ZPE': ZPE_H2_EV, 'TS': TS_H2_EV},
                'O2': {'ZPE': ZPE_O2_EV, 'TS': TS_O2_EV},
            },
        }
    )


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate an o2_reference_energy stage configuration."""
    name = stage['name']

    for key in ('h2_structure', 'h2o_structure', 'h2_incar', 'h2o_incar'):
        if key not in stage:
            raise ValueError(f"Stage '{name}': o2_reference_energy requires '{key}'")

    for key in ('h2_incar', 'h2o_incar'):
        if not isinstance(stage.get(key), dict):
            raise ValueError(
                f"Stage '{name}': {key} must be a dict, got {type(stage.get(key)).__name__}"
            )

    if 'kpoints' in stage:
        kpts = stage['kpoints']
        if not isinstance(kpts, (list, tuple)) or len(kpts) != 3 or not all(
            isinstance(x, int) and x > 0 for x in kpts
        ):
            raise ValueError(
                f"Stage '{name}': kpoints must be [nx, ny, nz] positive ints, got {kpts!r}"
            )

    if 'kpoints_spacing' in stage:
        ks = stage['kpoints_spacing']
        if not isinstance(ks, (int, float)) or float(ks) <= 0:
            raise ValueError(
                f"Stage '{name}': kpoints_spacing must be a positive number, got {ks!r}"
            )

    if 'retrieve' in stage and stage['retrieve'] is not None:
        if not isinstance(stage['retrieve'], (list, tuple)) or not all(
            isinstance(x, str) for x in stage['retrieve']
        ):
            raise ValueError(
                f"Stage '{name}': retrieve must be a list of strings, got {stage['retrieve']!r}"
            )


def _load_structure(structure_like) -> orm.StructureData:
    """Load a StructureData from PK if needed."""
    if isinstance(structure_like, int):
        return orm.load_node(structure_like)
    return structure_like


def create_stage_tasks(wg: WorkGraph, stage: dict, stage_name: str, context: dict) -> dict:
    """Create o2_reference_energy stage tasks in the WorkGraph."""
    from ..workgraph import _prepare_builder_inputs

    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    options = context['options']
    clean_workdir = context['clean_workdir']
    base_kpoints_spacing = context['base_kpoints_spacing']

    kpoints_mesh = stage.get('kpoints', [1, 1, 1])
    kpoints_spacing = stage.get('kpoints_spacing', base_kpoints_spacing)
    retrieve = stage.get('retrieve', None)

    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # --- H2 ---
    h2_structure = _load_structure(stage['h2_structure'])
    h2_builder_inputs = _prepare_builder_inputs(
        incar=stage['h2_incar'],
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        retrieve=retrieve,
        restart_folder=None,
        clean_workdir=clean_workdir,
        kpoints_mesh=kpoints_mesh,
    )
    h2_vasp = wg.add_task(
        VaspTask,
        name=f'vasp_{stage_name}_h2',
        structure=h2_structure,
        code=code,
        **h2_builder_inputs,
    )
    h2_energy = wg.add_task(
        extract_total_energy,
        name=f'energy_{stage_name}_h2',
        energies=h2_vasp.outputs.misc,
        retrieved=h2_vasp.outputs.retrieved,
    )

    # --- H2O ---
    h2o_structure = _load_structure(stage['h2o_structure'])
    h2o_builder_inputs = _prepare_builder_inputs(
        incar=stage['h2o_incar'],
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        retrieve=retrieve,
        restart_folder=None,
        clean_workdir=clean_workdir,
        kpoints_mesh=kpoints_mesh,
    )
    h2o_vasp = wg.add_task(
        VaspTask,
        name=f'vasp_{stage_name}_h2o',
        structure=h2o_structure,
        code=code,
        **h2o_builder_inputs,
    )
    h2o_energy = wg.add_task(
        extract_total_energy,
        name=f'energy_{stage_name}_h2o',
        energies=h2o_vasp.outputs.misc,
        retrieved=h2o_vasp.outputs.retrieved,
    )

    # --- E_ref(O2) ---
    o2_energy = wg.add_task(
        compute_o2_reference_energy,
        name=f'o2_reference_energy_{stage_name}',
        h2_energy=h2_energy.outputs.result,
        h2o_energy=h2o_energy.outputs.result,
    )

    o2_structure = wg.add_task(
        build_dummy_o2_structure,
        name=f'o2_reference_structure_{stage_name}',
    )

    report = wg.add_task(
        build_o2_reference_report,
        name=f'o2_reference_report_{stage_name}',
        h2_energy=h2_energy.outputs.result,
        h2o_energy=h2o_energy.outputs.result,
        o2_reference_energy=o2_energy.outputs.result,
    )

    return {
        # Main outputs for downstream bricks
        'energy': o2_energy,
        'structure': o2_structure,
        'misc': report,
        # Exposed for inspection/debugging
        'h2': h2_vasp,
        'h2_energy': h2_energy,
        'h2o': h2o_vasp,
        'h2o_energy': h2o_energy,
    }


def expose_stage_outputs(wg: WorkGraph, stage_name: str, stage_tasks_result: dict, namespace_map=None) -> None:
    """Expose o2_reference_energy outputs on the WorkGraph."""
    energy_task = stage_tasks_result['energy']
    structure_task = stage_tasks_result['structure']
    report_task = stage_tasks_result['misc']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.o2_reference_energy.energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{ns}.o2_reference_energy.structure', structure_task.outputs.result)
        setattr(wg.outputs, f'{ns}.o2_reference_energy.misc', report_task.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_structure', structure_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_misc', report_task.outputs.result)


def get_stage_results(wg_node: t.Any, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from an o2_reference_energy stage."""
    result = {
        'energy': None,
        'structure': None,
        'misc': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'o2_reference_energy',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'o2_reference_energy', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'energy'):
                    node = brick_ns.energy
                    result['energy'] = node.value if hasattr(node, 'value') else float(node)
                if hasattr(brick_ns, 'structure'):
                    result['structure'] = brick_ns.structure
                if hasattr(brick_ns, 'misc') and hasattr(brick_ns.misc, 'get_dict'):
                    result['misc'] = brick_ns.misc.get_dict()
        else:
            # Flat naming
            e_attr = f'{stage_name}_energy'
            if hasattr(outputs, e_attr):
                node = getattr(outputs, e_attr)
                result['energy'] = node.value if hasattr(node, 'value') else float(node)

            s_attr = f'{stage_name}_structure'
            if hasattr(outputs, s_attr):
                result['structure'] = getattr(outputs, s_attr)

            m_attr = f'{stage_name}_misc'
            if hasattr(outputs, m_attr):
                node = getattr(outputs, m_attr)
                if hasattr(node, 'get_dict'):
                    result['misc'] = node.get_dict()

    if result['misc'] is None:
        _extract_from_links(wg_node, stage_name, result)

    return result


def _extract_from_links(wg_node, stage_name: str, result: dict) -> None:
    """Fallback: traverse WorkGraph links to find the report Dict."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'o2_reference_report_{stage_name}'
    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        if task_name not in link.link_label:
            continue
        child = link.node
        created = child.base.links.get_outgoing(link_type=LinkType.CREATE)
        for out_link in created.all():
            if out_link.link_label == 'result' and hasattr(out_link.node, 'get_dict'):
                result['misc'] = out_link.node.get_dict()
                return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for an o2_reference_energy stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="o2_reference_energy")

    energy = stage_result.get('energy')
    if energy is not None:
        console.print(f"      [bold]E_ref(O2):[/bold] {energy:.6f} eV (per O2)")
        console.print(f"      [bold]E_ref(O):[/bold]  {energy / 2.0:.6f} eV (per O atom)")
    else:
        console.print("      [dim](No energy available)[/dim]")

