"""AiiDA calcfunction tasks for Hubbard U calculation.

These tasks extract d-electron occupations from VASP output and calculate
the Hubbard U parameter using linear response theory.

The extract_d_electron_occupation function parses the OUTCAR directly to get
the total charge per orbital (not magnetization), which is required for
accurate U calculation.
"""

import re
import typing as t
import warnings

from aiida import orm
from aiida_workgraph import task

from .utils import linear_regression


def _parse_total_charge_from_outcar(outcar_content: str) -> t.List[t.Dict[str, float]]:
    """
    Parse the 'total charge' section from VASP OUTCAR content.

    For spin-polarized calculations (ISPIN=2), VASP writes multiple sections:
    - First "total charge": spin-up + spin-down (TOTAL) ← Use this!
    - Second "magnetization": spin-up - spin-down (difference)

    This function automatically detects ISPIN and uses the appropriate section
    to ensure d-occupations represent the total electron count.

    The OUTCAR contains a section like:
        total charge
        # of ion       s       p       d       tot
        ------------------------------------------
            1        0.150   0.016   8.437   8.602
            2        1.634   3.033   0.000   4.667
        --------------------------------------------------

    Args:
        outcar_content: Full content of OUTCAR file

    Returns:
        List of dicts, one per ion, with keys 's', 'p', 'd', 'tot'
        For ISPIN=2: values are spin-summed (total charge per orbital)

    Raises:
        ValueError: If total charge section not found
    """
    # Detect ISPIN from OUTCAR
    ispin_match = re.search(r'ISPIN\s*=\s*(\d)', outcar_content)
    ispin = int(ispin_match.group(1)) if ispin_match else 1

    # Find the "total charge" section
    # Pattern: "total charge" followed by header and data lines
    pattern = r'total charge\s*\n\s*#\s*of ion\s+s\s+p\s+d\s+tot\s*\n[-]+\s*\n((?:\s*\d+\s+[\d.-]+\s+[\d.-]+\s+[\d.-]+\s+[\d.-]+\s*\n)+)'

    matches = list(re.finditer(pattern, outcar_content))

    if not matches:
        raise ValueError(
            "Could not find 'total charge' section in OUTCAR. "
            "Ensure LORBIT=11 is set in INCAR."
        )

    # Strategy depends on ISPIN
    if ispin == 2 and len(matches) >= 2:
        # For spin-polarized: First match is total charge (sum)
        # Second match may be magnetization (difference) - ignore
        target_match = matches[0]  # Take FIRST, not last!
        print("INFO: ISPIN=2 detected, using first 'total charge' section (spin-summed)")
    else:
        # For non-spin-polarized or single match: use last (final SCF)
        target_match = matches[-1]

    data_block = target_match.group(1)

    charges = []
    for line in data_block.strip().split('\n'):
        parts = line.split()
        if len(parts) >= 5:
            # parts: [ion_number, s, p, d, tot]
            charges.append({
                's': float(parts[1]),
                'p': float(parts[2]),
                'd': float(parts[3]),
                'tot': float(parts[4]),
            })

    if not charges:
        raise ValueError(
            "Found 'total charge' section but could not parse any ion data."
        )

    return charges


