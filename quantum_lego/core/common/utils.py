"""
Shared Utilities for Quantum Lego

This module contains common utility functions used across multiple Quantum Lego modules.
Centralizing these functions reduces code duplication and ensures consistent behavior.
"""

import copy
import logging
from collections import Counter
from functools import reduce
from math import gcd
from typing import Union, Any, NamedTuple, Optional

import numpy as np
from aiida import orm
from aiida_workgraph import task


# =============================================================================
# Logging Configuration
# =============================================================================

def get_logger(name: str = 'quantum_lego') -> logging.Logger:
    """
    Get a logger instance for Quantum Lego modules.

    This provides a consistent logging interface across all Quantum Lego modules.
    The logger integrates with AiiDA's logging system and can be configured
    via standard Python logging configuration.

    Args:
        name: Logger name (default: 'quantum_lego')

    Returns:
        Configured logger instance

    Example:
        >>> from quantum_lego.core.common.utils import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("Starting workflow...")
        >>> logger.warning("Configuration issue detected")
    """
    return logging.getLogger(name)


# Create module-level logger for Quantum Lego
logger = get_logger('quantum_lego.core')


# =============================================================================
# Placeholder Classes for WorkGraph Socket Compatibility
# =============================================================================

class TaskOutputPlaceholder(NamedTuple):
    """
    Placeholder for VASP task outputs when calculation is skipped.

    This provides a type-safe alternative to dynamically created objects
    using type() metaclass. Use this when you need to pass socket-like
    objects that won't actually be used in downstream calculations.

    Attributes:
        structure: Socket-like object with structure output
        misc: Socket-like object with misc output (optional)

    Example:
        >>> # Instead of: metal_vasp = type('obj', (object,), {'structure': bulk_vasp.structure})()
        >>> metal_vasp = TaskOutputPlaceholder(structure=bulk_vasp.structure)
    """
    structure: Any
    misc: Optional[Any] = None


class EnergyOutputPlaceholder(NamedTuple):
    """
    Placeholder for energy extraction outputs when calculation is skipped.

    Attributes:
        result: Socket-like object with result output

    Example:
        >>> # Instead of: metal_energy = type('obj', (object,), {'result': bulk_energy.result})()
        >>> metal_energy = EnergyOutputPlaceholder(result=bulk_energy.result)
    """
    result: Any


class FormationEnthalpyPlaceholder(NamedTuple):
    """
    Placeholder for formation enthalpy outputs when calculation is skipped.

    Attributes:
        result: Socket-like object with result output
    """
    result: Any


def deep_merge_dicts(base: dict, override: dict) -> dict:
    """
    Deep merge override dict into base dict.

    For nested dicts, recursively merges. For other values, override replaces base.
    This is particularly useful for merging VASP parameter dictionaries where you
    want to override specific INCAR parameters while preserving others.

    Args:
        base: Base dictionary
        override: Override dictionary (values take precedence)

    Returns:
        Merged dictionary (new dict, inputs are not modified)

    Example:
        >>> base = {'a': 1, 'b': {'c': 2, 'd': 3}}
        >>> override = {'b': {'c': 99}, 'e': 5}
        >>> result = deep_merge_dicts(base, override)
        >>> result
        {'a': 1, 'b': {'c': 99, 'd': 3}, 'e': 5}

        # Common use case - merging VASP parameters:
        >>> base_params = {'incar': {'ENCUT': 400, 'ISMEAR': 0, 'SIGMA': 0.05}}
        >>> override_params = {'incar': {'ENCUT': 520}}
        >>> merged = deep_merge_dicts(base_params, override_params)
        >>> merged['incar']
        {'ENCUT': 520, 'ISMEAR': 0, 'SIGMA': 0.05}
    """
    result = copy.deepcopy(base)

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge nested dicts
            result[key] = deep_merge_dicts(result[key], value)
        else:
            # Override value
            result[key] = copy.deepcopy(value)

    return result


