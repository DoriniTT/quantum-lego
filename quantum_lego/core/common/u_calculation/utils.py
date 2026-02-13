"""Pure Python utilities for Hubbard U calculation module.

This module provides helper functions for:
- Linear regression for U calculation from multiple potential values
- INCAR preparation for ground state and response calculations
- LDAU array construction for multi-species systems
"""

import copy
import typing as t


def linear_regression(x: t.List[float], y: t.List[float]) -> t.Tuple[float, float, float]:
    """
    Perform linear regression y = mx + c.

    Uses least squares fitting without external dependencies.

    Args:
        x: Independent variable values (potential values V)
        y: Dependent variable values (occupation changes ΔN)

    Returns:
        Tuple of (slope, intercept, r_squared)

    Example:
        >>> x = [-0.2, -0.1, 0.0, 0.1, 0.2]
        >>> y = [0.04, 0.02, 0.0, -0.02, -0.04]  # chi_0 * V
        >>> slope, intercept, r2 = linear_regression(x, y)
        >>> print(f"slope={slope:.3f}, R²={r2:.3f}")
        slope=-0.200, R²=1.000
    """
    n = len(x)
    if n != len(y):
        raise ValueError(f"x and y must have same length, got {n} and {len(y)}")
    if n < 2:
        raise ValueError(f"Need at least 2 points for regression, got {n}")

    # Calculate sums
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi * xi for xi in x)

    # Calculate slope and intercept
    denominator = n * sum_x2 - sum_x * sum_x
    if abs(denominator) < 1e-15:
        raise ValueError("Cannot fit: all x values are identical")

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n

    # Calculate R-squared
    mean_y = sum_y / n
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)
    ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))

    if ss_tot < 1e-15:
        # All y values are identical
        r_squared = 1.0 if ss_res < 1e-15 else 0.0
    else:
        r_squared = 1.0 - (ss_res / ss_tot)

    return float(slope), float(intercept), float(r_squared)


def _lowercase_keys(d: dict) -> dict:
    """Convert all dictionary keys to lowercase (recursively for nested dicts)."""
    result = {}
    for key, value in d.items():
        lower_key = key.lower()
        if isinstance(value, dict):
            result[lower_key] = _lowercase_keys(value)
        else:
            result[lower_key] = value
    return result


def build_ldau_arrays(
    target_species: str,
    all_species: t.List[str],
    ldaul_value: int,
    potential_value: float,
    ldauj_value: t.Optional[float] = None,
) -> t.Tuple[t.List[int], t.List[float], t.List[float]]:
    """
    Build LDAUL, LDAUU, LDAUJ arrays for multi-species system.

    VASP requires these arrays in the order of species in POTCAR.
    Target species gets the specified L and U values, others get -1 and 0.

    For LDAUTYPE=3 (linear response), LDAUJ must equal LDAUU to apply the
    same potential to both spin channels. When ldauj_value is None (default),
    LDAUJ is automatically set equal to LDAUU.

    Args:
        target_species: Species name for Hubbard U calculation (e.g., 'Fe',
            or a kind name like 'Sn' for split-species structures)
        all_species: List of all species/kind names in POTCAR order
        ldaul_value: Angular momentum (2 for d-electrons, 3 for f-electrons)
        potential_value: Applied potential V (eV) - this goes into LDAUU
        ldauj_value: Exchange J value. None (default) = same as LDAUU,
            which is correct for LDAUTYPE=3

    Returns:
        Tuple of (ldaul_list, ldauu_list, ldauj_list)

    Example:
        >>> ldaul, ldauu, ldauj = build_ldau_arrays(
        ...     target_species='Sn',
        ...     all_species=['Sn', 'Sn1', 'O'],
        ...     ldaul_value=2,
        ...     potential_value=0.1,
        ... )
        >>> print(f"LDAUL={ldaul}, LDAUU={ldauu}, LDAUJ={ldauj}")
        LDAUL=[2, -1, -1], LDAUU=[-0.1, 0.0, 0.0], LDAUJ=[-0.1, 0.0, 0.0]
    """
    ldaul = []
    ldauu = []
    ldauj = []

    for species in all_species:
        if species == target_species:
            ldaul.append(ldaul_value)
            # Negate potential to match VASP convention:
            # Positive V should increase d-occupation
            ldauu.append(-potential_value)
            # For LDAUTYPE=3, LDAUJ must equal LDAUU (same potential on both spins)
            ldauj.append(-potential_value if ldauj_value is None else ldauj_value)
        else:
            ldaul.append(-1)  # No LDA+U for this species
            ldauu.append(0.0)
            ldauj.append(0.0)

    return ldaul, ldauu, ldauj


