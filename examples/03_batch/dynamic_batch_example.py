#!/usr/bin/env python
"""Dynamic batch relaxation of all SnO2(110) surface terminations.

Demonstrates the dynamic_batch brick for fan-out workflows where the set of
structures is only known at runtime (here: slab terminations generated from a
relaxed bulk cell).

Pipeline stages:
  1. bulk_relax  — relax bulk SnO2 (vasp, ISIF=3)
  2. slab_terms  — generate all symmetrized SnO2(110) terminations (surface_terminations)
  3. slab_relax  — relax every termination in parallel (dynamic_batch)

The dynamic_batch brick uses a scatter-gather pattern: it receives a dynamic
dict of StructureData nodes and launches one VaspWorkChain per structure.

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: intermediate
Usage:
    python examples/03_batch/dynamic_batch_example.py
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
BULK_INCAR = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 3,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

SLAB_INCAR = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 2,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}


# ---------------------------------------------------------------------------
# Stage pipeline
# ---------------------------------------------------------------------------
stages = [
    # Stage 1: relax the bulk SnO2 cell to get an accurate lattice
    {
        'name': 'bulk_relax',
        'type': 'vasp',
        'incar': BULK_INCAR,
        'restart': None,
        'kpoints_spacing': 0.03,
    },
    # Stage 2: enumerate all distinct SnO2(110) terminations from the relaxed bulk
    # The surface_terminations brick uses Pymatgen's SlabGenerator internally.
    {
        'name': 'slab_terms',
        'type': 'surface_terminations',
        'structure_from': 'bulk_relax',
        'miller_indices': [1, 1, 0],
        'min_slab_size': 12.0,
        'min_vacuum_size': 12.0,
        'lll_reduce': True,
        'center_slab': True,
        'primitive': True,
        'reorient_lattice': True,
    },
    # Stage 3: relax all terminations in parallel
    # dynamic_batch fans out: one VaspWorkChain per structure in slab_terms output.
    # max_concurrent_jobs limits simultaneous VASP jobs within this stage.
    {
        'name': 'slab_relax',
        'type': 'dynamic_batch',
        'structures_from': 'slab_terms',
        'base_incar': SLAB_INCAR,
        'kpoints_spacing': 0.05,
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
        name='example_sno2_dynamic_batch',
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
    print('slab_relax outputs a dynamic dict of relaxed structures and energies:')
    print('  from aiida.orm import load_node')
    print(f'  wg = load_node({pk})')
    print('  # one energy per termination label')
    print('  for label, e in wg.outputs.slab_relax_energies.items():')
    print('      print(label, float(e), "eV")')
