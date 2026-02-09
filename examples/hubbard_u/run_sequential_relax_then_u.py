"""
Sequential workflow: Relax SnO2 bulk, then calculate Hubbard U.

Four-stage sequential workflow:
  1. Ionic relaxation (IBRION=2, NSW=50)
  2. Ground state SCF (LORBIT=11, LWAVE=True, LCHARG=True)
  3. Response calculations (NSCF + SCF per potential value)
  4. Analysis (linear regression to extract U)

This demonstrates the hubbard_response and hubbard_analysis bricks used
as stages in quick_vasp_sequential, chained after relaxation and ground
state stages.

Usage:
    source ~/envs/aiida/bin/activate
    verdi daemon restart
    python examples/lego/hubbard_u/run_sequential_relax_then_u.py
    verdi process show <PK>

Note:
    SnO2 is used here for demonstration. For realistic Hubbard U
    calculations, use transition metal oxides (NiO, Fe2O3, MnO, etc.).
"""

from pathlib import Path

from aiida import load_profile, orm
from ase.io import read

load_profile()

# ── Load structure ──────────────────────────────────────────────────────
struct_path = Path(__file__).parent / 'sno2.vasp'
structure = orm.StructureData(ase=read(str(struct_path)))

# ── Define stages ───────────────────────────────────────────────────────
base_incar = {
    'encut': 400,
    'ediff': 1e-5,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'algo': 'Normal',
    'nelm': 100,
}

stages = [
    # Stage 1: Relax the structure
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
    # Stage 2: Ground state SCF (+U with U=0)
    # CRITICAL: LDAU=True with LDAUU=0 is required for ICHARG=11 compatibility
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
            'ldaul': [2, -1],       # ADDED: d for Sn, none for O
            'ldauj': [0.0, 0.0],    # ADDED
            'ldauu': [0.0, 0.0],    # ADDED: U=0 for ground state
            'lmaxmix': 4,
            'lorbit': 11,
            'lwave': True,
            'lcharg': True,
        },
        'restart': None,
        'kpoints_spacing': 0.05,
        'retrieve': ['OUTCAR'],
    },
    # Stage 3: Response calculations (NSCF + SCF per potential)
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',
        'structure_from': 'relax',
        'target_species': 'Sn',
        'incar': base_incar,
        'potential_values': [-0.2, -0.1, 0.1, 0.2],
        'ldaul': 2,
        'kpoints_spacing': 0.05,
    },
    # Stage 4: Linear regression and summary
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',
        'structure_from': 'relax',
        'target_species': 'Sn',
        'ldaul': 2,
    },
]

# ── Submit sequential workflow ──────────────────────────────────────────
from quantum_lego.core import quick_vasp_sequential, print_sequential_results

result = quick_vasp_sequential(
    structure=structure,
    stages=stages,
    code_label='VASP-6.5.1@localwork',
    kpoints_spacing=0.05,
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={
        'resources': {
            'num_machines': 1,
            'num_mpiprocs_per_machine': 8,
        },
    },
    name='sno2_relax_then_hubbard_u',
)

pk = result['__workgraph_pk__']
print(f"Submitted WorkGraph PK: {pk}")
print(f"Stages: {result['__stage_names__']}")
print()
print("Monitor with:")
print(f"  verdi process show {pk}")
print(f"  verdi process report {pk}")
print()
print("Get results when done:")
print("  from quantum_lego.core import print_sequential_results, get_stage_results")
print(f"  print_sequential_results({result})")
print(f"  u_result = get_stage_results({result}, 'analysis')")
print("  print(f\"U = {u_result['hubbard_u_eV']:.3f} eV\")")
