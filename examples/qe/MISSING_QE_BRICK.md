# Missing QE Brick Setup Requirements

This document outlines what is **required** to use the QE brick before running any calculations.

## Missing Requirement 1: Configure a QE Code

You need to set up an AiiDA code pointing to your Quantum ESPRESSO `pw.x` binary.

### Command to Create Code

```bash
verdi code create core.remote.run_job \
    --label pw@<cluster> \
    --description "Quantum ESPRESSO pw.x" \
    --computer <computer-name> \
    --filepath-executable /path/to/pw.x
```

### Example: Local Testing

```bash
verdi code create core.remote.run_job \
    --label pw@localhost \
    --description "Quantum ESPRESSO pw.x (local)" \
    --computer localhost \
    --filepath-executable /usr/bin/pw.x
```

### Example: Obelix Cluster

```bash
verdi code create core.remote.run_job \
    --label pw@obelix \
    --description "Quantum ESPRESSO pw.x (Obelix)" \
    --computer obelix \
    --filepath-executable /path/to/pw.x
```

### Verify Code Creation

```bash
verdi code list
```

---

## Missing Requirement 2: Install Pseudopotential Family

The QE brick requires explicit pseudopotential family specification. You must have a pseudopotential family installed.

### Check Available Families

```bash
verdi data pseudo family list
```

### Install SSSP (Recommended)

```bash
aiida-pseudo install sssp -v 1.3 -f PBE -p efficiency
```

### Verify Installation

```bash
verdi data pseudo family list
```

You should see output like:
```
PK  Label                     Type  Count
---  --------                 ----  -----
1   SSSP/1.3/PBE/efficiency  PAW   86
```

### Common Pseudopotential Families

- **SSSP/1.3/PBE/efficiency** (recommended)
- **SSSP/1.3/PBE/precision**
- **SSSP/1.1/PBEsol/efficiency**
- **GBRV/1.5/PBE/USPP**

---

## Missing Requirement 3: Test with Example Script

Once configured, test the QE brick using the provided example.

### Edit Configuration

Open `run_qe_si.py` and update to match your setup:

```python
code_label = 'pw@localhost'  # Your code label
pseudo_family = 'SSSP/1.3/PBE/efficiency'  # Your pseudo family
```

### Run Example

```bash
source ~/envs/aiida/bin/activate
python run_qe_si.py
```

### Monitor Execution

```bash
verdi daemon logshow
verdi process show <PK>
```

### Check Results

```python
from quantum_lego import get_results
results = get_results(<PK>)
print(results)
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Command 'verdi' not found" | Activate AiiDA environment: `source ~/envs/aiida/bin/activate` |
| "Code not found" | Check code exists: `verdi code list` |
| "Pseudopotential family not found" | Install SSSP: `aiida-pseudo install sssp -v 1.3 -f PBE -p efficiency` |
| "pw.x executable not found" | Verify filepath in code: `verdi code show <code_label>` |
| Calculation fails | Check logs: `verdi process report <PK>` |

---

## Summary Checklist

- [ ] AiiDA environment activated
- [ ] QE `pw.x` binary available on system/cluster
- [ ] AiiDA code created with `verdi code create`
- [ ] Pseudopotential family installed with `aiida-pseudo install`
- [ ] Example script tested successfully
- [ ] Results extracted and verified

Once all items are checked, the QE brick is ready to use!
