#!/usr/bin/env python
"""Sequential NEB pipeline with generated images.

API functions: quick_vasp_sequential
Difficulty: advanced
Usage:
    python examples/07_advanced_vasp/neb_pipeline.py
"""

from aiida import orm

from examples._shared.config import setup_profile
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


def build_endpoints() -> tuple[orm.StructureData, orm.StructureData]:
    """Build initial/final endpoint structures for the NEB path."""
    initial_structure = load_sno2()
    final_pmg = initial_structure.get_pymatgen().copy()
    final_pmg.translate_sites(
        indices=[0],
        vector=[0.08, 0.00, 0.00],
        frac_coords=True,
        to_unit_cell=True,
    )
    return initial_structure, orm.StructureData(pymatgen=final_pmg)


if __name__ == '__main__':
    setup_profile()
    initial_structure, final_structure = build_endpoints()

    common_relax_incar = {
        'encut': 520,
        'ediff': 1e-6,
        'ismear': 0,
        'sigma': 0.05,
        'ibrion': 2,
        'nsw': 80,
        'isif': 2,
        'lwave': False,
        'lcharg': False,
    }

    stages = [
        {
            'name': 'relax_initial',
            'type': 'vasp',
            'structure': initial_structure,
            'incar': common_relax_incar,
            'restart': None,
        },
        {
            'name': 'relax_final',
            'type': 'vasp',
            'structure': final_structure,
            'incar': common_relax_incar,
            'restart': None,
        },
        {
            'name': 'make_images',
            'type': 'generate_neb_images',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'n_images': 5,
            'method': 'idpp',
            'mic': True,
        },
        {
            'name': 'neb_stage_1',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_from': 'make_images',
            'incar': {
                'encut': 520,
                'ediff': 1e-6,
                'ediffg': -0.5,
                'ismear': 0,
                'sigma': 0.05,
                'ibrion': 3,
                'iopt': 3,
                'spring': -5,
                'potim': 0.0,
                'nsw': 150,
                'lclimb': False,
            },
            'restart': None,
        },
        {
            'name': 'neb_stage_2_ci',
            'type': 'neb',
            'initial_from': 'relax_initial',
            'final_from': 'relax_final',
            'images_from': 'make_images',
            'incar': {
                'encut': 520,
                'ediff': 1e-6,
                'ediffg': -0.5,
                'ismear': 0,
                'sigma': 0.05,
                'ibrion': 3,
                'iopt': 3,
                'spring': -5,
                'potim': 0.0,
                'nsw': 150,
                'lclimb': True,
            },
            'restart': 'neb_stage_1',
        },
    ]

    result = quick_vasp_sequential(
        structure=initial_structure,
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',
        kpoints_spacing=0.04,
        potential_family='PBE',
        potential_mapping={'Sn': 'Sn', 'O': 'O'},
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N example_sno2_neb',
        },
        max_concurrent_jobs=1,
        name='example_sno2_neb_pipeline',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
