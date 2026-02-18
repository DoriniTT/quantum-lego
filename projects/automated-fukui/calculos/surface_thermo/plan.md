# Plan: SnO2 surface-thermo example (single WorkGraph)

## Goal (this step only)

Create a **working example** in:

- `/home/trevizam/git/automated-fukui/calculos/surface_thermo/`

that:

1. Relaxes **bulk SnO2** using the `vasp` brick
2. Generates **all symmetrized slab terminations** for one Miller index using `pymatgen.core.surface.SlabGenerator`
   - defaults: **18 Å slab thickness**, **15 Å vacuum**
3. Relaxes all generated slab terminations **in parallel** (fan-out inside the same WorkGraph)
4. Computes the **enthalpy of formation** of the relaxed SnO2 bulk using reference calculations for **Sn** and **O2**
   - Sn, O2 are computed as additional independent `vasp` stages in the same WorkGraph
   - a new pure-Python brick computes ΔHf from the 3 relaxed structures + energies

Out of scope for now:

- Connecting `surface_enumeration` into this pipeline
- Computing surface thermodynamics / surface Gibbs free energy

---

## Key constraints / design choices

- Slab terminations are only known **after** the bulk relaxation finishes, so the slab relaxation step must support **dynamic fan-out** inside a single WorkGraph (same pattern already used by `relax_thickness_series` in the thickness-convergence tooling).
- We will keep the “slab terminations” brick focused on **generation only** (no VASP inside it); relaxation happens in a separate stage.

Assumption for the SnO2 demo surface:

- Use **(1, 1, 0)** (SnO2(110)) as the Miller index by default (common rutile surface and already used elsewhere in examples).

Formation enthalpy conventions (proposal; confirm in review):

- Compute ΔHf in **eV per reduced formula unit** and also report **eV/atom**
- Reference energies are taken **per atom** from the reference structures:
  - Sn reference: bulk Sn energy / N(Sn)
  - O reference: O2-in-a-box energy / 2

---

## Workplan

### A) Add a “surface terminations” brick to quantum-lego (generation only)

- [x] Search existing bricks/helpers to reuse (`SlabGenerator` prior art is in `core/common/convergence/slabs.py`)
- [x] Implement new brick module:
  - `quantum_lego/core/bricks/surface_terminations.py`
  - Pure-Python `@task.calcfunction` that:
    - inputs: `structure`, `miller_indices`, `min_slab_size`, `min_vacuum_size`, `lll_reduce`, `center_slab`, `primitive`
    - uses `SlabGenerator(...).get_slabs(symmetrize=True)` to generate *all* terminations
    - converts each slab to `StructureData` (use `get_orthogonal_c_slab()` like thickness helpers)
    - returns:
      - `slabs`: **dynamic namespace** of `StructureData` (e.g. `term_00`, `term_01`, …)
      - `manifest`: `Dict` with labels + termination metadata (shifts, miller, counts, parameters)
- [x] Wire brick into the sequential system:
  - register ports in `quantum_lego/core/bricks/connections.py`
  - register module in `quantum_lego/core/bricks/__init__.py`
- [x] Update `quantum-lego` tests to include the new brick in the registry/valid type list

### B) Relax generated terminations inside the same WorkGraph (`dynamic_batch`)

- [x] Implement a dedicated `dynamic_batch` brick that takes a **dynamic dict of structures**
  (output of `surface_terminations`) and relaxes them in parallel (internally reusing the
  `relax_thickness_series` fan-out pattern).
- [x] Ensure the termination-relax stage outputs:
  - relaxed structures (dynamic namespace)
  - energies (dynamic namespace or aggregated `Dict`)
  so later “surface thermodynamics” can consume them without link-traversal hacks.

### C) Add a “formation enthalpy” brick to quantum-lego

- [x] Implement new brick module:
  - `quantum_lego/core/bricks/formation_enthalpy.py`
  - Pure-Python `@calcfunction` to compute ΔHf from:
    - target structure + energy (SnO2)
    - one or more reference structures + energies (pure-element references, e.g. Sn, O2)
  - Returns `orm.Dict` with:
    - target formula/composition, total energy, energy/atom, energy/formula-unit
    - per-element reference energy/atom
    - computed ΔHf (eV/formula-unit + eV/atom)
- [x] Brick module functions:
  - `validate_stage`: verify required `*_from` fields exist and reference previous stages
  - `create_stage_tasks`: resolve structure/energy sockets via `resolve_structure_from` + `resolve_energy_from`
  - `expose_stage_outputs`: expose `formation_enthalpy` Dict on `wg.outputs`
  - `get_stage_results` + `print_stage_results`: mirror style of other analysis bricks
- [x] Wire into registry + connections:
  - add port type (e.g. `formation_enthalpy`) and ports declarations
  - add to `BRICK_REGISTRY`
- [x] Update `quantum-lego` tests to include the new brick in the registry/valid type list

### D) Create the automated-fukui run script (SnO2)

- [x] Create folder structure:
  - `/home/trevizam/git/automated-fukui/calculos/surface_thermo/`
  - `structures/` (copied `sno2.vasp` + reference `Sn.cif` and `O2.cif`)
- [x] Add a single-workgraph run script, e.g.:
  - `calculos/surface_thermo/run_surface_thermo_prepare.py`
- [x] Script behavior:
  - load AiiDA profile (match other calculos scripts: `presto`)
  - read `structures/sno2.vasp`
  - build explicit reference structures for Sn and O2 (either from files in `structures/` or constructed with ASE; decision documented in script)
  - define stages (single WorkGraph), roughly:
    1) `bulk_relax` (`type: vasp`, `restart: None`)
    2) `sn_relax` (`type: vasp`, `structure: <Sn StructureData>`, `restart: None`)
    3) `o2_relax` (`type: vasp`, `structure: <O2 StructureData>`, `restart: None`)
    4) `slab_terms` (`type: surface_terminations`, `structure_from: bulk_relax`, miller=(1,1,0), 18A/15A defaults)
    5) `slab_relax` (`type: dynamic_batch`, `structures_from: slab_terms`, relax all terminations)
    6) `dhf` (`type: formation_enthalpy`, `structure_from`/`energy_from`=bulk_relax, references={'Sn': sn_relax, 'O': o2_relax})
  - submit via `quick_vasp_sequential(...)` with appropriate `max_concurrent_jobs`
  - write PK to `surface_thermo_pks.txt`

### E) Verification

- [x] Run `pytest -q` in `/home/trevizam/git/quantum-lego`
- [ ] Dry-run the surface_thermo script (imports + stage validation) (optional local run)
- [x] Ensure the generated slab labels are stable/deterministic between runs for the same structure + parameters (sorted by slab shift)

---

## Notes / future follow-ups (not in this step)

- Integrate `surface_enumeration` so Miller indices can be generated automatically (instead of hard-coding (110)).
- Extend workflow to compute surface energies and then surface Gibbs free energies (ab initio atomistic thermodynamics).
- Add the actual “surface_thermodynamics” brick/preset (bulk + references + terminations + relaxations + thermodynamics) once this example is validated end-to-end.
