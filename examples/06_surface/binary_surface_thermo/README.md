# Binary oxide surface thermodynamics (SnO2 example)

End-to-end example showing **working** surface thermodynamics for a **binary oxide**
using Quantum Lego bricks:

- `o2_reference_energy`: computes an effective O₂ reference energy via water splitting (H₂ + H₂O)
- `surface_terminations`: generates symmetrized slab terminations
- `dynamic_batch`: relaxes all terminations in parallel
- `formation_enthalpy`: computes ΔHf from Sn and O references
- `surface_gibbs_energy`: computes γ(ΔμO) for each termination (binary oxide case)

## Run

```bash
python examples/06_surface/binary_surface_thermo/run_surface_thermo_prepare.py
```

The script prints a WorkGraph PK. Then plot γ vs ΔμO:

```bash
python examples/06_surface/binary_surface_thermo/plot_surface_thermodynamics.py --pk <PK>
```

Outputs are written next to the plotting script (PDF + CSV).

Plotting requires `matplotlib` (and uses `seaborn` if available).
