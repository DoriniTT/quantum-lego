"""NEB brick for the lego module.

Runs aiida-vasp ``vasp.neb`` using endpoint structures from previous VASP stages.
Intermediate images can come from a generate_neb_images stage or from files in a
local directory.

**Current Status (2026-02-06):**

The NEB brick is **working** on bohr and lovelace clusters. Successfully completed
end-to-end testing with a 5-stage pipeline (relax endpoints → generate images →
NEB stage 1 → CI-NEB stage 2). The LegoVaspNEBWorkChain properly reconstructs
namespace inputs from WorkGraph's flat key format (``neb_images__01``, etc.).

**Remaining verification tasks:**
1. Investigate and fix obelix cluster compatibility (subdirectory transfer issues
   in submission script prevent VASP NEB subdirs from being properly copied)
2. Test image generation with additional test cases to validate robustness

**Future enhancement:**
Add ``neb_analysis`` brick to extract energy barriers and reaction paths using
VTST tools (perl scripts: ``nebbarrier.pl``, ``nebef.pl``, etc.).
"""

from pathlib import Path
import re
import math

from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import task
from aiida_vasp.workchains.v2.neb import VaspNEBWorkChain
from aiida_vasp.workchains.v2.vasp import VaspWorkChain

from .connections import NEB_PORTS as PORTS  # noqa: F401
from quantum_lego.core.common.utils import deep_merge_dicts, get_vasp_parser_settings


_OPTIONAL_OUTPUTS = {
    'trajectory': 'trajectory',
    'energies': 'energies',
    'dos': 'dos',
    'projectors': 'projectors',
    'arrays': 'arrays',
    'bands': 'bands',
    'kpoints': 'kpoints',
    'parameters': 'parameters',
    'chgcar': 'chgcar',
    'wavecar': 'wavecar',
    'hessian': 'hessian',
    'dynmat': 'dynmat',
    'born_charges': 'born_charges',
    'dielectrics': 'dielectrics',
    'parallel_settings': 'parallel_settings',
}


class LegoVaspNEBWorkChain(VaspNEBWorkChain):
    """Patch VaspNEBWorkChain for WorkGraph namespace input handling.

    WorkGraph passes namespace inputs as flat keys with ``__`` separators
    (e.g. ``neb_images__01``, ``neb_images__02``) rather than creating a
    nested dict.  VaspNEBWorkChain's ``check_neb_inputs()`` expects
    ``self.ctx.inputs.neb_images`` to be a dict-like namespace.  This
    subclass reconstructs the ``neb_images`` namespace from the flat keys
    before calling ``check_neb_inputs()``.
    """

    def init_inputs(self):  # type: ignore[override]
        exit_code = VaspWorkChain.init_inputs(self)
        if exit_code is not None:
            return exit_code

        # WorkGraph passes namespace inputs as flat keys with ``__`` separator
        # (e.g. ``neb_images__01``, ``neb_images__02``) instead of creating a
        # nested ``neb_images`` dict.  Reconstruct the namespace so that
        # ``check_neb_inputs()`` can access ``self.ctx.inputs.neb_images``.
        if 'neb_images' not in self.ctx.inputs:
            from aiida.common.extendeddicts import AttributeDict as _AD
            collected = {}
            for key in list(self.inputs.keys()):
                if key.startswith('neb_images__'):
                    image_key = key[len('neb_images__'):]
                    collected[image_key] = self.inputs[key]
            if collected:
                self.ctx.inputs['neb_images'] = _AD(collected)

        return self.check_neb_inputs()


def _extract_lclimb_from_incar(incar: dict) -> tuple[dict, bool | None]:
    """Remove LCLIMB/lclimb from INCAR and return its normalized bool value.

    aiida-vasp's parameter massager for ``vasp.neb`` rejects the LCLIMB tag.
    We therefore inject it via ``metadata.options.prepend_text`` instead.
    """
    updated = dict(incar)
    lclimb_value = None
    lclimb_key = None

    for key in list(updated.keys()):
        if key.lower() == 'lclimb':
            lclimb_key = key
            lclimb_value = updated.pop(key)
            break

    if lclimb_key is None:
        return updated, None

    if isinstance(lclimb_value, bool):
        return updated, lclimb_value
    if isinstance(lclimb_value, int) and lclimb_value in (0, 1):
        return updated, bool(lclimb_value)
    if isinstance(lclimb_value, str):
        normalized = lclimb_value.strip().lower()
        if normalized in {'true', '.true.', 't', 'yes', 'y', '1'}:
            return updated, True
        if normalized in {'false', '.false.', 'f', 'no', 'n', '0'}:
            return updated, False

    raise ValueError(
        f"LCLIMB in INCAR must be bool-like, got {type(lclimb_value).__name__}: {lclimb_value!r}"
    )


