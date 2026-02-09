# Hubbard U Module - TODO

⚠️ **STATUS: MODULE NOT YET FUNCTIONAL** ⚠️

This module requires essential fixes to match the VASP wiki reference implementation.
**Current implementation produces incorrect U values due to fundamental methodological issues.**

---

## Critical Issues (MUST FIX)

### Issue #1: POTCAR Structure for Single-Atom Perturbation (CRITICAL)

**Priority**: HIGHEST
**Difficulty**: HIGH
**Status**: NOT IMPLEMENTED

**Problem**: The linear response method requires applying the perturbation potential to **a single atom** to measure site-specific response. Current implementation applies potential to **all atoms** of the target species, which gives fundamentally wrong physics.

**VASP Wiki Reference** (`/home/trevizam/NiO_calcU/`):
```
POSCAR species line: 1 15 16
  ↳ Split Ni into 2 groups: 1 perturbed + 15 unperturbed

POTCAR structure:
  cat Ni/POTCAR Ni/POTCAR O/POTCAR
  ↳ 2× Ni + 1× O (three species)

INCAR:
  LDAUL  = 2 -1 -1   # d on Ni#1, none on Ni#2-16, none on O
  LDAUU  = V 0.0 0.0  # potential ONLY on atom 1
  LDAUJ  = V 0.0 0.0  # J must equal U for LDAUTYPE=3
```

**Current PS-TEROS** (`teros/core/u_calculation/utils.py:116-127`):
```python
# All Ni treated as one species
for species in all_species:
    if species == target_species:
        ldaul.append(ldaul_value)   # Applied to ALL Ni
        ldauu.append(-potential_value)  # Applied to ALL Ni - WRONG!
```

**Why This Matters**:
- Linear response measures how **one atom's** d-occupation responds to a local potential
- Applying V to all atoms → collective response, not site-specific
- This is a **fundamental physics error**, not a minor implementation detail
- Results will be completely wrong (incorrect U magnitude, possibly wrong sign)

**Implementation Strategy**:

1. **Modify POSCAR/StructureData** to split target species:
   ```python
   # For NiO with 4 Ni + 4 O:
   # Split into: 1 Ni (perturbed) + 3 Ni (unperturbed) + 4 O
   # Species symbols: ['Ni', 'Ni', 'O']  # Note: same element, different POTCAR
   ```

2. **Generate POTCAR with duplicated target species**:
   ```python
   # Current: ['Ni', 'O'] → POTCAR has Ni + O
   # Needed:  ['Ni', 'Ni', 'O'] → POTCAR has Ni + Ni + O (concatenated)
   ```

3. **Build LDAU arrays for split species**:
   ```python
   def build_ldau_arrays_single_atom(...):
       # For ['Ni', 'Ni', 'O'] with target='Ni':
       ldaul = [2, -1, -1]     # d on first Ni only
       ldauu = [V, 0.0, 0.0]   # potential on first Ni only
       ldauj = [V, 0.0, 0.0]   # J equals U (see Issue #2)
   ```

4. **Handle atom indexing**:
   - First atom of target species gets potential
   - Remaining atoms of same element get LDAUL=-1, LDAUU=0

**References**:
- VASP wiki: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
- Example: `/home/trevizam/NiO_calcU/POSCAR` (line 6: `1 15 16`)
- Example: `/home/trevizam/NiO_calcU/POTCAR` (grep TITEL shows 2× Ni + 1× O)

---

### Issue #2: LDAUJ Parameter (CRITICAL)

**Priority**: HIGH
**Difficulty**: LOW
**Status**: INCORRECT (always 0.0, should equal LDAUU)

**Problem**: For LDAUTYPE=3 (linear response), LDAUJ must equal LDAUU to apply the same potential to both spin channels. Current implementation always sets LDAUJ=0.

**VASP Wiki Reference** (`/home/trevizam/NiO_calcU/doall.sh:68,86`):
```bash
LDAUU = $v 0.00 0.00
LDAUJ = $v 0.00 0.00   # J equals U for all potentials
```

