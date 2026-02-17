# 06 Surface

This section focuses on slab and surface workflows.

## Files

- `surface_enumeration.py`: Enumerate symmetrically distinct Miller indices for Wulff construction.
- `thickness_convergence.py`: Bulk+surface sequential workflow for slab thickness convergence.
- `binary_surface_thermo/`: Binary oxide surface thermodynamics (SnO2(110)) using
  `o2_reference_energy` + `surface_gibbs_energy` bricks, with a plotting script.

## Run

```bash
python examples/06_surface/surface_enumeration.py
python examples/06_surface/thickness_convergence.py
python examples/06_surface/binary_surface_thermo/run_surface_thermo_prepare.py
```
