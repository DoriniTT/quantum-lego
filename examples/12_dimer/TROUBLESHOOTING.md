# Dimer Method Example — Troubleshooting Guide

## Issue: Spurious Imaginary Modes in Post-Dimer Vibrational Analysis

### Observed Behavior

NODE: 6aaa8c35-9b25-4592-a389-445d1b38d33d

After running the IDM pipeline (vib → idm_ts → vib_verify):
- **vib (initial)**: 1 large imaginary mode (775 cm⁻¹) ✓ correct
- **idm_ts**: All 32 dimer steps show negative curvature ✓ stable TS search
- **vib_verify (final)**: 3 large imaginary modes (14, 61, 798 cm⁻¹) ✗ **unexpected**

Expected: vib_verify should show exactly 1 large imaginary mode (the reaction coordinate), since we optimized to a TS.

### Root Cause (Hypothesis)

The dimer method is converging the geometry toward a saddle point, but the final structure may not be *exactly* at a true first-order saddle point. The spurious 14 cm⁻¹ and 61 cm⁻¹ modes are "ghost" modes indicating the structure is near but not at the TS.

Possible explanations:
1. **CONTCAR axis lines not being properly injected** into vib_verify POSCAR
   - The `inject_contcar_axis_prepend_text` calcfunction reads CONTCAR's dimer direction and appends echo commands to prepend_text
   - If these lines are malformed or not written correctly, VASP may not see them and may use the wrong structure
   
2. **Geometry not tightly converged at TS**
   - Even with EDIFFG=-0.005, there may be residual curvature
   - For ammonia (small system), may need even tighter EDIFFG or more dimer-specific tuning
   
3. **Dimer axis injection format issue**
   - VASP may expect the dimer direction lines in a specific format
   - Current approach uses `echo "dx dy dz" >> POSCAR` which may not be byte-for-byte identical to VASP's native output

4. **Initial dimer axis from vib OUTCAR is not optimal**
   - The hardest imaginary mode from initial vib may not be the best dimer starting direction
   - Dimer may be converging toward a different saddle point or a second-order feature

### Debugging Steps (For Next Investigation)

1. **Inspect the CONTCAR lines directly**
   ```bash
   tail -5 ~/trabalho/.aiida/XXX/CONTCAR  # from idm_ts stage
   ```
   Verify the dimer axis lines are present and have reasonable magnitude (typically ~0.001 to ~1.0 in normalized form).

2. **Check vib_verify POSCAR at runtime**
   - The POSCAR file that VASP actually uses in vib_verify should have the dimer axis appended
   - Check scheduler's stdout or VASP's output to see if it's reading those lines
   - Look for any VASP warnings about unexpected POSCAR format

3. **Compare initial and final dimer axes**
   - Extract the dimer axis from vib OUTCAR (eigenvectors of mode 12)
   - Extract the dimer axis from idm_ts CONTCAR (extra lines after coordinates)
   - Plot them to see if they've rotated significantly (suggesting the dimer may have followed a different path)

4. **Increase dimer convergence further**
   - Try EDIFFG = -0.001 eV/Å (even tighter)
   - Try NSW = 500 (more steps)
   - Try EDIFF = 1e-7 (tighter electronic convergence)

5. **Check VASP's dimer diagnostics in idm_ts OUTCAR**
   - Look for lines like `dForce`, `dCurv`, `dDistance` to see how the algorithm behaved
   - Check if the dimer reached a plateau or was still converging when it stopped

### Ammonia Flipping Specifics

The ammonia N-H inversion is a relatively low barrier (~0.15 eV), and the TS may be very flat or have a shallow potential. This can make it harder to locate precisely.

Possible ammonia-specific fixes:
- **Increase ENCUT** from 400 to 520 eV (better description of the transition region)
- **Use a denser k-point mesh** (currently Γ-only; for a 6×7×8 box this is fine, but add more k-points if atoms are closer)
- **Reduce POTIM for vib_verify** from 0.02 Å to 0.01–0.015 Å (smaller displacements for soft modes)
- **Use NFREE=4** instead of 2 in vib_verify (forward/backward differences instead of central; more robust for marginal cases)

### Files to Inspect

From the failed run:
- `idm_ts` CONTCAR extra lines (tail -5)
- `vib_verify` INCAR (to confirm tightest settings were used)
- `vib_verify` OUTCAR (to see the modal decomposition)

### Next Steps

1. Verify the dimer axis is being written to vib_verify's POSCAR correctly
2. If yes: investigate dimer convergence quality; increase NSW and EDIFFG tightness
3. If no: debug the `inject_contcar_axis_prepend_text` calcfunction to ensure the echo commands are correctly formatted

### References

- VASP wiki: https://vasp.at/wiki/Improved_dimer_method
- VASP wiki: https://vasp.at/wiki/Dimer_method
- Original dimer method paper: Henkelman & Jónsson, J. Chem. Phys. 111, 7010 (1999)
