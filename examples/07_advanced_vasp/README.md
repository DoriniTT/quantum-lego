# 07 Advanced VASP

This section covers specialized VASP workflows.

## Files

- `bader_analysis.py`: SCF + Bader analysis workflow.
- `hubbard_u_sno2.py`: Four-stage Hubbard U example on SnO2.
- `hubbard_u_nio.py`: NiO Hubbard U via the `quick_hubbard_u` convenience API.
- `hubbard_u_nio_afm_supercell.py`: NiO Hubbard U with explicit stages, AFM supercell, and `prepare_perturbed_structure`.
- `sequential_relax_then_u.py`: Relaxation followed by response/analysis stages.
- `neb_pipeline.py`: Multi-stage NEB pipeline with generated images.
- `birch_murnaghan_sno2.py`: Birch-Murnaghan EOS with coarse scan + refinement round.
- `hybrid_bands_and_dos_sno2.py`: HSE06 hybrid band structure + DOS (hybrid_bands + dos bricks).
- `plot_workgraph_bands_and_dos.py`: Plot bands + TDOS/PDOS from a finished WorkGraph.

## Run

```bash
python examples/07_advanced_vasp/bader_analysis.py
python examples/07_advanced_vasp/hubbard_u_sno2.py
python examples/07_advanced_vasp/hubbard_u_nio.py
python examples/07_advanced_vasp/hubbard_u_nio_afm_supercell.py
python examples/07_advanced_vasp/sequential_relax_then_u.py
python examples/07_advanced_vasp/neb_pipeline.py
python examples/07_advanced_vasp/birch_murnaghan_sno2.py
python examples/07_advanced_vasp/hybrid_bands_and_dos_sno2.py

# after it finishes:
python examples/07_advanced_vasp/plot_workgraph_bands_and_dos.py <WORKGRAPH_PK>
```
