# 09 Other Codes

This section covers non-VASP backends.

## Setup Notes (QE)

Before running QE examples, configure:

1. A QE `pw.x` AiiDA code (for example `pw@localhost`).
2. A pseudopotential family (for example `SSSP/1.3/PBE/efficiency`).

Useful commands:

```bash
verdi code list
verdi data pseudo family list
aiida-pseudo install sssp -v 1.3 -f PBE -p efficiency
```

## Files

- `qe_single_and_pipeline.py`: single QE SCF and two-stage QE pipeline.
- `cp2k_pipeline.py`: CP2K geometry optimization + single-point, and optional MD.

## Run

```bash
python examples/09_other_codes/qe_single_and_pipeline.py
python examples/09_other_codes/qe_single_and_pipeline.py sequential
python examples/09_other_codes/cp2k_pipeline.py
python examples/09_other_codes/cp2k_pipeline.py md
```
