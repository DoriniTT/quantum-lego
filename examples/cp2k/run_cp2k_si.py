#!/usr/bin/env python
"""Example: CP2K calculations using the lego module.

This script demonstrates:
1. Sequential CP2K pipeline with quick_vasp_sequential() using cp2k brick type

Prerequisites:
- AiiDA profile configured with CP2K code (e.g., 'cp2k@cluster')
- Basis and pseudopotential files (BASIS_MOLOPT, GTH_POTENTIALS)
- Structure to calculate (we create a simple Si structure here)

Usage:
    verdi daemon restart
    python run_cp2k_si.py
    verdi process show <PK>

Notes:
- Adjust code_label to match your CP2K installation
- Adjust basis_file and pseudo_file paths to your data files
- CP2K uses nested dict parameters (GLOBAL, FORCE_EVAL, MOTION)
- Energy is automatically converted from Hartree to eV
"""

from aiida import orm, load_profile
from ase.build import bulk

# Import shared structure utilities
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from common_structures import create_si_structure

load_profile()


# Paths to basis and pseudopotential files - adjust to your system
BASIS_FILE = '/path/to/BASIS_MOLOPT'
PSEUDO_FILE = '/path/to/GTH_POTENTIALS'


def run_cp2k_geo_opt_then_energy():
    """Run a CP2K pipeline: GEO_OPT -> ENERGY with restart.

    This demonstrates:
    - Two-stage CP2K pipeline
    - Restart chaining between stages
    - Structure passing from optimization to single point
    """
    from quantum_lego import quick_vasp_sequential, get_status

    structure = create_si_structure()

    stages = [
        {
            'name': 'geo_opt',
            'type': 'cp2k',
            'parameters': {
                'GLOBAL': {
                    'RUN_TYPE': 'GEO_OPT',
                    'PRINT_LEVEL': 'LOW',
                },
                'FORCE_EVAL': {
                    'METHOD': 'QUICKSTEP',
                    'DFT': {
                        'BASIS_SET_FILE_NAME': 'BASIS_MOLOPT',
                        'POTENTIAL_FILE_NAME': 'GTH_POTENTIALS',
                        'MGRID': {
                            'CUTOFF': 300,  # Ry
                            'REL_CUTOFF': 60,
                        },
                        'QS': {
                            'EPS_DEFAULT': 1e-10,
                        },
                        'SCF': {
                            'EPS_SCF': 1e-6,
                            'MAX_SCF': 50,
                            'SCF_GUESS': 'RESTART',
                        },
                        'XC': {
                            'XC_FUNCTIONAL': {'_': 'PBE'},
                        },
                    },
                    'SUBSYS': {
                        'KIND': [
                            {
                                '_': 'Si',
                                'BASIS_SET': 'DZVP-MOLOPT-SR-GTH',
                                'POTENTIAL': 'GTH-PBE',
                            },
                        ],
                    },
                },
                'MOTION': {
                    'GEO_OPT': {
                        'MAX_ITER': 50,
                        'OPTIMIZER': 'BFGS',
                    },
                },
            },
            'restart': None,
            'file': {
                'basis': BASIS_FILE,
                'pseudo': PSEUDO_FILE,
            },
        },
        {
            'name': 'energy',
            'type': 'cp2k',
            'parameters': {
                'GLOBAL': {
                    'RUN_TYPE': 'ENERGY',
                    'PRINT_LEVEL': 'MEDIUM',
                },
                'FORCE_EVAL': {
                    'METHOD': 'QUICKSTEP',
                    'DFT': {
                        'BASIS_SET_FILE_NAME': 'BASIS_MOLOPT',
                        'POTENTIAL_FILE_NAME': 'GTH_POTENTIALS',
                        'MGRID': {
                            'CUTOFF': 400,  # Higher for single point
                            'REL_CUTOFF': 80,
                        },
                        'QS': {
                            'EPS_DEFAULT': 1e-12,
                        },
                        'SCF': {
                            'EPS_SCF': 1e-8,
                            'MAX_SCF': 100,
                            'SCF_GUESS': 'RESTART',
                        },
                        'XC': {
                            'XC_FUNCTIONAL': {'_': 'PBE'},
                        },
                    },
                    'SUBSYS': {
                        'KIND': [
                            {
                                '_': 'Si',
                                'BASIS_SET': 'DZVP-MOLOPT-SR-GTH',
                                'POTENTIAL': 'GTH-PBE',
                            },
                        ],
                    },
                },
            },
            'restart': 'geo_opt',  # Use wavefunction from previous stage
            'structure_from': 'geo_opt',  # Use optimized structure
            'file': {
                'basis': BASIS_FILE,
                'pseudo': PSEUDO_FILE,
            },
        },
    ]

    result = quick_vasp_sequential(
        structure=structure,
        code_label='cp2k@cluster',  # Adjust to your CP2K code label
        stages=stages,
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
        },
        name='si_cp2k_pipeline',
    )

    pk = result['__workgraph_pk__']
    print(f"Submitted CP2K sequential pipeline: PK = {pk}")
    print(f"Stages: {result['__stage_names__']}")
    print(f"Status: {get_status(pk)}")
    print(f"Monitor with: verdi process show {pk}")
    return result


