"""Surface enumeration brick for the lego module.

Pure computation brick (no VASP). Takes a bulk structure and determines
all symmetrically non-equivalent low-index surface orientations for
Wulff construction.

Uses pymatgen SpacegroupAnalyzer and Miller index utilities.
"""

from aiida import orm
from aiida.common.links import LinkType
from aiida.engine import calcfunction

from .connections import SURFACE_ENUMERATION_PORTS as PORTS  # noqa: F401


@calcfunction
def enumerate_surfaces(structure, max_index, symprec):
    """Determine symmetrically distinct Miller indices for a bulk structure.

    Args:
        structure: AiiDA StructureData of the bulk crystal.
        max_index: orm.Int, maximum Miller index to consider.
        symprec: orm.Float, symmetry precision for SpacegroupAnalyzer.

    Returns:
        orm.Dict with crystal system, space group info, distinct Miller
        indices, and their symmetry-equivalent families.
    """
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from pymatgen.core.surface import (
        get_symmetrically_distinct_miller_indices,
        get_symmetrically_equivalent_miller_indices,
    )

    pmg_structure = structure.get_pymatgen_structure()
    max_idx = max_index.value
    sym_prec = symprec.value

    sga = SpacegroupAnalyzer(pmg_structure, symprec=sym_prec)
    conv_structure = sga.get_conventional_standard_structure()

    # Re-analyze the conventional cell
    sga_conv = SpacegroupAnalyzer(conv_structure, symprec=sym_prec)

    crystal_system = sga_conv.get_crystal_system()
    sg_symbol = sga_conv.get_space_group_symbol()
    sg_number = sga_conv.get_space_group_number()
    point_group = sga_conv.get_point_group_symbol()

    distinct = get_symmetrically_distinct_miller_indices(
        conv_structure, max_idx, return_hkil=False
    )

    families = {}
    for miller in distinct:
        equiv = get_symmetrically_equivalent_miller_indices(
            conv_structure, miller
        )
        key = str(tuple(miller))
        families[key] = [list(m) for m in equiv]

    result = {
        'crystal_system': crystal_system,
        'space_group_symbol': sg_symbol,
        'space_group_number': sg_number,
        'point_group': point_group,
        'max_index': max_idx,
        'n_distinct_surfaces': len(distinct),
        'distinct_miller_indices': [list(m) for m in distinct],
        'families': families,
    }

    return orm.Dict(dict=result)


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a surface_enumeration stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    # structure_from is required
    if 'structure_from' not in stage:
        raise ValueError(
            f"Stage '{name}': surface_enumeration stages require "
            f"'structure_from' ('input' or a previous stage name)"
        )

    structure_from = stage['structure_from']
    if structure_from != 'input' and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must be "
            f"'input' or a previous stage name"
        )

    # max_index validation
    max_index = stage.get('max_index', 1)
    if not isinstance(max_index, int) or max_index < 1:
        raise ValueError(
            f"Stage '{name}': max_index must be a positive integer, "
            f"got {max_index!r}"
        )

    # symprec validation
    symprec = stage.get('symprec', 0.01)
    if not isinstance(symprec, (int, float)) or symprec <= 0:
        raise ValueError(
            f"Stage '{name}': symprec must be a positive number, "
            f"got {symprec!r}"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create surface_enumeration stage tasks in the WorkGraph.

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    input_structure = context['input_structure']

    # Resolve input structure
    structure_from = stage['structure_from']
    if structure_from == 'input':
        stage_structure = input_structure
    else:
        from . import resolve_structure_from
        stage_structure = resolve_structure_from(structure_from, context)

    max_index = stage.get('max_index', 1)
    symprec = stage.get('symprec', 0.01)

    task = wg.add_task(
        enumerate_surfaces,
        name=f'enumerate_surfaces_{stage_name}',
        structure=stage_structure,
        max_index=orm.Int(max_index),
        symprec=orm.Float(symprec),
    )

    return {
        'enumerate': task,
        'structure': stage_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose surface_enumeration stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    task = stage_tasks_result['enumerate']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.surface_enumeration.surface_families',
                task.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_surface_families',
                task.outputs.result)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a surface_enumeration stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: surface_families, crystal_system, space_group_symbol,
        space_group_number, point_group, n_distinct_surfaces,
        distinct_miller_indices, pk, stage, type.
    """
    result = {
        'surface_families': None,
        'crystal_system': None,
        'space_group_symbol': None,
        'space_group_number': None,
        'point_group': None,
        'n_distinct_surfaces': None,
        'distinct_miller_indices': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'surface_enumeration',
    }

    families_node = None

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'surface_enumeration', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'surface_families'):
                    families_node = brick_ns.surface_families
        else:
            families_attr = f'{stage_name}_surface_families'
            if hasattr(outputs, families_attr):
                families_node = getattr(outputs, families_attr)

    if families_node is not None and hasattr(families_node, 'get_dict'):
        families_dict = families_node.get_dict()
        result['surface_families'] = families_dict
        result['crystal_system'] = families_dict.get('crystal_system')
        result['space_group_symbol'] = families_dict.get('space_group_symbol')
        result['space_group_number'] = families_dict.get('space_group_number')
        result['point_group'] = families_dict.get('point_group')
        result['n_distinct_surfaces'] = families_dict.get('n_distinct_surfaces')
        result['distinct_miller_indices'] = families_dict.get('distinct_miller_indices')

    # Fallback: traverse links
    if result['surface_families'] is None:
        _extract_enumeration_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_enumeration_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract surface enumeration results by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'enumerate_surfaces_{stage_name}'

    called_calc = wg_node.base.links.get_outgoing(
        link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if task_name in link_label or link_label == task_name:
            created = child_node.base.links.get_outgoing(
                link_type=LinkType.CREATE)
            for out_link in created.all():
                out_label = out_link.link_label
                out_node = out_link.node

                if out_label == 'result' and hasattr(out_node, 'get_dict'):
                    families_dict = out_node.get_dict()
                    result['surface_families'] = families_dict
                    result['crystal_system'] = families_dict.get('crystal_system')
                    result['space_group_symbol'] = families_dict.get('space_group_symbol')
                    result['space_group_number'] = families_dict.get('space_group_number')
                    result['point_group'] = families_dict.get('point_group')
                    result['n_distinct_surfaces'] = families_dict.get('n_distinct_surfaces')
                    result['distinct_miller_indices'] = families_dict.get('distinct_miller_indices')
            break


def print_stage_results(
    index: int, stage_name: str, stage_result: dict
) -> None:
    """Print formatted results for a surface_enumeration stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="surface_enumeration")

    if stage_result['crystal_system'] is not None:
        console.print(f"      [bold]Crystal system:[/bold] [cyan]{stage_result['crystal_system']}[/cyan]")

    if stage_result['space_group_symbol'] is not None:
        sg = stage_result['space_group_symbol']
        sg_num = stage_result.get('space_group_number', '')
        console.print(f"      [bold]Space group:[/bold] [cyan]{sg}[/cyan] (#{sg_num})")

    if stage_result['point_group'] is not None:
        console.print(f"      [bold]Point group:[/bold] [cyan]{stage_result['point_group']}[/cyan]")

    if stage_result['n_distinct_surfaces'] is not None:
        console.print(f"      [bold]Distinct surfaces:[/bold] {stage_result['n_distinct_surfaces']}")

    if stage_result['distinct_miller_indices'] is not None:
        for miller in stage_result['distinct_miller_indices']:
            hkl = '({})'.format(' '.join(str(i) for i in miller))
            families = stage_result.get('surface_families', {})
            key = str(tuple(miller))
            n_equiv = len(families.get(key, []))
            console.print(f"        [cyan]{hkl}[/cyan]  ({n_equiv} equivalent)")
