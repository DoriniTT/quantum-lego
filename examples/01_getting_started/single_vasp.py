#!/usr/bin/env python
"""Single VASP hello-world example.

API functions: quick_vasp, get_status
Difficulty: beginner
Usage:
    python examples/01_getting_started/single_vasp.py
"""

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2
from quantum_lego import get_status, quick_vasp


INCAR = {
    'prec': 'Normal',
    'encut': 400,
    'ediff': 1e-5,
    'ismear': 0,
    'sigma': 0.05,
    'nsw': 0,
    'ibrion': -1,
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}


if __name__ == '__main__':
    setup_profile()
    structure = load_sno2()

    pk = quick_vasp(
        structure=structure,
        code_label=DEFAULT_VASP_CODE,
        incar=INCAR,
        kpoints_spacing=0.05,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        retrieve=['OUTCAR'],
        name='example_single_vasp',
    )

    print(f'Submitted calculation PK: {pk}')
    print(f'Current status: {get_status(pk)}')
    print(f'Monitor with: verdi process show {pk}')