def run_cp2k_md():
    """Run a CP2K MD simulation.

    This demonstrates:
    - AIMD-like usage with CP2K brick
    - Temperature and timestep control in MOTION section
    - Trajectory output
    """
    from quantum_lego import quick_vasp_sequential, get_status

    structure = create_si_structure()

    stages = [
        {
            'name': 'md_equil',
            'type': 'cp2k',
            'parameters': {
                'GLOBAL': {
                    'RUN_TYPE': 'MD',
                    'PRINT_LEVEL': 'LOW',
                },
                'FORCE_EVAL': {
                    'METHOD': 'QUICKSTEP',
                    'DFT': {
                        'BASIS_SET_FILE_NAME': 'BASIS_MOLOPT',
                        'POTENTIAL_FILE_NAME': 'GTH_POTENTIALS',
                        'MGRID': {
                            'CUTOFF': 250,
                            'REL_CUTOFF': 50,
                        },
                        'SCF': {
                            'EPS_SCF': 1e-5,
                            'MAX_SCF': 30,
                            'SCF_GUESS': 'RESTART',
                        },
                        'XC': {
                            'XC_FUNCTIONAL': {'_': 'PBE'},
                        },
                    },
                    'SUBSYS': {
                        'KIND': [
                            {
                                '_': 'Si',
                                'BASIS_SET': 'DZVP-MOLOPT-SR-GTH',
                                'POTENTIAL': 'GTH-PBE',
                            },
                        ],
                    },
                },
                'MOTION': {
                    'MD': {
                        'ENSEMBLE': 'NVT',
                        'STEPS': 100,  # Short for testing
                        'TIMESTEP': 0.5,  # fs
                        'TEMPERATURE': 300,
                        'THERMOSTAT': {
                            'TYPE': 'NOSE',
                            'NOSE': {
                                'TIMECON': 100,
                            },
                        },
                    },
                    'PRINT': {
                        'TRAJECTORY': {
                            'EACH': {'MD': 5},
                        },
                        'VELOCITIES': {
                            'EACH': {'MD': 5},
                        },
                    },
                },
            },
            'restart': None,
            'file': {
                'basis': BASIS_FILE,
                'pseudo': PSEUDO_FILE,
            },
            'retrieve': ['*-pos-1.xyz', '*-vel-1.xyz'],  # Retrieve trajectory files
        },
    ]

    result = quick_vasp_sequential(
        structure=structure,
        code_label='cp2k@cluster',  # Adjust to your CP2K code label
        stages=stages,
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
        },
        name='si_cp2k_md',
    )

    pk = result['__workgraph_pk__']
    print(f"Submitted CP2K MD simulation: PK = {pk}")
    print(f"Status: {get_status(pk)}")
    print(f"Monitor with: verdi process show {pk}")
    return result


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'md':
        run_cp2k_md()
    else:
        run_cp2k_geo_opt_then_energy()
        print("\nTip: Run with 'md' argument for the MD example:")
        print("  python run_cp2k_si.py md")
