# Plan: `fukui_analysis` Brick for the Lego Module

## Overview

Create a new brick that takes the 4 CHGCAR files from a `batch` stage's retrieved outputs, runs FukuiGrid `Fukui_interpolation`, and exposes the resulting `CHGCAR_FUKUI.vasp` as a `SinglefileData` output on the WorkGraph.

This replaces the manual post-processing step (`extract_and_run_fukui.py`) with an automated, provenance-tracked AiiDA calcfunction.

## Stage Configuration (user-facing API)

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

## Files to Create/Modify

### 1. Create: `bricks/fukui_analysis.py`

New brick module following the standard 5-function pattern + the calcfunction.

**`validate_stage(stage, stage_names)`**:
- Check `batch_from` exists in `stage_names`
- Check `fukui_type` is `'minus'` or `'plus'`
- Check `delta_n_map` is a non-empty dict with exactly 4 entries

**`create_stage_tasks(wg, stage, stage_name, context)`**:
1. Get the batch stage's `calc_tasks` from `context['stage_tasks'][batch_from]`
2. Sort calc_labels by delta_n **descending** (FukuiGrid requirement)
3. Apply sign convention: negate δN for `fukui_type='minus'`, keep positive for `'plus'`
4. Build `orm.Dict` config with sorted delta_n array
5. Wire the 4 sorted `retrieved` FolderData outputs from the batch VASP tasks into the calcfunction
6. Return task references

```python
batch_tasks = context['stage_tasks'][batch_from]
calc_tasks = batch_tasks['calc_tasks']  # dict: calc_label -> vasp_task

# Sort by delta_n descending
sorted_items = sorted(delta_n_map.items(), key=lambda x: x[1], reverse=True)

# Wire retrieved outputs in sorted order
retrieved_1 = calc_tasks[sorted_items[0][0]].outputs.retrieved
retrieved_2 = calc_tasks[sorted_items[1][0]].outputs.retrieved
retrieved_3 = calc_tasks[sorted_items[2][0]].outputs.retrieved
retrieved_4 = calc_tasks[sorted_items[3][0]].outputs.retrieved
```

**`run_fukui_interpolation` calcfunction** (`@task.calcfunction(outputs=['fukui_chgcar'])`):
- Inputs: `retrieved_1`, `retrieved_2`, `retrieved_3`, `retrieved_4` (each `orm.FolderData`), `config` (`orm.Dict`)
- Logic:
  1. Create tempdir
  2. Extract CHGCAR from each FolderData → named files (e.g., `CHGCAR_0.15`, `CHGCAR_0.10`, etc.)
  3. Import FukuiGrid via path relative to teros: `Path(__file__).parents[3] / 'external' / 'FukuiGrid'`
  4. `os.chdir(tmpdir)` and call `Fukui_interpolation(file1, file2, file3, file4, dn=sorted_dn)`
  5. Verify `CHGCAR_FUKUI.vasp` was created
  6. Return `{'fukui_chgcar': orm.SinglefileData(file=path_to_fukui_chgcar)}`
  7. Cleanup tempdir in `finally` block

**`expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None)`**:
- Expose `fukui_chgcar` on `wg.outputs`
- With namespace: `wg.outputs.{ns}.fukui_analysis.fukui_chgcar`
- Without namespace (flat): `wg.outputs.{stage_name}_fukui_chgcar`

**`get_stage_results(wg_node, wg_pk, stage_name, namespace_map=None)`**:
- Extract the SinglefileData from outputs (direct attribute access)
- Fallback: traverse CALL_CALC links to find the calcfunction node and its CREATE outputs

**`print_stage_results(index, stage_name, stage_result)`**:
- Print file PK, size, and fukui_type

### 2. Modify: `bricks/connections.py`

Add `FUKUI_ANALYSIS_PORTS` dict:

```python
FUKUI_ANALYSIS_PORTS = {
    'inputs': {
        'batch_retrieved': {
            'type': 'retrieved',
            'required': True,
            'source': 'batch_from',
            'compatible_bricks': ['batch'],
            'prerequisites': {
                'retrieve': ['CHGCAR'],
            },
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

Add to `ALL_PORTS`:
```python
ALL_PORTS = {
    ...
    'fukui_analysis': FUKUI_ANALYSIS_PORTS,
}
```

### 3. Modify: `bricks/__init__.py`

```python
from . import vasp, dos, batch, bader, convergence, thickness, hubbard_response, hubbard_analysis, aimd, fukui_analysis

