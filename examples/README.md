# Examples

This directory is organized as a numbered learning path from simple to advanced workflows.

## Shared Helpers

- `examples/_shared/config.py`: profile setup, default code labels, cluster defaults, canonical structures path.
- `examples/_shared/structures.py`: convenience loaders (`load_sno2`, `load_sno2_pnnm`, `load_nio`, `create_si_structure`).
- `examples/structures/`: canonical `.vasp` inputs used across examples.

## Progression

1. `01_getting_started`
2. `02_dos`
3. `03_batch`
4. `04_sequential`
5. `05_convergence`
6. `06_surface` — surface workflows including NEB (`neb_pt_step_edge.py`)
7. `07_advanced_vasp`
8. `08_aimd`
9. `09_other_codes`
10. `10_utilities`

## Quick Start

```bash
python examples/01_getting_started/single_vasp.py
python examples/04_sequential/mixed_dos_sources.py
python examples/09_other_codes/qe_single_and_pipeline.py
```

## Notes

- Set profile via `QUANTUM_LEGO_PROFILE` (or rely on your AiiDA default profile).
- Set default VASP code via `QUANTUM_LEGO_VASP_CODE`.
- For QE/CP2K examples, update code labels and pseudo/basis files for your environment.
