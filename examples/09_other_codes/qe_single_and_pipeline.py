#!/usr/bin/env python
"""QE examples: single calculation and sequential pipeline.

API functions: quick_qe, quick_qe_sequential
Difficulty: advanced
Usage:
    python examples/09_other_codes/qe_single_and_pipeline.py
    python examples/09_other_codes/qe_single_and_pipeline.py sequential
"""

import sys

from examples._shared.config import setup_profile
from examples._shared.structures import create_si_structure
from quantum_lego import quick_qe, quick_qe_sequential


QE_CODE_LABEL = 'pw@localhost'
QE_PSEUDO_FAMILY = 'SSSP/1.3/PBE/efficiency'
QE_OPTIONS = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 4,
    },
}


def run_single() -> int:
    structure = create_si_structure()
    return quick_qe(
        structure=structure,
        code_label=QE_CODE_LABEL,
        parameters={
            'CONTROL': {'calculation': 'scf'},
            'SYSTEM': {'ecutwfc': 30, 'ecutrho': 240},
            'ELECTRONS': {'conv_thr': 1e-6},
        },
        kpoints_spacing=0.15,
        pseudo_family=QE_PSEUDO_FAMILY,
        options=QE_OPTIONS,
        name='example_qe_single',
    )


def run_sequential() -> dict:
    structure = create_si_structure()
    stages = [
        {
            'name': 'relax',
            'type': 'qe',
            'parameters': {
                'CONTROL': {'calculation': 'relax'},
                'SYSTEM': {'ecutwfc': 30, 'ecutrho': 240},
                'ELECTRONS': {'conv_thr': 1e-6},
                'IONS': {},
            },
            'restart': None,
            'kpoints_spacing': 0.15,
        },
        {
            'name': 'scf_fine',
            'type': 'qe',
            'parameters': {
                'CONTROL': {'calculation': 'scf'},
                'SYSTEM': {'ecutwfc': 40, 'ecutrho': 320},
                'ELECTRONS': {'conv_thr': 1e-8},
            },
            'restart': 'relax',
            'kpoints_spacing': 0.10,
        },
    ]

    return quick_qe_sequential(
        structure=structure,
        stages=stages,
        code_label=QE_CODE_LABEL,
        kpoints_spacing=0.15,
        pseudo_family=QE_PSEUDO_FAMILY,
        options=QE_OPTIONS,
        name='example_qe_pipeline',
    )


if __name__ == '__main__':
    setup_profile()

    if len(sys.argv) > 1 and sys.argv[1] == 'sequential':
        result = run_sequential()
        print(f"Submitted QE sequential PK: {result['__workgraph_pk__']}")
    else:
        pk = run_single()
        print(f'Submitted QE single PK: {pk}')
        print('Tip: run with "sequential" for the two-stage pipeline example.')
