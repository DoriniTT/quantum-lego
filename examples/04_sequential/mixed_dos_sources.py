#!/usr/bin/env python
"""Single WorkGraph DOS workflow with mixed structure sources.

API functions: quick_vasp_sequential
Difficulty: intermediate
Usage:
    python examples/04_sequential/mixed_dos_sources.py
"""

from aiida import orm

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2, load_sno2_pnnm
from quantum_lego import quick_vasp_sequential


RELAX_INCAR = {
    'nsw': 60,
    'ibrion': 2,
    'isif': 2,
    'ediff': 1e-5,
    'encut': 400,
    'prec': 'Normal',
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
}

DOS_SCF_INCAR = {
    'encut': 400,
    'ediff': 1e-6,
    'prec': 'Normal',
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
}

DOS_INCAR = {
    'encut': 400,
    'prec': 'Normal',
    'nedos': 2000,
    'lorbit': 11,
    'ismear': -5,
}


def build_stages(external_structure: orm.StructureData) -> list[dict]:
    return [
        {
            'name': 'relax',
            'type': 'vasp',
            'incar': RELAX_INCAR,
            'restart': None,
            'kpoints_spacing': 0.06,
            'retrieve': ['CONTCAR', 'OUTCAR'],
        },
        {
            'name': 'dos_relaxed',
            'type': 'dos',
            'structure_from': 'relax',
            'scf_incar': DOS_SCF_INCAR,
            'dos_incar': DOS_INCAR,
            'kpoints_spacing': 0.06,
            'dos_kpoints_spacing': 0.04,
            'retrieve': ['DOSCAR'],
        },
        {
            'name': 'dos_external',
            'type': 'dos',
            'structure': external_structure,
            'scf_incar': DOS_SCF_INCAR,
            'dos_incar': DOS_INCAR,
            'kpoints_spacing': 0.06,
            'dos_kpoints_spacing': 0.04,
            'retrieve': ['DOSCAR'],
        },
    ]


if __name__ == '__main__':
    setup_profile()

    initial_structure = load_sno2()
    external_structure = load_sno2_pnnm()

    result = quick_vasp_sequential(
        structure=initial_structure,
        stages=build_stages(external_structure),
        code_label=DEFAULT_VASP_CODE,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=2,
        name='example_mixed_dos_sources',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
