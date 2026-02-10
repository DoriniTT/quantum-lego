"""Type definitions for Quantum Lego workflows.

This module provides TypedDict definitions for configuration dictionaries,
result structures, and other commonly-used types across the codebase.

The types defined here are used to improve IDE support, static type checking,
and documentation of the brick API functions.
"""

from typing import TypedDict, NotRequired, Any, Dict, List, Union

__all__ = [
    'ResourceDict',
    'SchedulerOptions',
    'StageContext',
    'StageTasksResult',
    'VaspResults',
    'DosResults',
    'BatchResults',
]


# =============================================================================
# Scheduler and Resource Types
# =============================================================================

class ResourceDict(TypedDict):
    """Resource specification for AiiDA calculations.

    Attributes:
        num_machines: Number of machines/nodes to use
        num_mpiprocs_per_machine: MPI processes per machine
        num_cores_per_mpiproc: Optional cores per MPI process
    """
    num_machines: int
    num_mpiprocs_per_machine: int
    num_cores_per_mpiproc: NotRequired[int]


class SchedulerOptions(TypedDict, total=False):
    """Scheduler options for AiiDA calculations.

    Attributes:
        resources: Resource specification (required)
        account: Account name for the scheduler
        queue_name: Queue/partition name
        custom_scheduler_commands: Custom scheduler directives
        max_wallclock_seconds: Maximum walltime in seconds
        withmpi: Whether to run with MPI
    """
    resources: ResourceDict
    account: str
    queue_name: str
    custom_scheduler_commands: str
    max_wallclock_seconds: int
    withmpi: bool


# =============================================================================
# Stage Context and Results
# =============================================================================

class StageContext(TypedDict, total=False):
    """Context passed to brick create_stage_tasks functions.

    This dict contains shared configuration and references to previous stage tasks.

    Attributes:
        code: AiiDA Code for the calculation
        potential_family: Name of the potential family (e.g., 'PBE')
        potential_mapping: Mapping of element symbols to potential names
        options: Scheduler options
        base_kpoints_spacing: Default k-points spacing (Å⁻¹)
        clean_workdir: Whether to clean working directory after completion
        stage_tasks: Dict mapping stage names to their task outputs
        stage_types: Dict mapping stage names to their brick types
        stage_names: List of stage names in order
        stage_index: Current stage index
        input_structure: Input structure for the workflow
    """
    code: Any  # AiiDA Code node
    potential_family: str
    potential_mapping: Dict[str, str]
    options: SchedulerOptions
    base_kpoints_spacing: float
    clean_workdir: bool
    stage_tasks: Dict[str, 'StageTasksResult']
    stage_types: Dict[str, str]
    stage_names: List[str]
    stage_index: int
    input_structure: Any  # AiiDA StructureData node


class StageTasksResult(TypedDict, total=False):
    """Result returned by brick create_stage_tasks functions.

    Contains references to WorkGraph task nodes for later connection.
    The exact keys vary by brick type.

    Attributes:
        vasp: VASP calculation task node
        energy: Energy extraction task node
        structure: Structure (for pass-through in DOS/batch stages)
        dos: DOS calculation task node
        batch_tasks: Dict of batch calculation task nodes
        qe: Quantum ESPRESSO calculation task node
        cp2k: CP2K calculation task node
        neb: NEB calculation task node
    """
    vasp: Any
    energy: Any
    structure: Any
    dos: Any
    batch_tasks: Dict[str, Any]
    qe: Any
    cp2k: Any
    neb: Any


# =============================================================================
# Result Types
# =============================================================================

class VaspResults(TypedDict, total=False):
    """Results from a VASP calculation.

    Attributes:
        energy: Total energy in eV (None if extraction failed)
        structure: Relaxed structure (None if nsw=0 or extraction failed)
        misc: Parsed VASP results dict
        files: Retrieved FolderData node
        pk: Process PK
    """
    energy: Union[float, None]
    structure: Any  # AiiDA StructureData or None
    misc: Union[Dict[str, Any], None]
    files: Any  # AiiDA FolderData or None
    pk: int


class DosResults(TypedDict, total=False):
    """Results from a DOS calculation.

    Attributes:
        energy: Total energy from SCF step in eV (None if extraction failed)
        scf_misc: Parsed VASP results from SCF step
        dos_misc: Parsed VASP results from DOS step
        dos: DOS data array
        projectors: Projector data
        pk: Process PK
    """
    energy: Union[float, None]
    scf_misc: Union[Dict[str, Any], None]
    dos_misc: Union[Dict[str, Any], None]
    dos: Any  # AiiDA ArrayData or None
    projectors: Any  # AiiDA ArrayData or None
    pk: int


class BatchResults(TypedDict):
    """Results from a batch calculation stage.

    Attributes:
        calculations: Dict mapping calculation labels to their results
        pk: WorkGraph PK
    """
    calculations: Dict[str, VaspResults]
    pk: int
