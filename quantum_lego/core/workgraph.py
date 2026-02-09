"""WorkGraph builders for the lego module.

This module provides lightweight, incremental VASP calculation wrappers
for exploratory work. The goal is simplicity: submit a calculation,
check results, decide next step, optionally restart.
"""

import typing as t
import time

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task

from .tasks import extract_energy, compute_dynamics
from .utils import prepare_restart_settings, get_status
from .retrieve_defaults import build_vasp_retrieve
from .common.utils import deep_merge_dicts


def quick_vasp(
    structure: t.Union[orm.StructureData, int] = None,
    code_label: str = None,
    incar: dict = None,
    kpoints_spacing: float = 0.03,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    retrieve: t.List[str] = None,
    restart_from: int = None,
    copy_wavecar: bool = True,
    copy_chgcar: bool = False,
    name: str = 'quick_vasp',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> int:
    """
    Submit a single VASP calculation with minimal boilerplate.

    This is the primary entry point for exploratory VASP calculations.
    Specify INCAR parameters directly - no presets, maximum flexibility.

    Args:
        structure: StructureData or PK. If restart_from is provided, this is optional.
        code_label: VASP code label (e.g., 'VASP-6.5.1@localwork')
        incar: INCAR parameters dict (e.g., {'NSW': 100, 'IBRION': 2})
        kpoints_spacing: K-points spacing in A^-1 (default: 0.03)
        potential_family: POTCAR family (default: 'PBE')
        potential_mapping: Element to POTCAR mapping (e.g., {'Sn': 'Sn_d', 'O': 'O'})
        options: Scheduler options dict with 'resources' key
        retrieve: Additional files to retrieve (merged with defaults)
        restart_from: PK of previous calculation to restart from
        copy_wavecar: Copy WAVECAR from restart_from (sets ISTART=1)
        copy_chgcar: Copy CHGCAR from restart_from (sets ICHARG=1)
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean the work directory after completion

    Returns:
        PK of the submitted WorkGraph

    Example:
        >>> pk = quick_vasp(
        ...     structure=my_structure,
        ...     code_label='VASP-6.5.1@localwork',
        ...     incar={'NSW': 100, 'IBRION': 2, 'ISIF': 3},
        ...     kpoints_spacing=0.03,
        ...     potential_family='PBE',
        ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
        ...     retrieve=['CONTCAR', 'CHGCAR'],
        ...     name='sno2_relax',
        ... )

        >>> # Restart from previous calculation
        >>> pk2 = quick_vasp(
        ...     restart_from=pk,
        ...     code_label='VASP-6.5.1@localwork',
        ...     incar={'NSW': 0, 'NEDOS': 2000},
        ...     retrieve=['DOSCAR'],
        ...     name='sno2_dos',
        ... )
    """
    # Handle restart
    restart_folder = None
    incar_additions = {}

    if restart_from is not None:
        restart_structure, restart_settings = prepare_restart_settings(
            restart_from,
            copy_wavecar=copy_wavecar,
            copy_chgcar=copy_chgcar,
        )
        if structure is None:
            structure = restart_structure
        restart_folder = restart_settings['folder']
        incar_additions = restart_settings['incar_additions']

    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required (or provide restart_from)")
    if code_label is None:
        raise ValueError("code_label is required")
    if incar is None:
        raise ValueError("incar is required - always specify INCAR parameters explicitly")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Load structure if PK
    if isinstance(structure, int):
        structure = orm.load_node(structure)

    # Merge restart INCAR additions
    if incar_additions:
        incar = deep_merge_dicts(incar, incar_additions)

    # Load code
    code = orm.load_code(code_label)

    # Get VASP workchain and wrap as task
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    # Prepare builder inputs
    builder_inputs = _prepare_builder_inputs(
        incar=incar,
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping or {},
        options=options,
        retrieve=retrieve,
        restart_folder=restart_folder,
        clean_workdir=clean_workdir,
    )

    # Add VASP task
    vasp_task = wg.add_task(
        VaspTask,
        name='vasp_calc',
        structure=structure,
        code=code,
        **builder_inputs
    )

    # Add energy extraction task
    energy_task = wg.add_task(
        extract_energy,
        name='extract_energy',
        misc=vasp_task.outputs.misc,
        retrieved=vasp_task.outputs.retrieved,
    )

    # Set WorkGraph outputs
    wg.outputs.energy = energy_task.outputs.result
    wg.outputs.structure = vasp_task.outputs.structure
    wg.outputs.misc = vasp_task.outputs.misc
    wg.outputs.retrieved = vasp_task.outputs.retrieved

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    return wg.pk


def quick_vasp_batch(
    structures: t.Dict[str, t.Union[orm.StructureData, int]],
    code_label: str,
    incar: dict,
    kpoints_spacing: float = 0.03,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    retrieve: t.List[str] = None,
    incar_overrides: t.Dict[str, dict] = None,
    max_concurrent_jobs: int = None,
    name: str = 'quick_vasp_batch',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> t.Dict[str, int]:
    """
    Submit multiple VASP calculations with the same base settings.

    Useful for Fukui-style calculations or comparing different structures
    with consistent computational parameters.

    Args:
        structures: Dict mapping keys to StructureData or PKs
                   (e.g., {'clean': s1, 'defect': s2})
        code_label: VASP code label
        incar: Base INCAR parameters dict (applied to all calculations)
        kpoints_spacing: K-points spacing in A^-1 (default: 0.03)
        potential_family: POTCAR family (default: 'PBE')
        potential_mapping: Element to POTCAR mapping
        options: Scheduler options dict
        retrieve: Additional files to retrieve (merged with defaults)
        incar_overrides: Per-structure INCAR overrides
                        (e.g., {'delta_0.05': {'NELECT': 191.95}})
        max_concurrent_jobs: Maximum parallel VASP jobs (default: unlimited)
        name: WorkGraph name
        wait: If True, block until all calculations finish
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean work directories after completion

    Returns:
        Dict mapping structure keys to individual WorkGraph PKs

    Example:
        >>> # Same settings for all structures
        >>> pks = quick_vasp_batch(
        ...     structures={'clean': s1, 'defect': s2},
        ...     code_label='VASP-6.5.1@localwork',
        ...     incar={'NSW': 100},
        ...     retrieve=['CONTCAR'],
        ...     max_concurrent_jobs=2,
        ... )

        >>> # Fukui-style with per-structure INCAR overrides
        >>> pks = quick_vasp_batch(
        ...     structures={'delta_0.00': s, 'delta_0.05': s, 'delta_0.10': s},
        ...     incar={'NSW': 0, 'ALGO': 'All'},
        ...     incar_overrides={
        ...         'delta_0.05': {'NELECT': 191.95},
        ...         'delta_0.10': {'NELECT': 191.90},
        ...     },
        ...     retrieve=['CHGCAR'],
        ...     max_concurrent_jobs=4,
        ... )
    """
    # Validate inputs
    if not structures:
        raise ValueError("structures dict cannot be empty")
    if code_label is None:
        raise ValueError("code_label is required")
    if incar is None:
        raise ValueError("incar is required - always specify INCAR parameters explicitly")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    if incar_overrides is None:
        incar_overrides = {}

    # Load code
    code = orm.load_code(code_label)

    # Get VASP workchain and wrap as task
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    if max_concurrent_jobs is not None:
        wg.max_number_jobs = max_concurrent_jobs

    # Track task names for each key
    task_map = {}

    # Process each structure
    for key, struct_input in structures.items():
        # Load structure if PK
        if isinstance(struct_input, int):
            struct = orm.load_node(struct_input)
        else:
            struct = struct_input

        # Merge base INCAR with per-structure overrides
        if key in incar_overrides:
            merged_incar = deep_merge_dicts(incar, incar_overrides[key])
        else:
            merged_incar = incar

        # Prepare builder inputs
        builder_inputs = _prepare_builder_inputs(
            incar=merged_incar,
            kpoints_spacing=kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping or {},
            options=options,
            retrieve=retrieve,
            restart_folder=None,
            clean_workdir=clean_workdir,
        )

        # Add VASP task for this structure
        task_name = f'vasp_{key}'
        vasp_task = wg.add_task(
            VaspTask,
            name=task_name,
            structure=struct,
            code=code,
            **builder_inputs
        )

        # Add energy extraction task
        energy_task_name = f'energy_{key}'
        wg.add_task(
            extract_energy,
            name=energy_task_name,
            misc=vasp_task.outputs.misc,
            retrieved=vasp_task.outputs.retrieved,
        )

        task_map[key] = {
            'vasp_task': task_name,
            'energy_task': energy_task_name,
        }

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    # Return the WorkGraph PK with keys for reference
    # Users can extract individual results using get_batch_results_from_workgraph
    return {
        '__workgraph_pk__': wg.pk,
        '__task_map__': task_map,
        **{key: wg.pk for key in structures.keys()},
    }


def _builder_to_dict(builder) -> dict:
    """
    Recursively convert a ProcessBuilder to a plain dict.

    ProcessBuilderNamespace objects need to be converted to regular dicts
    for use with WorkGraph add_task().

    Args:
        builder: ProcessBuilder or ProcessBuilderNamespace

    Returns:
        Plain dict with all nested namespaces converted
    """
    from aiida.engine.processes.builder import ProcessBuilderNamespace

    result = {}
    for key, value in builder.items():
        if isinstance(value, ProcessBuilderNamespace):
            # Recursively convert nested namespaces
            nested = _builder_to_dict(value)
            if nested:  # Only include non-empty namespaces
                result[key] = nested
        elif value is not None:
            result[key] = value
    return result


def _prepare_builder_inputs(
    incar: dict,
    kpoints_spacing: float,
    potential_family: str,
    potential_mapping: dict,
    options: dict,
    retrieve: t.List[str] = None,
    restart_folder=None,
    clean_workdir: bool = False,
    kpoints_mesh: t.List[int] = None,
    structure: orm.StructureData = None,
    fix_type: str = None,
    fix_thickness: float = 0.0,
    fix_elements: t.List[str] = None,
) -> dict:
    """
    Prepare builder inputs for VaspWorkChain.

    Args:
        incar: INCAR parameters dict
        kpoints_spacing: K-points spacing (used if kpoints_mesh not provided)
        potential_family: POTCAR family
        potential_mapping: Element to POTCAR mapping
        options: Scheduler options
        retrieve: Additional files to retrieve (merged with defaults)
        restart_folder: RemoteData for restart
        clean_workdir: Whether to clean work directory
        kpoints_mesh: Explicit k-points mesh [nx, ny, nz] (overrides kpoints_spacing)
        structure: StructureData (required for selective dynamics)
        fix_type: Where to fix atoms ('bottom', 'center', 'top', or None)
        fix_thickness: Thickness in Angstroms for fixing region
        fix_elements: Optional list of element symbols to fix

    Returns:
        Dict of prepared inputs for VaspWorkChain
    """
    from .common.fixed_atoms import get_fixed_atoms_list

    prepared = {}

    # Parameters (INCAR)
    prepared['parameters'] = orm.Dict(dict={'incar': incar})

    # K-points: explicit mesh or spacing
    if kpoints_mesh is not None:
        kpoints = orm.KpointsData()
        kpoints.set_kpoints_mesh(kpoints_mesh)
        prepared['kpoints'] = kpoints
    else:
        prepared['kpoints_spacing'] = float(kpoints_spacing)

    # Potentials
    prepared['potential_family'] = potential_family
    prepared['potential_mapping'] = orm.Dict(dict=potential_mapping)

    # Options
    prepared['options'] = orm.Dict(dict=options)

    # Clean workdir
    prepared['clean_workdir'] = clean_workdir

    # Settings (for file retrieval)
    # Note: aiida-vasp expects UPPERCASE keys for settings
    settings = {}
    retrieve_list = build_vasp_retrieve(retrieve)
    if retrieve_list:
        settings['ADDITIONAL_RETRIEVE_LIST'] = retrieve_list
    if settings:
        prepared['settings'] = orm.Dict(dict=settings)

    # Restart folder
    if restart_folder is not None:
        prepared['restart'] = {'folder': restart_folder}

    # Selective dynamics (fix atoms)
    if structure is not None and fix_type is not None and fix_thickness > 0.0:
        fixed_atoms_list = get_fixed_atoms_list(
            structure=structure,
            fix_type=fix_type,
            fix_thickness=fix_thickness,
            fix_elements=fix_elements,
        )

        if fixed_atoms_list:
            # Create positions_dof array: True = relax, False = fix
            num_atoms = len(structure.sites)
            positions_dof = []

            for i in range(1, num_atoms + 1):  # 1-based indexing
                if i in fixed_atoms_list:
                    positions_dof.append([False, False, False])  # Fix atom
                else:
                    positions_dof.append([True, True, True])  # Relax atom

            prepared['dynamics'] = orm.Dict(dict={'positions_dof': positions_dof})

    return prepared


def _wait_for_completion(pk: int, poll_interval: float) -> None:
    """
    Block until a WorkGraph completes.

    Args:
        pk: WorkGraph PK
        poll_interval: Seconds between status checks
    """
    print(f"Waiting for WorkGraph PK {pk} to complete...")

    while True:
        status = get_status(pk)

        if status in ('finished', 'failed', 'excepted', 'killed'):
            print(f"WorkGraph PK {pk} completed with status: {status}")
            break

        time.sleep(poll_interval)


def _validate_stages(stages: t.List[dict]) -> None:
    """
    Validate sequential stage configuration.

    Delegates type-specific validation to each brick module.

    Args:
        stages: List of stage configuration dicts

    Raises:
        ValueError: If validation fails
    """
    import warnings as _warnings
    from .bricks import get_brick_module, VALID_BRICK_TYPES, validate_connections

    if not stages:
        raise ValueError("stages list cannot be empty")

    stage_names = set()
    for i, stage in enumerate(stages):
        # Require name
        if 'name' not in stage:
            raise ValueError(f"Stage {i} missing required 'name' field")

        name = stage['name']
        if name in stage_names:
            raise ValueError(f"Duplicate stage name: '{name}'")
        stage_names.add(name)

        # Get stage type (default to 'vasp')
        stage_type = stage.get('type', 'vasp')
        if stage_type not in VALID_BRICK_TYPES:
            raise ValueError(
                f"Stage '{name}' type='{stage_type}' must be one of {VALID_BRICK_TYPES}"
            )

        # Delegate type-specific validation to brick module
        brick = get_brick_module(stage_type)
        brick.validate_stage(stage, stage_names)

    # Validate inter-stage connections using port declarations
    connection_warnings = validate_connections(stages)
    for w in connection_warnings:
        _warnings.warn(w, stacklevel=3)


def _build_indexed_output_name(index: int, name: str) -> str:
    """Build a stable indexed output name (e.g. ``s01_relax``)."""
    return f's{index:02d}_{name}'


def _build_combined_trajectory_output_name(stage_count: int) -> str:
    """Build indexed output name for the final combined trajectory."""
    return _build_indexed_output_name(stage_count + 1, 'combined_trajectory')


def quick_vasp_sequential(
    structure: t.Union[orm.StructureData, int] = None,
    stages: t.List[dict] = None,
    code_label: str = None,
    kpoints_spacing: float = 0.03,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    max_concurrent_jobs: int = None,
    name: str = 'quick_vasp_sequential',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
    concatenate_aimd_trajectories: bool = False,
) -> dict:
    """
    Submit a multi-stage sequential VASP calculation with automatic restart chaining.

    Each stage runs after the previous one completes, automatically using the
    previous stage's output structure and remote_folder for restart. Supercell
    transformations can be inserted between stages.

    Args:
        structure: Initial StructureData or PK
        stages: List of stage configuration dicts (see Stage Configuration below)
        code_label: VASP code label (e.g., 'VASP-6.5.1@localwork')
        kpoints_spacing: Default k-points spacing in A^-1 (default: 0.03)
        potential_family: POTCAR family (default: 'PBE')
        potential_mapping: Element to POTCAR mapping (e.g., {'Sn': 'Sn_d', 'O': 'O'})
        options: Scheduler options dict with 'resources' key
        max_concurrent_jobs: Maximum number of VASP jobs running simultaneously
                            (default: None = unlimited). Useful when batch stages
                            launch many parallel calculations.
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean work directories after completion

    Returns:
        Dict with:
            - __workgraph_pk__: WorkGraph PK
            - __stage_names__: List of stage names in order
            - __stage_types__: Dict mapping stage names to types
              ('vasp', 'dos', 'batch', 'bader', 'convergence', 'thickness',
               'hubbard_response', 'hubbard_analysis', 'aimd', 'qe', 'cp2k',
               'generate_neb_images', or 'neb')
            - __stage_namespaces__: Dict mapping stage names to namespace_map dicts
            - <stage_name>: WorkGraph PK (for each stage)

    Stage Configuration (VASP stages, type='vasp' or omitted):
        - name (required): Unique stage identifier
        - type: 'vasp' (default) - standard VASP calculation
        - incar (required): INCAR parameters for this stage
        - restart (required): None or stage name to restart from
        - structure_from: 'previous' (default), 'input', or specific stage name
        - supercell: [nx, ny, nz] to create supercell
        - kpoints_spacing: Override k-points spacing for this stage
        - kpoints: Explicit k-points mesh [nx, ny, nz] (overrides kpoints_spacing)
        - retrieve: Additional files to retrieve for this stage (merged with defaults)
        - fix_type: Where to fix atoms ('bottom', 'center', 'top', or None)
        - fix_thickness: Thickness in Angstroms for fixing region (required if fix_type set)
        - fix_elements: Optional list of element symbols to restrict fixing to

    Stage Configuration (DOS stages, type='dos'):
        - name (required): Unique stage identifier
        - type: 'dos' - DOS calculation (SCF + DOS)
        - structure_from (required): Stage name to get structure from
        - scf_incar (required): INCAR for SCF step (lwave/lcharg forced to True)
        - dos_incar (required): INCAR for DOS step (ismear defaults to -5, lorbit to 11)
        - kpoints_spacing: K-points for SCF (default: base value)
        - dos_kpoints_spacing: K-points for DOS (default: kpoints_spacing * 0.8)
        - retrieve: Files to retrieve from DOS step (default: ['DOSCAR'], merged with defaults)

    Stage Configuration (Batch stages, type='batch'):
        Runs multiple parallel VASP calculations on the same structure with
        varying parameters (e.g., fractional charge for Fukui analysis).

        - name (required): Unique stage identifier
        - type: 'batch'
        - structure_from (required): Stage name to get structure from
        - base_incar (required): Base INCAR dict applied to ALL calculations
        - calculations (required): Dict of {label: overrides}, where each
          override dict may contain:
            - incar: INCAR keys to override/add on top of base_incar
            - kpoints: Explicit k-points mesh [nx, ny, nz]
            - kpoints_spacing: K-points spacing
            - retrieve: Files to retrieve (merged with defaults)
        - kpoints_spacing: Default k-points spacing for all calculations
        - kpoints: Default explicit k-points mesh for all calculations
        - retrieve: Default files to retrieve for all calculations (merged with defaults)

        Output naming: Each calculation produces outputs named
            {stage_name}_{calc_label}_energy
            {stage_name}_{calc_label}_misc
            {stage_name}_{calc_label}_remote
            {stage_name}_{calc_label}_retrieved

        Note: Batch stages do NOT modify the structure. All calculations
        run the same geometry with different electronic parameters.

    Stage Configuration (Generate NEB Images, type='generate_neb_images'):
        - name (required): Unique stage identifier
        - type: 'generate_neb_images'
        - initial_from (required): Previous VASP stage name for initial endpoint
        - final_from (required): Previous VASP stage name for final endpoint
        - n_images (required): Number of intermediate images (>= 1)
        - method: Interpolation method ('idpp' default, or 'linear')
        - mic: Minimum-image-convention interpolation flag (default: True)

    Stage Configuration (NEB, type='neb'):
        - name (required): Unique stage identifier
        - type: 'neb'
        - initial_from (required): Previous VASP stage name for initial endpoint
        - final_from (required): Previous VASP stage name for final endpoint
        - incar (required): INCAR parameters (images count is auto-synchronized)
          (LCLIMB/lclimb is supported and injected via scheduler prepend_text)
        - images_from: Previous generate_neb_images stage name
        - images_dir: Local path with NEB images (.vasp files or 00/01... folders)
        - restart: Previous NEB stage name for restart_folder chaining (optional)
        - kpoints_spacing: Override stage k-point spacing (optional)
        - kpoints: Explicit k-point mesh [nx, ny, nz] (optional)
        - retrieve: Additional files to retrieve (merged with defaults)

        Exactly one of images_from or images_dir must be provided.

    Explicit CI-NEB pattern:
        Define two sequential NEB stages:
        1) regular NEB stage (`restart`: None, `lclimb`: False in INCAR)
        2) CI-NEB stage (`restart`: <stage1>, `lclimb`: True in INCAR)

    Example:
        >>> stages = [
        ...     {
        ...         'name': 'relax_1x1_rough',
        ...         'incar': {'NSW': 100, 'IBRION': 2, 'ISIF': 2, 'EDIFF': 1e-4, 'ENCUT': 400},
        ...         'restart': None,
        ...         'kpoints_spacing': 0.06,
        ...         'retrieve': ['CONTCAR', 'OUTCAR'],
        ...     },
        ...     {
        ...         'name': 'relax_1x1_fine',
        ...         'incar': {'NSW': 100, 'IBRION': 2, 'ISIF': 2, 'EDIFF': 1e-6, 'ENCUT': 520},
        ...         'restart': 'relax_1x1_rough',
        ...         'kpoints_spacing': 0.03,
        ...         'retrieve': ['CONTCAR', 'OUTCAR'],
        ...     },
        ...     {
        ...         'name': 'relax_2x2_rough',
        ...         'supercell': [2, 2, 1],
        ...         'incar': {'NSW': 100, 'IBRION': 2, 'ISIF': 2, 'EDIFF': 1e-4, 'ENCUT': 400},
        ...         'restart': None,
        ...         'kpoints': [2, 2, 1],
        ...         'retrieve': ['CONTCAR', 'OUTCAR'],
        ...     },
        ...     {
        ...         'name': 'relax_2x2_fine',
        ...         'incar': {'NSW': 100, 'IBRION': 2, 'ISIF': 2, 'EDIFF': 1e-6, 'ENCUT': 520},
        ...         'restart': 'relax_2x2_rough',
        ...         'kpoints': [6, 6, 1],
        ...         'retrieve': ['CONTCAR', 'OUTCAR', 'CHGCAR'],
        ...     },
        ... ]
        >>>
        >>> result = quick_vasp_sequential(
        ...     structure=sno2_structure,
        ...     stages=stages,
        ...     code_label='VASP-6.5.1@localwork',
        ...     potential_family='PBE',
        ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
        ... )
        >>>
        >>> # Monitor: verdi process show result['__workgraph_pk__']
        >>> # Results: print_sequential_results(result)

    Note:
        - When supercell is specified, restart is automatically set to None
        - VaspWorkChain handles WAVECAR/CHGCAR copying from restart.folder automatically
    """
    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if stages is None:
        raise ValueError("stages is required - provide list of stage configurations")
    if code_label is None:
        raise ValueError("code_label is required")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Validate stages
    _validate_stages(stages)

    # Load structure if PK
    if isinstance(structure, int):
        structure = orm.load_node(structure)

    # Load code
    code = orm.load_code(code_label)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    if max_concurrent_jobs is not None:
        wg.max_number_jobs = max_concurrent_jobs

    # Track structures and remote folders across stages
    stage_tasks = {}  # name -> {'vasp': task, 'energy': task, 'supercell': task, ...}
    stage_names = []  # Ordered list
    stage_types = {}  # name -> 'vasp', 'dos', 'batch', 'bader', etc.
    stage_namespaces = {}  # name -> namespace_map (e.g. {'main': 's01_relax_2x2_rough'})

    for i, stage in enumerate(stages):
        stage_name = stage['name']
        stage_type = stage.get('type', 'vasp')
        stage_names.append(stage_name)
        stage_types[stage_name] = stage_type

        # Build context for brick modules
        context = {
            'wg': wg,
            'code': code,
            'potential_family': potential_family,
            'potential_mapping': potential_mapping or {},
            'options': options,
            'base_kpoints_spacing': kpoints_spacing,
            'clean_workdir': clean_workdir,
            'stage_tasks': stage_tasks,
            'stage_types': stage_types,
            'stage_names': stage_names,
            'stages': stages,
            'input_structure': structure,
            'stage_index': i,
            'max_concurrent_jobs': max_concurrent_jobs,
        }

        # Delegate to brick module
        from .bricks import get_brick_module
        brick = get_brick_module(stage_type)
        tasks_result = brick.create_stage_tasks(wg, stage, stage_name, context)
        stage_tasks[stage_name] = tasks_result

        # Build namespace_map with index prefix for ordered display
        # Use 's' prefix (stage) since Python identifiers can't start with digits
        indexed_name = _build_indexed_output_name(i + 1, stage_name)
        namespace_map = {'main': indexed_name}
        if stage_type == 'dos':
            namespace_map['scf'] = indexed_name
            namespace_map['dos'] = indexed_name

        stage_namespaces[stage_name] = namespace_map
        brick.expose_stage_outputs(wg, stage_name, tasks_result, namespace_map)

    # Concatenate AIMD trajectories if requested
    if concatenate_aimd_trajectories:
        from .tasks import concatenate_trajectories

        # Collect trajectory outputs from AIMD stages
        # IMPORTANT: Use task output sockets directly - do NOT access wg.outputs
        # during workgraph construction (those are setter-only attributes)
        traj_inputs = {}
        for stage_name in stage_names:
            if stage_types[stage_name] == 'aimd':
                ns = stage_namespaces[stage_name]['main']
                # Prefer normalized trajectory socket when provided by AIMD brick.
                trajectory_task = stage_tasks[stage_name].get('trajectory')
                if trajectory_task is not None:
                    traj_inputs[ns] = trajectory_task.outputs.result
                else:
                    vasp_task = stage_tasks[stage_name]['vasp']
                    traj_inputs[ns] = vasp_task.outputs.trajectory

        # Only add concatenate task if we have AIMD stages
        if traj_inputs:
            concat_task = wg.add_task(
                concatenate_trajectories,
                name='concatenate_trajectories',
                trajectories=traj_inputs,
            )
            combined_name = _build_combined_trajectory_output_name(len(stage_names))
            setattr(wg.outputs, combined_name, concat_task.outputs.result)

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    # Return result dict
    return {
        '__workgraph_pk__': wg.pk,
        '__stage_names__': stage_names,
        '__stage_types__': stage_types,
        '__stage_namespaces__': stage_namespaces,
        **{name: wg.pk for name in stage_names},
    }


def get_batch_results_from_workgraph(batch_result: dict) -> t.Dict[str, dict]:
    """
    Extract results from a quick_vasp_batch result.

    Args:
        batch_result: Return value from quick_vasp_batch

    Returns:
        Dict mapping structure keys to result dicts
    """
    from .results import get_results

    wg_pk = batch_result['__workgraph_pk__']
    task_map = batch_result['__task_map__']

    wg_node = orm.load_node(wg_pk)

    results = {}
    for key, task_info in task_map.items():
        # Extract results for this key
        result = {
            'energy': None,
            'structure': None,
            'misc': None,
            'files': None,
            'pk': wg_pk,
            'key': key,
        }

        # Access task outputs
        vasp_task_name = task_info['vasp_task']
        energy_task_name = task_info['energy_task']

        if hasattr(wg_node, 'tasks'):
            # Live WorkGraph
            tasks = wg_node.tasks
            if vasp_task_name in tasks:
                vasp_task = tasks[vasp_task_name]
                if hasattr(vasp_task.outputs, 'misc'):
                    misc_val = vasp_task.outputs.misc.value
                    if hasattr(misc_val, 'get_dict'):
                        result['misc'] = misc_val.get_dict()
                if hasattr(vasp_task.outputs, 'structure'):
                    struct_val = vasp_task.outputs.structure.value
                    if struct_val is not None:
                        result['structure'] = struct_val
                if hasattr(vasp_task.outputs, 'retrieved'):
                    result['files'] = vasp_task.outputs.retrieved.value

            if energy_task_name in tasks:
                energy_task = tasks[energy_task_name]
                if hasattr(energy_task.outputs, 'result'):
                    energy_val = energy_task.outputs.result.value
                    if energy_val is not None:
                        result['energy'] = energy_val.value if hasattr(energy_val, 'value') else float(energy_val)

        # Extract energy from misc if not found
        if result['energy'] is None and result['misc'] is not None:
            from .results import _extract_energy_from_misc
            result['energy'] = _extract_energy_from_misc(result['misc'])

        results[key] = result

    return results


def quick_dos_batch(
    structures: t.Dict[str, t.Union[orm.StructureData, int]],
    code_label: str,
    scf_incar: dict,
    dos_incar: dict,
    kpoints_spacing: float = 0.03,
    dos_kpoints_spacing: float = None,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    retrieve: t.List[str] = None,
    scf_incar_overrides: t.Dict[str, dict] = None,
    dos_incar_overrides: t.Dict[str, dict] = None,
    max_concurrent_jobs: int = None,
    name: str = 'quick_dos_batch',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> t.Dict[str, int]:
    """
    Submit multiple DOS calculations in parallel using BandsWorkChain.

    Each structure runs through SCF -> DOS workflow with optional per-structure
    INCAR overrides. Useful for comparing DOS across different structures
    (e.g., pristine vs defects, different terminations).

    Args:
        structures: Dict mapping keys to StructureData or PKs
                   (e.g., {'pristine': s1, 'vacancy': s2})
        code_label: VASP code label
        scf_incar: Base INCAR for SCF stage (lowercase keys, e.g., {'encut': 400})
        dos_incar: Base INCAR for DOS stage (lowercase keys, e.g., {'nedos': 2000})
        kpoints_spacing: K-points spacing in A^-1 for SCF (default: 0.03)
        dos_kpoints_spacing: K-points spacing for DOS (default: 80% of kpoints_spacing)
        potential_family: POTCAR family (default: 'PBE')
        potential_mapping: Element to POTCAR mapping
        options: Scheduler options dict
        retrieve: Additional files to retrieve (merged with defaults)
        scf_incar_overrides: Per-structure SCF INCAR overrides
                            (e.g., {'vacancy': {'ismear': 0, 'sigma': 0.02}})
        dos_incar_overrides: Per-structure DOS INCAR overrides
        max_concurrent_jobs: Maximum parallel DOS jobs (default: unlimited)
        name: WorkGraph name
        wait: If True, block until all calculations finish
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean work directories after completion

    Returns:
        Dict with:
            - __workgraph_pk__: WorkGraph PK
            - __task_map__: Dict mapping keys to task names
            - <key>: WorkGraph PK (for each structure key)

    Example:
        >>> # Compare DOS for different structures
        >>> result = quick_dos_batch(
        ...     structures={'pristine': s1, 'vacancy': s2},
        ...     code_label='VASP-6.5.1@localwork',
        ...     scf_incar={'encut': 400, 'ediff': 1e-6, 'ismear': 0},
        ...     dos_incar={'nedos': 2000, 'lorbit': 11, 'ismear': -5},
        ...     kpoints_spacing=0.03,
        ...     max_concurrent_jobs=2,
        ... )
        >>> print(f"WorkGraph PK: {result['__workgraph_pk__']}")

        >>> # With per-structure INCAR overrides
        >>> result = quick_dos_batch(
        ...     structures={'metal': s1, 'insulator': s2},
        ...     scf_incar={'encut': 400, 'ediff': 1e-6},
        ...     dos_incar={'nedos': 2000, 'lorbit': 11},
        ...     scf_incar_overrides={
        ...         'metal': {'ismear': 1, 'sigma': 0.2},
        ...         'insulator': {'ismear': 0, 'sigma': 0.05},
        ...     },
        ...     dos_incar_overrides={
        ...         'metal': {'ismear': 1},
        ...         'insulator': {'ismear': -5},
        ...     },
        ... )

    Note:
        AiiDA-VASP requires lowercase INCAR keys (e.g., 'encut' not 'ENCUT').

    Exposed Outputs:
        For each structure key, the following outputs are exposed on the WorkGraph:
        - {key}_scf_misc: Dict with SCF calculation results
        - {key}_scf_remote: RemoteData for SCF calculation
        - {key}_scf_retrieved: FolderData with SCF retrieved files
        - {key}_dos_misc: Dict with DOS calculation results
        - {key}_dos_remote: RemoteData for DOS calculation
        - {key}_dos_retrieved: FolderData with DOS retrieved files (includes DOSCAR)
    """
    # Validate inputs
    if not structures:
        raise ValueError("structures dict cannot be empty")
    if code_label is None:
        raise ValueError("code_label is required")
    if scf_incar is None:
        raise ValueError("scf_incar is required - always specify SCF INCAR explicitly")
    if dos_incar is None:
        raise ValueError("dos_incar is required - always specify DOS INCAR explicitly")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    if scf_incar_overrides is None:
        scf_incar_overrides = {}
    if dos_incar_overrides is None:
        dos_incar_overrides = {}

    # Default DOS k-points spacing to 80% of SCF spacing (denser)
    if dos_kpoints_spacing is None:
        dos_kpoints_spacing = kpoints_spacing * 0.8

    # Load code and wrap VaspWorkChain as task
    code = orm.load_code(code_label)
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    if max_concurrent_jobs is not None:
        wg.max_number_jobs = max_concurrent_jobs

    # Track task names for each key
    task_map = {}

    # Process each structure
    for key, struct_input in structures.items():
        # Load structure if PK
        if isinstance(struct_input, int):
            struct = orm.load_node(struct_input)
        else:
            struct = struct_input

        # Merge base INCAR with per-structure overrides
        if key in scf_incar_overrides:
            merged_scf_incar = deep_merge_dicts(scf_incar, scf_incar_overrides[key])
        else:
            merged_scf_incar = dict(scf_incar)

        if key in dos_incar_overrides:
            merged_dos_incar = deep_merge_dicts(dos_incar, dos_incar_overrides[key])
        else:
            merged_dos_incar = dict(dos_incar)

        # Prepare SCF INCAR - force lwave and lcharg for DOS restart
        scf_incar_final = dict(merged_scf_incar)
        scf_incar_final['lwave'] = True
        scf_incar_final['lcharg'] = True
        if 'nsw' not in scf_incar_final:
            scf_incar_final['nsw'] = 0
        if 'ibrion' not in scf_incar_final:
            scf_incar_final['ibrion'] = -1

        # Prepare DOS INCAR
        # Note: Don't set ISTART/ICHARG - the restart.folder mechanism in
        # VaspWorkChain handles WAVECAR/CHGCAR copying automatically
        dos_incar_final = dict(merged_dos_incar)
        if 'nsw' not in dos_incar_final:
            dos_incar_final['nsw'] = 0
        if 'ibrion' not in dos_incar_final:
            dos_incar_final['ibrion'] = -1

        # Prepare SCF builder inputs
        scf_builder_inputs = _prepare_builder_inputs(
            incar=scf_incar_final,
            kpoints_spacing=kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping or {},
            options=options,
            retrieve=None,  # No special retrieval for SCF
            restart_folder=None,
            clean_workdir=False,  # Keep for DOS restart
        )

        # Add SCF task
        scf_task_name = f'scf_{key}'
        scf_task = wg.add_task(
            VaspTask,
            name=scf_task_name,
            structure=struct,
            code=code,
            **scf_builder_inputs
        )

        # Prepare DOS builder inputs
        # Note: We prepare the base inputs here, then add restart in add_task
        dos_retrieve = retrieve if retrieve is not None else ['DOSCAR']
        dos_builder_inputs = _prepare_builder_inputs(
            incar=dos_incar_final,
            kpoints_spacing=dos_kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping or {},
            options=options,
            retrieve=dos_retrieve,
            restart_folder=None,  # Will be passed directly below
            clean_workdir=clean_workdir,
        )

        # Add DOS task with restart from SCF
        # Pass restart directly in add_task to avoid potential issues with set_inputs
        dos_task_name = f'dos_{key}'
        dos_task = wg.add_task(
            VaspTask,
            name=dos_task_name,
            structure=struct,
            code=code,
            restart={'folder': scf_task.outputs.remote_folder},  # Wire restart here
            **dos_builder_inputs
        )

        # Expose outputs for this structure
        # SCF outputs
        setattr(wg.outputs, f'{key}_scf_misc', scf_task.outputs.misc)
        setattr(wg.outputs, f'{key}_scf_remote', scf_task.outputs.remote_folder)
        setattr(wg.outputs, f'{key}_scf_retrieved', scf_task.outputs.retrieved)
        # DOS outputs
        setattr(wg.outputs, f'{key}_dos_misc', dos_task.outputs.misc)
        setattr(wg.outputs, f'{key}_dos_remote', dos_task.outputs.remote_folder)
        setattr(wg.outputs, f'{key}_dos_retrieved', dos_task.outputs.retrieved)

        task_map[key] = {
            'scf_task': scf_task_name,
            'dos_task': dos_task_name,
        }

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    # Return the WorkGraph PK with keys for reference
    return {
        '__workgraph_pk__': wg.pk,
        '__task_map__': task_map,
        **{key: wg.pk for key in structures.keys()},
    }


def quick_dos(
    structure: t.Union[orm.StructureData, int] = None,
    code_label: str = None,
    scf_incar: dict = None,
    dos_incar: dict = None,
    kpoints_spacing: float = 0.03,
    kpoints: t.List[int] = None,
    dos_kpoints_spacing: float = None,
    dos_kpoints: t.List[int] = None,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    retrieve: t.List[str] = None,
    name: str = 'quick_dos',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> dict:
    """
    Submit a DOS calculation using BandsWorkChain with only_dos=True.

    This function uses AiiDA-VASP's BandsWorkChain which handles the
    SCF -> DOS workflow internally with proper CHGCAR/WAVECAR passing.

    Args:
        structure: StructureData or PK of structure to calculate DOS for.
        code_label: VASP code label (e.g., 'VASP-6.5.1@localwork')
        scf_incar: INCAR parameters for SCF stage (e.g., {'encut': 400, 'ediff': 1e-5}).
                   lwave and lcharg are forced to True internally by BandsWorkChain.
        dos_incar: INCAR parameters for DOS stage (e.g., {'nedos': 2000, 'lorbit': 11}).
                   Passed to the 'dos' namespace of BandsWorkChain.
        kpoints_spacing: K-points spacing in A^-1 for SCF (default: 0.03)
        kpoints: Explicit k-points mesh for SCF [nx, ny, nz] (overrides kpoints_spacing)
        dos_kpoints_spacing: K-points spacing for DOS (default: 80% of kpoints_spacing)
        dos_kpoints: Explicit k-points mesh for DOS [nx, ny, nz] (overrides dos_kpoints_spacing)
        potential_family: POTCAR family (default: 'PBE')
        potential_mapping: Element to POTCAR mapping (e.g., {'Sn': 'Sn_d', 'O': 'O'})
        options: Scheduler options dict with 'resources' key
        retrieve: Additional files to retrieve (merged with defaults)
        name: Calculation label for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean the work directory after completion

    Returns:
        Dict with '__workgraph_pk__' key containing the BandsWorkChain PK

    Example (using spacing):
        >>> result = quick_dos(
        ...     structure=my_structure,
        ...     code_label='VASP-6.5.1@localwork',
        ...     scf_incar={'encut': 400, 'ediff': 1e-6, 'ismear': 0, 'sigma': 0.05},
        ...     dos_incar={'nedos': 2000, 'lorbit': 11, 'ismear': -5},
        ...     kpoints_spacing=0.03,
        ...     dos_kpoints_spacing=0.02,
        ...     potential_family='PBE',
        ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
        ...     retrieve=['DOSCAR'],
        ...     name='sno2_dos',
        ... )

    Example (using explicit k-points - recommended for slabs):
        >>> result = quick_dos(
        ...     structure=my_structure,
        ...     code_label='VASP-6.5.1@localwork',
        ...     scf_incar={'encut': 400, 'ediff': 1e-6},
        ...     dos_incar={'nedos': 3000, 'lorbit': 11, 'ismear': -5},
        ...     kpoints=[6, 6, 1],          # SCF k-points mesh
        ...     dos_kpoints=[8, 8, 1],      # DOS k-points mesh (denser)
        ...     potential_family='PBE',
        ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
        ...     retrieve=['DOSCAR', 'PROCAR', 'vasprun.xml'],
        ...     name='sno2_dos',
        ... )

    Note:
        AiiDA-VASP requires lowercase INCAR keys (e.g., 'encut' not 'ENCUT').
    """
    from aiida.engine import submit

    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if code_label is None:
        raise ValueError("code_label is required")
    if scf_incar is None:
        raise ValueError("scf_incar is required - always specify SCF INCAR parameters explicitly")
    if dos_incar is None:
        raise ValueError("dos_incar is required - always specify DOS INCAR parameters explicitly")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Load structure if PK
    if isinstance(structure, int):
        structure = orm.load_node(structure)

    # Default DOS k-points spacing to 80% of SCF spacing (denser)
    # Only used if explicit dos_kpoints mesh is not provided
    if dos_kpoints_spacing is None and dos_kpoints is None:
        dos_kpoints_spacing = kpoints_spacing * 0.8

    # Load code and BandsWorkChain
    code = orm.load_code(code_label)
    BandsWorkChain = WorkflowFactory('vasp.v2.bands')

    # Prepare INCAR parameters
    # Force lwave and lcharg for non-SCF DOS calculation
    scf_incar_final = dict(scf_incar)
    scf_incar_final['lwave'] = True
    scf_incar_final['lcharg'] = True
    # Ensure static calculation
    if 'nsw' not in scf_incar_final:
        scf_incar_final['nsw'] = 0
    if 'ibrion' not in scf_incar_final:
        scf_incar_final['ibrion'] = -1

    # DOS INCAR
    dos_incar_final = dict(dos_incar)
    if 'nsw' not in dos_incar_final:
        dos_incar_final['nsw'] = 0
    if 'ibrion' not in dos_incar_final:
        dos_incar_final['ibrion'] = -1

    # Band settings - only_dos mode
    # dos_kpoints_distance is required but will be ignored if explicit kpoints is set
    band_settings = {
        'only_dos': True,
        'run_dos': True,
        'dos_kpoints_distance': float(dos_kpoints_spacing) if dos_kpoints_spacing else 0.03,
    }

    # Build overrides for protocol-based builder
    # Note: settings must be {} not None to avoid aiida-vasp bug
    scf_overrides = {
        'parameters': {'incar': scf_incar_final},
        'potential_family': potential_family,
        'potential_mapping': potential_mapping or {},
        'clean_workdir': False,  # Keep for DOS restart
        'settings': {
            'ADDITIONAL_RETRIEVE_LIST': build_vasp_retrieve(None),
        },
    }

    # SCF k-points: explicit mesh or spacing
    if kpoints is not None:
        scf_kpoints_data = orm.KpointsData()
        scf_kpoints_data.set_kpoints_mesh(kpoints)
        scf_overrides['kpoints'] = scf_kpoints_data
    else:
        scf_overrides['kpoints_spacing'] = float(kpoints_spacing)

    # DOS overrides
    dos_retrieve = retrieve if retrieve is not None else ['DOSCAR']
    dos_overrides = {
        'parameters': {'incar': dos_incar_final},
        'settings': {
            'ADDITIONAL_RETRIEVE_LIST': build_vasp_retrieve(dos_retrieve),
            'parser_settings': {
                'include_node': ['dos'],
            },
        },
    }

    # DOS k-points: explicit mesh or spacing
    if dos_kpoints is not None:
        dos_kpoints_data = orm.KpointsData()
        dos_kpoints_data.set_kpoints_mesh(dos_kpoints)
        dos_overrides['kpoints'] = dos_kpoints_data

    overrides = {
        'scf': scf_overrides,
        'dos': dos_overrides,
        'band_settings': band_settings,
    }

    # Add settings for file retrieval
    # Note: aiida-vasp expects UPPERCASE keys for settings

    # Clean workdir option
    if clean_workdir:
        overrides['clean_children_workdir'] = 'all'

    # Use protocol-based builder with run_relax=False to exclude relax namespace
    # Note: band_settings must be in overrides, not as separate parameter
    # (to avoid recursive_merge error with None)
    builder = BandsWorkChain.get_builder_from_protocol(
        code=code,
        structure=structure,
        run_relax=False,  # Critical: skip relaxation
        overrides=overrides,
        options=options,
    )

    # Set metadata label
    builder.metadata.label = name

    # Note: The `retrieve` parameter is passed through protocol overrides.
    # If DOSCAR doesn't appear in retrieved files, use export_files() to
    # manually download it from the remote folder after calculation completes.

    # Submit the builder directly (not unpacked)
    node = submit(builder)
    pk = node.pk

    # Wait if requested
    if wait:
        _wait_for_completion(pk, poll_interval)

    # Return dict for consistency with other quick_* functions
    return {
        '__workgraph_pk__': pk,
    }


def quick_hubbard_u(
    structure: t.Union[orm.StructureData, int] = None,
    code_label: str = None,
    target_species: str = None,
    incar: dict = None,
    potential_values: t.List[float] = None,
    ldaul: int = 2,
    ldauj: float = 0.0,
    kpoints_spacing: float = 0.03,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    name: str = 'quick_hubbard_u',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> dict:
    """
    Submit a Hubbard U parameter calculation using the linear response method.

    This is a convenience function that internally builds a 3-stage sequential
    workflow using quick_vasp_sequential:

    1. ground_state (vasp brick): SCF with LORBIT=11, LWAVE=True, LCHARG=True
    2. response (hubbard_response brick): NSCF + SCF per potential, occupation
       extraction, gather responses
    3. analysis (hubbard_analysis brick): linear regression, summary compilation

    Args:
        structure: StructureData or PK of the input structure
        code_label: VASP code label (e.g., 'VASP-6.5.1@localwork')
        target_species: Element symbol for U calculation (e.g., 'Ni', 'Fe', 'Mn')
        incar: Base INCAR parameters dict (applied to ground state and responses).
               Lowercase keys recommended (e.g., {'encut': 520, 'ediff': 1e-6}).
               The module automatically adds LDAU, LORBIT, LWAVE, LCHARG, etc.
        potential_values: List of perturbation potentials in eV.
                         Default: [-0.2, -0.1, 0.1, 0.2]. Must not include 0.0.
        ldaul: Angular momentum quantum number (2=d electrons, 3=f electrons)
        ldauj: Exchange J parameter (default: 0.0)
        kpoints_spacing: K-points spacing in A^-1 (default: 0.03)
        potential_family: POTCAR family (default: 'PBE')
        potential_mapping: Element to POTCAR mapping (e.g., {'Ni': 'Ni', 'O': 'O'})
        options: Scheduler options dict with 'resources' key
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean work directories after completion

    Returns:
        Dict with quick_vasp_sequential result keys including '__workgraph_pk__'

    Example:
        >>> result = quick_hubbard_u(
        ...     structure=nio_structure,
        ...     code_label='VASP-6.5.1@localwork',
        ...     target_species='Ni',
        ...     incar={'encut': 520, 'ediff': 1e-6, 'ismear': 0, 'sigma': 0.05},
        ...     potential_values=[-0.2, -0.1, 0.1, 0.2],
        ...     ldaul=2,
        ...     potential_family='PBE',
        ...     potential_mapping={'Ni': 'Ni', 'O': 'O'},
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
        ...     name='NiO_HubbardU',
        ... )
        >>> print(f"WorkGraph PK: {result['__workgraph_pk__']}")

    Reference:
        https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
    """
    from quantum_lego.core.common.u_calculation.utils import (
        DEFAULT_POTENTIAL_VALUES,
        prepare_ground_state_incar,
    )

    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if code_label is None:
        raise ValueError("code_label is required")
    if target_species is None:
        raise ValueError(
            "target_species is required (e.g., 'Ni', 'Fe', 'Mn')")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Default INCAR
    if incar is None:
        incar = {
            'encut': 520,
            'ediff': 1e-6,
            'ismear': 0,
            'sigma': 0.05,
            'prec': 'Accurate',
            'algo': 'Normal',
            'nelm': 100,
        }

    if potential_values is None:
        potential_values = DEFAULT_POTENTIAL_VALUES

    lmaxmix = 4 if ldaul == 2 else 6

    # Build ground state INCAR from the base incar
    gs_incar = prepare_ground_state_incar(
        base_params=incar,
        lmaxmix=lmaxmix,
    )

    # Build 3-stage workflow
    stages = [
        {
            'name': 'ground_state',
            'type': 'vasp',
            'incar': gs_incar,
            'restart': None,
            'kpoints_spacing': kpoints_spacing,
            'retrieve': ['OUTCAR'],
        },
        {
            'name': 'response',
            'type': 'hubbard_response',
            'ground_state_from': 'ground_state',
            'structure_from': 'input',
            'target_species': target_species,
            'potential_values': potential_values,
            'ldaul': ldaul,
            'ldauj': ldauj,
            'incar': incar,
            'kpoints_spacing': kpoints_spacing,
        },
        {
            'name': 'analysis',
            'type': 'hubbard_analysis',
            'response_from': 'response',
            'structure_from': 'input',
            'target_species': target_species,
            'ldaul': ldaul,
        },
    ]

    return quick_vasp_sequential(
        structure=structure,
        stages=stages,
        code_label=code_label,
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        name=name,
        wait=wait,
        poll_interval=poll_interval,
        clean_workdir=clean_workdir,
    )


def quick_qe(
    structure: t.Union[orm.StructureData, int] = None,
    code_label: str = None,
    parameters: dict = None,
    kpoints_spacing: float = 0.03,
    kpoints: t.List[int] = None,
    pseudo_family: str = None,
    options: dict = None,
    restart_from: int = None,
    name: str = 'quick_qe',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> int:
    """
    Submit a single Quantum ESPRESSO calculation with minimal boilerplate.

    This wraps PwBaseWorkChain from aiida-quantumespresso for SCF, relax,
    and vc-relax calculations.

    Args:
        structure: StructureData or PK. Required.
        code_label: QE pw.x code label (e.g., 'pw@localhost')
        parameters: QE namelists dict (CONTROL, SYSTEM, ELECTRONS, etc.)
                   Example: {'CONTROL': {'calculation': 'scf'},
                            'SYSTEM': {'ecutwfc': 50, 'ecutrho': 400},
                            'ELECTRONS': {'conv_thr': 1e-8}}
        kpoints_spacing: K-points spacing in A^-1 (default: 0.03)
        kpoints: Explicit k-points mesh [nx, ny, nz] (overrides kpoints_spacing)
        pseudo_family: Pseudopotential family name (required, no default)
        options: Scheduler options dict with 'resources' key
        restart_from: PK of previous QE WorkGraph to restart from
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean the work directory after completion

    Returns:
        PK of the submitted WorkGraph

    Example:
        >>> pk = quick_qe(
        ...     structure=si_structure,
        ...     code_label='pw@localhost',
        ...     parameters={
        ...         'CONTROL': {'calculation': 'relax'},
        ...         'SYSTEM': {'ecutwfc': 50, 'ecutrho': 400},
        ...         'ELECTRONS': {'conv_thr': 1e-8},
        ...         'IONS': {},
        ...     },
        ...     kpoints_spacing=0.03,
        ...     pseudo_family='SSSP/1.3/PBE/efficiency',
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 4}},
        ...     name='si_relax',
        ... )
    """
    from aiida.plugins import WorkflowFactory

    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if code_label is None:
        raise ValueError("code_label is required")
    if parameters is None:
        raise ValueError("parameters is required - specify QE namelists (CONTROL, SYSTEM, etc.)")
    if pseudo_family is None:
        raise ValueError("pseudo_family is required - specify pseudopotential family name")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Load structure if PK
    if isinstance(structure, int):
        structure = orm.load_node(structure)

    # Load code
    code = orm.load_code(code_label)

    # Load pseudo family and get pseudos
    pseudo_family_group = orm.load_group(pseudo_family)
    if not hasattr(pseudo_family_group, 'get_pseudos'):
        raise ValueError(f"Group '{pseudo_family}' is not a PseudoPotentialFamily")
    pseudos = pseudo_family_group.get_pseudos(structure=structure)

    # Get PwBaseWorkChain and wrap as task
    PwBaseWorkChain = WorkflowFactory('quantumespresso.pw.base')
    QeTask = task(PwBaseWorkChain)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    # Build k-points argument
    if kpoints is not None:
        kpoints_data = orm.KpointsData()
        kpoints_data.set_kpoints_mesh(kpoints)
        kpoints_arg = {'pw__kpoints': kpoints_data}
    else:
        kpoints_arg = {'kpoints_distance': orm.Float(kpoints_spacing)}

    # Handle restart
    restart_arg = {}
    if restart_from is not None:
        restart_node = orm.load_node(restart_from)
        # Navigate to remote_folder output
        if hasattr(restart_node, 'outputs'):
            # Try to get remote folder from the QE task output
            from aiida.common.links import LinkType
            for link in restart_node.base.links.get_outgoing(link_type=LinkType.RETURN).all():
                if 'remote' in link.link_label.lower():
                    restart_arg = {'pw__parent_folder': link.node}
                    break

    # Build task inputs
    qe_kwargs = {
        'pw__structure': structure,
        'pw__code': code,
        'pw__parameters': orm.Dict(dict=parameters),
        'pw__pseudos': pseudos,
        'pw__metadata': {'options': options},
        **kpoints_arg,
        **restart_arg,
        'clean_workdir': orm.Bool(clean_workdir),
    }

    # Add QE task
    qe_task = wg.add_task(QeTask, name='qe_calc', **qe_kwargs)

    # Add energy extraction task
    from .tasks import extract_qe_energy
    energy_task = wg.add_task(
        extract_qe_energy,
        name='extract_energy',
        output_parameters=qe_task.outputs.output_parameters,
    )

    # Set WorkGraph outputs
    wg.outputs.energy = energy_task.outputs.result
    wg.outputs.structure = qe_task.outputs.output_structure
    wg.outputs.output_parameters = qe_task.outputs.output_parameters
    wg.outputs.remote = qe_task.outputs.remote_folder
    wg.outputs.retrieved = qe_task.outputs.retrieved

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    return wg.pk


def quick_qe_sequential(
    structure: t.Union[orm.StructureData, int] = None,
    stages: t.List[dict] = None,
    code_label: str = None,
    kpoints_spacing: float = 0.03,
    pseudo_family: str = None,
    options: dict = None,
    max_concurrent_jobs: int = None,
    name: str = 'quick_qe_sequential',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> dict:
    """
    Submit a multi-stage sequential QE calculation with automatic restart chaining.

    Each stage runs after the previous one completes, automatically using the
    previous stage's output structure and remote_folder for restart.

    Args:
        structure: Initial StructureData or PK
        stages: List of stage configuration dicts (see Stage Configuration below)
        code_label: QE pw.x code label (e.g., 'pw@localhost')
        kpoints_spacing: Default k-points spacing in A^-1 (default: 0.03)
        pseudo_family: Pseudopotential family name (required, no default)
        options: Scheduler options dict with 'resources' key
        max_concurrent_jobs: Maximum number of jobs running simultaneously
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean work directories after completion

    Returns:
        Dict with:
            - __workgraph_pk__: WorkGraph PK
            - __stage_names__: List of stage names in order
            - __stage_types__: Dict mapping stage names to types
            - __stage_namespaces__: Dict mapping stage names to namespace_map dicts
            - <stage_name>: WorkGraph PK (for each stage)

    Stage Configuration (type='qe'):
        - name (required): Unique stage identifier
        - type: 'qe' (required for QE stages)
        - parameters (required): QE namelists dict (CONTROL, SYSTEM, ELECTRONS, etc.)
        - restart (required): None or stage name to restart from
        - structure_from: 'previous' (default), 'input', or specific stage name
        - kpoints_spacing: Override k-points spacing for this stage
        - kpoints: Explicit k-points mesh [nx, ny, nz] (overrides kpoints_spacing)
        - pseudo_family: Override pseudo family for this stage
        - code_label: Override code label for this stage

    Example:
        >>> stages = [
        ...     {
        ...         'name': 'relax',
        ...         'type': 'qe',
        ...         'parameters': {
        ...             'CONTROL': {'calculation': 'relax'},
        ...             'SYSTEM': {'ecutwfc': 50, 'ecutrho': 400},
        ...             'ELECTRONS': {'conv_thr': 1e-8},
        ...             'IONS': {},
        ...         },
        ...         'restart': None,
        ...     },
        ...     {
        ...         'name': 'scf',
        ...         'type': 'qe',
        ...         'parameters': {
        ...             'CONTROL': {'calculation': 'scf'},
        ...             'SYSTEM': {'ecutwfc': 60, 'ecutrho': 480},
        ...             'ELECTRONS': {'conv_thr': 1e-10},
        ...         },
        ...         'restart': 'relax',
        ...         'kpoints_spacing': 0.02,
        ...     },
        ... ]
        >>>
        >>> result = quick_qe_sequential(
        ...     structure=si_structure,
        ...     stages=stages,
        ...     code_label='pw@localhost',
        ...     pseudo_family='SSSP/1.3/PBE/efficiency',
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 4}},
        ... )
    """
    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if stages is None:
        raise ValueError("stages is required - provide list of stage configurations")
    if code_label is None:
        raise ValueError("code_label is required")
    if pseudo_family is None:
        raise ValueError("pseudo_family is required - specify pseudopotential family name")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Validate that all stages are QE type
    for i, stage in enumerate(stages):
        stage_type = stage.get('type', 'qe')
        if stage_type != 'qe':
            raise ValueError(
                f"quick_qe_sequential only supports 'qe' stages, but stage {i} "
                f"has type='{stage_type}'. Use quick_vasp_sequential for mixed pipelines."
            )
        # Ensure type is set for validation
        stage['type'] = 'qe'

    # Validate stages
    _validate_stages(stages)

    # Load structure if PK
    if isinstance(structure, int):
        structure = orm.load_node(structure)

    # Load code
    code = orm.load_code(code_label)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    if max_concurrent_jobs is not None:
        wg.max_number_jobs = max_concurrent_jobs

    # Track structures and remote folders across stages
    stage_tasks = {}  # name -> task result dict
    stage_names = []  # Ordered list
    stage_types = {}  # name -> 'qe'
    stage_namespaces = {}  # name -> namespace_map

    for i, stage in enumerate(stages):
        stage_name = stage['name']
        stage_type = 'qe'
        stage_names.append(stage_name)
        stage_types[stage_name] = stage_type

        # Build context for brick modules
        context = {
            'wg': wg,
            'code': code,
            'pseudo_family': pseudo_family,
            'options': options,
            'base_kpoints_spacing': kpoints_spacing,
            'clean_workdir': clean_workdir,
            'stage_tasks': stage_tasks,
            'stage_types': stage_types,
            'stage_names': stage_names,
            'stages': stages,
            'input_structure': structure,
            'stage_index': i,
            'max_concurrent_jobs': max_concurrent_jobs,
        }

        # Delegate to QE brick module
        from .bricks import get_brick_module
        brick = get_brick_module('qe')
        tasks_result = brick.create_stage_tasks(wg, stage, stage_name, context)
        stage_tasks[stage_name] = tasks_result

        # Build namespace_map with index prefix for ordered display
        indexed_name = f's{i + 1:02d}_{stage_name}'
        namespace_map = {'main': indexed_name}

        stage_namespaces[stage_name] = namespace_map
        brick.expose_stage_outputs(wg, stage_name, tasks_result, namespace_map)

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    # Return result dict
    return {
        '__workgraph_pk__': wg.pk,
        '__stage_names__': stage_names,
        '__stage_types__': stage_types,
        '__stage_namespaces__': stage_namespaces,
        **{name: wg.pk for name in stage_names},
    }


def quick_aimd(
    structure: t.Union[orm.StructureData, int] = None,
    code_label: str = None,
    aimd_stages: t.List[dict] = None,
    incar: dict = None,
    supercell: t.List[int] = None,
    kpoints_spacing: float = 0.5,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    max_concurrent_jobs: int = None,
    name: str = 'quick_aimd',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> dict:
    """
    Submit a multi-stage AIMD workflow with optional stage splitting.

    Converts a list of AIMD stage configs into lego stages and submits
    via quick_vasp_sequential. Each stage can be split into sub-stages
    with automatic restart chaining.

    IMPORTANT: LVEL is automatically set to True to enable velocity
    writing to CONTCAR for seamless MD continuation between stages.

    Args:
        structure: Initial StructureData or PK
        code_label: VASP code label (e.g., 'VASP-6.5.1@localwork')
        aimd_stages: List of AIMD stage dicts (see Stage Config below)
        incar: Base INCAR parameters shared by all stages
        supercell: [nx, ny, nz] applied to the first stage only
        kpoints_spacing: K-points spacing in A^-1 (default: 0.5 for MD)
        potential_family: POTCAR family (default: 'PBE')
        potential_mapping: Element to POTCAR mapping
        options: Scheduler options dict with 'resources' key
        max_concurrent_jobs: Maximum parallel jobs (default: None)
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean work directories after completion

    Returns:
        Dict with quick_vasp_sequential result keys including '__workgraph_pk__'

    Stage Config:
        Each entry in aimd_stages supports:
        - tebeg (required): Initial temperature in K
        - nsw (required): Total MD steps for this stage
        - name (optional): Base name for generated stages (default: stage_0, stage_1, ...)
        - splits (optional): Split into N sub-stages with restart chaining (default: 1)
        - teend (optional): Final temperature in K (default: tebeg)
        - potim (optional): Timestep in fs
        - mdalgo (optional): Thermostat algorithm
        - smass (optional): Nose mass parameter

    Example:
        >>> result = quick_aimd(
        ...     structure=structure,
        ...     code_label='VASP-6.5.1@localwork',
        ...     aimd_stages=[
        ...         {'name': 'equilibration', 'tebeg': 300, 'nsw': 2000, 'splits': 2,
        ...          'potim': 2.0, 'mdalgo': 2, 'smass': 0.0},
        ...         {'name': 'production', 'tebeg': 300, 'nsw': 10000, 'splits': 4,
        ...          'potim': 1.5, 'mdalgo': 2, 'smass': 0.0},
        ...     ],
        ...     incar={'encut': 400, 'ediff': 1e-5, 'prec': 'Normal'},
        ...     supercell=[2, 2, 1],
        ...     kpoints_spacing=0.5,
        ...     potential_family='PBE',
        ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
        ... )
    """
    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if code_label is None:
        raise ValueError("code_label is required")
    if aimd_stages is None:
        raise ValueError("aimd_stages is required - provide list of AIMD stage configs")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    base_incar = incar or {}
    stages = []
    previous_stage_name = None

    for i, aimd_stage in enumerate(aimd_stages):
        # Validate required fields
        if 'tebeg' not in aimd_stage:
            raise ValueError(f"aimd_stages[{i}] missing required 'tebeg' field")
        if 'nsw' not in aimd_stage:
            raise ValueError(f"aimd_stages[{i}] missing required 'nsw' field")

        stage_label = aimd_stage.get('name', f'stage_{i}')
        splits = aimd_stage.get('splits', 1)
        total_nsw = aimd_stage['nsw']
        nsw_per_split = total_nsw // splits

        if nsw_per_split <= 0:
            raise ValueError(
                f"aimd_stages[{i}] nsw={total_nsw} with splits={splits} "
                f"gives {nsw_per_split} steps per split (must be > 0)"
            )

        for s in range(splits):
            lego_stage = {
                'name': f'md_{stage_label}_{s}',
                'type': 'aimd',
                'tebeg': aimd_stage['tebeg'],
                'nsw': nsw_per_split,
                'incar': dict(base_incar),
                'restart': previous_stage_name,
            }

            # Copy optional AIMD params
            for key in ('teend', 'potim', 'mdalgo', 'smass'):
                if key in aimd_stage:
                    lego_stage[key] = aimd_stage[key]

            # Supercell only on the very first stage
            if i == 0 and s == 0 and supercell is not None:
                lego_stage['supercell'] = supercell

            stages.append(lego_stage)
            previous_stage_name = lego_stage['name']

    return quick_vasp_sequential(
        structure=structure,
        stages=stages,
        code_label=code_label,
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        max_concurrent_jobs=max_concurrent_jobs,
        name=name,
        wait=wait,
        poll_interval=poll_interval,
        clean_workdir=clean_workdir,
        concatenate_aimd_trajectories=True,
    )
