"""AIMD brick for the lego module.

Handles ab initio molecular dynamics stages (IBRION=0).
Multi-stage AIMD is achieved by chaining multiple aimd bricks with restart.
"""

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task

from .connections import AIMD_PORTS as PORTS  # noqa: F401
from ..tasks import extract_energy


def _looks_fractional_trajectory_positions(positions, cells, tol: float = 0.25) -> bool:
    """Heuristic: detect fractional trajectory coordinates (0..1 scale)."""
    import numpy as np

    if positions is None or cells is None:
        return False

    if getattr(positions, 'size', 0) == 0:
        return False

    # Typical fractional coordinates stay close to [0, 1], allowing slight drift.
    min_pos = float(np.min(positions))
    max_pos = float(np.max(positions))
    if min_pos < -tol or max_pos > 1.0 + tol:
        return False

    # Require a physically sized cell to avoid false positives.
    cell_lengths = np.linalg.norm(cells, axis=2)
    return float(np.max(cell_lengths)) > 2.0


def _fractional_to_cartesian_positions(positions, cells):
    """Convert fractional positions to Cartesian using per-frame cells."""
    import numpy as np

    return np.einsum('sni,sij->snj', positions, cells, optimize=True)


@task.calcfunction
def ensure_cartesian_trajectory(
    trajectory: orm.TrajectoryData,
) -> orm.TrajectoryData:
    """Ensure trajectory positions are Cartesian.

    aiida-vasp trajectories may provide fractional coordinates. AiiDA's
    TrajectoryData assumes Cartesian positions, so convert when detected.
    """
    import numpy as np

    positions = np.asarray(trajectory.get_positions(), dtype=float)
    cells = trajectory.get_cells()
    stepids = trajectory.get_stepids()
    times = trajectory.get_times()
    velocities = trajectory.get_velocities()
    symbols = list(trajectory.base.attributes.get('symbols', []))

    if _looks_fractional_trajectory_positions(positions, cells):
        positions = _fractional_to_cartesian_positions(positions, cells)

    result = orm.TrajectoryData()
    result.set_trajectory(
        symbols=symbols,
        positions=positions,
        stepids=stepids,
        cells=cells,
        times=times,
        velocities=velocities,
    )

    core_arrays = {'positions', 'cells', 'steps', 'times', 'velocities'}
    for array_name in trajectory.get_arraynames():
        if array_name in core_arrays:
            continue
        result.set_array(array_name, trajectory.get_array(array_name))

    return result


@task.calcfunction
def extract_velocities_from_contcar(
    retrieved: orm.FolderData,
    structure: orm.StructureData,
) -> orm.Dict:
    """Extract velocity vectors from CONTCAR output of VASP AIMD calculation.

    Reads CONTCAR from the retrieved calculation folder and parses the velocity
    block (positions in velocity format: Å/fs). This enables seamless velocity
    continuation in sequential AIMD runs via restart.

    Args:
        retrieved: FolderData from VASP calculation (contains CONTCAR).
        structure: StructureData from VASP output (used for validation).

    Returns:
        orm.Dict with keys:
            - 'velocities': [[vx, vy, vz], ...] array (Å/fs)
            - 'units': 'Angstrom/fs'
            - 'n_atoms': number of atoms
            - 'has_velocities': bool indicating presence of velocity block
    """
    import numpy as np
    from ase.io import read as ase_read
    from io import StringIO

    result = {
        'velocities': [],
        'units': 'Angstrom/fs',
        'n_atoms': len(structure.sites),
        'has_velocities': False,
    }

    try:
        # Read CONTCAR from retrieved folder
        with retrieved.base.repository.open('CONTCAR', 'r') as f:
            contcar_text = f.read()
    except (FileNotFoundError, IOError, OSError):
        # If CONTCAR not found, try POSCAR
        try:
            with retrieved.base.repository.open('POSCAR', 'r') as f:
                contcar_text = f.read()
        except (FileNotFoundError, IOError, OSError):
            # No POSCAR/CONTCAR found, return empty result
            return orm.Dict(dict=result)

    # Parse CONTCAR with ASE to get velocity block
    try:
        # Use ASE to parse the structure
        ase_read(StringIO(contcar_text), format='vasp')  # Validate VASP format

        # Try to extract velocities if present
        # ASE stores velocities in atoms.get_momenta() / atoms.get_masses()
        # or in atoms.arrays['momenta']. VASP CONTCAR format has velocities
        # after the positions in the Direct coordinate block.

        # Parse manually from CONTCAR text to get raw velocities
        lines = contcar_text.strip().split('\n')

        # Find the "Direct" or "Cartesian" line
        coord_line_idx = -1
        for i, line in enumerate(lines):
            if 'direct' in line.lower() or 'cartesian' in line.lower():
                coord_line_idx = i
                break

        if coord_line_idx < 0:
            # No coordinate section found
            return orm.Dict(dict=result)

        # Skip the coordinate line and read positions
        species_counts = _parse_species_counts(lines)
        n_atoms_contcar = sum(species_counts)

        # Positions start after the coordinate line, velocities follow
        positions = []
        velocities = []
        data_start = coord_line_idx + 1

        for i in range(n_atoms_contcar):
            if data_start + i >= len(lines):
                break
            parts = lines[data_start + i].split()
            if len(parts) >= 3:
                positions.append([float(x) for x in parts[:3]])

        # Velocities come after positions (if present)
        # Skip any blank lines between positions and velocities
        velocity_start = data_start + n_atoms_contcar
        while velocity_start < len(lines) and not lines[velocity_start].strip():
            velocity_start += 1

        for i in range(n_atoms_contcar):
            if velocity_start + i >= len(lines):
                break
            line = lines[velocity_start + i].strip()
            if not line:
                # Skip blank lines within velocity block (shouldn't happen)
                continue
            if any(c.isalpha() for c in line[:10] if c not in 'eEdD+-'):
                # Hit a comment/section marker, no velocities
                # (allow 'e'/'E'/'d'/'D' for scientific notation)
                break
            parts = line.split()
            if len(parts) >= 3:
                try:
                    vel = [float(x) for x in parts[:3]]
                    velocities.append(vel)
                except (ValueError, IndexError):
                    break

        if velocities and len(velocities) == n_atoms_contcar:
            result['velocities'] = velocities
            result['has_velocities'] = True

    except Exception:
        # Any parsing error, return empty result
        pass

    return orm.Dict(dict=result)


