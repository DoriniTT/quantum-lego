"""Tier2 & tier3 integration tests for the batch lego brick.

Tier2: Tests WorkGraph construction with real AiiDA nodes (no VASP).
Tier3: Tests against pre-computed batch results.
"""

import pytest


def _check_aiida():
    try:
        from aiida import load_profile
        load_profile()
        return True
    except Exception:
        return False


AIIDA_AVAILABLE = _check_aiida()

if not AIIDA_AVAILABLE:
    pytest.skip("AiiDA not configured", allow_module_level=True)

from aiida import orm  # noqa: E402


# ============================================================================
# TIER 2 — Validation tests (no VASP needed)
# ============================================================================

@pytest.mark.tier1
class TestBatchValidation:
    """Test batch brick validation logic."""

    def test_validate_stage_rejects_empty_calculations(self):
        """validate_stage should reject batch stage with empty calculations."""
        from quantum_lego.core.bricks.batch import validate_stage

        stage = {
            'name': 'bad_batch',
            'type': 'batch',
            'structure_from': 'relax',
            'base_incar': {'encut': 300},
            'calculations': {},
        }

        with pytest.raises(ValueError, match="non-empty 'calculations'"):
            validate_stage(stage, {'relax'})

    def test_validate_stage_rejects_missing_structure_from(self):
        """validate_stage should reject batch stage without structure_from."""
        from quantum_lego.core.bricks.batch import validate_stage

        stage = {
            'name': 'bad_batch',
            'type': 'batch',
            'base_incar': {'encut': 300},
            'calculations': {'calc1': {}},
        }

        with pytest.raises(ValueError, match="structure_from"):
            validate_stage(stage, set())

    def test_validate_stage_rejects_missing_base_incar(self):
        """validate_stage should reject batch stage without base_incar."""
        from quantum_lego.core.bricks.batch import validate_stage

        stage = {
            'name': 'bad_batch',
            'type': 'batch',
            'structure_from': 'relax',
            'calculations': {'calc1': {}},
        }

        with pytest.raises(ValueError, match="base_incar"):
            validate_stage(stage, {'relax'})

    def test_validate_stage_rejects_nonexistent_structure_from(self):
        """validate_stage should reject structure_from that doesn't reference a previous stage."""
        from quantum_lego.core.bricks.batch import validate_stage

        stage = {
            'name': 'batch',
            'type': 'batch',
            'structure_from': 'nonexistent_stage',
            'base_incar': {'encut': 300},
            'calculations': {'calc1': {}},
        }

        with pytest.raises(ValueError, match="must reference"):
            validate_stage(stage, {'relax'})


@pytest.mark.tier1
class TestBatchImport:
    """Test that batch brick can be imported and basic functionality works."""

    def test_batch_brick_importable(self):
        """Batch brick should import without errors."""
        from quantum_lego.core.bricks import batch
        assert batch is not None
        assert hasattr(batch, 'validate_stage')
        assert hasattr(batch, 'create_stage_tasks')
        assert hasattr(batch, 'expose_stage_outputs')
        assert hasattr(batch, 'get_stage_results')
        assert hasattr(batch, 'print_stage_results')
        assert hasattr(batch, 'PORTS')

    def test_batch_ports_defined(self):
        """Batch brick PORTS should define expected inputs/outputs."""
        from quantum_lego.core.bricks.batch import PORTS
        assert 'inputs' in PORTS
        assert 'outputs' in PORTS
        assert 'structure' in PORTS['inputs']
        # 'calculations' is a stage config field, not a port
        assert '{label}_energy' in PORTS['outputs']

    def test_batch_deep_merge_utility(self):
        """Test that batch brick can use deep_merge_dicts for INCAR merging."""
        from quantum_lego.core.common.utils import deep_merge_dicts

        base = {'incar': {'encut': 300, 'ismear': 0}}
        override = {'incar': {'encut': 400}}
        merged = deep_merge_dicts(base, override)

        assert merged['incar']['encut'] == 400
        assert merged['incar']['ismear'] == 0


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestBatchStructureFixtures:
    """Test that AiiDA structure fixtures are available for batch tests."""

    def test_create_structure_fixtures(self, si_diamond_structure):
        """Test that structure fixtures work for batch calculations."""
        assert si_diamond_structure is not None
        assert len(si_diamond_structure.sites) == 2


# ============================================================================
# TIER 3 — Result extraction from pre-computed batch calculations
# ============================================================================

@pytest.mark.tier3
@pytest.mark.localwork
@pytest.mark.requires_aiida
class TestBatchResultExtraction:
    """Validate result extraction from a completed batch calculation (Si ENCUT scan)."""

    def test_batch_stage_results_schema(self, reference_pks):
        """get_stage_results should return batch-type dict with calculations."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['batch']['batch_si_encut']
        seq_result = build_sequential_result(scenario)

        stage_names = seq_result['__stage_names__']
        assert len(stage_names) >= 1, "Batch pipeline should have at least 1 stage"

        # Get the batch stage (first one)
        batch_stage_name = stage_names[0]
        result = get_stage_results(seq_result, batch_stage_name)

        assert result['type'] == 'batch'
        assert result['stage'] == batch_stage_name
        assert 'calculations' in result
        assert isinstance(result['calculations'], dict)

    def test_batch_has_three_calculations(self, reference_pks):
        """Batch stage should contain exactly 3 calculations (3 ENCUT values)."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['batch']['batch_si_encut']
        seq_result = build_sequential_result(scenario)

        batch_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, batch_stage_name)

        calcs = result['calculations']
        assert len(calcs) == 3, f"Expected 3 batch calculations, got {len(calcs)}"

    def test_batch_all_calculations_have_energy(self, reference_pks):
        """Each batch calculation should have a negative energy."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['batch']['batch_si_encut']
        seq_result = build_sequential_result(scenario)

        batch_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, batch_stage_name)

        for label, calc_result in result['calculations'].items():
            assert calc_result['energy'] is not None, (
                f"Calculation '{label}' should have an energy"
            )
            assert calc_result['energy'] < 0, (
                f"Calculation '{label}' energy should be negative, got {calc_result['energy']}"
            )

    def test_batch_energies_differ_by_encut(self, reference_pks):
        """Energies should vary with ENCUT (not all identical)."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['batch']['batch_si_encut']
        seq_result = build_sequential_result(scenario)

        batch_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, batch_stage_name)

        energies = [c['energy'] for c in result['calculations'].values()]
        # With different ENCUT values, energies should not all be identical
        assert len(set(round(e, 6) for e in energies)) > 1, (
            f"Energies should differ with ENCUT, got {energies}"
        )

    def test_batch_all_calculations_have_misc(self, reference_pks):
        """Each batch calculation should have a misc dict."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['batch']['batch_si_encut']
        seq_result = build_sequential_result(scenario)

        batch_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, batch_stage_name)

        for label, calc_result in result['calculations'].items():
            assert calc_result['misc'] is not None, (
                f"Calculation '{label}' should have misc dict"
            )
            assert isinstance(calc_result['misc'], dict)
