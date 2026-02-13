"""DOS workflow builders for the lego module.

This module provides DOS helper functions. Single DOS flows are routed
through ``quick_vasp_sequential`` and the DOS brick system, while
``quick_dos_batch`` keeps a dedicated parallel implementation.
"""

import typing as t

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task

from .common.utils import deep_merge_dicts
from .workflow_utils import (
    _prepare_builder_inputs,
    _wait_for_completion,
)


def quick_dos_sequential(
    structure: t.Union[orm.StructureData, int] = None,
    stages: t.List[dict] = None,
    code_label: str = None,
    kpoints_spacing: float = 0.03,
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    options: dict = None,
    max_concurrent_jobs: int = None,
    name: str = 'quick_dos_sequential',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> dict:
    """Submit one or more DOS stages through quick_vasp_sequential.

    This is a thin DOS-focused wrapper around ``quick_vasp_sequential``.
    Every stage is validated as DOS and delegated to the DOS brick.

    Returns:
        Dict with the same shape as ``quick_vasp_sequential``.
    """
    if structure is None:
        raise ValueError("structure is required")
    if stages is None:
        raise ValueError("stages is required - provide list of DOS stage configurations")
    if code_label is None:
        raise ValueError("code_label is required")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    normalized_stages = []
    for index, stage in enumerate(stages):
        normalized_stage = dict(stage)
        stage_name = normalized_stage.get('name', f'stage_{index + 1}')
        stage_type = normalized_stage.get('type', 'dos')
        if stage_type != 'dos':
            raise ValueError(
                f"Stage '{stage_name}' has type='{stage_type}'. "
                f"quick_dos_sequential only accepts DOS stages."
            )
        normalized_stage['type'] = 'dos'
        normalized_stages.append(normalized_stage)

    from .vasp_workflows import quick_vasp_sequential

    return quick_vasp_sequential(
        structure=structure,
        stages=normalized_stages,
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
    Submit a single DOS calculation through the stage/brick system.

    Thin wrapper around ``quick_dos_sequential`` that builds one DOS stage
    and preserves the public return contract ``{'__workgraph_pk__': pk}``.

    Args:
        structure: StructureData or PK of structure to calculate DOS for.
        code_label: VASP code label (e.g., 'VASP-6.5.1@localwork')
        scf_incar: INCAR parameters for SCF stage (e.g., {'encut': 400, 'ediff': 1e-5}).
                   lwave and lcharg are forced to True.
        dos_incar: INCAR parameters for DOS stage (e.g., {'nedos': 2000, 'lorbit': 11}).
                   Passed to the DOS brick.
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
        Dict with '__workgraph_pk__' key containing the WorkGraph PK.

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

    # Keep compatibility with previous quick_dos behavior
    scf_incar_final = dict(scf_incar)
    scf_incar_final['lwave'] = True
    scf_incar_final['lcharg'] = True

    stage = {
        'name': 'dos',
        'type': 'dos',
        'structure': structure,
        'scf_incar': scf_incar_final,
        'dos_incar': dict(dos_incar),
    }

    if kpoints is not None:
        stage['kpoints'] = kpoints
    elif kpoints_spacing != 0.03:
        stage['kpoints_spacing'] = kpoints_spacing

    if dos_kpoints is not None:
        stage['dos_kpoints'] = dos_kpoints
    elif dos_kpoints_spacing is not None:
        stage['dos_kpoints_spacing'] = dos_kpoints_spacing

    if retrieve is not None:
        stage['retrieve'] = retrieve

    result = quick_dos_sequential(
        structure=structure,
        stages=[stage],
        code_label=code_label,
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        max_concurrent_jobs=None,
        name=name,
        wait=wait,
        poll_interval=poll_interval,
        clean_workdir=clean_workdir,
    )

    return {
        '__workgraph_pk__': result['__workgraph_pk__'],
    }


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
