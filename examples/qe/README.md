# QE Brick Setup and Testing Guide

This directory contains examples for using the QE (Quantum ESPRESSO) brick in the Lego module. Before running any QE calculations, you need to complete the following setup steps.

## 1. Configure a QE Code

You need to set up an AiiDA code pointing to your Quantum ESPRESSO `pw.x` binary. Use the following command:

```bash
verdi code create core.remote.run_job \
    --label pw@<cluster> \
    --description "Quantum ESPRESSO pw.x" \
    --computer <computer-name> \
    --filepath-executable /path/to/pw.x
```

**Example for local testing:**
```bash
verdi code create core.remote.run_job \
    --label pw@localhost \
    --description "Quantum ESPRESSO pw.x (local)" \
    --computer localhost \
    --filepath-executable /usr/bin/pw.x
```

**Example for cluster (Obelix):**
```bash
verdi code create core.remote.run_job \
    --label pw@obelix \
    --description "Quantum ESPRESSO pw.x (Obelix)" \
    --computer obelix \
    --filepath-executable /path/to/pw.x
```

Verify the code was created:
```bash
verdi code list
```

You can also use an existing code if one is available. List available codes with:
```bash
verdi code list --all
```

## 2. Set Up Pseudopotential Family

The QE brick requires explicit pseudopotential family specification. You need to have a pseudopotential family installed in AiiDA.

### Check Available Families

```bash
verdi data pseudo family list
```

### Common Pseudopotential Families

- **SSSP** (Standard Solid State Pseudopotentials)
  - Versions: 1.1, 1.2, 1.3
  - Functional: PBE, PBEsol
  - Precision: efficiency, precision
  - Example: `SSSP/1.3/PBE/efficiency`

- **GBRV** (Garrity-Bennett-Rabe-Vanderbilt)
  - Versions: 1.4, 1.5
  - Example: `GBRV/1.5/PBE/USPP`

### Install SSSP (Recommended)

```bash
aiida-pseudo install sssp -v 1.3 -f PBE -p efficiency
```

Verify installation:
```bash
verdi data pseudo family list
```

You should see output like:
```
PK  Label                     Type  Count
---  --------                 ----  -----
1   SSSP/1.3/PBE/efficiency  PAW   86
```

## 3. Test the Example

Once you have configured the code and pseudopotential family, test the QE brick with the example script:

### Local Test (Recommended First Step)

Edit `run_qe_si.py` and update:
```python
code_label = 'pw@localhost'
pseudo_family = 'SSSP/1.3/PBE/efficiency'  # Use your installed family
```

Then run:
```bash
source ~/envs/aiida/bin/activate
python examples/lego/qe/run_qe_si.py
```

### Monitor Execution

In another terminal:
```bash
verdi daemon logshow
verdi process list -a
verdi process show <PK>
```

### Check Results

After the calculation completes:
```python
from quantum_lego import get_results
results = get_results(<PK>)
print(results)
```

## 4. Common Issues and Troubleshooting

### "Code not found"
Make sure the code label matches your configured code:
```bash
verdi code list
```

### "Pseudopotential family not found"
Verify the pseudo family is installed:
```bash
verdi data pseudo family list
```

Note: Family names are case-sensitive. Use exact name from `verdi data pseudo family list`.

### "pw.x executable not found"
The filepath in the code configuration must be correct. On a cluster, you may need to load the QE module first:
```bash
# In your custom_scheduler_commands:
#PBS -l modules=quantum_espresso
```

### Calculation fails with "input_structure required"
When using `quick_qe()`:
```python
structure = orm.load_node(<PK>)  # Load existing structure
wg = quick_qe(structure=structure, ...)
```

Or create a test structure:
```python
from ase.build import bulk
from aiida.orm import StructureData
si = bulk('Si', 'diamond', a=5.43)
structure = StructureData(ase=si)
structure.store()
```

## 5. Running Sequential QE Workflows

For multi-stage pipelines (SCF → relax → DOS), use `quick_qe_sequential()`:

```python
from quantum_lego import quick_qe_sequential

stages = [
    {
        'name': 'scf',
        'type': 'qe',
        'parameters': {
            'CONTROL': {'calculation': 'scf'},
            'SYSTEM': {'ecutwfc': 50},
        },
    },
    {
        'name': 'relax',
        'type': 'qe',
        'structure_from': 'scf',
        'parameters': {
            'CONTROL': {'calculation': 'relax'},
            'SYSTEM': {'ecutwfc': 50},
        },
        'restart': 'scf',
    },
]

wg = quick_qe_sequential(
    structure=structure,
    code_label='pw@localhost',
    pseudo_family='SSSP/1.3/PBE/efficiency',
    stages=stages,
)
```

## Next Steps

1. ✅ Configure QE code (done above)
2. ✅ Install pseudopotential family (done above)
3. ✅ Run `examples/lego/qe/run_qe_si.py` to test
4. Modify example or create new script for your own structures
5. Check `teros/core/lego/bricks/qe.py` for advanced configuration options

## References

- [Quantum ESPRESSO Documentation](https://www.quantum-espresso.org/Doc/INPUT_PW.html)
- [AiiDA-quantumespresso Plugin](https://aiida-quantumespresso.readthedocs.io/)
- [AiiDA-pseudo Package](https://aiida-pseudo.readthedocs.io/)
