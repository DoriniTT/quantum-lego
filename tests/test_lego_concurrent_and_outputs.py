"""Unit tests for max_concurrent_jobs parameter in quick_vasp_sequential.

All tests are tier1 (pure Python, no AiiDA profile needed).
"""

import inspect
import pytest


# ---------------------------------------------------------------------------
# TestMaxConcurrentJobsParameter
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestMaxConcurrentJobsParameter:
    """Tests that quick_vasp_sequential accepts max_concurrent_jobs."""

    def test_parameter_in_signature(self):
        from quantum_lego.core.workgraph import quick_vasp_sequential
        sig = inspect.signature(quick_vasp_sequential)
        assert 'max_concurrent_jobs' in sig.parameters

    def test_default_is_none(self):
        from quantum_lego.core.workgraph import quick_vasp_sequential
        sig = inspect.signature(quick_vasp_sequential)
        param = sig.parameters['max_concurrent_jobs']
        assert param.default is None

    def test_parameter_type_annotation(self):
        from quantum_lego.core.workgraph import quick_vasp_sequential
        sig = inspect.signature(quick_vasp_sequential)
        param = sig.parameters['max_concurrent_jobs']
        assert param.annotation is int


@pytest.mark.tier1
class TestIndexedOutputNaming:
    """Tests indexed output naming helpers used by lego sequential workflows."""

    def test_build_indexed_output_name(self):
        from quantum_lego.core.workgraph import _build_indexed_output_name
        assert _build_indexed_output_name(3, 'md_production_0') == 's03_md_production_0'

    def test_build_combined_trajectory_output_name(self):
        from quantum_lego.core.workgraph import _build_combined_trajectory_output_name
        assert _build_combined_trajectory_output_name(6) == 's07_combined_trajectory'