def prepare_ground_state_incar(
    base_params: t.Optional[dict] = None,
    lmaxmix: int = 4,
) -> dict:
    """
    Prepare INCAR parameters for ground state calculation (no LDAU).

    The ground state calculation determines the baseline d-electron occupancy
    and saves CHGCAR/WAVECAR for subsequent response calculations.

    Args:
        base_params: Base INCAR parameters (ENCUT, EDIFF, etc.)
        lmaxmix: Maximum l for mixing (4 for d-electrons, 6 for f-electrons)

    Returns:
        dict with INCAR parameters for ground state

    Key parameters set:
        - LDAU = False (no +U correction)
        - LMAXMIX = 4 (for d-electron mixing)
        - LORBIT = 11 (for orbital projections - required!)
        - LWAVE = True (save WAVECAR)
        - LCHARG = True (save CHGCAR)
    """
    # Convert base params to lowercase
    incar = _lowercase_keys(copy.deepcopy(base_params)) if base_params else {}

    # Core ground state parameters (lowercase for AiiDA-VASP)
    incar.update({
        'ldau': False,
        'lmaxmix': lmaxmix,
        'lorbit': 11,      # Required for orbital projections
        'lwave': True,     # Save WAVECAR
        'lcharg': True,    # Save CHGCAR
    })

    return incar


def prepare_response_incar(
    base_params: t.Optional[dict],
    potential_value: float,
    target_species: str,
    all_species: t.List[str],
    ldaul: int = 2,
    ldauj: float = 0.0,
    is_scf: bool = True,
    lmaxmix: int = 4,
) -> dict:
    """
    Prepare INCAR parameters for response calculation (with LDAU).

    Creates INCAR for either:
    - Non-SCF response (ICHARG=11): Fixed charge density from ground state
    - SCF response: Allows charge to evolve self-consistently

    Args:
        base_params: Base INCAR parameters (ENCUT, EDIFF, etc.)
        potential_value: Applied potential V (eV)
        target_species: Element for Hubbard U (e.g., 'Fe')
        all_species: All element symbols in POTCAR order
        ldaul: Angular momentum (2=d, 3=f). Default: 2
        ldauj: Exchange J value. Default: 0.0
        is_scf: If True, SCF response. If False, non-SCF (ICHARG=11)
        lmaxmix: Maximum l for mixing. Default: 4

    Returns:
        dict with INCAR parameters for response calculation

    Key parameters set:
        - LDAU = True
        - LDAUTYPE = 3 (linear response mode)
        - LDAUL, LDAUU, LDAUJ arrays
        - ICHARG = 11 (only for non-SCF)
        - LORBIT = 11 (for orbital projections)
    """
    # Convert base params to lowercase
    incar = _lowercase_keys(copy.deepcopy(base_params)) if base_params else {}

    # Build LDAU arrays
    ldaul_list, ldauu_list, ldauj_list = build_ldau_arrays(
        target_species=target_species,
        all_species=all_species,
        ldaul_value=ldaul,
        potential_value=potential_value,
        ldauj_value=ldauj,
    )

    # Set LDAU parameters (lowercase for AiiDA-VASP)
    incar.update({
        'ldau': True,
        'ldautype': 3,        # Linear response mode
        'ldaul': ldaul_list,
        'ldauu': ldauu_list,
        'ldauj': ldauj_list,
        'lorbit': 11,         # Required for orbital projections
        'lmaxmix': lmaxmix,
    })

    # Non-SCF: Read and fix charge density
    if not is_scf:
        incar['icharg'] = 11
        incar['istart'] = 0  # CRITICAL: Start from new wavefunctions, not WAVECAR
        # This ensures eigenvalues are recalculated with the perturbed +U potential,
        # giving the correct "bare" response

    return incar


