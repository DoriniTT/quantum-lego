# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

```bash
# After any code changes
verdi daemon restart

# Run tests for this module
pytest teros/core/aimd/test_*.py -v

# Run specific test file
pytest teros/core/aimd/test_utils.py -v       # Validation utilities
pytest teros/core/aimd/test_tasks.py -v       # Supercell creation
pytest teros/core/aimd/test_overrides.py -v   # Override system

# Linting
flake8 teros/core/aimd/ --max-line-length=120 --ignore=E501,W503,E402,F401
```

---

## Module Overview

`teros/core/aimd/` is a **standalone AIMD module** for running Ab Initio Molecular Dynamics calculations independent of the main bulk+slab workflow. It provides:

- Direct structure input (StructureData or PKs)
- Sequential multi-stage AIMD with automatic restart chaining
- Optional supercell transformations before AIMD
- Three-tier override system for per-structure/stage parameter customization
- Concurrency control via `max_concurrent_jobs`

### Module Structure

```
aimd/
├── __init__.py           # Exports: build_aimd_workgraph, organize_aimd_results
├── workgraph.py          # Main entry: build_aimd_workgraph()
├── tasks.py              # WorkGraph tasks: create_supercell, create_supercells_scatter
├── utils.py              # Validation and merging utilities
├── test_utils.py         # Tests for validation
├── test_tasks.py         # Tests for supercell creation
├── test_overrides.py     # Tests for override system
└── README.md             # User documentation
```

---

## Architecture

### Relationship to Parent Module

This module is **independent** from `teros.core.workgraph.build_core_workgraph()` but reuses the underlying `aimd_single_stage_scatter()` function from `teros.core.aimd_functions.py`.

```
build_aimd_workgraph()  (this module)
        │
        └──> aimd_single_stage_scatter()  (from quantum_lego.core.common.aimd_functions)
                    │
                    └──> VaspWorkChain  (from aiida-vasp)
```

### Workflow Execution Pattern

```
1. create_supercell_{name}  (optional, if supercell_specs provided)
   ↓
2. stage_0_aimd  (equilibration, all structures in parallel)
   ↓
3. stage_1_aimd  (production, restarts from stage 0)
   ↓
4. stage_N_aimd  (continues until all stages complete)
```

**Key behaviors:**
- Within each stage: structures run **in parallel** (limited by `max_concurrent_jobs`)
- Across stages: strictly **sequential** (stage N+1 waits for stage N)
- Restart chaining: stage N+1 automatically uses stage N's `remote_folder`

---

## Key Components

### `workgraph.py` - Main Entry Point

**`build_aimd_workgraph()`** - The primary user-facing function.

Key parameters:
- `structures`: `{name: StructureData | PK}` - input structures
- `aimd_stages`: `[{'TEBEG': K, 'NSW': N}, ...]` - VASP-native parameters per stage
- `builder_inputs`: Base VASP configuration for all calculations
- `supercell_specs`: `{name: [nx, ny, nz]}` - optional supercell creation
- Override parameters (see below)

### `tasks.py` - WorkGraph Tasks

- **`create_supercell_calcfunc()`**: `@calcfunction` that creates supercells via pymatgen
- **`create_supercell`**: Task-wrapped version for use in WorkGraphs
- **`create_supercells_scatter()`**: `@task.graph` for parallel supercell creation

Conversion path: `StructureData → ASE → pymatgen → supercell → ASE → StructureData`

### `utils.py` - Validation & Utilities

- **`validate_stage_sequence()`**: Ensures each stage has `TEBEG` and `NSW`
- **`validate_supercell_spec()`**: Validates `[nx, ny, nz]` format
- **`merge_builder_inputs()`**: Deep merges override dicts into base config
- **`organize_aimd_results()`**: Extracts results from completed WorkGraph (TODO)

---

## Override System

Three levels of INCAR parameter customization:

