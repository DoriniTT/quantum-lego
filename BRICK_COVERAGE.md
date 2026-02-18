# Brick Coverage

This file shows which example scripts demonstrate each brick type available in the
`BRICK_REGISTRY`.  It is intended to help developers verify that each brick has
at least one working example, and to guide users toward the right starting point.

## Summary

| Brick | Has example? | Example files |
|-------|:------------:|---------------|
| `vasp` | ✅ | multiple (see below) |
| `dos` | ✅ | `02_dos/`, `04_sequential/`, `07_advanced_vasp/hybrid_bands_and_dos_sno2.py` |
| `batch` | ✅ | `03_batch/compare_structures.py`, `07_advanced_vasp/birch_murnaghan_sno2.py` |
| `birch_murnaghan` | ✅ | `07_advanced_vasp/birch_murnaghan_sno2.py` |
| `birch_murnaghan_refine` | ✅ | `07_advanced_vasp/birch_murnaghan_sno2.py` |
| `bader` | ✅ | `07_advanced_vasp/bader_analysis.py` |
| `convergence` | ✅ | `05_convergence/encut_kpoints.py` |
| `thickness` | ✅ | `06_surface/thickness_convergence.py` |
| `hubbard_response` | ✅ | `07_advanced_vasp/hubbard_u_*.py` |
| `hubbard_analysis` | ✅ | `07_advanced_vasp/hubbard_u_*.py` |
| `aimd` | ✅ | `08_aimd/aimd_workflow.py` |
| `qe` | ✅ | `09_other_codes/qe_single_and_pipeline.py` |
| `cp2k` | ✅ | `09_other_codes/cp2k_pipeline.py` |
| `generate_neb_images` | ✅ | `07_advanced_vasp/neb_pipeline.py`, `11_neb/neb_pt_step_edge.py` |
| `neb` | ✅ | `07_advanced_vasp/neb_pipeline.py`, `11_neb/neb_pt_step_edge.py` |
| `dimer` | ✅ | `12_dimer/dimer_ammonia.py` |
| `hybrid_bands` | ✅ | `07_advanced_vasp/hybrid_bands_and_dos_sno2.py` |
| `fukui_analysis` | ✅ | `07_advanced_vasp/fukui_indices.py` |
| `fukui_dynamic` | ✅ | `07_advanced_vasp/fukui_indices.py` |
| `surface_enumeration` | ✅ | `06_surface/surface_enumeration.py` |
| `surface_terminations` | ✅ | `03_batch/dynamic_batch_example.py`, `06_surface/surface_gibbs_example.py` |
| `dynamic_batch` | ✅ | `03_batch/dynamic_batch_example.py`, `06_surface/surface_gibbs_example.py` |
| `formation_enthalpy` | ✅ | `06_surface/formation_enthalpy_example.py` |
| `o2_reference_energy` | ✅ | `06_surface/o2_reference_example.py` |
| `surface_gibbs_energy` | ✅ | `06_surface/surface_gibbs_example.py` |
| `select_stable_surface` | ❌ | no dedicated example yet |

---

## Detailed Brick-to-Example Mapping

### `vasp` — Standard VASP calculation (relax, static SCF)