@task.calcfunction
def extract_d_electron_occupation(
    retrieved: orm.FolderData,
    target_species: orm.Str,
    structure: orm.StructureData,
) -> orm.Dict:
    """
    Extract d-electron occupation for target species from VASP OUTCAR.

    Parses the 'total charge' section of OUTCAR to get orbital-resolved
    occupations. Requires LORBIT=11 in VASP INCAR.

    For spin-polarized calculations (ISPIN=2), the function automatically
    uses spin-summed values (total charge) rather than magnetization.

    Args:
        retrieved: FolderData from VASP calculation containing OUTCAR
        target_species: Element symbol to extract occupations for (e.g., 'Fe')
        structure: StructureData to identify atom types

    Returns:
        Dict with:
            - total_d_occupation: Sum of d-occupations for target species
            - per_atom_d_occupation: List of d-occupation per atom
            - atom_indices: 0-based indices of target atoms
            - atom_count: Number of target atoms
            - target_species: Element symbol
            - ispin: ISPIN value from OUTCAR (1 or 2)

    Raises:
        ValueError: If OUTCAR not found or d-occupation data cannot be parsed
    """
    species = target_species.value

    # Get atom symbols from structure
    ase_struct = structure.get_ase()
    symbols = ase_struct.get_chemical_symbols()

    # Find indices of target species (0-based)
    target_indices = [i for i, s in enumerate(symbols) if s == species]

    if not target_indices:
        raise ValueError(
            f"Target species '{species}' not found in structure. "
            f"Available: {sorted(set(symbols))}"
        )

    # Read OUTCAR from retrieved folder
    try:
        outcar_content = retrieved.get_object_content('OUTCAR')
    except FileNotFoundError:
        raise ValueError(
            "OUTCAR not found in retrieved folder. "
            "Check that the VASP calculation completed successfully."
        )

    # Parse total charge from OUTCAR
    charges = _parse_total_charge_from_outcar(outcar_content)

    # Extract d-occupations for target species
    per_atom_d_occ = []
    for idx in target_indices:
        if idx < len(charges):
            per_atom_d_occ.append(charges[idx]['d'])
        else:
            raise ValueError(
                f"Site index {idx} out of range for parsed charges "
                f"(got {len(charges)} ions)"
            )

    total_d_occ = sum(per_atom_d_occ)

    # Detect ISPIN from OUTCAR for validation
    ispin_match = re.search(r'ISPIN\s*=\s*(\d)', outcar_content)
    ispin = int(ispin_match.group(1)) if ispin_match else 1

    # Validation for spin-polarized calculations
    if ispin == 2:
        print("INFO: ISPIN=2 detected (spin-polarized calculation)")
        print(f"  Extracted total d-occupation: {total_d_occ:.4f}")
        print(f"  Per-atom: {per_atom_d_occ}")

        # Sanity check: for transition metals, d-occupation should be 0-10 per atom
        avg_d = total_d_occ / len(target_indices)
        if avg_d < 0.1 or avg_d > 10.5:
            warnings.warn(
                f"Average d-occupation per {species} atom is {avg_d:.2f}, "
                f"which is outside typical range (0-10). "
                f"Check OUTCAR parsing for spin-polarized calculations."
            )

    return orm.Dict(dict={
        'total_d_occupation': total_d_occ,
        'per_atom_d_occupation': per_atom_d_occ,
        'atom_indices': target_indices,
        'atom_count': len(target_indices),
        'target_species': species,
        'ispin': ispin,  # Track if spin-polarized
    })


@task.calcfunction
def calculate_occupation_response(
    ground_state_occupation: orm.Dict,
    nscf_occupation: orm.Dict,
    scf_occupation: orm.Dict,
    potential_value: orm.Float,
) -> orm.Dict:
    """
    Calculate response functions (chi, chi_0) for a single potential value.

    The linear response theory relates occupation change to applied potential:
        ΔN_NSCF = χ₀ * V  (non-self-consistent response)
        ΔN_SCF = χ * V    (self-consistent response)

    Args:
        ground_state_occupation: D-occupation from ground state (no potential)
        nscf_occupation: D-occupation from non-SCF response calculation
        scf_occupation: D-occupation from SCF response calculation
        potential_value: Applied potential V (eV)

    Returns:
        Dict with:
            - potential: Applied potential V (eV)
            - ground_state_d: Ground state d-occupation
            - nscf_d: Non-SCF response d-occupation
            - scf_d: SCF response d-occupation
            - delta_n_nscf: N_nscf - N_ground
            - delta_n_scf: N_scf - N_ground
    """
    gs_dict = ground_state_occupation.get_dict()
    nscf_dict = nscf_occupation.get_dict()
    scf_dict = scf_occupation.get_dict()
    V = potential_value.value

    gs_d = gs_dict['total_d_occupation']
    nscf_d = nscf_dict['total_d_occupation']
    scf_d = scf_dict['total_d_occupation']

    delta_n_nscf = nscf_d - gs_d
    delta_n_scf = scf_d - gs_d

    return orm.Dict(dict={
        'potential': V,
        'ground_state_d': gs_d,
        'nscf_d': nscf_d,
        'scf_d': scf_d,
        'delta_n_nscf': delta_n_nscf,
        'delta_n_scf': delta_n_scf,
    })


