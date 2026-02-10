#!/usr/bin/env python
"""Convergence test for ENCUT and k-point spacing on SnO2.

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: intermediate
Usage:
    python examples/05_convergence/encut_kpoints.py
"""

from examples._shared.config import SNO2_POTCAR, setup_profile
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


stages = [
    {
        'name': 'conv_test',
        'type': 'convergence',
        'incar': {
            'prec': 'Accurate',
            'ismear': 0,
            'sigma': 0.05,
            'ediff': 1e-6,
            'ibrion': -1,
            'nsw': 0,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'conv_settings': {
            'cutoff_start': 300,
            'cutoff_stop': 500,
            'cutoff_step': 100,
            'kspacing_start': 0.05,
            'kspacing_stop': 0.03,
            'kspacing_step': 0.01,
            'cutoff_kconv': 400,
            'kspacing_cutconv': 0.04,
        },
        'convergence_threshold': 0.001,
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
            'custom_scheduler_commands': '#PBS -l cput=90000:00:00\n'
                                         '#PBS -l nodes=1:ppn=88:skylake\n'
                                         '#PBS -j oe\n'
                                         '#PBS -N example_sno2_conv',
        },
        max_concurrent_jobs=4,
        name='example_sno2_convergence',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
    print(f'Detailed report: verdi process report {pk}')
