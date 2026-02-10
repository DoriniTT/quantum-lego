#!/usr/bin/env python
"""Batch DOS calculation example using quick_dos_batch.

This script demonstrates how to run DOS calculations on multiple
structures in parallel using the explorer module.

Usage:
    1. Place structure files (structure_1.vasp, structure_2.vasp, ...) in this directory
    2. Edit the configuration below for your system
    3. Run: python run_batch_dos.py
    4. Monitor: verdi process show <PK>
    5. Get results: python -c "from quantum_lego import print_batch_dos_results; print_batch_dos_results(<result>)"
"""

from pathlib import Path
from aiida import orm, load_profile
from ase.io import read
from quantum_lego import quick_dos_batch, get_batch_dos_results

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
KPOINTS_SPACING = 0.05  # Coarse for testing
DOS_KPOINTS_SPACING = 0.04  # Slightly denser for DOS

# Maximum concurrent jobs (localwork typically runs ONE job at a time)
MAX_CONCURRENT_JOBS = 1

# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    # Load AiiDA profile
    load_profile('presto')

    # Load multiple structures from .vasp files in this directory
    structure_dir = Path(__file__).parent
    structures = {}

    for vasp_file in sorted(structure_dir.glob('*.vasp')):
        key = vasp_file.stem  # e.g., 'structure_1', 'structure_2'
        structures[key] = orm.StructureData(ase=read(vasp_file))
        print(f"Loaded: {key} ({structures[key].get_formula()})")

    if not structures:
        print("No .vasp files found in this directory")
        print("Please create structure files (e.g., structure_1.vasp, structure_2.vasp)")
        exit(1)

    if len(structures) < 2:
        print(f"Only found {len(structures)} structure(s). Batch DOS is most useful with 2+ structures.")
        print("Proceeding anyway...")

    # Submit batch DOS calculation
    result = quick_dos_batch(
        structures=structures,
        code_label=CODE_LABEL,
        scf_incar=SCF_INCAR,
        dos_incar=DOS_INCAR,
        kpoints_spacing=KPOINTS_SPACING,
        dos_kpoints_spacing=DOS_KPOINTS_SPACING,
        potential_family=POTENTIAL_FAMILY,
        potential_mapping=POTENTIAL_MAPPING,
        options=OPTIONS,
        max_concurrent_jobs=MAX_CONCURRENT_JOBS,
        retrieve=['DOSCAR'],
        name=f'batch_dos_{len(structures)}_structures',
    )

    print(f"\nSubmitted batch DOS calculation")
    print(f"WorkGraph PK: {result['__workgraph_pk__']}")
    print(f"Structures: {list(structures.keys())}")
    print(f"\nMonitor with: verdi process show {result['__workgraph_pk__']}")
    print(f"             verdi process report {result['__workgraph_pk__']}")
    print(f"\nTo get results when done:")
    print(f"  from quantum_lego import get_batch_dos_results, print_batch_dos_results")
    print(f"  result = {result}")
    print(f"  print_batch_dos_results(result)")
    print(f"\n  # Or extract results programmatically:")
    print(f"  batch_results = get_batch_dos_results(result)")
    print(f"  for key, r in batch_results.items():")
    print(f"      print(f\"{{key}}: E = {{r['energy']:.6f}} eV\")")
