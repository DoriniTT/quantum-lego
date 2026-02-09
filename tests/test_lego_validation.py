"""Unit tests for _validate_stages() top-level orchestrator.

All tests are tier1 (pure Python, no AiiDA profile needed).
"""

import pytest


@pytest.mark.tier1
class TestValidateStages:
    """Tests for quantum_lego.core.workgraph._validate_stages()."""

    def _validate(self, stages):
        from quantum_lego.core.workgraph import _validate_stages
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

    def test_default_type_is_vasp(self):
        """Stage without 'type' should be validated as VASP (needs incar, restart)."""
        stages = [{'name': 'relax', 'incar': {'NSW': 100}, 'restart': None}]
        self._validate(stages)  # should not raise

    def test_single_valid_vasp_passes(self):
        stages = [{'name': 'relax', 'type': 'vasp', 'incar': {'NSW': 100}, 'restart': None}]
        self._validate(stages)

    def test_two_stage_sequence_passes(self):
        stages = [
            {'name': 'relax', 'incar': {'NSW': 100}, 'restart': None},
            {'name': 'scf', 'incar': {'NSW': 0}, 'restart': 'relax'},
        ]
        self._validate(stages)

    def test_mixed_types_passes(self):
        stages = [
            {'name': 'relax', 'type': 'vasp',
             'incar': {'NSW': 100, 'laechg': True, 'lcharg': True},
             'restart': None,
             'retrieve': ['AECCAR0', 'AECCAR2', 'CHGCAR']},
            {'name': 'dos_calc', 'type': 'dos', 'scf_incar': {'encut': 400},
             'dos_incar': {'nedos': 2000}, 'structure_from': 'relax'},
            {'name': 'fukui', 'type': 'batch', 'structure_from': 'relax',
             'base_incar': {'NSW': 0},
             'calculations': {'neutral': {'incar': {'NELECT': 100}}}},
            {'name': 'bader', 'type': 'bader', 'charge_from': 'relax'},
            {'name': 'conv', 'type': 'convergence'},
            {'name': 'gs', 'type': 'vasp',
             'incar': {'NSW': 0, 'lorbit': 11, 'lwave': True, 'lcharg': True},
             'restart': None, 'structure_from': 'relax',
             'retrieve': ['OUTCAR']},
            {'name': 'response', 'type': 'hubbard_response',
             'ground_state_from': 'gs', 'structure_from': 'input',
             'target_species': 'Ni'},
            {'name': 'analysis', 'type': 'hubbard_analysis',
             'response_from': 'response', 'structure_from': 'input',
             'target_species': 'Ni'},
        ]
        self._validate(stages)

    def test_convergence_stage_passes(self):
        stages = [
            {'name': 'conv', 'type': 'convergence',
             'conv_settings': {'cutoff_start': 300},
             'convergence_threshold': 0.001},
        ]
        self._validate(stages)

    def test_convergence_with_structure_from_passes(self):
        stages = [
            {'name': 'relax', 'type': 'vasp', 'incar': {'NSW': 100}, 'restart': None},
            {'name': 'conv', 'type': 'convergence', 'structure_from': 'relax'},
        ]
        self._validate(stages)

    def test_delegates_vasp_error(self):
        """Missing incar should trigger VASP-brick ValueError."""
        stages = [{'name': 'relax', 'type': 'vasp', 'restart': None}]
        with pytest.raises(ValueError, match="incar"):
            self._validate(stages)

    def test_delegates_dos_error(self):
        """Missing scf_incar should trigger DOS-brick ValueError."""
        stages = [
            {'name': 'relax', 'type': 'vasp', 'incar': {'NSW': 100}, 'restart': None},
            {'name': 'dos', 'type': 'dos', 'dos_incar': {'nedos': 2000},
             'structure_from': 'relax'},
        ]
        with pytest.raises(ValueError, match="scf_incar"):
            self._validate(stages)

    def test_delegates_batch_error(self):
        """Missing calculations should trigger batch-brick ValueError."""
        stages = [
            {'name': 'relax', 'type': 'vasp', 'incar': {'NSW': 100}, 'restart': None},
            {'name': 'fukui', 'type': 'batch', 'structure_from': 'relax',
             'base_incar': {'NSW': 0}},
        ]
        with pytest.raises(ValueError, match="calculations"):
            self._validate(stages)

    def test_delegates_bader_error(self):
        """Missing charge_from should trigger bader-brick ValueError."""
        stages = [
            {'name': 'relax', 'type': 'vasp', 'incar': {'NSW': 100}, 'restart': None},
            {'name': 'bader', 'type': 'bader'},
        ]
        with pytest.raises(ValueError, match="charge_from"):
            self._validate(stages)

    def test_delegates_convergence_error(self):
        """Invalid conv_settings type should trigger convergence-brick ValueError."""
        stages = [
            {'name': 'conv', 'type': 'convergence', 'conv_settings': 'bad'},
        ]
        with pytest.raises(ValueError, match="conv_settings"):
            self._validate(stages)

    def test_delegates_hubbard_response_error(self):
        """Missing target_species should trigger hubbard_response-brick ValueError."""
        stages = [
            {'name': 'gs', 'type': 'vasp', 'incar': {'NSW': 0}, 'restart': None},
            {'name': 'response', 'type': 'hubbard_response',
             'ground_state_from': 'gs', 'structure_from': 'input'},
        ]
        with pytest.raises(ValueError, match="target_species"):
            self._validate(stages)

    def test_delegates_hubbard_analysis_error(self):
        """Missing response_from should trigger hubbard_analysis-brick ValueError."""
        stages = [
            {'name': 'gs', 'type': 'vasp', 'incar': {'NSW': 0}, 'restart': None},
            {'name': 'analysis', 'type': 'hubbard_analysis',
             'structure_from': 'input', 'target_species': 'Ni'},
        ]
        with pytest.raises(ValueError, match="response_from"):
            self._validate(stages)
