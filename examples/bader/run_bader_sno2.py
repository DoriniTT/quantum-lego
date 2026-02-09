"""
Bader charge analysis example: SnO2 bulk (rutile).

Two-stage workflow:
  1. SCF with LAECHG=True to produce AECCAR0, AECCAR2, CHGCAR
  2. Bader charge analysis using the bader binary

Usage:
    source ~/envs/aiida/bin/activate
    verdi daemon restart
    python examples/explorer/bader/run_bader_sno2.py
    verdi process show <PK>

Requirements:
    - bader binary installed at ~/.local/bin/bader
    - pymatgen (for AECCAR summation)
"""

from pathlib import Path

from aiida import load_profile, orm
from pymatgen.core import Structure

load_profile()

# ── Load structure ──────────────────────────────────────────────────────
struct_path = Path(__file__).parent / 'sno2.vasp'
pmg_struct = Structure.from_file(str(struct_path))
structure = orm.StructureData(pymatgen=pmg_struct)

# ── Define stages ───────────────────────────────────────────────────────
stages = [
    {
        'name': 'scf',
        'type': 'vasp',
        'incar': {
            'encut': 520,
            'ediff': 1e-6,
            'ismear': 0,
            'sigma': 0.05,
            'ibrion': -1,
            'nsw': 0,
            'prec': 'Accurate',
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': True,
            'laechg': True,  # Required for Bader analysis
        },
        'restart': None,
        'kpoints_spacing': 0.03,
        'retrieve': ['AECCAR0', 'AECCAR2', 'CHGCAR', 'OUTCAR'],
    },
    {
        'name': 'bader',
        'type': 'bader',
        'charge_from': 'scf',
    },
]

# ── Cluster config: bohr, par40 queue ───────────────────────────────────
from quantum_lego.core import quick_vasp_sequential

result = quick_vasp_sequential(
    structure=structure,
    stages=stages,
    code_label='VASP-6.4.3@bohr',
    kpoints_spacing=0.03,
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={
        'resources': {
            'num_machines': 1,
            'num_cores_per_machine': 40,
        },
        'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N sno2_bader',
    },
    name='sno2_bader',
)

print(f"Submitted WorkGraph PK: {result['__workgraph_pk__']}")
print(f"Stages: {result['__stage_names__']}")
print()
print("Monitor with:")
print(f"  verdi process show {result['__workgraph_pk__']}")
print(f"  verdi process report {result['__workgraph_pk__']}")
print()
print("Get results when done:")
print("  from quantum_lego.core import print_sequential_results")
print(f"  print_sequential_results({result})")
