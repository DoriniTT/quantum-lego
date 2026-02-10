#!/usr/bin/env python
"""Slab thickness convergence for SnO2(110) surface.

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: advanced
Usage:
    python examples/06_surface/thickness_convergence.py
"""

from examples._shared.config import SNO2_POTCAR, setup_profile
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


stages = [
    {
        'name': 'bulk',
        'type': 'vasp',
        'incar': {
            'prec': 'Accurate',
            'encut': 400,
            'ismear': 0,
            'sigma': 0.05,
            'ediff': 1e-5,
            'ibrion': 2,
            'nsw': 20,
            'isif': 3,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'restart': None,
        'kpoints_spacing': 0.06,
        'retrieve': ['CONTCAR', 'OUTCAR'],
    },
    {
        'name': 'thick_conv',
        'type': 'thickness',
        'structure_from': 'bulk',
        'energy_from': 'bulk',
        'miller_indices': [1, 1, 0],
        'layer_counts': [3, 5, 7],
        'convergence_threshold': 0.05,
        'slab_incar': {
            'prec': 'Accurate',
            'encut': 400,
            'ismear': 0,
            'sigma': 0.05,
            'ediff': 1e-5,
            'ibrion': 2,
            'nsw': 20,
            'isif': 2,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'slab_kpoints_spacing': 0.06,
        'min_vacuum_thickness': 12.0,
    },
]


if __name__ == '__main__':
    setup_profile()

    result = quick_vasp_sequential(
        structure=load_sno2(),
        stages=stages,
        code_label='VASP-6.5.1-idefix-4@obelix',
        kpoints_spacing=0.03,
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
                                         '#PBS -N example_thickness_sno2',
        },
        max_concurrent_jobs=4,
        name='example_sno2_thickness_convergence',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
    print(f'Detailed report: verdi process report {pk}')
