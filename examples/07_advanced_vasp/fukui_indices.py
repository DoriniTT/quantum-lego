#!/usr/bin/env python
"""Fukui index analysis for SnO2 using the fukui_dynamic + fukui_analysis bricks.

Computes condensed Fukui functions f⁺(r), f⁻(r) for a SnO2 surface slab by
running eight fractional-occupation VASP calculations (4 for f⁻, 4 for f⁺)
and interpolating the resulting charge-density files.

Pipeline stages:
  1. scf         — static SCF on the neutral slab (lcharg=True, lwave=True)
  2. fukui_batch — 8 fractional-charge VASP runs (fukui_dynamic brick)
  3. fukui_plus  — interpolate f⁺(r) CHGCAR files (fukui_analysis brick)
  4. fukui_minus — interpolate f⁻(r) CHGCAR files (fukui_analysis brick)

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: advanced
Usage:
    python examples/07_advanced_vasp/fukui_indices.py
"""

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


# ---------------------------------------------------------------------------
# INCAR presets
# ---------------------------------------------------------------------------
SCF_INCAR = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'ibrion': -1,
    'nsw': 0,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': True,
    'lcharg': True,
}

FUKUI_INCAR = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'ibrion': -1,
    'nsw': 0,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': True,
}

# ---------------------------------------------------------------------------
# delta_n_map: fractional electron offsets used for each Fukui interpolation.
# These match the four offset points produced by fukui_dynamic.
# ---------------------------------------------------------------------------
DELTA_N_MAP = {
    'neutral': 0.00,
    'delta_005': 0.05,
    'delta_010': 0.10,
    'delta_015': 0.15,
}

# ---------------------------------------------------------------------------
# Stage pipeline
# ---------------------------------------------------------------------------
stages = [
    # Stage 1: converged SCF for the neutral system
    {
        'name': 'scf',
        'type': 'vasp',
        'incar': SCF_INCAR,
        'restart': None,
        'kpoints_spacing': 0.03,
        'retrieve': ['OUTCAR'],
    },
    # Stage 2: 8 fractional-charge runs (4 for f-, 4 for f+)
    # NELECT is determined automatically from the POTCAR data in AiiDA.
    {
        'name': 'fukui_batch',
        'type': 'fukui_dynamic',
        'structure_from': 'scf',
        'base_incar': FUKUI_INCAR,
        'kpoints_spacing': 0.03,
    },
    # Stage 3: interpolate f+(r) from the four f+ CHGCAR files
    {
        'name': 'fukui_plus',
        'type': 'fukui_analysis',
        'batch_from': 'fukui_batch',
        'fukui_type': 'plus',
        'delta_n_map': DELTA_N_MAP,
    },
    # Stage 4: interpolate f-(r) from the four f- CHGCAR files
    {
        'name': 'fukui_minus',
        'type': 'fukui_analysis',
        'batch_from': 'fukui_batch',
        'fukui_type': 'minus',
        'delta_n_map': DELTA_N_MAP,
    },
]


if __name__ == '__main__':
    setup_profile()

    result = quick_vasp_sequential(
        structure=load_sno2(),
        stages=stages,
        code_label=DEFAULT_VASP_CODE,
        kpoints_spacing=0.03,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=4,
        name='example_sno2_fukui',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, inspect results with:')
    print('  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()
    print('The fukui_plus and fukui_minus stages each output a')
    print('CHGCAR_FUKUI.vasp SinglefileData node that can be downloaded')
    print('and visualised with VESTA or a similar tool.')
