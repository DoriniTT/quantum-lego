# TODO: Lego as Central Orchestration Hub

## Vision

The `lego` module is the **central orchestration hub** for all PS-TEROS workflows. Instead of just chaining VASP calculations, users can compose complex multi-physics workflows by combining different stage types as **bricks**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          LEGO: Central Hub                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Stage 1        Stage 2        Stage 3        Stage 4        Stage 5      │
│  ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐       │
│  │  VASP  │───►│  VASP  │───►│  VASP  │───►│  DOS   │───►│  AIMD  │       │
│  │ relax  │    │ relax  │    │supercell│    │ module │    │ module │       │
│  └────────┘    └────────┘    └────────┘    └────────┘    └────────┘       │
│      │              │              │              │              │          │
│      ▼              ▼              ▼              ▼              ▼          │
│   outputs        outputs        outputs        outputs        outputs      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Motivation

Currently, to run a complex workflow like:
1. Relax a slab (rough → fine)
2. Create supercell and relax
3. Calculate DOS
4. Run AIMD simulation

Users must manually orchestrate separate workflows and pass data between them. With the "LEGO" approach, this becomes a single, unified workflow with automatic data passing.

## Example: The Dream API

```python
from quantum_lego.core import quick_workflow

stages = [
    # Stage 1-4: VASP relaxations (current functionality)
    {
        'name': 'relax_1x1_rough',
        'type': 'vasp',  # NEW: stage type
        'incar': incar_rough,
        'restart': None,
        'kpoints_spacing': 0.06,
        'fix_type': 'center',
        'fix_thickness': 7.0,
    },
    {
        'name': 'relax_1x1_fine',
        'type': 'vasp',
        'incar': incar_fine,
        'restart': None,
        'kpoints_spacing': 0.03,
        'fix_type': 'center',
        'fix_thickness': 7.0,
    },
    {
        'name': 'relax_2x2',
        'type': 'vasp',
        'supercell': [2, 2, 1],
        'incar': incar_fine,
        'restart': None,
        'kpoints': [6, 6, 1],
        'fix_type': 'center',
        'fix_thickness': 7.0,
    },

    # Stage 5: DOS calculation (NEW!)
    {
        'name': 'dos_calculation',
        'type': 'dos',  # Uses quick_dos internally
        'structure_from': 'relax_2x2',  # Use structure from previous stage
        'scf_incar': {'encut': 700, 'ediff': 1e-6, 'ismear': 0},
        'dos_incar': {'nedos': 3000, 'lorbit': 11, 'ismear': -5},
        'dos_kpoints_spacing': 0.02,
        'retrieve': ['DOSCAR'],
    },

    # Stage 6: AIMD simulation (NEW!)
    {
        'name': 'aimd_equilibration',
        'type': 'aimd',  # Uses AIMD module internally
        'structure_from': 'relax_2x2',
        'temperature': 300,  # Kelvin
        'timestep': 1.0,     # fs
        'nsteps': 5000,
        'ensemble': 'NVT',
        'thermostat': 'nose-hoover',
    },

    # Stage 7: Production AIMD (NEW!)
    {
        'name': 'aimd_production',
        'type': 'aimd',
        'structure_from': 'aimd_equilibration',
        'restart': 'aimd_equilibration',  # Continue from equilibration
        'temperature': 300,
        'nsteps': 50000,
    },

    # Stage 8: Surface thermodynamics (FUTURE)
    {
        'name': 'surface_energy',
        'type': 'thermodynamics',
        'structure_from': 'relax_2x2',
        'bulk_structure': bulk_structure,
        'reference_energies': {...},
    },
]

result = quick_workflow(
    structure=initial_structure,
    stages=stages,
    code_label='VASP-6.5.1@cluster',
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options=options,
)
```

## Module Integration Roadmap

### Phase 1: DOS Integration (DONE)

**Status:** Implemented as `bricks/dos.py`. DOS stages use the BandsWorkChain internally.

**Stage Configuration for DOS:**
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `type` | Yes | - | `'dos'` |
| `name` | Yes | - | Unique stage identifier |
| `structure_from` | Yes | - | Stage name to get structure from |
| `scf_incar` | Yes | - | INCAR for SCF step |
| `dos_incar` | Yes | - | INCAR for DOS step |
| `kpoints_spacing` | No | base | K-points for SCF |
| `dos_kpoints_spacing` | No | 80% of SCF | K-points for DOS |
| `retrieve` | No | `[]` | Files to retrieve |

