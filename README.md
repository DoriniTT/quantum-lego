# Quantum Lego

Lightweight, incremental VASP calculation module for exploratory work.

📚 **[Brick Connection Guide](docs/BRICK_CONNECTIONS.md)** - Visual guide showing how all 13 brick types connect together like Lego pieces

## Design Philosophy

- **Incremental**: Run one calculation at a time, inspect, decide what's next
- **Minimal provenance**: Track via PKs manually, no complex dependency graphs
- **Specific file retrieval**: Standard VASP files are always retrieved; add extras as needed
- **Non-blocking default**: Submit and return immediately
- **No presets**: Always specify INCAR manually for maximum flexibility

## Quick Start

Standard VASP files always retrieved:
`INCAR`, `KPOINTS`, `POTCAR`, `POSCAR`, `CONTCAR`, `OUTCAR`, `vasprun.xml`, `OSZICAR`.

```python
from quantum_lego import quick_vasp, get_results, get_status

# Single calculation
pk = quick_vasp(
    structure=sno2_110,
    code_label='VASP-6.5.1@localwork',
    incar={'NSW': 100, 'IBRION': 2},
    kpoints_spacing=0.03,
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
    retrieve=['CHGCAR'],  # Extras (standard VASP files are always retrieved)
    name='sno2_relax',
)

# Check status
get_status(pk)  # -> 'waiting', 'running', 'finished', 'failed', 'excepted'

# Get results
results = get_results(pk)
print(f"Energy: {results['energy']:.4f} eV")
```

## API Reference

### Core Functions

#### `quick_vasp()`

Submit a single VASP calculation with minimal boilerplate.

```python
pk = quick_vasp(
    structure=structure,           # StructureData or PK
    code_label='VASP-6.5.1@...',   # VASP code label
    incar={'NSW': 100, ...},       # INCAR parameters (required)
    kpoints_spacing=0.03,          # K-points spacing (A^-1)
    potential_family='PBE',        # POTCAR family
    potential_mapping={'Sn': 'Sn_d'},
    options={'resources': {...}},   # Scheduler options (required)
    retrieve=['CHGCAR'],            # Extra files to retrieve (merged with defaults)
    restart_from=None,              # PK to restart from
    copy_wavecar=True,              # Copy WAVECAR on restart
    copy_chgcar=False,              # Copy CHGCAR on restart
    name='my_calc',                 # WorkGraph name
    wait=False,                     # Block until finished
)
```

#### `quick_vasp_batch()`

Submit multiple VASP calculations with per-structure INCAR overrides.

```python
pks = quick_vasp_batch(
    structures={'clean': s1, 'defect': s2},
    code_label='VASP-6.5.1@...',
    incar={'NSW': 100},            # Base INCAR
    incar_overrides={              # Per-structure overrides
        'defect': {'NELECT': 191.95},
    },
    max_concurrent_jobs=4,         # Limit parallel jobs
    retrieve=['CHGCAR'],  # Extra files to retrieve (merged with defaults)
    name='batch_calc',
)
```

#### `quick_dos()`

Submit a DOS calculation using the BandsWorkChain (SCF + DOS internally).

```python
# Note: AiiDA-VASP requires lowercase INCAR keys
pk = quick_dos(
    structure=structure,           # StructureData or PK
    code_label='VASP-6.5.1@...',   # VASP code label
    scf_incar={'encut': 400, 'ediff': 1e-6, 'ismear': 0},  # SCF parameters
    dos_incar={'nedos': 2000, 'lorbit': 11, 'ismear': -5}, # DOS parameters
    kpoints_spacing=0.03,          # K-points for SCF (A^-1)
    dos_kpoints_spacing=0.02,      # K-points for DOS (denser)
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={'resources': {...}},
    retrieve=['DOSCAR'],           # Extra files to retrieve (merged with defaults)
    name='sno2_dos',
)
```

**Forced INCAR parameters (lowercase):**
- SCF: `lwave=True`, `lcharg=True` (outputs wavefunctions and charge_density)
- DOS: `icharg=11`, `istart=1` (non-SCF from existing charge/wavefunction)

#### `quick_vasp_sequential()`

Submit a multi-stage WorkGraph where dependencies are defined per stage.

For DOS stages, you can now provide the structure source in two ways:
- `structure_from='relax_stage_name'` (from a previous stage), or
- `structure=<StructureData|PK>` (explicit structure for that stage).

Exactly one of `structure_from` or `structure` must be provided in DOS stages.

