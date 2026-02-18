"""VASP brick for the lego module.

Handles standard VASP calculation stages: relaxation, SCF, etc.
"""

from typing import Dict, Set, Any

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task, WorkGraph

from .connections import VASP_PORTS as PORTS  # noqa: F401
from ..common.utils import extract_total_energy
from ..tasks import compute_dynamics
from ..types import StageContext, StageTasksResult, VaspResults


# Recommended INCAR defaults for vibrational analysis (IBRION=5) stages.
# Merged with user-supplied INCAR; user values always take precedence.
#
# Why these values:
#   EDIFF=1e-6  — tight electronic convergence is needed to get accurate
#                 forces for reliable mode frequencies; 1e-5 can produce
#                 spurious low-frequency imaginary modes
#   NFREE=2     — central differences (more accurate than forward differences)
#   POTIM=0.02  — displacement step in Å; 0.02 is a good default for most
#                 systems (reduce to 0.01–0.015 for soft/floppy modes)
#   NSW=1       — single SCF + finite-difference displacements (standard for IBRION=5)
#   NWRITE=3    — write eigenvectors after division by SQRT(mass); required if
#                 OUTCAR is used as input for a subsequent dimer calculation
_VIB_INCAR_DEFAULTS: dict = {
    'ibrion': 5,
    'ediff': 1e-6,
    'nfree': 2,
    'potim': 0.02,
    'nsw': 1,
    'nwrite': 3,
}


