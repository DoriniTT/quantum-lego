"""Unit tests for workflow_utils module.

Tests shared utility functions extracted from workgraph.py.
All tests are tier1 (pure Python, no AiiDA profile needed).
"""

import pytest


@pytest.mark.tier1
class TestBuildIndexedOutputName:
    """Tests for _build_indexed_output_name()."""

    def test_basic_naming(self):
        from quantum_lego.core.workflow_utils import _build_indexed_output_name
        assert _build_indexed_output_name(1, 'relax') == 's01_relax'

    def test_double_digit_index(self):
        from quantum_lego.core.workflow_utils import _build_indexed_output_name
        assert _build_indexed_output_name(10, 'scf') == 's10_scf'

    def test_zero_index(self):
        from quantum_lego.core.workflow_utils import _build_indexed_output_name
        assert _build_indexed_output_name(0, 'test') == 's00_test'

    def test_complex_name(self):
        from quantum_lego.core.workflow_utils import _build_indexed_output_name
        assert _build_indexed_output_name(3, 'md_production_0') == 's03_md_production_0'


@pytest.mark.tier1
class TestBuildCombinedTrajectoryOutputName:
    """Tests for _build_combined_trajectory_output_name()."""

    def test_basic(self):
        from quantum_lego.core.workflow_utils import _build_combined_trajectory_output_name
        assert _build_combined_trajectory_output_name(6) == 's07_combined_trajectory'

    def test_single_stage(self):
        from quantum_lego.core.workflow_utils import _build_combined_trajectory_output_name
        assert _build_combined_trajectory_output_name(1) == 's02_combined_trajectory'

    def test_zero_stages(self):
        from quantum_lego.core.workflow_utils import _build_combined_trajectory_output_name
        assert _build_combined_trajectory_output_name(0) == 's01_combined_trajectory'


@pytest.mark.tier1
class TestValidateStages:
    """Tests for _validate_stages() imported from workflow_utils."""

    def _validate(self, stages):
        from quantum_lego.core.workflow_utils import _validate_stages
        _validate_stages(stages)

    def test_empty_stages_raises(self):
        with pytest.raises(ValueError, match="empty"):
            self._validate([])

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._validate([{'type': 'vasp', 'incar': {'NSW': 0}, 'restart': None}])

    def test_duplicate_names_raises(self):
        stages = [
            {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None},
            {'name': 'relax', 'incar': {'NSW': 0}, 'restart': 'relax'},
        ]
        with pytest.raises(ValueError, match="Duplicate"):
            self._validate(stages)

    def test_invalid_type_raises(self):
        stages = [{'name': 'step', 'type': 'unknown', 'incar': {'NSW': 0}, 'restart': None}]
        with pytest.raises(ValueError, match="must be one of"):
            self._validate(stages)

    def test_single_valid_vasp_passes(self):
        stages = [{'name': 'relax', 'type': 'vasp', 'incar': {'NSW': 100}, 'restart': None}]
        self._validate(stages)


@pytest.mark.tier1
class TestBackwardCompatImports:
    """Tests that importing from workgraph.py still works (facade compatibility)."""

    def test_build_indexed_output_name_from_workgraph(self):
        from quantum_lego.core.workgraph import _build_indexed_output_name
        assert _build_indexed_output_name(3, 'md_production_0') == 's03_md_production_0'

    def test_build_combined_trajectory_output_name_from_workgraph(self):
        from quantum_lego.core.workgraph import _build_combined_trajectory_output_name
        assert _build_combined_trajectory_output_name(6) == 's07_combined_trajectory'

    def test_validate_stages_from_workgraph(self):
        from quantum_lego.core.workgraph import _validate_stages
        with pytest.raises(ValueError, match="empty"):
            _validate_stages([])
