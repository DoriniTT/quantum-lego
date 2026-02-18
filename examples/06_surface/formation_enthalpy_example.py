#!/usr/bin/env python
"""Bulk formation enthalpy of SnO2 using the formation_enthalpy brick.

Demonstrates a focused 3-stage pipeline:
  1. bulk_relax  — relax SnO2 (vasp, ISIF=3)
  2. sn_relax    — relax Sn reference metal (vasp, ISIF=3)
  3. o2_ref      — O2 reference energy via water splitting (o2_reference_energy)
  4. dhf         — compute ΔHf(SnO2) per formula unit (formation_enthalpy)

The formation enthalpy is stored as an AiiDA Dict on the WorkGraph output:
  dhf_formation_enthalpy (orm.Dict) with keys:
    - delta_h_formation_eV_per_fu  (eV per SnO2 formula unit)
    - delta_h_formation_eV_per_atom

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: intermediate
Usage:
    python examples/06_surface/formation_enthalpy_example.py
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


_STRUCT_DIR = Path(__file__).resolve().parent.parent / 'structures'

# Sn reference metal (or provide your own POSCAR/CONTCAR)
_sn_atoms = read(str(Path(__file__).resolve().parent / 'binary_surface_thermo' / 'structures' / 'Sn.cif'))
ref_sn = orm.StructureData(ase=_sn_atoms)

_h2_atoms = read(str(Path(__file__).resolve().parent / 'binary_surface_thermo' / 'structures' / 'H2.cif'))
ref_h2 = orm.StructureData(ase=_h2_atoms)

_h2o_atoms = read(str(Path(__file__).resolve().parent / 'binary_surface_thermo' / 'structures' / 'H2O.cif'))
ref_h2o = orm.StructureData(ase=_h2o_atoms)


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


# ---------------------------------------------------------------------------
# Stage pipeline
# ---------------------------------------------------------------------------
stages = [
    # Stage 1: relax bulk SnO2 (target compound)
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
    # Stage 3: O2 reference energy via water-splitting reaction
    # E_ref(O2) = 2 E(H2O) - 2 E(H2) + 5.52 eV  (298.15 K, 1 bar)
    {
        'name': 'o2_ref',
        'type': 'o2_reference_energy',
        'h2_structure': ref_h2,
        'h2o_structure': ref_h2o,
        'h2_incar': H2_INCAR,
        'h2o_incar': H2O_INCAR,
        'kpoints': [1, 1, 1],
    },
    # Stage 4: compute ΔHf(SnO2)
    # references maps element symbol -> name of stage that provides its energy
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
        max_concurrent_jobs=2,
        name='example_sno2_formation_enthalpy',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, read ΔHf from the WorkGraph output:')
    print('  from aiida.orm import load_node')
    print(f'  wg = load_node({pk})')
    print('  dhf = wg.outputs.dhf_formation_enthalpy.get_dict()')
    print('  print(dhf["delta_h_formation_eV_per_fu"], "eV/f.u.")')
