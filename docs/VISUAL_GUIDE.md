# Quantum Lego Visual Workflow Guide

This guide provides visual diagrams for common computational workflows using Quantum Lego bricks. For VASP workflows, `quick_vasp_sequential()` is the central execution path behind stage/brick orchestration.

## Table of Contents

- [Basic Single Calculations](#basic-single-calculations)
- [Sequential Workflows](#sequential-workflows)
- [Batch Operations](#batch-operations)
- [Advanced Multi-Stage Workflows](#advanced-multi-stage-workflows)
- [NEB Calculations](#neb-calculations)
- [Port Connection Patterns](#port-connection-patterns)

---

## Basic Single Calculations

### Simple VASP Relaxation

```mermaid
graph TD
    A[Input Structure] --> B[VASP Brick<br/>NSW=100, IBRION=2]
    B --> C[Relaxed Structure]
    B --> D[Final Energy]
    B --> E[Output Files<br/>CONTCAR, OUTCAR, etc.]

    style B fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style A fill:#E3F2FD,stroke:#1976D2
    style C fill:#FFF3E0,stroke:#F57C00
    style D fill:#FFF3E0,stroke:#F57C00
    style E fill:#FFF3E0,stroke:#F57C00
```

**Code:**
```python
pk = quick_vasp(
    structure=structure,
    code_label='VASP-6.5.1@localwork',
    incar={'NSW': 100, 'IBRION': 2, 'ENCUT': 400},
    kpoints_spacing=0.03,
    ...
)
```

### DOS Calculation (Two-Step Process)

```mermaid
graph TD
    A[Input Structure] --> B[DOS Brick]
    B --> C[Step 1: SCF<br/>LWAVE=True, LCHARG=True]
    C --> D[Step 2: Non-SCF DOS<br/>ICHARG=11, NEDOS=2000]
    D --> E[SCF Energy]
    D --> F[DOS Data]
    D --> G[DOSCAR File]

    style B fill:#2196F3,stroke:#0D47A1,stroke-width:3px
    style C fill:#64B5F6,stroke:#1976D2
    style D fill:#1976D2,stroke:#0D47A1
    style E fill:#FFF3E0,stroke:#F57C00
    style F fill:#FFF3E0,stroke:#F57C00
    style G fill:#FFF3E0,stroke:#F57C00
```

**Code:**
```python
result = quick_dos(
    structure=structure,
    code_label='VASP-6.5.1@localwork',
    scf_incar={'encut': 400, 'ediff': 1e-6},
    dos_incar={'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    kpoints_spacing=0.03,
    dos_kpoints_spacing=0.02,
    ...
)
dos_stage = get_stage_results(result, 'dos')
```

---

## Sequential Workflows

### Relaxation → SCF → DOS

```mermaid
graph TD
    A[Initial Structure] --> B[Stage 1: VASP Relax<br/>NSW=100, IBRION=2]
    B -->|structure_from| C[Stage 2: VASP SCF<br/>NSW=0, LWAVE=True]
    B -->|structure_from| D[Stage 3: DOS<br/>SCF + DOS steps]
    C -->|restart| D
    D --> E[Final Results]

    style B fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style C fill:#2196F3,stroke:#0D47A1,stroke-width:3px
    style D fill:#FF9800,stroke:#E65100,stroke-width:3px
    style A fill:#E3F2FD,stroke:#1976D2
    style E fill:#FFF3E0,stroke:#F57C00
```

**Code:**
```python
stages = [
    {
        'name': 'relax',
        'type': 'vasp',
        'incar': {'NSW': 100, 'IBRION': 2, 'ENCUT': 520},
    },
    {
        'name': 'scf',
        'type': 'vasp',
        'structure_from': 'relax',
        'incar': {'NSW': 0, 'ENCUT': 600, 'LWAVE': True},
        'restart': None,
    },
    {
        'name': 'dos',
        'type': 'dos',
        'structure_from': 'relax',
        'scf_incar': {'encut': 600, 'ediff': 1e-6},
        'dos_incar': {'nedos': 2000, 'lorbit': 11},
    },
]

result = quick_vasp_sequential(structure, stages=stages, ...)
```

### Relaxation → Bader Analysis

```mermaid
graph TD
    A[Initial Structure] --> B[Stage 1: VASP SCF<br/>NSW=0, LCHARG=True]
    B -->|structure_from| C[Stage 2: Bader Brick<br/>Charge Analysis]
    B -->|charge_from| C
    C --> D[Atomic Charges]
    C --> E[Charge Transfer]
    C --> F[Bader Volumes]

    style B fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style C fill:#E91E63,stroke:#880E4F,stroke-width:3px
    style D fill:#FFF3E0,stroke:#F57C00
    style E fill:#FFF3E0,stroke:#F57C00
    style F fill:#FFF3E0,stroke:#F57C00
```

**Code:**
```python
stages = [
    {
        'name': 'scf',
        'type': 'vasp',
        'incar': {'NSW': 0, 'ENCUT': 500, 'LCHARG': True},
    },
    {
        'name': 'bader',
        'type': 'bader',
        'structure_from': 'scf',
        'charge_from': 'scf',
    },
]
```

### Convergence Testing

```mermaid
graph TD
    A[Initial Structure] --> B[Convergence Brick<br/>Type: ENCUT]
    B --> C1[ENCUT=300 eV]
    B --> C2[ENCUT=400 eV]
    B --> C3[ENCUT=500 eV]
    B --> C4[ENCUT=600 eV]
    C1 --> D[Convergence Analysis]
    C2 --> D
    C3 --> D
    C4 --> D
    D --> E[Optimal ENCUT]

    style B fill:#00BCD4,stroke:#006064,stroke-width:3px
    style C1 fill:#4DD0E1,stroke:#00838F
    style C2 fill:#4DD0E1,stroke:#00838F
    style C3 fill:#4DD0E1,stroke:#00838F
    style C4 fill:#4DD0E1,stroke:#00838F
    style D fill:#FFF3E0,stroke:#F57C00
    style E fill:#C8E6C9,stroke:#2E7D32
```

**Code:**
```python
stages = [
    {
        'name': 'convergence',
        'type': 'convergence',
        'convergence_type': 'encut',
        'values': [300, 400, 500, 600],
        'incar': {'NSW': 0, 'PREC': 'Accurate'},
    },
]
```

---

## Batch Operations

### Batch VASP Calculations

```mermaid
graph TD
    A[Multiple Structures] --> B[Batch Brick]
    B --> C1[Structure 1<br/>Base INCAR]
    B --> C2[Structure 2<br/>INCAR + Override 1]
    B --> C3[Structure 3<br/>INCAR + Override 2]
    C1 --> D[Aggregated Results]
    C2 --> D
    C3 --> D

    style B fill:#FF9800,stroke:#E65100,stroke-width:3px
    style C1 fill:#FFB74D,stroke:#F57C00
    style C2 fill:#FFB74D,stroke:#F57C00
    style C3 fill:#FFB74D,stroke:#F57C00
    style D fill:#FFF3E0,stroke:#F57C00
```

**Code:**
```python
structures = {
    'pristine': structure1,
    'defect_1': structure2,
    'defect_2': structure3,
}

incar_overrides = {
    'defect_1': {'NELECT': 191.95},
    'defect_2': {'NELECT': 192.05},
}

result = quick_vasp_batch(
    structures=structures,
    incar={'NSW': 0, 'ENCUT': 400},
    incar_overrides=incar_overrides,
    ...
)
```

### Batch DOS Calculations

```mermaid
graph TD
    A[Multiple Structures] --> B[Batch DOS Brick]
    B --> C1[DOS Calc 1<br/>SCF + DOS]
    B --> C2[DOS Calc 2<br/>SCF + DOS]
    B --> C3[DOS Calc 3<br/>SCF + DOS]
    C1 --> D1[Energy 1 + DOS 1]
    C2 --> D2[Energy 2 + DOS 2]
    C3 --> D3[Energy 3 + DOS 3]
    D1 --> E[Combined Results]
    D2 --> E
    D3 --> E

    style B fill:#2196F3,stroke:#0D47A1,stroke-width:3px
    style C1 fill:#64B5F6,stroke:#1976D2
    style C2 fill:#64B5F6,stroke:#1976D2
    style C3 fill:#64B5F6,stroke:#1976D2
    style E fill:#FFF3E0,stroke:#F57C00
```

**Code:**
```python
structures = {
    'struct_1': structure1,
    'struct_2': structure2,
    'struct_3': structure3,
}

result = quick_dos_batch(
    structures=structures,
    scf_incar={'encut': 400, 'ediff': 1e-6},
    dos_incar={'nedos': 2000, 'lorbit': 11, 'ismear': -5},
    max_concurrent_jobs=2,
    ...
)
```

---

## Advanced Multi-Stage Workflows

### Relax → Multiple Analyses

```mermaid
graph TD
    A[Initial Structure] --> B[Stage 1: Relax<br/>NSW=100, IBRION=2]
    B -->|structure_from| C[Stage 2: DOS<br/>Electronic Structure]
    B -->|structure_from| D[Stage 3: Bader<br/>Charge Analysis]
    B -->|structure_from| E[Stage 4: AIMD<br/>Dynamics at 300K]
    C --> F[DOS Results]
    D --> F
    E --> F

    style B fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style C fill:#2196F3,stroke:#0D47A1,stroke-width:3px
    style D fill:#E91E63,stroke:#880E4F,stroke-width:3px
    style E fill:#9C27B0,stroke:#4A148C,stroke-width:3px
    style F fill:#FFF3E0,stroke:#F57C00
```

**Note:** Stages C, D, and E can run in parallel if `max_concurrent_jobs > 1`.

### Hubbard U Calculation

```mermaid
graph TD
    A[Initial Structure] --> B[Stage 1: Ground State SCF<br/>NSW=0]
    B --> C[Stage 2: Hubbard Response<br/>Multiple perturbed calcs]
    C --> D[Stage 3: Hubbard Analysis<br/>Linear regression]
    D --> E[U Parameters]

    style B fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style C fill:#CDDC39,stroke:#827717,stroke-width:3px
    style D fill:#8BC34A,stroke:#33691E,stroke-width:3px
    style E fill:#C8E6C9,stroke:#2E7D32
```

**Code:**
```python
stages = [
    {
        'name': 'ground_state',
        'type': 'vasp',
        'incar': {'NSW': 0, 'ENCUT': 500},
    },
    {
        'name': 'response',
        'type': 'hubbard_response',
        'ground_state_from': 'ground_state',
        'perturbed_incar': {'ENCUT': 500},
        'atom_index': 0,
        'perturbations': [-0.2, -0.1, 0.1, 0.2],
    },
    {
        'name': 'analysis',
        'type': 'hubbard_analysis',
        'response_from': 'response',
    },
]
```

---

## NEB Calculations

### Complete NEB Workflow

```mermaid
graph TD
    A1[Initial Structure] --> B1[Stage 1: Relax Initial<br/>NSW=100, IBRION=2]
    A2[Final Structure] --> B2[Stage 2: Relax Final<br/>NSW=100, IBRION=2]
    B1 --> C[Stage 3: Generate Images<br/>n_images=7]
    B2 --> C
    C --> D[Stage 4: NEB Calculation<br/>IBRION=3, IOPT=3]
    D --> E[Stage 5: CI-NEB<br/>LCLIMB=True]
    E --> F[Reaction Path]
    E --> G[Energy Barrier]
    E --> H[Transition State]

    style B1 fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style B2 fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style C fill:#607D8B,stroke:#263238,stroke-width:3px
    style D fill:#455A64,stroke:#263238,stroke-width:3px
    style E fill:#37474F,stroke:#263238,stroke-width:3px
    style F fill:#FFF3E0,stroke:#F57C00
    style G fill:#FFF3E0,stroke:#F57C00
    style H fill:#FFF3E0,stroke:#F57C00
```

**Code:**
```python
stages = [
    {
        'name': 'relax_initial',
        'type': 'vasp',
        'structure': initial_structure,
        'incar': {'NSW': 100, 'IBRION': 2, 'ENCUT': 400},
    },
    {
        'name': 'relax_final',
        'type': 'vasp',
        'structure': final_structure,
        'incar': {'NSW': 100, 'IBRION': 2, 'ENCUT': 400},
    },
    {
        'name': 'make_images',
        'type': 'generate_neb_images',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'n_images': 7,
    },
    {
        'name': 'neb',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',
        'incar': {'IBRION': 3, 'IOPT': 3, 'NSW': 200, 'SPRING': -5},
    },
    {
        'name': 'neb_ci',
        'type': 'neb',
        'initial_from': 'relax_initial',
        'final_from': 'relax_final',
        'images_from': 'make_images',
        'restart': 'neb',
        'incar': {'IBRION': 3, 'IOPT': 3, 'NSW': 200, 'SPRING': -5, 'LCLIMB': True},
    },
]

result = quick_vasp_sequential(structure=initial_structure, stages=stages, ...)
```

---

## Port Connection Patterns

### Port Types and Connections

```mermaid
graph LR
    subgraph "Producer Brick (VASP)"
        P1[structure output<br/>type: structure]
        P2[energy output<br/>type: energy]
        P3[remote_folder output<br/>type: remote_folder]
    end

    subgraph "Consumer Brick (DOS)"
        C1[structure input<br/>type: structure]
        C2[restart_folder input<br/>type: remote_folder]
    end

    P1 -->|structure_from| C1
    P3 -->|restart| C2

    style P1 fill:#C8E6C9,stroke:#2E7D32
    style P2 fill:#C8E6C9,stroke:#2E7D32
    style P3 fill:#C8E6C9,stroke:#2E7D32
    style C1 fill:#BBDEFB,stroke:#1565C0
    style C2 fill:#BBDEFB,stroke:#1565C0
```

### Valid Connection Examples

```mermaid
graph TD
    A[VASP Brick] -->|structure| B[VASP Brick]
    A -->|structure| C[DOS Brick]
    A -->|structure| D[Bader Brick]
    A -->|remote_folder| E[VASP Brick<br/>restart]
    C -->|dos_data| F[Analysis]
    D -->|bader_charges| F

    style A fill:#4CAF50,stroke:#2E7D32
    style B fill:#4CAF50,stroke:#2E7D32
    style C fill:#2196F3,stroke:#0D47A1
    style D fill:#E91E63,stroke:#880E4F
    style E fill:#4CAF50,stroke:#2E7D32
    style F fill:#9C27B0,stroke:#4A148C
```

### Invalid Connection (Caught by Validation)

```mermaid
graph TD
    A[DOS Brick] -->|structure?| B[VASP Brick]

    style A fill:#2196F3,stroke:#0D47A1
    style B fill:#4CAF50,stroke:#2E7D32

    C[❌ Invalid!<br/>DOS brick doesn't<br/>output structure]

    style C fill:#FFCDD2,stroke:#C62828,stroke-width:2px
```

**Note:** DOS bricks perform calculations but don't modify the structure, so they don't have a `structure` output port.

---

## Workflow Execution Patterns

### Serial Execution (max_concurrent_jobs=1)

```mermaid
gantt
    title Serial Execution Timeline
    dateFormat X
    axisFormat %s

    section Stages
    Relax       :0, 100s
    SCF         :100s, 50s
    DOS         :150s, 80s
```

**Code:**
```python
result = quick_vasp_sequential(
    structure=structure,
    stages=stages,
    max_concurrent_jobs=1,  # One at a time
    ...
)
```

### Parallel Execution (max_concurrent_jobs=3)

```mermaid
gantt
    title Parallel Execution Timeline
    dateFormat X
    axisFormat %s

    section Independent
    Relax       :0, 100s

    section Parallel (after relax)
    DOS         :100s, 80s
    Bader       :100s, 60s
    AIMD        :100s, 120s
```

**Code:**
```python
stages = [
    {'name': 'relax', 'type': 'vasp', ...},
    {'name': 'dos', 'type': 'dos', 'structure_from': 'relax', ...},
    {'name': 'bader', 'type': 'bader', 'structure_from': 'relax', ...},
    {'name': 'aimd', 'type': 'aimd', 'structure_from': 'relax', ...},
]

result = quick_vasp_sequential(
    structure=structure,
    stages=stages,
    max_concurrent_jobs=3,  # DOS, Bader, AIMD run in parallel
    ...
)
```

---

## Complete Example: Surface Adsorption Study

```mermaid
graph TD
    A[Clean Surface] --> B[Stage 1: Relax Clean<br/>NSW=100, ISIF=2]
    C[Surface + Adsorbate] --> D[Stage 2: Relax Adsorbed<br/>NSW=100, ISIF=2]

    B --> E[Stage 3: Clean DOS<br/>Electronic structure]
    D --> F[Stage 4: Adsorbed DOS<br/>Electronic structure]

    B --> G[Stage 5: Clean Bader<br/>Charge analysis]
    D --> H[Stage 6: Adsorbed Bader<br/>Charge analysis]

    E --> I[Compare DOS]
    F --> I
    G --> J[Charge Transfer Analysis]
    H --> J

    I --> K[Final Results]
    J --> K

    style B fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style D fill:#4CAF50,stroke:#2E7D32,stroke-width:3px
    style E fill:#2196F3,stroke:#0D47A1,stroke-width:2px
    style F fill:#2196F3,stroke:#0D47A1,stroke-width:2px
    style G fill:#E91E63,stroke:#880E4F,stroke-width:2px
    style H fill:#E91E63,stroke:#880E4F,stroke-width:2px
    style K fill:#FFD54F,stroke:#F57F17,stroke-width:3px
```

**Implementation:**
```python
# Two separate sequential workflows
stages_clean = [
    {'name': 'relax', 'type': 'vasp', 'incar': {...}},
    {'name': 'dos', 'type': 'dos', 'structure_from': 'relax', ...},
    {'name': 'bader', 'type': 'bader', 'structure_from': 'relax', ...},
]

stages_adsorbed = [
    {'name': 'relax', 'type': 'vasp', 'incar': {...}},
    {'name': 'dos', 'type': 'dos', 'structure_from': 'relax', ...},
    {'name': 'bader', 'type': 'bader', 'structure_from': 'relax', ...},
]

result_clean = quick_vasp_sequential(clean_surface, stages=stages_clean, ...)
result_adsorbed = quick_vasp_sequential(surface_with_adsorbate, stages=stages_adsorbed, ...)

# Compare results
clean_energy = get_stage_results(result_clean, 'relax')['energy']
adsorbed_energy = get_stage_results(result_adsorbed, 'relax')['energy']
adsorption_energy = adsorbed_energy - clean_energy
```

---

## Summary

### Brick Color Code

- 🟢 **Green (VASP)**: Standard DFT calculations
- 🔵 **Blue (DOS)**: Electronic structure analysis
- 🟠 **Orange (Batch)**: Parallel operations
- 🟣 **Purple (AIMD)**: Molecular dynamics
- 🔴 **Pink (Bader)**: Charge analysis
- 🟡 **Yellow/Green (Hubbard)**: DFT+U calculations
- ⚫ **Gray (NEB)**: Reaction pathways
- 🔵 **Indigo (QE/CP2K)**: Alternative DFT codes
- 🔷 **Cyan (Convergence)**: Parameter optimization

### Key Principles

1. **Validate Before Submit**: Connections are checked automatically
2. **Type Safety**: Port types must match (structure→structure, energy→energy)
3. **Parallel When Possible**: Independent stages run concurrently
4. **Restart Saves Time**: Use WAVECAR/CHGCAR from previous stages
5. **Monitor Progress**: Always use `verdi process show <PK>`

---

**For more details, see `DOCUMENTATION.md` and `QUICK_START.md`!**