def _parse_species_counts(lines):
    """Parse species counts from POSCAR-like header.

    Returns list of species counts [n_species0, n_species1, ...].
    """
    # Species counts are typically on a line after the lattice vectors.
    # For VASP 5.x format: line 6 has element names, line 7 has counts
    if len(lines) < 7:
        return []
    try:
        counts_line = lines[6]
        counts = [int(x) for x in counts_line.split()]
        return counts
    except (ValueError, IndexError):
        return []


def _build_aimd_parser_settings(existing: dict | None = None) -> dict:
    """Build parser settings for AIMD stages.

    Uses modern aiida-vasp keys (`include_node`) while keeping legacy
    `add_*` flags for backward compatibility.
    """
    parser_settings = dict(existing or {})

    include_node = list(parser_settings.get('include_node', []))
    for node_name in ('trajectory', 'structure', 'kpoints'):
        if node_name not in include_node:
            include_node.append(node_name)
    parser_settings['include_node'] = include_node

    # Keep legacy flags for compatibility with older parser configurations.
    parser_settings['add_energy'] = True
    parser_settings['add_trajectory'] = True
    parser_settings['add_structure'] = True
    parser_settings['add_kpoints'] = True

    return parser_settings


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate an AIMD stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    # tebeg required and must be > 0
    if 'tebeg' not in stage:
        raise ValueError(f"Stage '{name}' missing required 'tebeg' field (temperature in K)")
    tebeg = stage['tebeg']
    if not isinstance(tebeg, (int, float)) or tebeg <= 0:
        raise ValueError(f"Stage '{name}' tebeg={tebeg} must be a positive number (temperature in K)")

    # nsw required and must be > 0
    if 'nsw' not in stage:
        raise ValueError(f"Stage '{name}' missing required 'nsw' field (number of MD steps)")
    nsw = stage['nsw']
    if not isinstance(nsw, int) or nsw <= 0:
        raise ValueError(f"Stage '{name}' nsw={nsw} must be a positive integer")

    # potim if present must be > 0
    if 'potim' in stage:
        potim = stage['potim']
        if not isinstance(potim, (int, float)) or potim <= 0:
            raise ValueError(f"Stage '{name}' potim={potim} must be a positive number (timestep in fs)")

    # Require restart (must be None or a previous stage name)
    if 'restart' not in stage:
        raise ValueError(f"Stage '{name}' missing required 'restart' field (use None or a stage name)")

    restart = stage['restart']
    if restart is not None:
        if restart not in stage_names:
            raise ValueError(
                f"Stage '{name}' restart='{restart}' references unknown or "
                f"later stage (must be defined before this stage)"
            )

    # Validate structure_from
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


