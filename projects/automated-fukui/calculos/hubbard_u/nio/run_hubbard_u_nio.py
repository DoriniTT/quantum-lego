#!/usr/bin/env python
"""Hubbard U calculation for NiO using linear response method.

Uses the antiferromagnetic 2x2x2 supercell from the VASP wiki
(16 Ni + 16 O = 32 atoms) with single-atom perturbation: one Ni atom
is split into a separate kind ('Ni') while the remaining 15 are labeled
'Ni1'. This ensures the perturbation potential is applied to exactly one
atom, as required by the VASP wiki linear response protocol.

Target cluster: bohr par40 (40 cores, 1 node)
Expected result: Ni-d U ~ 5.3-6.4 eV (VASP wiki: 5.58 eV from linear fit)

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
structure_path = Path(__file__).resolve().parent.parent / 'structures' / 'nio.vasp'
pmg_struct = Structure.from_file(str(structure_path))
# Structure is already a 2x2x2 AFM supercell (16 Ni + 16 O), no supercell needed

# Store as AiiDA StructureData, then split species for single-atom perturbation
supercell = orm.StructureData(pymatgen=pmg_struct)
split_structure, perturbed_kind, unperturbed_kind = prepare_perturbed_structure(
    supercell, target_species='Ni'
)

# ---------------------------------------------------------------------------
# 2. POTCAR mapping (duplicate Ni for both Ni kinds)
# ---------------------------------------------------------------------------
potential_family = 'PBE'
potential_mapping = {
    'Ni': 'Ni',     # perturbed Ni (10 valence electrons)
    'Ni1': 'Ni',    # unperturbed Ni (same pseudopotential)
    'O': 'O',
}

# ---------------------------------------------------------------------------
# 3. Base INCAR (shared across stages)
# ---------------------------------------------------------------------------
# AFM ordering: alternating up/down moments on Ni sublattice
# After prepare_perturbed_structure: [Ni(1), Ni1(15), O(16)]
# Moments: 1.0 -1.0 1.0 -1.0 ... (16 Ni) + 0.0*16 (O)
ni_magmom = [1.0, -1.0] * 8   # 16 Ni atoms, alternating AFM
o_magmom = [0.0] * 16          # 16 O atoms, non-magnetic
magmom = ni_magmom + o_magmom  # 32 atoms total

base_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.2,
    'prec': 'Accurate',
    'lreal': 'Auto',      # for supercell
    'lmaxmix': 4,         # for d-electrons
    'ispin': 2,            # spin-polarized
    'magmom': magmom,      # AFM ordering
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
            # No LDAU in ground state — matches VASP wiki protocol.
            # LDAU is only introduced in the response calculations.
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
        'target_species': 'Ni',  # kind name = perturbed atom only
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
        'target_species': 'Ni',
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
            'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N nio_hubbard_u',
        },
        max_concurrent_jobs=4,
        name='nio_hubbard_u',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('Expected results:')
    print('  - Ni-d U ~ 5.3-6.4 eV (VASP wiki: 5.58 eV from linear fit)')
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
        f.write(f'{timestamp}  nio_hubbard_u  PK={pk}\n')
    print(f'PK saved to {pk_file}')
