#!/usr/bin/env python
"""Surface enumeration for SnO2 (no VASP, pure analysis).

Single-stage workflow: determine symmetrically distinct Miller indices
for bulk SnO2 (tetragonal rutile, P4_2/mnm #136) up to max_index=1
for Wulff construction planning.

The surface_enumeration brick is a pure-Python calcfunction (no VASP,
no scheduler). It uses pymatgen's SpacegroupAnalyzer to identify the
crystal symmetry and get_symmetrically_distinct_miller_indices to find
the unique surface orientations that need to be calculated.

Expected results for SnO2 (tetragonal, 4/mmm):
  - max_index=1: 5 distinct surfaces — (001), (100), (101), (110), (111)
  - max_index=2: 12 distinct surfaces

API functions: quick_vasp_sequential, print_sequential_results
Usage:
    python run_surface_enumeration.py
"""

from ase.io import read
from aiida import orm, load_profile
from quantum_lego import quick_vasp_sequential, print_sequential_results

load_profile(profile='presto')

# --- Structure ---
atoms = read('structures/sno2.vasp')

# --- Stages ---
stages = [
    {
        'name': 'enumerate_surfaces',
        'type': 'surface_enumeration',
        'structure_from': 'input',
        'max_index': 1,
        'symprec': 0.01,
    },
]

# --- Submit ---
if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=orm.StructureData(ase=atoms),
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',
        kpoints_spacing=0.03,
        potential_family='PBE',
        potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N sno2_surface_enum',
        },
        name='sno2_surface_enum',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('Expected results (SnO2 tetragonal P4_2/mnm, max_index=1):')
    print('  - 5 distinct surface orientations')
    print('  - (0 0 1): 2 equivalent, (1 0 0): 4 equivalent')
    print('  - (1 0 1): 8 equivalent, (1 1 0): 4 equivalent')
    print('  - (1 1 1): 8 equivalent')
    print()
    print('After completion, analyze with:')
    print(f'  from quantum_lego import get_sequential_results, print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()

    # Save PK to file for tracking
    from pathlib import Path
    from datetime import datetime
    pk_file = Path(__file__).parent / 'surface_enumeration_pks.txt'
    with open(pk_file, 'a') as f:
        timestamp = datetime.now().isoformat()
        f.write(f'{timestamp}  sno2_surface_enum  PK={pk}\n')
    print(f'PK saved to {pk_file}')
