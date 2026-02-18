"""Fukui dynamic batch brick for the lego module.

Runs eight VASP static calculations on a single slab structure — four for
f−(r) and four for f+(r) — using fractional electron offsets of 0.00, 0.05,
0.10, and 0.15 electrons relative to the neutral count.

NELECT is computed at runtime from the structure using the actual POTCAR data
stored in AiiDA (via ``teros.core.fukui.calculate_nelect``), so no prior
knowledge of the electron count is needed.

Output sockets
--------------
  retrieved_minus_neutral / delta_005 / delta_010 / delta_015  →  f−
  retrieved_plus_neutral  / delta_005 / delta_010 / delta_015  →  f+

These are consumed directly by ``fukui_analysis`` stages via
``batch_from='<this stage>'`` and
``delta_n_map = {'neutral': 0.00, 'delta_005': 0.05, 'delta_010': 0.10, 'delta_015': 0.15}``.
"""

from __future__ import annotations

import typing as t

from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import get_current_graph, namespace, task

from .connections import FUKUI_DYNAMIC_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_max_jobs_value


# ---------------------------------------------------------------------------
# Calculation table:  (group, label, signed_offset)
# ---------------------------------------------------------------------------

_FUKUI_CALCS: list[tuple[str, str, float]] = [
    ('minus', 'neutral',   0.00),
    ('minus', 'delta_005', -0.05),
    ('minus', 'delta_010', -0.10),
    ('minus', 'delta_015', -0.15),
    ('plus',  'neutral',    0.00),
    ('plus',  'delta_005', +0.05),
    ('plus',  'delta_010', +0.10),
    ('plus',  'delta_015', +0.15),
]


# ---------------------------------------------------------------------------
# NELECT calcfunction
# ---------------------------------------------------------------------------

@task.calcfunction
def compute_nelect_from_potcar(
    structure: orm.StructureData,
    potential_family: orm.Str,
    potential_mapping: orm.Dict,
) -> orm.Int:
    """Compute total valence electron count from POTCAR data stored in AiiDA."""
    from teros.core.fukui import calculate_nelect

    nelect = calculate_nelect(
        structure=structure,
        potential_family=potential_family.value,
        potential_mapping=potential_mapping.get_dict(),
    )
    return orm.Int(nelect)


# ---------------------------------------------------------------------------
# Batch @task.graph
# ---------------------------------------------------------------------------

@task.graph
def run_fukui_batch(
    structure: orm.StructureData,
    nelect_base: int,
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
        retrieved_minus_neutral=orm.FolderData,
        retrieved_minus_delta_005=orm.FolderData,
        retrieved_minus_delta_010=orm.FolderData,
        retrieved_minus_delta_015=orm.FolderData,
        retrieved_plus_neutral=orm.FolderData,
        retrieved_plus_delta_005=orm.FolderData,
        retrieved_plus_delta_010=orm.FolderData,
        retrieved_plus_delta_015=orm.FolderData,
    ),
]:
    """Run 8 VASP static calculations with fractional NELECT offsets.

    Four calculations for f−: dN ∈ {0.00, −0.05, −0.10, −0.15}.
    Four calculations for f+: dN ∈ {0.00, +0.05, +0.10, +0.15}.

    The neutral calculation (dN = 0.00) is run twice — once in each group —
    so that each ``fukui_analysis`` stage receives a self-contained set of
    four retrieved folders with a consistent reference.
    """
    from aiida.plugins import WorkflowFactory

    from ..workgraph import _prepare_builder_inputs

    if max_number_jobs is not None:
        wg = get_current_graph()
        wg.max_number_jobs = extract_max_jobs_value(max_number_jobs)

    code = orm.load_node(code_pk)
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    results: dict[str, t.Any] = {}
    for group, label, offset in _FUKUI_CALCS:
        incar_copy = dict(base_incar)
        incar_copy['nelect'] = nelect_base + offset

        builder_inputs = _prepare_builder_inputs(
            incar=incar_copy,
            kpoints_spacing=float(kpoints_spacing) if kpoints_spacing is not None else 0.05,
            potential_family=potential_family,
            potential_mapping=dict(potential_mapping),
            options=dict(options),
            retrieve=retrieve,
            restart_folder=None,
            clean_workdir=clean_workdir,
            kpoints_mesh=kpoints_mesh,
        )

        vasp_task = VaspTask(
            structure=structure,
            code=code,
            **builder_inputs,
        )
        results[f'retrieved_{group}_{label}'] = vasp_task.retrieved

    return results


# ---------------------------------------------------------------------------
# Brick interface
# ---------------------------------------------------------------------------