```python
from quantum_lego import quick_vasp_sequential

stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {'nsw': 100, 'ibrion': 2, 'isif': 2, 'encut': 520},
        'restart': None,
    },
    {
        'name': 'dos_relaxed',
        'type': 'dos',
        'structure_from': 'relax',  # from previous stage
        'scf_incar': {'encut': 520, 'ediff': 1e-6},
        'dos_incar': {'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    },
    {
        'name': 'dos_alt_structure',
        'type': 'dos',
        'structure': alt_structure,  # explicit StructureData
        'scf_incar': {'encut': 520, 'ediff': 1e-6},
        'dos_incar': {'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    },
]

result = quick_vasp_sequential(
    structure=initial_structure,   # seed structure for stage 1 / 'input'
    stages=stages,
    code_label='VASP-6.5.1@localwork',
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
    max_concurrent_jobs=2,         # global cap inside this WorkGraph
    name='mixed_structure_dos',
)
```

See `examples/04_sequential/mixed_dos_sources.py` for a runnable version.

### Result Functions

#### `get_results(pk)`

Extract results from a completed calculation.

```python
results = get_results(pk)
# results['energy']     -> float (eV)
# results['structure']  -> StructureData (relaxed, if NSW > 0)
# results['misc']       -> dict (parsed VASP outputs)
# results['files']      -> FolderData (retrieved files)
```

#### `get_energy(pk)`

Quick shortcut to get just the energy.

```python
energy = get_energy(pk)  # -> float (eV)
```

#### `get_batch_results(pks)`

Extract results from multiple calculations.

```python
results = get_batch_results({'clean': pk1, 'defect': pk2})
# -> {'clean': {...}, 'defect': {...}}
```

#### `get_batch_energies(pks)`

Quick shortcut to get energies from multiple calculations.

```python
energies = get_batch_energies({'clean': pk1, 'defect': pk2})
# -> {'clean': -123.45, 'defect': -234.56}
```

#### `get_dos_results(pk)`

Extract results from a completed `quick_dos` calculation.

```python
results = get_dos_results(pk)
# results['energy']    -> float (SCF energy, eV)
# results['structure'] -> StructureData (input structure)
# results['scf_misc']  -> dict (SCF VASP outputs)
# results['dos_misc']  -> dict (DOS VASP outputs)
# results['files']     -> FolderData (retrieved files, e.g., DOSCAR)
```

#### `print_dos_results(pk)`

Print a formatted summary of DOS calculation results.

```python
print_dos_results(pk)
# DOS Calculation PK 12345
#   Status: finished
#   SCF Energy: -832.636575 eV
#   Structure: Sn2O4 (PK: 12346)
#   DOS run status: finished
#   Retrieved files: DOSCAR
```

### Utility Functions

#### `get_status(pk)`

Get the status of a calculation.

```python
status = get_status(pk)
# -> 'waiting', 'running', 'finished', 'failed', 'excepted', 'killed'
```

#### `export_files(pk, output_dir, files)`

Export retrieved files to a local directory.

```python
exported = export_files(pk, output_dir='./results/', files=['CHGCAR', 'DOSCAR'])
# -> ['./results/CHGCAR', './results/DOSCAR']
```

#### `list_calculations(name_pattern, limit)`

List lego calculations, optionally filtered by name.

```python
calcs = list_calculations(name_pattern='sno2*', limit=20)
# -> [{'pk': 123, 'label': 'sno2_relax', 'state': 'finished', 'ctime': '...'}, ...]
```

#### `get_restart_info(pk)`

Extract restart information from a previous calculation.

```python
info = get_restart_info(pk)
# info['structure']     -> StructureData
# info['remote_folder'] -> RemoteData (for WAVECAR restart)
```

## Restart Workflow

```python
# 1. Relaxation
pk1 = quick_vasp(
    structure=initial_structure,
    incar={'NSW': 100, 'IBRION': 2, 'ISIF': 3},
    retrieve=['CONTCAR'],
    name='sno2_relax',
)

# Wait for completion...

# 2. DOS from relaxed structure (with WAVECAR restart)
pk2 = quick_vasp(
    restart_from=pk1,              # Auto-loads relaxed structure + WAVECAR
    incar={'NSW': 0, 'NEDOS': 2000, 'LORBIT': 11},
    retrieve=['DOSCAR', 'EIGENVAL'],
    name='sno2_dos',
)
```

## DOS Calculation (quick_dos)

For DOS calculations, `quick_dos` provides a simpler interface that handles
the SCF → DOS chain automatically via the BandsWorkChain:

```python
from quantum_lego import quick_dos, get_dos_results, print_dos_results

# Submit DOS calculation
# Note: AiiDA-VASP requires lowercase INCAR keys
pk = quick_dos(
    structure=my_structure,
    code_label='VASP-6.5.1@localwork',
    scf_incar={
        'encut': 400,
        'ediff': 1e-6,
        'ismear': 0,
        'sigma': 0.05,
    },
    dos_incar={
        'nedos': 2000,
        'lorbit': 11,
        'ismear': -5,  # Tetrahedron method
    },
    kpoints_spacing=0.03,
    dos_kpoints_spacing=0.02,  # Denser k-mesh for DOS
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
    retrieve=['DOSCAR'],
    name='sno2_dos',
)

# Wait for completion, then get results
results = get_dos_results(pk)
print(f"Energy: {results['energy']:.4f} eV")
print(f"Files: {results['files'].list_object_names()}")

# Or use the formatted printer
print_dos_results(pk)
```

