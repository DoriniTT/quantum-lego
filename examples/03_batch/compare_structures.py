#!/usr/bin/env python
"""Compare two structures with static SCF VASP calculations.

API functions: quick_vasp_batch
Difficulty: intermediate
Usage:
    python examples/03_batch/compare_structures.py
"""

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2, load_sno2_pnnm
from quantum_lego import quick_vasp_batch


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

    structures = {
        'sno2_rutile': load_sno2(),
        'sno2_pnnm': load_sno2_pnnm(),
    }

    result = quick_vasp_batch(
        structures=structures,
        code_label=DEFAULT_VASP_CODE,
        incar=INCAR,
        kpoints_spacing=0.04,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        retrieve=['OUTCAR'],
        max_concurrent_jobs=1,
        name='example_compare_structures',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
