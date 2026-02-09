# Convergence Testing Module

This module provides automated convergence testing for VASP calculations, including:

1. **ENCUT and k-points convergence** using the `vasp.v2.converge` plugin
2. **Slab thickness convergence** for surface energy calculations
3. **Visualization and export utilities** for analyzing results

## Theory

### ENCUT Convergence

The plane-wave cutoff energy (ENCUT) determines the size of the basis set. Higher ENCUT includes more plane waves, improving accuracy but increasing computational cost. The goal is to find the minimum ENCUT where the total energy is converged within a specified threshold.

**Convergence criterion:**
$$|E(E_{\text{cut}}) - E(E_{\text{cut,ref}})| / N_{\text{atoms}} < \epsilon$$

Where $E_{\text{cut,ref}}$ is the energy at the highest tested cutoff (assumed most accurate).

### K-points Convergence

The k-point density determines how finely the Brillouin zone is sampled. Denser k-grids (smaller k-spacing) improve accuracy. The goal is to find the coarsest k-spacing that achieves converged results.

**Convergence criterion:**
$$|E(k_{\text{spacing}}) - E(k_{\text{spacing,ref}})| / N_{\text{atoms}} < \epsilon$$

Where $k_{\text{spacing,ref}}$ is the energy at the finest grid (smallest k-spacing).

### Typical Convergence Thresholds

| Application | Threshold (meV/atom) | Notes |
|-------------|---------------------|-------|
| Quick screening | 5-10 | Rough estimates |
| Standard calculations | 1-2 | Most production work |
| High precision | 0.1-0.5 | Formation energies, phonons |
| Benchmark quality | < 0.1 | Reference calculations |

## Module Structure

```
convergence/
├── __init__.py              # Module exports
├── workgraph.py             # WorkGraph builders for convergence workflows
├── tasks.py                 # Analysis calcfunctions
├── slabs.py                 # Slab generation for thickness convergence
├── visualization.py         # Plotting and summary functions (NEW)
└── README.md                # This file
```

## Key Functions

### ENCUT/K-points Convergence

#### `build_convergence_workgraph`

Main entry point for ENCUT and k-points convergence testing.

```python
from quantum_lego.core.common.convergence import build_convergence_workgraph

wg = build_convergence_workgraph(
    structure=my_structure,           # StructureData
    code_label='VASP-6.4.3@bohr',    # VASP code
    builder_inputs={...},             # VASP parameters
    conv_settings={...},              # Convergence scan settings
    convergence_threshold=0.001,      # 1 meV/atom
    name='Si_convergence',
)
wg.submit()
```

**Parameters:**
- `structure`: AiiDA StructureData to test
- `code_label`: VASP code label in AiiDA
- `builder_inputs`: Dict with VASP parameters (see below)
- `conv_settings`: Dict with scan ranges (see below)
- `convergence_threshold`: Energy threshold in eV/atom (default: 0.001 = 1 meV)
- `name`: WorkGraph name

#### `get_convergence_results`

Extract results from a completed convergence workflow.

```python
from quantum_lego.core.common.convergence import get_convergence_results

results = get_convergence_results(wg)  # or get_convergence_results(pk)

print(f"Recommended ENCUT: {results['recommended_cutoff']} eV")
print(f"Recommended k-spacing: {results['recommended_kspacing']} Å⁻¹")
```

**Returns dict with:**
- `cutoff_conv_data`: Raw ENCUT convergence data
- `kpoints_conv_data`: Raw k-points convergence data
- `cutoff_analysis`: Detailed ENCUT analysis
- `kpoints_analysis`: Detailed k-points analysis
- `recommended_cutoff`: Recommended ENCUT with safety margin (int or None)
- `recommended_kspacing`: Recommended k-spacing with safety margin (float or None)
- `convergence_summary`: Summary dict with threshold and status

### Visualization Functions

#### `print_convergence_summary`

Print a formatted table of convergence results to the console.

```python
from quantum_lego.core.common.convergence import print_convergence_summary

print_convergence_summary(12345)  # Using PK
print_convergence_summary(wg)     # Using WorkGraph object
```