## Fukui-Style Batch Example

```python
from quantum_lego import quick_vasp_batch, get_batch_results_from_workgraph

# Run Fukui+ interpolation: 4 charge states
delta_values = [0.0, 0.05, 0.10, 0.15]
N_neutral = 192  # Calculate from POTCAR

structures = {f'delta_{d:.2f}': structure for d in delta_values}
incar_overrides = {
    f'delta_{d:.2f}': {'NELECT': N_neutral - d}
    for d in delta_values if d > 0
}

result = quick_vasp_batch(
    structures=structures,
    code_label='VASP-6.5.1@localwork',
    incar={'NSW': 0, 'ALGO': 'All'},
    incar_overrides=incar_overrides,
    retrieve=['CHGCAR'],
    max_concurrent_jobs=1,
    name='fukui_plus',
)

# Later: collect results
results = get_batch_results_from_workgraph(result)
for key, r in results.items():
    print(f"{key}: E = {r['energy']:.4f} eV")
```

## Sequential NEB Stages

`quick_vasp_sequential` now supports two NEB-focused stage types:

- `generate_neb_images`: generate intermediate images from two relaxed VASP endpoints
- `neb`: run `vasp.neb` using either generated images (`images_from`) or folder images (`images_dir`)

Minimal pattern:

```python
from quantum_lego import quick_vasp_sequential

stages = [
    {'name': 'relax_initial', 'type': 'vasp', 'structure': initial, 'incar': relax_incar, 'restart': None},
    {'name': 'relax_final', 'type': 'vasp', 'structure': final, 'incar': relax_incar, 'restart': None},
    {
        'name': 'make_images',
        'type': 'generate_neb_images',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'n_images': 5,
    },
    {
        'name': 'neb_stage_1',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',  # xor images_dir
        'incar': {'ibrion': 3, 'nsw': 120, 'iopt': 3, 'spring': -5},
        'restart': None,
    },
    {
        'name': 'neb_stage_2_ci',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',
        'incar': {'ibrion': 3, 'nsw': 120, 'iopt': 3, 'spring': -5, 'lclimb': True},
        'restart': 'neb_stage_1',
    },
]

result = quick_vasp_sequential(structure=initial, stages=stages, ...)
```

## Module Structure

```
quantum_lego/core/
├── __init__.py      # Public API exports
├── workgraph.py     # Main WorkGraph builders (thin dispatcher)
├── tasks.py         # @task.calcfunction helpers
├── utils.py         # Status, restart, file handling
├── results.py       # Result extraction (thin dispatcher)
├── retrieve_defaults.py # Default VASP retrieve file lists
├── bricks/          # Stage type modules
│   ├── __init__.py  # Brick registry + shared helpers
│   ├── connections.py # PORTS/connection validation (pure Python)
│   ├── vasp.py      # VASP brick
│   ├── dos.py       # DOS brick
│   ├── batch.py     # Batch brick
│   ├── bader.py     # Bader brick
│   ├── convergence.py # Convergence brick
│   ├── thickness.py # Thickness brick
│   ├── hubbard_response.py # Hubbard response brick
│   ├── hubbard_analysis.py # Hubbard analysis brick
│   ├── aimd.py      # AIMD brick
│   ├── qe.py        # QE brick
│   ├── cp2k.py      # CP2K brick
│   ├── generate_neb_images.py # NEB image generator brick
│   └── neb.py       # vasp.neb brick
├── calcs/           # Custom AiiDA calculation plugins
│   └── aimd_vasp.py # AIMD VASP with velocity injection
└── common/          # Shared utilities
    ├── utils.py     # deep_merge_dicts, logging, helpers
    ├── constants.py # Physical constants
    ├── fixed_atoms.py # Selective dynamics
    ├── aimd/        # AIMD submodule
    ├── convergence/ # Convergence submodule
    └── u_calculation/ # Hubbard U submodule
```

## Files to Retrieve

Common VASP output files to retrieve:

| File | Purpose |
|------|---------|
| `CONTCAR` | Relaxed structure |
| `CHGCAR` | Charge density (for Fukui, restart) |
| `WAVECAR` | Wavefunctions (for restart, bands) |
| `DOSCAR` | Density of states |
| `EIGENVAL` | Eigenvalues |
| `OUTCAR` | Full output log |
| `PROCAR` | Projected DOS/bands |
| `LOCPOT` | Local potential |

Note: WAVECAR and CHGCAR are automatically used for restart via `restart.folder` -
you don't need to retrieve them explicitly for restart functionality.
