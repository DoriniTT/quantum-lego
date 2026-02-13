"""Tier2 & tier3 integration tests for sequential lego pipelines.

Tier2: Tests WorkGraph construction for multi-stage pipelines (no VASP).
Tier3: Tests against pre-computed sequential workflow results.
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

@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestSequentialValidation:
    """Test sequential workflow validation logic."""

    def test_validate_stages_rejects_duplicate_names(self):
        """_validate_stages should reject stages with duplicate names."""
        from quantum_lego.core.workgraph import _validate_stages

        stages = [
            {
                'name': 'relax',
                'type': 'vasp',
                'incar': {'encut': 300, 'ibrion': 2, 'nsw': 10},
                'restart': None,
            },
            {
                'name': 'relax',
                'type': 'vasp',
                'incar': {'encut': 300, 'nsw': 0},
                'restart': None,
            },
        ]

        with pytest.raises(ValueError, match="[Dd]uplicate|[Ss]ame name"):
            _validate_stages(stages)

    def test_validate_stages_rejects_empty_stages(self):
        """_validate_stages should reject empty stages list."""
        from quantum_lego.core.workgraph import _validate_stages

        with pytest.raises(ValueError):
            _validate_stages([])

    def test_validate_stages_accepts_valid_pipeline(self):
        """_validate_stages should accept a valid two-stage pipeline."""
        from quantum_lego.core.workgraph import _validate_stages

        stages = [
            {
                'name': 'relax',
                'type': 'vasp',
                'incar': {'encut': 300, 'ibrion': 2, 'nsw': 10, 'isif': 3},
                'restart': None,
            },
            {
                'name': 'scf',
                'type': 'vasp',
                'incar': {'encut': 300, 'nsw': 0, 'ibrion': -1},
                'restart': None,
                'structure_from': 'relax',
            },
        ]

        # Should not raise
        _validate_stages(stages)


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestSequentialIndexing:
    """Test that sequential pipelines use correct output naming."""

    def test_indexed_output_naming(self):
        """Output namespaces should use s01_, s02_ prefix format."""
        from quantum_lego.core.workgraph import _build_indexed_output_name

        assert _build_indexed_output_name(1, 'relax') == 's01_relax'
        assert _build_indexed_output_name(2, 'scf') == 's02_scf'
        assert _build_indexed_output_name(10, 'dos') == 's10_dos'
        assert _build_indexed_output_name(99, 'final') == 's99_final'

    def test_indexed_output_naming_is_sortable(self):
        """Indexed output names should sort in definition order."""
        from quantum_lego.core.workgraph import _build_indexed_output_name

        names = [
            _build_indexed_output_name(i, f'stage{i}')
            for i in range(1, 6)
        ]

        sorted_names = sorted(names)
        assert names == sorted_names, "Indexed names should be naturally sortable"


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestSequentialImportsAndBasic:
    """Test that sequential workflow infrastructure can be imported."""

    def test_quick_vasp_sequential_importable(self):
        """quick_vasp_sequential should be importable."""
        from quantum_lego.core import quick_vasp_sequential
        assert quick_vasp_sequential is not None
        assert callable(quick_vasp_sequential)

    def test_quick_vasp_importable(self):
        """quick_vasp should be importable."""
        from quantum_lego.core import quick_vasp
        assert quick_vasp is not None
        assert callable(quick_vasp)

    def test_quick_dos_importable(self):
        """quick_dos should be importable."""
        from quantum_lego.core import quick_dos
        assert quick_dos is not None
        assert callable(quick_dos)

    def test_quick_dos_sequential_importable(self):
        """quick_dos_sequential should be importable."""
        from quantum_lego.core import quick_dos_sequential
        assert quick_dos_sequential is not None
        assert callable(quick_dos_sequential)

    def test_quick_vasp_batch_importable(self):
        """quick_vasp_batch should be importable."""
        from quantum_lego.core import quick_vasp_batch
        assert quick_vasp_batch is not None
        assert callable(quick_vasp_batch)

    def test_result_extraction_importable(self):
        """Result extraction functions should be importable."""
        from quantum_lego.core.results import (
            get_results, get_sequential_results, get_stage_results,
            print_sequential_results
        )
        assert get_results is not None
        assert get_sequential_results is not None
        assert get_stage_results is not None
        assert print_sequential_results is not None


# ============================================================================
# TIER 3 — Result extraction from pre-computed sequential pipelines
# ============================================================================

@pytest.mark.tier3
@pytest.mark.requires_aiida
class TestSequentialResultExtraction:
    """Validate result extraction from a completed sequential pipeline (Si relax→SCF)."""

    def test_get_sequential_results_returns_all_stages(self, reference_pks):
        """get_sequential_results should return results for all stages."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_sequential_results

        scenario = reference_pks['sequential']['relax_then_scf_si']
        seq_result = build_sequential_result(scenario)

        results = get_sequential_results(seq_result)
        assert isinstance(results, dict)
        assert len(results) == 2, f"Expected 2 stages (relax, scf), got {len(results)}"

        stage_names = list(results.keys())
        assert 'relax' in stage_names, f"'relax' stage missing, got {stage_names}"
        assert 'scf' in stage_names, f"'scf' stage missing, got {stage_names}"

    def test_relax_stage_has_energy_and_structure(self, reference_pks):
        """Relax stage should produce energy and output structure."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['sequential']['relax_then_scf_si']
        seq_result = build_sequential_result(scenario)

        result = get_stage_results(seq_result, 'relax')
        assert result['type'] == 'vasp'
        assert result['energy'] is not None, "Relax stage must have energy"
        assert result['energy'] < 0, f"Relax energy should be negative, got {result['energy']}"
        assert result['structure'] is not None, "Relax stage must produce output structure"
        assert 'Si' in result['structure'].get_formula()

    def test_scf_stage_has_energy_no_structure(self, reference_pks):
        """SCF stage should produce energy but no output structure (NSW=0)."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['sequential']['relax_then_scf_si']
        seq_result = build_sequential_result(scenario)

        result = get_stage_results(seq_result, 'scf')
        assert result['type'] == 'vasp'
        assert result['energy'] is not None, "SCF stage must have energy"
        assert result['energy'] < 0, f"SCF energy should be negative, got {result['energy']}"
        # NSW=0 → no output structure
        assert result['structure'] is None, "SCF (NSW=0) should not produce structure"

    def test_scf_energy_close_to_relax_energy(self, reference_pks):
        """SCF energy should be close to the relaxed energy (same structure)."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['sequential']['relax_then_scf_si']
        seq_result = build_sequential_result(scenario)

        relax_result = get_stage_results(seq_result, 'relax')
        scf_result = get_stage_results(seq_result, 'scf')

        e_relax = relax_result['energy']
        e_scf = scf_result['energy']

        # Energies should be similar (within ~0.1 eV for Si 2-atom cell)
        diff = abs(e_relax - e_scf)
        assert diff < 0.5, (
            f"Relax ({e_relax:.6f}) and SCF ({e_scf:.6f}) energies differ by "
            f"{diff:.6f} eV, expected < 0.5 eV"
        )

    def test_both_stages_have_misc(self, reference_pks):
        """Both stages should return misc dicts."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_sequential_results

        scenario = reference_pks['sequential']['relax_then_scf_si']
        seq_result = build_sequential_result(scenario)

        results = get_sequential_results(seq_result)
        for stage_name, stage_result in results.items():
            assert stage_result['misc'] is not None, (
                f"Stage '{stage_name}' should have misc dict"
            )
            assert isinstance(stage_result['misc'], dict)

    def test_both_stages_have_files(self, reference_pks):
        """Both stages should return retrieved files."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_sequential_results

        scenario = reference_pks['sequential']['relax_then_scf_si']
        seq_result = build_sequential_result(scenario)

        results = get_sequential_results(seq_result)
        for stage_name, stage_result in results.items():
            assert stage_result['files'] is not None, (
                f"Stage '{stage_name}' should have retrieved files"
            )

    def test_invalid_stage_name_raises(self, reference_pks):
        """get_stage_results should raise ValueError for unknown stage."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['sequential']['relax_then_scf_si']
        seq_result = build_sequential_result(scenario)

        with pytest.raises(ValueError, match="not found"):
            get_stage_results(seq_result, 'nonexistent_stage')
