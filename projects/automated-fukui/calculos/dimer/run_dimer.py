#!/usr/bin/env python
"""Improved dimer method (IDM) example: ammonia flipping (VASP wiki).

Pipeline:
  1) vib     — vibrational analysis (IBRION=5, NWRITE=3)
  2) idm_ts  — improved dimer method refinement (IBRION=44)

Reference: https://vasp.at/wiki/Improved_dimer_method
"""

from pathlib import Path

from ase.io import read
from aiida import orm, load_profile
from quantum_lego import quick_vasp_sequential

load_profile(profile='presto')


POSCAR_PATH = Path(__file__).parent / 'POSCAR'
atoms = read(str(POSCAR_PATH))
structure = orm.StructureData(ase=atoms)


COMMON_INCAR = {
    'encut': 400,
    'ediff': 1e-5,
    'prec': 'Normal',
    'ispin': 1,
    'lreal': 'Auto',
    'lwave': True,
    'lcharg': False,
}


stages = [
    {
        'name': 'vib',
        'type': 'vasp',
        'incar': {
            **COMMON_INCAR,
            'nsw': 1,
            'ibrion': 5,   # vibrational analysis
            'nfree': 2,    # central differences
            'potim': 0.02, # numerical differentiation step
            'nwrite': 3,   # print eigenvectors after division by SQRT(mass)
        },
        'restart': None,
        'retrieve': ['OUTCAR'],
    },
    {
        'name': 'idm_ts',
        'type': 'dimer',
        'vibrational_from': 'vib',
        'incar': {
            **COMMON_INCAR,
            'nsw': 100,
            'ibrion': 44,   # improved dimer method
            'ediffg': -0.03,
        },
        'restart': None,
    },
]


if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=structure,
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',
        kpoints_spacing=1.0,  # gamma-only for this large cell
        potential_family='PBE',
        potential_mapping={'H': 'H', 'N': 'N'},
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N ammonia_idm',
        },
        max_concurrent_jobs=1,
        name='ammonia_idm',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f"Stages: {result['__stage_names__']}")
