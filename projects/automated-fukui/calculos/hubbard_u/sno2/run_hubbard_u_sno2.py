#!/usr/bin/env python
"""Hubbard U calculation for SnO2 using linear response method.

Uses a 2x2x2 supercell (16 Sn + 32 O = 48 atoms) with single-atom
perturbation: one Sn atom is split into a separate kind ('Sn') while
the remaining 15 are labeled 'Sn1'. This ensures the perturbation
potential is applied to exactly one atom, as required by the VASP wiki
linear response protocol.

Target cluster: bohr par40 (40 cores, 1 node)
Expected result: Sn-d U ~ 3-4 eV (literature)

Reference: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
"""

from pathlib import Path

from pymatgen.core import Structure
from aiida import orm, load_profile
from quantum_lego import quick_vasp_sequential
from quantum_lego.core.common.u_calculation.utils import prepare_perturbed_structure

load_profile(profile='presto')

# ---------------------------------------------------------------------------
# 1. Load and prepare structure
# ---------------------------------------------------------------------------
structure_path = Path(__file__).parent / 'structures' / 'sno2.vasp'
pmg_struct = Structure.from_file(str(structure_path))
pmg_struct.make_supercell([2, 2, 2])  # 2x2x2 supercell: 16 Sn + 32 O
# pymatgen keeps atoms sorted by species (all Sn first, then all O)

# Store as AiiDA StructureData, then split species for single-atom perturbation
supercell = orm.StructureData(pymatgen=pmg_struct)
split_structure, perturbed_kind, unperturbed_kind = prepare_perturbed_structure(
    supercell, target_species='Sn'
)

# ---------------------------------------------------------------------------
# 2. POTCAR mapping (duplicate Sn_d for both Sn kinds)
# ---------------------------------------------------------------------------
potential_family = 'PBE'
potential_mapping = {
    'Sn': 'Sn_d',    # perturbed Sn (14 valence electrons)
    'Sn1': 'Sn_d',   # unperturbed Sn (same pseudopotential)
    'O': 'O',
}

# ---------------------------------------------------------------------------
# 3. Base INCAR (shared across stages)
# ---------------------------------------------------------------------------
base_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',  # for supercell
    'lmaxmix': 4,     # for d-electrons
}

# ---------------------------------------------------------------------------
# 4. Stages
# ---------------------------------------------------------------------------
stages = [
    # Stage 1: Ground state — no perturbation, save WAVECAR+CHGCAR
    {
        'name': 'ground_state',
        'type': 'vasp',
        'incar': {
            **base_incar,
            'nsw': 0,
            'ibrion': -1,
            # LDAU with zero potential for charge density compatibility
            # with subsequent response calculations. Array length = 3
            # matching split species: [Sn, Sn1, O]
            'ldau': True,
            'ldautype': 3,
            'ldaul': [2, -1, -1],     # d on perturbed Sn only
            'ldauu': [0.0, 0.0, 0.0],  # zero potential
            'ldauj': [0.0, 0.0, 0.0],
            'lorbit': 11,  # orbital projections (required!)
            'lwave': True,
            'lcharg': True,
        },
        'restart': None,
        'kpoints_spacing': 0.03,
        'retrieve': ['OUTCAR'],
    },
    # Stage 2: Response — NSCF + SCF at each perturbation potential
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',
        'structure_from': 'input',
        'target_species': 'Sn',  # kind name = perturbed atom only
        'potential_values': [-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20],
        'ldaul': 2,  # d-electrons
        'incar': base_incar,
        'kpoints_spacing': 0.03,
    },
    # Stage 3: Analysis — linear regression to get U
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',
        'structure_from': 'input',
        'target_species': 'Sn',
        'ldaul': 2,
    },
]

# ---------------------------------------------------------------------------
# 5. Submit
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=split_structure,
        stages=stages,
        code_label='VASP-VTST-6.4.3@bohr',
        kpoints_spacing=0.03,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options={
            'resources': {
                'num_machines': 1,
                'num_cores_per_machine': 40,
            },
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N sno2_hubbard_u',
        },
        name='sno2_hubbard_u',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('Expected results:')
    print('  - Sn-d U ~ 3-4 eV')
    print('  - R² > 0.98 for both chi and chi_0 fits')
    print()
    print('After completion, analyze with:')
    print(f'  from quantum_lego import get_sequential_results, print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()

    # Save PK to file for tracking
    from datetime import datetime
    pk_file = Path(__file__).parent / 'hubbard_u_pks.txt'
    with open(pk_file, 'a') as f:
        timestamp = datetime.now().isoformat()
        f.write(f'{timestamp}  sno2_hubbard_u  PK={pk}\n')
    print(f'PK saved to {pk_file}')
