#!/usr/bin/env python
"""Four-stage Hubbard U workflow for SnO2 (demonstration case).

API functions: quick_vasp_sequential, get_stage_results, print_sequential_results
Difficulty: advanced
Usage:
    python examples/07_advanced_vasp/hubbard_u_sno2.py
"""

from examples._shared.config import SNO2_POTCAR, setup_profile
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


base_incar = {
    'encut': 400,
    'ediff': 1e-5,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'algo': 'Normal',
    'nelm': 100,
    'lmaxmix': 4,
}

stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {
            **base_incar,
            'ibrion': 2,
            'nsw': 50,
            'isif': 3,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'restart': None,
        'kpoints_spacing': 0.05,
        'retrieve': ['CONTCAR', 'OUTCAR'],
    },
    {
        'name': 'ground_state',
        'type': 'vasp',
        'structure_from': 'relax',
        'incar': {
            **base_incar,
            'nsw': 0,
            'ibrion': -1,
            'ldau': True,
            'ldautype': 3,
            'ldaul': [2, -1],
            'ldauj': [0.0, 0.0],
            'ldauu': [0.0, 0.0],
            'lorbit': 11,
            'lwave': True,
            'lcharg': True,
        },
        'restart': None,
        'kpoints_spacing': 0.05,
        'retrieve': ['OUTCAR'],
    },
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',
        'structure_from': 'relax',
        'target_species': 'Sn',
        'potential_values': [-0.2, -0.1, 0.1, 0.2],
        'ldaul': 2,
        'incar': base_incar,
        'kpoints_spacing': 0.05,
    },
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',
        'structure_from': 'relax',
        'target_species': 'Sn',
        'ldaul': 2,
    },
]


if __name__ == '__main__':
    setup_profile()

    result = quick_vasp_sequential(
        structure=load_sno2(),
        stages=stages,
        code_label='VASP-6.5.1-idefix-4@obelix',
        kpoints_spacing=0.05,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
            'custom_scheduler_commands': (
                '#PBS -l cput=90000:00:00\n'
                '#PBS -l nodes=1:ppn=88:skylake\n'
                '#PBS -j oe\n'
                '#PBS -N example_sno2_hubbard_u'
            ),
        },
        name='example_sno2_hubbard_u',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
