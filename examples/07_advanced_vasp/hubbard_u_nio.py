#!/usr/bin/env python
"""Convenience Hubbard U workflow for NiO.

API functions: quick_hubbard_u
Difficulty: advanced
Usage:
    python examples/07_advanced_vasp/hubbard_u_nio.py
"""

from examples._shared.config import setup_profile
from examples._shared.structures import load_nio
from quantum_lego import quick_hubbard_u


incar = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'algo': 'Normal',
    'nelm': 200,
    'ispin': 2,
    'magmom': [2.0] * 4 + [0.6] * 4,
    'lmaxmix': 4,
}

if __name__ == '__main__':
    setup_profile()

    result = quick_hubbard_u(
        structure=load_nio(),
        code_label='VASP-6.5.1-idefix-4@obelix',
        target_species='Ni',
        incar=incar,
        potential_values=[-0.2, -0.1, 0.1, 0.2],
        ldaul=2,
        kpoints_spacing=0.04,
        potential_family='PBE',
        potential_mapping={'Ni': 'Ni_pv', 'O': 'O'},
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
            'custom_scheduler_commands': (
                '#PBS -l cput=90000:00:00\n'
                '#PBS -l nodes=1:ppn=88:skylake\n'
                '#PBS -j oe\n'
                '#PBS -N example_nio_hubbard_u'
            ),
        },
        name='example_nio_hubbard_u',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result.get("__stage_names__", "auto-generated")}')
    print(f'Monitor with: verdi process show {pk}')