| Example | Stage names | Notes |
|---------|------------|-------|
| `01_getting_started/single_vasp.py` | _(single stage via `quick_vasp`)_ | Hello-world static SCF |
| `03_batch/dynamic_batch_example.py` | `bulk_relax` | Bulk relaxation before surface generation |
| `04_sequential/mixed_dos_sources.py` | `relax` | Relax before DOS |
| `04_sequential/relax_then_dos.py` | `relax` | Relax before DOS |
| `06_surface/thickness_convergence.py` | `initial_relax` | Seed structure for thickness test |
| `06_surface/formation_enthalpy_example.py` | `bulk_relax`, `sn_relax` | SnO₂ + Sn reference relaxations |
| `06_surface/surface_gibbs_example.py` | `bulk_relax`, `sn_relax` | Bulk reference relaxations |
| `07_advanced_vasp/bader_analysis.py` | `relax`, `scf` | Relax + charge-density SCF for Bader |
| `07_advanced_vasp/birch_murnaghan_sno2.py` | — | Batch energies feed into BM EOS |
| `07_advanced_vasp/hubbard_u_sno2.py` | `relax`, `scf` | Two-stage ground-state before Hubbard |
| `07_advanced_vasp/hubbard_u_nio_afm_supercell.py` | `ground_state` | AFM ground state for Hubbard U |
| `07_advanced_vasp/neb_pipeline.py` | `relax_initial`, `relax_final` | Endpoint relaxations for NEB |
| `07_advanced_vasp/hybrid_bands_and_dos_sno2.py` | `hse_relax` | HSE06 relaxation stage |
| `07_advanced_vasp/sequential_relax_then_u.py` | `relax`, `scf` | Sequential relax → SCF → Hubbard |
| `08_aimd/aimd_workflow.py` | — | SnO₂ AIMD _(via `quick_aimd`, not `vasp` brick directly)_ |
| `11_neb/neb_pt_step_edge.py` | `relax_initial`, `relax_final` | NEB endpoint relaxations on Pt(211) |
| `12_dimer/dimer_ammonia.py` | `vib`, `vib_verify` | Vibrational analysis stages |

### `dos` — Density of states (BandsWorkChain wrapper)

| Example | Stage names | Notes |
|---------|------------|-------|
| `02_dos/single_dos.py` | _(single stage via `quick_dos`)_ | Basic DOS for SnO₂ |
| `02_dos/batch_dos.py` | _(via `quick_dos_batch`)_ | Parallel DOS for two structures |
| `04_sequential/mixed_dos_sources.py` | `dos_rutile`, `dos_pnnm` | DOS from two different source structures |
| `04_sequential/relax_then_dos.py` | `dos_calc` | DOS following relaxation |
| `07_advanced_vasp/hybrid_bands_and_dos_sno2.py` | `dos_hse` | HSE06 DOS stage |

### `batch` — Parallel VASP runs with varying parameters

| Example | Stage names | Notes |
|---------|------------|-------|
| `03_batch/compare_structures.py` | _(single stage via `quick_vasp_batch`)_ | Energy comparison of two SnO₂ polymorphs |
| `07_advanced_vasp/birch_murnaghan_sno2.py` | `eos_batch` | Volume-scan energies for BM EOS fitting |

### `birch_murnaghan` — Birch-Murnaghan EOS fitting

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/birch_murnaghan_sno2.py` | Fits E(V) from batch energies; outputs V₀, B₀, B₀′ |

### `birch_murnaghan_refine` — Refined BM EOS scan

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/birch_murnaghan_sno2.py` | Refines around V₀ from the first BM fit |

### `bader` — Bader charge analysis

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/bader_analysis.py` | Full pipeline: relax → SCF (LAECHG=True) → Bader |

### `convergence` — ENCUT / k-points convergence

| Example | Notes |
|---------|-------|
| `05_convergence/encut_kpoints.py` | Scans ENCUT and k-mesh density for SnO₂ |

### `thickness` — Slab thickness convergence

| Example | Notes |
|---------|-------|
| `06_surface/thickness_convergence.py` | SnO₂(110) slab: scans number of layers for surface energy |

### `hubbard_response` — Hubbard U linear-response calculations

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/hubbard_u_nio.py` | NiO via `quick_hubbard_u` convenience wrapper |
| `07_advanced_vasp/hubbard_u_nio_afm_supercell.py` | NiO 2×2×2 AFM supercell, explicit stages |
| `07_advanced_vasp/hubbard_u_sno2.py` | SnO₂ Sn-d Hubbard U, explicit stages |
| `07_advanced_vasp/sequential_relax_then_u.py` | Relax first, then compute U |

### `hubbard_analysis` — Hubbard U regression and summary

Same examples as `hubbard_response` (always used together with it).

### `aimd` — Ab initio molecular dynamics (IBRION=0)

| Example | Notes |
|---------|-------|
| `08_aimd/aimd_workflow.py` | SnO₂ NVT equilibration + production run |

### `qe` — Quantum ESPRESSO pw.x

