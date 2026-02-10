# Brick Connection Guide

This guide visualizes how Quantum Lego bricks connect together like puzzle pieces to build complex computational workflows.

## Table of Contents

1. [Overview: All 13 Brick Types](#overview-all-13-brick-types)
2. [Port Type System](#port-type-system)
3. [Basic Sequential Patterns](#basic-sequential-patterns)
4. [Advanced Workflows](#advanced-workflows)
5. [Batch and Analysis Patterns](#batch-and-analysis-patterns)
6. [Multi-Code Workflows](#multi-code-workflows)
7. [Connection Rules](#connection-rules)

---

## Overview: All 13 Brick Types

```mermaid
graph TB
    subgraph "Computation Bricks (Structure Producers)"
        VASP[VASP<br/>Relax, SCF, Static]
        AIMD[AIMD<br/>Molecular Dynamics]
        QE[QE<br/>Quantum ESPRESSO]
        CP2K[CP2K<br/>CP2K Calculations]
        NEB[NEB<br/>Transition Paths]
    end

    subgraph "Computation Bricks (Non-Structure)"
        DOS[DOS<br/>Density of States]
        BATCH[BATCH<br/>Parallel Calculations]
    end

    subgraph "Analysis Bricks"
        BADER[BADER<br/>Charge Analysis]
        CONV[CONVERGENCE<br/>ENCUT & K-points]
        THICK[THICKNESS<br/>Slab Convergence]
        HUBB_R[HUBBARD_RESPONSE<br/>U Response Calcs]
        HUBB_A[HUBBARD_ANALYSIS<br/>U Regression]
        GEN_NEB[GENERATE_NEB_IMAGES<br/>NEB Image Generator]
    end

    style VASP fill:#4CAF50,stroke:#2E7D32,color:#fff
    style AIMD fill:#4CAF50,stroke:#2E7D32,color:#fff
    style QE fill:#4CAF50,stroke:#2E7D32,color:#fff
    style CP2K fill:#4CAF50,stroke:#2E7D32,color:#fff
    style NEB fill:#4CAF50,stroke:#2E7D32,color:#fff
    style DOS fill:#2196F3,stroke:#1565C0,color:#fff
    style BATCH fill:#2196F3,stroke:#1565C0,color:#fff
    style BADER fill:#FF9800,stroke:#E65100,color:#fff
    style CONV fill:#FF9800,stroke:#E65100,color:#fff
    style THICK fill:#FF9800,stroke:#E65100,color:#fff
    style HUBB_R fill:#FF9800,stroke:#E65100,color:#fff
    style HUBB_A fill:#FF9800,stroke:#E65100,color:#fff
    style GEN_NEB fill:#FF9800,stroke:#E65100,color:#fff
```

**Legend:**
- 🟢 **Green**: Computation bricks that produce structure outputs
- 🔵 **Blue**: Computation bricks without structure outputs
- 🟠 **Orange**: Analysis bricks

---

## Port Type System

The brick connection system uses 15 typed ports for data flow:

```mermaid
graph LR
    subgraph "Core Data Types"
        S[structure]
        E[energy]
        M[misc]
    end

    subgraph "Remote/Retrieved Data"
        RF[remote_folder]
        RET[retrieved]
    end

    subgraph "Specialized Data"
        DOS[dos_data]
        PROJ[projectors]
        TRAJ[trajectory]
        BC[bader_charges]
    end

    subgraph "Analysis Results"
        CONV[convergence]
        HR[hubbard_responses]
        HO[hubbard_occupation]
        HRES[hubbard_result]
    end

    subgraph "Utility Types"
        FILE[file]
        NEB_I[neb_images]
    end

    style S fill:#4CAF50,color:#fff
    style E fill:#FFC107,color:#000
    style M fill:#9E9E9E,color:#fff
    style RF fill:#3F51B5,color:#fff
    style RET fill:#3F51B5,color:#fff
    style DOS fill:#E91E63,color:#fff
    style PROJ fill:#E91E63,color:#fff
    style TRAJ fill:#00BCD4,color:#fff
    style BC fill:#FF5722,color:#fff
    style CONV fill:#8BC34A,color:#fff
    style HR fill:#9C27B0,color:#fff
    style HO fill:#9C27B0,color:#fff
    style HRES fill:#9C27B0,color:#fff
    style FILE fill:#607D8B,color:#fff
    style NEB_I fill:#795548,color:#fff
```

---

## Basic Sequential Patterns

### Pattern 1: VASP Relaxation Chain

```mermaid
graph LR
    INPUT[Initial Structure] -->|structure| RELAX[VASP Relax<br/>nsw=100]
    RELAX -->|structure| SCF[VASP SCF<br/>nsw=0]
    RELAX -->|remote_folder| SCF
    RELAX -->|structure| STATIC[VASP Static<br/>High precision]
    SCF -->|remote_folder<br/>WAVECAR/CHGCAR| STATIC

    RELAX -.->|energy| OUT1[Energy 1]
    SCF -.->|energy| OUT2[Energy 2]
    STATIC -.->|energy| OUT3[Energy 3]

    style RELAX fill:#4CAF50,stroke:#2E7D32,color:#fff
    style SCF fill:#4CAF50,stroke:#2E7D32,color:#fff
    style STATIC fill:#4CAF50,stroke:#2E7D32,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style OUT1 fill:#90CAF9,stroke:#1565C0,color:#000
    style OUT2 fill:#90CAF9,stroke:#1565C0,color:#000
    style OUT3 fill:#90CAF9,stroke:#1565C0,color:#000
```

**Key Features:**
- `structure_from`: Connect structures between stages
- `restart`: Reuse WAVECAR/CHGCAR for faster convergence
- Each stage produces independent energy

---

### Pattern 2: DOS Calculation

```mermaid
graph LR
    INPUT[Initial Structure] -->|structure| RELAX[VASP Relax<br/>nsw=100]
    RELAX -->|structure| DOS_CALC[DOS Brick<br/>SCF + DOS]

    DOS_CALC -->|energy| SCF_E[SCF Energy]
    DOS_CALC -->|dos| DOS_DATA[DOS Data]
    DOS_CALC -->|projectors| PROJ_DATA[Projected DOS]

    style RELAX fill:#4CAF50,stroke:#2E7D32,color:#fff
    style DOS_CALC fill:#2196F3,stroke:#1565C0,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style SCF_E fill:#90CAF9,stroke:#1565C0,color:#000
    style DOS_DATA fill:#F48FB1,stroke:#C2185B,color:#fff
    style PROJ_DATA fill:#F48FB1,stroke:#C2185B,color:#fff
```

**Configuration:**
```python
stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {'nsw': 100, 'ibrion': 2},
        'restart': None,
    },
    {
        'name': 'dos_calc',
        'type': 'dos',
        'structure_from': 'relax',  # Connection!
        'scf_incar': {'encut': 520, 'ediff': 1e-6},
        'dos_incar': {'nedos': 2000, 'lorbit': 11},
    },
]
```

---

### Pattern 3: Batch Parallel Calculations

```mermaid
graph TB
    INPUT[Structure] -->|structure| BATCH[BATCH Brick]

    BATCH -->|label1_energy| E1[Calc 1 Energy]
    BATCH -->|label1_misc| M1[Calc 1 Results]
    BATCH -->|label2_energy| E2[Calc 2 Energy]
    BATCH -->|label2_misc| M2[Calc 2 Results]
    BATCH -->|label3_energy| E3[Calc 3 Energy]
    BATCH -->|label3_misc| M3[Calc 3 Results]

    style BATCH fill:#2196F3,stroke:#1565C0,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style E1 fill:#90CAF9,stroke:#1565C0,color:#000
    style E2 fill:#90CAF9,stroke:#1565C0,color:#000
    style E3 fill:#90CAF9,stroke:#1565C0,color:#000
    style M1 fill:#BCAAA4,stroke:#4E342E,color:#fff
    style M2 fill:#BCAAA4,stroke:#4E342E,color:#fff
    style M3 fill:#BCAAA4,stroke:#4E342E,color:#fff
```

**Use Case:** Test multiple INCAR parameters in parallel (e.g., ENCUT convergence)

---

## Advanced Workflows

### Pattern 4: Bader Charge Analysis

```mermaid
graph LR
    INPUT[Structure] -->|structure| SCF[VASP SCF<br/>laechg=True<br/>lcharg=True]

    SCF -->|structure| BADER[BADER Brick]
    SCF -->|retrieved<br/>AECCAR0/2, CHGCAR| BADER

    BADER -->|charges| BC[Per-atom Charges]
    BADER -->|acf| ACF[ACF.dat]
    BADER -->|bcf| BCF[BCF.dat]
    BADER -->|avf| AVF[AVF.dat]

    style SCF fill:#4CAF50,stroke:#2E7D32,color:#fff
    style BADER fill:#FF9800,stroke:#E65100,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style BC fill:#FF7043,stroke:#BF360C,color:#fff
    style ACF fill:#B0BEC5,stroke:#455A64,color:#fff
    style BCF fill:#B0BEC5,stroke:#455A64,color:#fff
    style AVF fill:#B0BEC5,stroke:#455A64,color:#fff
```

**Prerequisites:** VASP stage must have:
- `incar`: `{'laechg': True, 'lcharg': True}`
- `retrieve`: `['AECCAR0', 'AECCAR2', 'CHGCAR', 'OUTCAR']`

---

### Pattern 5: Hubbard U Calculation

```mermaid
graph TB
    INPUT[Structure] -->|structure| RELAX[VASP Relax]

    RELAX -->|structure| GS[VASP Ground State<br/>lorbit=11<br/>lwave=True<br/>lcharg=True]

    GS -->|structure| RESP[HUBBARD_RESPONSE<br/>Perturbed Calcs]
    GS -->|remote_folder<br/>WAVECAR/CHGCAR| RESP
    GS -->|retrieved<br/>OUTCAR| RESP

    RESP -->|responses| ANAL[HUBBARD_ANALYSIS<br/>Linear Regression]
    RESP -->|ground_state_occupation| ANAL
    RELAX -->|structure| ANAL

    ANAL -->|hubbard_u_result| U_VALUE[U Value]
    ANAL -->|summary| SUMMARY[Full Summary]

    style RELAX fill:#4CAF50,stroke:#2E7D32,color:#fff
    style GS fill:#4CAF50,stroke:#2E7D32,color:#fff
    style RESP fill:#FF9800,stroke:#E65100,color:#fff
    style ANAL fill:#FF9800,stroke:#E65100,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style U_VALUE fill:#AB47BC,stroke:#6A1B9A,color:#fff
    style SUMMARY fill:#AB47BC,stroke:#6A1B9A,color:#fff
```

**Configuration:**
```python
stages = [
    {'name': 'relax', 'type': 'vasp', 'incar': {...}, 'restart': None},
    {
        'name': 'ground_state',
        'type': 'vasp',
        'structure_from': 'relax',
        'incar': {'nsw': 0, 'lorbit': 11, 'lwave': True, 'lcharg': True},
        'restart': None,
    },
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',  # Connection!
        'structure_from': 'relax',
        'target_species': 'Sn',
        'potential_values': [-0.2, -0.1, 0.1, 0.2],
    },
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',  # Connection!
        'structure_from': 'relax',
        'target_species': 'Sn',
    },
]
```

---

### Pattern 6: NEB Transition Path

```mermaid
graph TB
    INIT[Initial Structure] -->|structure| RELAX_I[VASP Relax Initial]
    FINAL[Final Structure] -->|structure| RELAX_F[VASP Relax Final]

    RELAX_I -->|structure| GEN[GENERATE_NEB_IMAGES<br/>IDPP/Linear]
    RELAX_F -->|structure| GEN

    GEN -->|neb_images| NEB1[NEB Stage 1<br/>Standard NEB]
    RELAX_I -->|structure| NEB1
    RELAX_F -->|structure| NEB1

    NEB1 -->|remote_folder| NEB2[NEB Stage 2<br/>CI-NEB<br/>lclimb=True]
    RELAX_I -->|structure| NEB2
    RELAX_F -->|structure| NEB2
    GEN -->|neb_images| NEB2

    NEB2 -->|trajectory| PATH[Reaction Path]
    NEB2 -->|misc| BARRIER[Energy Barrier]

    style RELAX_I fill:#4CAF50,stroke:#2E7D32,color:#fff
    style RELAX_F fill:#4CAF50,stroke:#2E7D32,color:#fff
    style GEN fill:#FF9800,stroke:#E65100,color:#fff
    style NEB1 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style NEB2 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style INIT fill:#FFD54F,stroke:#F57F17,color:#000
    style FINAL fill:#FFD54F,stroke:#F57F17,color:#000
    style PATH fill:#4DD0E1,stroke:#00838F,color:#fff
    style BARRIER fill:#BCAAA4,stroke:#4E342E,color:#fff
```

**Key Points:**
- `generate_neb_images` creates intermediate structures
- NEB stages can be chained via `restart`
- `images_from` connects to generator OR `images_dir` for manual images

---

### Pattern 7: AIMD Chain

```mermaid
graph LR
    INPUT[Structure<br/>or Supercell] -->|structure| AIMD1[AIMD Stage 1<br/>Equilibration]

    AIMD1 -->|remote_folder<br/>WAVECAR| AIMD2[AIMD Stage 2<br/>Production 1]
    AIMD1 -.->|trajectory<br/>auto-extract velocities| AIMD2

    AIMD2 -->|remote_folder| AIMD3[AIMD Stage 3<br/>Production 2]
    AIMD2 -.->|trajectory<br/>velocities| AIMD3

    AIMD1 -->|trajectory| T1[Trajectory 1]
    AIMD2 -->|trajectory| T2[Trajectory 2]
    AIMD3 -->|trajectory| T3[Trajectory 3]

    style AIMD1 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style AIMD2 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style AIMD3 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style T1 fill:#4DD0E1,stroke:#00838F,color:#fff
    style T2 fill:#4DD0E1,stroke:#00838F,color:#fff
    style T3 fill:#4DD0E1,stroke:#00838F,color:#fff
```

**Features:**
- Velocities automatically extracted from previous trajectory
- `restart` reuses WAVECAR for efficiency
- Trajectories can be concatenated for analysis

---

## Batch and Analysis Patterns

### Pattern 8: Convergence Testing

```mermaid
graph TB
    INPUT[Structure] -->|structure| CONV[CONVERGENCE Brick]

    CONV -->|cutoff_analysis| ENCUT[ENCUT Results<br/>Energy vs ENCUT]
    CONV -->|kpoints_analysis| KPTS[K-points Results<br/>Energy vs Density]
    CONV -->|recommendations| REC[Recommended<br/>Parameters]

    style CONV fill:#FF9800,stroke:#E65100,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style ENCUT fill:#AED581,stroke:#558B2F,color:#fff
    style KPTS fill:#AED581,stroke:#558B2F,color:#fff
    style REC fill:#AED581,stroke:#558B2F,color:#fff
```

**Auto-Tests:**
- ENCUT: Multiple values tested
- K-points: Multiple densities tested
- Produces convergence plots and recommendations

---

### Pattern 9: Thickness Convergence

```mermaid
graph TB
    subgraph "Option A: Standalone"
        INPUT1[Bulk Structure] -->|structure| THICK1[THICKNESS Brick<br/>Auto-compute bulk]
        THICK1 -->|convergence_results| RES1[Surface Energy vs<br/>Layer Count]
    end

    subgraph "Option B: With VASP Bulk"
        INPUT2[Bulk Structure] -->|structure| BULK[VASP Bulk Calc]
        BULK -->|structure| THICK2[THICKNESS Brick]
        BULK -->|energy| THICK2
        THICK2 -->|convergence_results| RES2[Surface Energy vs<br/>Layer Count]
    end

    style THICK1 fill:#FF9800,stroke:#E65100,color:#fff
    style THICK2 fill:#FF9800,stroke:#E65100,color:#fff
    style BULK fill:#4CAF50,stroke:#2E7D32,color:#fff
    style INPUT1 fill:#FFD54F,stroke:#F57F17,color:#000
    style INPUT2 fill:#FFD54F,stroke:#F57F17,color:#000
    style RES1 fill:#AED581,stroke:#558B2F,color:#fff
    style RES2 fill:#AED581,stroke:#558B2F,color:#fff
```

**Configuration:**
```python
# Option B example
stages = [
    {
        'name': 'bulk',
        'type': 'vasp',
        'incar': {'nsw': 100, 'ibrion': 2, 'isif': 3},
        'restart': None,
    },
    {
        'name': 'thickness',
        'type': 'thickness',
        'structure_from': 'bulk',  # Uses relaxed bulk
        'energy_from': 'bulk',     # Uses bulk energy
        'miller_indices': [1, 1, 0],
        'layer_counts': [3, 4, 5, 6, 7],
        'vacuum': 15.0,
        'incar': {'nsw': 100, 'ibrion': 2},
    },
]
```

---

## Multi-Code Workflows

### Pattern 10: Quantum ESPRESSO

```mermaid
graph LR
    INPUT[Structure] -->|structure| QE1[QE Relax<br/>calculation='relax']

    QE1 -->|structure| QE2[QE SCF<br/>calculation='scf']
    QE1 -->|remote_folder<br/>parent_folder| QE2

    QE2 -->|structure| QE3[QE Static<br/>High precision]
    QE2 -->|remote_folder| QE3

    QE1 -.->|energy| E1[Energy 1]
    QE2 -.->|energy| E2[Energy 2]
    QE3 -.->|energy| E3[Energy 3]

    style QE1 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style QE2 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style QE3 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style E1 fill:#90CAF9,stroke:#1565C0,color:#000
    style E2 fill:#90CAF9,stroke:#1565C0,color:#000
    style E3 fill:#90CAF9,stroke:#1565C0,color:#000
```

---

### Pattern 11: CP2K

```mermaid
graph LR
    INPUT[Structure] -->|structure| CP1[CP2K GEO_OPT<br/>Geometry Optimization]

    CP1 -->|structure| CP2[CP2K SCF<br/>Energy Calc]
    CP1 -->|remote_folder<br/>parent_calc_folder| CP2

    INPUT -->|structure| CP3[CP2K MD<br/>Molecular Dynamics]
    CP3 -->|trajectory| TRAJ[MD Trajectory]

    style CP1 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style CP2 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style CP3 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style INPUT fill:#FFD54F,stroke:#F57F17,color:#000
    style TRAJ fill:#4DD0E1,stroke:#00838F,color:#fff
```

---

## Connection Rules

### 1. Source Resolution Modes

| Mode | Description | Example |
|------|-------------|---------|
| `auto` | General mode for structure-bearing bricks: resolves structure from `structure_from` (defaulting to `previous`/`input` when absent) | `'source': 'auto'` → uses `structure_from` or falls back to previous/input |
| `structure_from` | Reference structure from named stage | `'structure_from': 'relax'` |
| `energy_from` | Reference energy from named stage | `'energy_from': 'scf'` |
| `charge_from` | Bader: reference VASP charge stage | `'charge_from': 'scf'` |
| `ground_state_from` | Hubbard: reference ground state VASP | `'ground_state_from': 'gs'` |
| `response_from` | Hubbard analysis: reference response | `'response_from': 'response'` |
| `restart` | Reuse remote folder (WAVECAR/CHGCAR) | `'restart': 'previous_stage'` |
| `initial_from` / `final_from` | NEB endpoints | `'initial_from': 'relax_i'` |
| `images_from` | NEB images from generator | `'images_from': 'gen_images'` |

---

### 2. Type Compatibility Matrix

| Output Port Type | Compatible Input Port Types |
|-----------------|----------------------------|
| `structure` | `structure` |
| `energy` | `energy` |
| `remote_folder` | `remote_folder`, `restart_folder` |
| `retrieved` | `retrieved`, `charge_files` |
| `dos_data` | `dos_data` |
| `trajectory` | `trajectory` |
| `hubbard_responses` | `hubbard_responses` |
| `neb_images` | `neb_images` |

**Rule:** Input port type must exactly match output port type.

---

### 3. Brick Compatibility Constraints

Some inputs can only connect to specific brick types:

| Input Port | Allowed Source Bricks |
|-----------|----------------------|
| `bader.charge_files` | `vasp` |
| `bader.structure` | `vasp` |
| `hubbard_response.ground_state_remote` | `vasp` |
| `hubbard_analysis.responses` | `hubbard_response` |
| `generate_neb_images.initial_structure` | `vasp` |
| `neb.initial_structure` | `vasp` |
| `neb.images` | `generate_neb_images` |
| `thickness.energy` | `vasp` |

---

### 4. Prerequisite Validation

Some connections require specific INCAR settings and retrieved files:

#### Bader Analysis Prerequisites:
```python
# Source VASP stage must have:
'incar': {
    'laechg': True,
    'lcharg': True,
}
'retrieve': ['AECCAR0', 'AECCAR2', 'CHGCAR', 'OUTCAR']
```

#### Hubbard Response Prerequisites:
```python
# Ground state VASP must have:
'incar': {
    'lorbit': 11,
    'lwave': True,
    'lcharg': True,
}
'retrieve': ['OUTCAR']  # For occupation numbers
```

---

### 5. Conditional Outputs

Some outputs are only meaningful under certain conditions:

| Brick | Output | Condition |
|-------|--------|-----------|
| VASP | `structure` | `nsw > 0` (relaxation/MD) |
| QE | `structure` | `calculation in ['relax', 'vc-relax']` |
| CP2K | `structure` | `RUN_TYPE in ['GEO_OPT', 'CELL_OPT', 'MD']` |
| CP2K | `trajectory` | `RUN_TYPE == 'MD'` |

**Warnings:** The validation system warns if you reference a potentially meaningless output (e.g., structure from `nsw=0` static calc).

---

### 6. Validation Before Submission

Call `validate_connections()` to check all connections:

```python
from quantum_lego.core.bricks import validate_connections

stages = [
    {'name': 'relax', 'type': 'vasp', ...},
    {'name': 'dos', 'type': 'dos', 'structure_from': 'relax', ...},
]

warnings = validate_connections(stages)
# Returns list of warning strings (empty if OK)
# Raises ValueError if connections are invalid
```

**What it checks:**
1. ✓ Port type compatibility
2. ✓ Referenced stages exist
3. ✓ Brick compatibility constraints
4. ✓ Prerequisites (INCAR settings, retrieve lists)
5. ⚠ Conditional output warnings

---

## Quick Reference: Brick Capabilities

| Brick | Input Structure | Output Structure | Output Energy | Output Trajectory | Requires Prior VASP | Chainable |
|-------|----------------|------------------|---------------|-------------------|---------------------|-----------|
| **vasp** | Yes | Yes* | Yes | No | No | Via `restart` |
| **dos** | From stage | No | Yes (SCF) | No | Yes | No |
| **batch** | From stage | No | Yes (per-calc) | No | Yes | No |
| **bader** | From stage | No | No | No | Yes | No |
| **convergence** | Optional | No | No | No | No | No |
| **thickness** | Optional | No | No | No | No | No |
| **hubbard_response** | From stage | No | No | No | Yes (ground state) | No |
| **hubbard_analysis** | From stage | No | No | No | No (uses response data) | No |
| **aimd** | Yes | Yes | Yes | Yes | No | Via `restart` |
| **qe** | Yes | Yes* | Yes | No | No | Via `restart` |
| **cp2k** | Yes | Yes* | Yes | Yes* | No | Via `restart` |
| **generate_neb_images** | 2x from VASP | No | No | No | Yes (endpoints) | No |
| **neb** | 2x from VASP | Yes | No | Yes | Yes (endpoints) | Via `restart` |

\* Conditional on calculation type (see [Conditional Outputs](#5-conditional-outputs))

---

## Examples from Codebase

### Example 1: Full VASP → DOS Pipeline

```python
from quantum_lego import quick_vasp_sequential

stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {'nsw': 100, 'ibrion': 2, 'isif': 3, 'encut': 520},
        'kpoints_spacing': 0.05,
        'restart': None,
    },
    {
        'name': 'scf',
        'type': 'vasp',
        'structure_from': 'relax',  # Use relaxed structure
        'incar': {'nsw': 0, 'encut': 520, 'lwave': True, 'lcharg': True},
        'kpoints_spacing': 0.03,
        'restart': 'relax',  # Reuse WAVECAR
    },
    {
        'name': 'dos',
        'type': 'dos',
        'structure_from': 'relax',  # Use relaxed structure
        'scf_incar': {'encut': 520, 'ediff': 1e-6},
        'dos_incar': {'nedos': 2000, 'lorbit': 11, 'ismear': -5},
        'kpoints_spacing': 0.03,
        'dos_kpoints_spacing': 0.02,
    },
]

result = quick_vasp_sequential(
    structure=structure,
    code_label='VASP-6.5.1@localwork',
    stages=stages,
    potential_family='PBE',
    potential_mapping={'Sn': 'Sn_d', 'O': 'O'},
    options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 8}},
)
```

---

### Example 2: Complete Hubbard U Workflow

```python
stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {'nsw': 50, 'ibrion': 2, 'isif': 2, 'encut': 520},
        'restart': None,
    },
    {
        'name': 'ground_state',
        'type': 'vasp',
        'structure_from': 'relax',
        'incar': {
            'nsw': 0,
            'encut': 520,
            'lorbit': 11,  # Required for occupations
            'lwave': True,  # Required for restart
            'lcharg': True,  # Required for restart
        },
        'restart': None,
    },
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',  # Where to get WAVECAR/CHGCAR
        'structure_from': 'relax',            # Where to get structure
        'target_species': 'Sn',
        'target_orbitals': 'd',
        'potential_values': [-0.2, -0.1, 0.1, 0.2],  # Perturbation potentials
        'nscf_incar': {'nelm': 1},           # NSCF settings
        'scf_incar': {'ediff': 1e-6},        # SCF settings
    },
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',          # Where to get response data
        'structure_from': 'relax',            # Where to get structure
        'target_species': 'Sn',
    },
]
```

---

### Example 3: NEB with Image Generation

```python
stages = [
    {
        'name': 'relax_initial',
        'type': 'vasp',
        'incar': {'nsw': 80, 'ibrion': 2, 'ediffg': -0.02},
        'restart': None,
    },
    {
        'name': 'relax_final',
        'type': 'vasp',
        'incar': {'nsw': 80, 'ibrion': 2, 'ediffg': -0.02},
        'restart': None,
    },
    {
        'name': 'make_images',
        'type': 'generate_neb_images',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'n_images': 5,
        'method': 'idpp',  # Better than linear
    },
    {
        'name': 'neb_stage_1',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',  # Use generated images
        'incar': {'ibrion': 3, 'potim': 0.0, 'iopt': 1, 'ediffg': -0.05},
        'restart': None,
    },
    {
        'name': 'neb_stage_2_ci',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',  # Reuse same images
        'incar': {'lclimb': True, 'ibrion': 3, 'ediffg': -0.02},  # Climbing image
        'restart': 'neb_stage_1',  # Restart from previous NEB
    },
]
```

---

## Summary

The Quantum Lego brick system provides:

1. **13 Brick Types**: 5 structure-producing, 2 non-structure computation, 6 analysis
2. **14 Port Types**: Typed data flow with validation
3. **9 Source Modes**: Flexible connection patterns
4. **Automatic Validation**: Type checking, prerequisite checking, warning system
5. **Common Patterns**: Sequential, batch, restart chaining, multi-stage analysis

**Key Principle:** Bricks connect like Lego pieces through typed ports, with validation ensuring compatible connections before submission.

For implementation details, see:
- Port declarations: `quantum_lego/core/bricks/connections.py`
- Brick implementations: `quantum_lego/core/bricks/*.py`
- Examples: `examples/` directory
- Developer guide: `AGENTS.md`
