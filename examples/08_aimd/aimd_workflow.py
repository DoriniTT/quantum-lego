#!/usr/bin/env python
"""AIMD example using the quick_aimd convenience helper.

API functions: quick_aimd
Difficulty: advanced
Usage:
    python examples/08_aimd/aimd_workflow.py
"""

from aiida import orm
from pymatgen.core import Lattice, Structure

from examples._shared.config import setup_profile
from quantum_lego import quick_aimd


if __name__ == '__main__':
    setup_profile()

    lattice = Lattice.tetragonal(4.737, 3.186)
    sno2 = Structure(
        lattice,
        ['Sn', 'Sn', 'O', 'O', 'O', 'O'],
        [
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5],
            [0.3056, 0.3056, 0.0],
            [0.6944, 0.6944, 0.0],
            [0.1944, 0.8056, 0.5],
            [0.8056, 0.1944, 0.5],
        ],
    )
    structure = orm.StructureData(pymatgen=sno2)

    result = quick_aimd(
        structure=structure,
        code_label='VASP-6.5.1-idefix-4@obelix',
        aimd_stages=[
            {
                'name': 'equilibration',
                'tebeg': 300,
                'nsw': 100,
                'splits': 2,
                'potim': 2.0,
                'mdalgo': 2,
                'smass': 0.0,
            },
            {
                'name': 'production',
                'tebeg': 300,
                'nsw': 200,
                'splits': 4,
                'potim': 1.5,
                'mdalgo': 2,
                'smass': 0.0,
            },
        ],
        incar={'encut': 400, 'ediff': 1e-5, 'ismear': 0, 'sigma': 0.05},
        supercell=[2, 2, 1],
        kpoints_spacing=0.5,
        potential_family='PBE',
        potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
            'custom_scheduler_commands': (
                '#PBS -l cput=90000:00:00\n'
                '#PBS -l nodes=1:ppn=88:skylake\n'
                '#PBS -j oe\n'
                '#PBS -N example_sno2_aimd'
            ),
        },
        name='example_sno2_aimd_quick',
    )

    print(f'WorkGraph PK: {result["__workgraph_pk__"]}')
    print('Monitor with: verdi process show <PK>')
