#!/usr/bin/env python
"""HSE06 hybrid band structure + DOS for SnO2 on bohr (fast test settings).

Three-stage workflow:
  1. GGA PBE pre-SCF (static, coarse settings for quick testing)
  2. HSE06 hybrid bands using VaspHybridBandsWorkChain
  3. HSE06 DOS using the DOS brick (vasp.v2.bands, only_dos)

The hybrid_bands brick wraps vasp.v2.hybrid_bands, which adds band path
segments as zero-weighted k-points to SCF calculations. This is necessary
for hybrid functionals where non-SCF band structure methods don't work.

Note: VaspHybridBandsWorkChain does NOT run a separate DOS calculation, so we
run a separate DOS stage to expose retrieved files (e.g. vasprun.xml, DOSCAR).

API functions: quick_vasp_sequential, print_sequential_results
Usage:
    python run_hybrid_dos_bands.py
"""

from ase.io import read
from aiida import orm, load_profile
from quantum_lego import quick_vasp_sequential, print_sequential_results

load_profile(profile='presto')

# --- Structure ---
atoms = read('structures/sno2.vasp')
structure = orm.StructureData(ase=atoms)

# --- Common INCAR (from vasp_builders_HYBRID_BANDS.py) ---
COMMON_INCAR = {
    'encut': 500,
    'ediff': 1e-5,
    'prec': 'Accurate',
    'ncore': 4,
    'ispin': 1,  # SnO2 is non-magnetic
    'lasph': True,
    'lreal': 'Auto',
}

# NOTE on k-point units:
# aiida-vasp converts `kpoints_spacing` to an AiiDA mesh density by multiplying by (2*pi).
# Typical values in this repo are ~0.03–0.05 (-> density ~0.19–0.31 1/Å).

# --- Stages ---
stages = [
    # Stage 1: GGA PBE pre-SCF (static, quick test)
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {
            **COMMON_INCAR,
            'algo': 'Fast',
            'ismear': 0,
            'sigma': 0.05,
            'nsw': 0,
            'ibrion': -1,
            'lwave': True,
            'lcharg': False,
        },
        'restart': None,
        'kpoints_spacing': 0.05,
    },
    # Stage 2: HSE06 hybrid band structure
    {
        'name': 'hse_bands',
        'type': 'hybrid_bands',
        'structure_from': 'input',  # Use original structure; relax is static (nsw=0)
        'scf_incar': {
            **COMMON_INCAR,
            'algo': 'Normal',
            'nelm': 120,
            'ismear': 0,
            'sigma': 0.01,
            'lorbit': 11,
            'lhfcalc': True,
            'hfscreen': 0.2,
            'gga': 'PE',
            'lwave': False,
            'lcharg': False,
        },
        'band_settings': {
            'band_mode': 'seekpath-aiida',
            'symprec': 1e-4,
            'band_kpoints_distance': 0.05,
            'kpoints_per_split': 90,
            'hybrid_reuse_wavecar': False,  # relax is external to this workchain
            'additional_band_analysis_parameters': {
                'with_time_reversal': True,
                'threshold': 1e-5,
            },
        },
        'kpoints_spacing': 0.05,
    },
    # Stage 3: HSE06 DOS
    # Note: aiida-vasp v5.x VaspHybridBandsWorkChain does not run DOS even if a
    # `dos` namespace is provided, so we run a separate DOS stage.
    {
        'name': 'hse_dos',
        'type': 'dos',
        'structure': structure,
        'scf_incar': {
            **COMMON_INCAR,
            'algo': 'Normal',
            'nelm': 120,
            'ismear': 0,
            'sigma': 0.01,
            'lorbit': 11,
            'lhfcalc': True,
            'hfscreen': 0.2,
            'gga': 'PE',
            # Needed for the DOS step restart (CHGCAR/WAVECAR)
            'lwave': True,
            'lcharg': True,
        },
        'dos_incar': {
            **COMMON_INCAR,
            'algo': 'Normal',
            'nelm': 100,
            'sigma': 0.01,
            'lhfcalc': True,
            'hfscreen': 0.2,
            'gga': 'PE',
            'ismear': 0,
            'lreal': False,
            'lorbit': 11,
            'nedos': 2000,
            'emin': -10.0,
            'emax': 10.0,
            'lwave': False,
            'lcharg': False,
        },
        'kpoints_spacing': 0.05,
        'dos_kpoints_spacing': 0.04,
    },
]

# --- Submit ---
if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=structure,
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',
        kpoints_spacing=0.05,
        potential_family='PBE',
        potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N sno2_hse_bands',
        },
        max_concurrent_jobs=4,
        name='sno2_hse_bands',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, analyze with:')
    print(f'  from quantum_lego import get_sequential_results, print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()

    # Save PK to file for tracking
    from pathlib import Path
    from datetime import datetime
    pk_file = Path(__file__).parent / 'hybrid_dos_bands_pks.txt'
    with open(pk_file, 'a') as f:
        timestamp = datetime.now().isoformat()
        f.write(f'{timestamp}  sno2_hse_bands  PK={pk}\n')
    print(f'PK saved to {pk_file}')