BRICK_REGISTRY = {
    ...
    'fukui_analysis': fukui_analysis,
}
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Number of calculations | Exactly 4 | FukuiGrid's `Fukui_interpolation` takes exactly 4 files |
| `delta_n_map` | Explicit in config | More flexible and explicit, no magic label parsing |
| FukuiGrid location | Path relative to teros | `Path(__file__).parents[3] / 'external' / 'FukuiGrid'` |
| Calcfunction outputs | `SinglefileData` | Standard AiiDA type for file outputs with provenance |

## Delta-N Sorting Convention

FukuiGrid expects files sorted by |δN| **descending**:

For **f⁻** (`fukui_type='minus'`):
- Files in order: CHGCAR_0.15, CHGCAR_0.10, CHGCAR_0.05, CHGCAR_0.00
- δN passed to FukuiGrid: `[-0.15, -0.10, -0.05, 0.00]`

For **f⁺** (`fukui_type='plus'`):
- Files in order: CHGCAR_0.15, CHGCAR_0.10, CHGCAR_0.05, CHGCAR_0.00
- δN passed to FukuiGrid: `[0.15, 0.10, 0.05, 0.00]`

## Connection to Batch Outputs

The batch brick's `create_stage_tasks` returns:
```python
{
    'calc_tasks': {calc_label: vasp_task, ...},
    'energy_tasks': {calc_label: energy_task, ...},
    'structure': input_structure,
}
```

The fukui_analysis brick accesses: `calc_tasks[calc_label].outputs.retrieved`

## Example Workflow

```python
stages = [
    {'name': 'relax_rough', 'type': 'vasp', 'incar': incar_rough, ...},
    {'name': 'relax_fine', 'type': 'vasp', 'incar': incar_fine, ...},
    {
        'name': 'fukui_minus_calcs',
        'type': 'batch',
        'structure_from': 'relax_fine',
        'base_incar': incar_static_fukui,
        'retrieve': ['CHGCAR', 'OUTCAR'],
        'calculations': {
            'neutral':   {'incar': {'nelect': nelect}},
            'delta_005': {'incar': {'nelect': nelect - 0.05}},
            'delta_010': {'incar': {'nelect': nelect - 0.10}},
            'delta_015': {'incar': {'nelect': nelect - 0.15}},
        },
    },
    {
        'name': 'fukui_minus_analysis',
        'type': 'fukui_analysis',
        'batch_from': 'fukui_minus_calcs',
        'fukui_type': 'minus',
        'delta_n_map': {
            'neutral':   0.00,
            'delta_005': 0.05,
            'delta_010': 0.10,
            'delta_015': 0.15,
        },
    },
]
```

After execution, the CHGCAR_FUKUI.vasp is available as:
```python
wg_node.outputs.fukui_minus_analysis_fukui_chgcar  # SinglefileData
```

## Verification Checklist

- [ ] `validate_stage` catches missing `batch_from`, invalid `fukui_type`, wrong number of entries in `delta_n_map`
- [ ] `validate_connections()` validates batch → fukui_analysis connection (`compatible_bricks` + `prerequisites`)
- [ ] Integration: add `fukui_analysis` stage after `batch` in a workflow, verify `CHGCAR_FUKUI.vasp` appears as `SinglefileData` output
- [ ] Manual: `verdi process show <PK>` shows the calcfunction with `SinglefileData` output

## Reference Files

- Existing batch brick: `teros/core/lego/bricks/batch.py`
- Existing bader brick (similar post-processing pattern): `teros/core/lego/bricks/bader.py`
- Current manual script: `calculos/fukui/learning/sno2/calculos/calcs/pristine/results/fukui_analysis/extract_and_run_fukui.py`
- FukuiGrid module: `teros/external/FukuiGrid/FukuiGrid.py` (function: `Fukui_interpolation`)
- Port declarations: `teros/core/lego/bricks/connections.py`
- Brick registry: `teros/core/lego/bricks/__init__.py`

---

*Created: 2026-02-03*
*Status: PLANNING*
