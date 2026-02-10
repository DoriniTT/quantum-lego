"""Lego module for lightweight, incremental VASP/QE calculations.

This module provides a simple API for exploratory computational work:
- Submit a calculation, check results, decide next step, optionally restart
- No presets - always specify parameters manually for maximum flexibility
- Specific file retrieval - standard VASP files are always retrieved, add extras as needed
- Non-blocking default - submit and return immediately

Stage types are implemented as "bricks" (see bricks/ subdirectory):
- vasp: Standard VASP calculations (relaxation, SCF, etc.)
- dos: DOS calculations via BandsWorkChain
- batch: Multiple parallel VASP calculations with varying parameters
- bader: Bader charge analysis
- convergence: ENCUT and k-points convergence testing
- thickness: Slab thickness convergence testing
- hubbard_response: Response calculations for Hubbard U (NSCF + SCF per potential)
- hubbard_analysis: Linear regression and summary for Hubbard U
- aimd: Ab initio molecular dynamics (IBRION=0)
- qe: Quantum ESPRESSO calculations (PwBaseWorkChain)
- cp2k: CP2K calculations
- generate_neb_images: Generate intermediate NEB images from VASP endpoints
- neb: NEB calculations via aiida-vasp ``vasp.neb``

Example usage:

    >>> from quantum_lego import quick_vasp, get_results, get_status
    >>>
    >>> # Single calculation
    >>> pk = quick_vasp(
    ...     structure=my_structure,
    ...     code_label='VASP-6.5.1@localwork',
    ...     incar={'NSW': 100, 'IBRION': 2},
    ...     kpoints_spacing=0.03,
    ...     potential_family='PBE',
    ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
    ...     retrieve=['CHGCAR'],
    ...     name='sno2_relax',
    ... )
    >>>
    >>> # Check status
    >>> get_status(pk)  # -> 'waiting', 'running', 'finished', 'failed'
    >>>
    >>> # Get results when done
    >>> results = get_results(pk)
    >>> print(f"Energy: {results['energy']:.4f} eV")
    >>>
    >>> # Restart from previous calculation
    >>> pk2 = quick_vasp(
    ...     restart_from=pk,
    ...     code_label='VASP-6.5.1@localwork',
    ...     incar={'NSW': 0, 'NEDOS': 2000},
    ...     retrieve=['DOSCAR'],
    ...     name='sno2_dos',
    ... )

DOS calculation using BandsWorkChain:

    >>> from quantum_lego import quick_dos, get_dos_results
    >>>
    >>> # DOS calculation (SCF + DOS handled internally)
    >>> # Note: AiiDA-VASP requires lowercase INCAR keys
    >>> pk = quick_dos(
    ...     structure=my_structure,
    ...     code_label='VASP-6.5.1@localwork',
    ...     scf_incar={'encut': 400, 'ediff': 1e-6, 'ismear': 0},
    ...     dos_incar={'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    ...     kpoints_spacing=0.03,
    ...     dos_kpoints_spacing=0.02,
    ...     potential_family='PBE',
    ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
    ...     retrieve=['DOSCAR'],
    ... )
    >>>
    >>> # Get DOS results
    >>> results = get_dos_results(pk)
    >>> print(f"Energy: {results['energy']:.4f} eV")

Batch DOS calculation (multiple structures in parallel):

    >>> from quantum_lego import quick_dos_batch, get_batch_dos_results
    >>>
    >>> # Compare DOS for different structures
    >>> result = quick_dos_batch(
    ...     structures={'pristine': s1, 'vacancy': s2, 'interstitial': s3},
    ...     code_label='VASP-6.5.1@localwork',
    ...     scf_incar={'encut': 400, 'ediff': 1e-6, 'ismear': 0},
    ...     dos_incar={'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    ...     kpoints_spacing=0.03,
    ...     potential_family='PBE',
    ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
    ...     max_concurrent_jobs=2,  # Run 2 DOS calcs in parallel
    ...     retrieve=['DOSCAR'],
    ... )
    >>> print(f"WorkGraph PK: {result['__workgraph_pk__']}")
    >>>
    >>> # Get batch results when done
    >>> batch_results = get_batch_dos_results(result)
    >>> for key, dos_result in batch_results.items():
    ...     print(f"{key}: E = {dos_result['energy']:.4f} eV")

Sequential multi-stage calculation with restart chaining:

    >>> from quantum_lego import quick_vasp_sequential, print_sequential_results
    >>>
    >>> # Define stages with automatic restart chaining
    >>> stages = [
    ...     {
    ...         'name': 'relax_rough',
    ...         'incar': {'NSW': 100, 'IBRION': 2, 'ISIF': 2, 'ENCUT': 400},
    ...         'kpoints_spacing': 0.06,
    ...         'retrieve': ['CONTCAR', 'OUTCAR'],
    ...     },
    ...     {
    ...         'name': 'relax_fine',
    ...         'incar': {'NSW': 100, 'IBRION': 2, 'ISIF': 2, 'ENCUT': 520},
    ...         'kpoints_spacing': 0.03,
    ...         'retrieve': ['CONTCAR', 'OUTCAR', 'WAVECAR'],
    ...         # restart='previous' is default -> restart from previous stage
    ...     },
    ...     {
    ...         'name': 'relax_supercell',
    ...         'supercell': [2, 2, 1],  # Create supercell, no restart_folder
    ...         'incar': {'NSW': 100, 'IBRION': 2, 'ISIF': 2, 'ENCUT': 520},
    ...         'kpoints_spacing': 0.03,
    ...         'retrieve': ['CONTCAR', 'OUTCAR', 'CHGCAR'],
    ...     },
    ... ]
    >>>
    >>> result = quick_vasp_sequential(
    ...     structure=my_structure,
    ...     stages=stages,
    ...     code_label='VASP-6.5.1@localwork',
    ...     potential_family='PBE',
    ...     potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
    ... )
    >>>
    >>> # Get results when done
    >>> print_sequential_results(result)

Batch stages: multiple parallel calculations with varying parameters
(e.g., Fukui function with fractional charges):

    >>> stages = [
    ...     {
    ...         'name': 'relax_fine',
    ...         'incar': incar_fine,
    ...         'restart': None,
    ...         'kpoints_spacing': 0.03,
    ...         'retrieve': ['CONTCAR', 'OUTCAR', 'CHGCAR'],
    ...     },
    ...     {
    ...         'name': 'fukui_minus',
    ...         'type': 'batch',
    ...         'structure_from': 'relax_fine',
    ...         'base_incar': incar_static,
    ...         'kpoints_spacing': 0.03,
    ...         'retrieve': ['CHGCAR', 'OUTCAR'],
    ...         'calculations': {
    ...             'neutral':   {'incar': {'NELECT': nelect}},
    ...             'delta_005': {'incar': {'NELECT': nelect - 0.05}},
    ...             'delta_010': {'incar': {'NELECT': nelect - 0.10}},
    ...             'delta_015': {'incar': {'NELECT': nelect - 0.15}},
    ...         },
    ...     },
    ... ]
    >>>
    >>> result = quick_vasp_sequential(structure=structure, stages=stages, ...)
    >>>
    >>> # Access batch results
    >>> stage_results = get_stage_results(result, 'fukui_minus')
    >>> for calc_label, calc_data in stage_results['calculations'].items():
    ...     print(f"{calc_label}: E = {calc_data['energy']} eV")
"""

