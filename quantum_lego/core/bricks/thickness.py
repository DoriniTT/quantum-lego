"""Thickness convergence brick for the lego module.

Wraps the existing slab thickness convergence workflow from
quantum_lego.core.common.convergence to provide thickness convergence testing
as a lego stage.

Two input modes:
1. From previous VASP stage: structure_from + energy_from point at a bulk
   relaxation stage (both must be set together).
2. Standalone: Uses the initial input structure and runs its own bulk
   relaxation to get the energy.
"""

from aiida.common.links import LinkType
from .connections import THICKNESS_PORTS as PORTS


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a thickness convergence stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    # structure_from and energy_from must be both set or both unset
    structure_from = stage.get('structure_from')
    energy_from = stage.get('energy_from')

    if (structure_from is None) != (energy_from is None):
        raise ValueError(
            f"Stage '{name}': 'structure_from' and 'energy_from' must be "
            f"both set or both unset. Got structure_from={structure_from!r}, "
            f"energy_from={energy_from!r}"
        )

    # Validate references to previous stages
    if structure_from is not None and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must reference "
            f"a previous stage name"
        )
    if energy_from is not None and energy_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' energy_from='{energy_from}' must reference "
            f"a previous stage name"
        )

    # If standalone mode, bulk_incar is required
    if structure_from is None:
        if 'bulk_incar' not in stage:
            raise ValueError(
                f"Stage '{name}': standalone thickness brick requires "
                f"'bulk_incar' (INCAR parameters for bulk relaxation)"
            )

    # miller_indices is required
    miller = stage.get('miller_indices')
    if miller is None:
        raise ValueError(
            f"Stage '{name}': 'miller_indices' is required "
            f"(e.g., [1, 1, 0])"
        )
    if not isinstance(miller, (list, tuple)) or len(miller) != 3:
        raise ValueError(
            f"Stage '{name}': 'miller_indices' must be a list of 3 integers, "
            f"got {miller!r}"
        )
    if not all(isinstance(m, int) for m in miller):
        raise ValueError(
            f"Stage '{name}': 'miller_indices' must contain integers, "
            f"got {miller!r}"
        )

    # layer_counts is required with at least 2 entries
    layers = stage.get('layer_counts')
    if layers is None:
        raise ValueError(
            f"Stage '{name}': 'layer_counts' is required "
            f"(e.g., [3, 5, 7, 9])"
        )
    if not isinstance(layers, (list, tuple)) or len(layers) < 2:
        raise ValueError(
            f"Stage '{name}': 'layer_counts' must be a list of at least "
            f"2 integers, got {layers!r}"
        )
    if not all(isinstance(n, int) and n > 0 for n in layers):
        raise ValueError(
            f"Stage '{name}': 'layer_counts' must contain positive integers, "
            f"got {layers!r}"
        )

    # convergence_threshold must be a positive float if present
    threshold = stage.get('convergence_threshold')
    if threshold is not None:
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            raise ValueError(
                f"Stage '{name}': 'convergence_threshold' must be a number, "
                f"got {type(stage['convergence_threshold']).__name__}"
            )
        if threshold <= 0:
            raise ValueError(
                f"Stage '{name}': 'convergence_threshold' must be positive, "
                f"got {threshold}"
            )

    # slab_incar must be a dict if present
    slab_incar = stage.get('slab_incar')
    if slab_incar is not None and not isinstance(slab_incar, dict):
        raise ValueError(
            f"Stage '{name}': 'slab_incar' must be a dict, "
            f"got {type(slab_incar).__name__}"
        )

    # bulk_incar must be a dict if present
    bulk_incar = stage.get('bulk_incar')
    if bulk_incar is not None and not isinstance(bulk_incar, dict):
        raise ValueError(
            f"Stage '{name}': 'bulk_incar' must be a dict, "
            f"got {type(bulk_incar).__name__}"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create thickness convergence stage tasks in the WorkGraph.

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    from aiida import orm
    from aiida.plugins import WorkflowFactory
    from aiida_workgraph import task as wg_task

    from quantum_lego.core.common.convergence import (
        extract_total_energy,
        relax_thickness_series,
        compute_surface_energies,
        gather_surface_energies,
    )
    from quantum_lego.core.common.convergence.utils import _get_thickness_settings
    from quantum_lego.core.common.convergence.slabs import generate_thickness_series

    # Resolve bulk structure and energy
    structure_from = stage.get('structure_from')
    energy_from = stage.get('energy_from')

    if structure_from is not None:
        # Mode A: from previous VASP stage
        from . import resolve_structure_from, resolve_energy_from
        bulk_structure = resolve_structure_from(structure_from, context)
        bulk_energy = resolve_energy_from(energy_from, context)
    else:
        # Mode B: standalone — use initial structure and run bulk relax
        bulk_input = context['input_structure']

        VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
        VaspTask = wg_task(VaspWorkChain)

        bulk_incar = stage.get('bulk_incar', {})
        bulk_kpoints = stage.get('bulk_kpoints_spacing',
                                 context['base_kpoints_spacing'])

        bulk_task = wg.add_task(
            VaspTask,
            name=f'bulk_relax_{stage_name}',
            structure=bulk_input,
            code=context['code'],
            parameters={'incar': bulk_incar},
            options=context['options'],
            kpoints_spacing=bulk_kpoints,
            potential_family=context['potential_family'],
            potential_mapping=orm.Dict(
                dict=dict(context['potential_mapping'])
            ),
            clean_workdir=context['clean_workdir'],
            settings=orm.Dict(dict=_get_thickness_settings()),
        )

        bulk_structure = bulk_task.outputs.structure
        bulk_energy = extract_total_energy(
            misc=bulk_task.outputs.misc,
        ).outputs.result

    # Slab generation parameters
    miller_indices = stage['miller_indices']
    layer_counts = stage['layer_counts']
    min_vacuum = stage.get('min_vacuum_thickness', 15.0)
    lll_reduce = stage.get('lll_reduce', True)
    center_slab = stage.get('center_slab', True)
    primitive = stage.get('primitive', True)
    termination_index = stage.get('termination_index', 0)

    miller_list = orm.List(list=[int(m) for m in miller_indices])
    layers_list = orm.List(list=[int(n) for n in layer_counts])

    slab_gen_task = wg.add_task(
        generate_thickness_series,
        name=f'generate_slabs_{stage_name}',
        bulk_structure=bulk_structure,
        miller_indices=miller_list,
        layer_counts=layers_list,
        min_vacuum_thickness=orm.Float(min_vacuum),
        lll_reduce=orm.Bool(lll_reduce),
        center_slab=orm.Bool(center_slab),
        primitive=orm.Bool(primitive),
        termination_index=orm.Int(termination_index),
    )

    # Slab relaxation
    slab_incar = stage.get('slab_incar', {})
    slab_kpoints = stage.get('slab_kpoints_spacing',
                             context['base_kpoints_spacing'])

    relax_task = wg.add_task(
        relax_thickness_series,
        name=f'relax_slabs_{stage_name}',
        slabs=slab_gen_task.outputs.slabs,
        code_pk=context['code'].pk,
        potential_family=context['potential_family'],
        potential_mapping=context['potential_mapping'],
        parameters=slab_incar,
        options=context['options'],
        kpoints_spacing=slab_kpoints,
        clean_workdir=context['clean_workdir'],
        max_number_jobs=None,  # Controlled by parent WorkGraph
    )

    # Surface energy calculation
    surface_energy_task = wg.add_task(
        compute_surface_energies,
        name=f'surface_energies_{stage_name}',
        slabs=relax_task.outputs.relaxed_structures,
        energies=relax_task.outputs.energies,
        bulk_structure=bulk_structure,
        bulk_energy=bulk_energy,
    )

    # Gather and analyze convergence
    convergence_threshold = stage.get('convergence_threshold', 0.01)
    gather_task = wg.add_task(
        gather_surface_energies,
        name=f'gather_{stage_name}',
        surface_energies=surface_energy_task.outputs.surface_energies,
        miller_indices=miller_list,
        convergence_threshold=orm.Float(convergence_threshold),
    )

    return {
        'gather': gather_task,
        'bulk_structure': bulk_structure,
        'bulk_energy': bulk_energy,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose thickness convergence stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    gather_task = stage_tasks_result['gather']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.thickness.convergence_results',
                gather_task.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_convergence_results',
                gather_task.outputs.result)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a thickness convergence stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the thickness stage.
        namespace_map: Dict mapping output group to namespace string.

    Returns:
        Dict with keys: convergence_results, pk, stage, type.
    """
    result = {
        'convergence_results': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'thickness',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'thickness', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'convergence_results'):
                    node = brick_ns.convergence_results
                    if hasattr(node, 'get_dict'):
                        result['convergence_results'] = node.get_dict()
        else:
            attr = f'{stage_name}_convergence_results'
            if hasattr(outputs, attr):
                node = getattr(outputs, attr)
                if hasattr(node, 'get_dict'):
                    result['convergence_results'] = node.get_dict()

    # Fallback: traverse links
    if result['convergence_results'] is None:
        _extract_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_from_workgraph(wg_node, stage_name: str, result: dict) -> None:
    """Extract thickness results by traversing WorkGraph links.

    Args:
        wg_node: The WorkGraph ProcessNode.
        stage_name: Name of the thickness stage.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    gather_name = f'gather_{stage_name}'

    called_work = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called_work.all():
        if gather_name in link.link_label or link.link_label == gather_name:
            # gather_surface_energies is a @task.graph, look for CALL_CALC
            child = link.node
            called_calc = child.base.links.get_outgoing(
                link_type=LinkType.CALL_CALC
            )
            for calc_link in called_calc.all():
                created = calc_link.node.base.links.get_outgoing(
                    link_type=LinkType.CREATE
                )
                for out_link in created.all():
                    if out_link.link_label == 'result':
                        out_node = out_link.node
                        if hasattr(out_node, 'get_dict'):
                            result['convergence_results'] = out_node.get_dict()
                            return

    # Also try CALL_CALC directly (gather may appear at top level)
    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        if gather_name in link.link_label or link.link_label == gather_name:
            created = link.node.base.links.get_outgoing(
                link_type=LinkType.CREATE
            )
            for out_link in created.all():
                if out_link.link_label == 'result':
                    out_node = out_link.node
                    if hasattr(out_node, 'get_dict'):
                        result['convergence_results'] = out_node.get_dict()
                        return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a thickness convergence stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    print(f"  [{index}] {stage_name} (THICKNESS CONVERGENCE)")

    conv = stage_result.get('convergence_results')
    if conv is None:
        print("      (No convergence results available)")
        return

    summary = conv.get('summary', {})
    miller = conv.get('miller_indices', [])
    thicknesses = summary.get('thicknesses', [])
    energies = summary.get('surface_energies_J_m2', [])
    converged = summary.get('converged', False)
    recommended = summary.get('recommended_layers')
    threshold = summary.get('convergence_threshold', 0.01)

    print(f"      Miller indices: ({', '.join(str(m) for m in miller)})")
    print(f"      Threshold: {threshold * 1000:.1f} mJ/m²")
    print()

    if thicknesses and energies:
        print(f"      {'Layers':>8s}  {'γ (J/m²)':>10s}  {'Δ (mJ/m²)':>10s}")
        print(f"      {'─' * 8}  {'─' * 10}  {'─' * 10}")
        for i, (n, gamma) in enumerate(zip(thicknesses, energies)):
            if i == 0:
                delta_str = '—'
            else:
                delta = abs(energies[i] - energies[i - 1]) * 1000
                delta_str = f'{delta:.1f}'
            print(f"      {n:8d}  {gamma:10.4f}  {delta_str:>10s}")

    print()
    if converged:
        print(f"      CONVERGED at {recommended} layers")
    else:
        print(f"      NOT CONVERGED (tested up to "
              f"{max(thicknesses) if thicknesses else '?'} layers)")