**Current PS-TEROS** (`teros/core/u_calculation/utils.py:84,122`):
```python
def build_ldau_arrays(
    ...
    ldauj_value: float = 0.0,  # DEFAULT IS WRONG!
):
    ...
    ldauj.append(ldauj_value)  # Always 0 unless explicitly overridden
```

**Why This Matters**:
- LDAUTYPE=3 uses spherical potential on d-manifold
- LDAUU applies to spin-up d-states, LDAUJ to spin-down
- For symmetric perturbation, both must equal V
- Wrong LDAUJ → asymmetric spin response → incorrect χ₀ and χ → wrong U

**Physical Impact**:
```
Correct:   χ₀(V) measures total d-occupation response with symmetric V
Incorrect: Different potentials on spin channels → spin-dependent artifact
```

**Implementation Strategy**:

1. **Update function signature** (`teros/core/u_calculation/utils.py:84`):
   ```python
   # BEFORE:
   ldauj_value: float = 0.0,

   # AFTER:
   ldauj_value: t.Optional[float] = None,  # None means "same as LDAUU"
   ```

2. **Set LDAUJ equal to LDAUU** when None:
   ```python
   if ldauj_value is None:
       ldauj_value = potential_value  # J = U for LDAUTYPE=3
   ```

3. **Update brick configuration** (`teros/core/lego/bricks/hubbard_response.py`):
   ```python
   # Pass ldauj=None to use default (same as LDAUU)
   ldaul, ldauu, ldauj = build_ldau_arrays(
       target_species=target_species,
       all_species=all_species,
       ldaul_value=ldaul,
       potential_value=V,
       ldauj_value=None,  # ADDED: defaults to V
   )
   ```

4. **Add validation warning**:
   ```python
   if ldauj_value != potential_value:
       logger.warning(
           f"LDAUJ={ldauj_value} differs from LDAUU={potential_value}. "
           "For LDAUTYPE=3, these should typically be equal."
       )
   ```

**Difficulty**: LOW - Simple parameter fix, no structural changes needed.

**References**:
- VASP wiki: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
- Example: `/home/trevizam/NiO_calcU/doall.sh` (lines 68, 86)

---

### Issue #3: AFM-II Magnetic Structure (CRITICAL)

**Priority**: HIGH
**Difficulty**: MEDIUM
**Status**: INCORRECT (simplified MAGMOM, not AFM-II)

**Problem**: NiO has AFM-II antiferromagnetic ground state with alternating spin orientation. Current examples use simplified ferromagnetic or random initial moments, giving wrong electronic structure and wrong U.

**VASP Wiki Reference** (`/home/trevizam/NiO_calcU/INCAR:16-20`):
```
MAGMOM = 2.0 -1.0  1.0 -1.0  1.0 \
        -1.0  1.0 -1.0  1.0 -1.0 \
         1.0 -1.0  1.0 -1.0  1.0 \
        -1.0  1.0 -1.0  1.0 -1.0 \
        16*0.0

↳ 20 Ni atoms with alternating ±1.0 moments (AFM-II)
↳ 16 O atoms with zero initial moment
```

**Current PS-TEROS** (`examples/lego/hubbard_u/run_hubbard_u_nio.py:46`):
```python
'magmom': [2.0] * 4 + [0.6] * 4,  # 4 Ni + 4 O
↳ All Ni have SAME sign (+2.0) → ferromagnetic, not AFM!
```

**Why This Matters**:
- AFM-II is the **experimental ground state** for NiO (T_N = 523 K)
- Wrong magnetic structure → wrong band gap, wrong d-orbital splitting
- Wrong electronic structure → wrong d-electron occupations → wrong χ₀ and χ
- VASP wiki example explicitly uses AFM-II for a reason

**Physical Impact**:
```
Correct AFM:   Insulating ground state, correct d⁸ Ni²⁺ configuration
Ferromagnetic: May give metallic or wrong insulating state
```

**Implementation Strategy**:

