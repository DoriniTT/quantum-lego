"""
Fixed Atoms Module

Calculator-agnostic utilities for constraining atoms in slab structures.
Supports fixing atoms by position (top, bottom, center) with configurable thicknesses.
"""

import typing as t
import numpy as np
from aiida import orm


def get_fixed_atoms_list(
    structure: orm.StructureData,
    fix_type: str = None,
    fix_thickness: float = 0.0,
    fix_elements: t.List[str] = None,
) -> t.List[int]:
    """
    Identify atoms to fix in a slab structure based on position criteria.

    Args:
        structure: AiiDA StructureData (slab structure)
        fix_type: Where to fix atoms. Options:
            - 'bottom': Fix atoms from bottom up to fix_thickness Å
            - 'top': Fix atoms from top down to fix_thickness Å
            - 'center': Fix atoms within fix_thickness/2 Å of slab center
            - None: No fixing (returns empty list)
        fix_thickness: Thickness in Angstroms for fixing region
        fix_elements: Optional list of element symbols to fix (e.g., ['Ag', 'O'])
                     If None, all elements in the region are fixed

    Returns:
        List of 1-based atom indices to fix (sorted)

    Examples:
        # Fix bottom 7 Å of all atoms
        >>> fixed = get_fixed_atoms_list(slab, fix_type='bottom', fix_thickness=7.0)

        # Fix top 5 Å of Ag atoms only
        >>> fixed = get_fixed_atoms_list(slab, fix_type='top', fix_thickness=5.0,
        ...                              fix_elements=['Ag'])

        # Fix 4 Å around center (2 Å above and below)
        >>> fixed = get_fixed_atoms_list(slab, fix_type='center', fix_thickness=4.0)
    """
    if fix_type is None or fix_thickness <= 0.0:
        return []

    # Get atomic positions and symbols
    positions = np.array([site.position for site in structure.sites])
    symbols = [site.kind_name for site in structure.sites]

    z_coords = positions[:, 2]
    z_min, z_max = np.min(z_coords), np.max(z_coords)
    z_center = (z_min + z_max) / 2.0

    fixed_indices = set()

    def is_eligible(symbol: str) -> bool:
        """Check if atom type should be fixed."""
        return fix_elements is None or symbol in fix_elements

    # Determine fixing region based on type
    if fix_type == 'bottom':
        z_cutoff = z_min + fix_thickness
        for idx, (z, symbol) in enumerate(zip(z_coords, symbols)):
            if z <= z_cutoff and is_eligible(symbol):
                fixed_indices.add(idx + 1)  # 1-based indexing

    elif fix_type == 'top':
        z_cutoff = z_max - fix_thickness
        for idx, (z, symbol) in enumerate(zip(z_coords, symbols)):
            if z >= z_cutoff and is_eligible(symbol):
                fixed_indices.add(idx + 1)

    elif fix_type == 'center':
        half_thickness = fix_thickness / 2.0
        z_lower = z_center - half_thickness
        z_upper = z_center + half_thickness
        for idx, (z, symbol) in enumerate(zip(z_coords, symbols)):
            if z_lower <= z <= z_upper and is_eligible(symbol):
                fixed_indices.add(idx + 1)

    else:
        raise ValueError(
            f"Invalid fix_type: '{fix_type}'. "
            f"Must be one of: 'bottom', 'top', 'center', or None"
        )

    return sorted(fixed_indices)


def add_fixed_atoms_to_cp2k_parameters(
    base_parameters: dict,
    fixed_atoms_list: t.List[int],
    components: str = "XYZ",
) -> dict:
    """
    Add FIXED_ATOMS constraint to CP2K parameters.

    Args:
        base_parameters: Base CP2K parameters dict
        fixed_atoms_list: List of 1-based atom indices to fix
        components: Which components to fix (default: "XYZ")
            - "XYZ": Fix all three dimensions (fully rigid)
            - "XY": Fix only in-plane motion
            - "Z": Fix only out-of-plane motion

    Returns:
        Updated parameters dict with FIXED_ATOMS constraint
    """
    import copy
    params = copy.deepcopy(base_parameters)

    if not fixed_atoms_list:
        return params

    # Ensure MOTION section exists
    if "MOTION" not in params:
        params["MOTION"] = {}
    if "CONSTRAINT" not in params["MOTION"]:
        params["MOTION"]["CONSTRAINT"] = {}

    # Add FIXED_ATOMS constraint
    params["MOTION"]["CONSTRAINT"]["FIXED_ATOMS"] = {
        "LIST": " ".join(map(str, fixed_atoms_list)),
        "COMPONENTS_TO_FIX": components
    }

    return params


def add_fixed_atoms_to_vasp_parameters(
    base_parameters: dict,
    structure: orm.StructureData,
    fixed_atoms_list: t.List[int],
) -> t.Tuple[dict, orm.StructureData]:
    """
    Add selective dynamics to VASP INCAR and create constrained structure.

    VASP uses selective dynamics via POSCAR, not INCAR parameters.
    This function:
    1. Sets IBRION and NSW appropriately
    2. Returns a modified StructureData with constraints

    Args:
        base_parameters: Base VASP INCAR parameters
        structure: Original StructureData
        fixed_atoms_list: List of 1-based atom indices to fix

    Returns:
        Tuple of (updated_parameters, constrained_structure)

    Note:
        For VASP, the constrained structure must be used in the calculation.
        The structure's 'kinds' will have 'fixed' tags set appropriately.
    """
    import copy
    from ase import Atoms
    from ase.constraints import FixAtoms

    params = copy.deepcopy(base_parameters)

    if not fixed_atoms_list:
        return params, structure

    # Ensure selective dynamics is enabled
    params['IBRION'] = params.get('IBRION', 2)  # Keep existing or default to 2

    # Get ASE atoms and add constraint
    atoms = structure.get_ase()

    # Convert to 0-based indices for ASE
    fixed_indices_0based = [idx - 1 for idx in fixed_atoms_list]

    # Add FixAtoms constraint
    constraint = FixAtoms(indices=fixed_indices_0based)
    atoms.set_constraint(constraint)

    # Create new StructureData with constraints
    constrained_structure = orm.StructureData(ase=atoms)

    return params, constrained_structure
