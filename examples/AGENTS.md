# AGENTS.md — Examples Directory

Guidance for AI coding agents working with the `examples/` directory.

## Directory Layout

```
examples/
├── _shared/
│   ├── config.py         # Profile setup, code labels, cluster options, STRUCTURES_DIR
│   └── structures.py     # load_sno2(), load_nio(), create_si_structure(), load_structure()
├── structures/           # Canonical .vasp/.cif input files used across examples
│   ├── sno2.vasp         # Rutile SnO2 primitive cell
│   ├── Sn.cif            # Sn metal reference
│   ├── H2.cif            # H2 molecule (for O2 reference via water splitting)
│   ├── H2O.cif           # H2O molecule (for O2 reference via water splitting)
│   ├── nio.vasp          # NiO rocksalt
│   └── ...
├── 01_getting_started/   # Simplest single-stage examples
├── 02_dos/ … 12_dimer/   # Topic-specific examples (see README.md)
└── 13_full_characterisation/
    ├── sno2_full_characterisation.py   # Main script (all six phases)
    └── README.md                       # Detailed documentation
```

## Shared Helpers

Always use `_shared/config.py` and `_shared/structures.py` when adding new
examples.  Key exports:

| Symbol | Type | Description |
|--------|------|-------------|
| `setup_profile()` | function | Loads the configured AiiDA profile |
| `DEFAULT_VASP_CODE` | str | `VASP-6.5.1@localwork` (override via env var) |
| `LOCALWORK_OPTIONS` | dict | 1 machine, 8 MPI procs (local testing) |
| `OBELIX_OPTIONS` | dict | 1 node, 4 MPI procs, PBS skylake 88-core |
| `SNO2_POTCAR` | dict | `{'family': 'PBE', 'mapping': {'Sn': 'Sn_d', 'O': 'O'}}` |
| `STRUCTURES_DIR` | Path | Absolute path to `examples/structures/` |
| `load_sno2()` | function | Returns `StructureData` for rutile SnO2 |
| `load_nio()` | function | Returns `StructureData` for NiO |

## 13_full_characterisation — Six-Phase SnO2 Pipeline

This is the most comprehensive example in the repository.  It runs all
seventeen quantum-lego brick types in a single `quick_vasp_sequential` call.

### Phase Architecture

```
T=0 ──┬── initial_relax       Phase 1: BM EOS chain
      ├── hub_ground_state    Phase 2: Hubbard U (parallel, independent)
      ├── sn_relax            Phase 5: reference metals (parallel)
      └── o2_ref              Phase 5: O2 reference (parallel)

T=1 ──┬── volume_scan         (after initial_relax)
      └── hub_response        (after hub_ground_state)

T=2 ──┬── eos_fit             (after volume_scan)
      └── hub_analysis        (after hub_response)

T=3 ──── eos_refine           (after eos_fit)

T=4 ──── bulk_relax           (after eos_refine)

T=5 ──┬── hse_prerelax        Phase 3: HSE06 (after bulk_relax)
      ├── enumerate_surfaces  Phase 4: surface enumeration
      ├── dhf                 Phase 5: formation enthalpy
      └── slab_terms_{hkl}    Phase 5: terminations (one per hkl)

T=6 ──┬── hse_bands           (after hse_prerelax)
      ├── hse_dos             (after hse_prerelax, independent branch)
      └── slab_relax_{hkl}    (after slab_terms_{hkl}, one per hkl)

T=7 ──── surface_gibbs_{hkl}  (after slab_relax_{hkl} + dhf)

T=8 ──── select_stable_{hkl}  (after surface_gibbs_{hkl} + slab_relax_{hkl})

T=9 ──── fukui_batch_{hkl}    (after select_stable_{hkl})

T=10 ─┬── fukui_plus_{hkl}    (after fukui_batch_{hkl})
      └── fukui_minus_{hkl}   (after fukui_batch_{hkl})
```

### Key Design Decisions

