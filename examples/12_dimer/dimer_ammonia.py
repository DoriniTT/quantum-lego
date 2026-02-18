#!/usr/bin/env python
"""Improved Dimer Method (IDM) example: ammonia nitrogen inversion.

Demonstrates the full IDM transition-state workflow on the ammonia flipping
reaction (from the VASP wiki), using three sequential stages:

  1. vib        — vibrational analysis (IBRION=5, NWRITE=3)
                  Yields the dimer axis: eigenvectors of the hardest imaginary
                  mode after division by sqrt(mass).
  2. idm_ts     — IDM TS refinement (IBRION=44)
                  The dimer axis is parsed from stage-1 OUTCAR at submission
                  time and injected into POSCAR via scheduler prepend_text.
                  Key diagnostic: curvature along dimer direction should be
                  *negative* throughout.  Positive values indicate the
                  algorithm has not found a true saddle point.
  3. vib_verify — vibrational analysis on the relaxed TS (IBRION=5, NWRITE=3)
                  Confirms a first-order saddle point (exactly one large
                  imaginary frequency).  Any f/i mode with |ν| < 5 cm⁻¹
                  and large "dx" / near-zero "dy","dz" is a translational
                  artefact and should be ignored for thermodynamic properties.

Reference: https://vasp.at/wiki/Improved_dimer_method

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: advanced
Usage:
    python examples/12_dimer/dimer_ammonia.py
"""

from __future__ import annotations

import sys
import textwrap
from io import StringIO
from pathlib import Path

# Allow running from any directory (repo root or examples/12_dimer/)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ase.io import read as ase_read
from aiida import orm

from examples._shared.config import setup_profile, DEFAULT_VASP_CODE, LOCALWORK_OPTIONS
from quantum_lego import quick_vasp_sequential, print_sequential_results

# ---------------------------------------------------------------------------
# Ammonia structure (from the VASP wiki IDM example)
# Simple molecule in a large box so Γ-only k-point sampling is sufficient.
# ---------------------------------------------------------------------------
_POSCAR_TEXT = textwrap.dedent("""\
    ammonia flipping
    1.
     6.  0.  0.
     0.  7.  0.
     0.  0.  8.
    H  N
    3  1
    cart
    -0.872954  0.000000  -0.504000
     0.000000  0.000000   1.008000
     0.872954  0.000000  -0.504000
     0.000000  0.000000   0.000000
""")


def _build_structure() -> orm.StructureData:
    atoms = ase_read(StringIO(_POSCAR_TEXT), format='vasp')
    return orm.StructureData(ase=atoms)


# ---------------------------------------------------------------------------
# INCAR definitions
#
# Brick defaults (applied automatically, user values override):
#   IBRION=5  stages (vasp brick):  ediff=1e-6, nfree=2, potim=0.02, nsw=1, nwrite=3
#   IBRION=44 stages (dimer brick): ediff=1e-6, ediffg=-0.005, nsw=200
#
# Key tuning advice:
#   ediffg (IDM)  — CRITICAL: residual forces > ~0.01 eV/Å produce spurious
#                   imaginary modes in vib_verify.  Default -0.005 eV/Å is safe.
#                   If vib_verify still shows > 1 large imaginary mode, tighten
#                   to -0.001 eV/Å and/or increase NSW.
#   potim (vib)   — Reduce to 0.01–0.015 Å for soft/floppy systems.
#   ediff         — 1e-6 works for most cases; use 1e-7 for very accurate
#                   thermochemistry (reaction barriers ≲ 0.1 eV).
# ---------------------------------------------------------------------------
_COMMON = {
    'encut': 400,
    'prec': 'Normal',
    'ispin': 1,
    'lreal': 'Auto',
    'lwave': True,
    'lcharg': False,
}

VIB_INCAR = {
    **_COMMON,
    'ibrion': 5,
    # Brick defaults fill in: ediff=1e-6, nfree=2, potim=0.02, nsw=1, nwrite=3
    # Override here if needed, e.g.: 'potim': 0.015, 'ediff': 1e-7
}

IDM_INCAR = {
    **_COMMON,
    'ibrion': 44,
    # Brick defaults fill in: ediff=1e-6, ediffg=-0.005, nsw=200
    # To tighten further: 'ediffg': -0.001, 'nsw': 400
}


# ---------------------------------------------------------------------------
# Stage pipeline
# ---------------------------------------------------------------------------
STAGES = [
    # Stage 1: vibrational analysis to obtain the dimer axis (hardest f/i mode)
    {
        'name': 'vib',
        'type': 'vasp',
        'incar': VIB_INCAR,
        'restart': None,
        'retrieve': ['OUTCAR'],
    },
    # Stage 2: IDM transition-state search
    # The dimer axis is read from 'vib' OUTCAR at submission time and appended
    # to POSCAR via scheduler prepend_text before VASP starts.
    {
        'name': 'idm_ts',
        'type': 'dimer',
        'vibrational_from': 'vib',
        'incar': IDM_INCAR,
        'restart': None,
    },
    # Stage 3: verify relaxed TS is a first-order saddle point
    # structure_from='idm_ts' passes the clean StructureData from CONTCAR
    # (ASE strips the extra dimer-direction lines VASP appends for restarts).
    {
        'name': 'vib_verify',
        'type': 'vasp',
        'structure_from': 'idm_ts',
        'incar': VIB_INCAR,
        'restart': None,
        'retrieve': ['OUTCAR'],
    },
]


if __name__ == '__main__':
    setup_profile()

    structure = _build_structure()

    result = quick_vasp_sequential(
        structure=structure,
        stages=STAGES,
        code_label=DEFAULT_VASP_CODE,
        kpoints_spacing=1.0,  # Γ-only for this molecule
        potential_family='PBE',
        potential_mapping={'H': 'H', 'N': 'N'},
        options={
            **LOCALWORK_OPTIONS,
            'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 4},
        },
        max_concurrent_jobs=1,
        name='ammonia_dimer',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f"Stages: {result['__stage_names__']}")
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('Key output ports on the WorkGraph node (visible in verdi process show):')
    print('  idm_ts_ts_analysis           — orm.Dict: curvature summary')
    print('  vib_verify_vibrational_modes — orm.Dict: imaginary mode summary')
    print()
    print('Quick check after completion:')
    print(f'  from aiida.orm import load_node')
    print(f'  wg = load_node({pk})')
    print(f'  print(wg.outputs.idm_ts_ts_analysis.get_dict())')
    print(f'  print(wg.outputs.vib_verify_vibrational_modes.get_dict())')
    print()
    print('After completion, analyze with:')
    print(f'  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()
    print('Key diagnostics:')
    print('  idm_ts.dimer_curvatures  — should be negative throughout')
    print('  vib_verify OUTCAR        — should have exactly one large f/i mode')
    print('    (any f/i < 5 cm⁻¹ with large dx / near-zero dy,dz is translational)')
