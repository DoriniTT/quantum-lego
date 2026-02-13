"""Birch-Murnaghan EOS refinement brick for the lego module.

Performs a zoomed-in BM scan around V0 from a previous BM fit.
Generates volume-scaled structures, runs single-point VASP calculations,
fits a refined EOS, and produces a recommended structure at refined V0.

The number of VASP tasks is fixed at graph-build time (refine_n_points),
but the actual volumes/structures are computed at runtime from the
initial BM fit's V0.
"""

from typing import Any, Dict, Set

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task, WorkGraph

from .connections import BIRCH_MURNAGHAN_REFINE_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_total_energy
from ..common.eos_tasks import (
    gather_eos_data,
    fit_birch_murnaghan_eos,
    build_recommended_structure,
    compute_refined_eos_params,
    build_single_refined_structure,
)


def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate a birch_murnaghan_refine stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'eos_from' not in stage:
        raise ValueError(
            f"Stage '{name}': birch_murnaghan_refine stages require 'eos_from' "
            f"(name of a previous birch_murnaghan stage)"
        )
    eos_from = stage['eos_from']
    if eos_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' eos_from='{eos_from}' must reference "
            f"a previous stage name"
        )

    if 'structure_from' not in stage:
        raise ValueError(
            f"Stage '{name}': birch_murnaghan_refine stages require "
            f"'structure_from'"
        )
    structure_from = stage['structure_from']
    if structure_from != 'input' and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must reference "
            f"a previous stage name or 'input'"
        )

    if 'base_incar' not in stage:
        raise ValueError(
            f"Stage '{name}': birch_murnaghan_refine stages require "
            f"'base_incar'"
        )

    n_points = stage.get('refine_n_points', 7)
    if not isinstance(n_points, int) or n_points < 4:
        raise ValueError(
            f"Stage '{name}': refine_n_points must be an integer >= 4 "
            f"(got {n_points})"
        )

    strain_range = stage.get('refine_strain_range', 0.02)
    if not isinstance(strain_range, (int, float)) or strain_range <= 0:
        raise ValueError(
            f"Stage '{name}': refine_strain_range must be positive "
            f"(got {strain_range})"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create birch_murnaghan_refine stage tasks in the WorkGraph.

    Creates:
    1. compute_refined_eos_params: computes target volumes and labels
    2. N build_single_refined_structure tasks: one scaled structure per point
    3. N VASP tasks + energy extraction tasks
    4. gather_eos_data: collects volume-energy pairs
    5. fit_birch_murnaghan_eos: fits refined EOS
    6. build_recommended_structure: scales to refined V0

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    from . import resolve_structure_from
    from ..workgraph import _prepare_builder_inputs

    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']
    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    options = context['options']
    base_kpoints_spacing = context['base_kpoints_spacing']
    clean_workdir = context['clean_workdir']

    # Get EOS result from previous BM stage
    eos_from = stage['eos_from']
    ref_stage_type = stage_types.get(eos_from)
    if ref_stage_type != 'birch_murnaghan':
        raise ValueError(
            f"Refine stage '{stage_name}' eos_from='{eos_from}' "
            f"must reference a birch_murnaghan stage "
            f"(got type='{ref_stage_type}')"
        )
    eos_result_socket = stage_tasks[eos_from]['fit'].outputs.result

    # Resolve input structure
    structure_from = stage['structure_from']
    if structure_from == 'input':
        input_structure = context['input_structure']
    else:
        input_structure = resolve_structure_from(structure_from, context)

    n_points = stage.get('refine_n_points', 7)
    strain_range = stage.get('refine_strain_range', 0.02)

    # Shared orm parameters for structure tasks
    strain_range_node = orm.Float(strain_range)
    n_points_node = orm.Int(n_points)

    # Compute volumes and labels (declared outputs: 'volumes', 'labels')
    params_task = wg.add_task(
        compute_refined_eos_params,
        name=f'params_{stage_name}',
        eos_result=eos_result_socket,
        strain_range=strain_range_node,
        n_points=n_points_node,
    )

    # VASP setup
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    base_incar = stage['base_incar']
    stage_kpoints_spacing = stage.get('kpoints_spacing', base_kpoints_spacing)
    stage_kpoints_mesh = stage.get('kpoints', None)
    stage_retrieve = stage.get('retrieve', None)

    builder_inputs = _prepare_builder_inputs(
        incar=base_incar,
        kpoints_spacing=stage_kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        retrieve=stage_retrieve,
        restart_folder=None,
        clean_workdir=clean_workdir,
        kpoints_mesh=stage_kpoints_mesh,
    )

    # Create structure + VASP + energy tasks for each refine point
    energy_tasks = {}
    calc_tasks = {}
    struct_tasks = {}
    for i in range(n_points):
        label = f'refine_{i:02d}'

        struct_task = wg.add_task(
            build_single_refined_structure,
            name=f'struct_{stage_name}_{label}',
            structure=input_structure,
            eos_result=eos_result_socket,
            strain_range=strain_range_node,
            n_points=n_points_node,
            point_index=orm.Int(i),
        )

        vasp_task = wg.add_task(
            VaspTask,
            name=f'vasp_{stage_name}_{label}',
            structure=struct_task.outputs.result,
            code=code,
            **builder_inputs,
        )

        energy_task = wg.add_task(
            extract_total_energy,
            name=f'energy_{stage_name}_{label}',
            energies=vasp_task.outputs.misc,
            retrieved=vasp_task.outputs.retrieved,
        )

        struct_tasks[label] = struct_task
        calc_tasks[label] = vasp_task
        energy_tasks[label] = energy_task

    # Create gather task
    energy_kwargs = {
        label: et.outputs.result for label, et in energy_tasks.items()
    }
    gather_task = wg.add_task(
        gather_eos_data,
        name=f'gather_refined_{stage_name}',
        volumes=params_task.outputs.volumes,
        labels=params_task.outputs.labels,
        **energy_kwargs,
    )

    # Create fit task
    fit_task = wg.add_task(
        fit_birch_murnaghan_eos,
        name=f'fit_refined_{stage_name}',
        eos_data=gather_task.outputs.result,
    )

    # Create recommend task
    recommend_task = wg.add_task(
        build_recommended_structure,
        name=f'recommend_refined_{stage_name}',
        structure=input_structure,
        eos_result=fit_task.outputs.result,
    )

    return {
        'params': params_task,
        'struct_tasks': struct_tasks,
        'calc_tasks': calc_tasks,
        'energy_tasks': energy_tasks,
        'gather': gather_task,
        'fit': fit_task,
        'recommend': recommend_task,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose birch_murnaghan_refine stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string.
    """
    fit_task = stage_tasks_result['fit']
    recommend_task = stage_tasks_result['recommend']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(
            wg.outputs,
            f'{ns}.birch_murnaghan_refine.eos_result',
            fit_task.outputs.result,
        )
        setattr(
            wg.outputs,
            f'{ns}.birch_murnaghan_refine.recommended_structure',
            recommend_task.outputs.result,
        )
    else:
        setattr(
            wg.outputs,
            f'{stage_name}_eos_result',
            fit_task.outputs.result,
        )
        setattr(
            wg.outputs,
            f'{stage_name}_recommended_structure',
            recommend_task.outputs.result,
        )


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a birch_murnaghan_refine stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the stage.
        namespace_map: Dict mapping output group to namespace string.

    Returns:
        Dict with EOS fit results and recommended structure info.
    """
    result = {
        'eos_result': None,
        'v0': None,
        'e0': None,
        'b0_GPa': None,
        'b1': None,
        'n_points': None,
        'rms_residual_eV': None,
        'recommended_label': None,
        'recommended_volume_error_pct': None,
        'recommended_structure_pk': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'birch_murnaghan_refine',
    }

    eos_node = None
    rec_struct_node = None

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = (
                getattr(stage_ns, 'birch_murnaghan_refine', None)
                if stage_ns is not None else None
            )
            if brick_ns is not None:
                if hasattr(brick_ns, 'eos_result'):
                    eos_node = brick_ns.eos_result
                if hasattr(brick_ns, 'recommended_structure'):
                    rec_struct_node = brick_ns.recommended_structure
        else:
            output_attr = f'{stage_name}_eos_result'
            if hasattr(outputs, output_attr):
                eos_node = getattr(outputs, output_attr)
            rec_attr = f'{stage_name}_recommended_structure'
            if hasattr(outputs, rec_attr):
                rec_struct_node = getattr(outputs, rec_attr)

    if eos_node is not None and hasattr(eos_node, 'get_dict'):
        eos_dict = eos_node.get_dict()
        result['eos_result'] = eos_dict
        result['v0'] = eos_dict.get('v0')
        result['e0'] = eos_dict.get('e0')
        result['b0_GPa'] = eos_dict.get('b0_GPa')
        result['b1'] = eos_dict.get('b1')
        result['n_points'] = eos_dict.get('n_points')
        result['rms_residual_eV'] = eos_dict.get('rms_residual_eV')
        result['recommended_label'] = eos_dict.get('recommended_label')
        result['recommended_volume_error_pct'] = eos_dict.get(
            'recommended_volume_error_pct'
        )

    if rec_struct_node is not None and hasattr(rec_struct_node, 'pk'):
        result['recommended_structure_pk'] = rec_struct_node.pk

    # Fallback: traverse links
    if result['eos_result'] is None:
        _extract_refine_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_refine_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract refine stage results by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'fit_refined_{stage_name}'

    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if task_name in link_label or link_label == task_name:
            created = child_node.base.links.get_outgoing(
                link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result' and hasattr(out_link.node, 'get_dict'):
                    eos_dict = out_link.node.get_dict()
                    result['eos_result'] = eos_dict
                    result['v0'] = eos_dict.get('v0')
                    result['e0'] = eos_dict.get('e0')
                    result['b0_GPa'] = eos_dict.get('b0_GPa')
                    result['b1'] = eos_dict.get('b1')
                    result['n_points'] = eos_dict.get('n_points')
                    result['rms_residual_eV'] = eos_dict.get('rms_residual_eV')
                    result['recommended_label'] = eos_dict.get(
                        'recommended_label'
                    )
                    result['recommended_volume_error_pct'] = eos_dict.get(
                        'recommended_volume_error_pct'
                    )
                    return


def print_stage_results(
    index: int, stage_name: str, stage_result: dict
) -> None:
    """Print formatted results for a birch_murnaghan_refine stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="birch_murnaghan_refine")

    if stage_result['v0'] is not None:
        console.print(f"      [bold]V0 (refined):[/bold] [energy]{stage_result['v0']:.4f}[/energy] A^3")

    if stage_result['e0'] is not None:
        console.print(f"      [bold]E0 (refined):[/bold] [energy]{stage_result['e0']:.6f}[/energy] eV")

    if stage_result['b0_GPa'] is not None:
        console.print(f"      [bold]B0 (refined):[/bold] [energy]{stage_result['b0_GPa']:.2f}[/energy] GPa")

    if stage_result['b1'] is not None:
        console.print(f"      [bold]B0' (refined):[/bold] [energy]{stage_result['b1']:.2f}[/energy]")

    if stage_result['n_points'] is not None:
        console.print(f"      [bold]Data points:[/bold] {stage_result['n_points']}")

    if stage_result['rms_residual_eV'] is not None:
        console.print(f"      [bold]RMS residual:[/bold] [energy]{stage_result['rms_residual_eV']:.2e}[/energy] eV")

    if stage_result.get('recommended_label') is not None:
        console.print(f"      [bold]Recommended calc:[/bold] {stage_result['recommended_label']}")

    if stage_result.get('recommended_volume_error_pct') is not None:
        console.print(f"      [bold]V0 error:[/bold] {stage_result['recommended_volume_error_pct']:.3f}%")

    if stage_result.get('recommended_structure_pk') is not None:
        console.print(f"      [bold]Recommended structure:[/bold] PK [pk]{stage_result['recommended_structure_pk']}[/pk]")

    # Print V/E table
    eos = stage_result.get('eos_result')
    if eos is not None:
        volumes = eos.get('volumes', [])
        energies = eos.get('energies', [])
        if volumes and energies:
            console.print("      [bold]V/E data (refined):[/bold]")
            for v, e in zip(volumes, energies):
                console.print(f"        V = {v:.4f} A^3  E = [energy]{e:.6f}[/energy] eV")
