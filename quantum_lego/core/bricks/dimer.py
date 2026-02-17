"""Dimer brick for the lego module.

Implements the VASP Improved Dimer Method (IDM) transition-state refinement:

1) Run a vibrational analysis (IBRION=5, NWRITE=3) in a prior VASP stage
2) Extract the hardest imaginary mode eigenvectors (dx, dy, dz columns) from OUTCAR
3) Append the 3N-vector (one line per atom) to POSCAR via scheduler prepend_text
4) Run VASP with IBRION=44

Reference: https://vasp.at/wiki/Improved_dimer_method
"""

from __future__ import annotations

import re
from typing import Any, Dict, Set

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task

from .connections import DIMER_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_total_energy
from ..tasks import compute_dynamics
from ..types import StageContext, StageTasksResult, VaspResults


_MODE_HEADER_RE = re.compile(
    r'^\s*(\d+)\s+f/i=\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*THz.*?'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*cm-1',
    re.IGNORECASE,
)
_EIGENVECTOR_HEADER_RE = re.compile(r'^\s*X\s+Y\s+Z\s+dx\s+dy\s+dz\s*$', re.IGNORECASE)


def _parse_hardest_imaginary_mode(outcar_content: str, n_atoms: int) -> dict:
    """Parse OUTCAR and return the hardest imaginary mode eigenvectors.

    Returns a dict:
        {
            'mode_index': int,
            'frequency_thz': float,
            'frequency_cm-1': float,
            'axis': [(dx, dy, dz), ...]  # len == n_atoms, strings (verbatim tokens)
        }
    """
    if n_atoms < 1:
        raise ValueError(f"Invalid atom count for dimer axis extraction: n_atoms={n_atoms}")

    marker = 'Eigenvectors after division by SQRT(mass)'
    lower = outcar_content.lower()
    start = lower.rfind(marker.lower())
    if start == -1:
        raise ValueError(
            "Could not find 'Eigenvectors after division by SQRT(mass)' in OUTCAR. "
            "Ensure the vibrational calculation used NWRITE=3."
        )

    lines = outcar_content[start:].splitlines()
    modes: list[dict] = []

    for i, line in enumerate(lines):
        match = _MODE_HEADER_RE.match(line)
        if match is None:
            continue

        mode_index = int(match.group(1))
        freq_thz = float(match.group(2))
        freq_cm1 = float(match.group(3))

        # Find the "X Y Z dx dy dz" header, then read n_atoms lines below.
        j = i + 1
        while j < len(lines) and _EIGENVECTOR_HEADER_RE.match(lines[j]) is None:
            j += 1
        if j >= len(lines):
            continue

        axis: list[tuple[str, str, str]] = []
        for k in range(n_atoms):
            idx = j + 1 + k
            if idx >= len(lines):
                break
            data = lines[idx].strip()
            if not data:
                break
            toks = data.split()
            if len(toks) < 6:
                break

            dx, dy, dz = toks[3], toks[4], toks[5]
            try:
                float(dx)
                float(dy)
                float(dz)
            except ValueError:
                break
            axis.append((dx, dy, dz))

        if len(axis) == n_atoms:
            modes.append(
                {
                    'mode_index': mode_index,
                    'frequency_thz': freq_thz,
                    'frequency_cm-1': freq_cm1,
                    'axis': axis,
                }
            )

    if not modes:
        raise ValueError(
            "Could not parse any imaginary modes (f/i=) with a complete 3N eigenvector "
            f"table in OUTCAR (expected {n_atoms} atoms). Ensure the vibrational stage ran "
            "with IBRION=5 and NWRITE=3, and that OUTCAR was retrieved."
        )

    # Hardest imaginary mode: largest magnitude in cm-1 (translational modes are small).
    return max(modes, key=lambda item: abs(item['frequency_cm-1']))