def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate a VASP stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'incar' not in stage:
        raise ValueError(f"Stage '{name}' missing required 'incar' field")

    # Require restart or restart_from (mutually exclusive)
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

    if restart is not None:
        if restart not in stage_names:
            raise ValueError(
                f"Stage '{name}' restart='{restart}' references unknown or "
                f"later stage (must be defined before this stage)"
            )

    if restart_from is not None and not isinstance(restart_from, int):
        raise ValueError(
            f"Stage '{name}': restart_from must be an int PK, got {type(restart_from).__name__}"
        )

    # Validate structure_from for VASP stages (skip if explicit structure provided)
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

        # If fix_type is set, fix_thickness must be positive
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
    context: StageContext
) -> StageTasksResult:
    """Create VASP stage tasks in the WorkGraph.

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context (code, options, stage_tasks, etc.).

    Returns:
        Dict with task references for later stages.
    """
    from quantum_lego.core.common.aimd.tasks import create_supercell
    from ..workgraph import _prepare_builder_inputs

    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    options = context['options']
    kpoints_spacing = context['base_kpoints_spacing']
    clean_workdir = context['clean_workdir']
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']
    stage_names = context['stage_names']
    i = context['stage_index']
    input_structure = context['input_structure']

    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Determine structure source
    if 'structure' in stage:
        # Explicit structure provided in stage config
        explicit = stage['structure']
        stage_structure = orm.load_node(explicit) if isinstance(explicit, int) else explicit
    elif i == 0:
        # First stage always uses input structure
        stage_structure = input_structure
    elif stage.get('structure_from', 'previous') == 'input':
        stage_structure = input_structure
    elif stage.get('structure_from', 'previous') == 'previous':
        # Use output structure from previous stage
        prev_name = stage_names[i - 1]
        prev_stage_type = stage_types[prev_name]
        if prev_stage_type in ('dos', 'batch', 'bader'):
            stage_structure = stage_tasks[prev_name]['structure']
        elif prev_stage_type in ('vasp', 'aimd'):
            stage_structure = stage_tasks[prev_name]['vasp'].outputs.structure
        elif prev_stage_type == 'dimer':
            # Use clean CONTCAR structure from the dimer stage
            stage_structure = stage_tasks[prev_name]['contcar_structure'].outputs.result
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
        # Use output structure from specific stage
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
            spec=orm.List(list=supercell_spec),
        )
        stage_structure = supercell_task.outputs.result

    # Determine restart source: internal stage name or external PK
    restart = stage.get('restart')
    restart_from = stage.get('restart_from')
    restart_folder = None

    if restart is not None:
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
        # Use restart structure if no explicit structure source
        if i == 0 and 'structure' not in stage and stage.get('structure_from') is None:
            stage_structure = restart_structure

    # Prepare builder inputs for this stage
    # Apply vibrational defaults when IBRION=5 (user values take precedence)
    raw_incar = stage['incar']
    if int(raw_incar.get('ibrion', -1)) == 5:
        from ..common.utils import deep_merge_dicts
        stage_incar = deep_merge_dicts(_VIB_INCAR_DEFAULTS, raw_incar)
    else:
        stage_incar = raw_incar
    stage_kpoints_spacing = stage.get('kpoints_spacing', kpoints_spacing)
    stage_kpoints_mesh = stage.get('kpoints', None)
    stage_retrieve = stage.get('retrieve', None)

    # Get fix parameters for this stage
    stage_fix_type = stage.get('fix_type', None)
    stage_fix_thickness = stage.get('fix_thickness', 0.0)
    stage_fix_elements = stage.get('fix_elements', None)

    # Determine if we can compute dynamics at build time
    is_structure_socket = not isinstance(stage_structure, orm.StructureData)

    # Prepare builder inputs
    if stage_fix_type is not None and not is_structure_socket:
        builder_inputs = _prepare_builder_inputs(
            incar=stage_incar,
            kpoints_spacing=stage_kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping,
            options=options,
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
            options=options,
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

    # If structure comes from a dimer stage, re-inject its CONTCAR axis lines into POSCAR.
    # VASP writes the dimer direction as extra lines in CONTCAR (for IBRION=44 restart and
    # IBRION=5 verification), but ASE strips them when converting to StructureData.
    dimer_source_name = None
    structure_from_key = stage.get('structure_from', 'previous')
    if structure_from_key == 'previous' and i > 0:
        prev_name = stage_names[i - 1]
        if stage_types.get(prev_name) == 'dimer':
            dimer_source_name = prev_name
    elif structure_from_key not in ('previous', 'input') and stage_types.get(structure_from_key) == 'dimer':
        dimer_source_name = structure_from_key

    if dimer_source_name is not None:
        from .dimer import inject_contcar_axis_prepend_text
        dimer_retrieved = stage_tasks[dimer_source_name]['vasp'].outputs.retrieved
        contcar_opts_task = wg.add_task(
            inject_contcar_axis_prepend_text,
            name=f'contcar_axis_{stage_name}',
            options=builder_inputs['options'],
            retrieved=dimer_retrieved,
        )
        builder_inputs['options'] = contcar_opts_task.outputs.result

    # Add VASP task
    vasp_task_kwargs = {
        'name': f'vasp_{stage_name}',
        'structure': stage_structure,
        'code': code,
        **builder_inputs
    }

    # Add restart if available
    if restart_folder is not None:
        vasp_task_kwargs['restart'] = {'folder': restart_folder}

    # Add dynamics from calcfunction if computed at runtime
    if dynamics_task is not None:
        vasp_task_kwargs['dynamics'] = dynamics_task.outputs.result

    # Explicit dynamics override (for frequency calculations etc.)
    if 'dynamics' in stage and dynamics_task is None and 'dynamics' not in vasp_task_kwargs:
        dyn = stage['dynamics']
        if isinstance(dyn, orm.Dict):
            vasp_task_kwargs['dynamics'] = dyn
        else:
            vasp_task_kwargs['dynamics'] = orm.Dict(dict=dyn)

    vasp_task = wg.add_task(VaspTask, **vasp_task_kwargs)

    # Add energy extraction task
    energy_task = wg.add_task(
        extract_total_energy,
        name=f'energy_{stage_name}',
        energies=vasp_task.outputs.misc,
        retrieved=vasp_task.outputs.retrieved,
    )

    # For vibrational analysis stages (IBRION=5), add a task that parses
    # imaginary modes from OUTCAR and produces an AiiDA Dict with TS diagnostics.
    vibrational_modes_task = None
    if int(stage_incar.get('ibrion', -1)) == 5:
        from .vibrational_utils import parse_vibrational_modes
        vibrational_modes_task = wg.add_task(
            parse_vibrational_modes,
            name=f'vibrational_modes_{stage_name}',
            retrieved=vasp_task.outputs.retrieved,
        )

    return {
        'vasp': vasp_task,
        'energy': energy_task,
        'supercell': supercell_task,
        'input_structure': stage_structure,
        'vibrational_modes': vibrational_modes_task,
    }


def expose_stage_outputs(
    wg: WorkGraph,
    stage_name: str,
    stage_tasks_result: StageTasksResult,
    namespace_map: Dict[str, str] = None
) -> None:
    """Expose VASP stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    vasp_task = stage_tasks_result['vasp']
    energy_task = stage_tasks_result['energy']
    vibrational_modes_task = stage_tasks_result.get('vibrational_modes')

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.vasp.energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{ns}.vasp.structure', vasp_task.outputs.structure)
        setattr(wg.outputs, f'{ns}.vasp.misc', vasp_task.outputs.misc)
        setattr(wg.outputs, f'{ns}.vasp.remote', vasp_task.outputs.remote_folder)
        setattr(wg.outputs, f'{ns}.vasp.retrieved', vasp_task.outputs.retrieved)
        if vibrational_modes_task is not None:
            setattr(wg.outputs, f'{ns}.vasp.vibrational_modes', vibrational_modes_task.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_structure', vasp_task.outputs.structure)
        setattr(wg.outputs, f'{stage_name}_misc', vasp_task.outputs.misc)
        setattr(wg.outputs, f'{stage_name}_remote', vasp_task.outputs.remote_folder)
        setattr(wg.outputs, f'{stage_name}_retrieved', vasp_task.outputs.retrieved)
        if vibrational_modes_task is not None:
            setattr(wg.outputs, f'{stage_name}_vibrational_modes', vibrational_modes_task.outputs.result)


def get_stage_results(
    wg_node: Any,
    wg_pk: int,
    stage_name: str,
    namespace_map: Dict[str, str] = None
) -> VaspResults:
    """Extract results from a VASP stage in a sequential workflow.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the VASP stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: energy, structure, misc, remote, files, pk, stage, type.
    """
    from ..results import _extract_energy_from_misc

    result = {
        'energy': None,
        'structure': None,
        'misc': None,
        'remote': None,
        'files': None,
        'vibrational_modes': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'vasp',
    }

    # Try to access via WorkGraph outputs (exposed outputs)
    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            # Namespaced outputs: access via stage_ns.vasp.output
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'vasp', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'energy'):
                    energy_node = brick_ns.energy
                    if hasattr(energy_node, 'value'):
                        result['energy'] = energy_node.value
                    else:
                        result['energy'] = float(energy_node)
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
                if hasattr(brick_ns, 'vibrational_modes'):
                    vm_node = brick_ns.vibrational_modes
                    if hasattr(vm_node, 'get_dict'):
                        result['vibrational_modes'] = vm_node.get_dict()
        else:
            # Flat naming fallback
            # Energy
            energy_attr = f'{stage_name}_energy'
            if hasattr(outputs, energy_attr):
                energy_node = getattr(outputs, energy_attr)
                if hasattr(energy_node, 'value'):
                    result['energy'] = energy_node.value
                else:
                    result['energy'] = float(energy_node)

            # Structure
            struct_attr = f'{stage_name}_structure'
            if hasattr(outputs, struct_attr):
                result['structure'] = getattr(outputs, struct_attr)

            # Misc
            misc_attr = f'{stage_name}_misc'
            if hasattr(outputs, misc_attr):
                misc_node = getattr(outputs, misc_attr)
                if hasattr(misc_node, 'get_dict'):
                    result['misc'] = misc_node.get_dict()

            # Remote folder
            remote_attr = f'{stage_name}_remote'
            if hasattr(outputs, remote_attr):
                result['remote'] = getattr(outputs, remote_attr)

            # Retrieved files
            retrieved_attr = f'{stage_name}_retrieved'
            if hasattr(outputs, retrieved_attr):
                result['files'] = getattr(outputs, retrieved_attr)

            # Vibrational modes (IBRION=5 stages only)
            vm_attr = f'{stage_name}_vibrational_modes'
            if hasattr(outputs, vm_attr):
                vm_node = getattr(outputs, vm_attr)
                if hasattr(vm_node, 'get_dict'):
                    result['vibrational_modes'] = vm_node.get_dict()

    # Fallback: Traverse links to find VaspWorkChain outputs (for stored nodes)
    if result['energy'] is None or result['misc'] is None:
        _extract_sequential_stage_from_workgraph(wg_node, stage_name, result)

    # Extract energy from misc if not found directly
    if result['energy'] is None and result['misc'] is not None:
        result['energy'] = _extract_energy_from_misc(result['misc'])

    return result


def _extract_sequential_stage_from_workgraph(
    wg_node: Any,
    stage_name: str,
    result: Dict[str, Any]
) -> None:
    """Extract stage results by traversing WorkGraph links.

    Args:
        wg_node: The WorkGraph node.
        stage_name: Name of the stage to extract.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    vasp_task_name = f'vasp_{stage_name}'
    energy_task_name = f'energy_{stage_name}'

    # Traverse CALL_WORK links to find VaspWorkChain
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

    # Traverse CALL_CALC links to find energy calcfunction
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
    """Print formatted results for a VASP stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="vasp")

    if stage_result['energy'] is not None:
        console.print(f"      [bold]Energy:[/bold] [energy]{stage_result['energy']:.6f}[/energy] eV")

    if stage_result['structure'] is not None:
        struct = stage_result['structure']
        formula = struct.get_formula()
        n_atoms = len(struct.sites)
        console.print(f"      [bold]Structure:[/bold] {formula} [dim]({n_atoms} atoms, PK: {struct.pk})[/dim]")

    if stage_result['misc'] is not None:
        misc = stage_result['misc']
        run_status = misc.get('run_status', 'N/A')
        max_force = misc.get('maximum_force', None)
        force_str = f", max_force: {max_force:.4f} eV/Å" if max_force else ""
        console.print(f"      [bold]Status:[/bold] {run_status}{force_str}")

    if stage_result['remote'] is not None:
        console.print(f"      [bold]Remote folder:[/bold] PK [pk]{stage_result['remote'].pk}[/pk]")

    if stage_result['files'] is not None:
        files = stage_result['files'].list_object_names()
        console.print(f"      [bold]Retrieved:[/bold] [dim]{', '.join(files)}[/dim]")

    vm = stage_result.get('vibrational_modes')
    if vm:
        status = vm.get('saddle_point_status', 'unknown')
        color = {'confirmed': 'green', 'failed': 'red', 'uncertain': 'yellow'}.get(status, 'dim')
        console.print(f"      [bold]Vib. modes:[/bold] [{color}]{vm.get('assessment', status)}[/{color}]")
        n_large = vm.get('n_large_imaginary', 0)
        n_trans = vm.get('n_translational_artifacts', 0)
        ts_freq = vm.get('ts_frequency_cm1')
        if n_large or n_trans:
            parts = []
            if n_large:
                parts.append(f"{n_large} TS mode(s)")
                if ts_freq:
                    parts[-1] += f" @ {ts_freq:.1f} cm⁻¹"
            if n_trans:
                parts.append(f"{n_trans} translational artefact(s) (<5 cm⁻¹)")
            console.print(f"      [bold]Imaginary modes:[/bold] [dim]{', '.join(parts)}[/dim]")
