"""
AIMD Module for PS-TEROS

Ab initio molecular dynamics calculations on slab structures.
Sequential AIMD stages with automatic restart chaining.
"""

import typing as t
from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task, dynamic, namespace
from quantum_lego.core.common.utils import extract_total_energy
from quantum_lego.core.common.utils import get_vasp_parser_settings, extract_max_jobs_value


def get_settings():
    """
    Parser settings for aiida-vasp.

    Note: This function is kept for backward compatibility.
    New code should use get_vasp_parser_settings() from utils.py
    """
    return get_vasp_parser_settings()


def prepare_aimd_parameters(
    base_parameters: dict,
    stage_config: dict
) -> dict:
    """
    Prepare INCAR parameters for a single AIMD stage.

    Takes base AIMD parameters and injects stage-specific values from stage_config.
    Required parameters: TEBEG, NSW
    Optional parameters: TEEND (defaults to TEBEG), POTIM, MDALGO, SMASS

    Args:
        base_parameters: Base AIMD INCAR dict (IBRION=0, MDALGO, POTIM, etc.)
        stage_config: Dict with AIMD stage parameters (TEBEG, NSW required)

    Returns:
        Complete INCAR dict for this AIMD stage

    Raises:
        ValueError: If TEBEG or NSW not in stage_config
    """
    # Start with base parameters
    aimd_incar = base_parameters.copy()

    # Validate required parameters
    if 'TEBEG' not in stage_config or 'NSW' not in stage_config:
        raise ValueError("aimd_stages dict must contain 'TEBEG' and 'NSW' parameters")

    # Extract required parameters
    tebeg = stage_config['TEBEG']
    nsw = stage_config['NSW']

    # TEEND defaults to TEBEG (constant temperature MD)
    teend = stage_config.get('TEEND', tebeg)

    # Set temperature and steps
    aimd_incar['TEBEG'] = tebeg
    aimd_incar['TEEND'] = teend
    aimd_incar['NSW'] = nsw

    # Set optional AIMD parameters if provided (override base)
    for param in ['POTIM', 'MDALGO', 'SMASS']:
        if param in stage_config:
            aimd_incar[param] = stage_config[param]

    # Ensure IBRION=0 for MD mode
    aimd_incar['IBRION'] = 0

    return aimd_incar


def _aimd_single_stage_scatter_impl(
    slabs: dict,
    temperature: float,
    steps: int,
    code: orm.Code,
    aimd_parameters: dict,
    potential_family: str,
    potential_mapping: dict,
    options: dict,
    kpoints_spacing: float,
    clean_workdir: bool,
    restart_folders: dict = None,
):
    """
    Internal implementation of AIMD single stage scatter.
    This is the actual logic without @task.graph decorator.
    """
    from aiida.plugins import WorkflowFactory
    
    # Get VASP workchain
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    structures_out = {}
    remote_folders_out = {}
    energies_out = {}

    # Scatter: create AIMD task for each slab (runs in parallel)
    for slab_label, slab_structure in slabs.items():
        # Prepare parameters for this stage
        stage_params = prepare_aimd_parameters(aimd_parameters, temperature, steps)

        # Build VASP inputs
        vasp_inputs = {
            'structure': slab_structure,
            'code': code,
            'parameters': {'incar': stage_params},
            'options': dict(options),
            'potential_family': potential_family,
            'potential_mapping': dict(potential_mapping),
            'kpoints_spacing': kpoints_spacing,
            'clean_workdir': clean_workdir,
            'settings': orm.Dict(dict=get_settings()),
        }

        # Add restart folder if provided for this slab
        if restart_folders and slab_label in restart_folders:
            vasp_inputs['restart_folder'] = restart_folders[slab_label]

        # Create VASP task
        aimd_task = VaspTask(**vasp_inputs)

        # Store outputs for this slab
        structures_out[slab_label] = aimd_task.structure
        remote_folders_out[slab_label] = aimd_task.remote_folder
        energies_out[slab_label] = extract_total_energy(energies=aimd_task.misc).result

    # Gather: return collected results
    return {
        'structures': structures_out,
        'remote_folders': remote_folders_out,
        'energies': energies_out,
    }


