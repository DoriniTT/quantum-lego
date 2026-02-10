#!/usr/bin/env python
"""
Single WorkGraph DOS workflow with mixed structure sources.

Stages in one `quick_vasp_sequential()` call:
1. Relax input structure (`sno2.vasp`)
2. DOS from relaxed structure (`structure_from='relax'`)
3. DOS from an explicit external structure (`structure=sno2_pnnm.vasp`)

`max_concurrent_jobs` applies globally to all runnable tasks in the WorkGraph.
"""

from pathlib import Path

from aiida import orm, load_profile
from ase.io import read

from quantum_lego import quick_vasp_sequential


CODE_LABEL = 'VASP-6.5.1@localwork'
POTENTIAL_FAMILY = 'PBE'
POTENTIAL_MAPPING = {'Sn': 'Sn_d', 'O': 'O'}

OPTIONS = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 8,
    },
}

RELAX_INCAR = {
    'nsw': 60,
    'ibrion': 2,
    'isif': 2,
    'ediff': 1e-5,
    'encut': 400,
    'prec': 'Normal',
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
}

DOS_SCF_INCAR = {
    'encut': 400,
    'ediff': 1e-6,
    'prec': 'Normal',
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
}

DOS_INCAR = {
    'encut': 400,
    'prec': 'Normal',
    'nedos': 2000,
    'lorbit': 11,
    'ismear': -5,
}


def load_structures() -> tuple[orm.StructureData, orm.StructureData]:
    """Load the initial and external DOS structures from local VASP files."""
    script_dir = Path(__file__).parent
    initial_structure = orm.StructureData(ase=read(script_dir / 'sno2.vasp'))
    external_structure = orm.StructureData(ase=read(script_dir / 'sno2_pnnm.vasp'))
    return initial_structure, external_structure


def build_stages(external_structure: orm.StructureData) -> list[dict]:
    """Create stage list for the mixed-source DOS workflow."""
    return [
        {
            'name': 'relax',
            'type': 'vasp',
            'incar': RELAX_INCAR,
            'restart': None,
            'kpoints_spacing': 0.06,
            'retrieve': ['CONTCAR', 'OUTCAR'],
        },
        {
            'name': 'dos_relaxed',
            'type': 'dos',
            'structure_from': 'relax',
            'scf_incar': DOS_SCF_INCAR,
            'dos_incar': DOS_INCAR,
            'kpoints_spacing': 0.06,
            'dos_kpoints_spacing': 0.04,
            'retrieve': ['DOSCAR'],
        },
        {
            'name': 'dos_external',
            'type': 'dos',
            'structure': external_structure,
            'scf_incar': DOS_SCF_INCAR,
            'dos_incar': DOS_INCAR,
            'kpoints_spacing': 0.06,
            'dos_kpoints_spacing': 0.04,
            'retrieve': ['DOSCAR'],
        },
    ]


if __name__ == '__main__':
    load_profile('presto')

    initial_structure, external_structure = load_structures()
    stages = build_stages(external_structure)

    result = quick_vasp_sequential(
        structure=initial_structure,
        stages=stages,
        code_label=CODE_LABEL,
        potential_family=POTENTIAL_FAMILY,
        potential_mapping=POTENTIAL_MAPPING,
        options=OPTIONS,
        name='sno2_mixed_dos_sources',
        max_concurrent_jobs=2,
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
