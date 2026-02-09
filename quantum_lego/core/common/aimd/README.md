# AIMD Standalone Module

Standalone AIMD functionality for PS-TEROS with full control over multi-stage molecular dynamics calculations.

## Overview

This module provides a simplified API for running Ab Initio Molecular Dynamics (AIMD) calculations on pre-existing structures, independent of the main bulk+slab workflow. It supports:

- **Direct structure input**: Pass StructureData nodes or PKs directly
- **Sequential multi-stage AIMD**: Automatic restart chaining between stages
- **Optional supercell transformations**: Create supercells before AIMD starts
- **Concurrency control**: Limit parallel VASP calculations with `max_concurrent_jobs`
- **Parallel execution**: All structures run in parallel within each stage

## Quick Start

```python
from quantum_lego.core.common.aimd import build_aimd_workgraph
from aiida import orm, load_profile
from ase.io import read

load_profile('presto')

# Load structures
structure1 = orm.StructureData(ase=read('structure1.cif'))
structure2 = orm.StructureData(ase=read('structure2.cif'))

# Define AIMD stages (sequential) using VASP-native parameter names
aimd_stages = [
    {'TEBEG': 300, 'NSW': 50},   # Equilibration
    {'TEBEG': 300, 'NSW': 200},  # Production
]

# Builder inputs (VASP parameters)
builder_inputs = {
    'parameters': {
        'incar': {
            'PREC': 'Normal',
            'ENCUT': 400,
            'EDIFF': 1e-5,
            'ISMEAR': 0,
            'SIGMA': 0.05,
            'IBRION': 0,  # MD
            'MDALGO': 2,  # Nosé-Hoover
            'POTIM': 2.0, # Time step (fs)
        }
    },
    'kpoints_spacing': 0.5,
    'potential_family': 'PBE',
    'potential_mapping': {'Ag': 'Ag', 'O': 'O'},
    'options': {
        'resources': {
            'num_machines': 1,
            'num_cores_per_machine': 24,
        },
    },
    'clean_workdir': False,
}

# Build workgraph
wg = build_aimd_workgraph(
    structures={'struct1': structure1, 'struct2': structure2},
    aimd_stages=aimd_stages,
    code_label='VASP6.5.0@cluster02',
    builder_inputs=builder_inputs,

    # Optional: create supercell for struct1
    supercell_specs={'struct1': [2, 2, 1]},

    # Optional: limit concurrency
    max_concurrent_jobs=2,

    name='MyAIMD_Workflow',
)

# Submit
wg.submit(wait=False)
print(f"WorkGraph PK: {wg.pk}")
```

## API Reference

### Main Function

```python
def build_aimd_workgraph(
    structures: dict[str, orm.StructureData | int],
    aimd_stages: list[dict],
    code_label: str,
    builder_inputs: dict,
    supercell_specs: dict[str, list[int]] = None,
    structure_overrides: dict[str, dict] = None,
    stage_overrides: dict[int, dict] = None,
    matrix_overrides: dict[tuple, dict] = None,
    max_concurrent_jobs: int = None,
    name: str = 'AIMDWorkGraph',
) -> WorkGraph
```

#### Parameters

**structures** : `dict[str, orm.StructureData | int]`
- Input structures for AIMD
- Format: `{name: StructureData_node}` or `{name: PK}`
- Example: `{'slab1': structure, 'slab2': 12345}`

**aimd_stages** : `list[dict]`
- Sequential AIMD stages using VASP-native parameter names
- Required parameters: `TEBEG` (initial temperature K), `NSW` (MD steps)
- Optional parameters: `TEEND` (final temperature, defaults to TEBEG), `POTIM` (timestep fs), `MDALGO` (thermostat), `SMASS` (Nosé mass)
- Example: `[{'TEBEG': 300, 'NSW': 100}, {'TEBEG': 400, 'NSW': 200}]`
- Temperature annealing: `[{'TEBEG': 300, 'TEEND': 500, 'NSW': 200}]`

**code_label** : `str`
- VASP code label from AiiDA
- Format: `'CodeName@ComputerName'`
- Example: `'VASP6.5.0@cluster02'`

