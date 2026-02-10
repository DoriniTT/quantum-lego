"""Tier2 & tier3 integration tests for the DOS lego brick.

Tier2: Tests WorkGraph construction with real AiiDA nodes (no VASP).
Tier3: Tests against pre-computed DOS results.
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
from aiida_workgraph import WorkGraph, task  # noqa: E402


# ============================================================================
# TIER 2 — WorkGraph construction tests (no VASP needed)
# ============================================================================

@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestDosValidation:
    """Test DOS brick validation logic."""

    def test_validate_stage_rejects_missing_scf_incar(self):
        """validate_stage should reject DOS stage without scf_incar."""
        from quantum_lego.core.bricks.dos import validate_stage

        stage = {
            'name': 'bad_dos',
            'type': 'dos',
            'dos_incar': {'ismear': -5},
            'structure_from': 'relax',
        }

        with pytest.raises(ValueError, match="scf_incar"):
            validate_stage(stage, {'relax'})

    def test_validate_stage_rejects_missing_dos_incar(self):
        """validate_stage should reject DOS stage without dos_incar."""
        from quantum_lego.core.bricks.dos import validate_stage

        stage = {
            'name': 'bad_dos',
            'type': 'dos',
            'scf_incar': {'encut': 300},
            'structure_from': 'relax',
        }

        with pytest.raises(ValueError, match="dos_incar"):
            validate_stage(stage, {'relax'})

    def test_validate_stage_requires_structure_source(self):
        """validate_stage should require structure or structure_from for DOS stages."""
        from quantum_lego.core.bricks.dos import validate_stage

        stage = {
            'name': 'bad_dos',
            'type': 'dos',
            'scf_incar': {'encut': 300},
            'dos_incar': {'ismear': -5},
        }

        with pytest.raises(ValueError, match="structure source"):
            validate_stage(stage, set())

    def test_validate_stage_accepts_explicit_structure(self):
        """validate_stage should accept DOS stage with explicit structure."""
        from quantum_lego.core.bricks.dos import validate_stage

        stage = {
            'name': 'dos',
            'type': 'dos',
            'scf_incar': {'encut': 300},
            'dos_incar': {'ismear': -5},
            'structure': object(),
        }

        validate_stage(stage, set())

    def test_validate_stage_rejects_nonexistent_structure_from(self):
        """validate_stage should reject structure_from that doesn't reference a previous stage."""
        from quantum_lego.core.bricks.dos import validate_stage

        stage = {
            'name': 'dos',
            'type': 'dos',
            'scf_incar': {'encut': 300},
            'dos_incar': {'ismear': -5},
            'structure_from': 'nonexistent_stage',
        }

        with pytest.raises(ValueError, match="must reference"):
            validate_stage(stage, {'relax'})


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestDosImportAndBasic:
    """Test that DOS brick can be imported and basic structures work."""

    def test_dos_brick_importable(self):
        """DOS brick should import without errors."""
        from quantum_lego.core.bricks import dos
        assert dos is not None
        assert hasattr(dos, 'validate_stage')
        assert hasattr(dos, 'create_stage_tasks')
        assert hasattr(dos, 'expose_stage_outputs')
        assert hasattr(dos, 'get_stage_results')
        assert hasattr(dos, 'print_stage_results')
        assert hasattr(dos, 'PORTS')

    def test_dos_ports_defined(self):
        """DOS brick PORTS should define expected inputs/outputs."""
        from quantum_lego.core.bricks.dos import PORTS
        assert 'inputs' in PORTS
        assert 'outputs' in PORTS
        assert 'structure' in PORTS['inputs']

    def test_create_structure_fixtures(self, si_diamond_structure, sno2_rutile_structure):
        """Test structure fixtures are available."""
        assert si_diamond_structure is not None
        assert sno2_rutile_structure is not None
        assert len(si_diamond_structure.sites) == 2
        assert len(sno2_rutile_structure.sites) == 6


# ============================================================================
# TIER 3 — Result extraction from pre-computed DOS calculations
# ============================================================================

@pytest.mark.tier3
@pytest.mark.requires_aiida
class TestDosResultExtraction:
    """Validate result extraction from a completed DOS calculation (SnO2)."""

    def test_get_dos_results_returns_energy(self, reference_pks):
        """get_dos_results should return SCF energy for SnO2 DOS."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_dos_results

        pk = reference_pks['dos']['dos_sno2']['pk']
        load_node_or_skip(pk)

        result = get_dos_results(pk)
        assert result['energy'] is not None, "DOS SCF energy must not be None"
        assert isinstance(result['energy'], float)
        assert result['energy'] < 0, f"SnO2 SCF energy should be negative, got {result['energy']}"

    def test_get_dos_results_returns_scf_misc(self, reference_pks):
        """get_dos_results should return scf_misc dict."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_dos_results

        pk = reference_pks['dos']['dos_sno2']['pk']
        load_node_or_skip(pk)

        result = get_dos_results(pk)
        assert result['scf_misc'] is not None, "scf_misc must not be None"
        assert isinstance(result['scf_misc'], dict)

    def test_get_dos_results_returns_dos_misc(self, reference_pks):
        """get_dos_results should return dos_misc dict."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_dos_results

        pk = reference_pks['dos']['dos_sno2']['pk']
        load_node_or_skip(pk)

        result = get_dos_results(pk)
        assert result['dos_misc'] is not None, "dos_misc must not be None"
        assert isinstance(result['dos_misc'], dict)

    def test_get_dos_results_returns_files(self, reference_pks):
        """get_dos_results should return retrieved files."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_dos_results

        pk = reference_pks['dos']['dos_sno2']['pk']
        load_node_or_skip(pk)

        result = get_dos_results(pk)
        assert result['files'] is not None, "Retrieved files must not be None"

    def test_get_dos_results_schema(self, reference_pks):
        """get_dos_results should return all expected keys."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_dos_results

        pk = reference_pks['dos']['dos_sno2']['pk']
        load_node_or_skip(pk)

        result = get_dos_results(pk)
        required_keys = {'energy', 'scf_misc', 'dos_misc', 'files', 'pk'}
        assert required_keys.issubset(result.keys()), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )
        assert result['pk'] == pk