@task.calcfunction
def calculate_hubbard_u_single_point(
    response: orm.Dict,
) -> orm.Dict:
    """
    Calculate Hubbard U from a single potential value (quick estimate).

    Uses U = 1/χ - 1/χ₀ where:
        χ = ΔN_SCF / V
        χ₀ = ΔN_NSCF / V

    Note: This is less accurate than linear regression with multiple potentials.

    Args:
        response: Response dict from calculate_occupation_response

    Returns:
        Dict with U value and intermediate quantities

    Raises:
        ValueError: If potential is zero (cannot calculate chi)
    """
    resp_dict = response.get_dict()
    V = resp_dict['potential']

    if abs(V) < 1e-10:
        raise ValueError(
            "Cannot calculate U from V=0 response. "
            "Use a non-zero potential or multiple potentials with linear regression."
        )

    delta_n_nscf = resp_dict['delta_n_nscf']
    delta_n_scf = resp_dict['delta_n_scf']

    chi_0 = delta_n_nscf / V
    chi = delta_n_scf / V

    # Avoid division by zero
    if abs(chi) < 1e-10 or abs(chi_0) < 1e-10:
        raise ValueError(
            f"Response is too small to calculate U. "
            f"chi={chi:.6f}, chi_0={chi_0:.6f}. "
            f"Try a larger potential value."
        )

    U = (1.0 / chi) - (1.0 / chi_0)

    return orm.Dict(dict={
        'U': U,
        'chi': chi,
        'chi_0': chi_0,
        'potential': V,
        'delta_n_scf': delta_n_scf,
        'delta_n_nscf': delta_n_nscf,
    })


@task.calcfunction
def calculate_hubbard_u_linear_regression(
    responses: orm.List,
) -> orm.Dict:
    """
    Calculate Hubbard U from multiple potential values using linear regression.

    Performs linear fits:
        ΔN_NSCF = χ₀ * V + c₀
        ΔN_SCF = χ * V + c

    Then calculates: U = 1/χ - 1/χ₀

    This is more accurate than single-point calculation as it averages
    over multiple perturbation strengths.

    Args:
        responses: List of response dicts from calculate_occupation_response
            Each dict should have: potential, delta_n_nscf, delta_n_scf

    Returns:
        Dict with:
            - U: Final Hubbard U value (eV)
            - chi_slope: SCF response slope
            - chi_0_slope: NSCF response slope
            - chi_intercept: SCF intercept
            - chi_0_intercept: NSCF intercept
            - chi_r2: SCF fit R²
            - chi_0_r2: NSCF fit R²
            - potential_values: List of potentials used
            - delta_n_scf_values: List of SCF occupation changes
            - delta_n_nscf_values: List of NSCF occupation changes

    Raises:
        ValueError: If too few data points or regression fails
    """
    responses_list = responses.get_list()

    if len(responses_list) < 2:
        raise ValueError(
            f"Need at least 2 potential values for linear regression, "
            f"got {len(responses_list)}"
        )

    # Extract data arrays
    potentials = []
    delta_n_nscf_vals = []
    delta_n_scf_vals = []

    for resp in responses_list:
        potentials.append(resp['potential'])
        delta_n_nscf_vals.append(resp['delta_n_nscf'])
        delta_n_scf_vals.append(resp['delta_n_scf'])

    # Convention: chi (screened) from NSCF, chi_0 (bare) from SCF
    # - NSCF (ICHARG=11): Frozen charge → system cannot respond → screened → chi (small)
    # - SCF (relaxed): Charge can relax → full system response → bare → chi_0 (large)
    # Expected: chi < chi_0 (screened < bare)

    # Linear regression for chi (NSCF response, screened)
    chi_slope, chi_intercept, chi_r2 = linear_regression(
        potentials, delta_n_nscf_vals
    )

    # Linear regression for chi_0 (SCF response, bare)
    chi_0_slope, chi_0_intercept, chi_0_r2 = linear_regression(
        potentials, delta_n_scf_vals
    )

    # Calculate U
    if abs(chi_slope) < 1e-10 or abs(chi_0_slope) < 1e-10:
        raise ValueError(
            f"Response slopes are too small to calculate U. "
            f"chi_slope={chi_slope:.6f}, chi_0_slope={chi_0_slope:.6f}. "
            f"This may indicate insufficient perturbation or numerical issues."
        )

    U = (1.0 / chi_slope) - (1.0 / chi_0_slope)

    # Validation checks
    if chi_slope <= 0:
        warnings.warn(
            f"chi slope is non-positive ({chi_slope:.4f}). "
            "This suggests sign convention issues in the response calculations."
        )

    if chi_0_slope <= 0:
        warnings.warn(
            f"chi_0 slope is non-positive ({chi_0_slope:.4f}). "
            "This suggests sign convention issues in the response calculations."
        )

    if chi_slope >= chi_0_slope:
        warnings.warn(
            f"chi ({chi_slope:.4f}) >= chi_0 ({chi_0_slope:.4f}). "
            "Expected chi < chi_0 (screened < bare). Check calculation setup."
        )

    if U < 0 or U > 50:
        warnings.warn(
            f"U = {U:.2f} eV is outside typical range (0-20 eV). "
            "Check response calculations and potential values."
        )

    return orm.Dict(dict={
        'U': U,
        'chi_slope': chi_slope,
        'chi_0_slope': chi_0_slope,
        'chi_intercept': chi_intercept,
        'chi_0_intercept': chi_0_intercept,
        'chi_r2': chi_r2,
        'chi_0_r2': chi_0_r2,
        'potential_values': potentials,
        'delta_n_scf_values': delta_n_scf_vals,
        'delta_n_nscf_values': delta_n_nscf_vals,
        'n_points': len(potentials),
    })