def get_vasp_parser_settings(
    add_energy: bool = True,
    add_trajectory: bool = True,
    add_structure: bool = True,
    add_kpoints: bool = True,
) -> dict:
    """
    Get standard parser settings for aiida-vasp.

    This function provides a consistent configuration for the VASP parser
    across all PS-TEROS modules.

    Args:
        add_energy: Parse energy outputs (default: True)
        add_trajectory: Parse trajectory data (default: True)
        add_structure: Parse output structure (default: True)
        add_kpoints: Parse k-points information (default: True)

    Returns:
        Dictionary with 'parser_settings' key containing the configuration

    Example:
        >>> settings = get_vasp_parser_settings()
        >>> settings
        {'parser_settings': {'add_energy': True, 'add_trajectory': True, ...}}
    """
    return {
        'parser_settings': {
            'add_energy': add_energy,
            'add_trajectory': add_trajectory,
            'add_structure': add_structure,
            'add_kpoints': add_kpoints,
        }
    }


def extract_max_jobs_value(max_number_jobs: Union[orm.Int, int, None]) -> int:
    """
    Extract integer value from max_number_jobs parameter.

    Handles both AiiDA orm.Int nodes and plain Python integers,
    providing a consistent way to access the max jobs value across modules.

    Args:
        max_number_jobs: Either an orm.Int node or a plain integer, or None

    Returns:
        Integer value of max jobs, or 0 if None

    Example:
        >>> from aiida import orm
        >>> extract_max_jobs_value(orm.Int(4))
        4
        >>> extract_max_jobs_value(4)
        4
        >>> extract_max_jobs_value(None)
        0
    """
    if max_number_jobs is None:
        return 0
    if hasattr(max_number_jobs, 'value'):
        return max_number_jobs.value
    return int(max_number_jobs)


def ensure_python_dict(value: Union[orm.Dict, dict]) -> dict:
    """
    Ensure value is a Python dict, converting from orm.Dict if necessary.

    This is useful when a function can receive either an AiiDA Dict node
    or a plain Python dictionary.

    Args:
        value: Either an orm.Dict node or a plain Python dict

    Returns:
        Python dictionary

    Example:
        >>> from aiida import orm
        >>> ensure_python_dict({'a': 1})
        {'a': 1}
        >>> ensure_python_dict(orm.Dict({'a': 1}))
        {'a': 1}
    """
    if isinstance(value, orm.Dict):
        return value.get_dict()
    return value


def ensure_python_float(value: Union[orm.Float, float]) -> float:
    """
    Ensure value is a Python float, converting from orm.Float if necessary.

    Args:
        value: Either an orm.Float node or a plain Python float

    Returns:
        Python float

    Example:
        >>> from aiida import orm
        >>> ensure_python_float(3.14)
        3.14
        >>> ensure_python_float(orm.Float(3.14))
        3.14
    """
    if hasattr(value, 'value'):
        return value.value
    return float(value)


def ensure_python_int(value: Union[orm.Int, int]) -> int:
    """
    Ensure value is a Python int, converting from orm.Int if necessary.

    Args:
        value: Either an orm.Int node or a plain Python int

    Returns:
        Python int

    Example:
        >>> from aiida import orm
        >>> ensure_python_int(42)
        42
        >>> ensure_python_int(orm.Int(42))
        42
    """
    if hasattr(value, 'value'):
        return value.value
    return int(value)


def ensure_python_bool(value: Union[orm.Bool, bool]) -> bool:
    """
    Ensure value is a Python bool, converting from orm.Bool if necessary.

    Args:
        value: Either an orm.Bool node or a plain Python bool

    Returns:
        Python bool

    Example:
        >>> from aiida import orm
        >>> ensure_python_bool(True)
        True
        >>> ensure_python_bool(orm.Bool(True))
        True
    """
    if hasattr(value, 'value'):
        return value.value
    return bool(value)


def ensure_python_str(value: Union[orm.Str, str]) -> str:
    """
    Ensure value is a Python str, converting from orm.Str if necessary.

    Args:
        value: Either an orm.Str node or a plain Python str

    Returns:
        Python str

    Example:
        >>> from aiida import orm
        >>> ensure_python_str('hello')
        'hello'
        >>> ensure_python_str(orm.Str('hello'))
        'hello'
    """
    if hasattr(value, 'value'):
        return value.value
    return str(value)


def ensure_python_list(value: Union[orm.List, list]) -> list:
    """
    Ensure value is a Python list, converting from orm.List if necessary.

    Args:
        value: Either an orm.List node or a plain Python list

    Returns:
        Python list

    Example:
        >>> from aiida import orm
        >>> ensure_python_list([1, 2, 3])
        [1, 2, 3]
        >>> ensure_python_list(orm.List([1, 2, 3]))
        [1, 2, 3]
    """
    if isinstance(value, orm.List):
        return value.get_list()
    return list(value)


