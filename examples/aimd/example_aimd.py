"""Example: AIMD workflow using the lego module.

This example demonstrates two approaches:
1. Manual stage definition with quick_vasp_sequential
2. Convenience function quick_aimd with stage splitting

Both approaches use the AIMD brick for molecular dynamics calculations.
"""

from aiida import orm, load_profile
load_profile()

from pymatgen.core import Structure, Lattice
from quantum_lego import quick_vasp_sequential, quick_aimd, print_sequential_results

# ── Create a simple SnO2 structure ──
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

# ── Common settings ──
code_label = 'VASP-6.5.1-idefix-4@obelix'
potential_family = 'PBE'
potential_mapping = {'Sn': 'Sn_d', 'O': 'O'}
options = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 4,  # PROCESS_MPI=4 (hybrid MPI+OpenMP)
    },
    'custom_scheduler_commands': '''#PBS -l cput=90000:00:00
#PBS -l nodes=1:ppn=88:skylake
#PBS -j oe
#PBS -N sno2_aimd''',
}


# ============================================================
# Approach 1: Manual stages with quick_vasp_sequential
# ============================================================

stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {
            'encut': 400, 'ediff': 1e-4, 'ibrion': 2,
            'nsw': 20, 'isif': 3, 'ismear': 0, 'sigma': 0.05,
        },
        'restart': None,
    },
    {
        'name': 'equilibration',
        'type': 'aimd',
        'structure_from': 'relax',
        'tebeg': 300,
        'nsw': 50,
        'potim': 2.0,
        'mdalgo': 2,
        'smass': 0.0,
        'supercell': [2, 2, 1],
        'incar': {'encut': 400, 'ediff': 1e-5, 'ismear': 0, 'sigma': 0.05},
        'restart': None,
    },
    {
        'name': 'production',
        'type': 'aimd',
        'tebeg': 300,
        'nsw': 100,
        'potim': 1.5,
        'mdalgo': 2,
        'smass': 0.0,
        'incar': {'encut': 400, 'ediff': 1e-5, 'ismear': 0, 'sigma': 0.05},
        'restart': 'equilibration',
        'retrieve': ['XDATCAR'],
    },
]

# Uncomment to submit:
# result = quick_vasp_sequential(
#     structure=structure,
#     stages=stages,
#     code_label=code_label,
#     kpoints_spacing=0.5,
#     potential_family=potential_family,
#     potential_mapping=potential_mapping,
#     options=options,
#     name='sno2_aimd_manual',
# )
# print(f"WorkGraph PK: {result['__workgraph_pk__']}")

# ============================================================
# Approach 2: quick_aimd with stage splitting
# ============================================================

# Uncomment to submit:
result = quick_aimd(
    structure=structure,
    code_label=code_label,
    aimd_stages=[
        {
            'name': 'equilibration',
            'tebeg': 300,
            'nsw': 100,
            'splits': 2,      # -> md_equilibration_0 (50 steps), md_equilibration_1 (50 steps)
            'potim': 2.0,
            'mdalgo': 2,
            'smass': 0.0,
        },
        {
            'name': 'production',
            'tebeg': 300,
            'nsw': 200,
            'splits': 4,      # -> md_production_0..3 (50 steps each)
            'potim': 1.5,
            'mdalgo': 2,
            'smass': 0.0,
        },
    ],
    incar={'encut': 400, 'ediff': 1e-5, 'ismear': 0, 'sigma': 0.05},
    supercell=[2, 2, 1],
    kpoints_spacing=0.5,
    potential_family=potential_family,
    potential_mapping=potential_mapping,
    options=options,
    name='sno2_aimd_quick',
)
print(f"WorkGraph PK: {result['__workgraph_pk__']}")

print("Example script loaded successfully. Uncomment submission blocks to run.")