"""
Slab thickness convergence test: SnO2 (110) surface.

Two-stage pipeline on obelix cluster:
  1. Bulk relaxation (VASP)
  2. Thickness convergence (generates slabs at multiple thicknesses,
     relaxes them, computes surface energies, checks convergence)

Usage:
    source ~/envs/aiida/bin/activate
    verdi daemon restart
    python examples/lego/thickness/run_thickness_sno2.py
    verdi process show <PK>
"""
from pathlib import Path

from aiida import load_profile, orm
from pymatgen.core import Structure

load_profile()

# ============================================================================
# Configuration - Edit these for your system
# ============================================================================

STRUCTURE_FILE = Path(__file__).parent.parent / 'convergence' / 'sno2.vasp'
CODE_LABEL = 'VASP-6.5.1-idefix-4@obelix'
POTENTIAL_FAMILY = 'PBE'
POTENTIAL_MAPPING = {'Sn': 'Sn_d', 'O': 'O'}

OPTIONS = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 4,
    },
    'custom_scheduler_commands': '''#PBS -l cput=90000:00:00
#PBS -l nodes=1:ppn=88:skylake
#PBS -j oe
#PBS -N thickness_sno2''',
}

# ============================================================================
# Stage definitions
# ============================================================================

stages = [
    # Stage 1: Bulk relaxation
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
    # Stage 2: Thickness convergence
    {
        'name': 'thick_conv',
        'type': 'thickness',
        'structure_from': 'bulk',     # Use relaxed bulk structure
        'energy_from': 'bulk',        # Use bulk energy
        'miller_indices': [1, 1, 0],
        'layer_counts': [3, 5, 7],
        'convergence_threshold': 0.05,  # J/m² (loose for local testing)
        'slab_incar': {
            'prec': 'Accurate',
            'encut': 400,
            'ismear': 0,
            'sigma': 0.05,
            'ediff': 1e-5,
            'ibrion': 2,
            'nsw': 20,
            'isif': 2,      # Relax ions only (fixed cell)
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'slab_kpoints_spacing': 0.06,
        'min_vacuum_thickness': 12.0,
    },
]

# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    if not STRUCTURE_FILE.exists():
        print(f"Error: Structure file not found: {STRUCTURE_FILE}")
        print("Place a SnO2 bulk POSCAR/CONTCAR at that path.")
        exit(1)

    pmg_struct = Structure.from_file(str(STRUCTURE_FILE))
    structure = orm.StructureData(pymatgen=pmg_struct)

    from quantum_lego import quick_vasp_sequential

    result = quick_vasp_sequential(
        structure=structure,
        stages=stages,
        code_label=CODE_LABEL,
        kpoints_spacing=0.03,
        potential_family=POTENTIAL_FAMILY,
        potential_mapping=POTENTIAL_MAPPING,
        options=OPTIONS,
        max_concurrent_jobs=4,  # obelix can handle multiple concurrent jobs
        name='sno2_thickness_convergence',
    )

    pk = result['__workgraph_pk__']
    print(f"Submitted WorkGraph PK: {pk}")
    print()
    print("Monitor with:")
    print(f"  verdi process show {pk}")
    print(f"  verdi process report {pk}")
    print()
    print("Get results when done:")
    print("  from quantum_lego import print_sequential_results")
    print(f"  print_sequential_results({result})")
