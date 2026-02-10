# AGENTS.md

This file provides guidance to any coding agent when working with code in this repository.

## Quick Reference

```bash
# Environment setup
source ~/envs/aiida/bin/activate
pip install -e /home/trevizam/git/quantum-lego  # Editable install
verdi profile set-default presto
verdi daemon restart  # CRITICAL: after any code changes

# Testing (three tiers)
cd /home/trevizam/git/quantum-lego
pytest tests/ -m tier1 -v                     # Tier1: Pure Python tests (fast, no AiiDA)
pytest tests/ -m tier2 -v                     # Tier2: AiiDA integration (no VASP, ~20s)
pytest tests/ -m tier3 -v                     # Tier3: Real VASP results (requires pre-computed PKs)
pytest tests/ -v                              # Run all tests (498 tests)

# Linting
flake8 quantum_lego/ --max-line-length=120 --ignore=E501,W503,E402,F401
flake8 tests/ --max-line-length=120 --ignore=E501,W503,E402,F401

# Workflow monitoring
verdi process show <PK>                       # Show workflow status
verdi process report <PK>                     # Detailed hierarchy
verdi daemon logshow                          # Debug daemon issues
```

## Overview

**Quantum Lego** provides modular, brick-based building blocks for composing AiiDA computational workflows. It supports VASP, Quantum ESPRESSO, and CP2K through a unified stage/brick abstraction.

**Technology Stack:** AiiDA (workflow/provenance), AiiDA-WorkGraph (task composition), AiiDA-VASP (DFT), Pymatgen (structures), ASE (I/O)

**Key Dependencies:**
- **aiida-workgraph==1.0.0b3**: Pinned to beta version 1.0.0b3. Will be updated to stable 1.0 release when available.
- **Python >=3.9**: Compatible with aiida-workgraph 1.0.0b3 requirement (>=3.9,<3.14)

**Design Philosophy:**
- **Incremental**: Run one calculation at a time, inspect, decide next step
- **No presets**: Always specify parameters manually for maximum flexibility
- **Modular bricks**: Composable stage types with typed port connections
- **Fail early**: `validate_connections()` catches wiring errors before submission

## Package Structure

