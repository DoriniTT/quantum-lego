#!/usr/bin/env python
"""NEB calculation: N diffusion on Pt(211) step edge.

Demonstrates the full two-stage NEB pipeline (regular NEB → CI-NEB) using the
classic ASE Pt step-edge tutorial system.

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: advanced
Usage:
    python examples/06_surface/neb_pt_step_edge.py

Requires:
    - VASP with the VTST patch (for IOPT/IBRION=3 and LCLIMB).
    - At least 3 compute nodes × 40 cores for the NEB stages (7 images + 2 endpoints).
    - PBE POTCAR library with 'Pt' and 'N' entries.

Pipeline stages:
    1. relax_initial  — Relax N at fcc hollow below the step (IBRION=2, ISIF=2)
    2. relax_final    — Relax N at hcp hollow above the step (same INCAR)
    3. make_images    — Interpolate 5 images with IDPP from relaxed endpoints
    4. neb_stage1     — Regular NEB (LCLIMB=False, IOPT=3 FIRE, SPRING=-5)
    5. neb_cineb      — CI-NEB restart from stage 4 (LCLIMB=True)

The structures are built from the classic ASE NEB tutorial (FaceCenteredCubic
directions d1/d2/d3, 2×1×2 supercell, a=3.9 Å, 10 Å vacuum).  Run
create_structures.py (or the snippet below) to generate POSCAR files before
submitting this script.

Structure generation snippet::

    from ase import Atoms
    from ase.lattice.cubic import FaceCenteredCubic
    import numpy as np

    d3 = [2, 1, 1]
    d1 = np.cross(np.array([0, 1, 1]), d3)
    d2 = np.cross(np.array([0, -1, 1]), d3)
    slab = FaceCenteredCubic(symbol='Pt', directions=[d1, d2, d3],
                             size=(2, 1, 2), latticeconstant=3.9)
    uc = slab.get_cell()
    uc[2] += [0.0, 0.0, 10.0]
    slab.set_cell(uc, scale_atoms=False)

    x1, x2 = 1.379, 4.137
    x3, y2, z1, z2 = 2.759, 2.238, 7.165, 6.439

    initial = slab.copy()
    initial += Atoms('N', positions=[((x2 + x1) / 2.0, 0.0, z1 + 1.5)])

    final = slab.copy()
    final += Atoms('N', positions=[(x3, y2 + 1.0, z2 + 3.5)])
"""

from pathlib import Path

from ase.io import read
from aiida import orm

from examples._shared.config import setup_profile
from quantum_lego import quick_vasp_sequential, print_sequential_results

setup_profile()

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------
STRUCTURES_DIR = Path(__file__).resolve().parent.parent.parent / 'structures'

# Alternatively, point to your own POSCAR files:
#   STRUCTURES_DIR = Path('path/to/your/structures')

initial_atoms = read(str(STRUCTURES_DIR / 'n_pt_step_initial.vasp'))
final_atoms = read(str(STRUCTURES_DIR / 'n_pt_step_final.vasp'))

initial_structure = orm.StructureData(ase=initial_atoms)
final_structure = orm.StructureData(ase=final_atoms)

# ---------------------------------------------------------------------------
# INCAR templates
# ---------------------------------------------------------------------------
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

RELAX_INCAR = {
    **COMMON_INCAR,
    'ibrion': 2,
    'isif': 2,
    'nsw': 200,
    'ediffg': -0.05,
    'ismear': 1,
    'sigma': 0.1,
    'algo': 'Fast',
}

NEB_INCAR = {
    **COMMON_INCAR,
    'ibrion': 3,    # Required for VTST optimisers
    'potim': 0,     # VTST handles step size
    'iopt': 3,      # FIRE optimiser from VTST
    'spring': -5,   # NEB spring constant (eV/Å²)
    'ediffg': -0.1,
    'nsw': 500,
    'ismear': 1,
    'sigma': 0.1,
    'algo': 'Fast',
}

# ---------------------------------------------------------------------------
# Cluster options  — adjust for your HPC environment
# ---------------------------------------------------------------------------
NEB_OPTIONS = {
    'resources': {
        'num_machines': 3,
        'num_cores_per_machine': 40,
    },
    # Uncomment and adapt for PBS/SLURM:
    # 'custom_scheduler_commands': '#PBS -q par120\n#PBS -j oe\n#PBS -N n_pt_neb',
}

# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
stages = [
    # Stage 1 — relax initial endpoint
    {
        'name': 'relax_initial',
        'type': 'vasp',
        'incar': RELAX_INCAR,
        'restart': None,
    },
    # Stage 2 — relax final endpoint (different starting structure)
    {
        'name': 'relax_final',
        'type': 'vasp',
        'structure': final_structure,
        'incar': RELAX_INCAR,
        'restart': None,
    },
    # Stage 3 — interpolate 5 intermediate images with IDPP
    {
        'name': 'make_images',
        'type': 'generate_neb_images',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'n_images': 5,
        'method': 'idpp',
        'mic': True,
    },
    # Stage 4 — regular NEB (no climbing image)
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
        'options': NEB_OPTIONS,
    },
    # Stage 5 — CI-NEB restart from stage 4
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
        'options': NEB_OPTIONS,
    },
]

# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=initial_structure,
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',   # update for your code label
        kpoints_spacing=0.06,
        potential_family='PBE',
        potential_mapping={'Pt': 'Pt', 'N': 'N'},
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
        },
        max_concurrent_jobs=4,
        name='n_pt_step_neb',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, inspect results with:')
    print(f'  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
