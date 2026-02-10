#!/usr/bin/env python
"""Batch DOS workflow for multiple structures in parallel.

API functions: quick_dos_batch, get_batch_dos_results
Difficulty: intermediate
Usage:
    python examples/02_dos/batch_dos.py
"""

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2, load_sno2_pnnm
from quantum_lego import quick_dos_batch


SCF_INCAR = {
    'prec': 'Accurate',
    'encut': 400,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
    'nelm': 120,
}

DOS_INCAR = {
    'nedos': 2000,
    'lorbit': 11,
    'ismear': -5,
    'prec': 'Accurate',
    'algo': 'Normal',
}


if __name__ == '__main__':
    setup_profile()

    structures = {
        'sno2_rutile': load_sno2(),
        'sno2_pnnm': load_sno2_pnnm(),
    }

    result = quick_dos_batch(
        structures=structures,
        code_label=DEFAULT_VASP_CODE,
        scf_incar=SCF_INCAR,
        dos_incar=DOS_INCAR,
        kpoints_spacing=0.05,
        dos_kpoints_spacing=0.04,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=1,
        retrieve=['DOSCAR'],
        name='example_batch_dos',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted batch DOS WorkGraph PK: {pk}')
    print(f'Structures: {list(structures)}')
    print(f'Monitor with: verdi process show {pk}')
    print(f'Detailed report: verdi process report {pk}')
