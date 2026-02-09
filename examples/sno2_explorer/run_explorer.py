#!/usr/bin/env python
"""
Explorer Example: Compare two structures with static SCF calculations.

Place structure_1.vasp and structure_2.vasp in this folder before running.

Usage:
    python run_two_structures.py
"""

from pathlib import Path
from aiida import orm, load_profile
from ase.io import read
from quantum_lego.core import quick_vasp_batch

# =============================================================================
# Configuration
# =============================================================================

CODE_LABEL = 'VASP-6.5.1@localwork'
POTENTIAL_FAMILY = 'PBE'
POTENTIAL_MAPPING = {
    'Sn': 'Sn_d',
    'O': 'O',
}

INCAR = {
    'prec': 'Normal',
    'encut': 400,
    'ediff': 1e-5,
    'ismear': 0,
    'sigma': 0.05,
    'nsw': 0,
    'ibrion': -1,
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

OPTIONS = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 8,
    },
}

# =============================================================================
# Main
# =============================================================================

load_profile('presto')

# Load structures
script_dir = Path(__file__).parent
structures = {
    'structure_1': orm.StructureData(ase=read(script_dir / 'sno2.vasp')),
}

# Submit calculations
result = quick_vasp_batch(
    structures=structures,
    code_label=CODE_LABEL,
    incar=INCAR,
    kpoints_spacing=0.04,
    potential_family=POTENTIAL_FAMILY,
    potential_mapping=POTENTIAL_MAPPING,
    options=OPTIONS,
    retrieve=['OUTCAR'],
    max_concurrent_jobs=1,
    name='explorer_sno2',
)

pk = result['__workgraph_pk__']
print(f"Submitted WorkGraph PK: {pk}")
print(f"Monitor with: verdi process show {pk}")
