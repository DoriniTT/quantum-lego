"""Convergence brick for the lego module.

Handles ENCUT and k-points convergence testing stages using
the vasp.v2.converge workchain plus analysis calcfunctions from
quantum_lego.core.common.convergence.tasks.
"""

from aiida.common.links import LinkType
from .connections import CONVERGENCE_PORTS as PORTS


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a convergence stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    # structure_from is optional; if present, must reference a previous stage
    structure_from = stage.get('structure_from')
    if structure_from is not None and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must reference "
            f"a previous stage name"
        )

    # conv_settings must be a dict if present
    conv_settings = stage.get('conv_settings')
    if conv_settings is not None and not isinstance(conv_settings, dict):
        raise ValueError(
            f"Stage '{name}': 'conv_settings' must be a dict, "
            f"got {type(conv_settings).__name__}"
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


def create_stage_tasks(wg, stage, stage_name, context):
    """Create convergence stage tasks in the WorkGraph.

    Uses individual VaspTasks inside a convergence_scan @task.graph,
    which supports max_number_jobs for concurrency control. This replaces
    the VaspConvergenceWorkChain which launched all calculations at once.

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    from aiida import orm
    from quantum_lego.core.common.convergence.workgraph import (
        convergence_scan, DEFAULT_CONV_SETTINGS,
    )
    from quantum_lego.core.common.convergence.tasks import (
        analyze_cutoff_convergence,
        analyze_kpoints_convergence,
        extract_recommended_parameters,
    )
    from quantum_lego.core.common.utils import deep_merge_dicts

    # Resolve structure
    structure_from = stage.get('structure_from')
    if structure_from:
        from . import resolve_structure_from
        structure = resolve_structure_from(structure_from, context)
    else:
        structure = context['input_structure']

    # Merge convergence settings
    user_settings = stage.get('conv_settings', {})
    merged_settings = deep_merge_dicts(DEFAULT_CONV_SETTINGS, user_settings)

    incar = stage.get('incar', {})

    # Add convergence scan task (individual VaspTasks with concurrency control)
    converge = wg.add_task(
        convergence_scan,
        name=f'converge_{stage_name}',
        structure=structure,
        code_pk=context['code'].pk,
        base_incar=incar,
        options=context['options'],
        potential_family=context['potential_family'],
        potential_mapping=context['potential_mapping'],
        conv_settings=merged_settings,
        clean_workdir=context['clean_workdir'],
        max_number_jobs=context.get('max_concurrent_jobs'),
    )

    # Analysis tasks
    threshold = orm.Float(stage.get('convergence_threshold', 0.001))

    cutoff_task = wg.add_task(
        analyze_cutoff_convergence,
        name=f'analyze_cutoff_{stage_name}',
        conv_data=converge.outputs.cutoff_conv_data,
        threshold=threshold,
        structure=structure,
    )

    kpoints_task = wg.add_task(
        analyze_kpoints_convergence,
        name=f'analyze_kpoints_{stage_name}',
        conv_data=converge.outputs.kpoints_conv_data,
        threshold=threshold,
        structure=structure,
    )

    recommend_task = wg.add_task(
        extract_recommended_parameters,
        name=f'recommend_{stage_name}',
        cutoff_analysis=cutoff_task.outputs.result,
        kpoints_analysis=kpoints_task.outputs.result,
        threshold=threshold,
    )

    return {
        'converge': converge,
        'analyze_cutoff': cutoff_task,
        'analyze_kpoints': kpoints_task,
        'recommendations': recommend_task,
        'structure': structure,  # Pass-through for downstream stages
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose convergence stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    converge = stage_tasks_result['converge']
    cutoff_task = stage_tasks_result['analyze_cutoff']
    kpoints_task = stage_tasks_result['analyze_kpoints']
    recommend_task = stage_tasks_result['recommendations']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.convergence.cutoff_conv_data',
                converge.outputs.cutoff_conv_data)
        setattr(wg.outputs, f'{ns}.convergence.kpoints_conv_data',
                converge.outputs.kpoints_conv_data)
        setattr(wg.outputs, f'{ns}.convergence.cutoff_analysis',
                cutoff_task.outputs.result)
        setattr(wg.outputs, f'{ns}.convergence.kpoints_analysis',
                kpoints_task.outputs.result)
        setattr(wg.outputs, f'{ns}.convergence.recommendations',
                recommend_task.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_cutoff_conv_data',
                converge.outputs.cutoff_conv_data)
        setattr(wg.outputs, f'{stage_name}_kpoints_conv_data',
                converge.outputs.kpoints_conv_data)
        setattr(wg.outputs, f'{stage_name}_cutoff_analysis',
                cutoff_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_kpoints_analysis',
                kpoints_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_recommendations',
                recommend_task.outputs.result)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a convergence stage in a sequential workflow.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the convergence stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: cutoff_analysis, kpoints_analysis, recommendations,
        pk, stage, type.
    """
    result = {
        'cutoff_analysis': None,
        'kpoints_analysis': None,
        'recommendations': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'convergence',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'convergence', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'cutoff_analysis'):
                    node = brick_ns.cutoff_analysis
                    if hasattr(node, 'get_dict'):
                        result['cutoff_analysis'] = node.get_dict()
                if hasattr(brick_ns, 'kpoints_analysis'):
                    node = brick_ns.kpoints_analysis
                    if hasattr(node, 'get_dict'):
                        result['kpoints_analysis'] = node.get_dict()
                if hasattr(brick_ns, 'recommendations'):
                    node = brick_ns.recommendations
                    if hasattr(node, 'get_dict'):
                        result['recommendations'] = node.get_dict()
        else:
            # Flat naming fallback
            # Cutoff analysis
            cutoff_attr = f'{stage_name}_cutoff_analysis'
            if hasattr(outputs, cutoff_attr):
                node = getattr(outputs, cutoff_attr)
                if hasattr(node, 'get_dict'):
                    result['cutoff_analysis'] = node.get_dict()

            # K-points analysis
            kpoints_attr = f'{stage_name}_kpoints_analysis'
            if hasattr(outputs, kpoints_attr):
                node = getattr(outputs, kpoints_attr)
                if hasattr(node, 'get_dict'):
                    result['kpoints_analysis'] = node.get_dict()

            # Recommendations
            rec_attr = f'{stage_name}_recommendations'
            if hasattr(outputs, rec_attr):
                node = getattr(outputs, rec_attr)
                if hasattr(node, 'get_dict'):
                    result['recommendations'] = node.get_dict()

    # Fallback: traverse links
    if result['recommendations'] is None:
        _extract_convergence_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_convergence_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract convergence stage results by traversing WorkGraph links.

    Args:
        wg_node: The WorkGraph ProcessNode.
        stage_name: Name of the convergence stage.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    task_names = {
        f'analyze_cutoff_{stage_name}': 'cutoff_analysis',
        f'analyze_kpoints_{stage_name}': 'kpoints_analysis',
        f'recommend_{stage_name}': 'recommendations',
    }

    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        for task_name, result_key in task_names.items():
            if task_name in link_label or link_label == task_name:
                created = child_node.base.links.get_outgoing(
                    link_type=LinkType.CREATE
                )
                for out_link in created.all():
                    if out_link.link_label == 'result':
                        out_node = out_link.node
                        if hasattr(out_node, 'get_dict'):
                            result[result_key] = out_node.get_dict()
                break


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a convergence stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    print(f"  [{index}] {stage_name} (CONVERGENCE)")

    recommendations = stage_result.get('recommendations')
    if recommendations:
        rec_cutoff = recommendations.get('recommended_cutoff')
        conv_cutoff = recommendations.get('converged_cutoff_raw')
        rec_ksp = recommendations.get('recommended_kspacing')
        conv_ksp = recommendations.get('converged_kspacing_raw')
        threshold = recommendations.get('threshold_used', 0.001)
        cutoff_conv = recommendations.get('cutoff_converged', False)
        kpoints_conv = recommendations.get('kpoints_converged', False)

        if rec_cutoff is not None:
            print(f"      Recommended ENCUT: {rec_cutoff} eV "
                  f"(converged at {conv_cutoff} eV)")
        else:
            print("      Recommended ENCUT: NOT CONVERGED")

        if rec_ksp is not None:
            print(f"      Recommended k-spacing: {rec_ksp} A^-1 "
                  f"(converged at {conv_ksp} A^-1)")
        else:
            print("      Recommended k-spacing: NOT CONVERGED")

        print(f"      Threshold: {threshold * 1000:.1f} meV/atom")
        print(f"      ENCUT converged: {cutoff_conv}")
        print(f"      K-points converged: {kpoints_conv}")
    else:
        print("      (No convergence results available)")