def _inject_lclimb_prepend_text(options: dict, lclimb: bool | None) -> dict:
    """Inject LCLIMB assignment into metadata options prepend_text."""
    if lclimb is None:
        return dict(options)

    updated = dict(options)
    value = '.TRUE.' if lclimb else '.FALSE.'
    command = f'echo LCLIMB={value} >> INCAR'

    existing = updated.get('prepend_text')
    if existing:
        if command not in existing:
            updated['prepend_text'] = f'{existing.rstrip()}\n{command}'
    else:
        updated['prepend_text'] = command

    return updated


def _build_neb_parser_settings(existing: dict | None = None) -> dict:
    """Build parser settings that guarantee key NEB outputs are created."""
    settings = dict(existing or {})
    parser_settings = dict(settings.get('parser_settings', {}))

    required = get_vasp_parser_settings(
        add_energy=True,
        add_trajectory=True,
        add_structure=True,
        add_kpoints=True,
    )['parser_settings']

    parser_settings = deep_merge_dicts(parser_settings, required)

    include_node = list(parser_settings.get('include_node', []))
    for node_name in ('trajectory', 'structure', 'kpoints'):
        if node_name not in include_node:
            include_node.append(node_name)
    parser_settings['include_node'] = include_node

    settings['parser_settings'] = parser_settings
    return settings