**builder_inputs** : `dict`
- Default VASP builder configuration used for all (structure, stage) combinations
- Required keys:
  - `parameters`: `{'incar': {...}}` - VASP INCAR settings
  - `kpoints_spacing`: `float` - K-points spacing
  - `potential_family`: `str` - Pseudopotential family
  - `potential_mapping`: `dict` - Element to potential mapping
  - `options`: `dict` - Scheduler options
  - `clean_workdir`: `bool` - Whether to clean work directory

**supercell_specs** : `dict[str, list[int]]`, optional
- Supercell transformations to apply before AIMD
- Format: `{structure_name: [nx, ny, nz]}`
- Example: `{'slab1': [2, 2, 1]}` creates 2x2x1 supercell for slab1
- Applied once before first AIMD stage

**structure_overrides** : `dict[str, dict]`, optional
- Override builder_inputs per structure (all stages)
- Format: `{structure_name: {'parameters': {'incar': {...}}}}`
- Example: `{'slab2': {'parameters': {'incar': {'ENCUT': 500}}}}`
- See Override System section below

**stage_overrides** : `dict[int, dict]`, optional
- Override builder_inputs per stage (all structures)
- Format: `{stage_idx: {'parameters': {'incar': {...}}}}`
- Example: `{1: {'parameters': {'incar': {'EDIFF': 1e-7}}}}`
- See Override System section below

**matrix_overrides** : `dict[tuple, dict]`, optional
- Override builder_inputs for specific (structure, stage) combinations
- Format: `{(structure_name, stage_idx): {'parameters': {'incar': {...}}}}`
- Example: `{('slab1', 1): {'parameters': {'incar': {'ALGO': 'All'}}}}`
- See Override System section below

**max_concurrent_jobs** : `int`, optional
- Maximum number of concurrent VASP calculations
- Default: `None` (unlimited within WorkGraph limits)
- Example: `max_concurrent_jobs=4` limits to 4 parallel jobs

**name** : `str`, optional
- WorkGraph name for identification
- Default: `'AIMDWorkGraph'`

#### Returns

**WorkGraph**
- AiiDA WorkGraph ready to submit
- Submit with: `wg.submit(wait=False)`

### Output Structure

Results are accessible through the WorkGraph node after completion:

```python
wg_node = orm.load_node(wg.pk)

# Access individual stage outputs
stage_0_structures = wg_node.outputs.stage_0_structures
stage_0_energies = wg_node.outputs.stage_0_energies
stage_1_structures = wg_node.outputs.stage_1_structures

# Access supercells (if created)
supercell_struct1 = wg_node.outputs.supercell_struct1
```

## Override System

The override parameters (`structure_overrides`, `stage_overrides`, `matrix_overrides`)
support **INCAR parameter customization**.

### Supported Parameters

Any VASP INCAR tag can be overridden:
- `ENCUT`, `PREC`, `EDIFF`, `EDIFFG`
- `ALGO`, `ISIF`, `IBRION`
- `NCORE`, `KPAR`, `LREAL`
- Any other INCAR setting

### Not Supported

These builder inputs remain uniform across all structures:
- `kpoints_spacing` - K-points grid density
- `options` - Scheduler settings (num_cores, walltime, etc.)
- `potential_mapping` - Element to pseudopotential mapping
- `potential_family` - Pseudopotential family name

**Workaround:** Use separate `build_aimd_workgraph()` calls for structures needing different kpoints/options.

### Priority Order

When multiple override levels are specified:
1. **Matrix overrides** (highest): `{(structure_name, stage_idx): {...}}`
2. **Stage overrides**: `{stage_idx: {...}}`
3. **Structure overrides**: `{structure_name: {...}}`
4. **Base parameters** (lowest): `builder_inputs['parameters']['incar']`

### Example

```python
wg = build_aimd_workgraph(
    structures={'slab1': s1, 'slab2': s2},
    aimd_stages=[
        {'TEBEG': 300, 'NSW': 100},
        {'TEBEG': 300, 'NSW': 500},
    ],
    code_label='VASP6.5.0@cluster02',
    builder_inputs={
        'parameters': {'incar': {'ENCUT': 400, 'PREC': 'Normal'}},  # Base
        # ... other parameters
    },

    # slab2 needs higher cutoff everywhere
    structure_overrides={
        'slab2': {'parameters': {'incar': {'ENCUT': 500}}}
    },

    # Stage 1 (production) needs tighter convergence
    stage_overrides={
        1: {'parameters': {'incar': {'EDIFF': 1e-7}}}
    },

    # slab1 + stage 1 needs special algorithm
    matrix_overrides={
        ('slab1', 1): {'parameters': {'incar': {'ALGO': 'All'}}}
    },
)
```

