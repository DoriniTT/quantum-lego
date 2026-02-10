"""
Hubbard U calculation for SnO2 (rutile) using the Lego module.

Four-stage sequential workflow:
  1. Ionic relaxation (IBRION=2, ISIF=3)
  2. Ground state SCF (LORBIT=11, LWAVE=True, LCHARG=True, +U with U=0)
  3. Response calculations (NSCF + SCF per perturbation potential)
  4. Analysis (linear regression to extract U = 1/chi - 1/chi_0)

Note:
    SnO2 is not a typical system where Hubbard U is applied (Sn d-electrons
    are deep core states in a closed-shell configuration). This serves as a
    lightweight demonstration and integration test. For physically meaningful
    Hubbard U calculations, use transition metal oxides like NiO, Fe2O3,
    MnO, or CoO.

Usage:
    source ~/envs/aiida/bin/activate
    verdi daemon restart
    python examples/lego/hubbard_u/run_hubbard_u_sno2.py
    verdi process show <PK>

Viewing results:
    from quantum_lego import print_sequential_results, get_stage_results
    print_sequential_results(<PK>)

    # Access U value directly
    u_result = get_stage_results(<PK>, 'analysis')
    print(f"U = {u_result['hubbard_u_eV']:.3f} eV")
"""

from pathlib import Path

from aiida import load_profile, orm
from ase.io import read

load_profile()

# ── Load structure ──────────────────────────────────────────────────────
struct_path = Path(__file__).parent / 'sno2.vasp'
structure = orm.StructureData(ase=read(str(struct_path)))

# ── Common INCAR parameters ────────────────────────────────────────────
# SnO2 is non-magnetic, so ISPIN=1 (default).
# LMAXMIX=4 is required when d-electrons are involved in +U calculations.
# Light parameters for fast local testing.
base_incar = {
    'encut': 400,
    'ediff': 1e-5,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'algo': 'Normal',
    'nelm': 100,
    'lmaxmix': 4,
}

# ── Define stages ───────────────────────────────────────────────────────
stages = [
    # Stage 1: Full relaxation (ions + cell)
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {
            **base_incar,
            'ibrion': 2,
            'nsw': 50,
            'isif': 3,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'restart': None,
        'kpoints_spacing': 0.05,
        'retrieve': ['CONTCAR', 'OUTCAR'],
    },
    # Stage 2: Ground state SCF (produces WAVECAR, CHGCAR, OUTCAR)
    # Prerequisites for hubbard_response:
    #   - lorbit=11  (site-projected DOS for d-occupation extraction)
    #   - lwave=True (WAVECAR for NSCF restart)
    #   - lcharg=True (CHGCAR for NSCF restart)
    #   - ldau=True with ldauu=[0,0]  (CRITICAL: needed for ICHARG=11 compatibility)
    #   - retrieve=['OUTCAR'] (d-occupation parsing)
    {
        'name': 'ground_state',
        'type': 'vasp',
        'structure_from': 'relax',
        'incar': {
            **base_incar,
            'nsw': 0,
            'ibrion': -1,
            'ldau': True,           # FIXED: was False (incompatible with ICHARG=11)
            'ldautype': 3,          # ADDED: required for +U
            'ldaul': [2, -1],       # ADDED: d-orbitals for Sn, none for O
            'ldauj': [0.0, 0.0],    # ADDED: J=0
            'ldauu': [0.0, 0.0],    # ADDED: U=0 for ground state
            'lorbit': 11,
            'lwave': True,
            'lcharg': True,
        },
        'restart': None,
        'kpoints_spacing': 0.05,
        'retrieve': ['OUTCAR'],
    },
    # Stage 3: Response calculations (NSCF + SCF per potential V)
    # For each V in potential_values, runs:
    #   - NSCF (ICHARG=11, LDAUTYPE=3): bare response chi_0
    #   - SCF (LDAUTYPE=3): screened response chi
    # Total: 8 VASP calculations (4 potentials x 2 types)
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',
        'structure_from': 'relax',
        'target_species': 'Sn',
        'potential_values': [-0.2, -0.1, 0.1, 0.2],
        'ldaul': 2,  # d-electrons
        'incar': base_incar,
        'kpoints_spacing': 0.05,
    },
    # Stage 4: Linear regression to extract U
    # No VASP calculations — pure data analysis.
    # Computes: U = 1/chi - 1/chi_0 from linear fits of
    # occupation vs. perturbation potential.
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',
        'structure_from': 'relax',
        'target_species': 'Sn',
        'ldaul': 2,
    },
]

# ── Submit ──────────────────────────────────────────────────────────────
from quantum_lego import quick_vasp_sequential

result = quick_vasp_sequential(
    structure=structure,
    stages=stages,
    code_label='VASP-6.5.1-idefix-4@obelix',
    kpoints_spacing=0.05,
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={
        'resources': {
            'num_machines': 1,
            'num_mpiprocs_per_machine': 4,
        },
        'custom_scheduler_commands': (
            '#PBS -l cput=90000:00:00\n'
            '#PBS -l nodes=1:ppn=88:skylake\n'
            '#PBS -j oe\n'
            '#PBS -N sno2_hubbard_u'
        ),
    },
    name='sno2_hubbard_u',
)

pk = result['__workgraph_pk__']
print(f"Submitted WorkGraph PK: {pk}")
print(f"Stages: {result['__stage_names__']}")
print(f"Stage types: {result['__stage_types__']}")
print()
print("Monitor with:")
print(f"  verdi process show {pk}")
print(f"  verdi process report {pk}")
print()
print("View results when finished:")
print("  from quantum_lego import print_sequential_results, get_stage_results")
print(f"  print_sequential_results({pk})")
print()
print("  # Extract U value directly")
print(f"  u_result = get_stage_results({pk}, 'analysis')")
print("  print(f\"U = {u_result['hubbard_u_eV']:.3f} eV\")")
print("  print(f\"SCF fit R²: {u_result['chi_r2']:.6f}\")")
print("  print(f\"NSCF fit R²: {u_result['chi_0_r2']:.6f}\")")