```
quantum-lego/                    # Git repository root
├── AGENTS.md                     # This file
├── README.md                     # API documentation
├── pyproject.toml                # Package metadata (name: quantum_lego)
├── quantum_lego/                 # Python package root
│   ├── __init__.py               # Re-exports from core
│   └── core/
│       ├── __init__.py           # Public API: quick_vasp, get_results, etc.
│       ├── workgraph.py          # WorkGraph builders (~2000 lines)
│       ├── tasks.py              # @task.calcfunction helpers
│       ├── results.py            # Result extraction functions
│       ├── utils.py              # Status, restart, file handling
│       ├── retrieve_defaults.py  # Default VASP retrieve file lists
│       ├── bricks/               # Brick modules (stage types)
│       │   ├── __init__.py       # BRICK_REGISTRY (13 types)
│       │   ├── connections.py    # PORTS declarations + validation (pure Python)
│       │   ├── vasp.py           # VASP brick (relaxation, SCF, etc.)
│       │   ├── dos.py            # DOS brick (BandsWorkChain wrapper)
│       │   ├── batch.py          # Batch brick (parallel VASP with varying params)
│       │   ├── bader.py          # Bader brick (charge analysis)
│       │   ├── convergence.py    # Convergence brick (ENCUT/k-points testing)
│       │   ├── thickness.py      # Thickness brick (slab thickness convergence)
│       │   ├── hubbard_response.py # Hubbard U response calculations
│       │   ├── hubbard_analysis.py # Hubbard U regression and summary
│       │   ├── aimd.py           # Ab initio molecular dynamics
│       │   ├── qe.py             # Quantum ESPRESSO (PwBaseWorkChain)
│       │   ├── cp2k.py           # CP2K (Cp2kBaseWorkChain)
│       │   ├── generate_neb_images.py # NEB image interpolation/generation
│       │   └── neb.py            # NEB workflow (vasp.neb)
│       ├── calcs/                # Custom AiiDA calculation plugins
│       │   ├── __init__.py
│       │   └── aimd_vasp.py      # AIMD VASP calculation with velocity injection
│       └── common/               # Shared utilities (extracted from PS-TEROS)
│           ├── utils.py          # deep_merge_dicts, get_logger, helpers
│           ├── constants.py      # Physical constants
│           ├── fixed_atoms.py    # Selective dynamics (atom fixing)
│           ├── aimd_functions.py # AIMD helper functions
│           ├── aimd/             # AIMD submodule
│           ├── convergence/      # Convergence submodule
│           └── u_calculation/    # Hubbard U calculation submodule
├── tests/                        # Test suite (498 tests)
│   ├── conftest.py               # Pytest config, fixtures, markers
│   ├── test_lego_connections.py  # Port/connection validation (tier1)
│   ├── test_lego_bricks.py       # Brick validate_stage() (tier1)
│   ├── test_lego_concurrent_and_outputs.py  # Output naming (tier1)
│   ├── test_lego_results.py      # print_stage_results() (tier1)
│   ├── test_lego_validation.py   # _validate_stages() (tier1)
│   ├── test_lego_vasp_integration.py     # VASP brick (tier2/3)
│   ├── test_lego_dos_integration.py      # DOS brick (tier2/3)
│   ├── test_lego_batch_integration.py    # Batch brick (tier2/3)
│   ├── test_lego_aimd_integration.py     # AIMD brick (tier2/3)
│   ├── test_lego_aimd_trajectory_concatenation.py  # AIMD concat (tier2)
│   ├── test_lego_sequential_integration.py  # Sequential (tier2/3)
│   └── fixtures/
│       ├── lego_reference_pks.json       # Tier3 reference PKs
│       ├── lego_reference_pks.json.template
│       └── structures/                   # Test structure files (.vasp)
└── examples/                     # Example scripts
    ├── run_dos.py
    ├── run_batch_dos.py
    ├── run_two_structures.py
    ├── check_results.py
    ├── aimd/
    ├── bader/
    ├── convergence/
    ├── cp2k/
    ├── hubbard_u/
    ├── neb/
    ├── qe/
    ├── sno2_explorer/
    └── thickness/
```

## Core API

### Quick Functions

```python
from quantum_lego import (
    quick_vasp,              # Single VASP calculation
    quick_vasp_batch,        # Multiple parallel VASP calcs
    quick_vasp_sequential,   # Multi-stage pipeline
    quick_dos,               # DOS calculation (SCF + DOS)
    quick_dos_batch,         # Multiple parallel DOS calcs
    quick_hubbard_u,         # Hubbard U calculation
    quick_aimd,              # AIMD simulation
    quick_qe,                # QE pw.x calculation
    quick_qe_sequential,     # Multi-stage QE pipeline
    get_results,             # Extract results from single calc
    get_energy,              # Quick energy extraction
    get_status,              # Check calculation status
    print_sequential_results,# Print multi-stage results
)
```

### Brick System

Each brick module in `bricks/` exports a `PORTS` dict plus 5 functions:

```python
PORTS                    # From connections.py (port declarations)
validate_stage()         # Brick-specific config validation
create_stage_tasks()     # Build WorkGraph tasks
expose_stage_outputs()   # Wire up WorkGraph outputs
get_stage_results()      # Extract results from completed WorkGraph
print_stage_results()    # Format results for display
```

### Available Brick Types (13)

