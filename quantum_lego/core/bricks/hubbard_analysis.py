"""Hubbard analysis brick for the lego module.

Pure computation brick (no VASP). Takes gathered responses from a
hubbard_response stage and performs linear regression to calculate
the Hubbard U parameter.

Reference: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
"""

from aiida import orm
from aiida.common.links import LinkType

from .connections import HUBBARD_ANALYSIS_PORTS as PORTS  # noqa: F401

from quantum_lego.core.common.u_calculation.tasks import (
    calculate_hubbard_u_linear_regression,
    compile_u_calculation_summary,
)


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a hubbard_analysis stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'response_from' not in stage:
        raise ValueError(
            f"Stage '{name}': hubbard_analysis stages require 'response_from' "
            f"(name of the hubbard_response stage)"
        )

    response_from = stage['response_from']
    if response_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' response_from='{response_from}' must be "
            f"a previous stage name"
        )

    if 'target_species' not in stage:
        raise ValueError(
            f"Stage '{name}': hubbard_analysis stages require 'target_species' "
            f"(element symbol, e.g., 'Ni', 'Fe')"
        )

    # structure_from is required (for summary compilation)
    if 'structure_from' not in stage:
        raise ValueError(
            f"Stage '{name}': hubbard_analysis stages require 'structure_from' "
            f"('input' or a previous stage name)"
        )

    structure_from = stage['structure_from']
    if structure_from != 'input' and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must be 'input' "
            f"or a previous stage name"
        )

    # Validate ldaul if provided
    ldaul = stage.get('ldaul', 2)
    if ldaul not in (2, 3):
        raise ValueError(
            f"Stage '{name}' ldaul={ldaul} must be 2 (d-electrons) or "
            f"3 (f-electrons)"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create hubbard_analysis stage tasks in the WorkGraph.

    This creates:
    1. Linear regression from gathered responses
    2. Summary compilation

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    input_structure = context['input_structure']
    stage_tasks = context['stage_tasks']

    target_species = stage['target_species']
    ldaul = stage.get('ldaul', 2)

    # Resolve input structure
    structure_from = stage['structure_from']
    if structure_from == 'input':
        stage_structure = input_structure
    else:
        from . import resolve_structure_from
        stage_structure = resolve_structure_from(structure_from, context)

    # Get outputs from the referenced response stage
    response_from = stage['response_from']
    gathered_responses = stage_tasks[response_from]['responses'].outputs.result
    gs_occupation = stage_tasks[response_from]['gs_occupation'].outputs.result

    # Linear regression
    calc_u = wg.add_task(
        calculate_hubbard_u_linear_regression,
        name=f'calc_u_{stage_name}',
        responses=gathered_responses,
    )

    # Compile summary
    summary = wg.add_task(
        compile_u_calculation_summary,
        name=f'summary_{stage_name}',
        hubbard_u_result=calc_u.outputs.result,
        ground_state_occupation=gs_occupation,
        structure=stage_structure,
        target_species=orm.Str(target_species),
        ldaul=orm.Int(ldaul),
    )

    return {
        'calc_u': calc_u,
        'summary': summary,
        'structure': stage_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose hubbard_analysis stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    summary = stage_tasks_result['summary']
    calc_u = stage_tasks_result['calc_u']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.hubbard_analysis.summary',
                summary.outputs.result)
        setattr(wg.outputs, f'{ns}.hubbard_analysis.hubbard_u_result',
                calc_u.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_summary',
                summary.outputs.result)
        setattr(wg.outputs, f'{stage_name}_hubbard_u_result',
                calc_u.outputs.result)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a hubbard_analysis stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: summary, hubbard_u_eV, target_species, chi_r2,
        chi_0_r2, response_data, pk, stage, type.
    """
    result = {
        'summary': None,
        'hubbard_u_eV': None,
        'target_species': None,
        'chi_r2': None,
        'chi_0_r2': None,
        'response_data': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'hubbard_analysis',
    }

    summary_node = None

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'hubbard_analysis', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'summary'):
                    summary_node = brick_ns.summary
        else:
            summary_attr = f'{stage_name}_summary'
            if hasattr(outputs, summary_attr):
                summary_node = getattr(outputs, summary_attr)

    if summary_node is not None and hasattr(summary_node, 'get_dict'):
        summary_dict = summary_node.get_dict()
        result['summary'] = summary_dict
        if 'summary' in summary_dict:
            result['hubbard_u_eV'] = summary_dict['summary'].get(
                'hubbard_u_eV')
            result['target_species'] = summary_dict['summary'].get(
                'target_species')
        if 'linear_fit' in summary_dict:
            lf = summary_dict['linear_fit']
            result['chi_r2'] = lf.get('chi_scf', {}).get('r_squared')
            result['chi_0_r2'] = lf.get('chi_0_nscf', {}).get(
                'r_squared')
        if 'response_data' in summary_dict:
            result['response_data'] = summary_dict['response_data']

    # Fallback: traverse links
    if result['summary'] is None:
        _extract_analysis_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_analysis_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract analysis stage results by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    summary_task_name = f'summary_{stage_name}'

    called_calc = wg_node.base.links.get_outgoing(
        link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if summary_task_name in link_label or link_label == summary_task_name:
            created = child_node.base.links.get_outgoing(
                link_type=LinkType.CREATE)
            for out_link in created.all():
                out_label = out_link.link_label
                out_node = out_link.node

                if out_label == 'result' and hasattr(out_node, 'get_dict'):
                    summary_dict = out_node.get_dict()
                    result['summary'] = summary_dict
                    if 'summary' in summary_dict:
                        result['hubbard_u_eV'] = summary_dict['summary'].get(
                            'hubbard_u_eV')
                        result['target_species'] = summary_dict[
                            'summary'].get('target_species')
                    if 'linear_fit' in summary_dict:
                        lf = summary_dict['linear_fit']
                        result['chi_r2'] = lf.get('chi_scf', {}).get(
                            'r_squared')
                        result['chi_0_r2'] = lf.get('chi_0_nscf', {}).get(
                            'r_squared')
                    if 'response_data' in summary_dict:
                        result['response_data'] = summary_dict['response_data']
            break


def print_stage_results(
    index: int, stage_name: str, stage_result: dict
) -> None:
    """Print formatted results for a hubbard_analysis stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="hubbard_analysis")

    if stage_result['hubbard_u_eV'] is not None:
        console.print(f"      [bold]U =[/bold] [energy]{stage_result['hubbard_u_eV']:.3f}[/energy] eV")

    if stage_result['target_species'] is not None:
        console.print(f"      [bold]Target:[/bold] [cyan]{stage_result['target_species']}[/cyan]")

    if stage_result['chi_r2'] is not None:
        console.print(f"      [bold]SCF fit R²:[/bold] {stage_result['chi_r2']:.6f}")

    if stage_result['chi_0_r2'] is not None:
        console.print(f"      [bold]NSCF fit R²:[/bold] {stage_result['chi_0_r2']:.6f}")

    if stage_result['response_data'] is not None:
        rd = stage_result['response_data']
        potentials = rd.get('potential_values_eV', [])
        if potentials:
            potentials_str = ', '.join(f"[energy]{p:.3f}[/energy]" for p in potentials)
            console.print(f"      [bold]Potentials:[/bold] {potentials_str} eV")

    if stage_result['summary'] is not None:
        summary = stage_result['summary']
        gs = summary.get('ground_state', {})
        avg_d = gs.get('average_d_per_atom')
        if avg_d is not None:
            species = stage_result['target_species'] or '?'
            console.print(f"      [bold]Avg d-occupation per {species}:[/bold] [energy]{avg_d:.3f}[/energy]")
