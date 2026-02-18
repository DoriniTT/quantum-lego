# 11 NEB

This section demonstrates Nudged Elastic Band (NEB) and CI-NEB pathways for finding transition states and minimum energy paths.

## Files

- `neb_pt_step_edge.py`: Full two-stage NEB pipeline (regular NEB → CI-NEB) for N diffusion on a Pt(211) step-edge surface. Uses `generate_neb_images` + `neb` bricks with IDPP interpolation and the VTST climbing-image extension.

## Run

```bash
python examples/11_neb/neb_pt_step_edge.py
```

## Requirements

- VASP compiled with the VTST patch (for `IOPT`/`IBRION=3` and `LCLIMB`).
- At least 3 compute nodes × 40 cores for the NEB stages (7 images + 2 endpoints).
- PBE POTCAR library with `Pt` and `N` entries.
- Endpoint structures (see the structure-generation snippet in `neb_pt_step_edge.py`).

## Notes

- Set `LCLIMB=False` for the first NEB stage and `LCLIMB=True` for the CI-NEB restart.
- Use `restart='neb_stage1'` in the CI-NEB stage to continue from the converged NEB path.
- After completion, extract the minimum-energy path and barrier with `print_sequential_results(pk)`.
