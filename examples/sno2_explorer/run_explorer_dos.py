#!/usr/bin/env python
"""DOS calculation example using quick_dos.

This script demonstrates how to run a DOS calculation using the
explorer module's quick_dos function.

Usage:
    1. Place a structure file (e.g., structure_1.vasp) in this directory
    2. Edit the configuration below for your system
    3. Run: python run_dos.py
    4. Monitor: verdi process show <PK>
    5. Get results: python -c "from quantum_lego.core import print_dos_results; print_dos_results(<PK>)"
"""

from pathlib import Path
from aiida import orm, load_profile
from ase.io import read
from quantum_lego.core import quick_dos

# ============================================================================
# Configuration - Edit these for your system
# ============================================================================

# VASP code label
CODE_LABEL = 'VASP-6.5.1@localwork'

# POTCAR settings
POTENTIAL_FAMILY = 'PBE'
POTENTIAL_MAPPING = {'Sn': 'Sn_d', 'O': 'O'}  # Edit for your elements

# SCF INCAR parameters - lwave and lcharg are handled by BandsWorkChain
# Note: AiiDA-VASP requires lowercase INCAR keys
SCF_INCAR = {
    'prec': 'Accurate',
    'encut': 400,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
    'nelm': 120,
    'lorbit': 11,
}

# DOS INCAR parameters - BandsWorkChain handles ICHARG internally
DOS_INCAR = {
    'nedos': 2000,
    'lorbit': 11,
    'ismear': -5,  # Tetrahedron method for DOS
    'prec': 'Accurate',
    'algo': 'Normal',
}

# Scheduler options
OPTIONS = {
    'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8},
}

# K-points spacing
KPOINTS_SPACING = 0.05      # For SCF
DOS_KPOINTS_SPACING = 0.04  # For DOS (denser)

# Structure file
STRUCTURE_FILE = Path(__file__).parent / 'sno2.vasp'

# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    # Load AiiDA profile
    load_profile('presto')

    # Load structure
    structure = orm.StructureData(ase=read(STRUCTURE_FILE))

    # Submit DOS calculation
    pk = quick_dos(
        structure=structure,
        code_label=CODE_LABEL,
        scf_incar=SCF_INCAR,
        dos_incar=DOS_INCAR,
        kpoints_spacing=KPOINTS_SPACING,
        dos_kpoints_spacing=DOS_KPOINTS_SPACING,
        potential_family=POTENTIAL_FAMILY,
        potential_mapping=POTENTIAL_MAPPING,
        options=OPTIONS,
        retrieve=['DOSCAR'],  # Retrieve DOSCAR file
        name=f'dos_{structure.get_formula()}',
    )

    print(f"\nSubmitted DOS calculation: PK {pk}")
    print(f"Monitor with: verdi process show {pk}")
    print(f"Get results: python -c \"from quantum_lego.core import print_dos_results; print_dos_results({pk})\"")
