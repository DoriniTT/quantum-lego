#!/usr/bin/env python
"""Create initial and final structures for NEB: N diffusion on a Pt step edge.

This reproduces the classic ASE example used for IDPP/NEB tutorials
(`doc/tutorials/neb/idpp4.py` in the ASE source tree):

* Build a Pt step-edge slab with FaceCenteredCubic + custom directions
* Add vacuum by extending the cell in z
* Place the N adatom at the same initial/final positions as the tutorial
* Pre-relax with EMT while keeping Pt atoms fixed (as in the tutorial)

Then we remove constraints and write VASP POSCAR files for subsequent DFT
relaxation.

Usage:
    python create_structures.py
"""

from pathlib import Path

import numpy as np
from ase import Atoms
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms
from ase.io import write
from ase.lattice.cubic import FaceCenteredCubic
from ase.optimize.fire import FIRE as QuasiNewton


def create_pt_step_slab():
    """Create a Pt(211) step-edge slab with vacuum."""
    # Some algebra to determine surface normal and the plane of the surface.
    d3 = [2, 1, 1]
    a1 = np.array([0, 1, 1])
    d1 = np.cross(a1, d3)
    a2 = np.array([0, -1, 1])
    d2 = np.cross(a2, d3)

    # Create the slab.
    slab = FaceCenteredCubic(
        symbol='Pt',
        directions=[d1, d2, d3],
        size=(2, 1, 2),
        latticeconstant=3.9,
    )

    # Add some vacuum to the slab (do not re-center; keep tutorial coordinates).
    uc = slab.get_cell()
    uc[2] += [0.0, 0.0, 10.0]
    slab.set_cell(uc, scale_atoms=False)

    return slab


def add_n_initial(slab):
    """Add N adatom at the fcc hollow below the step edge."""
    initial = slab.copy()

    # Positions from ASE tutorial example.
    x1 = 1.379
    x2 = 4.137
    y1 = 0.0
    z1 = 7.165

    initial += Atoms('N', positions=[((x2 + x1) / 2.0, y1, z1 + 1.5)])
    return initial


def add_n_final(slab):
    """Add N adatom at the hcp hollow above the step edge (shifted position)."""
    final = slab.copy()

    # Positions from ASE tutorial example.
    x3 = 2.759
    y2 = 2.238
    z2 = 6.439

    final += Atoms('N', positions=[(x3, y2 + 1.0, z2 + 3.5)])
    return final


def prerelax_with_emt(atoms, fmax=0.05, label=''):
    """Pre-relax structure with EMT while keeping Pt fixed (tutorial behaviour)."""
    relaxed = atoms.copy()

    mask = [atom.symbol == 'Pt' for atom in relaxed]
    relaxed.set_constraint(FixAtoms(mask=mask))

    relaxed.calc = EMT()
    opt = QuasiNewton(relaxed, logfile=None)
    opt.run(fmax=fmax)

    print(f'  {label}: EMT energy = {relaxed.get_potential_energy():.4f} eV '
          f'({opt.nsteps} steps)')

    # Remove constraints before writing (VASP will handle its own relaxation)
    relaxed.set_constraint()
    return relaxed


def main():
    output_dir = Path(__file__).parent / 'structures'
    output_dir.mkdir(exist_ok=True)

    print('Creating Pt(211) step-edge slab...')
    slab = create_pt_step_slab()
    print(f'  Slab: {len(slab)} atoms, cell = {slab.cell.lengths()}')

    print('Adding N adatom (initial position)...')
    initial = add_n_initial(slab)

    print('Adding N adatom (final position)...')
    final = add_n_final(slab)

    print('Pre-relaxing with EMT...')
    initial_relaxed = prerelax_with_emt(initial, label='Initial')
    final_relaxed = prerelax_with_emt(final, label='Final')

    # Write VASP POSCAR files
    initial_path = output_dir / 'n_pt_step_initial.vasp'
    final_path = output_dir / 'n_pt_step_final.vasp'

    # Keep atom ordering (Pt first, N last) consistent with the ASE tutorial.
    write(str(initial_path), initial_relaxed, format='vasp', vasp5=True, sort=False)
    write(str(final_path), final_relaxed, format='vasp', vasp5=True, sort=False)

    print(f'\nStructures written:')
    print(f'  Initial: {initial_path}  ({len(initial_relaxed)} atoms)')
    print(f'  Final:   {final_path}  ({len(final_relaxed)} atoms)')
    print(f'\nNext step: python run_neb.py')


if __name__ == '__main__':
    main()
