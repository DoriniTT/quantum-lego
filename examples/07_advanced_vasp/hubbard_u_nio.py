#!/usr/bin/env python
"""Convenience Hubbard U workflow for NiO using quick_hubbard_u.

Calculates the Hubbard U parameter for Ni d-electrons in NiO using the
linear response method (Cococcioni & de Gironcoli). Uses the quick_hubbard_u
convenience API which auto-builds a 3-stage pipeline:
  1. Ground state SCF (LORBIT=11, LWAVE/LCHARG=True)
  2. Hubbard response (NSCF + SCF per perturbation potential)
  3. Hubbard analysis (linear regression to extract U)

Validated result: NiO 2x2x2 AFM supercell (32 atoms) gives U(Ni-d) ~ 5.1 eV
with R^2 > 0.999 (VASP wiki reference: 5.58 eV).

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
    'sigma': 0.2,
    'prec': 'Accurate',
    'lreal': 'Auto',       # for supercell
    'lmaxmix': 4,          # required for d-electrons
    'ispin': 2,             # spin-polarized
    'magmom': [2.0] * 4 + [0.6] * 4,  # adjust to your structure
}

if __name__ == '__main__':
    setup_profile()

    result = quick_hubbard_u(
        structure=load_nio(),
        code_label='VASP-6.5.1-idefix-4@obelix',
        target_species='Ni',
        incar=incar,
        potential_values=[-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20],
        ldaul=2,
        kpoints_spacing=0.03,
        potential_family='PBE',
        potential_mapping={'Ni': 'Ni', 'O': 'O'},
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
        max_concurrent_jobs=4,
        name='example_nio_hubbard_u',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result.get("__stage_names__", "auto-generated")}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, check results with:')
    print('  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()
    print('Expected: U(Ni-d) ~ 5.1 eV, R^2 > 0.99')