1. **Create AFM pattern generator**:
   ```python
   def generate_afm_magmom(
       structure: orm.StructureData,
       target_species: str,
       magnetic_moment: float = 2.0,
   ) -> t.List[float]:
       """
       Generate AFM-II magnetic moments for rocksalt oxides.

       AFM-II: Alternating moments along [111] direction.
       For NiO: Ni at (0,0,0) and (0.5,0.5,0.5) have opposite spins.
       """
       sites = structure.get_ase().get_chemical_symbols()
       magmom = []

       ni_index = 0
       for i, symbol in enumerate(sites):
           if symbol == target_species:
               # Alternate sign for each Ni atom
               sign = 1 if ni_index % 2 == 0 else -1
               magmom.append(sign * magnetic_moment)
               ni_index += 1
           else:
               magmom.append(0.6)  # Small moment for O (gets quenched)

       return magmom
   ```

2. **Detect magnetic structure from symmetry** (advanced):
   ```python
   # Use pymatgen MagneticStructureEnumerator for automatic AFM detection
   from pymatgen.analysis.magnetism import MagneticStructureEnumerator
   ```

3. **User specification** (simple):
   ```python
   # Add parameter to hubbard_response brick
   'magnetic_structure': 'afm-ii',  # or 'fm', 'afm-i', custom list
   ```

4. **Update examples** (`examples/lego/hubbard_u/run_hubbard_u_nio.py`):
   ```python
   # BEFORE:
   'magmom': [2.0] * 4 + [0.6] * 4,

   # AFTER:
   'magmom': [2.0, -2.0, 2.0, -2.0, 0.6, 0.6, 0.6, 0.6],  # AFM-II pattern
   ```

**Validation**:
- Check OSZICAR for converged magnetic moments
- Verify band gap matches experimental value (NiO: ~4 eV)
- Compare U value with literature (NiO: 5-6 eV)

**Difficulty**: MEDIUM - Requires understanding of magnetic ordering and possibly symmetry analysis.

**References**:
- VASP wiki example: `/home/trevizam/NiO_calcU/INCAR` (lines 16-20)
- Literature: NiO AFM-II structure (T_N = 523 K)

---

### Issue #4: Potential Value Sampling (IMPORTANT)

**Priority**: MEDIUM
**Difficulty**: LOW
**Status**: INADEQUATE (4 values, should be 8+)

**Problem**: Current default uses only 4 potential values (±0.1, ±0.2 eV). VASP wiki recommends 8 values for robust linear regression.

**VASP Wiki Reference** (`/home/trevizam/NiO_calcU/doall.sh:57`):
```bash
for v in +0.05 -0.05 +0.10 -0.10 +0.15 -0.15 +0.20 -0.20
↳ 8 potential values, symmetric around V=0
```

**Current PS-TEROS** (`teros/core/lego/bricks/hubbard_response.py`):
```python
'potential_values': [-0.2, -0.1, 0.1, 0.2],  # Only 4 points - INADEQUATE
```

**Why This Matters**:
- Linear regression quality improves with more data points
- 4 points is **minimum viable**, 8+ is **recommended**
- More points → better R² → more reliable U value
- Small overhead (8 SCF vs 4 SCF) for significant quality gain

**Statistical Impact**:
```
4 points:  R² typically 0.95-0.99, uncertainty ±0.2 eV
8 points:  R² typically 0.99+, uncertainty ±0.1 eV
```

**Implementation Strategy**:

1. **Update default** (`teros/core/lego/bricks/hubbard_response.py`):
   ```python
   # BEFORE:
   potential_values = stage.get('potential_values', [-0.2, -0.1, 0.1, 0.2])

   # AFTER:
   potential_values = stage.get(
       'potential_values',
       [-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20]
   )
   ```

2. **Add validation warning** for insufficient sampling:
   ```python
   if len(potential_values) < 6:
       logger.warning(
           f"Only {len(potential_values)} potential values provided. "
           "Recommend at least 8 for robust linear regression."
       )
   ```

3. **Document in examples** (`examples/lego/hubbard_u/`):
   ```python
   # Good: VASP wiki recommendation (8 values)
   'potential_values': [-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20],

   # Acceptable: Minimum for testing (4 values)
   'potential_values': [-0.2, -0.1, 0.1, 0.2],

   # Best: High precision (10+ values)
   'potential_values': [-0.25, -0.20, -0.15, -0.10, -0.05,
                        0.05, 0.10, 0.15, 0.20, 0.25],
   ```

