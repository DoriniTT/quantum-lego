"""Specialized workflow builders for the lego module.

This module provides workflow functions for specialized calculation types
including Hubbard U parameter calculations and Ab Initio Molecular Dynamics
(AIMD) simulations.
"""

import typing as t

from aiida import orm

from .vasp_workflows import quick_vasp_sequential


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
