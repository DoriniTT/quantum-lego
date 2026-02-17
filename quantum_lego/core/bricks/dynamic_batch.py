"""Dynamic batch brick for the lego module.

Runs the same VASP settings on a dynamically generated dictionary of structures.

This is intended for fan-out workflows where the structures are only known at
runtime (e.g. surface terminations generated from a relaxed bulk).
"""

from __future__ import annotations

import logging
import typing as t

from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import task, dynamic, namespace, get_current_graph

from .connections import DYNAMIC_BATCH_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_max_jobs_value, extract_total_energy


@task.graph
def run_dynamic_batch(
    structures: t.Annotated[dict[str, orm.StructureData], dynamic(orm.StructureData)],
    code_pk: int,
    potential_family: str,
    potential_mapping: dict,
    base_incar: dict,
    options: dict,
    kpoints_spacing: float = None,
    kpoints_mesh: list[int] | None = None,
    retrieve: list[str] | None = None,
    clean_workdir: bool = False,
    max_number_jobs: int | None = None,
) -> t.Annotated[
    dict,
    namespace(
        structures=dynamic(orm.StructureData),
        energies=dynamic(orm.Float),
    ),
]:
    """Relax all structures in parallel using scatter-gather pattern."""
    from aiida.plugins import WorkflowFactory

    from ..workgraph import _prepare_builder_inputs

    # Set max_number_jobs on this sub-graph (WorkGraph does not inherit this).
    if max_number_jobs is not None:
        wg = get_current_graph()
        wg.max_number_jobs = extract_max_jobs_value(max_number_jobs)

    code = orm.load_node(code_pk)

    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Shared builder inputs for all calculations
    builder_inputs = _prepare_builder_inputs(
        incar=dict(base_incar),
        kpoints_spacing=float(kpoints_spacing) if kpoints_spacing is not None else 0.03,
        potential_family=potential_family,
        potential_mapping=dict(potential_mapping),
        options=dict(options),
        retrieve=retrieve,
        restart_folder=None,
        clean_workdir=clean_workdir,
        kpoints_mesh=kpoints_mesh,
    )

    relaxed_structures: dict[str, orm.StructureData] = {}
    energies_out: dict[str, orm.Float] = {}

    for label, structure in structures.items():
        vasp_task = VaspTask(
            structure=structure,
            code=code,
            **builder_inputs,
        )
        relaxed_structures[label] = vasp_task.structure
        energies_out[label] = extract_total_energy(
            energies=vasp_task.misc, retrieved=vasp_task.retrieved
        ).result

    return {
        'structures': relaxed_structures,
        'energies': energies_out,
    }


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a dynamic_batch stage configuration."""
    name = stage['name']

    if 'structures_from' not in stage:
        raise ValueError(
            f"Stage '{name}': dynamic_batch stages require 'structures_from'"
        )

    structures_from = stage['structures_from']
    if structures_from == 'input':
        raise ValueError(
            f"Stage '{name}': structures_from='input' is not supported for dynamic_batch "
            f"(it expects a previous stage producing multiple structures)."
        )
    if structures_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structures_from='{structures_from}' must reference "
            f"a previous stage name"
        )

    if 'base_incar' not in stage or not isinstance(stage['base_incar'], dict):
        raise ValueError(
            f"Stage '{name}': dynamic_batch stages require 'base_incar' dict"
        )

    if 'kpoints' in stage:
        kpts = stage['kpoints']
        if not isinstance(kpts, (list, tuple)) or len(kpts) != 3 or not all(
            isinstance(x, int) and x > 0 for x in kpts
        ):
            raise ValueError(
                f"Stage '{name}': kpoints must be [nx, ny, nz] positive ints, got {kpts!r}"
            )

    if 'kpoints_spacing' in stage:
        ks = stage['kpoints_spacing']
        if not isinstance(ks, (int, float)) or float(ks) <= 0:
            raise ValueError(
                f"Stage '{name}': kpoints_spacing must be a positive number, got {ks!r}"
            )

    if 'retrieve' in stage and stage['retrieve'] is not None:
        if not isinstance(stage['retrieve'], (list, tuple)) or not all(
            isinstance(x, str) for x in stage['retrieve']
        ):
            raise ValueError(
                f"Stage '{name}': retrieve must be a list of strings, got {stage['retrieve']!r}"
            )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create dynamic_batch stage tasks in the WorkGraph."""
    stage_tasks = context['stage_tasks']

    structures_from = stage['structures_from']
    upstream = stage_tasks.get(structures_from, {})
    if 'structures' not in upstream:
        raise ValueError(
            f"Stage '{stage_name}': structures_from='{structures_from}' does not provide "
            f"a 'structures' output for dynamic_batch."
        )

    structures_socket = upstream['structures']

    kpoints_spacing = stage.get('kpoints_spacing', context['base_kpoints_spacing'])
    kpoints_mesh = stage.get('kpoints', None)
    retrieve = stage.get('retrieve', None)

    # Inherit concurrency from parent WorkGraph unless explicitly overridden.
    max_jobs = stage.get('max_number_jobs', None)
    if max_jobs is None:
        max_jobs = getattr(wg, 'max_number_jobs', None)

    task_node = wg.add_task(
        run_dynamic_batch,
        name=f'dynamic_batch_{stage_name}',
        structures=structures_socket,
        code_pk=context['code'].pk,
        potential_family=context['potential_family'],
        potential_mapping=context['potential_mapping'],
        base_incar=stage['base_incar'],
        options=context['options'],
        kpoints_spacing=kpoints_spacing,
        kpoints_mesh=kpoints_mesh,
        retrieve=retrieve,
        clean_workdir=context['clean_workdir'],
        max_number_jobs=max_jobs,
    )

    return {
        'dynamic_batch': task_node,
        'structures': task_node.outputs.structures,
        'energies': task_node.outputs.energies,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose dynamic_batch stage outputs on the WorkGraph."""
    task_node = stage_tasks_result['dynamic_batch']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.dynamic_batch.structures', task_node.outputs.structures)
        setattr(wg.outputs, f'{ns}.dynamic_batch.energies', task_node.outputs.energies)
    else:
        setattr(wg.outputs, f'{stage_name}_structures', task_node.outputs.structures)
        setattr(wg.outputs, f'{stage_name}_energies', task_node.outputs.energies)


def get_stage_results(wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from a dynamic_batch stage."""
    result = {
        'calculations': {},
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'dynamic_batch',
    }

    # Best-effort extraction from exposed outputs (dynamic namespaces).
    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        energies_ns = None
        structures_ns = None

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'dynamic_batch', None) if stage_ns is not None else None
            if brick_ns is not None:
                energies_ns = getattr(brick_ns, 'energies', None)
                structures_ns = getattr(brick_ns, 'structures', None)
        else:
            energies_ns = getattr(outputs, f'{stage_name}_energies', None)
            structures_ns = getattr(outputs, f'{stage_name}_structures', None)

        if energies_ns is not None and structures_ns is not None:
            for label in dir(energies_ns):
                if label.startswith('_'):
                    continue
                energy_node = getattr(energies_ns, label, None)
                struct_node = getattr(structures_ns, label, None)
                if energy_node is None or struct_node is None:
                    continue

                energy_val = None
                try:
                    if hasattr(energy_node, 'value'):
                        energy_val = float(energy_node.value)
                    else:
                        energy_val = float(energy_node)
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Could not extract energy for label '%s' in stage '%s'",
                        label, stage_name,
                    )
                    energy_val = None

                result['calculations'][label] = {
                    'energy': energy_val,
                    'structure': struct_node,
                }

    if not result['calculations']:
        _extract_from_links(wg_node, stage_name, result)

    return result


def _extract_from_links(wg_node, stage_name: str, result: dict) -> None:
    """Fallback: traverse WorkGraph links to find VASP child calculations."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'dynamic_batch_{stage_name}'
    called_work = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called_work.all():
        if task_name not in link.link_label:
            continue
        # Best-effort: do not attempt deep traversal here (dynamic outputs).
        # The exposed outputs path should work on finished WorkGraphs.
        return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a dynamic_batch stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="dynamic_batch")

    calcs = stage_result.get('calculations') or {}
    console.print(f"      [bold]Relaxations:[/bold] {len(calcs)}")
    if calcs:
        # Print first few energies for quick sanity.
        preview = []
        for label in sorted(calcs.keys())[:5]:
            e = calcs[label].get('energy')
            preview.append(f"{label}: {e:.6f} eV" if e is not None else f"{label}: (energy unavailable)")
        console.print(f"      [bold]Preview:[/bold] [dim]{'; '.join(preview)}[/dim]")

