"""Atom-pair displacement brick for the lego module.

Pure computation brick (no VASP). Takes the relaxed structure from a specific
calculation in a batch stage and displaces two atoms of a given species in
opposite Cartesian directions to break local inversion symmetry.

  Atom1 (lower site index among all atoms of 'species') →  +displacement_cart
  Atom2 (higher site index)                              →  −displacement_cart

Usage in a stage list::

    {
        'name': 'displace_c1',
        'type': 'displace_atom',
        'batch_from': 'gamma_relax',         # previous batch stage
        'calc_label': 'config1',              # which calc in that batch
        'species': 'Bi',                      # element symbol to displace
        'displacement_cart': [0.03, 0.03, 0.03],  # Å, Cartesian
    }

The brick finds all sites of *species* in the relaxed structure, sorts them by
site index, and displaces the first two in opposite directions.  If more than
two sites of that species are present the first two (lowest indices) are used.
"""

from typing import Any, Dict, Set

from aiida import orm
from aiida_workgraph import task

from .connections import DISPLACE_ATOM_PORTS as PORTS  # noqa: F401


# ---------------------------------------------------------------------------
# AiiDA calcfunction — runs inside the WorkGraph at execution time
# ---------------------------------------------------------------------------

@task.calcfunction()
def displace_atom_pair(
    structure: orm.StructureData,
    species: orm.Str,
    displacement: orm.List,
) -> orm.StructureData:
    """Displace the first two atoms of *species* in opposite Cartesian directions.

    Atom1 (lower site index) is shifted by +displacement.
    Atom2 (next lowest site index) is shifted by −displacement.

    Args:
        structure: Input StructureData.
        species: Element symbol string (e.g. 'Bi').
        displacement: orm.List with [dx, dy, dz] in Cartesian Ångström.

    Returns:
        New StructureData with the two atoms displaced.

    Raises:
        ValueError: If fewer than 2 atoms of *species* are found.
    """
    import numpy as np

    pmg = structure.get_pymatgen()
    sp = species.value
    indices = sorted(
        i for i, site in enumerate(pmg) if site.specie.symbol == sp
    )

    if len(indices) < 2:
        raise ValueError(
            f"Expected at least 2 '{sp}' atoms in structure, "
            f"found {len(indices)}"
        )

    idx1, idx2 = indices[0], indices[1]
    disp_cart = np.array(displacement.get_list(), dtype=float)

    # Convert Cartesian displacement to fractional
    lat = pmg.lattice
    disp_frac = lat.get_fractional_coords(disp_cart)

    pmg_new = pmg.copy()
    pmg_new.translate_sites([idx1],  disp_frac, frac_coords=True, to_unit_cell=True)
    pmg_new.translate_sites([idx2], -disp_frac, frac_coords=True, to_unit_cell=True)

    return orm.StructureData(pymatgen=pmg_new)


# ---------------------------------------------------------------------------
# Brick interface
# ---------------------------------------------------------------------------

def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate a displace_atom stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'batch_from' not in stage:
        raise ValueError(
            f"Stage '{name}': displace_atom stages require 'batch_from' "
            f"(name of a previous batch stage)"
        )

    batch_from = stage['batch_from']
    if batch_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' batch_from='{batch_from}' must reference "
            f"a previous stage name"
        )
    if batch_from == name:
        raise ValueError(
            f"Stage '{name}': batch_from cannot reference itself"
        )

    if 'calc_label' not in stage:
        raise ValueError(
            f"Stage '{name}': displace_atom stages require 'calc_label' "
            f"(the calculation key inside the batch stage, e.g. 'config1')"
        )

    if 'species' not in stage:
        raise ValueError(
            f"Stage '{name}': displace_atom stages require 'species' "
            f"(element symbol to displace, e.g. 'Bi')"
        )

    if 'displacement_cart' not in stage:
        raise ValueError(
            f"Stage '{name}': displace_atom stages require 'displacement_cart' "
            f"([dx, dy, dz] in Cartesian Å). Atom1 gets +disp, Atom2 gets −disp."
        )

    disp = stage['displacement_cart']
    if not isinstance(disp, (list, tuple)) or len(disp) != 3:
        raise ValueError(
            f"Stage '{name}': displacement_cart must be [dx, dy, dz], "
            f"got {disp!r}"
        )
    for val in disp:
        if not isinstance(val, (int, float)):
            raise ValueError(
                f"Stage '{name}': displacement_cart values must be numeric, "
                f"got {val!r}"
            )


def create_stage_tasks(
    wg,
    stage: Dict[str, Any],
    stage_name: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Create displace_atom stage tasks in the WorkGraph.

    Wires the relaxed structure from a specific batch calc directly into the
    displacement calcfunction. No VASP task is created.

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Shared context dict (stage_tasks, stage_types, …).

    Returns:
        Dict with {'displace': displace_task}.
    """
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    batch_from = stage['batch_from']
    ref_stage_type = stage_types.get(batch_from, 'vasp')
    if ref_stage_type != 'batch':
        raise ValueError(
            f"displace_atom stage '{stage_name}': batch_from='{batch_from}' "
            f"must reference a batch stage (got type='{ref_stage_type}')"
        )

    batch_result = stage_tasks[batch_from]
    calc_tasks = batch_result.get('calc_tasks')
    if not calc_tasks:
        raise ValueError(
            f"displace_atom stage '{stage_name}': stage '{batch_from}' "
            f"has no calc_tasks"
        )

    calc_label = stage['calc_label']
    if calc_label not in calc_tasks:
        raise ValueError(
            f"displace_atom stage '{stage_name}': calc_label='{calc_label}' "
            f"not found in batch stage '{batch_from}'. "
            f"Available labels: {list(calc_tasks.keys())}"
        )

    sp = orm.Str(stage['species'])
    disp = stage['displacement_cart']
    displacement = orm.List(list=[float(v) for v in disp])

    # Wire the structure socket from the batch VASP output directly
    structure_socket = calc_tasks[calc_label].outputs.structure

    displace_task = wg.add_task(
        displace_atom_pair,
        name=f'displace_{stage_name}',
        structure=structure_socket,
        species=sp,
        displacement=displacement,
    )

    return {'displace': displace_task}


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose displace_atom stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Optional namespace dict (e.g. {'main': 'stage1'}).
    """
    displace_task = stage_tasks_result['displace']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.displace_atom.structure',
                displace_task.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_displaced_structure',
                displace_task.outputs.result)


def get_stage_results(
    wg_node,
    wg_pk: int,
    stage_name: str,
    namespace_map: dict = None,
) -> dict:
    """Extract results from a displace_atom stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the stage.
        namespace_map: Optional namespace dict.

    Returns:
        Dict with keys: displaced_structure, pk, stage, type.
    """
    result = {
        'displaced_structure': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'displace_atom',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'displace_atom', None) if stage_ns else None
            if brick_ns is not None and hasattr(brick_ns, 'structure'):
                result['displaced_structure'] = brick_ns.structure
        else:
            attr = f'{stage_name}_displaced_structure'
            if hasattr(outputs, attr):
                result['displaced_structure'] = getattr(outputs, attr)

    return result


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a displace_atom stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type='displace_atom')

    struct = stage_result.get('displaced_structure')
    if struct is not None and hasattr(struct, 'get_formula'):
        console.print(
            f"      [bold]Displaced structure:[/bold] "
            f"{struct.get_formula()} "
            f"[dim]({len(struct.sites)} atoms, PK: {struct.pk})[/dim]"
        )
    else:
        console.print(
            "      [dim](Displacement pending or structure not yet available)[/dim]"
        )