@task.calcfunction
def inject_dimer_axis_prepend_text(
    options: orm.Dict,
    retrieved: orm.FolderData,
    structure: orm.StructureData,
    poscar_filename: orm.Str | None = None,
) -> orm.Dict:
    """Return options dict with prepend_text that appends dimer axis to POSCAR."""
    opts = dict(options.get_dict() or {})
    filename = poscar_filename.value if poscar_filename is not None else 'POSCAR'

    try:
        content = retrieved.get_object_content('OUTCAR')
    except Exception as exc:  # pragma: no cover (AiiDA internals)
        raise ValueError(
            "OUTCAR not found in vibrational stage retrieved folder. "
            "Ensure the vibrational stage retrieves OUTCAR."
        ) from exc

    outcar_text = content.decode(errors='replace') if isinstance(content, bytes) else str(content)
    mode = _parse_hardest_imaginary_mode(outcar_text, n_atoms=len(structure.sites))

    # Append exactly N lines (no comment lines) after a separating blank line.
    commands = [f'echo \"\" >> {filename}']
    for dx, dy, dz in mode['axis']:
        commands.append(f'echo \"{dx} {dy} {dz}\" >> {filename}')

    block = '\n'.join(commands)
    existing = opts.get('prepend_text')
    if existing:
        if block not in existing:
            opts['prepend_text'] = f'{existing.rstrip()}\n{block}'
    else:
        opts['prepend_text'] = block

    return orm.Dict(dict=opts)