def validate_target_species(
    structure,
    target_species: str,
) -> None:
    """
    Validate that target species exists in structure.

    Accepts both element symbols and AiiDA kind names (for split species).

    Args:
        structure: AiiDA StructureData or any object with get_ase() method
        target_species: Element symbol or kind name to validate

    Raises:
        ValueError: If target_species is not found in structure

    Example:
        >>> validate_target_species(fe2o3_structure, 'Fe')  # OK
        >>> validate_target_species(split_structure, 'Sn')  # OK (kind name)
        >>> validate_target_species(fe2o3_structure, 'Ni')  # Raises ValueError
    """
    # AiiDA StructureData: check kind names first (supports split species)
    if hasattr(structure, 'sites'):
        kind_names = {site.kind_name for site in structure.sites}
        if target_species in kind_names:
            return  # Valid kind name

    # Fallback: element symbol check
    if hasattr(structure, 'get_ase'):
        ase_struct = structure.get_ase()
    elif hasattr(structure, 'get_chemical_symbols'):
        ase_struct = structure
    else:
        raise TypeError(
            f"structure must have get_ase(), sites, or get_chemical_symbols() method, "
            f"got {type(structure).__name__}"
        )

    symbols = set(ase_struct.get_chemical_symbols())

    if target_species not in symbols:
        # Build helpful error message with both kind names and symbols
        available = sorted(symbols)
        if hasattr(structure, 'sites'):
            kind_names = sorted({site.kind_name for site in structure.sites})
            available_str = f"element symbols: {available}, kind names: {kind_names}"
        else:
            available_str = str(available)
        raise ValueError(
            f"Target species '{target_species}' not found in structure. "
            f"Available: {available_str}"
        )


def get_species_order_from_structure(structure) -> t.List[str]:
    """
    Get unique species from structure in order of first appearance.

    This matches the order VASP uses for POTCAR and LDAU arrays.

    For AiiDA StructureData with split species (e.g., 'Sn' and 'Sn1'),
    uses kind_name instead of element symbol, so the LDAU arrays have
    the correct length matching the POTCAR.

    Args:
        structure: AiiDA StructureData or any object with get_ase() method

    Returns:
        List of unique species/kind names in order of first appearance

    Example:
        >>> species = get_species_order_from_structure(fe2o3_structure)
        >>> print(species)
        ['Fe', 'O']
        >>> # For split species:
        >>> species = get_species_order_from_structure(split_sno2)
        >>> print(species)
        ['Sn', 'Sn1', 'O']
    """
    # AiiDA StructureData: use kind names (supports split species)
    if hasattr(structure, 'sites'):
        seen = {}
        for site in structure.sites:
            if site.kind_name not in seen:
                seen[site.kind_name] = True
        return list(seen.keys())

    # Fallback: ASE chemical symbols
    if hasattr(structure, 'get_ase'):
        ase_struct = structure.get_ase()
    elif hasattr(structure, 'get_chemical_symbols'):
        ase_struct = structure
    else:
        raise TypeError(
            f"structure must have get_ase(), sites, or get_chemical_symbols() method, "
            f"got {type(structure).__name__}"
        )

    symbols = ase_struct.get_chemical_symbols()

    # Preserve order of first appearance (for Python 3.7+, dict keeps insertion order)
    seen = {}
    for s in symbols:
        if s not in seen:
            seen[s] = True
    return list(seen.keys())


