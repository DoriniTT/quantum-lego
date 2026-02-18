# 03 Batch

This section demonstrates parallel single-point calculations.

## Files

- `compare_structures.py`: Run static SCF on two structures via `quick_vasp_batch`.
- `dynamic_batch_example.py`: Dynamic parallel relaxation of all SnO2(110) surface terminations using the `dynamic_batch` brick (fan-out from `surface_terminations`).

## Run

```bash
python examples/03_batch/compare_structures.py
python examples/03_batch/dynamic_batch_example.py
```