def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate a dimer stage configuration."""
    name = stage['name']

    if 'incar' not in stage:
        raise ValueError(f"Stage '{name}' missing required 'incar' field")

    if 'vibrational_from' not in stage:
        raise ValueError(
            f"Stage '{name}': dimer stages require 'vibrational_from' "
            f"(name of the vibrational analysis VASP stage)"
        )

    vibrational_from = stage['vibrational_from']
    if not isinstance(vibrational_from, str) or not vibrational_from:
        raise ValueError(
            f"Stage '{name}': vibrational_from must be a non-empty stage name string"
        )
    if vibrational_from == name:
        raise ValueError(f"Stage '{name}': vibrational_from cannot reference itself")
    if vibrational_from not in stage_names:
        raise ValueError(
            f"Stage '{name}': vibrational_from='{vibrational_from}' must reference "
            f"a previous stage name"
        )

    incar = stage['incar']
    ibrion_key = next((k for k in incar.keys() if str(k).lower() == 'ibrion'), None)
    if ibrion_key is None:
        raise ValueError(f"Stage '{name}': dimer requires INCAR IBRION=44")
    if int(incar.get(ibrion_key)) != 44:
        raise ValueError(
            f"Stage '{name}': dimer requires INCAR IBRION=44, got {ibrion_key}={incar.get(ibrion_key)!r}"
        )

    # Require restart or restart_from (mutually exclusive) — consistent with vasp brick.
    restart = stage.get('restart')
    restart_from = stage.get('restart_from')

    if restart is not None and restart_from is not None:
        raise ValueError(
            f"Stage '{name}': cannot use both 'restart' and 'restart_from'"
        )
    if 'restart' not in stage and 'restart_from' not in stage:
        raise ValueError(
            f"Stage '{name}' missing 'restart' or 'restart_from' field "
            f"(use restart=None, restart='stage_name', or restart_from=PK)"
        )
    if restart is not None and restart not in stage_names:
        raise ValueError(
            f"Stage '{name}' restart='{restart}' references unknown or "
            f"later stage (must be defined before this stage)"
        )
    if restart_from is not None and not isinstance(restart_from, int):
        raise ValueError(
            f"Stage '{name}': restart_from must be an int PK, got {type(restart_from).__name__}"
        )

    # Validate structure_from (skip if explicit structure provided)
    if 'structure' not in stage:
        structure_from = stage.get('structure_from', 'previous')
        if structure_from not in ('previous', 'input') and structure_from not in stage_names:
            raise ValueError(
                f"Stage '{name}' structure_from='{structure_from}' must be 'previous', "
                f"'input', or a previous stage name"
            )

    # Validate supercell spec
    if 'supercell' in stage:
        spec = stage['supercell']
        if not isinstance(spec, (list, tuple)) or len(spec) != 3:
            raise ValueError(
                f"Stage '{name}' supercell must be [nx, ny, nz], got: {spec}"
            )
        for val in spec:
            if not isinstance(val, int) or val < 1:
                raise ValueError(
                    f"Stage '{name}' supercell values must be positive integers, "
                    f"got: {spec}"
                )

    # Validate fix_type
    fix_type = stage.get('fix_type', None)
    if fix_type is not None:
        valid_fix_types = ('bottom', 'center', 'top')
        if fix_type not in valid_fix_types:
            raise ValueError(
                f"Stage '{name}' fix_type='{fix_type}' must be one of {valid_fix_types}"
            )
        fix_thickness = stage.get('fix_thickness', 0.0)
        if fix_thickness <= 0.0:
            raise ValueError(
                f"Stage '{name}' has fix_type='{fix_type}' but fix_thickness={fix_thickness}. "
                f"fix_thickness must be > 0 when fix_type is set."
            )


def create_stage_tasks(
    wg: WorkGraph,
    stage: Dict[str, Any],
    stage_name: str,
    context: StageContext,
) -> StageTasksResult:
    """Create dimer stage tasks in the WorkGraph."""
    from quantum_lego.core.common.aimd.tasks import create_supercell
    from ..workgraph import _prepare_builder_inputs

    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    base_options = context['options']
    kpoints_spacing = context['base_kpoints_spacing']
    clean_workdir = context['clean_workdir']
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']
    stage_names = context['stage_names']
    i = context['stage_index']
    input_structure = context['input_structure']

    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Determine structure source (same behavior as vasp brick)
    if 'structure' in stage:
        explicit = stage['structure']
        stage_structure = orm.load_node(explicit) if isinstance(explicit, int) else explicit
    elif i == 0:
        stage_structure = input_structure
    elif stage.get('structure_from', 'previous') == 'input':
        stage_structure = input_structure
    elif stage.get('structure_from', 'previous') == 'previous':
        prev_name = stage_names[i - 1]
        prev_stage_type = stage_types[prev_name]
        if prev_stage_type in ('dos', 'batch', 'bader'):
            stage_structure = stage_tasks[prev_name]['structure']
        elif prev_stage_type in ('vasp', 'dimer', 'aimd'):
            stage_structure = stage_tasks[prev_name]['vasp'].outputs.structure
        elif prev_stage_type == 'neb':
            stage_structure = stage_tasks[prev_name]['neb'].outputs.structure
        else:
            raise ValueError(
                f"Stage '{stage['name']}' uses structure_from='previous' "
                f"but previous stage '{prev_name}' is a '{prev_stage_type}' "
                f"stage that doesn't produce a structure. Use an explicit "
                f"'structure_from' pointing to a VASP, AIMD, or NEB stage."
            )
    else:
        from . import resolve_structure_from
        structure_from = stage.get('structure_from', 'previous')
        stage_structure = resolve_structure_from(structure_from, context)

    # Handle supercell transformation
    supercell_task = None
    if 'supercell' in stage:
        supercell_spec = stage['supercell']
        supercell_task = wg.add_task(
            create_supercell,
            name=f'supercell_{stage_name}',
            structure=stage_structure,
            spec=orm.List(list=list(supercell_spec)),
        )
        stage_structure = supercell_task.outputs.result

    # Determine restart source: internal stage name or external PK
    restart = stage.get('restart')
    restart_from = stage.get('restart_from')
    restart_folder = None

    if restart is not None:
        ref_type = stage_types.get(restart, 'vasp')
        if ref_type not in ('vasp', 'dimer'):
            raise ValueError(
                f"Stage '{stage_name}': restart='{restart}' must point to a vasp/dimer stage, got '{ref_type}'"
            )
        restart_folder = stage_tasks[restart]['vasp'].outputs.remote_folder
    elif restart_from is not None:
        from ..utils import prepare_restart_settings
        copy_wavecar = stage.get('copy_wavecar', True)
        copy_chgcar = stage.get('copy_chgcar', False)
        restart_structure, restart_settings = prepare_restart_settings(
            restart_from, copy_wavecar=copy_wavecar, copy_chgcar=copy_chgcar
        )
        restart_folder = restart_settings['folder']
        if restart_settings['incar_additions']:
            from ..common.utils import deep_merge_dicts
            stage['incar'] = deep_merge_dicts(stage['incar'], restart_settings['incar_additions'])
        if i == 0 and 'structure' not in stage and stage.get('structure_from') is None:
            stage_structure = restart_structure

    # Prepare builder inputs
    stage_incar = stage['incar']
    stage_kpoints_spacing = stage.get('kpoints_spacing', kpoints_spacing)
    stage_kpoints_mesh = stage.get('kpoints', None)
    stage_retrieve = stage.get('retrieve', None)
    raw_stage_options = stage.get('options', base_options)
    stage_options = raw_stage_options.get_dict() if isinstance(raw_stage_options, orm.Dict) else raw_stage_options

    stage_fix_type = stage.get('fix_type', None)
    stage_fix_thickness = stage.get('fix_thickness', 0.0)
    stage_fix_elements = stage.get('fix_elements', None)

    is_structure_socket = not isinstance(stage_structure, orm.StructureData)

    if stage_fix_type is not None and not is_structure_socket:
        builder_inputs = _prepare_builder_inputs(
            incar=stage_incar,
            kpoints_spacing=stage_kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping,
            options=stage_options,
            retrieve=stage_retrieve,
            restart_folder=None,
            clean_workdir=clean_workdir,
            kpoints_mesh=stage_kpoints_mesh,
            structure=stage_structure,
            fix_type=stage_fix_type,
            fix_thickness=stage_fix_thickness,
            fix_elements=stage_fix_elements,
        )
    else:
        builder_inputs = _prepare_builder_inputs(
            incar=stage_incar,
            kpoints_spacing=stage_kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping,
            options=stage_options,
            retrieve=stage_retrieve,
            restart_folder=None,
            clean_workdir=clean_workdir,
            kpoints_mesh=stage_kpoints_mesh,
        )

    # If fix_type is set and structure is a socket, compute dynamics at runtime
    dynamics_task = None
    if stage_fix_type is not None and is_structure_socket:
        dynamics_task = wg.add_task(
            compute_dynamics,
            name=f'dynamics_{stage_name}',
            structure=stage_structure,
            fix_type=orm.Str(stage_fix_type),
            fix_thickness=orm.Float(stage_fix_thickness),
            fix_elements=orm.List(list=stage_fix_elements) if stage_fix_elements else None,
        )

    # Build runtime options with dimer axis injection
    vibrational_from = stage['vibrational_from']
    vib_type = stage_types.get(vibrational_from, 'vasp')
    if vib_type != 'vasp':
        raise ValueError(
            f"Stage '{stage_name}': vibrational_from='{vibrational_from}' must point to a VASP stage, got '{vib_type}'"
        )
    vib_retrieved = stage_tasks[vibrational_from]['vasp'].outputs.retrieved
    base_options_node = raw_stage_options if isinstance(raw_stage_options, orm.Dict) else orm.Dict(dict=stage_options)
    injected_options = wg.add_task(
        inject_dimer_axis_prepend_text,
        name=f'dimer_options_{stage_name}',
        options=base_options_node,
        retrieved=vib_retrieved,
        structure=stage_structure,
    )
    builder_inputs['options'] = injected_options.outputs.result

    # Add VASP task (same naming convention as vasp brick)
    vasp_task_kwargs = {
        'name': f'vasp_{stage_name}',
        'structure': stage_structure,
        'code': code,
        **builder_inputs,
    }

    if restart_folder is not None:
        vasp_task_kwargs['restart'] = {'folder': restart_folder}

    if dynamics_task is not None:
        vasp_task_kwargs['dynamics'] = dynamics_task.outputs.result

    if 'dynamics' in stage and dynamics_task is None and 'dynamics' not in vasp_task_kwargs:
        dyn = stage['dynamics']
        vasp_task_kwargs['dynamics'] = dyn if isinstance(dyn, orm.Dict) else orm.Dict(dict=dyn)

    vasp_task = wg.add_task(VaspTask, **vasp_task_kwargs)

    energy_task = wg.add_task(
        extract_total_energy,
        name=f'energy_{stage_name}',
        energies=vasp_task.outputs.misc,
        retrieved=vasp_task.outputs.retrieved,
    )

    return {
        'vasp': vasp_task,
        'energy': energy_task,
        'supercell': supercell_task,
        'input_structure': stage_structure,
        'injected_options': injected_options,
    }


def expose_stage_outputs(
    wg: WorkGraph,
    stage_name: str,
    stage_tasks_result: StageTasksResult,
    namespace_map: Dict[str, str] | None = None,
) -> None:
    """Expose dimer stage outputs on the WorkGraph."""
    vasp_task = stage_tasks_result['vasp']
    energy_task = stage_tasks_result['energy']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.dimer.energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{ns}.dimer.structure', vasp_task.outputs.structure)
        setattr(wg.outputs, f'{ns}.dimer.misc', vasp_task.outputs.misc)
        setattr(wg.outputs, f'{ns}.dimer.remote', vasp_task.outputs.remote_folder)
        setattr(wg.outputs, f'{ns}.dimer.retrieved', vasp_task.outputs.retrieved)
    else:
        setattr(wg.outputs, f'{stage_name}_energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_structure', vasp_task.outputs.structure)
        setattr(wg.outputs, f'{stage_name}_misc', vasp_task.outputs.misc)
        setattr(wg.outputs, f'{stage_name}_remote', vasp_task.outputs.remote_folder)
        setattr(wg.outputs, f'{stage_name}_retrieved', vasp_task.outputs.retrieved)


def get_stage_results(
    wg_node: Any,
    wg_pk: int,
    stage_name: str,
    namespace_map: Dict[str, str] | None = None,
) -> VaspResults:
    """Extract results from a dimer stage in a sequential workflow."""
    from ..results import _extract_energy_from_misc

    result: dict[str, Any] = {
        'energy': None,
        'structure': None,
        'misc': None,
        'remote': None,
        'files': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'dimer',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'dimer', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'energy'):
                    energy_node = brick_ns.energy
                    result['energy'] = energy_node.value if hasattr(energy_node, 'value') else float(energy_node)
                if hasattr(brick_ns, 'structure'):
                    result['structure'] = brick_ns.structure
                if hasattr(brick_ns, 'misc'):
                    misc_node = brick_ns.misc
                    if hasattr(misc_node, 'get_dict'):
                        result['misc'] = misc_node.get_dict()
                if hasattr(brick_ns, 'remote'):
                    result['remote'] = brick_ns.remote
                if hasattr(brick_ns, 'retrieved'):
                    result['files'] = brick_ns.retrieved
        else:
            energy_attr = f'{stage_name}_energy'
            if hasattr(outputs, energy_attr):
                energy_node = getattr(outputs, energy_attr)
                result['energy'] = energy_node.value if hasattr(energy_node, 'value') else float(energy_node)

            struct_attr = f'{stage_name}_structure'
            if hasattr(outputs, struct_attr):
                result['structure'] = getattr(outputs, struct_attr)

            misc_attr = f'{stage_name}_misc'
            if hasattr(outputs, misc_attr):
                misc_node = getattr(outputs, misc_attr)
                if hasattr(misc_node, 'get_dict'):
                    result['misc'] = misc_node.get_dict()

            remote_attr = f'{stage_name}_remote'
            if hasattr(outputs, remote_attr):
                result['remote'] = getattr(outputs, remote_attr)

            retrieved_attr = f'{stage_name}_retrieved'
            if hasattr(outputs, retrieved_attr):
                result['files'] = getattr(outputs, retrieved_attr)

    if result['energy'] is None or result['misc'] is None:
        _extract_sequential_stage_from_workgraph(wg_node, stage_name, result)

    if result['energy'] is None and result['misc'] is not None:
        result['energy'] = _extract_energy_from_misc(result['misc'])

    return result  # type: ignore[return-value]


def _extract_sequential_stage_from_workgraph(
    wg_node: Any,
    stage_name: str,
    result: Dict[str, Any],
) -> None:
    """Fallback: extract stage results by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    vasp_task_name = f'vasp_{stage_name}'
    energy_task_name = f'energy_{stage_name}'

    called = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called.all():
        child_node = link.node
        link_label = link.link_label

        if vasp_task_name in link_label or link_label == vasp_task_name:
            if hasattr(child_node, 'outputs'):
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

    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if energy_task_name in link_label or link_label == energy_task_name:
            created = child_node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result':
                    energy_node = out_link.node
                    if hasattr(energy_node, 'value'):
                        result['energy'] = energy_node.value
                    break


