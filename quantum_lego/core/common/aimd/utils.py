"""Utility functions for AIMD module."""
from copy import deepcopy


def validate_stage_sequence(stages: list[dict]) -> None:
    """
    Validate AIMD stage sequence format.

    Args:
        stages: List of stage dicts, each must contain 'TEBEG' and 'NSW'

    Raises:
        ValueError: If stages empty or missing required keys
    """
    if not stages:
        raise ValueError("aimd_stages must contain at least one stage")

    for idx, stage in enumerate(stages):
        if 'TEBEG' not in stage:
            raise ValueError(
                f"Stage {idx} missing required key 'TEBEG'. "
                f"Each stage must contain {{'TEBEG': K, 'NSW': N}}"
            )
        if 'NSW' not in stage:
            raise ValueError(
                f"Stage {idx} missing required key 'NSW'. "
                f"Each stage must contain {{'TEBEG': K, 'NSW': N}}"
            )


def validate_supercell_spec(spec: list[int]) -> None:
    """
    Validate supercell specification.

    Args:
        spec: [nx, ny, nz] supercell dimensions

    Raises:
        ValueError: If spec not valid 3D integer list with positive values
    """
    if not isinstance(spec, list):
        raise ValueError(f"Supercell spec must be a list, got {type(spec).__name__}")

    if len(spec) != 3:
        raise ValueError(
            f"Supercell spec must be a 3-element list [nx, ny, nz], got {len(spec)} elements"
        )

    for idx, val in enumerate(spec):
        if not isinstance(val, int):
            raise ValueError(
                f"Supercell spec elements must be positive integers, "
                f"element {idx} is {type(val).__name__}"
            )
        if val <= 0:
            raise ValueError(
                f"Supercell spec elements must be positive integers, "
                f"element {idx} is {val}"
            )


def merge_builder_inputs(base: dict, override: dict) -> dict:
    """
    Deep merge override into base builder inputs.

    Nested dicts are recursively merged.
    Non-dict values in override replace base values.
    Returns new dict (base and override unchanged).

    Args:
        base: Base builder inputs
        override: Override builder inputs

    Returns:
        Merged builder inputs

    Example:
        base = {'parameters': {'incar': {'ENCUT': 400, 'PREC': 'Normal'}}}
        override = {'parameters': {'incar': {'ENCUT': 500}}}
        result = {'parameters': {'incar': {'ENCUT': 500, 'PREC': 'Normal'}}}
    """
    result = deepcopy(base)

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Both are dicts: recursively merge
            result[key] = merge_builder_inputs(result[key], value)
        else:
            # Override wins
            result[key] = deepcopy(value)

    return result


def organize_aimd_results(node) -> dict:
    """
    Organize AIMD workflow results into user-friendly format.

    Args:
        node: Completed WorkGraph node

    Returns:
        {
            'summary': {
                'total_structures': int,
                'total_stages': int,
                'successful': int,
                'failed': int,
            },
            'results': {
                structure_name: [
                    {
                        'stage': 0,
                        'temperature': float,
                        'steps': int,
                        'energy': float,
                        'structure_pk': int,
                        'trajectory_pk': int,
                    },
                    ...
                ]
            },
            'failed_calculations': [
                {'structure': str, 'stage': int, 'error': str},
            ],
        }
    """
    # TODO: Implementation in next task
    pass
