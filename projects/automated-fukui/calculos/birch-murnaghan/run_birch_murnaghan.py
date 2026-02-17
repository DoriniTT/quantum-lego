#!/usr/bin/env python
"""Birch-Murnaghan equation of state for SnO2 on localwork.

Generates 7 volume-scaled structures (-6% to +6%) and runs single-point
VASP calculations, then fits the Birch-Murnaghan EOS.

API functions: quick_vasp_sequential, print_sequential_results
Usage:
    python run_birch_murnaghan.py
"""

import numpy as np
from ase.io import read
from aiida import orm, load_profile
from quantum_lego import quick_vasp_sequential, print_sequential_results

load_profile(profile='presto')

# --- Structure ---
atoms = read('structures/sno2.vasp')
base_volume = atoms.get_volume()

# --- Volume scaling: 7 points from -6% to +6% strain ---
strains = np.linspace(-0.06, 0.06, 7)
volume_calcs = {}    # {label: calc_config} for batch stage
volume_map = {}      # {label: volume_A3} for BM stage

for strain in strains:
    # Label: v_m006, v_m004, v_m002, v_p000, v_p002, v_p004, v_p006
    sign = 'm' if strain < 0 else 'p'
    label = f'v_{sign}{abs(strain * 100):03.0f}'

    # Scale cell uniformly: cell * (1 + strain)^(1/3)
    scale_factor = (1.0 + strain) ** (1.0 / 3.0)
    scaled = atoms.copy()
    scaled.set_cell(atoms.cell * scale_factor, scale_atoms=True)

    scaled_structure = orm.StructureData(ase=scaled)
    scaled_volume = scaled.get_volume()

    volume_calcs[label] = {
        'structure': scaled_structure,
    }
    volume_map[label] = scaled_volume

# --- INCAR for static SCF ---
scf_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 0,
    'ibrion': -1,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': False,
}

# --- Stages ---
stages = [
    {
        'name': 'volume_scan',
        'type': 'batch',
        'structure_from': 'input',
        'base_incar': scf_incar,
        'kpoints_spacing': 0.03,
        'calculations': volume_calcs,
    },
    {
        'name': 'eos_fit',
        'type': 'birch_murnaghan',
        'batch_from': 'volume_scan',
        'volumes': volume_map,
    },
    {
        'name': 'eos_refine',
        'type': 'birch_murnaghan_refine',
        'eos_from': 'eos_fit',
        'structure_from': 'input',
        'base_incar': scf_incar,
        'kpoints_spacing': 0.03,
        'refine_strain_range': 0.02,   # +/-2% around V0
        'refine_n_points': 7,
    },
]

# --- Submit ---
if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=orm.StructureData(ase=atoms),
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',
        kpoints_spacing=0.03,
        potential_family='PBE',
        potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N sno2_birch_murnaghan',
        },
        max_concurrent_jobs=3,
        name='sno2_birch_murnaghan',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('Volume points:')
    for label in sorted(volume_map):
        print(f'  {label}: {volume_map[label]:.4f} A^3')
    print()

    # Save PK to file for tracking
    from pathlib import Path
    from datetime import datetime
    pk_file = Path(__file__).parent / 'birch_murnaghan_pks.txt'
    with open(pk_file, 'a') as f:
        timestamp = datetime.now().isoformat()
        f.write(f'{timestamp}  sno2_birch_murnaghan  PK={pk}\n')
    print(f'PK saved to {pk_file}')
