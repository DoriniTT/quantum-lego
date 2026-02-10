#!/usr/bin/env python
"""Two-stage Bader analysis workflow for SnO2.

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: advanced
Usage:
    python examples/07_advanced_vasp/bader_analysis.py
"""

from examples._shared.config import SNO2_POTCAR, setup_profile
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


stages = [
    {
        'name': 'scf',
        'type': 'vasp',
        'incar': {
            'encut': 520,
            'ediff': 1e-6,
            'ismear': 0,
            'sigma': 0.05,
            'ibrion': -1,
            'nsw': 0,
            'prec': 'Accurate',
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': True,
            'laechg': True,
        },
        'restart': None,
        'kpoints_spacing': 0.03,
        'retrieve': ['AECCAR0', 'AECCAR2', 'CHGCAR', 'OUTCAR'],
    },
    {
        'name': 'bader',
        'type': 'bader',
        'charge_from': 'scf',
    },
]


if __name__ == '__main__':
    setup_profile()

    result = quick_vasp_sequential(
        structure=load_sno2(),
        stages=stages,
        code_label='VASP-6.4.3@bohr',
        kpoints_spacing=0.03,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N example_sno2_bader',
        },
        name='example_sno2_bader',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
