#!/usr/bin/env python
"""Single DOS workflow for a canonical SnO2 structure.

API functions: quick_dos, print_dos_results
Difficulty: beginner
Usage:
    python examples/02_dos/single_dos.py
"""

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2
from quantum_lego import quick_dos


SCF_INCAR = {
    'prec': 'Accurate',
    'encut': 400,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
    'nelm': 120,
    'lorbit': 11,
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
    structure = load_sno2()

    result = quick_dos(
        structure=structure,
        code_label=DEFAULT_VASP_CODE,
        scf_incar=SCF_INCAR,
        dos_incar=DOS_INCAR,
        kpoints_spacing=0.05,
        dos_kpoints_spacing=0.04,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        retrieve=['DOSCAR'],
        name='example_single_dos',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted DOS PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
    print('Get summary with: from quantum_lego import print_dos_results; print_dos_results(PK)')
