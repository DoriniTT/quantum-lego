#!/usr/bin/env python
"""Surface Gibbs free energy γ(ΔμO) for SnO2(110) terminations.

Demonstrates a focused surface thermodynamics pipeline that combines:
  - Bulk relaxation + slab relaxation (vasp bricks)
  - O2 reference energy (o2_reference_energy brick)
  - Formation enthalpy ΔHf (formation_enthalpy brick)
  - Surface Gibbs free energy γ(ΔμO) (surface_gibbs_energy brick)

The surface_gibbs_energy brick uses the ab initio atomistic thermodynamics
framework to compute γ as a function of the oxygen chemical potential ΔμO,
producing a Dict with surface energies for each slab termination.

Pipeline stages:
  1. bulk_relax   — relax bulk SnO2 (ISIF=3)
  2. sn_relax     — relax Sn reference metal (ISIF=3)
  3. o2_ref       — O2 reference energy via water splitting
  4. slab_terms   — generate all symmetrized SnO2(110) terminations (surface_terminations)
  5. slab_relax   — relax all terminations in parallel (dynamic_batch)
  6. dhf          — compute ΔHf(SnO2) (formation_enthalpy)
  7. surface_gibbs — compute γ(ΔμO) for each termination (surface_gibbs_energy)

API functions: quick_vasp_sequential
Difficulty: advanced
Usage:
    python examples/06_surface/surface_gibbs_example.py
"""

from pathlib import Path

from ase.io import read
from aiida import orm

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


_STRUCT_DIR = Path(__file__).resolve().parent / 'binary_surface_thermo' / 'structures'

ref_sn = orm.StructureData(ase=read(str(_STRUCT_DIR / 'Sn.cif')))
ref_h2 = orm.StructureData(ase=read(str(_STRUCT_DIR / 'H2.cif')))
ref_h2o = orm.StructureData(ase=read(str(_STRUCT_DIR / 'H2O.cif')))


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

SN_INCAR = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 3,
    'ismear': 1,
    'sigma': 0.2,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

H2_INCAR = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 60,
    'ibrion': 2,
    'isif': 2,
    'ismear': 0,
    'sigma': 0.05,
    'ispin': 1,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

H2O_INCAR = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 2,
    'ismear': 0,
    'sigma': 0.05,
    'ispin': 1,
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
    # Stage 1: relax bulk SnO2
    {
        'name': 'bulk_relax',
        'type': 'vasp',
        'incar': BULK_INCAR,
        'restart': None,
        'kpoints_spacing': 0.03,
    },
    # Stage 2: relax Sn reference metal
    {
        'name': 'sn_relax',
        'type': 'vasp',
        'structure': ref_sn,
        'incar': SN_INCAR,
        'restart': None,
        'kpoints_spacing': 0.03,
    },
    # Stage 3: O2 reference energy via water splitting
    {
        'name': 'o2_ref',
        'type': 'o2_reference_energy',
        'h2_structure': ref_h2,
        'h2o_structure': ref_h2o,
        'h2_incar': H2_INCAR,
        'h2o_incar': H2O_INCAR,
        'kpoints': [1, 1, 1],
    },
    # Stage 4: generate all symmetrized SnO2(110) slab terminations
    {
        'name': 'slab_terms',
        'type': 'surface_terminations',
        'structure_from': 'bulk_relax',
        'miller_indices': [1, 1, 0],
        'min_slab_size': 18.0,
        'min_vacuum_size': 15.0,
        'lll_reduce': True,
        'center_slab': True,
        'primitive': True,
        'reorient_lattice': True,
    },
    # Stage 5: relax all terminations in parallel
    {
        'name': 'slab_relax',
        'type': 'dynamic_batch',
        'structures_from': 'slab_terms',
        'base_incar': SLAB_INCAR,
        'kpoints_spacing': 0.05,
    },
    # Stage 6: bulk formation enthalpy ΔHf(SnO2)
    {
        'name': 'dhf',
        'type': 'formation_enthalpy',
        'structure_from': 'bulk_relax',
        'energy_from': 'bulk_relax',
        'references': {
            'Sn': 'sn_relax',
            'O': 'o2_ref',
        },
    },
    # Stage 7: surface Gibbs free energies γ(ΔμO) for each termination
    {
        'name': 'surface_gibbs',
        'type': 'surface_gibbs_energy',
        'bulk_structure_from': 'bulk_relax',
        'bulk_energy_from': 'bulk_relax',
        'slab_structures_from': 'slab_relax',
        'slab_energies_from': 'slab_relax',
        'formation_enthalpy_from': 'dhf',
        'sampling': 100,
    },
]


if __name__ == '__main__':
    setup_profile()

    potcar_mapping = dict(SNO2_POTCAR['mapping'])
    potcar_mapping['H'] = 'H'

    result = quick_vasp_sequential(
        structure=load_sno2(),
        stages=stages,
        code_label=DEFAULT_VASP_CODE,
        kpoints_spacing=0.03,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=potcar_mapping,
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=4,
        name='example_sno2_surface_gibbs',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, read the surface Gibbs free energies:')
    print('  from aiida.orm import load_node')
    print(f'  wg = load_node({pk})')
    print('  gamma = wg.outputs.surface_gibbs_surface_energies.get_dict()')
    print('  # gamma contains surface energies per termination in J/m2')