4. **Add R² threshold** in analysis brick:
   ```python
   R2_THRESHOLD = 0.98
   if r_squared < R2_THRESHOLD:
       logger.warning(
           f"Linear fit R²={r_squared:.3f} below threshold {R2_THRESHOLD}. "
           "Consider using more potential values or checking for convergence issues."
       )
   ```

**Difficulty**: LOW - Simple parameter change, no structural modifications.

**Computational Cost**: ~2× more VASP calculations (8 vs 4), but each is a fast SCF (~5-10 minutes).

**References**:
- VASP wiki: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
- Example: `/home/trevizam/NiO_calcU/doall.sh` (line 57)

---

## Recent Bug Fixes (Completed 2026-02-03)

✅ These issues have been **RESOLVED** and do not require further action:

1. **ISPIN=2 OUTCAR Parsing** (FIXED)
   - Issue: OUTCAR parser failed on spin-polarized calculations
   - Fix: Updated regex patterns to handle magnetization data
   - File: `teros/core/u_calculation/tasks.py`

2. **Chi/Chi_0 Label Convention** (FIXED)
   - Issue: Inconsistent naming (χ vs χ₀ swapped in code)
   - Fix: Standardized to VASP convention (χ₀=NSCF, χ=SCF)
   - File: `teros/core/u_calculation/tasks.py`, `teros/core/lego/bricks/hubbard_analysis.py`

3. **Sign Convention for Potential** (FIXED)
   - Issue: Positive V decreased d-occupation (backwards)
   - Fix: Negate potential in LDAUU (-V for applied potential +V)
   - File: `teros/core/u_calculation/utils.py:121`

4. **Ground State LDAU Settings** (FIXED)
   - Issue: Ground state had LDAU=False, causing ICHARG=11 to fail
   - Fix: Set LDAU=True with LDAUU=0 for compatible charge density
   - File: `examples/lego/hubbard_u/run_hubbard_u_nio.py:79-83`

5. **ISTART=0 for NSCF Response** (FIXED)
   - Issue: ICHARG=11 (NSCF) should have ISTART=0, not ISTART=1
   - Fix: Set ISTART=0 explicitly in NSCF step
   - File: `teros/core/u_calculation/workgraph.py`

---

## Implementation Priority

### Phase 1: CRITICAL Fixes (MUST FIX)
**These fixes are REQUIRED before the module can produce correct U values.**

1. **Issue #1: Single-atom perturbation** (HIGHEST priority)
   - Most fundamental physics error
   - Requires POTCAR/POSCAR restructuring
   - Estimated effort: 2-3 days

2. **Issue #2: LDAUJ parameter** (HIGH priority)
   - Simple parameter fix
   - Critical for correct spin response
   - Estimated effort: 1-2 hours

3. **Issue #3: AFM magnetic structure** (HIGH priority)
   - Essential for correct electronic structure
   - Medium complexity (magnetic ordering)
   - Estimated effort: 1 day

### Phase 2: Quality Improvements (SHOULD FIX)

4. **Issue #4: Potential sampling** (MEDIUM priority)
   - Simple default change
   - Improves reliability significantly
   - Estimated effort: 30 minutes

---

## Testing Strategy

### Validation Against VASP Wiki NiO Example

After implementing all CRITICAL fixes, validate against `/home/trevizam/NiO_calcU/`:

**Expected Results for NiO:**
```
U = 5.58 - 6.33 eV  (literature range)
χ₀ > χ              (NSCF response > SCF response)
R² > 0.98           (good linear fit)
```

**Test Procedure:**

1. **Run reference calculation**:
   ```bash
   cd /home/trevizam/NiO_calcU/
   ./doall.sh
   # Extract U from OUTCAR files (manual calculation)
   ```

2. **Run PS-TEROS implementation**:
   ```python
   # Use fixed implementation
   wg = quick_hubbard_u(
       structure=nio_structure,
       target_species='Ni',
       potential_values=[-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20],
       ldaul=2,
       incar={'magmom': afm_magmom},  # AFM-II pattern
   )
   ```

