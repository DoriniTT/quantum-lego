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

    def test_fukui_analysis_stage_passes_with_valid_batch_source(self):
        stages = [
            {
                'name': 'fukui_minus',
                'type': 'batch',
                'structure_from': 'input',
                'base_incar': {'nsw': 0},
                'retrieve': ['CHGCAR'],
                'calculations': {
                    'neutral': {'incar': {'nelect': 100.0}},
                    'delta_005': {'incar': {'nelect': 99.95}},
                    'delta_010': {'incar': {'nelect': 99.90}},
                    'delta_015': {'incar': {'nelect': 99.85}},
                },
            },
            {
                'name': 'fukui_minus_analysis',
                'type': 'fukui_analysis',
                'batch_from': 'fukui_minus',
                'fukui_type': 'minus',
                'delta_n_map': {
                    'neutral': 0.0,
                    'delta_005': 0.05,
                    'delta_010': 0.10,
                    'delta_015': 0.15,
                },
            },
        ]
        self._validate(stages)

    def test_fukui_analysis_stage_rejects_wrong_delta_n_map_size(self):
        stages = [
            {
                'name': 'fukui_minus',
                'type': 'batch',
                'structure_from': 'input',
                'base_incar': {'nsw': 0},
                'retrieve': ['CHGCAR'],
                'calculations': {
                    'neutral': {'incar': {'nelect': 100.0}},
                    'delta_005': {'incar': {'nelect': 99.95}},
                    'delta_010': {'incar': {'nelect': 99.90}},
                    'delta_015': {'incar': {'nelect': 99.85}},
                },
            },
            {
                'name': 'fukui_minus_analysis',
                'type': 'fukui_analysis',
                'batch_from': 'fukui_minus',
                'fukui_type': 'minus',
                'delta_n_map': {
                    'neutral': 0.0,
                    'delta_005': 0.05,
                    'delta_010': 0.10,
                },
            },
        ]
        with pytest.raises(ValueError, match="exactly 4 entries"):
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

    def test_quick_vasp_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_vasp
        assert callable(quick_vasp)

    def test_quick_vasp_batch_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_vasp_batch
        assert callable(quick_vasp_batch)

    def test_quick_vasp_sequential_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_vasp_sequential
        assert callable(quick_vasp_sequential)

    def test_quick_dos_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_dos
        assert callable(quick_dos)

    def test_quick_dos_batch_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_dos_batch
        assert callable(quick_dos_batch)

    def test_quick_dos_sequential_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_dos_sequential
        assert callable(quick_dos_sequential)

    def test_quick_qe_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_qe
        assert callable(quick_qe)

    def test_quick_qe_sequential_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_qe_sequential
        assert callable(quick_qe_sequential)

    def test_quick_hubbard_u_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_hubbard_u
        assert callable(quick_hubbard_u)

    def test_quick_aimd_importable_from_workgraph(self):
        from quantum_lego.core.workgraph import quick_aimd
        assert callable(quick_aimd)

    def test_get_batch_results_from_workgraph_importable(self):
        from quantum_lego.core.workgraph import get_batch_results_from_workgraph
        assert callable(get_batch_results_from_workgraph)


@pytest.mark.tier1
class TestDosWrappers:
    """Tests for DOS wrapper delegation behavior."""

    def test_quick_dos_sequential_delegates_to_quick_vasp_sequential(self, monkeypatch):
        from quantum_lego.core import dos_workflows
        from quantum_lego.core import vasp_workflows

        captured = {}

        def fake_quick_vasp_sequential(**kwargs):
            captured.update(kwargs)
            return {'__workgraph_pk__': 321, '__stage_names__': ['dos']}

        monkeypatch.setattr(vasp_workflows, 'quick_vasp_sequential', fake_quick_vasp_sequential)

        result = dos_workflows.quick_dos_sequential(
            structure='dummy-structure',
            stages=[{'name': 'dos', 'scf_incar': {'encut': 400}, 'dos_incar': {'nedos': 2000}}],
            code_label='dummy-code',
            options={'resources': {'num_machines': 1}},
        )

        assert result['__workgraph_pk__'] == 321
        assert captured['stages'][0]['type'] == 'dos'

    def test_quick_dos_wraps_single_dos_stage(self, monkeypatch):
        from quantum_lego.core import dos_workflows

        captured = {}

        def fake_quick_dos_sequential(**kwargs):
            captured.update(kwargs)
            return {'__workgraph_pk__': 999, '__stage_names__': ['dos']}

        monkeypatch.setattr(dos_workflows, 'quick_dos_sequential', fake_quick_dos_sequential)

        result = dos_workflows.quick_dos(
            structure='dummy-structure',
            code_label='dummy-code',
            scf_incar={'encut': 400},
            dos_incar={'nedos': 2000},
            options={'resources': {'num_machines': 1}},
        )

        assert result == {'__workgraph_pk__': 999}
        stage = captured['stages'][0]
        assert stage['type'] == 'dos'
        assert stage['name'] == 'dos'
        assert stage['structure'] == 'dummy-structure'
        assert stage['scf_incar']['lwave'] is True
        assert stage['scf_incar']['lcharg'] is True