def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a fukui_dynamic stage configuration."""
    name = stage['name']

    if 'base_incar' not in stage or not isinstance(stage['base_incar'], dict):
        raise ValueError(
            f"Stage '{name}': fukui_dynamic stages require 'base_incar' dict"
        )

    incar = stage['base_incar']
    if not incar.get('lcharg', False):
        raise ValueError(
            f"Stage '{name}': fukui_dynamic base_incar must have lcharg=True "
            f"(CHGCAR is required by fukui_analysis)"
        )

    if incar.get('nsw', 0) != 0:
        raise ValueError(
            f"Stage '{name}': fukui_dynamic base_incar must have nsw=0 "
            f"(static SCF only – geometry must not change between NELECT calculations)"
        )

    retrieve = stage.get('retrieve')
    if retrieve is not None and 'CHGCAR' not in retrieve:
        raise ValueError(
            f"Stage '{name}': 'retrieve' list must include 'CHGCAR' "
            f"when specified explicitly (got {retrieve!r})"
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


def create_stage_tasks(wg, stage, stage_name, context):
    """Create fukui_dynamic stage tasks in the WorkGraph."""
    from . import resolve_structure_from

    structure_from = stage.get('structure_from', 'previous')
    structure_socket = resolve_structure_from(structure_from, context)

    kpoints_spacing = stage.get('kpoints_spacing', context['base_kpoints_spacing'])
    kpoints_mesh = stage.get('kpoints', None)
    retrieve = stage.get('retrieve', None)

    max_jobs = stage.get('max_number_jobs', None)
    if max_jobs is None:
        max_jobs = getattr(wg, 'max_number_jobs', None)

    # Compute NELECT at runtime from actual POTCAR data
    nelect_task = wg.add_task(
        compute_nelect_from_potcar,
        name=f'compute_nelect_{stage_name}',
        structure=structure_socket,
        potential_family=orm.Str(context['potential_family']),
        potential_mapping=orm.Dict(context['potential_mapping']),
    )

    # Run 8 VASP calculations with fractional NELECT offsets
    task_node = wg.add_task(
        run_fukui_batch,
        name=f'fukui_dynamic_{stage_name}',
        structure=structure_socket,
        nelect_base=nelect_task.outputs.result,
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

    result = {
        'fukui_dynamic': task_node,
        'nelect_task': nelect_task,
    }
    for group, label, _ in _FUKUI_CALCS:
        key = f'retrieved_{group}_{label}'
        result[key] = getattr(task_node.outputs, key)

    return result


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose fukui_dynamic stage outputs on the WorkGraph."""
    task_node = stage_tasks_result['fukui_dynamic']

    for group, label, _ in _FUKUI_CALCS:
        output_attr = f'retrieved_{group}_{label}'
        socket = getattr(task_node.outputs, output_attr)

        if namespace_map is not None:
            ns = namespace_map['main']
            setattr(wg.outputs, f'{ns}.fukui_dynamic.{output_attr}', socket)
        else:
            setattr(wg.outputs, f'{stage_name}_{output_attr}', socket)


def get_stage_results(wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from a fukui_dynamic stage."""
    result = {
        'retrieved': {},
        'nelect': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'fukui_dynamic',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        for group, label, _ in _FUKUI_CALCS:
            output_attr = f'retrieved_{group}_{label}'
            if namespace_map is not None:
                ns = namespace_map['main']
                stage_ns = getattr(outputs, ns, None)
                brick_ns = getattr(stage_ns, 'fukui_dynamic', None) if stage_ns is not None else None
                if brick_ns is not None and hasattr(brick_ns, output_attr):
                    result['retrieved'][f'{group}_{label}'] = getattr(brick_ns, output_attr)
            else:
                wg_attr = f'{stage_name}_{output_attr}'
                if hasattr(outputs, wg_attr):
                    result['retrieved'][f'{group}_{label}'] = getattr(outputs, wg_attr)

    if not result['retrieved']:
        _extract_from_links(wg_node, stage_name, result)

    return result


def _extract_from_links(wg_node, stage_name: str, result: dict) -> None:
    """Fallback: traverse WorkGraph links to find the retrieved nodes."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'fukui_dynamic_{stage_name}'
    called_work = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called_work.all():
        if task_name not in link.link_label:
            continue
        # Best-effort: the exposed-outputs path should handle finished WorkGraphs.
        return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a fukui_dynamic stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="fukui_dynamic")

    retrieved = stage_result.get('retrieved') or {}
    nelect = stage_result.get('nelect')

    if nelect is not None:
        console.print(f"      [bold]NELECT base:[/bold] {nelect}")

    _LABELS = [
        ('neutral',   '±0.00'),
        ('delta_005', '±0.05'),
        ('delta_010', '±0.10'),
        ('delta_015', '±0.15'),
    ]
    for group in ('minus', 'plus'):
        sign = '−' if group == 'minus' else '+'
        for label, dn in _LABELS:
            key = f'{group}_{label}'
            node = retrieved.get(key)
            status = f"PK [pk]{node.pk}[/pk]" if node is not None else "pending"
            console.print(f"      [bold]f{sign} {label}:[/bold] dN={dn}  {status}")