---

### Phase 2: AIMD Integration (Priority: MEDIUM)

**Goal:** Add `type: 'aimd'` stages that use the AIMD module.

**Stage Configuration for AIMD:**
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `type` | Yes | - | `'aimd'` |
| `name` | Yes | - | Unique stage identifier |
| `structure_from` | Yes | - | Stage name for initial structure |
| `restart` | No | `None` | Stage name for AIMD restart |
| `temperature` | Yes | - | Temperature (K) |
| `timestep` | No | 1.0 | Timestep (fs) |
| `nsteps` | Yes | - | Number of MD steps |
| `ensemble` | No | `'NVT'` | `'NVE'`, `'NVT'`, `'NPT'` |
| `thermostat` | No | `'nose-hoover'` | Thermostat type |
| `incar_overrides` | No | `{}` | Additional INCAR settings |

**Outputs:**
- `{stage_name}_trajectory` - Trajectory data
- `{stage_name}_final_structure` - Final structure
- `{stage_name}_temperature_history` - T vs time
- `{stage_name}_energy_history` - E vs time

---

### Phase 3: Surface Thermodynamics (Priority: LOW)

**Goal:** Add `type: 'thermodynamics'` stages.

**Stage Configuration:**
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `type` | Yes | - | `'thermodynamics'` |
| `slab_structure_from` | Yes | - | Stage with relaxed slab |
| `bulk_structure` | Yes | - | Bulk structure (StructureData) |
| `bulk_energy` | No | - | Pre-computed bulk energy |
| `reference_energies` | Yes | - | O2, metal references |
| `temperature_range` | No | [300, 1000] | T range for phase diagram |

**Outputs:**
- `{stage_name}_surface_energy` - γ(T, Δμ)
- `{stage_name}_phase_diagram` - Stability regions

---

### Phase 4: Additional Modules (Priority: FUTURE)

| Module | Stage Type | Description |
|--------|------------|-------------|
| Adsorption Energy | `'adsorption'` | Calculate E_ads for adsorbates |
| Electronic Structure | `'bands'` | Band structure calculation |
| Phonons | `'phonons'` | Phonon dispersion (if supported) |
| NEB | `'neb'` | Nudged elastic band for barriers |
| Bader Analysis | `'bader'` | Charge analysis |

---

## Architecture Changes

### Current Architecture (Implemented)
```
quick_vasp_sequential()
    └── Brick dispatcher (vasp, dos, batch, bader)
        ├── bricks/vasp.py
        ├── bricks/dos.py
        ├── bricks/batch.py
        └── bricks/bader.py
```

Each brick module exports a PORTS dict plus 5 functions:
```python
PORTS                    # From connections.py (e.g., VASP_PORTS as PORTS)
def validate_stage(stage, stage_names): ...
def create_stage_tasks(wg, stage, stage_name, context): ...
def expose_stage_outputs(wg, stage_name, tasks_result): ...
def get_stage_results(wg_node, wg_pk, stage_name): ...
def print_stage_results(index, stage_name, stage_result): ...
```

### Key Design Decisions

1. **Backward Compatibility**
   - `quick_vasp_sequential()` uses brick dispatcher internally
   - Stages without `type` field default to `'vasp'`
   - All public API exports unchanged

2. **Brick Module Pattern**
   - Each brick is a Python module (not a class) with 5 standard functions
   - Registry in `bricks/__init__.py` maps type strings to modules
   - New bricks are added by creating a module and registering it

3. **Context Passing**
   ```python
   context = {
       'wg': wg,
       'code': code,
       'potential_family': potential_family,
       'potential_mapping': potential_mapping or {},
       'options': options,
       'base_kpoints_spacing': kpoints_spacing,
       'clean_workdir': clean_workdir,
       'stage_tasks': stage_tasks,
       'stage_types': stage_types,
       'stage_names': stage_names,
       'stages': stages,
       'input_structure': structure,
       'stage_index': i,
   }
   ```

4. **Output Naming Convention**
   ```
   {stage_name}_{output_type}

   Examples:
   - relax_2x2_energy
   - relax_2x2_structure
   - dos_calculation_dos
   - dos_calculation_projectors
   - aimd_production_trajectory
   - aimd_production_final_structure
   ```

---

## Implementation Plan