**Output:**
```
══════════════════════════════════════════════════════════════════════
              VASP CONVERGENCE TEST RESULTS
══════════════════════════════════════════════════════════════════════
WorkGraph PK: 12345
Structure: Si2 (2 atoms)
Threshold: 1.0 meV/atom
──────────────────────────────────────────────────────────────────────

ENCUT Convergence:
┌─────────┬──────────────┬──────────────┬───────────┐
│ ENCUT   │ Energy/atom  │ ΔE from ref  │ Converged │
│ (eV)    │ (eV)         │ (meV)        │           │
├─────────┼──────────────┼──────────────┼───────────┤
│     200 │      -5.4123 │        15.20 │ ✗         │
│     250 │      -5.4201 │         7.40 │ ✗         │
│     300 │      -5.4258 │         1.70 │ ✗         │
│     350 │      -5.4270 │         0.50 │ ✓         │
│     400 │      -5.4275 │         0.00 │ ✓ (ref)   │
└─────────┴──────────────┴──────────────┴───────────┘
✓ Converged at ENCUT = 350 eV
→ Recommended: 400 eV (with safety margin)
...
```

#### `plot_convergence`

Generate publication-quality convergence plots.

```python
from quantum_lego.core.common.convergence import plot_convergence

# Display interactively
fig = plot_convergence(12345)

# Save to file without displaying
fig = plot_convergence(wg, save_path='convergence.png', show=False)

# Customize the figure
fig = plot_convergence(wg, show=False)
fig.axes[0].set_xlim(200, 600)
fig.savefig('custom_plot.pdf', dpi=300)
```

**Parameters:**
- `workgraph`: PK (int/str), WorkGraph, or AiiDA Node
- `save_path`: Path to save figure (PNG, PDF, SVG)
- `figsize`: Figure size as (width, height) in inches
- `dpi`: Resolution for saved figure
- `show`: Whether to display interactively (default: True)

#### `export_convergence_data`

Export convergence data to CSV and JSON files.

```python
from quantum_lego.core.common.convergence import export_convergence_data

files = export_convergence_data(wg, './results', prefix='Si_conv')
print(files)
# {
#     'cutoff_csv': './results/Si_conv_cutoff.csv',
#     'kpoints_csv': './results/Si_conv_kpoints.csv',
#     'summary_json': './results/Si_conv_summary.json'
# }
```

**Creates:**
- `{prefix}_cutoff.csv`: ENCUT convergence data
- `{prefix}_kpoints.csv`: K-points convergence data
- `{prefix}_summary.json`: Summary with recommendations

### Thickness Convergence

#### `build_thickness_convergence_workgraph`

Test surface energy convergence with slab thickness.

```python
from quantum_lego.core.common.convergence import build_thickness_convergence_workgraph

wg = build_thickness_convergence_workgraph(
    bulk_structure_path='/path/to/bulk.cif',
    code_label='VASP-6.4.3@bohr',
    potential_family='PBE',
    potential_mapping={'Au': 'Au'},
    miller_indices=[1, 1, 1],
    layer_counts=[3, 5, 7, 9, 11],
    bulk_parameters={...},
    bulk_options={...},
    convergence_threshold=0.01,  # J/m²
    max_concurrent_jobs=4,
)
wg.submit()
```

### Thickness Convergence Visualization

#### `print_thickness_convergence_summary`

Print a formatted table of thickness convergence results.

```python
from quantum_lego.core.common.convergence import print_thickness_convergence_summary

print_thickness_convergence_summary(wg.pk)  # Using PK
print_thickness_convergence_summary(wg)     # Using WorkGraph
```

**Output:**
```
══════════════════════════════════════════════════════════════════════
          THICKNESS CONVERGENCE TEST RESULTS
══════════════════════════════════════════════════════════════════════
Structure: Au4 (4 atoms)
Miller indices: (1 1 1)
Threshold: 10.0 mJ/m²
──────────────────────────────────────────────────────────────────────

Slab Thickness Convergence:
┌─────────┬───────────────────┬──────────────┬───────────┐
│ Layers  │ Surface Energy    │ ΔE from prev │ Converged │
│         │ (J/m²)            │ (mJ/m²)      │           │
├─────────┼───────────────────┼──────────────┼───────────┤
│       3 │            0.8521 │         0.00 │ ─         │
│       5 │            0.7892 │        62.90 │ ✗         │
│       7 │            0.7756 │        13.60 │ ✗         │
│       9 │            0.7723 │         3.30 │ ✓         │
│      11 │            0.7715 │         0.80 │ ✓         │
└─────────┴───────────────────┴──────────────┴───────────┘

✓ Converged at 9 layers
→ Recommended: 9 layers
══════════════════════════════════════════════════════════════════════
```

#### `plot_thickness_convergence`

Generate a thickness convergence plot.

```python
from quantum_lego.core.common.convergence import plot_thickness_convergence

fig = plot_thickness_convergence(wg.pk)  # Display interactively
fig = plot_thickness_convergence(wg, save_path='thickness_conv.png')  # Save to file
```

#### `export_thickness_convergence_data`

Export thickness convergence data to CSV and JSON.

