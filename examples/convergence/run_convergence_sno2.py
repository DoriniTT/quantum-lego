"""
Convergence parameter test: SnO2 bulk (rutile).

Finds optimal ENCUT and k-points spacing using vasp.v2.converge.

Usage:
    source ~/envs/aiida/bin/activate
    verdi daemon restart
    python examples/lego/convergence/run_convergence_sno2.py
    verdi process show <PK>
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
        'name': 'conv_test',
        'type': 'convergence',
        'incar': {
            'prec': 'Accurate',
            'ismear': 0,
            'sigma': 0.05,
            'ediff': 1e-6,
            'ibrion': -1,
            'nsw': 0,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        },
        'conv_settings': {
            'cutoff_start': 300,
            'cutoff_stop': 500,
            'cutoff_step': 100,       # 3 points: 300, 400, 500
            'kspacing_start': 0.05,
            'kspacing_stop': 0.03,
            'kspacing_step': 0.01,    # 3 points: 0.05, 0.04, 0.03
            'cutoff_kconv': 400,
            'kspacing_cutconv': 0.04,
        },
        'convergence_threshold': 0.001,  # 1 meV/atom
    },
]

# ── Cluster config: obelix ─────────────────────────────────────────────
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
        'custom_scheduler_commands': '#PBS -l cput=90000:00:00\n'
                                     '#PBS -l nodes=1:ppn=88:skylake\n'
                                     '#PBS -j oe\n'
                                     '#PBS -N sno2_conv',
    },
    max_concurrent_jobs=4,
    name='sno2_convergence',
)

print(f"Submitted WorkGraph PK: {result['__workgraph_pk__']}")
print()
print("Monitor with:")
print(f"  verdi process show {result['__workgraph_pk__']}")
print(f"  verdi process report {result['__workgraph_pk__']}")
print()
print("Get results when done:")
print("  from quantum_lego import print_sequential_results")
print(f"  print_sequential_results({result})")