@task.calcfunction
def build_kpoints_from_spacing(
    structure: orm.StructureData,
    kpoints_spacing: orm.Float,
) -> orm.KpointsData:
    """Build KpointsData from structure and spacing for NEB workchain compatibility."""
    kpoints = orm.KpointsData()
    kpoints.set_cell_from_structure(structure)
    kpoints.set_kpoints_mesh_from_density(float(kpoints_spacing.value) * math.pi * 2.0)
    return kpoints


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a NEB stage configuration."""
    name = stage['name']

    for field in ('initial_from', 'final_from', 'incar'):
        if field not in stage:
            raise ValueError(f"Stage '{name}': NEB stages require '{field}'")

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

    incar = stage['incar']
    if not isinstance(incar, dict):
        raise ValueError(
            f"Stage '{name}': incar must be a dict, got {type(incar).__name__}"
        )

    has_images_from = stage.get('images_from') is not None
    has_images_dir = stage.get('images_dir') is not None
    if has_images_from == has_images_dir:
        raise ValueError(
            f"Stage '{name}': specify exactly one of 'images_from' or 'images_dir'"
        )

    if has_images_from:
        images_from = stage['images_from']
        if images_from == name:
            raise ValueError(
                f"Stage '{name}': images_from cannot reference itself"
            )
        if images_from not in stage_names:
            raise ValueError(
                f"Stage '{name}' images_from='{images_from}' must reference "
                f"a previous stage name"
            )

    if has_images_dir:
        images_dir = stage['images_dir']
        if not isinstance(images_dir, str) or not images_dir.strip():
            raise ValueError(
                f"Stage '{name}': images_dir must be a non-empty string path"
            )

    restart = stage.get('restart')
    if restart is not None:
        if restart == name:
            raise ValueError(f"Stage '{name}': restart cannot reference itself")
        if restart not in stage_names:
            raise ValueError(
                f"Stage '{name}' restart='{restart}' must reference "
                f"a previous stage name"
            )


def _resolve_endpoint_structure_socket(stage_ref: str, context: dict):
    """Resolve endpoint structure from a referenced VASP stage."""
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    ref_stage_type = stage_types.get(stage_ref)
    if ref_stage_type != 'vasp':
        raise ValueError(
            f"Endpoint stage '{stage_ref}' must be type 'vasp', got "
            f"'{ref_stage_type}'"
        )
    return stage_tasks[stage_ref]['vasp'].outputs.structure


def _parse_index_from_label(label: str) -> int:
    """Extract numeric index from labels like image_01."""
    match = re.search(r'(\d+)$', label)
    if match is None:
        raise ValueError(f"Could not parse image index from '{label}'")
    return int(match.group(1))


def _ordered_generated_images(images_map: dict) -> list:
    """Return generated image sockets ordered by numeric label."""
    ordered = []
    for label, value in images_map.items():
        idx = _parse_index_from_label(label)
        if hasattr(value, 'outputs') and hasattr(value.outputs, 'result'):
            socket = value.outputs.result
        else:
            socket = value
        ordered.append((idx, label, socket))
    ordered.sort(key=lambda item: item[0])
    return ordered


def _load_structure_from_file(filepath: Path) -> orm.StructureData:
    """Load a structure file into AiiDA StructureData."""
    from pymatgen.core import Structure

    pmg_structure = Structure.from_file(str(filepath))
    return orm.StructureData(pymatgen=pmg_structure)


def _load_images_from_directory(images_dir: str) -> list:
    """Load NEB images from a directory (VTST-style or flat-file layout)."""
    directory = Path(images_dir).expanduser()
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    directory = directory.resolve()

    if not directory.exists() or not directory.is_dir():
        raise ValueError(f"images_dir does not exist or is not a directory: {directory}")

    indexed_files = {}

    # VTST-style folders: 00/POSCAR, 01/POSCAR, ...
    for child in directory.iterdir():
        if not child.is_dir() or not child.name.isdigit():
            continue
        idx = int(child.name)
        for filename in ('POSCAR', 'CONTCAR', f'image_{idx:02d}.vasp', f'{idx:02d}.vasp'):
            candidate = child / filename
            if candidate.exists() and candidate.is_file():
                indexed_files[idx] = candidate
                break

    # Flat files: image_01.vasp, 01.vasp
    image_pattern = re.compile(r'^image_(\d+)\.vasp$', re.IGNORECASE)
    flat_pattern = re.compile(r'^(\d+)\.vasp$', re.IGNORECASE)
    for child in directory.iterdir():
        if not child.is_file():
            continue
        match = image_pattern.match(child.name) or flat_pattern.match(child.name)
        if match is None:
            continue
        idx = int(match.group(1))
        indexed_files.setdefault(idx, child)

    if not indexed_files:
        raise ValueError(
            f"No NEB image files found in images_dir: {directory}. "
            f"Supported layouts: numeric subfolders with POSCAR/CONTCAR or "
            f"flat files image_XX.vasp / XX.vasp."
        )

    sorted_indices = sorted(indexed_files.keys())
    max_idx = sorted_indices[-1]

    # If 00..N+1 exists contiguously, use only intermediates 01..N.
    expected = set(range(0, max_idx + 1))
    has_endpoint_layout = (
        sorted_indices[0] == 0 and len(sorted_indices) >= 3 and set(sorted_indices) == expected
    )
    if has_endpoint_layout:
        selected_indices = [idx for idx in sorted_indices if 0 < idx < max_idx]
    else:
        selected_indices = sorted_indices

    if not selected_indices:
        raise ValueError(
            f"No intermediate NEB images detected in {directory}. "
            f"Found indices: {sorted_indices}"
        )

    ordered_images = []
    for seq_idx, raw_idx in enumerate(selected_indices, start=1):
        label = f'image_{seq_idx:02d}'
        structure = _load_structure_from_file(indexed_files[raw_idx])
        ordered_images.append((seq_idx, label, structure))

    return ordered_images


def _set_images_count(incar: dict, n_images: int) -> dict:
    """Set INCAR images count consistently, removing any pre-existing casing."""
    updated = dict(incar)
    for key in list(updated.keys()):
        if key.lower() == 'images':
            updated.pop(key)
    updated['images'] = int(n_images)
    return updated


def create_stage_tasks(wg, stage, stage_name, context):
    """Create NEB stage tasks in the WorkGraph."""
    from ..workgraph import _prepare_builder_inputs

    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    initial_structure = _resolve_endpoint_structure_socket(stage['initial_from'], context)
    final_structure = _resolve_endpoint_structure_socket(stage['final_from'], context)

    has_images_from = stage.get('images_from') is not None
    if has_images_from:
        images_from = stage['images_from']
        if stage_types.get(images_from) != 'generate_neb_images':
            raise ValueError(
                f"Stage '{stage_name}': images_from='{images_from}' must point "
                f"to a generate_neb_images stage"
            )
        generated = stage_tasks[images_from].get('images', {})
        ordered_images = _ordered_generated_images(generated)
    else:
        ordered_images = _load_images_from_directory(stage['images_dir'])

    n_images = len(ordered_images)
    if n_images < 1:
        raise ValueError(
            f"Stage '{stage_name}': resolved zero intermediate images"
        )

    stage_incar, stage_lclimb = _extract_lclimb_from_incar(stage['incar'])
    stage_incar = _set_images_count(stage_incar, n_images)

    stage_kpoints_spacing = stage.get(
        'kpoints_spacing', context['base_kpoints_spacing']
    )
    stage_kpoints_mesh = stage.get('kpoints', None)
    stage_retrieve = stage.get('retrieve', None)
    stage_options = stage.get('options', context['options'])
    stage_options = _inject_lclimb_prepend_text(stage_options, stage_lclimb)
    stage_potential_family = stage.get(
        'potential_family', context['potential_family']
    )
    stage_potential_mapping = stage.get(
        'potential_mapping', context['potential_mapping']
    )

    builder_inputs = _prepare_builder_inputs(
        incar=stage_incar,
        kpoints_spacing=stage_kpoints_spacing,
        potential_family=stage_potential_family,
        potential_mapping=stage_potential_mapping,
        options=stage_options,
        retrieve=stage_retrieve,
        restart_folder=None,
        clean_workdir=context['clean_workdir'],
        kpoints_mesh=stage_kpoints_mesh,
    )
    kpoints_task = None
    if 'kpoints' not in builder_inputs and 'kpoints_spacing' in builder_inputs:
        spacing = builder_inputs.pop('kpoints_spacing')
        if not isinstance(spacing, orm.Float):
            spacing = orm.Float(float(spacing))
        kpoints_task = wg.add_task(
            build_kpoints_from_spacing,
            name=f'neb_kpoints_{stage_name}',
            structure=initial_structure,
            kpoints_spacing=spacing,
        )
        builder_inputs['kpoints'] = kpoints_task.outputs.result

    existing_settings = {}
    if 'settings' in builder_inputs:
        existing_settings = builder_inputs['settings'].get_dict()
    user_settings = stage.get('settings', {})
    if user_settings and not isinstance(user_settings, dict):
        raise ValueError(
            f"Stage '{stage_name}': settings must be a dict when provided"
        )
    merged_settings = deep_merge_dicts(existing_settings, user_settings)
    builder_inputs['settings'] = orm.Dict(
        dict=_build_neb_parser_settings(merged_settings)
    )

    restart = stage.get('restart')
    restart_folder = None
    if restart is not None:
        if stage_types.get(restart) != 'neb':
            raise ValueError(
                f"Stage '{stage_name}': restart='{restart}' must point to a NEB stage"
            )
        restart_folder = stage_tasks[restart]['neb'].outputs.remote_folder

    NEBTask = task(LegoVaspNEBWorkChain)

    neb_kwargs = {
        'name': f'neb_{stage_name}',
        'initial_structure': initial_structure,
        'final_structure': final_structure,
        'code': context['code'],
        **builder_inputs,
    }
    if restart_folder is not None:
        neb_kwargs['restart_folder'] = restart_folder

    # Add images at the top-level namespace for VaspNEBWorkChain input ports.
    image_sockets = {}
    for idx, label, image_socket in ordered_images:
        image_num = f'{idx:02d}'
        neb_kwargs[f'neb_images__{image_num}'] = image_socket
        image_sockets[label] = image_socket

    neb_task = wg.add_task(NEBTask, **neb_kwargs)

    return {
        'neb': neb_task,
        'images': image_sockets,
        'n_images': n_images,
        'kpoints': kpoints_task,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose NEB stage outputs on the WorkGraph."""
    neb_task = stage_tasks_result['neb']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.neb.misc', neb_task.outputs.misc)
        setattr(wg.outputs, f'{ns}.neb.structure', neb_task.outputs.structure)
        setattr(wg.outputs, f'{ns}.neb.remote', neb_task.outputs.remote_folder)
        setattr(wg.outputs, f'{ns}.neb.retrieved', neb_task.outputs.retrieved)
        for attr_name, out_name in _OPTIONAL_OUTPUTS.items():
            try:
                setattr(
                    wg.outputs,
                    f'{ns}.neb.{out_name}',
                    getattr(neb_task.outputs, attr_name),
                )
            except AttributeError:
                pass
    else:
        setattr(wg.outputs, f'{stage_name}_misc', neb_task.outputs.misc)
        setattr(wg.outputs, f'{stage_name}_structure', neb_task.outputs.structure)
        setattr(wg.outputs, f'{stage_name}_remote', neb_task.outputs.remote_folder)
        setattr(wg.outputs, f'{stage_name}_retrieved', neb_task.outputs.retrieved)
        for attr_name, out_name in _OPTIONAL_OUTPUTS.items():
            try:
                setattr(
                    wg.outputs,
                    f'{stage_name}_{out_name}',
                    getattr(neb_task.outputs, attr_name),
                )
            except AttributeError:
                pass


