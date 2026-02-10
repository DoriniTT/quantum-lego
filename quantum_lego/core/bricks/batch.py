"""Batch brick for the lego module.

Handles batch stages: multiple parallel VASP calculations with varying parameters.
"""

import typing as t

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task

from .connections import BATCH_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_total_energy, deep_merge_dicts


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a batch stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'structure_from' not in stage:
        raise ValueError(f"Stage '{name}': batch stages require 'structure_from'")
    if 'base_incar' not in stage:
        raise ValueError(f"Stage '{name}': batch stages require 'base_incar'")
    if 'calculations' not in stage or not stage['calculations']:
        raise ValueError(
            f"Stage '{name}': batch stages require non-empty 'calculations' dict"
        )

    structure_from = stage['structure_from']
    if structure_from != 'input' and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must reference "
            f"a previous stage name"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create batch stage tasks in the WorkGraph.

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

    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    options = context['options']
    base_kpoints_spacing = context['base_kpoints_spacing']
    clean_workdir = context['clean_workdir']

    # Resolve structure from referenced stage
    structure_from = stage['structure_from']
    if structure_from == 'input':
        input_structure = context['input_structure']
    else:
        input_structure = resolve_structure_from(structure_from, context)

    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    base_incar = stage['base_incar']
    calculations = stage['calculations']

    # Stage-level defaults
    stage_kpoints_spacing = stage.get('kpoints_spacing', base_kpoints_spacing)
    stage_kpoints_mesh = stage.get('kpoints', None)
    stage_retrieve = stage.get('retrieve', None)

    calc_tasks = {}
    energy_tasks = {}

    for calc_label, calc_config in calculations.items():
        # Deep-merge base_incar with per-calculation incar overrides
        calc_incar_overrides = calc_config.get('incar', {})
        if calc_incar_overrides:
            merged_incar = deep_merge_dicts(base_incar, calc_incar_overrides)
        else:
            merged_incar = dict(base_incar)

        # Per-calc kpoints or fall back to stage-level
        calc_kpoints_mesh = calc_config.get('kpoints', stage_kpoints_mesh)
        calc_kpoints_spacing = calc_config.get('kpoints_spacing', stage_kpoints_spacing)

        # Per-calc retrieve or fall back to stage-level
        calc_retrieve = calc_config.get('retrieve', stage_retrieve)

        # Prepare builder inputs
        builder_inputs = _prepare_builder_inputs(
            incar=merged_incar,
            kpoints_spacing=calc_kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping,
            options=options,
            retrieve=calc_retrieve,
            restart_folder=None,
            clean_workdir=clean_workdir,
            kpoints_mesh=calc_kpoints_mesh,
        )

        # Add VASP task
        vasp_task_name = f'vasp_{stage_name}_{calc_label}'
        vasp_task = wg.add_task(
            VaspTask,
            name=vasp_task_name,
            structure=input_structure,
            code=code,
            **builder_inputs
        )

        # Add energy extraction task
        energy_task_name = f'energy_{stage_name}_{calc_label}'
        energy_task = wg.add_task(
            extract_total_energy,
            name=energy_task_name,
            energies=vasp_task.outputs.misc,
            retrieved=vasp_task.outputs.retrieved,
        )

        calc_tasks[calc_label] = vasp_task
        energy_tasks[calc_label] = energy_task

    return {
        'calc_tasks': calc_tasks,
        'energy_tasks': energy_tasks,
        'structure': input_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose batch stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    for calc_label, vasp_task in stage_tasks_result['calc_tasks'].items():
        energy_task = stage_tasks_result['energy_tasks'][calc_label]

        if namespace_map is not None:
            ns = namespace_map['main']
            setattr(wg.outputs, f'{ns}.batch.{calc_label}.energy',
                    energy_task.outputs.result)
            setattr(wg.outputs, f'{ns}.batch.{calc_label}.misc',
                    vasp_task.outputs.misc)
            setattr(wg.outputs, f'{ns}.batch.{calc_label}.remote',
                    vasp_task.outputs.remote_folder)
            setattr(wg.outputs, f'{ns}.batch.{calc_label}.retrieved',
                    vasp_task.outputs.retrieved)
        else:
            setattr(wg.outputs, f'{stage_name}_{calc_label}_energy',
                    energy_task.outputs.result)
            setattr(wg.outputs, f'{stage_name}_{calc_label}_misc',
                    vasp_task.outputs.misc)
            setattr(wg.outputs, f'{stage_name}_{calc_label}_remote',
                    vasp_task.outputs.remote_folder)
            setattr(wg.outputs, f'{stage_name}_{calc_label}_retrieved',
                    vasp_task.outputs.retrieved)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a batch stage in a sequential workflow.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the batch stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: calculations, pk, stage, type.
    """
    from ..results import _extract_energy_from_misc

    result = {
        'calculations': {},
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'batch',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'batch', None) if stage_ns is not None else None
            if brick_ns is not None:
                # Each calc_label is a sub-namespace of brick_ns
                # with .energy, .misc, .remote, .retrieved inside
                for calc_label in dir(brick_ns):
                    if calc_label.startswith('_'):
                        continue
                    calc_ns = getattr(brick_ns, calc_label, None)
                    if calc_ns is None or not hasattr(calc_ns, 'energy'):
                        continue

                    calc_result = {
                        'energy': None,
                        'misc': None,
                        'remote': None,
                        'files': None,
                    }

                    if hasattr(calc_ns, 'energy'):
                        energy_node = calc_ns.energy
                        if hasattr(energy_node, 'value'):
                            calc_result['energy'] = energy_node.value
                        else:
                            calc_result['energy'] = float(energy_node)

                    if hasattr(calc_ns, 'misc'):
                        misc_node = calc_ns.misc
                        if hasattr(misc_node, 'get_dict'):
                            calc_result['misc'] = misc_node.get_dict()

                    if hasattr(calc_ns, 'remote'):
                        calc_result['remote'] = calc_ns.remote

                    if hasattr(calc_ns, 'retrieved'):
                        calc_result['files'] = calc_ns.retrieved

                    if calc_result['energy'] is None and calc_result['misc'] is not None:
                        calc_result['energy'] = _extract_energy_from_misc(calc_result['misc'])

                    result['calculations'][calc_label] = calc_result
        else:
            # Flat naming fallback
            energy_suffix = '_energy'
            stage_prefix = f'{stage_name}_'

            # Find all output attributes matching the pattern
            calc_labels = []
            for attr_name in dir(outputs):
                if attr_name.startswith(stage_prefix) and attr_name.endswith(energy_suffix):
                    calc_label = attr_name[len(stage_prefix):-len(energy_suffix)]
                    if calc_label:
                        calc_labels.append(calc_label)

            for calc_label in calc_labels:
                calc_result = {
                    'energy': None,
                    'misc': None,
                    'remote': None,
                    'files': None,
                }

                # Energy
                energy_attr = f'{stage_name}_{calc_label}_energy'
                if hasattr(outputs, energy_attr):
                    energy_node = getattr(outputs, energy_attr)
                    if hasattr(energy_node, 'value'):
                        calc_result['energy'] = energy_node.value
                    else:
                        calc_result['energy'] = float(energy_node)

                # Misc
                misc_attr = f'{stage_name}_{calc_label}_misc'
                if hasattr(outputs, misc_attr):
                    misc_node = getattr(outputs, misc_attr)
                    if hasattr(misc_node, 'get_dict'):
                        calc_result['misc'] = misc_node.get_dict()

                # Remote folder
                remote_attr = f'{stage_name}_{calc_label}_remote'
                if hasattr(outputs, remote_attr):
                    calc_result['remote'] = getattr(outputs, remote_attr)

                # Retrieved files
                retrieved_attr = f'{stage_name}_{calc_label}_retrieved'
                if hasattr(outputs, retrieved_attr):
                    calc_result['files'] = getattr(outputs, retrieved_attr)

                # Extract energy from misc if not found directly
                if calc_result['energy'] is None and calc_result['misc'] is not None:
                    calc_result['energy'] = _extract_energy_from_misc(calc_result['misc'])

                result['calculations'][calc_label] = calc_result

    # Fallback: traverse links if outputs not found
    if not result['calculations']:
        _extract_batch_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_batch_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract batch stage results by traversing WorkGraph links.

    Args:
        wg_node: The WorkGraph ProcessNode.
        stage_name: Name of the batch stage.
        result: Result dict to populate (modified in place).
    """
    from ..results import _extract_energy_from_misc

    if not hasattr(wg_node, 'base'):
        return

    vasp_prefix = f'vasp_{stage_name}_'

    # Collect calc labels from CALL_WORK links
    calc_labels = set()
    called = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called.all():
        link_label = link.link_label
        if link_label.startswith(vasp_prefix):
            calc_label = link_label[len(vasp_prefix):]
            calc_labels.add(calc_label)

    for calc_label in calc_labels:
        calc_result = {
            'energy': None,
            'misc': None,
            'remote': None,
            'files': None,
        }

        vasp_task_name = f'vasp_{stage_name}_{calc_label}'
        energy_task_name = f'energy_{stage_name}_{calc_label}'

        # Find VASP task outputs
        for link in called.all():
            if link.link_label == vasp_task_name or vasp_task_name in link.link_label:
                child_node = link.node
                if hasattr(child_node, 'outputs'):
                    outputs = child_node.outputs
                    if calc_result['misc'] is None and hasattr(outputs, 'misc'):
                        misc = outputs.misc
                        if hasattr(misc, 'get_dict'):
                            calc_result['misc'] = misc.get_dict()
                    if calc_result['remote'] is None and hasattr(outputs, 'remote_folder'):
                        calc_result['remote'] = outputs.remote_folder
                    if calc_result['files'] is None and hasattr(outputs, 'retrieved'):
                        calc_result['files'] = outputs.retrieved

        # Find energy task outputs
        called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
        for link in called_calc.all():
            if link.link_label == energy_task_name or energy_task_name in link.link_label:
                created = link.node.base.links.get_outgoing(link_type=LinkType.CREATE)
                for out_link in created.all():
                    if out_link.link_label == 'result':
                        energy_node = out_link.node
                        if hasattr(energy_node, 'value'):
                            calc_result['energy'] = energy_node.value
                        break

        # Extract energy from misc if not found
        if calc_result['energy'] is None and calc_result['misc'] is not None:
            calc_result['energy'] = _extract_energy_from_misc(calc_result['misc'])

        result['calculations'][calc_label] = calc_result


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a batch stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="batch")

    calculations = stage_result.get('calculations', {})
    if calculations:
        for calc_label, calc_result in calculations.items():
            if calc_result['energy'] is not None:
                console.print(f"      [{calc_label}] [bold]Energy:[/bold] [energy]{calc_result['energy']:.6f}[/energy] eV")
            else:
                console.print(f"      [{calc_label}] [bold]Energy:[/bold] N/A")

            if calc_result.get('misc') is not None:
                misc = calc_result['misc']
                run_status = misc.get('run_status', 'N/A')
                console.print(f"        [bold]Status:[/bold] {run_status}")

            if calc_result.get('remote') is not None:
                console.print(f"        [bold]Remote folder:[/bold] PK [pk]{calc_result['remote'].pk}[/pk]")

            if calc_result.get('files') is not None:
                files = calc_result['files'].list_object_names()
                console.print(f"        [bold]Retrieved:[/bold] [dim]{', '.join(files)}[/dim]")
    else:
        console.print("      [dim](No calculation results found)[/dim]")