3. **Compare results**:
   ```python
   u_result = get_stage_results(wg, 'analysis')
   u_value = u_result['summary']['hubbard_u_eV']

   assert 5.5 < u_value < 6.5, f"U={u_value:.2f} outside expected range"
   assert u_result['summary']['chi_0_mean'] > u_result['summary']['chi_mean']
   assert u_result['chi_0_fit']['r_squared'] > 0.98
   ```

4. **Physics checks**:
   - Ground state is insulating (band gap ~4 eV)
   - AFM-II magnetic ordering converges
   - d-electron occupation increases with positive V
   - χ₀ (bare response) > χ (screened response)

### Unit Tests (Add After Implementation)

```python
# tests/test_u_calculation_single_atom.py
def test_single_atom_perturbation():
    """Verify potential applied to single atom only."""
    ldaul, ldauu, ldauj = build_ldau_arrays_single_atom(...)
    assert ldauu[0] != 0.0  # First atom has potential
    assert all(u == 0.0 for u in ldauu[1:])  # Others zero

def test_ldauj_equals_ldauu():
    """Verify LDAUJ equals LDAUU for LDAUTYPE=3."""
    ldaul, ldauu, ldauj = build_ldau_arrays(..., ldauj_value=None)
    assert ldauj[0] == ldauu[0]  # J = U for target species

def test_afm_magmom_pattern():
    """Verify AFM-II alternating moments."""
    magmom = generate_afm_magmom(nio_structure, 'Ni')
    ni_moments = [m for m in magmom if abs(m) > 1.0]
    assert len(ni_moments) > 0
    assert any(m < 0 for m in ni_moments)  # Has negative moments
    assert any(m > 0 for m in ni_moments)  # Has positive moments
```

---

## References

### VASP Wiki
- Main reference: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
- LDAU parameters: https://www.vasp.at/wiki/index.php/LDAUL
- LDAUTYPE: https://www.vasp.at/wiki/index.php/LDAUTYPE

### Local Examples
- Complete workflow: `/home/trevizam/NiO_calcU/doall.sh`
- POSCAR (split species): `/home/trevizam/NiO_calcU/POSCAR`
- INCAR (AFM-II): `/home/trevizam/NiO_calcU/INCAR`
- POTCAR structure: `/home/trevizam/NiO_calcU/POTCAR` (grep TITEL)

### Literature
- NiO Hubbard U: 5.58 - 6.33 eV (experimental range)
- NiO band gap: ~4 eV (optical)
- NiO magnetic structure: AFM-II (T_N = 523 K)

### Current Implementation Files
- LDAU arrays: `teros/core/u_calculation/utils.py:79-128`
- Response brick: `teros/core/lego/bricks/hubbard_response.py`
- Analysis brick: `teros/core/lego/bricks/hubbard_analysis.py`
- Example script: `examples/lego/hubbard_u/run_hubbard_u_nio.py`

---

## Notes

⚠️ **DO NOT USE this module for production calculations until all CRITICAL issues are resolved.**

**Current Status**: Module is functional (runs without errors) but produces **physically incorrect U values** due to:
1. Wrong perturbation (applied to all atoms, not single atom)
2. Wrong LDAUJ parameter (0 instead of V)
3. Wrong magnetic structure (ferromagnetic instead of AFM-II)

These are not minor implementation details - they are **fundamental physics errors** that make the results unreliable.

**After fixes**, the module will correctly implement the VASP wiki linear response method for Hubbard U calculation.

---

## Summary Table

| Issue | Priority | Difficulty | Impact | Estimated Effort |
|-------|----------|-----------|--------|------------------|
| #1: Single-atom perturbation | CRITICAL | HIGH | Fundamental physics error | 2-3 days |
| #2: LDAUJ parameter | CRITICAL | LOW | Wrong spin response | 1-2 hours |
| #3: AFM magnetic structure | CRITICAL | MEDIUM | Wrong electronic structure | 1 day |
| #4: Potential sampling | IMPORTANT | LOW | Statistical quality | 30 minutes |

**Total estimated effort for full implementation: 4-5 days**

**Minimum viable fix (Issues #1-3): 3-4 days**