@task.graph
def aimd_single_stage_scatter(
    slabs: t.Annotated[dict[str, orm.StructureData], dynamic(orm.StructureData)],
    stage_config: dict,
    code: orm.Code,
    base_aimd_parameters: dict,
    potential_family: str,
    potential_mapping: dict,
    options: dict,
    kpoints_spacing: float,
    clean_workdir: bool,
    restart_folders: t.Annotated[dict[str, orm.RemoteData], dynamic(orm.RemoteData)] = {},
    structure_aimd_overrides: dict[str, dict] = None,
    max_number_jobs: int = None,
) -> t.Annotated[dict, namespace(structures=dynamic(orm.StructureData), remote_folders=dynamic(orm.RemoteData), energies=dynamic(orm.Float))]:
    """
    Run single AIMD stage on all slabs in parallel using scatter-gather pattern.

    This function handles ONE AIMD stage for all slabs.
    Call it multiple times sequentially to build multi-stage AIMD workflows.

    Args:
        slabs: Dictionary of slab structures to run AIMD on
        stage_config: Stage AIMD configuration dict with TEBEG, NSW (required)
                     and TEEND, POTIM, MDALGO, SMASS (optional)
        code: VASP code
        base_aimd_parameters: Base AIMD INCAR parameters
                             Applied to all structures by default
        potential_family: Potential family name
        potential_mapping: Element to potential mapping
        options: Scheduler options
        kpoints_spacing: K-points spacing
        clean_workdir: Whether to clean work directory
        restart_folders: Optional dict of RemoteData for restart (from previous stage)
        structure_aimd_overrides: Optional per-structure INCAR overrides.
                                 Format: {structure_name: {INCAR_key: value}}
                                 Missing structures use base_aimd_parameters.
        max_number_jobs: Maximum number of concurrent VASP calculations (None = unlimited)

    Returns:
        Dictionary with outputs per slab:
            - structures: Output structures from this stage
            - remote_folders: RemoteData nodes for potential next stage restart
            - energies: Total energies from this stage
    """
    from aiida_workgraph import get_current_graph

    # Set max_number_jobs on this workgraph to control concurrency
    if max_number_jobs is not None:
        wg = get_current_graph()
        max_jobs_value = extract_max_jobs_value(max_number_jobs)
        wg.max_number_jobs = max_jobs_value

    # Get VASP workchain
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    structures_out = {}
    remote_folders_out = {}
    energies_out = {}

    # Scatter: create AIMD task for each slab (runs in parallel)
    for slab_label, slab_structure in slabs.items():
        # Step 1: Apply stage AIMD parameters to base
        stage_params = prepare_aimd_parameters(base_aimd_parameters, stage_config)

        # Step 2: Merge with structure-specific overrides
        if structure_aimd_overrides and slab_label in structure_aimd_overrides:
            # Shallow merge: structure overrides take precedence
            merged_params = {**stage_params, **structure_aimd_overrides[slab_label]}
        else:
            # No override for this structure
            merged_params = stage_params

        # Build VASP inputs
        vasp_inputs = {
            'structure': slab_structure,
            'code': code,
            'parameters': {'incar': merged_params},
            'options': dict(options),
            'potential_family': potential_family,
            'potential_mapping': dict(potential_mapping),
            'kpoints_spacing': kpoints_spacing,
            'clean_workdir': clean_workdir,
            'settings': orm.Dict(dict=get_settings()),
        }

        # Add restart folder if provided for this slab
        if restart_folders and slab_label in restart_folders:
            vasp_inputs['restart_folder'] = restart_folders[slab_label]

        # Create VASP task
        aimd_task = VaspTask(**vasp_inputs)

        # Store outputs for this slab
        structures_out[slab_label] = aimd_task.structure
        remote_folders_out[slab_label] = aimd_task.remote_folder
        energies_out[slab_label] = extract_total_energy(energies=aimd_task.misc).result

    # Gather: return collected results
    return {
        'structures': structures_out,
        'remote_folders': remote_folders_out,
        'energies': energies_out,
    }
