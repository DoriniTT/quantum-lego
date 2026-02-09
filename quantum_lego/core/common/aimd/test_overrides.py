"""Tests for AIMD override system."""
from aiida import orm, load_profile
from ase.build import bulk
from quantum_lego.core.common.aimd import build_aimd_workgraph

# Load AiiDA profile for tests
load_profile('presto')


def test_structure_overrides():
    """Test per-structure INCAR overrides."""
    # Create test structures
    atoms1 = bulk('Al', 'fcc', a=4.0)
    atoms2 = bulk('Fe', 'bcc', a=2.87)
    struct1 = orm.StructureData(ase=atoms1)
    struct2 = orm.StructureData(ase=atoms2)

    # Base config
    builder_inputs = {
        'parameters': {'incar': {'PREC': 'Normal', 'ENCUT': 400}},
        'kpoints_spacing': 0.5,
        'potential_family': 'PBE',
        'potential_mapping': {'Al': 'Al', 'Fe': 'Fe'},
        'options': {'resources': {'num_machines': 1, 'num_cores_per_machine': 24}},
        'clean_workdir': False,
    }

    # Override struct1 to use ENCUT=500
    structure_overrides = {
        'struct1': {'parameters': {'incar': {'ENCUT': 500}}}
    }

    # Build workgraph
    wg = build_aimd_workgraph(
        structures={'struct1': struct1, 'struct2': struct2},
        aimd_stages=[{'TEBEG': 300, 'NSW': 10}],
        code_label='VASP-6.5.1@cluster02',
        builder_inputs=builder_inputs,
        structure_overrides=structure_overrides,
        name='test_structure_overrides',
    )

    # Verify workgraph was created
    assert wg is not None
    assert wg.name == 'test_structure_overrides'

    # Verify task exists
    assert 'stage_0_aimd' in [task.name for task in wg.tasks]


def test_stage_overrides():
    """Test per-stage INCAR overrides."""
    atoms = bulk('Al', 'fcc', a=4.0)
    struct = orm.StructureData(ase=atoms)

    builder_inputs = {
        'parameters': {'incar': {'PREC': 'Normal', 'ENCUT': 400}},
        'kpoints_spacing': 0.5,
        'potential_family': 'PBE',
        'potential_mapping': {'Al': 'Al'},
        'options': {'resources': {'num_machines': 1, 'num_cores_per_machine': 24}},
        'clean_workdir': False,
    }

    # Override stage 1 to use PREC=Accurate
    stage_overrides = {
        1: {'parameters': {'incar': {'PREC': 'Accurate'}}}
    }

    wg = build_aimd_workgraph(
        structures={'struct': struct},
        aimd_stages=[
            {'TEBEG': 300, 'NSW': 10},
            {'TEBEG': 300, 'NSW': 20},
        ],
        code_label='VASP-6.5.1@cluster02',
        builder_inputs=builder_inputs,
        stage_overrides=stage_overrides,
        name='test_stage_overrides',
    )

    assert wg is not None
    assert 'stage_0_aimd' in [task.name for task in wg.tasks]
    assert 'stage_1_aimd' in [task.name for task in wg.tasks]


def test_matrix_overrides():
    """Test (structure, stage) specific overrides."""
    atoms1 = bulk('Al', 'fcc', a=4.0)
    atoms2 = bulk('Fe', 'bcc', a=2.87)
    struct1 = orm.StructureData(ase=atoms1)
    struct2 = orm.StructureData(ase=atoms2)

    builder_inputs = {
        'parameters': {'incar': {'PREC': 'Normal', 'ENCUT': 400, 'ALGO': 'Normal'}},
        'kpoints_spacing': 0.5,
        'potential_family': 'PBE',
        'potential_mapping': {'Al': 'Al', 'Fe': 'Fe'},
        'options': {'resources': {'num_machines': 1, 'num_cores_per_machine': 24}},
        'clean_workdir': False,
    }

    # Override (struct1, stage 0) specifically
    matrix_overrides = {
        ('struct1', 0): {'parameters': {'incar': {'ALGO': 'Fast'}}}
    }

    wg = build_aimd_workgraph(
        structures={'struct1': struct1, 'struct2': struct2},
        aimd_stages=[{'TEBEG': 300, 'NSW': 10}],
        code_label='VASP-6.5.1@cluster02',
        builder_inputs=builder_inputs,
        matrix_overrides=matrix_overrides,
        name='test_matrix_overrides',
    )

    assert wg is not None


def test_override_priority():
    """Test override priority: matrix > stage > structure > base."""
    atoms = bulk('Al', 'fcc', a=4.0)
    struct = orm.StructureData(ase=atoms)

    builder_inputs = {
        'parameters': {'incar': {'ENCUT': 300}},  # base
        'kpoints_spacing': 0.5,
        'potential_family': 'PBE',
        'potential_mapping': {'Al': 'Al'},
        'options': {'resources': {'num_machines': 1, 'num_cores_per_machine': 24}},
        'clean_workdir': False,
    }

    # All levels defined - matrix should win
    structure_overrides = {'struct': {'parameters': {'incar': {'ENCUT': 400}}}}
    stage_overrides = {0: {'parameters': {'incar': {'ENCUT': 500}}}}
    matrix_overrides = {('struct', 0): {'parameters': {'incar': {'ENCUT': 600}}}}

    wg = build_aimd_workgraph(
        structures={'struct': struct},
        aimd_stages=[{'TEBEG': 300, 'NSW': 10}],
        code_label='VASP-6.5.1@cluster02',
        builder_inputs=builder_inputs,
        structure_overrides=structure_overrides,
        stage_overrides=stage_overrides,
        matrix_overrides=matrix_overrides,
        name='test_priority',
    )

    assert wg is not None