```python
from quantum_lego.core.common.convergence import export_thickness_convergence_data

files = export_thickness_convergence_data(wg.pk, './results', prefix='Au_111')
# Creates: Au_111.csv, Au_111_summary.json
```

## Input Configuration

### `builder_inputs` Structure

```python
builder_inputs = {
    'parameters': {
        'incar': {
            'prec': 'Accurate',
            'ismear': 0,         # 0 for semiconductors, 1 for metals
            'sigma': 0.05,
            'ediff': 1e-6,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
            'nelm': 100,
            'algo': 'Normal',
        }
    },
    'options': {
        'resources': {
            'num_machines': 1,
            'num_cores_per_machine': 40,  # PBS
            # or 'num_mpiprocs_per_machine': 4  # for hybrid MPI+OpenMP
        },
        'queue_name': 'par40',
        # 'custom_scheduler_commands': '...'  # for special clusters
    },
    'kpoints_spacing': 0.05,      # Starting value
    'potential_family': 'PBE',
    'potential_mapping': {'Si': 'Si'},
    'clean_workdir': True,
}
```

### `conv_settings` Structure

```python
conv_settings = {
    # ENCUT scan range
    'cutoff_start': 200,       # eV - starting ENCUT
    'cutoff_stop': 600,        # eV - ending ENCUT
    'cutoff_step': 50,         # eV - step size

    # K-points scan range
    'kspacing_start': 0.08,    # Å⁻¹ - coarsest grid
    'kspacing_stop': 0.02,     # Å⁻¹ - finest grid
    'kspacing_step': 0.01,     # Å⁻¹ - step size (positive; code subtracts internally)

    # Fixed values during the other scan
    'cutoff_kconv': 450,       # ENCUT used during k-points scan
    'kspacing_cutconv': 0.03,  # k-spacing used during ENCUT scan
}
```

**Default values:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `cutoff_start` | 200 | Starting ENCUT (eV) |
| `cutoff_stop` | 800 | Ending ENCUT (eV) |
| `cutoff_step` | 50 | ENCUT step (eV) |
| `kspacing_start` | 0.08 | Coarsest k-spacing (Å⁻¹) |
| `kspacing_stop` | 0.02 | Finest k-spacing (Å⁻¹) |
| `kspacing_step` | 0.01 | K-spacing step (Å⁻¹) |
| `cutoff_kconv` | 520 | Fixed ENCUT for k-points scan |
| `kspacing_cutconv` | 0.03 | Fixed k-spacing for ENCUT scan |

## Usage Examples

### Basic Si Convergence Test (bohr cluster)

```python
#!/usr/bin/env python
"""Si convergence test on bohr cluster (par40 queue)."""

from aiida import orm, load_profile
from ase.build import bulk
from quantum_lego.core.common.convergence import (
    build_convergence_workgraph,
    print_convergence_summary,
    plot_convergence,
)

load_profile()

# Create Si structure
ase_si = bulk('Si', 'diamond', a=5.431)
structure = orm.StructureData(ase=ase_si)

# VASP parameters for bohr cluster
builder_inputs = {
    'parameters': {
        'incar': {
            'prec': 'Accurate',
            'ismear': 0,
            'sigma': 0.05,
            'ediff': 1e-6,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        }
    },
    'options': {
        'resources': {
            'num_machines': 1,
            'num_cores_per_machine': 40,
        },
        'queue_name': 'par40',
    },
    'kpoints_spacing': 0.05,
    'potential_family': 'PBE',
    'potential_mapping': {'Si': 'Si'},
    'clean_workdir': True,
}

# Convergence scan settings
conv_settings = {
    'cutoff_start': 200,
    'cutoff_stop': 600,
    'cutoff_step': 50,
    'kspacing_start': 0.08,
    'kspacing_stop': 0.02,
    'kspacing_step': 0.01,
    'cutoff_kconv': 450,
    'kspacing_cutconv': 0.03,
}

# Build and submit
wg = build_convergence_workgraph(
    structure=structure,
    code_label='VASP-6.4.3@bohr',
    builder_inputs=builder_inputs,
    conv_settings=conv_settings,
    convergence_threshold=0.001,  # 1 meV/atom
    name='Si_convergence',
)

wg.submit(wait=False)
print(f"Submitted: PK {wg.pk}")
print(f"Monitor: verdi process show {wg.pk}")

# After completion:
# print_convergence_summary(wg.pk)
# plot_convergence(wg.pk, save_path='Si_convergence.png')
```

### Metal Convergence (obelix cluster)