from .workgraph import (
    quick_vasp,
    quick_vasp_batch,
    quick_vasp_sequential,
    quick_dos,
    quick_dos_batch,
    quick_hubbard_u,
    quick_aimd,
    quick_qe,
    quick_qe_sequential,
    get_batch_results_from_workgraph,
)
from .results import (
    get_results,
    get_energy,
    get_batch_results,
    get_batch_energies,
    print_results,
    get_dos_results,
    print_dos_results,
    get_batch_dos_results,
    print_batch_dos_results,
    get_sequential_results,
    get_stage_results,
    print_sequential_results,
)
from .utils import (
    get_status,
    export_files,
    list_calculations,
    get_restart_info,
)
from .types import (
    ResourceDict,
    SchedulerOptions,
    StageContext,
    StageTasksResult,
    VaspResults,
    DosResults,
    BatchResults,
)


__all__ = [
    # Core functions
    'quick_vasp',
    'quick_vasp_batch',
    'quick_vasp_sequential',
    'quick_dos',
    'quick_dos_batch',
    'quick_hubbard_u',
    'quick_aimd',
    'quick_qe',
    'quick_qe_sequential',
    # Result extraction
    'get_results',
    'get_energy',
    'get_batch_results',
    'get_batch_energies',
    'get_batch_results_from_workgraph',
    'print_results',
    'get_dos_results',
    'print_dos_results',
    'get_batch_dos_results',
    'print_batch_dos_results',
    'get_sequential_results',
    'get_stage_results',
    'print_sequential_results',
    # Utilities
    'get_status',
    'export_files',
    'list_calculations',
    'get_restart_info',
    # Type definitions
    'ResourceDict',
    'SchedulerOptions',
    'StageContext',
    'StageTasksResult',
    'VaspResults',
    'DosResults',
    'BatchResults',
]
