"""Tests for AIMD utils."""
import pytest
from quantum_lego.core.common.aimd.utils import validate_stage_sequence, validate_supercell_spec, merge_builder_inputs


def test_validate_stage_sequence_valid():
    """Valid stage sequence passes."""
    stages = [
        {'TEBEG': 300, 'NSW': 100},
        {'TEBEG': 500, 'NSW': 200},
    ]
    validate_stage_sequence(stages)  # Should not raise


def test_validate_stage_sequence_missing_tebeg():
    """Stage missing TEBEG raises ValueError."""
    stages = [{'NSW': 100}]
    with pytest.raises(ValueError, match="missing required key 'TEBEG'"):
        validate_stage_sequence(stages)


def test_validate_stage_sequence_missing_nsw():
    """Stage missing NSW raises ValueError."""
    stages = [{'TEBEG': 300}]
    with pytest.raises(ValueError, match="missing required key 'NSW'"):
        validate_stage_sequence(stages)


def test_validate_stage_sequence_empty():
    """Empty stage list raises ValueError."""
    with pytest.raises(ValueError, match="at least one stage"):
        validate_stage_sequence([])


def test_validate_supercell_spec_valid():
    """Valid supercell spec passes."""
    validate_supercell_spec([2, 2, 1])  # Should not raise


def test_validate_supercell_spec_not_list():
    """Non-list spec raises ValueError."""
    with pytest.raises(ValueError, match="must be a list"):
        validate_supercell_spec((2, 2, 1))


def test_validate_supercell_spec_wrong_length():
    """Wrong length raises ValueError."""
    with pytest.raises(ValueError, match="must be a 3-element list"):
        validate_supercell_spec([2, 2])


def test_validate_supercell_spec_non_integer():
    """Non-integer element raises ValueError."""
    with pytest.raises(ValueError, match="must be positive integers"):
        validate_supercell_spec([2, 2.5, 1])


def test_validate_supercell_spec_non_positive():
    """Non-positive integer raises ValueError."""
    with pytest.raises(ValueError, match="must be positive integers"):
        validate_supercell_spec([2, 0, 1])


def test_merge_builder_inputs_simple():
    """Simple merge replaces values."""
    base = {'a': 1, 'b': 2}
    override = {'b': 3}
    result = merge_builder_inputs(base, override)
    assert result == {'a': 1, 'b': 3}
    # Check immutability
    assert base == {'a': 1, 'b': 2}


def test_merge_builder_inputs_nested():
    """Nested dicts are recursively merged."""
    base = {
        'parameters': {
            'incar': {
                'ENCUT': 400,
                'PREC': 'Normal',
            }
        }
    }
    override = {
        'parameters': {
            'incar': {
                'ENCUT': 500,
            }
        }
    }
    result = merge_builder_inputs(base, override)
    assert result == {
        'parameters': {
            'incar': {
                'ENCUT': 500,
                'PREC': 'Normal',
            }
        }
    }


def test_merge_builder_inputs_add_new_keys():
    """Override can add new keys."""
    base = {'a': 1}
    override = {'b': 2}
    result = merge_builder_inputs(base, override)
    assert result == {'a': 1, 'b': 2}


def test_merge_builder_inputs_replace_dict_with_value():
    """Override can replace dict with non-dict value."""
    base = {'options': {'resources': {'num_machines': 1}}}
    override = {'options': 'replace'}
    result = merge_builder_inputs(base, override)
    assert result == {'options': 'replace'}
