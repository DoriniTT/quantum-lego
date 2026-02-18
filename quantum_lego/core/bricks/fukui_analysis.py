"""Fukui analysis brick for the lego module.

Consumes CHGCAR files from a previous batch stage and runs Fukui interpolation
to produce CHGCAR_FUKUI.vasp as SinglefileData.
"""

from typing import Any, Dict, Set

from aiida import orm
from aiida.common.links import LinkType

from .connections import FUKUI_ANALYSIS_PORTS as PORTS  # noqa: F401


def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate a fukui_analysis stage configuration."""
    name = stage['name']

    if 'batch_from' not in stage:
        raise ValueError(
            f"Stage '{name}': fukui_analysis stages require 'batch_from' "
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

    fukui_type = stage.get('fukui_type')
    if fukui_type not in ('plus', 'minus'):
        raise ValueError(
            f"Stage '{name}': fukui_type must be 'plus' or 'minus'"
        )

    delta_n_map = stage.get('delta_n_map')
    if not isinstance(delta_n_map, dict):
        raise ValueError(
            f"Stage '{name}': delta_n_map must be a dict of "
            f"{{calc_label: delta_n}}"
        )
    if len(delta_n_map) != 4:
        raise ValueError(
            f"Stage '{name}': delta_n_map must have exactly 4 entries "
            f"(got {len(delta_n_map)})"
        )
    for label, delta_n in delta_n_map.items():
        if not isinstance(label, str):
            raise ValueError(
                f"Stage '{name}': delta_n_map keys must be strings "
                f"(got {type(label)})"
            )
        if not isinstance(delta_n, (int, float)):
            raise ValueError(
                f"Stage '{name}': delta_n_map['{label}'] must be numeric"
            )
        if float(delta_n) < 0.0:
            raise ValueError(
                f"Stage '{name}': delta_n_map['{label}'] must be >= 0.0"
            )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create fukui_analysis stage tasks in the WorkGraph."""
    from teros.core.fukui.tasks import (
        collect_chgcar_files_internal,
        run_fukui_interpolation_calcfunc,
    )

    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    batch_from = stage['batch_from']
    ref_stage_type = stage_types.get(batch_from, 'vasp')

    # Use ascending delta_n so generated CHGCAR filenames match CHGCAR_0.00, ...
    sorted_items = sorted(
        ((label, float(delta_n)) for label, delta_n in stage['delta_n_map'].items()),
        key=lambda item: item[1],
    )
    labels = [item[0] for item in sorted_items]
    delta_n_values = [item[1] for item in sorted_items]

    if ref_stage_type == 'batch':
        batch_result = stage_tasks[batch_from]
        calc_tasks = batch_result.get('calc_tasks')
        if not calc_tasks:
            raise ValueError(
                f"Fukui analysis stage '{stage_name}': stage '{batch_from}' "
                f"does not have batch calc_tasks"
            )
        missing_labels = [lbl for lbl in labels if lbl not in calc_tasks]
        if missing_labels:
            raise ValueError(
                f"Fukui analysis stage '{stage_name}': labels {missing_labels} "
                f"not found in batch stage '{batch_from}' calculations"
            )
        retrieved_sockets = [calc_tasks[lbl].outputs.retrieved for lbl in labels]

    elif ref_stage_type == 'fukui_dynamic':
        # fukui_dynamic exposes 8 sockets: retrieved_{minus,plus}_{neutral,delta_005,...}
        # delta_n_map keys must be exactly the four fractional-offset labels.
        expected_labels = {'neutral', 'delta_005', 'delta_010', 'delta_015'}
        provided_labels = set(stage['delta_n_map'].keys())
        if provided_labels != expected_labels:
            raise ValueError(
                f"Fukui analysis stage '{stage_name}': when batch_from references "
                f"a fukui_dynamic stage, delta_n_map keys must be exactly "
                f"{sorted(expected_labels)}, got {sorted(provided_labels)}"
            )
        fukui_type = stage['fukui_type']  # 'plus' or 'minus'
        dyn_result = stage_tasks[batch_from]
        socket_keys = [f'retrieved_{fukui_type}_{lbl}' for lbl in labels]
        missing = [k for k in socket_keys if k not in dyn_result]
        if missing:
            raise ValueError(
                f"Fukui analysis stage '{stage_name}': fukui_dynamic stage "
                f"'{batch_from}' is missing output sockets: {missing}"
            )
        retrieved_sockets = [dyn_result[k] for k in socket_keys]

    else:
        raise ValueError(
            f"Fukui analysis stage '{stage_name}' batch_from='{batch_from}' "
            f"must reference a 'batch' or 'fukui_dynamic' stage "
            f"(got type='{ref_stage_type}')"
        )

    collect_task = wg.add_task(
        collect_chgcar_files_internal,
        name=f'collect_chgcar_{stage_name}',
        delta_n_list=orm.List(list=delta_n_values),
        labels_list=orm.List(list=labels),
        retrieved_0=retrieved_sockets[0],
        retrieved_1=retrieved_sockets[1],
        retrieved_2=retrieved_sockets[2],
        retrieved_3=retrieved_sockets[3],
    )

    interpolation_task = wg.add_task(
        run_fukui_interpolation_calcfunc,
        name=f'fukui_interp_{stage_name}',
        chgcar_files=collect_task.outputs.result,
        delta_n_values=orm.List(list=delta_n_values),
        fukui_type=orm.Str(stage['fukui_type']),
    )

    return {
        'collect': collect_task,
        'interpolation': interpolation_task,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose fukui_analysis stage outputs on the WorkGraph."""
    interpolation_task = stage_tasks_result['interpolation']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(
            wg.outputs,
            f'{ns}.fukui_analysis.fukui_chgcar',
            interpolation_task.outputs.result,
        )
    else:
        setattr(
            wg.outputs,
            f'{stage_name}_fukui_chgcar',
            interpolation_task.outputs.result,
        )


def get_stage_results(wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from a fukui_analysis stage."""
    result = {
        'fukui_chgcar': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'fukui_analysis',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'fukui_analysis', None) if stage_ns is not None else None
            if brick_ns is not None and hasattr(brick_ns, 'fukui_chgcar'):
                result['fukui_chgcar'] = brick_ns.fukui_chgcar
        else:
            output_attr = f'{stage_name}_fukui_chgcar'
            if hasattr(outputs, output_attr):
                result['fukui_chgcar'] = getattr(outputs, output_attr)

    if result['fukui_chgcar'] is None:
        _extract_fukui_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_fukui_stage_from_workgraph(wg_node, stage_name: str, result: dict) -> None:
    """Extract fukui_analysis stage outputs by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'fukui_interp_{stage_name}'

    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if task_name in link_label or link_label == task_name:
            created = child_node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result':
                    result['fukui_chgcar'] = out_link.node
                    return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a fukui_analysis stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="fukui_analysis")

    fukui_file = stage_result.get('fukui_chgcar')
    if fukui_file is not None:
        filename = getattr(fukui_file, 'filename', 'CHGCAR_FUKUI.vasp')
        console.print(
            f"      [bold]Fukui CHGCAR:[/bold] {filename} "
            f"(PK [pk]{fukui_file.pk}[/pk])"
        )
