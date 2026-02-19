"""Select the most stable surface termination from a surface_gibbs_energy summary.

Finds the termination with minimum φ = γ(ΔμM=0, ΔμO=0) and returns the
corresponding relaxed slab StructureData from the upstream dynamic_batch stage.

This brick is a pure-Python post-processing step with no VASP calculation.
"""

from __future__ import annotations

import typing as t

from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import dynamic, task

from .connections import SELECT_STABLE_SURFACE_PORTS as PORTS  # noqa: F401


@task.calcfunction
def select_min_phi_label(summary: orm.Dict) -> orm.Str:
    """Find the termination label with minimum φ from a surface_gibbs_energy summary.

    The summary Dict is produced by gather_surface_gibbs_energies and has the
    structure::

        {
            'oxide_type': 'ternary',
            'surface_energies': {
                '<label>': {
                    'primary': {'phi': float, ...},
                    ...
                },
                ...
            }
        }

    For binary oxides the 'primary' sub-dict is also present.  The selection
    criterion is the smallest ``primary['phi']`` value, which equals γ at
    ΔμM = 0 and ΔμO = 0 simultaneously.
    """
    data = summary.get_dict()
    surface_energies = data.get('surface_energies', {})

    min_label: str | None = None
    min_phi = float('inf')

    for label, term_data in surface_energies.items():
        if not isinstance(term_data, dict):
            continue
        primary = term_data.get('primary', term_data)
        phi = primary.get('phi') if isinstance(primary, dict) else None
        if phi is not None and float(phi) < min_phi:
            min_phi = float(phi)
            min_label = label

    if min_label is None:
        raise ValueError(
            'No valid phi values found in surface_gibbs_energy summary. '
            f'Available keys: {list(surface_energies.keys())}'
        )

    return orm.Str(min_label)


@task.calcfunction
def pick_structure_by_label(label: orm.Str, **structures) -> orm.StructureData:
    """Return the StructureData whose dict key matches label.

    The **structures kwargs are the individual relaxed slab StructureData nodes
    unpacked from the upstream dynamic_batch namespace.
    """
    key = label.value
    if key not in structures:
        raise KeyError(
            f"Selected label '{key}' not found in available structures. "
            f"Available: {sorted(structures.keys())}"
        )
    struct = structures[key]
    if not isinstance(struct, orm.StructureData):
        raise TypeError(
            f"Expected StructureData for label '{key}', got {type(struct)}"
        )
    # Clone to create a new node: calcfunctions cannot return an already-stored
    # node (it would violate the "one incoming CREATE link" AiiDA constraint).
    return struct.clone()


@task.graph
def run_select_stable_surface(
    structures: t.Annotated[dict[str, orm.StructureData], dynamic(orm.StructureData)],
    summary: orm.Dict,
) -> orm.StructureData:
    """Select the slab structure with lowest φ at ΔμM=0, ΔμO=0.

    Runs two calcfunctions in sequence:
      1. select_min_phi_label  – identifies the winning label from the summary
      2. pick_structure_by_label – returns that structure from the dynamic namespace
    """
    label_result = select_min_phi_label(summary=summary)

    struct_kwargs: dict[str, t.Any] = {'label': label_result.result}
    for key, struct in structures.items():
        struct_kwargs[key] = struct

    selected = pick_structure_by_label(**struct_kwargs)
    return selected.result


# ---------------------------------------------------------------------------
# Brick interface
# ---------------------------------------------------------------------------

def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a select_stable_surface stage configuration."""
    name = stage['name']
    for key in ('summary_from', 'structures_from'):
        if key not in stage:
            raise ValueError(
                f"Stage '{name}': select_stable_surface stages require '{key}'"
            )
        ref = stage[key]
        if ref not in stage_names:
            raise ValueError(
                f"Stage '{name}': {key}='{ref}' must reference a previous stage name"
            )
        if ref == name:
            raise ValueError(
                f"Stage '{name}': {key} cannot reference itself"
            )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create select_stable_surface stage tasks in the WorkGraph."""
    stage_tasks = context['stage_tasks']

    # Summary from surface_gibbs_energy stage
    summary_from = stage['summary_from']
    gibbs_tasks = stage_tasks.get(summary_from, {})
    summary_task = gibbs_tasks.get('summary')
    if summary_task is None:
        raise ValueError(
            f"Stage '{stage_name}': summary_from='{summary_from}' does not "
            f"provide a 'summary' task (expected a surface_gibbs_energy stage)"
        )

    # Relaxed structures from dynamic_batch stage
    structures_from = stage['structures_from']
    dyn_tasks = stage_tasks.get(structures_from, {})
    structures_socket = dyn_tasks.get('structures')
    if structures_socket is None:
        raise ValueError(
            f"Stage '{stage_name}': structures_from='{structures_from}' does not "
            f"provide a 'structures' output (expected a dynamic_batch stage)"
        )

    task_node = wg.add_task(
        run_select_stable_surface,
        name=f'select_stable_{stage_name}',
        structures=structures_socket,
        summary=summary_task.outputs.result,
    )

    return {
        'graph': task_node,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose select_stable_surface outputs on the WorkGraph."""
    task_node = stage_tasks_result['graph']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(
            wg.outputs,
            f'{ns}.select_stable_surface.structure',
            task_node.outputs.result,
        )
    else:
        setattr(
            wg.outputs,
            f'{stage_name}_selected_structure',
            task_node.outputs.result,
        )


def get_stage_results(wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from a select_stable_surface stage."""
    result = {
        'selected_structure': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'select_stable_surface',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'select_stable_surface', None) if stage_ns is not None else None
            if brick_ns is not None and hasattr(brick_ns, 'structure'):
                result['selected_structure'] = brick_ns.structure
        else:
            attr = f'{stage_name}_selected_structure'
            if hasattr(outputs, attr):
                result['selected_structure'] = getattr(outputs, attr)

    if result['selected_structure'] is None:
        _extract_from_links(wg_node, stage_name, result)

    return result


def _extract_from_links(wg_node, stage_name: str, result: dict) -> None:
    """Fallback: traverse WorkGraph links to find the selected StructureData."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'pick_structure_by_label_{stage_name}'
    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if task_name in link_label or link_label == task_name:
            created = child_node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result':
                    result['selected_structure'] = out_link.node
                    return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a select_stable_surface stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="select_stable_surface")

    struct = stage_result.get('selected_structure')
    if struct is not None:
        formula = getattr(struct, 'get_formula', lambda: 'N/A')()
        pk = getattr(struct, 'pk', None)
        console.print(
            f"      [bold]Selected structure:[/bold] {formula} "
            f"(PK [pk]{pk}[/pk])"
        )
    else:
        console.print("      [dim]Selected structure: not yet available[/dim]")