@task.calcfunction
def gather_responses(
    **kwargs: orm.Dict,
) -> orm.List:
    """
    Gather response Dicts into a List for linear regression.

    Args:
        **kwargs: Response dicts keyed by label (e.g., V_0, V_1, ...)

    Returns:
        List of response dicts sorted by potential value
    """
    responses = []

    for key, response_node in kwargs.items():
        if isinstance(response_node, orm.Dict):
            responses.append(response_node.get_dict())
        else:
            responses.append(dict(response_node))

    # Sort by potential value for consistent ordering
    responses.sort(key=lambda r: r.get('potential', 0.0))

    return orm.List(list=responses)


@task.calcfunction
def compile_u_calculation_summary(
    hubbard_u_result: orm.Dict,
    ground_state_occupation: orm.Dict,
    structure: orm.StructureData,
    target_species: orm.Str,
    ldaul: orm.Int,
) -> orm.Dict:
    """
    Compile a comprehensive summary of the Hubbard U calculation.

    This function creates a well-organized Dict containing all relevant
    results from the U calculation workflow, suitable for analysis and
    reporting.

    Args:
        hubbard_u_result: Output from calculate_hubbard_u_linear_regression
        ground_state_occupation: Output from extract_d_electron_occupation (GS)
        structure: Input structure used for calculation
        target_species: Element symbol for which U was calculated
        ldaul: Angular momentum quantum number (2=d, 3=f)

    Returns:
        Dict with organized results:
            - summary: Key results (U, target_species, structure info)
            - linear_fit: Regression statistics (slopes, R², intercepts)
            - response_data: Raw response values per potential
            - ground_state: Ground state occupation details
            - metadata: Calculation metadata
    """
    u_dict = hubbard_u_result.get_dict()
    gs_dict = ground_state_occupation.get_dict()
    species = target_species.value
    l_value = ldaul.value

    # Get structure info
    ase_struct = structure.get_ase()
    formula = structure.get_formula()
    n_atoms = len(ase_struct)
    cell_volume = ase_struct.get_volume()

    # Count target atoms
    symbols = ase_struct.get_chemical_symbols()
    n_target = sum(1 for s in symbols if s == species)

    # Orbital type string
    orbital_type = {2: 'd', 3: 'f'}.get(l_value, f'l={l_value}')

    # Build organized summary
    summary = {
        # Main results section
        'summary': {
            'hubbard_u_eV': u_dict['U'],
            'target_species': species,
            'orbital_type': orbital_type,
            'ldaul': l_value,
            'structure_formula': formula,
            'n_atoms_total': n_atoms,
            'n_target_atoms': n_target,
            'cell_volume_A3': cell_volume,
        },

        # Linear regression details
        'linear_fit': {
            'chi_scf': {
                'slope': u_dict['chi_slope'],
                'intercept': u_dict['chi_intercept'],
                'r_squared': u_dict['chi_r2'],
                'description': 'Self-consistent response (charge evolves)',
            },
            'chi_0_nscf': {
                'slope': u_dict['chi_0_slope'],
                'intercept': u_dict['chi_0_intercept'],
                'r_squared': u_dict['chi_0_r2'],
                'description': 'Non-self-consistent response (frozen charge)',
            },
            'n_data_points': u_dict['n_points'],
            'formula_used': 'U = 1/chi_scf - 1/chi_0_nscf',
        },

        # Raw response data for plotting/analysis
        'response_data': {
            'potential_values_eV': u_dict['potential_values'],
            'delta_n_scf': u_dict['delta_n_scf_values'],
            'delta_n_nscf': u_dict['delta_n_nscf_values'],
        },

        # Ground state information
        'ground_state': {
            'total_d_occupation': gs_dict['total_d_occupation'],
            'per_atom_d_occupation': gs_dict['per_atom_d_occupation'],
            'n_target_atoms': gs_dict['atom_count'],
            'target_atom_indices': gs_dict['atom_indices'],
            'average_d_per_atom': gs_dict['total_d_occupation'] / gs_dict['atom_count'],
        },

        # Metadata
        'metadata': {
            'method': 'Linear Response (Cococcioni & de Gironcoli)',
            'reference': 'https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U',
            'vasp_ldautype': 3,
        },
    }

    return orm.Dict(dict=summary)
