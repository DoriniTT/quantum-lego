#!/usr/bin/env python
"""Hubbard U for NiO using explicit stages with AFM 2x2x2 supercell.

Full-control approach using quick_vasp_sequential with explicit stages,
single-atom perturbation via prepare_perturbed_structure, and antiferromagnetic
ordering. This is the production-validated approach.

The workflow:
  1. Ground state SCF — no LDAU, saves WAVECAR+CHGCAR for restart
  2. Hubbard response — NSCF+SCF at each perturbation potential
  3. Hubbard analysis — linear regression to extract U

Structure preparation:
  - Start with a 2x2x2 AFM supercell (16 Ni + 16 O = 32 atoms)
  - prepare_perturbed_structure splits one Ni into kind 'Ni' (perturbed)
    and the remaining 15 into 'Ni1' (unperturbed), both using the same POTCAR

Validated result: U(Ni-d) = 5.08 eV, R^2 > 0.999 for both fits
VASP wiki reference: 5.58 eV (from linear fit on same system)

API functions: quick_vasp_sequential, prepare_perturbed_structure
Difficulty: advanced
Usage:
    python examples/07_advanced_vasp/hubbard_u_nio_afm_supercell.py
"""

from examples._shared.config import setup_profile
from examples._shared.structures import load_nio

from aiida import orm
from quantum_lego import quick_vasp_sequential
from quantum_lego.core.common.u_calculation.utils import prepare_perturbed_structure


# ---------------------------------------------------------------------------
# 1. Structure: split one Ni for single-atom perturbation
# ---------------------------------------------------------------------------
# load_nio() returns NiO (small cell). For production, use a 2x2x2 supercell.
# The structure should already be a supercell before calling this script.
# Here we use load_nio() as a demonstration; for real runs, load your own
# pre-built AFM supercell (16 Ni + 16 O = 32 atoms).

def prepare_nio_structure():
    """Load NiO and split species for single-atom perturbation."""
    structure = load_nio()
    split_structure, perturbed_kind, unperturbed_kind = prepare_perturbed_structure(
        structure, target_species='Ni'
    )
    return split_structure


# ---------------------------------------------------------------------------
# 2. POTCAR mapping (both Ni kinds use the same pseudopotential)
# ---------------------------------------------------------------------------
potential_family = 'PBE'
potential_mapping = {
    'Ni': 'Ni',      # perturbed Ni atom
    'Ni1': 'Ni',     # unperturbed Ni atoms (same POTCAR)
    'O': 'O',
}

# ---------------------------------------------------------------------------
# 3. Base INCAR (shared across stages)
# ---------------------------------------------------------------------------
# AFM ordering: alternating up/down moments on Ni sublattice
# After prepare_perturbed_structure: [Ni(1), Ni1(N-1), O(N)]
# Adjust magmom list to match YOUR structure's atom count.
ni_magmom = [1.0, -1.0] * 2   # 4 Ni atoms (for the example 8-atom cell)
o_magmom = [0.0] * 4           # 4 O atoms
magmom = ni_magmom + o_magmom

base_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.2,
    'prec': 'Accurate',
    'lreal': 'Auto',       # for supercell
    'lmaxmix': 4,          # for d-electrons
    'ispin': 2,             # spin-polarized
    'magmom': magmom,       # AFM ordering
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
            'lorbit': 11,       # orbital projections (required for occupation extraction)
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
        'target_species': 'Ni',
        'potential_values': [-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20],
        'ldaul': 2,             # d-electrons
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
    setup_profile()

    split_structure = prepare_nio_structure()

    result = quick_vasp_sequential(
        structure=split_structure,
        stages=stages,
        code_label='VASP-6.5.1-idefix-4@obelix',
        kpoints_spacing=0.03,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
            'custom_scheduler_commands': (
                '#PBS -l cput=90000:00:00\n'
                '#PBS -l nodes=1:ppn=88:skylake\n'
                '#PBS -j oe\n'
                '#PBS -N nio_hubbard_u'
            ),
        },
        max_concurrent_jobs=4,
        name='nio_hubbard_u',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Stages: {result["__stage_names__"]}')
    print(f'Monitor with: verdi process show {pk}')
    print()
    print('After completion, check results with:')
    print('  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()
    print('Expected: U(Ni-d) ~ 5.1 eV, R^2 > 0.99')
