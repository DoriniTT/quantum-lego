"""VASP workflow builders for the lego module.

This module provides VASP-specific workflow functions for single, batch,
and sequential calculations. It handles VASP WorkChain setup, restart
chaining, supercell transformations, and multi-stage pipelines.
"""

import typing as t

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task

from .common.utils import extract_total_energy
from .utils import prepare_restart_settings
from .common.utils import deep_merge_dicts
from .workflow_utils import (
    _prepare_builder_inputs,
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
        extract_total_energy,
        name='extract_energy',
        energies=vasp_task.outputs.misc,
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
            extract_total_energy,
            name=energy_task_name,
            energies=vasp_task.outputs.misc,
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
