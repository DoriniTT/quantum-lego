"""Unit tests for EOS enhancements: labels, recommended info, refine brick.

Tests:
- gather_eos_data returns labels in output
- fit_birch_murnaghan_eos returns recommended_label/volume_error
- build_recommended_structure scales correctly
- build_refined_structures generates correct structures/volumes
- birch_murnaghan_refine validate_stage checks
- Connection validation for new brick type and recommended_structure output

All tests are tier1 (pure Python, no AiiDA profile needed) unless marked otherwise.
"""

import os
import pytest
import importlib.util

# Import connections.py directly (no AiiDA dependency)
_connections_path = os.path.join(
    os.path.dirname(__file__), os.pardir,
    'quantum_lego', 'core', 'bricks', 'connections.py',
)
_connections_path = os.path.normpath(_connections_path)
_spec = importlib.util.spec_from_file_location(
    'quantum_lego.core.bricks.connections', _connections_path,
)
_connections = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_connections)

PORT_TYPES = _connections.PORT_TYPES
ALL_PORTS = _connections.ALL_PORTS
BIRCH_MURNAGHAN_PORTS = _connections.BIRCH_MURNAGHAN_PORTS
BIRCH_MURNAGHAN_REFINE_PORTS = _connections.BIRCH_MURNAGHAN_REFINE_PORTS
validate_connections = _connections.validate_connections
_validate_port_types = _connections._validate_port_types


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def relax_stage():
    return {
        'name': 'relax',
        'type': 'vasp',
        'incar': {'encut': 520, 'nsw': 100, 'ibrion': 2, 'isif': 3},
        'restart': None,
    }


@pytest.fixture
def batch_stage():
    return {
        'name': 'volume_scan',
        'type': 'batch',
        'structure_from': 'input',
        'base_incar': {'encut': 520, 'nsw': 0},
        'calculations': {
            'v_m006': {},
            'v_m004': {},
            'v_m002': {},
            'v_p000': {},
            'v_p002': {},
            'v_p004': {},
            'v_p006': {},
        },
    }


@pytest.fixture
def bm_stage():
    return {
        'name': 'eos_fit',
        'type': 'birch_murnaghan',
        'batch_from': 'volume_scan',
        'volumes': {
            'v_m006': 70.0,
            'v_m004': 72.0,
            'v_m002': 74.0,
            'v_p000': 76.0,
            'v_p002': 78.0,
            'v_p004': 80.0,
            'v_p006': 82.0,
        },
    }


@pytest.fixture
def refine_stage():
    return {
        'name': 'eos_refine',
        'type': 'birch_murnaghan_refine',
        'eos_from': 'eos_fit',
        'structure_from': 'input',
        'base_incar': {'encut': 520, 'nsw': 0},
        'kpoints_spacing': 0.03,
        'refine_strain_range': 0.02,
        'refine_n_points': 7,
    }


# ---------------------------------------------------------------------------
# TestBirchMurnaghanPortsUpdated
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBirchMurnaghanPortsUpdated:
    """Verify BIRCH_MURNAGHAN_PORTS has recommended_structure output."""

    def test_bm_has_recommended_structure_output(self):
        assert 'recommended_structure' in BIRCH_MURNAGHAN_PORTS['outputs']

    def test_bm_recommended_structure_type_is_structure(self):
        port = BIRCH_MURNAGHAN_PORTS['outputs']['recommended_structure']
        assert port['type'] == 'structure'

    def test_bm_recommended_structure_type_recognized(self):
        assert BIRCH_MURNAGHAN_PORTS['outputs']['recommended_structure']['type'] in PORT_TYPES

    def test_bm_still_has_eos_result_output(self):
        assert 'eos_result' in BIRCH_MURNAGHAN_PORTS['outputs']