### Step 1: Refactor into Bricks (DONE)
- [x] Extract VASP stage handling into `bricks/vasp.py`
- [x] Extract DOS stage handling into `bricks/dos.py`
- [x] Extract batch stage handling into `bricks/batch.py`
- [x] Extract bader stage handling into `bricks/bader.py`
- [x] Create brick registry in `bricks/__init__.py`
- [x] Slim down `workgraph.py` and `results.py` to thin dispatchers
- [x] Ensure backward compatibility

### Step 2: Implement AIMD Integration
- [ ] Create `bricks/aimd.py` brick module
- [ ] Add AIMD stage validation
- [ ] Wire AIMD WorkGraph as task
- [ ] Handle AIMD restart between stages
- [ ] Add trajectory output extraction
- [ ] Write tests
- [ ] Update documentation

### Step 2b: Implement Fukui Analysis Brick (Priority: HIGH)

**Goal:** Add `type: 'fukui_analysis'` brick that takes 4 CHGCAR files from a `batch` stage, runs FukuiGrid `Fukui_interpolation`, and exposes `CHGCAR_FUKUI.vasp` as `SinglefileData`.

**Stage Configuration:**
```python
{
    'name': 'fukui_minus_analysis',
    'type': 'fukui_analysis',
    'batch_from': 'fukui_minus_calcs',   # references a batch stage
    'fukui_type': 'minus',               # 'minus' (f⁻, negate δN) or 'plus' (f⁺)
    'delta_n_map': {                     # calc_label → |δN| value (exactly 4 entries)
        'neutral':   0.00,
        'delta_005': 0.05,
        'delta_010': 0.10,
        'delta_015': 0.15,
    },
}
```

**Files to create/modify:**

1. **Create `bricks/fukui_analysis.py`** — New brick module with:
   - `PORTS` (imported from `connections.py` as `FUKUI_ANALYSIS_PORTS`)
   - `validate_stage()` — Check `batch_from` references a previous stage, `fukui_type` is 'minus'|'plus', `delta_n_map` has exactly 4 entries
   - `create_stage_tasks()`:
     - Get batch stage's `calc_tasks` from `context['stage_tasks'][batch_from]`
     - Sort calc_labels by delta_n descending (FukuiGrid requirement)
     - Apply sign convention: negate δN for `fukui_type='minus'`, keep positive for `'plus'`
     - Build `orm.Dict` config with sorted delta_n array
     - Wire the 4 sorted `retrieved` FolderData outputs → `run_fukui_interpolation` calcfunction
   - `run_fukui_interpolation` calcfunction (`@task.calcfunction(outputs=['fukui_chgcar'])`):
     - Inputs: `retrieved_1..4` (`orm.FolderData`), `config` (`orm.Dict`)
     - Extract CHGCAR from each FolderData → tempdir
     - Import FukuiGrid via path relative to teros: `Path(__file__).parents[3] / 'external' / 'FukuiGrid'`
     - Call `Fukui_interpolation(file1, file2, file3, file4, dn=sorted_dn)`
     - Return `{'fukui_chgcar': orm.SinglefileData(file='CHGCAR_FUKUI.vasp')}`
   - `expose_stage_outputs()` — Expose `fukui_chgcar` on wg.outputs (namespace + flat naming)
   - `get_stage_results()` — Extract SinglefileData from outputs (direct + link traversal fallback)
   - `print_stage_results()` — Print file PK and size

2. **Modify `bricks/connections.py`**:
   - Add `FUKUI_ANALYSIS_PORTS` dict:
     ```python
     FUKUI_ANALYSIS_PORTS = {
         'inputs': {
             'batch_retrieved': {
                 'type': 'retrieved',
                 'required': True,
                 'source': 'batch_from',
                 'compatible_bricks': ['batch'],
                 'prerequisites': {'retrieve': ['CHGCAR']},
                 'description': 'Retrieved folders from batch stage (must contain CHGCAR)',
             },
         },
         'outputs': {
             'fukui_chgcar': {
                 'type': 'file',
                 'description': 'Interpolated Fukui function (CHGCAR_FUKUI.vasp as SinglefileData)',
             },
         },
     }
     ```
   - Add `'fukui_analysis': FUKUI_ANALYSIS_PORTS` to `ALL_PORTS`

