#!/usr/bin/env python
"""Sequential workflow: relax SnO2 then run DOS.

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: intermediate
Usage:
    python examples/04_sequential/relax_then_dos.py
"""

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential
from quantum_lego.core.bricks.connections import get_brick_info


RELAX_INCAR = {
    'nsw': 50,
    'ibrion': 2,
    'isif': 2,
    'ediff': 1e-4,
    'encut': 400,
    'prec': 'Normal',
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
    'lwave': True,
    'lcharg': True,
}

DOS_SCF_INCAR = {
    'encut': 400,
    'ediff': 1e-5,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Normal',
    'algo': 'Normal',
    'nsw': 0,
    'ibrion': -1,
}

DOS_INCAR = {
    'encut': 400,
    'prec': 'Normal',
    'nedos': 2000,
    'lorbit': 11,
    'ismear': -5,
    'nsw': 0,
    'ibrion': -1,
}


if __name__ == '__main__':
    setup_profile()

    print('=== Brick ports used in this workflow ===')
    for brick_type in ['vasp', 'dos']:
        info = get_brick_info(brick_type)
        print(f"{brick_type}: inputs={list(info['inputs'])}, outputs={list(info['outputs'])}")

    stages = [
        {
            'name': 'relax',
            'type': 'vasp',
            'incar': RELAX_INCAR,
            'restart': None,
            'kpoints_spacing': 0.06,
            'retrieve': ['CONTCAR', 'OUTCAR'],
        },
        {
            'name': 'dos',
            'type': 'dos',
            'structure_from': 'relax',
            'scf_incar': DOS_SCF_INCAR,
            'dos_incar': DOS_INCAR,
            'kpoints_spacing': 0.06,
            'dos_kpoints_spacing': 0.04,
            'retrieve': ['DOSCAR'],
        },
    ]

    result = quick_vasp_sequential(
        structure=load_sno2(),
        stages=stages,
        code_label=DEFAULT_VASP_CODE,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=1,
        name='example_relax_then_dos',
    )

    pk = result['__workgraph_pk__']
    print(f'WorkGraph PK: {pk}')
    print(f'Monitor: verdi process show {pk}')
    print('Results: from quantum_lego import print_sequential_results; print_sequential_results(result)')