def get_stage_results(
    wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None
) -> dict:
    """Extract results from a NEB stage in a sequential workflow."""
    result = {
        'misc': None,
        'structure': None,
        'remote': None,
        'files': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'neb',
    }
    for out_name in _OPTIONAL_OUTPUTS.values():
        result[out_name] = None

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'neb', None) if stage_ns is not None else None
            _read_outputs_from_namespace(brick_ns, result)
        else:
            if hasattr(outputs, f'{stage_name}_misc'):
                misc_node = getattr(outputs, f'{stage_name}_misc')
                if hasattr(misc_node, 'get_dict'):
                    result['misc'] = misc_node.get_dict()
            if hasattr(outputs, f'{stage_name}_structure'):
                result['structure'] = getattr(outputs, f'{stage_name}_structure')
            if hasattr(outputs, f'{stage_name}_remote'):
                result['remote'] = getattr(outputs, f'{stage_name}_remote')
            if hasattr(outputs, f'{stage_name}_retrieved'):
                result['files'] = getattr(outputs, f'{stage_name}_retrieved')
            for out_name in _OPTIONAL_OUTPUTS.values():
                attr = f'{stage_name}_{out_name}'
                if hasattr(outputs, attr):
                    result[out_name] = getattr(outputs, attr)

    if result['misc'] is None or result['remote'] is None:
        _extract_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _read_outputs_from_namespace(brick_ns, result: dict) -> None:
    """Read namespaced outputs into the result dict."""
    if brick_ns is None:
        return

    if hasattr(brick_ns, 'misc'):
        misc_node = brick_ns.misc
        if hasattr(misc_node, 'get_dict'):
            result['misc'] = misc_node.get_dict()
    if hasattr(brick_ns, 'structure'):
        result['structure'] = brick_ns.structure
    if hasattr(brick_ns, 'remote'):
        result['remote'] = brick_ns.remote
    if hasattr(brick_ns, 'retrieved'):
        result['files'] = brick_ns.retrieved

    for out_name in _OPTIONAL_OUTPUTS.values():
        if hasattr(brick_ns, out_name):
            result[out_name] = getattr(brick_ns, out_name)