3. **Modify `bricks/__init__.py`**:
   - Import `fukui_analysis` module
   - Add `'fukui_analysis': fukui_analysis` to `BRICK_REGISTRY`

**Design decisions:**
- Exactly 4 calculations (matches FukuiGrid's `Fukui_interpolation` signature)
- `delta_n_map` provided explicitly by user (no inference from labels)
- FukuiGrid located via path relative to teros package (`Path(__file__).parents[3] / 'external/FukuiGrid'`)

**Delta-N sorting convention:**
- FukuiGrid expects files sorted by |δN| descending
- For f⁻: δN = [-0.15, -0.10, -0.05, 0.00]
- For f⁺: δN = [0.15, 0.10, 0.05, 0.00]

**Verification:**
- [ ] `validate_stage` catches missing `batch_from`, invalid `fukui_type`, wrong number of entries in `delta_n_map`
- [ ] `validate_connections()` validates batch → fukui_analysis connection (compatible_bricks + prerequisites)
- [ ] Integration: add fukui_analysis stage after batch in a workflow, verify CHGCAR_FUKUI.vasp appears as SinglefileData output

### Step 3: Additional Bricks
- [ ] New bricks added by creating module + registering in `bricks/__init__.py`
- [ ] Unified validation via brick dispatcher
- [ ] Unified result extraction via brick dispatcher

---

## Open Questions

1. **How to handle different codes per stage?**
   - Some stages might need different VASP versions
   - AIMD might use CP2K instead of VASP
   - Solution: Allow `code_label` override per stage?

2. **How to handle different computational resources?**
   - DOS needs fewer resources than AIMD
   - Solution: Allow `options` override per stage?

3. **How to handle stage dependencies beyond structure?**
   - Some modules need multiple inputs (thermodynamics needs bulk + slab)
   - Solution: Allow `inputs_from` dict mapping input names to stages?

4. **How to handle conditional stages?**
   - "Only run AIMD if relaxation converged"
   - Solution: Add `condition` field with simple expressions?

5. **How to visualize complex workflows?**
   - ASCII art in terminal?
   - Export to graphviz/mermaid?

---

## Example Use Cases

### Use Case 1: Surface Characterization Pipeline
```python
stages = [
    {'type': 'vasp', 'name': 'relax', ...},
    {'type': 'dos', 'name': 'dos', 'structure_from': 'relax', ...},
    {'type': 'bands', 'name': 'bands', 'structure_from': 'relax', ...},
    {'type': 'bader', 'name': 'charges', 'structure_from': 'relax', ...},
]
```

### Use Case 2: Phase Diagram Calculation
```python
stages = [
    {'type': 'vasp', 'name': 'bulk_relax', ...},
    {'type': 'vasp', 'name': 'slab_relax', ...},
    {'type': 'thermodynamics', 'name': 'phase_diagram',
     'bulk_from': 'bulk_relax', 'slab_from': 'slab_relax', ...},
]
```

### Use Case 3: AIMD with Analysis
```python
stages = [
    {'type': 'vasp', 'name': 'relax', ...},
    {'type': 'aimd', 'name': 'equilibrate', 'structure_from': 'relax', ...},
    {'type': 'aimd', 'name': 'production', 'restart': 'equilibrate', ...},
    {'type': 'analysis', 'name': 'rdf', 'trajectory_from': 'production', ...},
]
```

### Use Case 4: Defect Formation Energy
```python
stages = [
    {'type': 'vasp', 'name': 'pristine', 'structure': pristine, ...},
    {'type': 'vasp', 'name': 'vacancy', 'structure': vacancy, ...},
    {'type': 'defect_energy', 'name': 'formation',
     'pristine_from': 'pristine', 'defect_from': 'vacancy', ...},
]
```

---

## Notes

- DOS, batch, and bader bricks already implemented
- Keep the architecture flexible for future bricks
- Maintain the "simple API" philosophy of lego
- Each brick has comprehensive validation
- Error messages clearly indicate which stage failed and why

---

## References

- Current `quick_vasp_sequential()` implementation: `workgraph.py`
- DOS module: `quick_dos()` in `workgraph.py`
- AIMD module: `teros/core/aimd/`
- Thermodynamics: `teros/core/thermodynamics.py`
- Adsorption energy: `teros/core/adsorption_energy.py`

---

*Created: 2025-01-27*
*Status: PLANNING*
*Priority: HIGH for DOS, MEDIUM for AIMD, LOW for others*
