# Canonical Structure Files

This directory contains the shared input structures used across the quantum-lego examples.
All files are VASP POSCAR/CONTCAR format (`.vasp`) unless noted otherwise.

Structures are loaded via the helpers in `examples/_shared/structures.py`:

```python
from examples._shared.structures import load_sno2, load_sno2_pnnm, load_nio, create_si_structure
```

---

## File Index

| File | System | Space group | Lattice (Å) | Atoms | Loader |
|------|--------|-------------|-------------|-------|--------|
| `sno2.vasp` | SnO₂ rutile (primitive cell) | P4₂/mnm (136) | a=b=4.765, c=3.207 | Sn₂O₄ | `load_sno2()` |
| `sno2_pnnm.vasp` | SnO₂ columbite (orthorhombic) | Pnnm (58) | a=3.241, b=4.788, c=4.867 | Sn₂O₄ | `load_sno2_pnnm()` |
| `nio.vasp` | NiO rock-salt | Fm-3m (225) | a=b=c=4.17 | Ni₄O₄ | `load_nio()` |

> **Si diamond structure** is generated programmatically (not a file):
> `create_si_structure()` builds a 2-atom diamond-cubic cell with a=5.43 Å using `ase.build.bulk`.

---

## Detailed Descriptions

### `sno2.vasp` — SnO₂ rutile, primitive cell

- **Description**: Tetragonal rutile-type tin dioxide. The most common SnO₂ polymorph (space group P4₂/mnm). Contains 2 Sn and 4 O atoms (one formula unit per primitive cell).
- **Lattice**: a=b=4.7648 Å, c=3.2075 Å, angles 90°/90°/90°.
- **Source**: DFT-PBE optimized geometry derived from the experimental rutile structure.
- **Used by**:
  - `01_getting_started/single_vasp.py`
  - `02_dos/single_dos.py`, `02_dos/batch_dos.py`
  - `03_batch/compare_structures.py`, `03_batch/dynamic_batch_example.py`
  - `04_sequential/mixed_dos_sources.py`, `04_sequential/relax_then_dos.py`
  - `05_convergence/encut_kpoints.py`
  - `06_surface/thickness_convergence.py`, `06_surface/surface_enumeration.py`,
    `06_surface/surface_gibbs_example.py`, `06_surface/formation_enthalpy_example.py`,
    `06_surface/o2_reference_example.py`,
    `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py`
  - `07_advanced_vasp/bader_analysis.py`, `07_advanced_vasp/birch_murnaghan_sno2.py`,
    `07_advanced_vasp/fukui_indices.py`, `07_advanced_vasp/hubbard_u_sno2.py`,
    `07_advanced_vasp/hybrid_bands_and_dos_sno2.py`, `07_advanced_vasp/neb_pipeline.py`,
    `07_advanced_vasp/sequential_relax_then_u.py`

### `sno2_pnnm.vasp` — SnO₂ columbite, orthorhombic

- **Description**: Orthorhombic columbite-type (α-PbO₂ structure) SnO₂ polymorph with Pnnm symmetry. Metastable high-pressure phase. Used alongside `sno2.vasp` to demonstrate multi-structure batch and DOS comparisons.
- **Lattice**: a=3.2409 Å, b=4.7880 Å, c=4.8666 Å, angles 90°/90°/90°.
- **Source**: DFT-PBE optimized geometry of the Pnnm polymorph.
- **Used by**:
  - `02_dos/batch_dos.py`
  - `03_batch/compare_structures.py`
  - `04_sequential/mixed_dos_sources.py`

### `nio.vasp` — NiO rock-salt, conventional cell

- **Description**: Cubic rock-salt nickel oxide. Canonical test system for DFT+U calculations (Hubbard U for Ni d-electrons). The cell contains 4 Ni and 4 O atoms.
- **Lattice**: a=b=c=4.17 Å, angles 90°/90°/90°. (Ferromagnetic/paramagnetic cell; AFM ordering is applied programmatically in the Hubbard U examples.)
- **Source**: Experimental lattice parameter a=4.177 Å (rock-salt NiO); used without relaxation as a starting point.
- **Used by**:
  - `07_advanced_vasp/hubbard_u_nio.py`
  - `07_advanced_vasp/hubbard_u_nio_afm_supercell.py`

---

## Other Structure Directories

Additional structure files live alongside the examples that use them:

### `11_neb/structures/`

| File | System | Description | Used by |
|------|--------|-------------|---------|
| `n_pt_step_initial.vasp` | N/Pt(211) | N adatom at fcc hollow below Pt step edge (initial NEB endpoint). Pt₂₄N₁, 25 atoms. | `11_neb/neb_pt_step_edge.py` |
| `n_pt_step_final.vasp` | N/Pt(211) | N adatom at hcp hollow above Pt step edge (final NEB endpoint). Pt₂₄N₁, 25 atoms. | `11_neb/neb_pt_step_edge.py` |

> **Generation**: Built from the classic ASE NEB Pt step-edge tutorial: FCC Pt
> (a=3.9 Å), (211) surface (2×1×3 layers), 10 Å vacuum, N placed at initial/final
> adsorption sites. See the structure-generation snippet in `neb_pt_step_edge.py`.

### `06_surface/binary_surface_thermo/structures/`

| File | System | Description | Used by |
|------|--------|-------------|---------|
| `H2.cif` | H₂ molecule | H₂ in a 15×15×15 Å cubic box (molecule-in-a-box, Γ-point). | `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` |
| `H2O.cif` | H₂O molecule | H₂O in a cubic box (molecule-in-a-box, Γ-point). | `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` |
| `Sn.cif` | Sn metal | Sn bulk reference (body-centered tetragonal, pymatgen-generated). | `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` |

> These files are used by the `o2_reference_energy` brick (H₂ + H₂O → O₂ reference)
> and the SnO₂ surface thermodynamics workflow.
