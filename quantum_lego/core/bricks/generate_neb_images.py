"""NEB image generation brick for the lego module.

Generates intermediate NEB images from two relaxed endpoint structures.
"""

from aiida import orm
from aiida.common.links import LinkType

from .connections import GENERATE_NEB_IMAGES_PORTS as PORTS  # noqa: F401
from ..tasks import generate_neb_intermediate_image, build_neb_images_manifest


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a generate_neb_images stage configuration."""
    name = stage['name']

    for field in ('initial_from', 'final_from', 'n_images'):
        if field not in stage:
            raise ValueError(
                f"Stage '{name}': generate_neb_images stages require '{field}'"
            )

    initial_from = stage['initial_from']
    final_from = stage['final_from']
    if initial_from == name or final_from == name:
        raise ValueError(
            f"Stage '{name}': initial_from/final_from cannot reference itself"
        )
    if initial_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' initial_from='{initial_from}' must reference "
            f"a previous stage name"
        )
    if final_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' final_from='{final_from}' must reference "
            f"a previous stage name"
        )

    n_images = stage['n_images']
    if not isinstance(n_images, int) or n_images < 1:
        raise ValueError(
            f"Stage '{name}' n_images={n_images} must be a positive integer"
        )

    method = stage.get('method', 'idpp')
    if not isinstance(method, str) or method.lower() not in {'idpp', 'linear'}:
        raise ValueError(
            f"Stage '{name}' method='{method}' must be 'idpp' or 'linear'"
        )

    mic = stage.get('mic', True)
    if not isinstance(mic, bool):
        raise ValueError(
            f"Stage '{name}' mic must be a bool, got {type(mic).__name__}"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create generate_neb_images stage tasks in the WorkGraph."""
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    initial_from = stage['initial_from']
    final_from = stage['final_from']

    if stage_types.get(initial_from) != 'vasp':
        raise ValueError(
            f"Stage '{stage_name}': initial_from='{initial_from}' must point "
            f"to a VASP stage"
        )
    if stage_types.get(final_from) != 'vasp':
        raise ValueError(
            f"Stage '{stage_name}': final_from='{final_from}' must point "
            f"to a VASP stage"
        )

    initial_structure = stage_tasks[initial_from]['vasp'].outputs.structure
    final_structure = stage_tasks[final_from]['vasp'].outputs.structure

    n_images = int(stage['n_images'])
    method = stage.get('method', 'idpp').lower()
    mic = bool(stage.get('mic', True))

    image_tasks = {}
    manifest_kwargs = {}
    for i in range(1, n_images + 1):
        label = f'image_{i:02d}'
        image_task = wg.add_task(
            generate_neb_intermediate_image,
            name=f'neb_image_{i:02d}_{stage_name}',
            initial_structure=initial_structure,
            final_structure=final_structure,
            n_images=orm.Int(n_images),
            image_index=orm.Int(i),
            method=orm.Str(method),
            mic=orm.Bool(mic),
        )
        image_tasks[label] = image_task
        manifest_kwargs[label] = image_task.outputs.result

    manifest_task = wg.add_task(
        build_neb_images_manifest,
        name=f'neb_images_manifest_{stage_name}',
        **manifest_kwargs,
    )

    return {
        'images': image_tasks,
        'manifest': manifest_task,
        'initial_structure': initial_structure,
        'final_structure': final_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose generate_neb_images outputs on the WorkGraph."""
    manifest_task = stage_tasks_result['manifest']
    image_tasks = stage_tasks_result['images']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(
            wg.outputs,
            f'{ns}.generate_neb_images.images',
            manifest_task.outputs.result,
        )
        for label in sorted(image_tasks.keys()):
            setattr(
                wg.outputs,
                f'{ns}.generate_neb_images.{label}',
                image_tasks[label].outputs.result,
            )
    else:
        setattr(wg.outputs, f'{stage_name}_images', manifest_task.outputs.result)
        for label in sorted(image_tasks.keys()):
            setattr(
                wg.outputs,
                f'{stage_name}_{label}',
                image_tasks[label].outputs.result,
            )


def get_stage_results(
    wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None
) -> dict:
    """Extract results from a generate_neb_images stage."""
    result = {
        'images': None,
        'image_structures': {},
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'generate_neb_images',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = (
                getattr(stage_ns, 'generate_neb_images', None)
                if stage_ns is not None else None
            )
            if brick_ns is not None and hasattr(brick_ns, 'images'):
                images_node = brick_ns.images
                if hasattr(images_node, 'get_dict'):
                    result['images'] = images_node.get_dict()
                labels = result['images'].get('labels', []) if result['images'] else []
                for label in labels:
                    if hasattr(brick_ns, label):
                        result['image_structures'][label] = getattr(brick_ns, label)
        else:
            images_attr = f'{stage_name}_images'
            if hasattr(outputs, images_attr):
                images_node = getattr(outputs, images_attr)
                if hasattr(images_node, 'get_dict'):
                    result['images'] = images_node.get_dict()
                labels = result['images'].get('labels', []) if result['images'] else []
                for label in labels:
                    image_attr = f'{stage_name}_{label}'
                    if hasattr(outputs, image_attr):
                        result['image_structures'][label] = getattr(outputs, image_attr)

    if result['images'] is None or not result['image_structures']:
        _extract_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_stage_from_workgraph(wg_node, stage_name: str, result: dict) -> None:
    """Extract stage results by traversing WorkGraph calcfunction links."""
    if not hasattr(wg_node, 'base'):
        return

    manifest_task_name = f'neb_images_manifest_{stage_name}'
    image_task_suffix = f'_{stage_name}'

    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if manifest_task_name in link_label or link_label == manifest_task_name:
            created = child_node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result' and hasattr(out_link.node, 'get_dict'):
                    result['images'] = out_link.node.get_dict()

        if 'neb_image_' in link_label and link_label.endswith(image_task_suffix):
            parts = link_label.split('_')
            image_idx = parts[2] if len(parts) >= 4 else None
            if image_idx is None:
                continue
            image_label = f'image_{image_idx}'
            created = child_node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result':
                    result['image_structures'][image_label] = out_link.node


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a generate_neb_images stage."""
    print(f"  [{index}] {stage_name} (GENERATE NEB IMAGES)")

    images_meta = stage_result.get('images') or {}
    n_images = images_meta.get('n_images')
    labels = images_meta.get('labels', [])
    if n_images is not None:
        print(f"      Images generated: {n_images}")
    if labels:
        print(f"      Labels: {', '.join(labels)}")
    if stage_result.get('image_structures'):
        pks = [
            f"{label}=PK {node.pk}"
            for label, node in sorted(stage_result['image_structures'].items())
            if hasattr(node, 'pk')
        ]
        if pks:
            print(f"      Structures: {', '.join(pks)}")
