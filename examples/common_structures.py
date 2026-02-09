"""Common structure utilities for quantum-lego examples.

This module provides reusable structure creation functions for example scripts,
reducing code duplication across multiple examples.
"""

from aiida import orm
from ase.build import bulk


def create_si_structure():
    """Create a simple Si diamond structure.
    
    Returns:
        orm.StructureData: Silicon structure with diamond lattice (a=5.43 Å)
    
    Example:
        >>> from examples.common_structures import create_si_structure
        >>> structure = create_si_structure()
        >>> print(structure.get_formula())
        Si2
    """
    si_ase = bulk('Si', 'diamond', a=5.43)
    structure = orm.StructureData(ase=si_ase)
    return structure
