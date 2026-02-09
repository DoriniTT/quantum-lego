"""Tests for AIMD tasks."""
from aiida import orm, load_profile
from ase.build import bulk
from quantum_lego.core.common.aimd.tasks import create_supercell

# Load AiiDA profile for tests
load_profile('presto')


def test_create_supercell_basic():
    """Test supercell creation."""
    # Create simple structure
    atoms = bulk('Al', 'fcc', a=4.0)
    structure = orm.StructureData(ase=atoms)
    spec = orm.List(list=[2, 2, 1])

    # Create 2x2x1 supercell - call the underlying calcfunction
    from quantum_lego.core.common.aimd.tasks import create_supercell_calcfunc
    supercell = create_supercell_calcfunc(structure, spec)

    # Check result is StructureData
    assert isinstance(supercell, orm.StructureData)
    assert len(supercell.sites) == len(structure.sites) * 4  # 2*2*1

    # Check cell dimensions
    original_cell = structure.cell
    super_cell = supercell.cell
    assert abs(super_cell[0][0] - 2 * original_cell[0][0]) < 0.01
    assert abs(super_cell[1][1] - 2 * original_cell[1][1]) < 0.01
    assert abs(super_cell[2][2] - original_cell[2][2]) < 0.01


def test_create_supercell_3x3x2():
    """Test larger supercell."""
    atoms = bulk('Fe', 'bcc', a=2.87)
    structure = orm.StructureData(ase=atoms)
    spec = orm.List(list=[3, 3, 2])

    from quantum_lego.core.common.aimd.tasks import create_supercell_calcfunc
    supercell = create_supercell_calcfunc(structure, spec)

    assert isinstance(supercell, orm.StructureData)
    assert len(supercell.sites) == len(structure.sites) * 18  # 3*3*2
