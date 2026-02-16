#!/usr/bin/env python
"""Surface enumeration for SnO2 — find symmetrically distinct Miller indices.

Pure-Python analysis brick (no VASP). Uses pymatgen SpacegroupAnalyzer to
identify the crystal symmetry of bulk SnO2 (tetragonal rutile, P4_2/mnm #136)
and determine all unique surface orientations up to max_index for Wulff
construction planning.

Expected results for SnO2 (tetragonal, 4/mmm, max_index=1):
  - 5 distinct surfaces: (001), (100), (101), (110), (111)

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: beginner
Usage:
    python examples/06_surface/surface_enumeration.py
"""

from examples._shared.config import SNO2_POTCAR, LOCALWORK_OPTIONS, setup_profile
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


stages = [
    {
        'name': 'enumerate_surfaces',
        'type': 'surface_enumeration',
        'structure_from': 'input',
        'max_index': 1,
        'symprec': 0.01,
    },
]


if __name__ == '__main__':
    setup_profile()

    result = quick_vasp_sequential(
        structure=load_sno2(),
        stages=stages,
        code_label='VASP-6.5.1@localwork',
        kpoints_spacing=0.03,
        potential_family=SNO2_POTCAR['family'],
        potential_mapping=SNO2_POTCAR['mapping'],
        options=LOCALWORK_OPTIONS,
        name='example_sno2_surface_enumeration',
    )

    pk = result['__workgraph_pk__']
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Monitor with: verdi process show {pk}')
    print(f'Detailed report: verdi process report {pk}')
