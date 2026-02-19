# 13 Full Characterisation

End-to-end SnO2 characterisation pipeline combining all six major workflow
phases in a single WorkGraph submission.

## Overview

`sno2_full_characterisation.py` demonstrates how every quantum-lego brick type
can be wired together into a single automated pipeline.  The example is a
production-ready script intended for cluster use (obelix, 88-core nodes).

## Six Phases

| Phase | Stages | Purpose |
|-------|--------|---------|
| 1 | `initial_relax → volume_scan → eos_fit → eos_refine → bulk_relax` | Ground-state structure and energy via Birch-Murnaghan EOS |
| 2 | `hub_ground_state → hub_response → hub_analysis` | Hubbard U(Sn-d) by linear-response method on a 2×2×2 supercell |
| 3 | `hse_prerelax → hse_bands → hse_dos` | HSE06 hybrid band structure + density of states |
| 4 | `enumerate_surfaces` | Symmetrically distinct low-index surface orientations |
| 5 | `sn_relax + o2_ref + dhf + slab_terms_{hkl} + slab_relax_{hkl} + surface_gibbs_{hkl}` | Surface Gibbs free energies γ(ΔμSn, ΔμO) per orientation |
| 6 | `select_stable_{hkl} + fukui_batch_{hkl} + fukui_plus_{hkl} + fukui_minus_{hkl}` | Fukui f±(r) on the most stable termination |

Phases 1 and 2 run fully in parallel from T=0.  Phases 5–6 are vectorised
over all distinct Miller indices automatically.

## Bricks Used

| Brick type | Phase | Description |
|-----------|-------|-------------|
| `vasp` | 1, 2, 3, 5 | Standard VASP relaxation and SCF |
| `batch` | 1 | Parallel BM volume-scan SCFs |
| `birch_murnaghan` | 1 | Third-order BM EOS fit |
| `birch_murnaghan_refine` | 1 | Refined EOS scan around V0 |
| `hubbard_response` | 2 | Linear-response perturbation calculations |
| `hubbard_analysis` | 2 | Linear regression → U (eV), R² |
| `hybrid_bands` | 3 | HSE06 band structure (VaspHybridBandsWorkChain) |
| `dos` | 3 | HSE06 density of states (VaspBandsWorkChain) |
| `surface_enumeration` | 4 | Enumerate distinct Miller indices |
| `o2_reference_energy` | 5 | O2 reference via water-splitting thermochemistry |
| `formation_enthalpy` | 5 | ΔHf(SnO2) from bulk + reference energies |
| `surface_terminations` | 5 | Generate all slab terminations for one hkl |
| `dynamic_batch` | 5 | Relax all terminations in parallel |
| `surface_gibbs_energy` | 5 | γ(ΔμSn, ΔμO) for each termination |
| `select_stable_surface` | 6 | Pick minimum-φ termination at ΔμM=ΔμO=0 |
| `fukui_dynamic` | 6 | 8 fractional-charge SCFs for f±(r) |
| `fukui_analysis` | 6 | CHGCAR interpolation → f+(r) or f-(r) |

## Structure Files Required

All structures are loaded from `examples/structures/`:

| File | Used in |
|------|---------|
| `sno2.vasp` | All phases (primitive SnO2 cell) |
| `Sn.cif` | Phase 5 (Sn metal reference) |
| `H2.cif` | Phase 5 (O2 reference via water splitting) |
| `H2O.cif` | Phase 5 (O2 reference via water splitting) |

## Cluster Configuration

The script targets **obelix** by default.  To switch clusters:

```python
# Bohr (par40 queue)
CODE_LABEL = 'VASP-VTST-6.4.3@bohr'
OBELIX_OPTIONS = {
    'resources': {'num_machines': 1, 'num_cores_per_machine': 40},
    'custom_scheduler_commands': '#PBS -q par40\n#PBS -j oe\n#PBS -N sno2_full',
}

# Lovelace (par128 queue)
CODE_LABEL = 'VASP-6.5.0@lovelace'
OBELIX_OPTIONS = {
    'resources': {'num_machines': 1, 'num_cores_per_machine': 128},
    'custom_scheduler_commands': '#PBS -q par128\n#PBS -j oe\n#PBS -N sno2_full',
}
```

## Run

```bash
python examples/13_full_characterisation/sno2_full_characterisation.py
```

## Monitor

```bash
verdi process show <PK>
verdi process report <PK>
```

## Inspect Results

```python
from quantum_lego import print_sequential_results
print_sequential_results(<PK>)
```

Key outputs per phase:

| Phase | Stage | Output |
|-------|-------|--------|
| 1 | `bulk_relax` | Equilibrium structure (`StructureData`) + energy (eV) |
| 2 | `hub_analysis` | `{'U_eV': float, 'r_squared': float}` |
| 3 | `hse_bands` | Band-structure node (seekpath k-path) |
| 3 | `hse_dos` | TDOS + PDOS (`DosData`) |
| 4 | `enumerate_surfaces` | List of distinct Miller index tuples |
| 5 | `surface_gibbs_{hkl}` | `{'surface_energies': {label: {'phi': float, ...}}}` |
| 6 | `fukui_plus_{hkl}` | `CHGCAR_FUKUI.vasp` — f⁺(r) charge density |
| 6 | `fukui_minus_{hkl}` | `CHGCAR_FUKUI.vasp` — f⁻(r) charge density |

## Notes

- `max_concurrent_jobs=4` limits simultaneous VASP jobs across the entire
  WorkGraph.  Raise this if your cluster allows more concurrency.
- `serialize_stages=False` enables WorkGraph's automatic parallel scheduling.
- The Fukui CHGCAR files can be visualised with VESTA by downloading the
  `SinglefileData` node from AiiDA and converting to a standard CHGCAR format.
- The `select_stable_surface` brick calls `struct.clone()` internally so the
  selected slab becomes a new provenance node, which is required by AiiDA's
  one-CREATE-link constraint.