**Parallel phases from T=0**
Phases 1 (EOS chain), 2 (Hubbard U), and 5 (Sn + O2 references) share no
data edges, so WorkGraph starts them simultaneously.  This saves wall time
equivalent to the longest of the three chains.

**Pre-enumeration at submission time**
`get_symmetrically_distinct_miller_indices` runs in plain Python before
submission to allow a `for hkl in miller_list` loop when building stages.
The `enumerate_surfaces` WorkGraph stage still runs in-graph as a verification
step.

**Hubbard U supercell**
`prepare_perturbed_structure` splits one Sn atom into kind `'Sn'` (perturbed)
and the other 15 into kind `'Sn1'` (unperturbed).  This is done once at
submission time and stored in `split_supercell`.  The POTCAR must map both
`'Sn'` and `'Sn1'` to `'Sn_d'`.

**`select_stable_surface` clone requirement**
The `pick_structure_by_label` calcfunction calls `struct.clone()` before
returning.  This is mandatory: a `StructureData` produced by the upstream
`dynamic_batch` VASP calculation already has a `CREATE` link; AiiDA forbids
a second `CREATE` link from the calcfunction output.  Cloning creates a new
node with fresh provenance.

**EOS chain and `structure_from`**
`eos_refine` uses `structure_from: initial_relax` (not the BM-recommended
bare structure) so that the already-relaxed cell is used as the scaling base
for the refined volume points.  This avoids rescaling an un-relaxed cell.

**HSE06 DOS as a separate stage**
`VaspHybridBandsWorkChain` in aiida-vasp does not run a DOS calculation.
A separate `dos` stage (`hse_dos`) is therefore required and can run in
parallel with `hse_bands` once `hse_prerelax` is done.

### Adding a New Surface Orientation

Add it to `miller_list` before the loop:

```python
miller_list = [(1, 1, 0), (1, 0, 0), (0, 0, 1)]
```

The loop appends the full seven-stage pipeline automatically.

### Adapting for a Different Material

1. Replace `sno2.vasp` with your structure file.
2. Adjust `potential_mapping` for the new species.
3. Update `POTENTIAL_MAPPING` to include any new element → POTCAR mappings.
4. Adjust `hub_response` `target_species` and `ldaul` for your d/f metal.
5. Remove Phases 2, 3, 5, 6 if not needed (simply delete those stages).

### Common Failure Modes

| Error | Cause | Fix |
|-------|-------|-----|
| `already has an incoming CREATE link` | calcfunction returning an existing AiiDA node | Call `.clone()` before returning |
| `select_stable fails: no valid phi values` | Summary dict structure mismatch | Check `surface_gibbs_energy` output format; key is `surface_energies` |
| `WorkGraph [302]`: child tasks skipped | A parent stage failed | Run `verdi process report <PK>` to find the failing task |
| VASP out-of-memory on slab | Slab too large for 4 MPI procs | Increase `num_mpiprocs_per_machine` or reduce slab size |

### Inspecting Phase Results

```python
from aiida.orm import load_node
from quantum_lego import print_sequential_results

wg = load_node(<PK>)

# Phase 1: bulk equilibrium energy
e_bulk = wg.outputs.bulk_relax_energy.value   # eV

# Phase 2: Hubbard U
u_result = wg.outputs.hub_analysis_result.get_dict()
print(f"U(Sn-d) = {u_result['U_eV']:.3f} eV, R² = {u_result['r_squared']:.4f}")

# Phase 5: surface energies for (1,1,0)
gamma = wg.outputs.surface_gibbs_110_summary.get_dict()
for label, data in gamma['surface_energies'].items():
    print(f"  {label}: φ = {data['primary']['phi']:.4f} J/m²")

# Phase 6: download Fukui f+(r) CHGCAR for (1,1,0)
fukui_node = wg.outputs.fukui_plus_110_chgcar
fukui_node.base.repository.get_object_content('CHGCAR_FUKUI.vasp')

# Print all results at once
print_sequential_results(<PK>)
```