def create_stage_tasks(wg, stage, stage_name, context):
    """Create AIMD stage tasks in the WorkGraph.

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

    # Determine structure source (same auto pattern as VASP brick)
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
        elif prev_stage_type in ('vasp', 'aimd'):
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
            spec=orm.List(list=supercell_spec),
        )
        stage_structure = supercell_task.outputs.result

    # Determine restart source (None or stage name)
    # For AIMD stages, this enables electronic structure restart (WAVECAR/CHGCAR)
    # Velocities are now also injected when restarting from a previous AIMD stage
    restart = stage['restart']
    restart_folder = None
    velocities_socket = None
    inject_velocities = False

    if restart is not None:
        # Validate that restart stage exists
        if restart not in stage_tasks:
            raise ValueError(
                f"Stage '{stage_name}' references restart='{restart}', "
                f"but this stage has not been processed yet or does not exist. "
                f"Available stages: {list(stage_tasks.keys())}"
            )

        restart_folder = stage_tasks[restart]['vasp'].outputs.remote_folder
        # Check if restarting from a previous AIMD stage and no supercell change
        # In that case, we should inject velocities for seamless MD continuation
        prev_stage_type = stage_types.get(restart)
        if prev_stage_type == 'aimd' and 'supercell' not in stage:
            # Ensure the restart stage actually has velocities output
            if 'velocities' not in stage_tasks[restart]:
                raise ValueError(
                    f"Stage '{stage_name}' cannot inject velocities from restart "
                    f"stage '{restart}' because it has no 'velocities' output. "
                    f"Available outputs: {list(stage_tasks[restart].keys())}"
                )
            inject_velocities = True
            velocities_socket = stage_tasks[restart]['velocities'].outputs.result
        elif prev_stage_type == 'aimd' and 'supercell' in stage:
            # AIMD → AIMD with supercell change: velocities would be invalid
            # Log this decision for transparency
            import sys
            print(
                f"[AIMD Velocity Injection] Stage '{stage_name}' restarts from "
                f"'{restart}' but has supercell change [{stage['supercell']}]. "
                f"Velocities NOT injected (structure mismatch).",
                file=sys.stderr
            )

    # Build INCAR: merge user incar with AIMD-specific params
    stage_incar = dict(stage.get('incar', {}))
    stage_incar['ibrion'] = 0  # Force MD mode
    stage_incar['lvel'] = True  # CRITICAL: Write velocities to CONTCAR
    stage_incar['tebeg'] = stage['tebeg']
    stage_incar['nsw'] = stage['nsw']
    stage_incar['teend'] = stage.get('teend', stage['tebeg'])
    if 'potim' in stage:
        stage_incar['potim'] = stage['potim']
    if 'mdalgo' in stage:
        stage_incar['mdalgo'] = stage['mdalgo']
    if 'smass' in stage:
        stage_incar['smass'] = stage['smass']

    stage_kpoints_spacing = stage.get('kpoints_spacing', kpoints_spacing)
    stage_kpoints_mesh = stage.get('kpoints', None)
    stage_retrieve = stage.get('retrieve', None)

    # Prepare builder inputs
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

    # Ensure parser settings request trajectory output for AIMD.
    settings_dict = builder_inputs['settings'].get_dict() if 'settings' in builder_inputs else {}
    existing_parser = settings_dict.get('parser_settings', {})
    settings_dict['parser_settings'] = _build_aimd_parser_settings(existing_parser)
    builder_inputs['settings'] = orm.Dict(dict=settings_dict)

    # Create POSCAR with velocities task if needed
    poscar_file_task = None
    if inject_velocities:
        if velocities_socket is None:
            raise ValueError(
                f"Stage '{stage_name}' has inject_velocities=True but "
                f"velocities_socket is None. This should not happen. "
                f"Check restart stage '{restart}' has a 'velocities' output."
            )
        from ..tasks import create_poscar_file_with_velocities
        poscar_file_task = wg.add_task(
            create_poscar_file_with_velocities,
            name=f'poscar_file_{stage_name}',
            structure=stage_structure,
            velocities_dict=velocities_socket,
        )
        import sys
        print(
            f"[AIMD Velocity Injection] Stage '{stage_name}' will inject "
            f"velocities from '{restart}' via POSCAR file.",
            file=sys.stderr
        )
    else:
        if restart is not None and 'velocities' in stage_tasks[restart]:
            import sys
            print(
                f"[AIMD Velocity Injection] Stage '{stage_name}' does NOT inject "
                f"velocities (restart={restart}, inject_velocities={inject_velocities}).",
                file=sys.stderr
            )

    # Select WorkChain based on whether velocity injection is needed
    if inject_velocities:
        # Use AimdVaspWorkChain which supports poscar_file input
        from ..calcs import AimdVaspWorkChain
        SelectedVaspTask = task(AimdVaspWorkChain)
    else:
        # Use standard VaspWorkChain
        SelectedVaspTask = VaspTask

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

    # Add poscar_file if velocity injection is enabled
    if inject_velocities:
        if poscar_file_task is None:
            raise ValueError(
                f"Stage '{stage_name}' has inject_velocities=True but "
                f"poscar_file_task was not created. This should not happen."
            )
        vasp_task_kwargs['poscar_file'] = poscar_file_task.outputs.result

    vasp_task = wg.add_task(SelectedVaspTask, **vasp_task_kwargs)

    # Add energy extraction task
    energy_task = wg.add_task(
        extract_energy,
        name=f'energy_{stage_name}',
        misc=vasp_task.outputs.misc,
        retrieved=vasp_task.outputs.retrieved,
    )

    # Add velocity extraction task (extract velocities from CONTCAR for next stage restart)
    velocity_task = wg.add_task(
        extract_velocities_from_contcar,
        name=f'velocities_{stage_name}',
        retrieved=vasp_task.outputs.retrieved,
        structure=vasp_task.outputs.structure,
    )

    # Normalize trajectory coordinates for reliable downstream visualization/processing.
    trajectory_task = wg.add_task(
        ensure_cartesian_trajectory,
        name=f'trajectory_{stage_name}',
        trajectory=vasp_task.outputs.trajectory,
    )

    return {
        'vasp': vasp_task,
        'energy': energy_task,
        'velocities': velocity_task,
        'trajectory': trajectory_task,
        'supercell': supercell_task,
        'poscar_file': poscar_file_task,
        'input_structure': stage_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose AIMD stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string.
    """
    vasp_task = stage_tasks_result['vasp']
    energy_task = stage_tasks_result['energy']

    velocity_task = stage_tasks_result['velocities']
    trajectory_task = stage_tasks_result['trajectory']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.vasp.energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{ns}.vasp.structure', vasp_task.outputs.structure)
        setattr(wg.outputs, f'{ns}.vasp.misc', vasp_task.outputs.misc)
        setattr(wg.outputs, f'{ns}.vasp.remote', vasp_task.outputs.remote_folder)
        setattr(wg.outputs, f'{ns}.vasp.retrieved', vasp_task.outputs.retrieved)
        setattr(wg.outputs, f'{ns}.vasp.trajectory', trajectory_task.outputs.result)
        setattr(wg.outputs, f'{ns}.vasp.velocities', velocity_task.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_structure', vasp_task.outputs.structure)
        setattr(wg.outputs, f'{stage_name}_misc', vasp_task.outputs.misc)
        setattr(wg.outputs, f'{stage_name}_remote', vasp_task.outputs.remote_folder)
        setattr(wg.outputs, f'{stage_name}_retrieved', vasp_task.outputs.retrieved)
        setattr(wg.outputs, f'{stage_name}_trajectory', trajectory_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_velocities', velocity_task.outputs.result)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from an AIMD stage in a sequential workflow.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the AIMD stage.
        namespace_map: Dict mapping output group to namespace string.

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
        'trajectory': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'aimd',
    }

    # Try to access via WorkGraph outputs (exposed outputs)
    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
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
                if hasattr(brick_ns, 'trajectory'):
                    result['trajectory'] = brick_ns.trajectory
        else:
            energy_attr = f'{stage_name}_energy'
            if hasattr(outputs, energy_attr):
                energy_node = getattr(outputs, energy_attr)
                if hasattr(energy_node, 'value'):
                    result['energy'] = energy_node.value
                else:
                    result['energy'] = float(energy_node)

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

            traj_attr = f'{stage_name}_trajectory'
            if hasattr(outputs, traj_attr):
                result['trajectory'] = getattr(outputs, traj_attr)

    # Fallback: Traverse links to find VaspWorkChain outputs (for stored nodes)
    if result['energy'] is None or result['misc'] is None:
        _extract_sequential_stage_from_workgraph(wg_node, stage_name, result)

    # Extract energy from misc if not found directly
    if result['energy'] is None and result['misc'] is not None:
        result['energy'] = _extract_energy_from_misc(result['misc'])

    return result


def _extract_sequential_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
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


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for an AIMD stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    print(f"  [{index}] {stage_name} (AIMD)")

    if stage_result['energy'] is not None:
        print(f"      Energy: {stage_result['energy']:.6f} eV")

    if stage_result['structure'] is not None:
        struct = stage_result['structure']
        formula = struct.get_formula()
        n_atoms = len(struct.sites)
        print(f"      Structure: {formula} ({n_atoms} atoms, PK: {struct.pk})")

    if stage_result['misc'] is not None:
        misc = stage_result['misc']
        run_status = misc.get('run_status', 'N/A')
        print(f"      Status: {run_status}")

    if stage_result['remote'] is not None:
        print(f"      Remote folder: PK {stage_result['remote'].pk}")

    if stage_result['files'] is not None:
        files = stage_result['files'].list_object_names()
        print(f"      Retrieved: {', '.join(files)}")