# ---------------------------------------------------------------------------
# TestBirchMurnaghanRefinePortDeclarations
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBirchMurnaghanRefinePortDeclarations:
    """Verify BIRCH_MURNAGHAN_REFINE_PORTS declarations."""

    def test_refine_registered_in_all_ports(self):
        assert 'birch_murnaghan_refine' in ALL_PORTS

    def test_refine_has_eos_result_input(self):
        assert 'eos_result' in BIRCH_MURNAGHAN_REFINE_PORTS['inputs']

    def test_refine_eos_result_input_required(self):
        port = BIRCH_MURNAGHAN_REFINE_PORTS['inputs']['eos_result']
        assert port['required'] is True

    def test_refine_eos_result_source_is_eos_from(self):
        port = BIRCH_MURNAGHAN_REFINE_PORTS['inputs']['eos_result']
        assert port['source'] == 'eos_from'

    def test_refine_eos_result_compatible_with_bm(self):
        port = BIRCH_MURNAGHAN_REFINE_PORTS['inputs']['eos_result']
        assert 'birch_murnaghan' in port['compatible_bricks']

    def test_refine_has_structure_input(self):
        assert 'structure' in BIRCH_MURNAGHAN_REFINE_PORTS['inputs']

    def test_refine_structure_input_required(self):
        port = BIRCH_MURNAGHAN_REFINE_PORTS['inputs']['structure']
        assert port['required'] is True

    def test_refine_has_eos_result_output(self):
        assert 'eos_result' in BIRCH_MURNAGHAN_REFINE_PORTS['outputs']

    def test_refine_has_recommended_structure_output(self):
        assert 'recommended_structure' in BIRCH_MURNAGHAN_REFINE_PORTS['outputs']

    def test_refine_recommended_structure_type_is_structure(self):
        port = BIRCH_MURNAGHAN_REFINE_PORTS['outputs']['recommended_structure']
        assert port['type'] == 'structure'

    def test_all_refine_port_types_recognized(self):
        _validate_port_types(BIRCH_MURNAGHAN_REFINE_PORTS, 'birch_murnaghan_refine')

    def test_refine_has_two_inputs(self):
        assert len(BIRCH_MURNAGHAN_REFINE_PORTS['inputs']) == 2

    def test_refine_has_two_outputs(self):
        assert len(BIRCH_MURNAGHAN_REFINE_PORTS['outputs']) == 2


