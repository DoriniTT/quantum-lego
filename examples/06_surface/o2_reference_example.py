#!/usr/bin/env python
"""O2 reference energy via the water-splitting reaction (o2_reference_energy brick).

The direct DFT energy of the O2 molecule is well-known to be inaccurate with
semi-local functionals (PBE over-binds by ~1 eV/O2).  This example uses the
thermochemically corrected water-splitting approach instead:

    E_ref(O2)  =  2 E_DFT(H2O) - 2 E_DFT(H2) + 5.52 eV

where 5.52 eV captures the experimental Gibbs free energy of water formation
plus zero-point and thermal corrections at 298.15 K, 1 bar.

Pipeline stages:
  1. o2_ref — relax H2 and H2O molecules (molecule-in-a-box, Γ-only),
              then compute E_ref(O2) (o2_reference_energy brick)

The brick outputs:
  - o2_ref_energy    (orm.Float)  — E_ref(O2) in eV per O2 molecule
  - o2_ref_details   (orm.Dict)   — intermediate energies and constants used

API functions: quick_vasp_sequential
Difficulty: beginner
Usage:
    python examples/06_surface/o2_reference_example.py
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

ref_h2 = orm.StructureData(ase=read(str(_STRUCT_DIR / 'H2.cif')))
ref_h2o = orm.StructureData(ase=read(str(_STRUCT_DIR / 'H2O.cif')))


# ---------------------------------------------------------------------------
# Molecule INCAR presets (gamma-only, no spin polarisation for these closed-shell refs)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Stage pipeline
# ---------------------------------------------------------------------------
stages = [
    {
        'name': 'o2_ref',
        'type': 'o2_reference_energy',
        'h2_structure': ref_h2,
        'h2o_structure': ref_h2o,
        'h2_incar': H2_INCAR,
        'h2o_incar': H2O_INCAR,
        'kpoints': [1, 1, 1],
    },
]


if __name__ == '__main__':
    setup_profile()

    potcar_mapping = dict(SNO2_POTCAR['mapping'])
    potcar_mapping['H'] = 'H'

    result = quick_vasp_sequential(
        structure=load_sno2(),   # primary structure (unused by o2_reference_energy)
        stages=stages,
        code_label=DEFAULT_VASP_CODE,
        kpoints_spacing=0.03,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=potcar_mapping,
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=2,
        name='example_o2_reference_energy',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, read the O2 reference energy:')
    print('  from aiida.orm import load_node')
    print(f'  wg = load_node({pk})')
    print('  e_o2 = float(wg.outputs.o2_ref_energy)')
    print('  details = wg.outputs.o2_ref_details.get_dict()')
    print('  print(f"E_ref(O2) = {e_o2:.4f} eV")')