def _extract_stage_from_workgraph(wg_node, stage_name: str, result: dict) -> None:
    """Extract NEB stage results by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    neb_task_name = f'neb_{stage_name}'
    called = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called.all():
        child_node = link.node
        link_label = link.link_label

        if neb_task_name not in link_label and link_label != neb_task_name:
            continue
        if not hasattr(child_node, 'outputs'):
            continue

        outputs = child_node.outputs
        if result['misc'] is None and hasattr(outputs, 'misc'):
            misc = outputs.misc
            if hasattr(misc, 'get_dict'):
                result['misc'] = misc.get_dict()
        if result['structure'] is None and hasattr(outputs, 'structure'):
            result['structure'] = outputs.structure
        if result['remote'] is None and hasattr(outputs, 'remote_folder'):
            result['remote'] = outputs.remote_folder
        if result['files'] is None and hasattr(outputs, 'retrieved'):
            result['files'] = outputs.retrieved

        for attr_name, out_name in _OPTIONAL_OUTPUTS.items():
            if result[out_name] is None and hasattr(outputs, attr_name):
                result[out_name] = getattr(outputs, attr_name)


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a NEB stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="neb")

    if stage_result['structure'] is not None:
        struct = stage_result['structure']
        formula = struct.get_formula()
        n_atoms = len(struct.sites)
        console.print(f"      [bold]Structure:[/bold] {formula} [dim]({n_atoms} atoms, PK: {struct.pk})[/dim]")

    if stage_result['misc'] is not None:
        run_status = stage_result['misc'].get('run_status', 'N/A')
        console.print(f"      [bold]Status:[/bold] {run_status}")

    if stage_result['remote'] is not None:
        console.print(f"      [bold]Remote folder:[/bold] PK [pk]{stage_result['remote'].pk}[/pk]")
    if stage_result['files'] is not None:
        files = stage_result['files'].list_object_names()
        console.print(f"      [bold]Retrieved:[/bold] [dim]{', '.join(files)}[/dim]")

    optional_available = [
        key for key in _OPTIONAL_OUTPUTS.values()
        if stage_result.get(key) is not None
    ]
    if optional_available:
        console.print(f"      [bold]Optional outputs:[/bold] [dim]{', '.join(optional_available)}[/dim]")
