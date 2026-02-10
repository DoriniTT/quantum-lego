"""Utility functions for convergence workflows.

This module provides shared utility functions used by both ENCUT/k-points
and thickness convergence workflows.
"""

from __future__ import annotations

from aiida import orm
from ase.io import read

from ..utils import get_vasp_parser_settings


def _load_structure_from_file(filepath: str) -> orm.StructureData:
    """Load structure from a file using ASE.

    Args:
        filepath: Path to structure file.

    Returns:
        AiiDA StructureData node.
    """
    atoms = read(filepath)
    return orm.StructureData(ase=atoms)


def _get_thickness_settings():
    """Parser settings for thickness convergence calculations.

    Returns:
        Dict with VASP parser settings including energy extraction.
    """
    return get_vasp_parser_settings(add_energy=True)


__all__ = [
    '_load_structure_from_file',
    '_get_thickness_settings',
]
