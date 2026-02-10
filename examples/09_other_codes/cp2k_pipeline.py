#!/usr/bin/env python
"""CP2K examples: geometry-optimization pipeline and MD stage.

API functions: quick_vasp_sequential
Difficulty: advanced
Usage:
    python examples/09_other_codes/cp2k_pipeline.py
    python examples/09_other_codes/cp2k_pipeline.py md
"""

import sys

from examples._shared.config import setup_profile
from examples._shared.structures import create_si_structure
from quantum_lego import quick_vasp_sequential


CP2K_CODE_LABEL = 'cp2k@cluster'
BASIS_FILE = '/path/to/BASIS_MOLOPT'
PSEUDO_FILE = '/path/to/GTH_POTENTIALS'
CP2K_OPTIONS = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 4,
    },
}


def run_geo_opt_then_energy() -> dict:
    structure = create_si_structure()
    stages = [
        {
            'name': 'geo_opt',
            'type': 'cp2k',
            'parameters': {
                'GLOBAL': {'RUN_TYPE': 'GEO_OPT', 'PRINT_LEVEL': 'LOW'},
                'FORCE_EVAL': {
                    'METHOD': 'QUICKSTEP',
                    'DFT': {
                        'BASIS_SET_FILE_NAME': 'BASIS_MOLOPT',
                        'POTENTIAL_FILE_NAME': 'GTH_POTENTIALS',
                        'MGRID': {'CUTOFF': 300, 'REL_CUTOFF': 60},
                        'QS': {'EPS_DEFAULT': 1e-10},
                        'SCF': {'EPS_SCF': 1e-6, 'MAX_SCF': 50, 'SCF_GUESS': 'RESTART'},
                        'XC': {'XC_FUNCTIONAL': {'_': 'PBE'}},
                    },
                    'SUBSYS': {
                        'KIND': [{'_': 'Si', 'BASIS_SET': 'DZVP-MOLOPT-SR-GTH', 'POTENTIAL': 'GTH-PBE'}],
                    },
                },
                'MOTION': {'GEO_OPT': {'MAX_ITER': 50, 'OPTIMIZER': 'BFGS'}},
            },
            'restart': None,
            'file': {'basis': BASIS_FILE, 'pseudo': PSEUDO_FILE},
        },
        {
            'name': 'energy',
            'type': 'cp2k',
            'parameters': {
                'GLOBAL': {'RUN_TYPE': 'ENERGY', 'PRINT_LEVEL': 'MEDIUM'},
                'FORCE_EVAL': {
                    'METHOD': 'QUICKSTEP',
                    'DFT': {
                        'BASIS_SET_FILE_NAME': 'BASIS_MOLOPT',
                        'POTENTIAL_FILE_NAME': 'GTH_POTENTIALS',
                        'MGRID': {'CUTOFF': 400, 'REL_CUTOFF': 80},
                        'QS': {'EPS_DEFAULT': 1e-12},
                        'SCF': {'EPS_SCF': 1e-8, 'MAX_SCF': 100, 'SCF_GUESS': 'RESTART'},
                        'XC': {'XC_FUNCTIONAL': {'_': 'PBE'}},
                    },
                    'SUBSYS': {
                        'KIND': [{'_': 'Si', 'BASIS_SET': 'DZVP-MOLOPT-SR-GTH', 'POTENTIAL': 'GTH-PBE'}],
                    },
                },
            },
            'restart': 'geo_opt',
            'structure_from': 'geo_opt',
            'file': {'basis': BASIS_FILE, 'pseudo': PSEUDO_FILE},
        },
    ]

    return quick_vasp_sequential(
        structure=structure,
        code_label=CP2K_CODE_LABEL,
        stages=stages,
        options=CP2K_OPTIONS,
        name='example_cp2k_pipeline',
    )


def run_md() -> dict:
    structure = create_si_structure()
    stages = [
        {
            'name': 'md_equil',
            'type': 'cp2k',
            'parameters': {
                'GLOBAL': {'RUN_TYPE': 'MD', 'PRINT_LEVEL': 'LOW'},
                'FORCE_EVAL': {
                    'METHOD': 'QUICKSTEP',
                    'DFT': {
                        'BASIS_SET_FILE_NAME': 'BASIS_MOLOPT',
                        'POTENTIAL_FILE_NAME': 'GTH_POTENTIALS',
                        'MGRID': {'CUTOFF': 250, 'REL_CUTOFF': 50},
                        'SCF': {'EPS_SCF': 1e-5, 'MAX_SCF': 30, 'SCF_GUESS': 'RESTART'},
                        'XC': {'XC_FUNCTIONAL': {'_': 'PBE'}},
                    },
                    'SUBSYS': {
                        'KIND': [{'_': 'Si', 'BASIS_SET': 'DZVP-MOLOPT-SR-GTH', 'POTENTIAL': 'GTH-PBE'}],
                    },
                },
                'MOTION': {
                    'MD': {
                        'ENSEMBLE': 'NVT',
                        'STEPS': 100,
                        'TIMESTEP': 0.5,
                        'TEMPERATURE': 300,
                        'THERMOSTAT': {'TYPE': 'NOSE', 'NOSE': {'TIMECON': 100}},
                    },
                    'PRINT': {
                        'TRAJECTORY': {'EACH': {'MD': 5}},
                        'VELOCITIES': {'EACH': {'MD': 5}},
                    },
                },
            },
            'restart': None,
            'file': {'basis': BASIS_FILE, 'pseudo': PSEUDO_FILE},
            'retrieve': ['*-pos-1.xyz', '*-vel-1.xyz'],
        },
    ]

    return quick_vasp_sequential(
        structure=structure,
        code_label=CP2K_CODE_LABEL,
        stages=stages,
        options=CP2K_OPTIONS,
        name='example_cp2k_md',
    )


if __name__ == '__main__':
    setup_profile()

    if len(sys.argv) > 1 and sys.argv[1] == 'md':
        result = run_md()
        print(f"Submitted CP2K MD PK: {result['__workgraph_pk__']}")
    else:
        result = run_geo_opt_then_energy()
        print(f"Submitted CP2K pipeline PK: {result['__workgraph_pk__']}")
        print('Tip: run with "md" to submit the CP2K MD example.')
