"""Surface termination generation brick for the lego module.

Pure-Python analysis brick (no VASP). Given a bulk structure and SlabGenerator
parameters, generates all symmetrized slab terminations for a given Miller index.
"""

from __future__ import annotations

import typing as t

from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import task, dynamic, namespace

from .connections import SURFACE_TERMINATIONS_PORTS as PORTS  # noqa: F401


@task.calcfunction
def generate_surface_terminations(
    bulk_structure: orm.StructureData,
    miller_indices: orm.List,
    min_slab_size: orm.Float,
    min_vacuum_size: orm.Float,
    lll_reduce: orm.Bool,
    center_slab: orm.Bool,
    primitive: orm.Bool,
    reorient_lattice: orm.Bool,
) -> t.Annotated[
    dict,
    namespace(
        structures=dynamic(orm.StructureData),
        manifest=orm.Dict,
    ),
]:
    """Generate all symmetrized slab terminations for a given Miller index."""
    from pymatgen.core.surface import SlabGenerator
    from pymatgen.io.ase import AseAtomsAdaptor

    adaptor = AseAtomsAdaptor()
    pmg_structure = adaptor.get_structure(bulk_structure.get_ase())

    miller = tuple(int(x) for x in miller_indices.get_list())

    generator = SlabGenerator(
        pmg_structure,
        miller,
        float(min_slab_size.value),
        float(min_vacuum_size.value),
        lll_reduce=bool(lll_reduce.value),
        center_slab=bool(center_slab.value),
        in_unit_planes=False,
        primitive=bool(primitive.value),
        reorient_lattice=bool(reorient_lattice.value),
    )

    slabs = generator.get_slabs(symmetrize=True)
    if not slabs:
        raise ValueError(
            f"No slabs were generated for Miller indices {miller}. "
            f"Check if the Miller indices are valid for this structure."
        )

    # Sort by shift to ensure stable labeling.
    slabs_sorted = sorted(slabs, key=lambda s: float(s.shift))

    structures: dict[str, orm.StructureData] = {}
    term_meta: list[dict[str, t.Any]] = []

    for i, slab in enumerate(slabs_sorted):
        label = f"term_{i:02d}"

        ortho = slab.get_orthogonal_c_slab()
        ase_slab = adaptor.get_atoms(ortho)
        structures[label] = orm.StructureData(ase=ase_slab)

        term_meta.append(
            {
                'label': label,
                'shift': float(slab.shift),
                'n_sites': int(len(slab.sites)),
            }
        )

    manifest = orm.Dict(
        dict={
            'miller_index': list(miller),
            'min_slab_size': float(min_slab_size.value),
            'min_vacuum_size': float(min_vacuum_size.value),
            'lll_reduce': bool(lll_reduce.value),
            'center_slab': bool(center_slab.value),
            'primitive': bool(primitive.value),
            'reorient_lattice': bool(reorient_lattice.value),
            'n_terminations': len(term_meta),
            'terminations': term_meta,
        }
    )

    return {
        'structures': structures,
        'manifest': manifest,
    }


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a surface_terminations stage configuration."""
    name = stage['name']

    if 'structure_from' not in stage:
        raise ValueError(
            f"Stage '{name}': surface_terminations stages require 'structure_from' "
            f"('input' or a previous stage name)"
        )

    structure_from = stage['structure_from']
    if structure_from != 'input' and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must be "
            f"'input' or a previous stage name"
        )

    miller = stage.get('miller_indices')
    if miller is None:
        raise ValueError(
            f"Stage '{name}': 'miller_indices' is required (e.g. [1, 1, 0])"
        )
    if not isinstance(miller, (list, tuple)) or len(miller) != 3 or not all(
        isinstance(x, int) for x in miller
    ):
        raise ValueError(
            f"Stage '{name}': 'miller_indices' must be a list of 3 integers, got {miller!r}"
        )

    min_slab_size = stage.get('min_slab_size', 18.0)
    min_vacuum_size = stage.get('min_vacuum_size', 15.0)
    if not isinstance(min_slab_size, (int, float)) or float(min_slab_size) <= 0:
        raise ValueError(
            f"Stage '{name}': min_slab_size must be a positive number, got {min_slab_size!r}"
        )
    if not isinstance(min_vacuum_size, (int, float)) or float(min_vacuum_size) <= 0:
        raise ValueError(
            f"Stage '{name}': min_vacuum_size must be a positive number, got {min_vacuum_size!r}"
        )

    for key in ('lll_reduce', 'center_slab', 'primitive', 'reorient_lattice'):
        if key in stage and not isinstance(stage[key], bool):
            raise ValueError(
                f"Stage '{name}': {key} must be a bool, got {type(stage[key]).__name__}"
            )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create surface_terminations stage tasks in the WorkGraph."""
    structure_from = stage['structure_from']

    if structure_from == 'input':
        bulk_structure = context['input_structure']
    else:
        from . import resolve_structure_from
        bulk_structure = resolve_structure_from(structure_from, context)

    miller = stage['miller_indices']

    task_node = wg.add_task(
        generate_surface_terminations,
        name=f'surface_terminations_{stage_name}',
        bulk_structure=bulk_structure,
        miller_indices=orm.List(list=[int(x) for x in miller]),
        min_slab_size=orm.Float(stage.get('min_slab_size', 18.0)),
        min_vacuum_size=orm.Float(stage.get('min_vacuum_size', 15.0)),
        lll_reduce=orm.Bool(stage.get('lll_reduce', True)),
        center_slab=orm.Bool(stage.get('center_slab', True)),
        primitive=orm.Bool(stage.get('primitive', True)),
        reorient_lattice=orm.Bool(stage.get('reorient_lattice', True)),
    )

    return {
        'terminations': task_node,
        'structures': task_node.outputs.structures,
        'manifest': task_node.outputs.manifest,
        'bulk_structure': bulk_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose surface_terminations stage outputs on the WorkGraph."""
    task_node = stage_tasks_result['terminations']

    # Keep exposure minimal (manifest only); structures are consumed by downstream bricks.
    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.surface_terminations.manifest', task_node.outputs.manifest)
    else:
        setattr(wg.outputs, f'{stage_name}_surface_terminations_manifest', task_node.outputs.manifest)


def get_stage_results(wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from a surface_terminations stage."""
    result = {
        'manifest': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'surface_terminations',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = (
                getattr(stage_ns, 'surface_terminations', None)
                if stage_ns is not None else None
            )
            if brick_ns is not None and hasattr(brick_ns, 'manifest'):
                node = brick_ns.manifest
                if hasattr(node, 'get_dict'):
                    result['manifest'] = node.get_dict()
        else:
            attr = f'{stage_name}_surface_terminations_manifest'
            if hasattr(outputs, attr):
                node = getattr(outputs, attr)
                if hasattr(node, 'get_dict'):
                    result['manifest'] = node.get_dict()

    if result['manifest'] is None:
        _extract_manifest_from_links(wg_node, stage_name, result)

    return result


def _extract_manifest_from_links(wg_node, stage_name: str, result: dict) -> None:
    """Fallback: traverse WorkGraph links to find the manifest Dict."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'surface_terminations_{stage_name}'
    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        if task_name not in link.link_label:
            continue
        child = link.node
        created = child.base.links.get_outgoing(link_type=LinkType.CREATE)
        for out_link in created.all():
            if out_link.link_label == 'manifest' and hasattr(out_link.node, 'get_dict'):
                result['manifest'] = out_link.node.get_dict()
                return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a surface_terminations stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="surface_terminations")

    manifest = stage_result.get('manifest') or {}
    miller = manifest.get('miller_index')
    n_terms = manifest.get('n_terminations')
    if miller is not None:
        console.print(f"      [bold]Miller:[/bold] {miller}")
    if n_terms is not None:
        console.print(f"      [bold]Terminations:[/bold] {n_terms}")