def print_stage_results(index: int, stage_name: str, stage_result: Dict[str, Any]) -> None:
    """Print formatted results for a dimer stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="dimer")

    if stage_result.get('energy') is not None:
        console.print(f"      [bold]Energy:[/bold] [energy]{stage_result['energy']:.6f}[/energy] eV")

    if stage_result.get('structure') is not None:
        struct = stage_result['structure']
        formula = struct.get_formula()
        n_atoms = len(struct.sites)
        console.print(f"      [bold]Structure:[/bold] {formula} [dim]({n_atoms} atoms, PK: {struct.pk})[/dim]")

    if stage_result.get('misc') is not None:
        misc = stage_result['misc']
        run_status = misc.get('run_status', 'N/A')
        max_force = misc.get('maximum_force', None)
        force_str = f", max_force: {max_force:.4f} eV/Å" if max_force else ""
        console.print(f"      [bold]Status:[/bold] {run_status}{force_str}")

    if stage_result.get('remote') is not None:
        console.print(f"      [bold]Remote folder:[/bold] PK [pk]{stage_result['remote'].pk}[/pk]")

    if stage_result.get('files') is not None:
        files = stage_result['files'].list_object_names()
        console.print(f"      [bold]Retrieved:[/bold] [dim]{', '.join(files)}[/dim]")
