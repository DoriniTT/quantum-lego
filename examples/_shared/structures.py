"""Structure helpers for quantum-lego examples."""

from __future__ import annotations

from pathlib import Path

from aiida import orm
from ase.build import bulk
from ase.io import read

from examples._shared.config import STRUCTURES_DIR


def create_si_structure() -> orm.StructureData:
    """Create a simple Si diamond structure (a=5.43 A)."""
    si_ase = bulk('Si', 'diamond', a=5.43)
    return orm.StructureData(ase=si_ase)


def load_structure(filename: str | Path) -> orm.StructureData:
    """Load a structure from ``examples/structures``.

    Args:
        filename: Name of a VASP file (for example ``sno2.vasp``).

    Returns:
        AiiDA ``StructureData`` built from the file.
    """
    path = STRUCTURES_DIR / Path(filename)
    if not path.exists():
        raise FileNotFoundError(f'Structure file not found: {path}')
    return orm.StructureData(ase=read(path))


def load_sno2() -> orm.StructureData:
    """Load canonical rutile SnO2 structure."""
    return load_structure('sno2.vasp')


def load_sno2_pnnm() -> orm.StructureData:
    """Load canonical Pnnm SnO2 structure."""
    return load_structure('sno2_pnnm.vasp')


def load_nio() -> orm.StructureData:
    """Load canonical NiO structure."""
    return load_structure('nio.vasp')
