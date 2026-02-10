"""
Hubbard U calculation for NiO - FIXED VERSION

CRITICAL FIX: Ground state now has LDAU=True with LDAUU=0.
Previously had LDAU=False which caused incompatible charge density
when restarting NSCF (ICHARG=11) calculations.

According to VASP Wiki (https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U):
- Ground state: DFT+U with U=0 (LDAU=.TRUE., LDAUU=0)
- Response: DFT+U with U=α (LDAU=.TRUE., LDAUU=α)

Four-stage sequential workflow:
  1. Ionic relaxation (IBRION=2, ISIF=3, spin-polarized)
  2. Ground state SCF (LORBIT=11, LWAVE=True, LCHARG=True, +U with U=0)
  3. Response calculations (NSCF + SCF per perturbation potential)
  4. Analysis (linear regression to extract U = 1/chi - 1/chi_0)

Usage:
    source ~/envs/aiida/bin/activate
    verdi daemon restart
    python examples/lego/hubbard_u/run_hubbard_u_nio_FIXED.py
    verdi process show <PK>
"""

from pathlib import Path

from aiida import load_profile, orm
from ase.io import read

load_profile()

# ── Load structure ──────────────────────────────────────────────────────
struct_path = Path(__file__).parent / 'nio.vasp'
structure = orm.StructureData(ase=read(str(struct_path)))

# ── Common INCAR parameters ────────────────────────────────────────────
base_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'algo': 'Normal',
    'nelm': 200,
    'ispin': 2,
    'magmom': [2.0] * 4 + [0.6] * 4,  # 4 Ni + 4 O
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
            'nsw': 100,
            'isif': 3,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'restart': None,
        'retrieve': ['CONTCAR', 'OUTCAR'],
    },
    # Stage 2: Ground state SCF with +U but U=0
    # CRITICAL FIX: Set ldau=True with ldauu=[0, 0]
    # This ensures charge density is compatible with ICHARG=11 response
    {
        'name': 'ground_state',
        'type': 'vasp',
        'structure_from': 'relax',
        'incar': {
            **base_incar,
            'nsw': 0,
            'ibrion': -1,
            'ldau': True,           # FIXED: was False
            'ldautype': 3,          # ADDED
            'ldaul': [2, -1],       # ADDED: d-orbitals for Ni, none for O
            'ldauj': [0.0, 0.0],    # ADDED
            'ldauu': [0.0, 0.0],    # ADDED: U=0 for ground state
            'lorbit': 11,
            'lwave': True,
            'lcharg': True,
        },
        'restart': None,
        'retrieve': ['OUTCAR'],
    },
    # Stage 3: Response calculations (NSCF + SCF per potential V)
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',
        'structure_from': 'relax',
        'target_species': 'Ni',
        'potential_values': [-0.2, -0.1, 0.1, 0.2],
        'ldaul': 2,  # d-electrons
        'incar': base_incar,
    },
    # Stage 4: Linear regression to extract U
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',
        'structure_from': 'relax',
        'target_species': 'Ni',
        'ldaul': 2,
    },
]

# ── Submit ──────────────────────────────────────────────────────────────
from quantum_lego import quick_vasp_sequential

result = quick_vasp_sequential(
    structure=structure,
    stages=stages,
    code_label='VASP-6.5.1-idefix-4@obelix',
    kpoints_spacing=0.04,
    potential_family='PBE',
    potential_mapping={'Ni': 'Ni_pv', 'O': 'O'},
    options={
        'resources': {
            'num_machines': 1,
            'num_mpiprocs_per_machine': 4,
        },
        'custom_scheduler_commands': (
            '#PBS -l cput=90000:00:00\n'
            '#PBS -l nodes=1:ppn=88:skylake\n'
            '#PBS -j oe\n'
            '#PBS -N nio_hubbard_u_fixed'
        ),
    },
    max_concurrent_jobs=2,
    name='nio_hubbard_u_fixed',
)

pk = result['__workgraph_pk__']
print(f"Submitted WorkGraph PK: {pk}")
print(f"Stages: {result['__stage_names__']}")
print()
print("FIXED: Ground state now has LDAU=True with LDAUU=[0,0]")
print("Expected: NSCF response (chi_0) > SCF response (chi)")
print()
print("Monitor with:")
print(f"  verdi process show {pk}")
print()
print("View results:")
print("  from quantum_lego import print_sequential_results, get_stage_results")
print(f"  print_sequential_results({pk})")
print(f"  u_result = get_stage_results({pk}, 'analysis')")
print("  print(f\"U = {u_result['summary']['hubbard_u_eV']:.3f} eV\")")
