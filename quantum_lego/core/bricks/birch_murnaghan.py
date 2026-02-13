"""Birch-Murnaghan EOS analysis brick for the lego module.

Pure computation brick (no VASP). Takes energy outputs from a previous
batch stage and fits a Birch-Murnaghan equation of state to the
volume-energy data using pymatgen's EOS class.
"""

from typing import Any, Dict, Set

from aiida import orm
from aiida.common.links import LinkType

from .connections import BIRCH_MURNAGHAN_PORTS as PORTS  # noqa: F401

from quantum_lego.core.common.eos_tasks import (
    gather_eos_data,
    fit_birch_murnaghan_eos,
)


def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate a birch_murnaghan stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'batch_from' not in stage:
        raise ValueError(
            f"Stage '{name}': birch_murnaghan stages require 'batch_from' "
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

    volumes = stage.get('volumes')
    if not isinstance(volumes, dict):
        raise ValueError(
            f"Stage '{name}': birch_murnaghan stages require 'volumes' dict "
            f"mapping calc_label to volume in Angstrom^3"
        )
    if len(volumes) < 4:
        raise ValueError(
            f"Stage '{name}': volumes must have at least 4 entries "
            f"(got {len(volumes)})"
        )
    for label, vol in volumes.items():
        if not isinstance(label, str):
            raise ValueError(
                f"Stage '{name}': volumes keys must be strings "
                f"(got {type(label)})"
            )
        if not isinstance(vol, (int, float)):
            raise ValueError(
                f"Stage '{name}': volumes['{label}'] must be numeric"
            )
        if float(vol) <= 0.0:
            raise ValueError(
                f"Stage '{name}': volumes['{label}'] must be positive "
                f"(got {vol})"
            )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create birch_murnaghan stage tasks in the WorkGraph.

    This creates:
    1. gather_eos_data: collects volume-energy pairs from batch
    2. fit_birch_murnaghan_eos: fits the EOS

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    batch_from = stage['batch_from']
    ref_stage_type = stage_types.get(batch_from, 'vasp')
    if ref_stage_type != 'batch':
        raise ValueError(
            f"Birch-Murnaghan stage '{stage_name}' batch_from='{batch_from}' "
            f"must reference a batch stage (got type='{ref_stage_type}')"
        )

    batch_result = stage_tasks[batch_from]
    energy_tasks = batch_result.get('energy_tasks')
    if not energy_tasks:
        raise ValueError(
            f"Birch-Murnaghan stage '{stage_name}': stage '{batch_from}' "
            f"does not have batch energy_tasks"
        )

    volumes = stage['volumes']

    # Validate labels match batch calculations
    missing_labels = [label for label in volumes if label not in energy_tasks]
    if missing_labels:
        raise ValueError(
            f"Birch-Murnaghan stage '{stage_name}': labels {missing_labels} "
            f"not found in batch stage '{batch_from}' calculations"
        )

    # Sort by label for deterministic ordering
    sorted_labels = sorted(volumes.keys())
    sorted_volumes = [float(volumes[label]) for label in sorted_labels]

    # Build energy kwargs for gather task
    energy_kwargs = {}
    for label in sorted_labels:
        energy_kwargs[label] = energy_tasks[label].outputs.result

    # Create gather task
    gather_task = wg.add_task(
        gather_eos_data,
        name=f'gather_eos_{stage_name}',
        volumes=orm.List(list=sorted_volumes),
        labels=orm.List(list=sorted_labels),
        **energy_kwargs,
    )

    # Create fit task
    fit_task = wg.add_task(
        fit_birch_murnaghan_eos,
        name=f'fit_bm_{stage_name}',
        eos_data=gather_task.outputs.result,
    )

    return {
        'gather': gather_task,
        'fit': fit_task,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose birch_murnaghan stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    fit_task = stage_tasks_result['fit']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(
            wg.outputs,
            f'{ns}.birch_murnaghan.eos_result',
            fit_task.outputs.result,
        )
    else:
        setattr(
            wg.outputs,
            f'{stage_name}_eos_result',
            fit_task.outputs.result,
        )


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a birch_murnaghan stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: eos_result, v0, e0, b0_GPa, b1, n_points,
        rms_residual_eV, pk, stage, type.
    """
    result = {
        'eos_result': None,
        'v0': None,
        'e0': None,
        'b0_GPa': None,
        'b1': None,
        'n_points': None,
        'rms_residual_eV': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'birch_murnaghan',
    }

    eos_node = None

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'birch_murnaghan', None) if stage_ns is not None else None
            if brick_ns is not None and hasattr(brick_ns, 'eos_result'):
                eos_node = brick_ns.eos_result
        else:
            output_attr = f'{stage_name}_eos_result'
            if hasattr(outputs, output_attr):
                eos_node = getattr(outputs, output_attr)

    if eos_node is not None and hasattr(eos_node, 'get_dict'):
        eos_dict = eos_node.get_dict()
        result['eos_result'] = eos_dict
        result['v0'] = eos_dict.get('v0')
        result['e0'] = eos_dict.get('e0')
        result['b0_GPa'] = eos_dict.get('b0_GPa')
        result['b1'] = eos_dict.get('b1')
        result['n_points'] = eos_dict.get('n_points')
        result['rms_residual_eV'] = eos_dict.get('rms_residual_eV')

    # Fallback: traverse links
    if result['eos_result'] is None:
        _extract_bm_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_bm_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract birch_murnaghan stage results by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'fit_bm_{stage_name}'

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
                    return


def print_stage_results(
    index: int, stage_name: str, stage_result: dict
) -> None:
    """Print formatted results for a birch_murnaghan stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="birch_murnaghan")

    if stage_result['v0'] is not None:
        console.print(f"      [bold]V0:[/bold] [energy]{stage_result['v0']:.4f}[/energy] A^3")

    if stage_result['e0'] is not None:
        console.print(f"      [bold]E0:[/bold] [energy]{stage_result['e0']:.6f}[/energy] eV")

    if stage_result['b0_GPa'] is not None:
        console.print(f"      [bold]B0:[/bold] [energy]{stage_result['b0_GPa']:.2f}[/energy] GPa")

    if stage_result['b1'] is not None:
        console.print(f"      [bold]B0':[/bold] [energy]{stage_result['b1']:.2f}[/energy]")

    if stage_result['n_points'] is not None:
        console.print(f"      [bold]Data points:[/bold] {stage_result['n_points']}")

    if stage_result['rms_residual_eV'] is not None:
        console.print(f"      [bold]RMS residual:[/bold] [energy]{stage_result['rms_residual_eV']:.2e}[/energy] eV")

    # Print V/E table
    eos = stage_result.get('eos_result')
    if eos is not None:
        volumes = eos.get('volumes', [])
        energies = eos.get('energies', [])
        if volumes and energies:
            console.print("      [bold]V/E data:[/bold]")
            for v, e in zip(volumes, energies):
                console.print(f"        V = {v:.4f} A^3  E = [energy]{e:.6f}[/energy] eV")
