#!/usr/bin/env python
"""Practical test: Submit small AIMD workflow and verify velocities in POSCAR.

This script:
1. Creates a simple SnO2 structure
2. Submits a quick_aimd workflow with 2 sequential stages
3. Waits for completion
4. Verifies velocities appear in the production stage's POSCAR

Run with: python examples/lego/aimd/test_velocity_injection.py
"""

from aiida import orm, load_profile
load_profile()

from pymatgen.core import Structure, Lattice
from quantum_lego.core import quick_aimd


def parse_poscar_velocities(poscar_content: str):
    """Parse velocity block from POSCAR content.
    
    Returns:
        Tuple of (n_atoms, has_velocities, num_velocity_lines)
    """
    lines = poscar_content.strip().split('\n')
    
    # Find coordinate type line (Direct or Cartesian)
    coord_idx = -1
    for i, line in enumerate(lines):
        if 'direct' in line.lower() or 'cartesian' in line.lower():
            coord_idx = i
            break
    
    if coord_idx < 0:
        return None, False, 0
    
    # Parse species and counts
    elem_line_idx = -1
    for i in range(coord_idx - 1, -1, -1):
        if any(c.isalpha() for c in lines[i][:20]):
            elem_line_idx = i
            break
    
    # Extract counts
    count_line = lines[elem_line_idx + 1] if elem_line_idx >= 0 else None
    if count_line:
        try:
            counts = [int(x) for x in count_line.split()]
            n_atoms = sum(counts)
        except (ValueError, IndexError):
            return None, False, 0
    else:
        return None, False, 0
    
    # Extract positions start and check for velocity block
    pos_start = coord_idx + 1
    pos_end = pos_start + n_atoms
    
    # Count velocity lines
    velocity_lines = 0
    if pos_end < len(lines):
        for i in range(n_atoms):
            if pos_end + i >= len(lines):
                break
            line = lines[pos_end + i].strip()
            if not line or any(c.isalpha() for c in line[:10]):
                break
            try:
                parts = [float(x) for x in line.split()[:3]]
                velocity_lines += 1
            except (ValueError, IndexError):
                break
    
    has_velocities = velocity_lines == n_atoms
    return n_atoms, has_velocities, velocity_lines


def main():
    print("\n" + "="*70)
    print("AIMD Velocity Injection Test")
    print("="*70)
    
    # Create simple SnO2 structure
    print("\n1. Creating SnO2 structure...")
    lattice = Lattice.tetragonal(4.737, 3.186)
    sno2 = Structure(
        lattice,
        ['Sn', 'Sn', 'O', 'O', 'O', 'O'],
        [
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5],
            [0.3056, 0.3056, 0.0],
            [0.6944, 0.6944, 0.0],
            [0.1944, 0.8056, 0.5],
            [0.8056, 0.1944, 0.5],
        ],
    )
    structure = orm.StructureData(pymatgen=sno2)
    print(f"   ✓ Created structure with {len(structure.sites)} atoms")
    
    # Submit quick_aimd workflow
    print("\n2. Submitting quick_aimd workflow with 2 sequential AIMD stages...")
    print("   Stage 1: equilibration (1 split = 20 steps)")
    print("   Stage 2: production (1 split = 10 steps, restart from stage 1)")
    
    result = quick_aimd(
        structure=structure,
        code_label='VASP-6.5.1@localwork',
        aimd_stages=[
            {
                'name': 'equilibration',
                'tebeg': 300,
                'nsw': 20,
                'splits': 1,
                'potim': 2.0,
                'mdalgo': 2,
                'smass': 0.0,
            },
            {
                'name': 'production',
                'tebeg': 300,
                'nsw': 10,
                'splits': 1,
                'potim': 1.5,
                'mdalgo': 2,
                'smass': 0.0,
            },
        ],
        incar={'encut': 300, 'ediff': 1e-4, 'ismear': 0, 'sigma': 0.05},
        supercell=[2, 2, 1],
        kpoints_spacing=0.5,
        potential_family='PBE',
        potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
        options={
            'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8},
        },
        name='test_velocity_injection',
        wait=False,  # Don't wait, we'll check manually
    )
    
    wg_pk = result['__workgraph_pk__']
    print(f"   ✓ WorkGraph submitted with PK: {wg_pk}")
    
    # Instructions for manual verification
    print("\n3. Workflow Status & Verification")
    print(f"   Check workflow status: verdi process show {wg_pk}")
    print(f"   Check detailed report: verdi process report {wg_pk}")
    
    print("\n4. Velocity Injection Verification Steps:")
    print("   Once both stages complete:")
    print("")
    print("   a) Check equilibration stage outputs:")
    print("      verdi process show {wg_pk}")
    print("      Look for: s01_equilibration_md_equilibration_0 and s02_equilibration_md_equilibration_1")
    print("      Both should have '.vasp.velocities' output")
    print("")
    print("   b) Check production stage POSCAR for velocities:")
    print("      Find the production stage's AimdVaspCalculation PK")
    print("      Run: verdi calcjob show <production_calc_pk>")
    print("           verdi calcjob inputcat <production_calc_pk> POSCAR | head -50")
    print("      Expected: POSCAR should have velocity block after positions (24 velocity lines)")
    print("")
    print("   c) Run this script again to parse the POSCAR:")
    print("      python examples/lego/aimd/test_velocity_injection.py --check-pk <production_calc_pk>")
    print("")
    
    # Option to check a specific calculation
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == '--check-pk':
        check_pk = int(sys.argv[2])
        print(f"\n5. Checking AimdVaspCalculation PK {check_pk}")
        
        try:
            from aiida.orm import load_node
            calc_node = load_node(check_pk)
            
            # Try to retrieve the POSCAR from the calculation
            if hasattr(calc_node, 'retrieved') and calc_node.retrieved:
                try:
                    poscar_content = calc_node.retrieved.listdir()[0]
                    # Try to get POSCAR
                    import subprocess
                    result = subprocess.run(
                        f"verdi calcjob inputcat {check_pk} POSCAR",
                        shell=True, capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        poscar_text = result.stdout
                        n_atoms, has_vel, n_vel_lines = parse_poscar_velocities(poscar_text)
                        
                        print(f"\n   POSCAR Analysis:")
                        print(f"   - Total atoms: {n_atoms}")
                        print(f"   - Velocity block present: {has_vel}")
                        print(f"   - Velocity lines: {n_vel_lines}")
                        
                        if has_vel:
                            print(f"\n   ✓✓✓ SUCCESS ✓✓✓")
                            print(f"   Velocities were correctly injected into the POSCAR!")
                        else:
                            print(f"\n   ✗✗✗ FAILED ✗✗✗")
                            print(f"   POSCAR does not contain velocity block.")
                except Exception as e:
                    print(f"   Error retrieving POSCAR: {e}")
        except Exception as e:
            print(f"   Error loading calculation: {e}")
    
    print("\n" + "="*70 + "\n")


if __name__ == '__main__':
    main()
