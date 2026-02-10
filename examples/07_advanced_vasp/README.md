# 07 Advanced VASP

This section covers specialized VASP workflows.

## Files

- `bader_analysis.py`: SCF + Bader analysis workflow.
- `hubbard_u_sno2.py`: Four-stage Hubbard U example on SnO2.
- `hubbard_u_nio.py`: NiO Hubbard U via the `quick_hubbard_u` convenience API.
- `sequential_relax_then_u.py`: Relaxation followed by response/analysis stages.
- `neb_pipeline.py`: Multi-stage NEB pipeline with generated images.

## Run

```bash
python examples/07_advanced_vasp/bader_analysis.py
python examples/07_advanced_vasp/hubbard_u_sno2.py
python examples/07_advanced_vasp/hubbard_u_nio.py
python examples/07_advanced_vasp/sequential_relax_then_u.py
python examples/07_advanced_vasp/neb_pipeline.py
```