| Type | Module | Description |
|------|--------|-------------|
| `vasp` | `bricks/vasp.py` | Standard VASP calculation (relax, static SCF) |
| `dos` | `bricks/dos.py` | Density of states via BandsWorkChain |
| `batch` | `bricks/batch.py` | Parallel VASP runs with varying parameters |
| `bader` | `bricks/bader.py` | Bader charge analysis |
| `convergence` | `bricks/convergence.py` | ENCUT and k-points convergence testing |
| `thickness` | `bricks/thickness.py` | Slab thickness convergence testing |
| `hubbard_response` | `bricks/hubbard_response.py` | Hubbard U response calculations |
| `hubbard_analysis` | `bricks/hubbard_analysis.py` | Hubbard U regression and summary |
| `aimd` | `bricks/aimd.py` | Ab initio molecular dynamics (IBRION=0) |
| `qe` | `bricks/qe.py` | Quantum ESPRESSO pw.x calculations |
| `cp2k` | `bricks/cp2k.py` | CP2K calculations |
| `generate_neb_images` | `bricks/generate_neb_images.py` | NEB image generation |
| `neb` | `bricks/neb.py` | NEB calculation via vasp.neb |

### Port System (`connections.py`)

Pure Python module (no AiiDA dependency) declaring typed inputs/outputs for each brick.

**Port types:** `structure`, `energy`, `misc`, `remote_folder`, `retrieved`, `dos_data`, `projectors`, `bader_charges`, `trajectory`, `convergence`, `file`, `hubbard_responses`, `hubbard_occupation`, `hubbard_result`, `neb_images`

**Source resolution modes:** `auto`, `structure_from`, `charge_from`, `restart`, `ground_state_from`, `response_from`, and explicit stage-level `structure` overrides (for bricks that support it, e.g., `vasp`, `dos`)

### Sequential Workflows

```python
from quantum_lego import quick_vasp_sequential

stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {'encut': 520, 'ibrion': 2, 'nsw': 100, 'isif': 3},
        'restart': None,
    },
    {
        'name': 'scf',
        'type': 'vasp',
        'structure_from': 'relax',
        'incar': {'encut': 520, 'nsw': 0, 'lwave': True, 'lcharg': True},
        'restart': None,
    },
    {
        'name': 'dos_calc',
        'type': 'dos',
        'structure_from': 'relax',
        'scf_incar': {'encut': 520, 'ediff': 1e-6},
        'dos_incar': {'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    },
    {
        'name': 'dos_external',
        'type': 'dos',
        'structure': other_structure,  # explicit StructureData/PK
        'scf_incar': {'encut': 520, 'ediff': 1e-6},
        'dos_incar': {'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    },
]

result = quick_vasp_sequential(structure, code_label, stages=stages, ...)
```

For DOS stages, provide exactly one of `structure_from` or `structure`.
`max_concurrent_jobs` limits concurrent jobs across the entire WorkGraph,
including independent DOS branches with explicit `structure`.
Reference example: `examples/vasp/run_mixed_dos_sources.py`.

## Testing

### Three-Tier Strategy

| Tier | Count | Speed | Requires | Tests |
|------|-------|-------|----------|-------|
| tier1 | 420 | ~3s | Nothing (pure Python) | Port types, connections, validation, parsing |
| tier2 | 48 | ~20s | AiiDA profile | WorkGraph construction, calcfunctions, mock nodes |
| tier3 | 30 | ~5s | Pre-computed VASP PKs | Result extraction against real VASP outputs |

**Important:** Tier2 tests create real AiiDA processes in the database (viewable via `verdi process list`). Some tests intentionally create failing processes to test error handling (e.g., `test_extract_energy_missing` creates WorkGraphs with exit code 302). These failures are **expected** - the test asserts `wg.tasks['task_name'].state == 'FAILED'` to verify error paths work correctly. All tier2 tests pass (48/48) even though some create "failed" database processes.

### Running Tests

```bash
pytest tests/ -m tier1 -v          # Fast, always runs
pytest tests/ -m tier2 -v          # AiiDA integration (creates DB processes)
pytest tests/ -m tier3 -v          # End-to-end (needs reference PKs)
pytest tests/ -v                   # All 498 tests
```

