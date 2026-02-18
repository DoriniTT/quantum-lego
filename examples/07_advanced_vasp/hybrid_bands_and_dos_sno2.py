#!/usr/bin/env python
"""Hybrid-functional band structure + DOS (HSE06) for SnO2.

Stages:
  1) pbe_scf   : quick static PBE SCF (optional baseline)
  2) hse_bands : HSE06 band structure via `hybrid_bands` brick (vasp.v2.hybrid_bands)
  3) hse_dos   : HSE06 DOS via `dos` brick (vasp.v2.bands, only_dos)

Notes:
  - aiida-vasp 5.x `VaspHybridBandsWorkChain` does not run a separate DOS step,
    so hybrid DOS is done as a separate `dos` stage.
  - `hybrid_reuse_wavecar` must be False here: the Quantum Lego wrapper does
    not expose the internal `relax` namespace of the aiida-vasp workchain.

API functions: quick_vasp_sequential
Difficulty: advanced
Usage:
    python examples/07_advanced_vasp/hybrid_bands_and_dos_sno2.py
"""

from __future__ import annotations

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


COMMON_INCAR = {
    'encut': 500,
    'ediff': 1e-5,
    'prec': 'Accurate',
    'ncore': 4,
    'ispin': 1,
    'lasph': True,
    'lreal': 'Auto',
}

PBE_SCF_INCAR = {
    **COMMON_INCAR,
    'algo': 'Fast',
    'ismear': 0,
    'sigma': 0.05,
    'nsw': 0,
    'ibrion': -1,
    'lwave': True,
    'lcharg': False,
}

HSE_SCF_INCAR = {
    **COMMON_INCAR,
    'algo': 'Normal',
    'nelm': 120,
    'ismear': 0,
    'sigma': 0.01,
    'lorbit': 11,
    'lhfcalc': True,
    'gga': 'PE',
    'hfscreen': 0.2,
    'lwave': False,
    'lcharg': False,
}

HSE_DOS_SCF_INCAR = {
    **HSE_SCF_INCAR,
    # Needed for the DOS step restart (CHGCAR/WAVECAR)
    'lwave': True,
    'lcharg': True,
}

HSE_DOS_INCAR = {
    **COMMON_INCAR,
    'algo': 'Normal',
    'nelm': 100,
    'ismear': -5,
    'sigma': 0.01,
    'lreal': False,
    'lorbit': 11,
    'nedos': 2000,
    'emin': -10.0,
    'emax': 10.0,
    'lhfcalc': True,
    'gga': 'PE',
    'hfscreen': 0.2,
    'lwave': False,
    'lcharg': False,
}


if __name__ == '__main__':
    setup_profile()
    structure = load_sno2()

    stages = [
        {
            'name': 'pbe_scf',
            'type': 'vasp',
            'incar': PBE_SCF_INCAR,
            'restart': None,
            'kpoints_spacing': 0.05,
        },
        {
            'name': 'hse_bands',
            'type': 'hybrid_bands',
            'structure_from': 'input',
            'scf_incar': HSE_SCF_INCAR,
            'band_settings': {
                'band_mode': 'seekpath-aiida',
                'symprec': 1e-4,
                'band_kpoints_distance': 0.05,
                'kpoints_per_split': 90,
                'hybrid_reuse_wavecar': False,
                'additional_band_analysis_parameters': {
                    'with_time_reversal': True,
                    'threshold': 1e-5,
                },
            },
            'kpoints_spacing': 0.05,
        },
        {
            'name': 'hse_dos',
            'type': 'dos',
            'structure': structure,
            'scf_incar': HSE_DOS_SCF_INCAR,
            'dos_incar': HSE_DOS_INCAR,
            'kpoints_spacing': 0.05,
            'dos_kpoints_spacing': 0.04,
            'retrieve': ['DOSCAR'],
        },
    ]

    result = quick_vasp_sequential(
        structure=structure,
        stages=stages,
        code_label=DEFAULT_VASP_CODE,
        kpoints_spacing=0.05,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=1,
        name='example_sno2_hse_bands_dos',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print('Plot with: python examples/07_advanced_vasp/plot_workgraph_bands_and_dos.py <PK>')
