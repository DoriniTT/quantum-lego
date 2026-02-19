# 12 Dimer

This section demonstrates the Improved Dimer Method (IDM) for transition-state (TS) refinement using VASP's `IBRION=44` tag.

## Files

- `dimer_ammonia.py`: Full IDM workflow for the ammonia nitrogen-inversion reaction (from the VASP wiki). Uses three sequential stages: vibrational analysis → IDM TS search → TS verification.
- `TROUBLESHOOTING.md`: Common issues and solutions for IDM calculations.

## Run

```bash
python examples/12_dimer/dimer_ammonia.py
```

## Workflow

1. **`vib`** — Vibrational analysis (`IBRION=5`) to obtain the dimer axis (eigenvectors of the hardest imaginary mode).
2. **`idm_ts`** — IDM TS refinement (`IBRION=44`). The dimer axis is parsed from the `vib` OUTCAR at submission time and injected into POSCAR via scheduler `prepend_text`.
3. **`vib_verify`** — Vibrational analysis on the relaxed TS to confirm a first-order saddle point (exactly one large imaginary frequency).

## Key Diagnostics

- `idm_ts.dimer_curvatures` — should be negative throughout the optimisation.
- `vib_verify` OUTCAR — should have exactly one large imaginary frequency (`f/i` mode); small `f/i < 5 cm⁻¹` modes with large `dx` and near-zero `dy`, `dz` are translational artefacts.

## Reference

- [VASP wiki: Improved Dimer Method](https://vasp.at/wiki/Improved_dimer_method)