```python
from aiida import orm, load_profile
from ase.build import bulk
from quantum_lego.core.common.convergence import build_convergence_workgraph

load_profile()

# Create Au FCC structure
ase_au = bulk('Au', 'fcc', a=4.08)
structure = orm.StructureData(ase=ase_au)

# Obelix cluster configuration (hybrid MPI+OpenMP)
builder_inputs = {
    'parameters': {
        'incar': {
            'prec': 'Accurate',
            'ismear': 1,         # Methfessel-Paxton for metals
            'sigma': 0.2,
            'ediff': 1e-6,
            'lreal': 'Auto',
            'lwave': False,
            'lcharg': False,
        }
    },
    'options': {
        'resources': {
            'num_machines': 1,
            'num_mpiprocs_per_machine': 4,  # Hybrid mode
        },
        'custom_scheduler_commands': '''#PBS -l cput=90000:00:00
#PBS -l nodes=1:ppn=88:skylake
#PBS -j oe
#PBS -N Au_conv''',
    },
    'kpoints_spacing': 0.05,
    'potential_family': 'PBE',
    'potential_mapping': {'Au': 'Au'},
    'clean_workdir': True,
}

wg = build_convergence_workgraph(
    structure=structure,
    code_label='VASP-6.5.1-idefix@obelix',
    builder_inputs=builder_inputs,
    convergence_threshold=0.001,
    name='Au_convergence',
)

wg.submit()
```

## Workflow Architecture

```
WorkGraph<convergence_test>
├── convergence_scan (vasp.v2.converge WorkChain)
│   ├── ENCUT scan: 200, 250, 300, ... eV
│   └── k-points scan: 0.08, 0.07, 0.06, ... Å⁻¹
├── analyze_cutoff (calcfunction)
│   └── Determines converged ENCUT
├── analyze_kpoints (calcfunction)
│   └── Determines converged k-spacing
└── extract_recommendations (calcfunction)
    └── Final recommendations with safety margin
```

## Output Structure

After completion, `verdi process show <PK>` displays:

```
Outputs                  PK      Type
-----------------------  ------  ------
cutoff_conv_data         XXXXX   Dict
kpoints_conv_data        XXXXX   Dict
cutoff_analysis          XXXXX   Dict
kpoints_analysis         XXXXX   Dict
recommendations          XXXXX   Dict
```

### `recommendations` Dict contents:

```json
{
    "recommended_cutoff": 450,
    "recommended_kspacing": 0.03,
    "threshold_used": 0.001,
    "cutoff_converged": true,
    "kpoints_converged": true,
    "converged_cutoff_raw": 400,
    "converged_kspacing_raw": 0.04,
    "summary": "ENCUT: 450 eV (converged at 400 eV)\nk-spacing: 0.03 A^-1 (converged at 0.04 A^-1)\nThreshold: 1.0 meV/atom"
}
```

## VASP Parameter Recommendations

### For Semiconductors/Insulators

```python
'incar': {
    'ismear': 0,      # Gaussian smearing
    'sigma': 0.05,    # Small smearing width
    'prec': 'Accurate',
}
```

### For Metals

```python
'incar': {
    'ismear': 1,      # Methfessel-Paxton (or 2)
    'sigma': 0.2,     # Moderate smearing
    'prec': 'Accurate',
}
```

### General Tips

- Start ENCUT scan below ENMAX from POTCAR
- Use a well-converged k-spacing for ENCUT scan (`kspacing_cutconv`)
- Use a well-converged ENCUT for k-points scan (`cutoff_kconv`)
- For production, add 50-100 eV safety margin to converged ENCUT
- For production, use slightly denser k-grid than converged value

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| NOT CONVERGED (ENCUT) | Range too narrow | Increase `cutoff_stop` |
| NOT CONVERGED (k-points) | Range too narrow | Decrease `kspacing_stop` |
| Large energy oscillations | Numerical issues | Check POTCAR, increase ENCUT |
| Workflow fails | VASP error | Check `verdi calcjob outputcat <PK>` |
| Missing outputs | Incomplete workflow | Check `verdi process report <PK>` |
| Plot won't display | No GUI backend | Use `show=False`, save to file |

## Dependencies

- `aiida-core`: Workflow management
- `aiida-workgraph`: Task orchestration
- `aiida-vasp` (>= 3.0): VASP plugin with `vasp.v2.converge`
- `matplotlib`: Plotting (optional, for `plot_convergence`)
- `ase`: Structure manipulation

## See Also

- `teros.core.surface_energy` - Metal surface energy calculations
- `teros.core.custom_calculation` - Generic VASP calculations
- [AiiDA-VASP documentation](https://aiida-vasp.readthedocs.io/)
- [VASP Wiki - Precision](https://www.vasp.at/wiki/index.php/Category:Precision)
