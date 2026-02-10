"""
Example NEB workflow with lego sequential stages (SnO2).

Pipeline:
1) Relax initial endpoint (vasp)
2) Relax final endpoint (vasp)
3) Generate NEB intermediate images (generate_neb_images)
4) Run NEB stage 1 (neb)
5) Run CI-NEB stage 2 with restart from stage 1 (neb)

Usage:
    source ~/envs/aiida/bin/activate
    verdi daemon restart
    python examples/lego/neb/run_neb_sno2.py
"""

from pathlib import Path

from aiida import load_profile, orm
from pymatgen.core import Structure

from quantum_lego import quick_vasp_sequential

load_profile()


def build_endpoints() -> tuple[orm.StructureData, orm.StructureData]:
    """Build initial/final endpoint structures for the example."""
    struct_path = Path(__file__).resolve().parent.parent / 'convergence' / 'sno2.vasp'
    initial_pmg = Structure.from_file(str(struct_path))

    # Create a simple displaced final endpoint from the same parent structure.
    final_pmg = initial_pmg.copy()
    final_pmg.translate_sites(
        indices=[0],
        vector=[0.08, 0.00, 0.00],
        frac_coords=True,
        to_unit_cell=True,
    )

    initial_structure = orm.StructureData(pymatgen=initial_pmg)
    final_structure = orm.StructureData(pymatgen=final_pmg)
    return initial_structure, final_structure


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
    code_label='VASP-VTST-6.4.3@bohr',  # Using bohr (obelix has NEB subdirectory issues)
    kpoints_spacing=0.04,
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn', 'O': 'O'},
    options={
        'resources': {
            'num_machines': 1,
            'num_cores_per_machine': 40,  # bohr uses num_cores_per_machine
        },
        'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N sno2_neb_pipeline',
    },
    max_concurrent_jobs=1,
    name='sno2_neb_pipeline',
)

print(f"Submitted WorkGraph PK: {result['__workgraph_pk__']}")
print(f"Stages: {result['__stage_names__']}")
print()
print("Monitor with:")
print(f"  verdi process show {result['__workgraph_pk__']}")
print(f"  verdi process report {result['__workgraph_pk__']}")
print()
print("Get stage summaries:")
print("  from quantum_lego import print_sequential_results")
print(f"  print_sequential_results({result})")