#!/usr/bin/env python
"""Example: QE calculations using the lego module.

This script demonstrates:
1. Single QE calculation with quick_qe()
2. Sequential QE pipeline with quick_qe_sequential()

Prerequisites:
- AiiDA profile configured with QE code (e.g., 'pw@localhost')
- PseudoPotential family installed (e.g., aiida-pseudo install sssp)
- Structure to calculate (we create a simple Si structure here)

Usage:
    verdi daemon restart
    python run_qe_si.py
    verdi process show <PK>
"""

from aiida import orm, load_profile
from ase.build import bulk

# Import shared structure utilities
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from common_structures import create_si_structure

load_profile()


def run_single_qe_calc():
    """Run a single QE calculation using quick_qe()."""
    from quantum_lego import quick_qe, get_status

    structure = create_si_structure()

    # Submit single QE SCF calculation
    pk = quick_qe(
        structure=structure,
        code_label='pw@localhost',  # Adjust to your QE code label
        parameters={
            'CONTROL': {
                'calculation': 'scf',
                'pseudo_dir': './',  # Usually not needed if using aiida-pseudo
            },
            'SYSTEM': {
                'ecutwfc': 30,  # Low for testing
                'ecutrho': 240,
            },
            'ELECTRONS': {
                'conv_thr': 1e-6,
            },
        },
        kpoints_spacing=0.15,  # Coarse for testing
        pseudo_family='SSSP/1.3/PBE/efficiency',  # Adjust to your pseudo family
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
        },
        name='si_scf_test',
    )

    print(f"Submitted QE SCF calculation: PK = {pk}")
    print(f"Status: {get_status(pk)}")
    print(f"Monitor with: verdi process show {pk}")
    return pk


def run_sequential_qe_pipeline():
    """Run a sequential QE pipeline: relax -> scf -> dos."""
    from quantum_lego import quick_qe_sequential, get_status

    structure = create_si_structure()

    stages = [
        {
            'name': 'relax',
            'type': 'qe',
            'parameters': {
                'CONTROL': {'calculation': 'relax'},
                'SYSTEM': {
                    'ecutwfc': 30,
                    'ecutrho': 240,
                },
                'ELECTRONS': {'conv_thr': 1e-6},
                'IONS': {},
            },
            'restart': None,
            'kpoints_spacing': 0.15,  # Coarse for testing
        },
        {
            'name': 'scf_fine',
            'type': 'qe',
            'parameters': {
                'CONTROL': {'calculation': 'scf'},
                'SYSTEM': {
                    'ecutwfc': 40,  # Higher cutoff
                    'ecutrho': 320,
                },
                'ELECTRONS': {'conv_thr': 1e-8},
            },
            'restart': 'relax',
            'kpoints_spacing': 0.10,  # Finer k-points
        },
    ]

    result = quick_qe_sequential(
        structure=structure,
        stages=stages,
        code_label='pw@localhost',  # Adjust to your QE code label
        kpoints_spacing=0.15,
        pseudo_family='SSSP/1.3/PBE/efficiency',  # Adjust to your pseudo family
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,
            },
        },
        name='si_qe_pipeline',
    )

    pk = result['__workgraph_pk__']
    print(f"Submitted QE sequential pipeline: PK = {pk}")
    print(f"Stages: {result['__stage_names__']}")
    print(f"Status: {get_status(pk)}")
    print(f"Monitor with: verdi process show {pk}")
    return result


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'sequential':
        run_sequential_qe_pipeline()
    else:
        run_single_qe_calc()
        print("\nTip: Run with 'sequential' argument for the pipeline example:")
        print("  python run_qe_si.py sequential")