def prepare_perturbed_structure(
    structure,
    target_species: str,
) -> t.Tuple:
    """Split first atom of target_species into a separate kind for single-atom perturbation.

    The linear response method requires applying the perturbation potential to
    a single atom. This function creates a new structure where:
    - The first atom of target_species keeps the original kind name (perturbed)
    - All other atoms of target_species get a new kind name with '1' suffix (unperturbed)
    - Other species are unchanged

    Atoms are sorted by kind so that the resulting POSCAR has contiguous species
    blocks (required by VASP). The kind order is: perturbed, unperturbed, then
    all other species in their original order.

    The POTCAR must then include duplicate entries for both kinds (same pseudopotential).

    Args:
        structure: AiiDA StructureData
        target_species: Element symbol to split (e.g., 'Sn')

    Returns:
        Tuple of (split_structure, perturbed_kind, unperturbed_kind) where:
        - split_structure: New StructureData with split kinds
        - perturbed_kind: Kind name for the perturbed atom (e.g., 'Sn')
        - unperturbed_kind: Kind name for unperturbed atoms (e.g., 'Sn1')

    Example:
        >>> split, perturbed, unperturbed = prepare_perturbed_structure(supercell, 'Sn')
        >>> # split has kinds: ['Sn', 'Sn1', 'O']
        >>> # Sn = 1 atom (perturbed), Sn1 = 15 atoms, O = 32 atoms
        >>> potential_mapping = {'Sn': 'Sn_d', 'Sn1': 'Sn_d', 'O': 'O'}
    """
    from aiida import orm

    if not hasattr(structure, 'sites'):
        raise TypeError(
            f"structure must be an AiiDA StructureData, got {type(structure).__name__}"
        )

    # Find which sites belong to target species
    target_indices = [
        i for i, site in enumerate(structure.sites)
        if site.kind_name == target_species
    ]

    if not target_indices:
        raise ValueError(
            f"Target species '{target_species}' not found in structure. "
            f"Available kinds: {sorted({s.kind_name for s in structure.sites})}"
        )

    if len(target_indices) < 2:
        raise ValueError(
            f"Need at least 2 atoms of '{target_species}' to split. "
            f"Found {len(target_indices)}. Use a supercell."
        )

    # Get the original kind to find the element symbol
    original_kind = None
    for kind in structure.kinds:
        if kind.name == target_species:
            original_kind = kind
            break

    perturbed_kind = target_species       # e.g., 'Sn'
    unperturbed_kind = target_species + '1'  # e.g., 'Sn1'

    # Classify each site into its new kind name and collect positions
    # bins[kind_name] = list of positions
    bins = {perturbed_kind: [], unperturbed_kind: []}
    other_kind_order = []  # preserve original kind order for non-target species

    first_target_found = False
    for site in structure.sites:
        if site.kind_name == target_species:
            if not first_target_found:
                first_target_found = True
                bins[perturbed_kind].append(site.position)
            else:
                bins[unperturbed_kind].append(site.position)
        else:
            if site.kind_name not in bins:
                bins[site.kind_name] = []
                other_kind_order.append(site.kind_name)
            bins[site.kind_name].append(site.position)

    # Build new structure with atoms sorted by kind (contiguous blocks for VASP)
    new_structure = orm.StructureData(cell=structure.cell)

    # Define kind order: perturbed first, then unperturbed, then others
    kind_order = [perturbed_kind, unperturbed_kind] + other_kind_order

    # Add kinds and their sites in order
    for kind_name in kind_order:
        positions = bins.get(kind_name, [])
        if not positions:
            continue

        # Add the kind definition
        if kind_name == perturbed_kind:
            new_structure.append_kind(original_kind)
        elif kind_name == unperturbed_kind:
            new_structure.append_kind(orm.Kind(
                name=unperturbed_kind,
                symbols=original_kind.symbols,
                weights=original_kind.weights,
            ))
        else:
            for kind in structure.kinds:
                if kind.name == kind_name:
                    new_structure.append_kind(kind)
                    break

        # Add all sites for this kind (contiguous block)
        for pos in positions:
            new_structure.append_site(
                orm.Site(kind_name=kind_name, position=pos)
            )

    return new_structure, perturbed_kind, unperturbed_kind


# Default potential values for linear regression
# Note: V=0 is excluded because GS has LDAU=False while response has LDAU=True,
# which can cause inconsistent baseline even at zero perturbation
DEFAULT_POTENTIAL_VALUES = [-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20]