| Level | Format | Scope |
|-------|--------|-------|
| `structure_overrides` | `{struct_name: {...}}` | All stages for one structure |
| `stage_overrides` | `{stage_idx: {...}}` | All structures for one stage |
| `matrix_overrides` | `{(struct_name, stage_idx): {...}}` | Specific (structure, stage) pair |

**Priority order** (highest to lowest):
1. `matrix_overrides`
2. `stage_overrides`
3. `structure_overrides`
4. `builder_inputs` (base)

**Limitation**: Only `parameters.incar` can be overridden. K-points, options, and potential settings remain uniform.

---

## Testing Patterns

Tests load the AiiDA profile at module level:
```python
from aiida import orm, load_profile
load_profile('presto')
```

**Test categories:**
- `test_utils.py`: Pure Python validation (no AiiDA nodes required for validation tests)
- `test_tasks.py`: Calcfunction tests with actual StructureData nodes
- `test_overrides.py`: Integration tests for WorkGraph construction

Example test structure:
```python
def test_validate_stage_sequence_valid():
    """Valid stage sequence passes."""
    stages = [{'TEBEG': 300, 'NSW': 100}]
    validate_stage_sequence(stages)  # Should not raise

def test_validate_stage_sequence_missing_tebeg():
    """Stage missing TEBEG raises ValueError."""
    with pytest.raises(ValueError, match="missing required key 'TEBEG'"):
        validate_stage_sequence([{'NSW': 100}])
```

---

## Adding New Features

### New Validation Function

Add to `utils.py`:
```python
def validate_my_input(value: SomeType) -> None:
    """Validate input.

    Raises:
        ValueError: If validation fails
    """
    if not valid:
        raise ValueError("Descriptive error message")
```

Add tests in `test_utils.py`.

### New Task

Add to `tasks.py`:
```python
@calcfunction
def my_calcfunc(structure: orm.StructureData, ...) -> orm.StructureData:
    """Docstring."""
    # Pure computation, no I/O
    return result

# Wrap as WorkGraph task
my_task = task(my_calcfunc)
```

Add tests in `test_tasks.py`.

### New Override Type

Modify `workgraph.py`:
1. Add parameter to `build_aimd_workgraph()` signature
2. Apply in the override merging loop (after line ~156)
3. Document priority order
4. Add tests in `test_overrides.py`

---

## Common Patterns

### AiiDA Node Type Conversions

```python
# List for WorkGraph
spec = orm.List(list=[2, 2, 1])
spec_values = spec.get_list()  # → [2, 2, 1]

# Load node by PK
if isinstance(struct_input, int):
    struct = orm.load_node(struct_input)
```

### Structure Manipulation

```python
# StructureData ↔ ASE ↔ Pymatgen
from pymatgen.io.ase import AseAtomsAdaptor

ase_atoms = structure.get_ase()
adaptor = AseAtomsAdaptor()
pmg_struct = adaptor.get_structure(ase_atoms)

# Supercell
pmg_supercell = pmg_struct * [2, 2, 1]

# Back to StructureData
ase_supercell = adaptor.get_atoms(pmg_supercell)
result = orm.StructureData(ase=ase_supercell)
```

### Deep Merge for Parameter Overrides

```python
from quantum_lego.core.common.aimd.utils import merge_builder_inputs

base = {'parameters': {'incar': {'ENCUT': 400, 'ISMEAR': 0}}}
override = {'parameters': {'incar': {'ENCUT': 520}}}

result = merge_builder_inputs(base, override)
# {'parameters': {'incar': {'ENCUT': 520, 'ISMEAR': 0}}}
```

---

## VASP AIMD Parameters

Required in `aimd_stages`:
- `TEBEG`: Initial temperature (K)
- `NSW`: Number of MD steps

Optional (defaults apply):
- `TEEND`: Final temperature (defaults to TEBEG)
- `POTIM`: Time step (fs)
- `MDALGO`: Thermostat algorithm (2 = Nosé-Hoover)
- `SMASS`: Nosé mass parameter

The module automatically sets `IBRION=0` (MD mode) in all AIMD calculations.