# =============================================================================
# Structure Analysis Utilities
# =============================================================================

def calculate_surface_area(structure: orm.StructureData) -> float:
    """
    Calculate surface area from in-plane lattice vectors (a × b).

    This computes the area of the surface unit cell by taking the cross
    product of the first two lattice vectors. This is commonly used for
    slab structures where the third vector (c) is perpendicular to the surface.

    Args:
        structure: StructureData node representing a slab

    Returns:
        Surface area in Angstroms^2

    Example:
        >>> from aiida import orm
        >>> area = calculate_surface_area(slab_structure)
        >>> print(f"Surface area: {area:.2f} Å²")
    """
    ase_struct = structure.get_ase()
    cell = ase_struct.get_cell()
    a_vec = cell[0]
    b_vec = cell[1]
    cross = np.cross(a_vec, b_vec)
    return float(np.linalg.norm(cross))


def get_atom_counts(structure: orm.StructureData) -> dict:
    """
    Get atom counts from structure using Counter.

    This provides a consistent way to count atoms across all PS-TEROS modules,
    avoiding repeated Counter(ase.get_chemical_symbols()) calls.

    Args:
        structure: StructureData node

    Returns:
        Dictionary mapping element symbols to atom counts

    Example:
        >>> counts = get_atom_counts(bulk_structure)
        >>> print(counts)
        {'Ag': 4, 'O': 2}
    """
    ase_struct = structure.get_ase()
    return dict(Counter(ase_struct.get_chemical_symbols()))


def get_formula_units(atom_counts: dict) -> int:
    """
    Get number of formula units (GCD of all atom counts).

    This determines how many formula units exist in a structure by finding
    the greatest common divisor of all atom counts.

    Args:
        atom_counts: Dictionary mapping elements to atom counts
                    (from get_atom_counts or similar)

    Returns:
        Number of formula units in the structure

    Example:
        >>> counts = {'Ag': 8, 'O': 4}  # 4 formula units of Ag2O
        >>> get_formula_units(counts)
        4
    """
    counts = list(atom_counts.values())
    if not counts:
        return 1
    return reduce(gcd, counts)


def get_reduced_stoichiometry(atom_counts: dict) -> dict:
    """
    Get reduced stoichiometry by dividing all counts by their GCD.

    This converts absolute atom counts to a per-formula-unit stoichiometry,
    which is useful for comparing compositions across different cell sizes.

    Args:
        atom_counts: Dictionary mapping elements to atom counts

    Returns:
        Dictionary with reduced stoichiometry (per formula unit)

    Example:
        >>> counts = {'Ag': 8, 'O': 4}  # Supercell of Ag2O
        >>> get_reduced_stoichiometry(counts)
        {'Ag': 2, 'O': 1}
    """
    common_divisor = get_formula_units(atom_counts)
    return {
        element: count // common_divisor
        for element, count in atom_counts.items()
    }


def get_metal_elements(atom_counts: dict) -> list:
    """
    Get metal elements (all non-oxygen elements) sorted alphabetically.

    In oxide systems, this identifies the metal cations by excluding oxygen.
    Elements are sorted to ensure consistent ordering across modules.

    Args:
        atom_counts: Dictionary mapping elements to atom counts

    Returns:
        Sorted list of metal element symbols

    Example:
        >>> counts = {'Ag': 3, 'P': 1, 'O': 4}  # Ag3PO4
        >>> get_metal_elements(counts)
        ['Ag', 'P']
    """
    return sorted(element for element in atom_counts if element != 'O')

@task.calcfunction
def extract_total_energy(energies: orm.Dict) -> orm.Float:
    """
    Extract total energy from VASP energies output.
    
    Args:
        energies: Dictionary containing energy outputs from VASP (from misc output)
    
    Returns:
        Total energy as Float
    """
    energy_dict = energies.get_dict()
    if 'total_energies' in energy_dict:
        energy_dict = energy_dict['total_energies']

    for key in ('energy_extrapolated', 'energy_no_entropy', 'energy'):
        if key in energy_dict:
            return orm.Float(energy_dict[key])

    available = ', '.join(sorted(energy_dict.keys()))
    raise ValueError(f'Unable to find total energy in VASP outputs. Available keys: {available}')
