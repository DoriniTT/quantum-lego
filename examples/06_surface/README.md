# 06 Surface

This section focuses on slab and surface workflows.

## Files

- `surface_enumeration.py`: Enumerate symmetrically distinct Miller indices for Wulff construction.
- `thickness_convergence.py`: Bulk+surface sequential workflow for slab thickness convergence.
- `binary_surface_thermo/`: Binary oxide surface thermodynamics (SnO2(110)) using
  `o2_reference_energy` + `surface_gibbs_energy` bricks, with a plotting script.
- `o2_reference_example.py`: Standalone example for the `o2_reference_energy` brick — O2 reference energy via the water-splitting reaction (H2 + H2O).
- `formation_enthalpy_example.py`: Standalone example for the `formation_enthalpy` brick — compute ΔHf(SnO2) from bulk and reference energies.
- `surface_gibbs_example.py`: Focused surface thermodynamics pipeline demonstrating `surface_terminations` + `dynamic_batch` + `formation_enthalpy` + `surface_gibbs_energy` bricks for SnO2(110).

## Run

```bash
python examples/06_surface/surface_enumeration.py
python examples/06_surface/thickness_convergence.py
python examples/06_surface/o2_reference_example.py
python examples/06_surface/formation_enthalpy_example.py
python examples/06_surface/surface_gibbs_example.py
python examples/06_surface/binary_surface_thermo/run_surface_thermo_prepare.py
```