**Result:**
- slab1, stage 0: `ENCUT=400, PREC=Normal` (base)
- slab1, stage 1: `ENCUT=400, PREC=Normal, EDIFF=1e-7, ALGO=All` (stage + matrix)
- slab2, stage 0: `ENCUT=500, PREC=Normal` (structure override)
- slab2, stage 1: `ENCUT=500, PREC=Normal, EDIFF=1e-7` (structure + stage)

## Workflow Structure

The module creates the following task flow:

```
1. create_supercell_{name}  (if supercell_specs provided)
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
- Restart chaining: stage N+1 automatically uses stage N remote_folder

## Examples

### Basic: Single Structure, Two Stages

```python
wg = build_aimd_workgraph(
    structures={'my_slab': slab_structure},
    aimd_stages=[
        {'TEBEG': 300, 'NSW': 100},
        {'TEBEG': 300, 'NSW': 500},
    ],
    code_label='VASP6.5.0@cluster02',
    builder_inputs=base_config,
)
```

### With Supercell

```python
wg = build_aimd_workgraph(
    structures={'small_slab': structure},
    aimd_stages=[{'TEBEG': 300, 'NSW': 200}],
    code_label='VASP6.5.0@cluster02',
    builder_inputs=base_config,
    supercell_specs={'small_slab': [3, 3, 1]},  # Create 3x3x1 supercell
)
```

### Multiple Structures with Concurrency Limit

```python
wg = build_aimd_workgraph(
    structures={
        'slab1': structure1,
        'slab2': structure2,
        'slab3': structure3,
        'slab4': structure4,
    },
    aimd_stages=[{'TEBEG': 400, 'NSW': 300}],
    code_label='VASP6.5.0@cluster02',
    builder_inputs=base_config,
    max_concurrent_jobs=2,  # Only 2 VASP jobs run at once
)
```

## Monitoring

```bash
# Check overall status
verdi process show <PK>

# Check specific stage
verdi process show <stage_PK>

# View logs
verdi process report <PK>

# Monitor in real-time
verdi process watch <PK>
```

## Testing

Unit tests are located in `test_*.py` files:

```bash
pytest teros/core/aimd/test_utils.py -v      # Validation and merging utilities
pytest teros/core/aimd/test_tasks.py -v      # Supercell creation
pytest teros/core/aimd/test_overrides.py -v  # Override system and priority
```

Run all tests:

```bash
pytest teros/core/aimd/test_*.py -v
```

Full workflow demonstration:

```bash
python examples/vasp/step_18_aimd_standalone.py
```

## Module Structure

```
teros/core/aimd/
├── __init__.py           # Exports: build_aimd_workgraph, organize_aimd_results
├── workgraph.py          # Main entry: build_aimd_workgraph()
├── tasks.py              # WorkGraph tasks: create_supercell()
├── utils.py              # Validation and merging utilities
├── test_utils.py         # Unit tests for validation and merging
├── test_tasks.py         # Unit tests for supercell creation
├── test_overrides.py     # Unit tests for override system
└── README.md             # This file
```

## Relationship to Main Workflow

This module is **independent** from `teros.core.workgraph.build_core_workgraph()` but reuses the underlying `aimd_single_stage_scatter()` function from `teros.core.aimd_functions`.

**Choose this module when:**
- You have pre-existing structures (from any source)
- You want simple AIMD-only workflows
- You need full control over all parameters

**Choose main workflow when:**
- You want full bulk → slab → relaxation → AIMD pipeline
- You want workflow presets (`'aimd_only'`, `'surface_energy'`, etc.)

## Implementation Notes

- Reuses `aimd_single_stage_scatter()` from `teros.core.aimd_functions`
- Supercells created with pymatgen via ASE adapter
- WorkGraph handles task orchestration and restart chaining
- All AiiDA nodes stored in provenance graph

## See Also

- Design document: `docs/plans/2025-11-03-aimd-standalone-module-design.md`
- Implementation plan: `docs/plans/2025-11-03-aimd-standalone-module.md`
- Override implementation: `docs/plans/2025-11-03-aimd-override-implementation.md`
- Example script: `examples/vasp/step_18_aimd_standalone.py`