# ---------------------------------------------------------------------------
# TestBirchMurnaghanRefineValidateStage
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBirchMurnaghanRefineValidateStage:
    """Tests for birch_murnaghan_refine.validate_stage()."""

    def _validate(self, stage, stage_names=None):
        from quantum_lego.core.bricks.birch_murnaghan_refine import validate_stage
        if stage_names is None:
            stage_names = set()
        validate_stage(stage, stage_names)

    def test_valid_passes(self, refine_stage):
        self._validate(
            refine_stage,
            stage_names={'volume_scan', 'eos_fit'},
        )

    def test_missing_eos_from_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="eos_from"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_eos_from_unknown_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'unknown',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="previous stage name"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_missing_structure_from_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'base_incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="structure_from"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_structure_from_unknown_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'unknown',
            'base_incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="previous stage name"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_structure_from_input_passes(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
        }
        self._validate(stage, stage_names={'eos_fit'})

    def test_missing_base_incar_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'input',
        }
        with pytest.raises(ValueError, match="base_incar"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_n_points_too_few_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
            'refine_n_points': 3,
        }
        with pytest.raises(ValueError, match="refine_n_points"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_n_points_not_int_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
            'refine_n_points': 7.5,
        }
        with pytest.raises(ValueError, match="refine_n_points"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_strain_range_zero_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
            'refine_strain_range': 0,
        }
        with pytest.raises(ValueError, match="refine_strain_range"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_strain_range_negative_raises(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
            'refine_strain_range': -0.02,
        }
        with pytest.raises(ValueError, match="refine_strain_range"):
            self._validate(stage, stage_names={'eos_fit'})

    def test_default_n_points_and_strain_passes(self):
        stage = {
            'name': 'refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
        }
        self._validate(stage, stage_names={'eos_fit'})


# ---------------------------------------------------------------------------
# TestValidateConnectionsRefine
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestValidateConnectionsRefine:
    """Connection validation tests for the refine brick."""

    def test_full_bm_pipeline_passes(self, batch_stage, bm_stage, refine_stage):
        warnings = validate_connections([batch_stage, bm_stage, refine_stage])
        assert isinstance(warnings, list)

    def test_refine_from_non_bm_rejected(self, batch_stage):
        refine = {
            'name': 'eos_refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'volume_scan',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="doesn't produce it|compatible with bricks"):
            validate_connections([batch_stage, refine])

    def test_refine_eos_from_unknown_rejected(self, batch_stage, bm_stage):
        refine = {
            'name': 'eos_refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'nonexistent',
            'structure_from': 'input',
            'base_incar': {'encut': 520},
        }
        with pytest.raises(ValueError, match="unknown stage"):
            validate_connections([batch_stage, bm_stage, refine])

    def test_refine_structure_from_input_passes(self, batch_stage, bm_stage,
                                                 refine_stage):
        validate_connections([batch_stage, bm_stage, refine_stage])

    def test_refine_structure_from_vasp_passes(self, relax_stage, batch_stage,
                                                bm_stage):
        batch = {**batch_stage, 'structure_from': 'relax'}
        refine = {
            'name': 'eos_refine',
            'type': 'birch_murnaghan_refine',
            'eos_from': 'eos_fit',
            'structure_from': 'relax',
            'base_incar': {'encut': 520},
        }
        validate_connections([relax_stage, batch, bm_stage, refine])

    def test_refine_produces_structure_output(self, batch_stage, bm_stage,
                                               refine_stage):
        """After refine, a VASP stage can use its structure via structure_from."""
        vasp_after = {
            'name': 'scf',
            'type': 'vasp',
            'incar': {'encut': 520, 'nsw': 0},
            'restart': None,
            'structure_from': 'eos_refine',
        }
        validate_connections([batch_stage, bm_stage, refine_stage, vasp_after])

    def test_bm_produces_structure_output(self, batch_stage, bm_stage):
        """After BM, a VASP stage can use its recommended_structure via structure_from."""
        vasp_after = {
            'name': 'scf',
            'type': 'vasp',
            'incar': {'encut': 520, 'nsw': 0},
            'restart': None,
            'structure_from': 'eos_fit',
        }
        validate_connections([batch_stage, bm_stage, vasp_after])


# ---------------------------------------------------------------------------
# TestBrickRegistryRefine
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBrickRegistryRefine:
    """Tests for birch_murnaghan_refine in BRICK_REGISTRY."""

    def test_refine_in_valid_brick_types(self):
        from quantum_lego.core.bricks import VALID_BRICK_TYPES
        assert 'birch_murnaghan_refine' in VALID_BRICK_TYPES

    def test_refine_in_registry(self):
        from quantum_lego.core.bricks import BRICK_REGISTRY
        assert 'birch_murnaghan_refine' in BRICK_REGISTRY

    def test_refine_has_five_functions(self):
        from quantum_lego.core.bricks import get_brick_module
        mod = get_brick_module('birch_murnaghan_refine')
        required = (
            'validate_stage', 'create_stage_tasks', 'expose_stage_outputs',
            'get_stage_results', 'print_stage_results',
        )
        for fn_name in required:
            assert callable(getattr(mod, fn_name, None)), \
                f"birch_murnaghan_refine module missing callable '{fn_name}'"

    def test_registry_count_increased(self):
        from quantum_lego.core.bricks import BRICK_REGISTRY
        assert len(BRICK_REGISTRY) == 16


# ---------------------------------------------------------------------------
# TestGatherEosDataLabels (requires AiiDA)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestGatherEosDataLabels:
    """Test that gather_eos_data returns labels in output."""

    def test_output_includes_labels(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import gather_eos_data

        volumes = orm.List(list=[70.0, 72.0, 74.0, 76.0])
        labels = orm.List(list=['v_m006', 'v_m004', 'v_m002', 'v_p000'])
        energies = {
            'v_m006': orm.Float(-50.0),
            'v_m004': orm.Float(-51.0),
            'v_m002': orm.Float(-51.5),
            'v_p000': orm.Float(-51.2),
        }

        result = gather_eos_data._callable(volumes, labels, **energies)
        result_dict = result.get_dict()

        assert 'labels' in result_dict
        assert len(result_dict['labels']) == 4

    def test_labels_sorted_by_volume(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import gather_eos_data

        # Provide in reverse volume order
        volumes = orm.List(list=[76.0, 70.0, 74.0, 72.0])
        labels = orm.List(list=['v_p000', 'v_m006', 'v_m002', 'v_m004'])
        energies = {
            'v_p000': orm.Float(-51.2),
            'v_m006': orm.Float(-50.0),
            'v_m002': orm.Float(-51.5),
            'v_m004': orm.Float(-51.0),
        }

        result = gather_eos_data._callable(volumes, labels, **energies)
        result_dict = result.get_dict()

        # Should be sorted by volume ascending
        assert result_dict['volumes'] == [70.0, 72.0, 74.0, 76.0]
        assert result_dict['labels'] == ['v_m006', 'v_m004', 'v_m002', 'v_p000']


# ---------------------------------------------------------------------------
# TestFitBirchMurnaghanRecommended (requires AiiDA)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestFitBirchMurnaghanRecommended:
    """Test that fit_birch_murnaghan_eos returns recommended info."""

    def _make_bm_data(self):
        """Create synthetic BM data with known V0 ~ 76."""
        import numpy as np
        from aiida import orm

        volumes = np.linspace(70, 82, 7)
        # Quadratic-ish energy curve centered near v=76
        energies = 0.01 * (volumes - 76) ** 2 - 51.5

        return orm.Dict(dict={
            'volumes': volumes.tolist(),
            'energies': energies.tolist(),
            'labels': [
                'v_m006', 'v_m004', 'v_m002', 'v_p000',
                'v_p002', 'v_p004', 'v_p006',
            ],
        })

    def test_result_has_recommended_label(self):
        from quantum_lego.core.common.eos_tasks import fit_birch_murnaghan_eos

        eos_data = self._make_bm_data()
        result = fit_birch_murnaghan_eos._callable(eos_data)
        result_dict = result.get_dict()

        assert 'recommended_label' in result_dict
        assert isinstance(result_dict['recommended_label'], str)

    def test_result_has_recommended_volume(self):
        from quantum_lego.core.common.eos_tasks import fit_birch_murnaghan_eos

        eos_data = self._make_bm_data()
        result = fit_birch_murnaghan_eos._callable(eos_data)
        result_dict = result.get_dict()

        assert 'recommended_volume' in result_dict
        assert isinstance(result_dict['recommended_volume'], float)

    def test_result_has_volume_error_pct(self):
        from quantum_lego.core.common.eos_tasks import fit_birch_murnaghan_eos

        eos_data = self._make_bm_data()
        result = fit_birch_murnaghan_eos._callable(eos_data)
        result_dict = result.get_dict()

        assert 'recommended_volume_error_pct' in result_dict
        assert result_dict['recommended_volume_error_pct'] >= 0

    def test_recommended_label_is_closest_to_v0(self):
        from quantum_lego.core.common.eos_tasks import fit_birch_murnaghan_eos

        eos_data = self._make_bm_data()
        result = fit_birch_murnaghan_eos._callable(eos_data)
        result_dict = result.get_dict()

        v0 = result_dict['v0']
        rec_vol = result_dict['recommended_volume']

        # Verify it's actually the closest
        volumes = result_dict['volumes']
        for v in volumes:
            assert abs(rec_vol - v0) <= abs(v - v0) + 1e-12

    def test_result_has_labels_list(self):
        from quantum_lego.core.common.eos_tasks import fit_birch_murnaghan_eos

        eos_data = self._make_bm_data()
        result = fit_birch_murnaghan_eos._callable(eos_data)
        result_dict = result.get_dict()

        assert 'labels' in result_dict
        assert len(result_dict['labels']) == 7

    def test_without_labels_no_recommended(self):
        """When eos_data has no labels, no recommended info is added."""
        import numpy as np
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import fit_birch_murnaghan_eos

        volumes = np.linspace(70, 82, 7)
        energies = 0.01 * (volumes - 76) ** 2 - 51.5

        eos_data = orm.Dict(dict={
            'volumes': volumes.tolist(),
            'energies': energies.tolist(),
        })

        result = fit_birch_murnaghan_eos._callable(eos_data)
        result_dict = result.get_dict()

        assert 'recommended_label' not in result_dict
        assert 'recommended_volume' not in result_dict
        assert 'recommended_volume_error_pct' not in result_dict


# ---------------------------------------------------------------------------
# TestBuildRecommendedStructure (requires AiiDA)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBuildRecommendedStructure:
    """Test build_recommended_structure calcfunction."""

    def test_scales_to_v0(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import build_recommended_structure

        structure = orm.StructureData(
            cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]]
        )
        structure.append_atom(position=(0.0, 0.0, 0.0), symbols='Si')
        structure.append_atom(position=(1.5, 1.5, 1.5), symbols='Si')

        target_v0 = 30.0
        eos_result = orm.Dict(dict={'v0': target_v0})

        result = build_recommended_structure._callable(structure, eos_result)

        assert isinstance(result, orm.StructureData)
        # Volume should be close to V0
        result_vol = result.get_pymatgen().volume
        assert abs(result_vol - target_v0) < 0.01

    def test_preserves_atom_count(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import build_recommended_structure

        structure = orm.StructureData(
            cell=[[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]]
        )
        for i in range(4):
            structure.append_atom(
                position=(float(i), 0.0, 0.0), symbols='O'
            )

        eos_result = orm.Dict(dict={'v0': 60.0})

        result = build_recommended_structure._callable(structure, eos_result)
        assert len(result.sites) == 4


# ---------------------------------------------------------------------------
# TestComputeRefinedEosParams (requires AiiDA)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestComputeRefinedEosParams:
    """Test compute_refined_eos_params calcfunction."""

    def test_returns_volumes_list(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import compute_refined_eos_params

        eos_result = orm.Dict(dict={'v0': 27.0})

        result = compute_refined_eos_params._callable(
            eos_result, orm.Float(0.02), orm.Int(5),
        )

        assert 'volumes' in result
        assert isinstance(result['volumes'], orm.List)
        volumes = result['volumes'].get_list()
        assert len(volumes) == 5

    def test_returns_labels_list(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import compute_refined_eos_params

        eos_result = orm.Dict(dict={'v0': 27.0})

        result = compute_refined_eos_params._callable(
            eos_result, orm.Float(0.02), orm.Int(5),
        )

        assert 'labels' in result
        labels = result['labels'].get_list()
        assert labels == [
            'refine_00', 'refine_01', 'refine_02',
            'refine_03', 'refine_04',
        ]

    def test_volumes_span_correct_range(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import compute_refined_eos_params

        v0 = 27.0
        sr = 0.02
        eos_result = orm.Dict(dict={'v0': v0})

        result = compute_refined_eos_params._callable(
            eos_result, orm.Float(sr), orm.Int(5),
        )

        volumes = result['volumes'].get_list()
        expected_min = v0 * (1 - sr)
        expected_max = v0 * (1 + sr)

        assert abs(volumes[0] - expected_min) < 0.01
        assert abs(volumes[-1] - expected_max) < 0.01

    def test_seven_points(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import compute_refined_eos_params

        eos_result = orm.Dict(dict={'v0': 75.0})

        result = compute_refined_eos_params._callable(
            eos_result, orm.Float(0.03), orm.Int(7),
        )

        volumes = result['volumes'].get_list()
        labels = result['labels'].get_list()
        assert len(volumes) == 7
        assert len(labels) == 7


# ---------------------------------------------------------------------------
# TestBuildSingleRefinedStructure (requires AiiDA)
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestBuildSingleRefinedStructure:
    """Test build_single_refined_structure calcfunction."""

    def _make_structure(self):
        from aiida import orm

        structure = orm.StructureData(
            cell=[[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]]
        )
        structure.append_atom(position=(0.0, 0.0, 0.0), symbols='Si')
        return structure

    def test_returns_structure_data(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import build_single_refined_structure

        structure = self._make_structure()
        eos_result = orm.Dict(dict={'v0': 27.0})

        result = build_single_refined_structure._callable(
            structure, eos_result,
            orm.Float(0.02), orm.Int(5), orm.Int(0),
        )

        assert isinstance(result, orm.StructureData)

    def test_volume_matches_expected(self):
        import numpy as np
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import build_single_refined_structure

        structure = self._make_structure()
        v0 = 27.0
        sr = 0.02
        n = 5
        eos_result = orm.Dict(dict={'v0': v0})

        for idx in range(n):
            result = build_single_refined_structure._callable(
                structure, eos_result,
                orm.Float(sr), orm.Int(n), orm.Int(idx),
            )
            frac = np.linspace(-1, 1, n)[idx]
            expected_vol = v0 * (1 + frac * sr)
            actual_vol = result.get_pymatgen().volume
            assert abs(actual_vol - expected_vol) < 0.01

    def test_preserves_atom_count(self):
        from aiida import orm
        from quantum_lego.core.common.eos_tasks import build_single_refined_structure

        structure = self._make_structure()
        eos_result = orm.Dict(dict={'v0': 27.0})

        result = build_single_refined_structure._callable(
            structure, eos_result,
            orm.Float(0.02), orm.Int(5), orm.Int(2),
        )

        assert len(result.sites) == 1
