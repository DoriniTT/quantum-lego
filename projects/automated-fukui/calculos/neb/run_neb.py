#!/usr/bin/env python
"""NEB calculation: N diffusion on Pt(211) step edge using VASP + VTST.

Five-stage pipeline using quantum-lego's quick_vasp_sequential:

  1. relax_initial   — Relax initial endpoint (IBRION=2, ISIF=2)
  2. relax_final     — Relax final endpoint (same INCAR)
  3. make_images     — Generate 5 IDPP images from relaxed endpoints
  4. neb_stage1      — Regular NEB (LCLIMB=False, IOPT=3)
  5. neb_cineb       — CI-NEB restart from stage 4 (LCLIMB=True)

Config: VASP-VTST-6.4.3@bohr, par40 (1x40 cores), PBE, kpoints_spacing=0.05

Usage:
    python create_structures.py   # generate structures first
    python run_neb.py             # submit NEB pipeline
"""

from pathlib import Path

from ase.io import read
from aiida import orm, load_profile
from quantum_lego import quick_vasp_sequential, print_sequential_results

load_profile(profile='presto')

# --- Structures ---
struct_dir = Path(__file__).parent / 'structures'

initial_atoms = read(str(struct_dir / 'n_pt_step_initial.vasp'))
initial_structure = orm.StructureData(ase=initial_atoms)

final_atoms = read(str(struct_dir / 'n_pt_step_final.vasp'))
final_structure = orm.StructureData(ase=final_atoms)

# --- Common INCAR ---
COMMON_INCAR = {
    'encut': 400,
    'ediff': 1e-5,
    'prec': 'Normal',
    'ncore': 8,
    'ispin': 1,
    'lreal': 'Auto',
    'lwave': True,
    'lcharg': False,
}

# --- Common NEB INCAR (VTST optimizer) ---
NEB_INCAR = {
    **COMMON_INCAR,
    'ibrion': 3,     # Required for VTST optimizers
    'potim': 0,      # Required for VTST (VTST handles step size)
    'iopt': 3,       # FIRE optimizer from VTST
    'spring': -5,    # NEB spring constant
    'ediffg': -0.1, # Force convergence criterion (eV/A)
    'nsw': 500,      # Max ionic steps
    'ismear': 1,     # Methfessel-Paxton (metal)
    'sigma': 0.1,
    'algo': 'Fast',
}

# --- Stages ---
stages = [
    # Stage 1: Relax initial endpoint
    {
        'name': 'relax_initial',
        'type': 'vasp',
        'incar': {
            **COMMON_INCAR,
            'ibrion': 2,
            'isif': 2,
            'nsw': 200,
            'ediffg': -0.05,
            'ismear': 1,
            'sigma': 0.1,
            'algo': 'Fast',
        },
        'restart': None,
    },
    # Stage 2: Relax final endpoint (separate structure)
    {
        'name': 'relax_final',
        'type': 'vasp',
        'structure': final_structure,
        'incar': {
            **COMMON_INCAR,
            'ibrion': 2,
            'isif': 2,
            'nsw': 200,
            'ediffg': -0.05,
            'ismear': 1,
            'sigma': 0.1,
            'algo': 'Fast',
        },
        'restart': None,
    },
    # Stage 3: Generate 5 IDPP intermediate images
    {
        'name': 'make_images',
        'type': 'generate_neb_images',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'n_images': 5,
        'method': 'idpp',
        'mic': True,
    },
    # Stage 4: Regular NEB (no climbing image) — par120 queue
    {
        'name': 'neb_stage1',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',
        'incar': {
            **NEB_INCAR,
            'LCLIMB': False,
        },
        'options': {
            'resources': {
                'num_machines': 3,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par120\n#PBS -j oe\n#PBS -N n_pt_neb',
        },
    },
    # Stage 5: CI-NEB restart from stage 4 — par120 queue
    {
        'name': 'neb_cineb',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',
        'restart': 'neb_stage1',
        'incar': {
            **NEB_INCAR,
            'LCLIMB': True,
            'ediffg': -0.05,
        },
        'options': {
            'resources': {
                'num_machines': 3,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par120\n#PBS -j oe\n#PBS -N n_pt_cineb',
        },
    },
]

# --- Submit ---
if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=initial_structure,
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',
        kpoints_spacing=0.06,
        potential_family='PBE',
        potential_mapping={'Pt': 'Pt', 'N': 'N'},
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N n_pt_neb',
        },
        max_concurrent_jobs=4,
        name='n_pt_step_neb',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, analyze with:')
    print(f'  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()

    # Save PK to file for tracking
    from datetime import datetime
    pk_file = Path(__file__).parent / 'neb_pks.txt'
    with open(pk_file, 'a') as f:
        timestamp = datetime.now().isoformat()
        f.write(f'{timestamp}  n_pt_step_neb  PK={pk}\n')
    print(f'PK saved to {pk_file}')
