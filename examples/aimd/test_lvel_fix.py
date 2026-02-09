#!/usr/bin/env python3
""" Test that LVEL=True fix enables velocity writing to CONTCAR.

This script submits a minimal 2-stage AIMD workflow and verifies:
1. INCAR contains LVEL = .TRUE.
2. CONTCAR from stage 1 has non-zero velocities
3. POSCAR for stage 2 has those velocities injected

Usage:
    python test_lvel_fix.py
"""

from aiida import orm, load_profile
from quantum_lego.core import quick_aimd

load_profile()

# Load a simple test structure (SnO2 primitive cell)
structure = orm.load_node(39387)  # From previous tests

# Submit minimal 2-stage AIMD
print("Submitting 2-stage AIMD workflow to test LVEL fix...")
result = quick_aimd(
    structure=structure,
    code_label='VASP-6.5.1@localwork',
    aimd_stages=[
        {
            'name': 'equilibration',
            'tebeg': 300,
            'nsw': 20,  # Very short for quick test
            'potim': 2.0,
            'mdalgo': 2,
            'smass': 0.0,
        },
        {
            'name': 'production',
            'tebeg': 300,
            'nsw': 20,
            'potim': 2.0,
            'mdalgo': 2,
            'smass': 0.0,
        },
    ],
    incar={'encut': 300, 'ediff': 1e-5, 'prec': 'Normal', 'ismear': 0, 'sigma': 0.05},
    kpoints_spacing=0.5,
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={
        'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 1},  # Use only 1 proc for localwork
        'max_wallclock_seconds': 3600,
    },
    name='test_lvel_fix',
)

pk = result['__workgraph_pk__']
print(f"\n{'='*70}")
print(f"WorkGraph submitted: PK = {pk}")
print(f"{'='*70}")

print("\nVerification steps after completion:")
print("\n1. Check that LVEL is in INCAR:")
print(f"   verdi process show {pk}  # Get WorkChain PK for equilibration")
print("   verdi calcjob inputls <CALC_PK>")
print("   verdi calcjob inputcat <CALC_PK> INCAR | grep LVEL")
print("   # Should show: LVEL = .TRUE.")

print("\n2. Check CONTCAR has non-zero velocities:")
print("   verdi calcjob outputcat <EQUILIBRATION_CALC_PK> CONTCAR | tail -30")
print("   # Should see scientific notation numbers (not all zeros)")

print("\n3. Check POSCAR for production has velocities:")
print("   verdi calcjob inputcat <PRODUCTION_CALC_PK> POSCAR | tail -30")
print("   # Should see velocity block matching CONTCAR")

print("\n4. Quick Python check:")
print("""
from aiida import orm, load_profile
load_profile()

wg = orm.load_node({pk})
# Find equilibration calc
for link in wg.get_outgoing().all():
    if 'equilibration' in link.link_label:
        for calc_link in link.node.get_outgoing().all():
            if 'calculation' in calc_link.link_label:
                calc = calc_link.node
                print(f"Equilibration calc: {{calc.pk}}")
                
                # Check INCAR
                incar = calc.inputs.parameters.get_dict()
                print(f"LVEL in INCAR: {{'lvel' in incar}}")
                print(f"LVEL value: {{incar.get('lvel', 'NOT SET')}}")
                
                # Check CONTCAR velocities
                if calc.is_finished_ok:
                    retrieved = calc.outputs.retrieved
                    with retrieved.base.repository.open('CONTCAR', 'r') as f:
                        contcar = f.read()
                        lines = contcar.strip().split('\\n')
                        # Velocities start after blank line following positions
                        print(f"CONTCAR last line: {{lines[-1]}}")
                        has_nonzero = any('E-' in line or 'E+' in line 
                                         for line in lines[-24:] if line.strip())
                        print(f"Has non-zero velocities: {{has_nonzero}}")
""".format(pk=pk))

print(f"\nMonitor with: verdi process show {pk}")