### Test Markers

```python
@pytest.mark.tier1              # Pure Python tests
@pytest.mark.tier2              # AiiDA integration (no VASP)
@pytest.mark.tier3              # End-to-end with VASP results
@pytest.mark.requires_aiida     # Skip if AiiDA not configured
```

### Tier3 Reference PKs

Stored in `tests/fixtures/lego_reference_pks.json`. Current coverage:
- **vasp**: relax_si, scf_sno2
- **dos**: dos_sno2
- **batch**: batch_si_encut
- **aimd**: aimd_si
- **sequential**: relax_then_scf_si

### Development Workflow

```bash
# After code changes:
verdi daemon restart                          # CRITICAL!
pytest tests/test_lego_connections.py -m tier1 -v  # Validate logic
pytest tests/ -m tier2 -v                     # Integration
pytest tests/ -m tier3 -v                     # End-to-end
```

### Cleaning Up Test Processes

Tier2 tests create AiiDA process nodes that persist in the database. To clean up:

```bash
# List recent test processes
verdi process list -a -p 1 | grep "WorkGraph<test_"

# Count processes by exit code
verdi process list -a -p 1 | grep "Finished \[302\]" | wc -l  # Expected failures
verdi process list -a -p 1 | grep "Finished \[0\]" | wc -l    # Successes

# Delete specific process (use with caution)
# verdi process delete <PK>

# For bulk cleanup, consider using a separate test AiiDA profile
# verdi profile setup --non-interactive --email test@example.com test_profile
# verdi profile setdefault test_profile
# pytest tests/ -m tier2 -v
# verdi profile delete test_profile  # Clean slate
```

## Adding a New Brick

1. **Declare ports** in `connections.py` (pure Python, no AiiDA): add `MYBRICK_PORTS` dict and register in `ALL_PORTS`
2. **Write tier1 tests** in `test_lego_connections.py` for ports and validation
3. **Create brick module** `bricks/mybrick.py` with 5 functions + `PORTS` import
4. **Register** in `BRICK_REGISTRY` in `bricks/__init__.py`
5. **Add example script** in `examples/`
6. **Run tests and lint:**
   ```bash
   pytest tests/test_lego_connections.py -m tier1 -v
   pytest tests/test_lego_bricks.py -m tier1 -v
   flake8 quantum_lego/core/bricks/ --max-line-length=120 --ignore=E501,W503,E402,F401
   ```

## Cluster Configuration

### localwork (development)
```python
code_label = 'VASP-6.5.1@localwork'
options = {
    'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8},
}
potential_family = 'PBE'
# max_concurrent_jobs = 1  # localwork runs ONE job at a time
```

### Obelix (production)
```python
code_label = 'VASP-6.5.1-idefix-4@obelix'
options = {
    'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 4},
    'custom_scheduler_commands': '''#PBS -l cput=90000:00:00
#PBS -l nodes=1:ppn=88:skylake
#PBS -j oe
#PBS -N MyJobName''',
}
potential_family = 'PBE'
```

## Code Style

- **Import order:** stdlib → aiida → aiida_workgraph → third-party → quantum_lego
- **Logger:** `from quantum_lego.core.common.utils import get_logger`
- **Docstrings:** Google style with Args, Returns, Example sections
- **Line length:** 120 characters max
- **Package imports:** Always use `quantum_lego.core.bricks...` (never `teros`)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: quantum_lego` | `pip install -e /path/to/quantum-lego` |
| Code changes not taking effect | `verdi daemon restart` |
| Process stuck in Waiting | `verdi process report <PK>` |
| VASP calculation failed | `verdi calcjob outputcat <PK>` |
| Tier3 tests all skip | Check `tests/fixtures/lego_reference_pks.json` has valid PKs |
