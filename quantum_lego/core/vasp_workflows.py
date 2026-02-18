"""VASP workflow builders for the lego module.

This module provides VASP-specific workflow functions for single, batch,
and sequential calculations. It handles VASP WorkChain setup, restart
chaining, supercell transformations, and multi-stage pipelines.

quick_vasp and quick_vasp_batch are thin wrappers around quick_vasp_sequential,
which is the central entry point. For more specialized workflows, see
specialized_workflows.py (quick_hubbard_u, quick_aimd).
"""

import typing as t

from aiida import orm

from aiida_workgraph import WorkGraph

from .workflow_utils import (
    _wait_for_completion,
    _validate_stages,
    _build_indexed_output_name,
    _build_combined_trajectory_output_name,
)


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

    Thin wrapper around quick_vasp_sequential that builds a single-stage
    config and delegates. Specify INCAR parameters directly - no presets,
    maximum flexibility.

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
    # Validate required inputs
    if structure is None and restart_from is None:
        raise ValueError("structure is required (or provide restart_from)")
    if code_label is None:
        raise ValueError("code_label is required")
    if incar is None:
        raise ValueError("incar is required - always specify INCAR parameters explicitly")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Build single stage config
    stage = {
        'name': 'calc',
        'incar': incar,
    }

    # Restart: external PK or none
    if restart_from is not None:
        stage['restart_from'] = restart_from
        stage['copy_wavecar'] = copy_wavecar
        stage['copy_chgcar'] = copy_chgcar
    else:
        stage['restart'] = None

    if kpoints_spacing != 0.03:
        stage['kpoints_spacing'] = kpoints_spacing
    if retrieve:
        stage['retrieve'] = retrieve

    # When restart_from is used without structure, pass a placeholder
    # (the vasp brick will resolve structure from the restart PK)
    seq_structure = structure
    if seq_structure is None:
        from .utils import prepare_restart_settings
        restart_structure, _ = prepare_restart_settings(restart_from)
        seq_structure = restart_structure

    result = quick_vasp_sequential(
        structure=seq_structure,
        stages=[stage],
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
    return result['__workgraph_pk__']


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
) -> dict:
    """
    Submit multiple VASP calculations with the same base settings.

    Thin wrapper around quick_vasp_sequential that builds a single batch
    stage with per-calculation structures and delegates. Useful for
    Fukui-style calculations or comparing different structures with
    consistent computational parameters.

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
        Dict with quick_vasp_sequential result keys including '__workgraph_pk__',
        '__stage_names__', '__stage_types__', '__stage_namespaces__'.
        Use get_stage_results(result, 'batch') to extract per-calculation results.

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

    # Build calculations dict for batch stage
    calculations = {}
    for key, struct_input in structures.items():
        calc_config = {}
        # Per-calc structure
        calc_config['structure'] = struct_input
        # INCAR overrides
        if key in incar_overrides:
            calc_config['incar'] = incar_overrides[key]
        calculations[key] = calc_config

    stage = {
        'name': 'batch',
        'type': 'batch',
        'structure_from': 'input',
        'base_incar': incar,
        'calculations': calculations,
    }
    if retrieve:
        stage['retrieve'] = retrieve
    if kpoints_spacing != 0.03:
        stage['kpoints_spacing'] = kpoints_spacing

    # Use first structure as input (will be overridden per-calc by batch brick)
    first_key = next(iter(structures))
    first_struct = structures[first_key]
    if isinstance(first_struct, int):
        first_struct = orm.load_node(first_struct)

    result = quick_vasp_sequential(
        structure=first_struct,
        stages=[stage],
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
    )

    return result


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
    serialize_stages: bool = False,
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
        serialize_stages: If True, force all stages to run one at a time in
                         the order they appear, regardless of data dependencies.
                         Useful to avoid flooding a cluster queue when many
                         independent stages would otherwise start simultaneously.
                         (default: False)

    Returns:
        Dict with:
            - __workgraph_pk__: WorkGraph PK
            - __stage_names__: List of stage names in order
            - __stage_types__: Dict mapping stage names to types
              ('vasp', 'dos', 'hybrid_bands', 'batch', 'bader',
               'convergence', 'thickness',
               'hubbard_response', 'hubbard_analysis', 'fukui_analysis',
               'aimd', 'qe', 'cp2k',
               'generate_neb_images', or 'neb')
            - __stage_namespaces__: Dict mapping stage names to namespace_map dicts
            - <stage_name>: WorkGraph PK (for each stage)

    Stage Configuration (VASP stages, type='vasp' or omitted):
        - name (required): Unique stage identifier
        - type: 'vasp' (default) - standard VASP calculation
        - incar (required): INCAR parameters for this stage
        - restart: None or stage name to restart from (mutually exclusive with restart_from)
        - restart_from: int PK of external calculation to restart from
          (mutually exclusive with restart). Sets restart folder and ISTART/ICHARG.
        - copy_wavecar: Copy WAVECAR from restart_from (default: True, only with restart_from)
        - copy_chgcar: Copy CHGCAR from restart_from (default: False, only with restart_from)
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
        - structure_from: Stage name to get structure from
        - structure: Explicit StructureData or PK
          (provide exactly one of structure_from or structure)
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
            - structure: StructureData or int PK (overrides stage-level structure)
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

        Note: By default, batch stages use the same structure for all
        calculations. Use per-calculation 'structure' to override this
        (e.g., for comparing different structures with consistent settings).

    Stage Configuration (Fukui analysis stages, type='fukui_analysis'):
        - name (required): Unique stage identifier
        - type: 'fukui_analysis'
        - batch_from (required): Name of previous batch stage with CHGCAR retrieved
        - fukui_type (required): 'plus' or 'minus'
        - delta_n_map (required): Dict {calc_label: delta_n} with exactly 4 entries

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

    def _serialize_barrier() -> bool:
        """No-op task used to serialize stages via _wait links (avoids Task.waiting_on deserialization issues)."""
        return True
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
    _prev_stage_barrier_task = None  # Used by serialize_stages
    _WG_BUILTIN_TASK_NAMES = {'graph_inputs', 'graph_outputs', 'graph_ctx'}

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
        _names_before = {t.name for t in wg.tasks if t.name not in _WG_BUILTIN_TASK_NAMES}
        tasks_result = brick.create_stage_tasks(wg, stage, stage_name, context)
        stage_tasks[stage_name] = tasks_result

        # serialize_stages: chain stages so each starts only after the previous finishes.
        # Do NOT use Task.waiting_on: it serializes to the per-task "wait" list and aiida-workgraph
        # validates wait targets during WorkGraph.from_dict before all tasks exist (AiiDA may reorder keys).
        _new_tasks_all = [t for t in wg.tasks
                           if t.name not in _WG_BUILTIN_TASK_NAMES and t.name not in _names_before]
        if serialize_stages and _prev_stage_barrier_task is not None and _new_tasks_all:
            for _task in _new_tasks_all:
                wg.add_link(_prev_stage_barrier_task.outputs._wait, _task.inputs._wait)

        if serialize_stages and _new_tasks_all:
            barrier = wg.add_task(
                _serialize_barrier,
                name=f'serialize_barrier_{i + 1:03d}_{stage_name}',
            )
            for _task in _new_tasks_all:
                wg.add_link(_task.outputs._wait, barrier.inputs._wait)
            _prev_stage_barrier_task = barrier

        # Build namespace_map with index prefix for ordered display
        # Use 's' prefix (stage) since Python identifiers can't start with digits
        indexed_name = _build_indexed_output_name(i + 1, stage_name)
        namespace_map = {'main': indexed_name}
        if stage_type == 'dos':
            namespace_map['scf'] = indexed_name
            namespace_map['dos'] = indexed_name
        elif stage_type == 'hybrid_bands':
            namespace_map['scf'] = indexed_name

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