| Example | Notes |
|---------|-------|
| `09_other_codes/qe_single_and_pipeline.py` | Single pw.x + relax → SCF pipeline for Si |

### `cp2k` — CP2K calculations

| Example | Notes |
|---------|-------|
| `09_other_codes/cp2k_pipeline.py` | Three-stage CP2K pipeline for Si |

### `generate_neb_images` — NEB image interpolation

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/neb_pipeline.py` | IDPP interpolation of 5 images between relaxed endpoints |
| `11_neb/neb_pt_step_edge.py` | IDPP images for N/Pt(211) step-edge diffusion |

### `neb` — NEB calculation (vasp.neb)

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/neb_pipeline.py` | Regular NEB → CI-NEB restart for SnO₂ |
| `11_neb/neb_pt_step_edge.py` | Regular NEB → CI-NEB for N diffusion on Pt(211) |

### `dimer` — Improved Dimer Method (IBRION=44)

| Example | Notes |
|---------|-------|
| `12_dimer/dimer_ammonia.py` | Ammonia inversion: vib → IDM TS search → vib verify |

### `hybrid_bands` — Hybrid functional band structure

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/hybrid_bands_and_dos_sno2.py` | HSE06 band structure + DOS for SnO₂ |

### `fukui_analysis` — Fukui index analysis

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/fukui_indices.py` | Condensed Fukui indices for SnO₂ surface reactivity |

### `fukui_dynamic` — Dynamic batch for Fukui perturbations

| Example | Notes |
|---------|-------|
| `07_advanced_vasp/fukui_indices.py` | Fan-out N±1 electron calculations for Fukui |

### `surface_enumeration` — Enumerate unique surface terminations

| Example | Notes |
|---------|-------|
| `06_surface/surface_enumeration.py` | List all symmetrically distinct SnO₂(110) terminations |

### `surface_terminations` — Generate slab models for each termination

| Example | Notes |
|---------|-------|
| `03_batch/dynamic_batch_example.py` | Generate SnO₂(110) slabs before dynamic batch relaxation |
| `06_surface/surface_gibbs_example.py` | Generate all termination slabs for surface Gibbs workflow |
| `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` | Full binary oxide thermodynamics pipeline |

### `dynamic_batch` — Scatter-gather batch over runtime-determined structures

| Example | Notes |
|---------|-------|
| `03_batch/dynamic_batch_example.py` | Relax all SnO₂(110) terminations in parallel |
| `06_surface/surface_gibbs_example.py` | Relax all slabs before Gibbs energy calculation |
| `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` | Full pipeline including dynamic_batch relaxation |

### `formation_enthalpy` — Bulk formation enthalpy calcfunction

| Example | Notes |
|---------|-------|
| `06_surface/formation_enthalpy_example.py` | ΔHf(SnO₂) from bulk + reference energies |
| `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` | Formation enthalpy as part of full surface thermo pipeline |

### `o2_reference_energy` — O₂ reference via water splitting

| Example | Notes |
|---------|-------|
| `06_surface/o2_reference_example.py` | Compute E_ref(O₂) from H₂ + H₂O calculations |
| `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` | O₂ reference as part of full surface thermo pipeline |

### `surface_gibbs_energy` — Surface Gibbs free energy γ(ΔμO)

| Example | Notes |
|---------|-------|
| `06_surface/surface_gibbs_example.py` | γ(ΔμO) for each SnO₂(110) termination |
| `06_surface/binary_surface_thermo/run_surface_thermo_prepare.py` | Full pipeline including γ vs ΔμO |

### `select_stable_surface` — Select thermodynamically stable termination

> ❌ **No dedicated example yet.**  This brick selects the lowest-γ surface from
> the `surface_gibbs_energy` output.  A simple usage example inside
> `06_surface/surface_gibbs_example.py` or a new `06_surface/stable_surface.py`
> would complete the coverage.

---

## Bricks Without Dedicated Examples

| Brick | Reason / Suggested example |
|-------|---------------------------|
| `select_stable_surface` | Post-processing step; add to `06_surface/surface_gibbs_example.py` or create `06_surface/stable_surface.py` |
