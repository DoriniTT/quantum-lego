"""Brick registry and shared helpers for the lego module.

Each brick module exports a PORTS dict plus 5 functions:
    PORTS: dict with 'inputs' and 'outputs' port declarations (from connections.py)
    validate_stage(stage, stage_names) -> None
    create_stage_tasks(wg, stage, stage_name, context) -> dict
    expose_stage_outputs(wg, stage_name, stage_tasks_result) -> None
    get_stage_results(wg_node, wg_pk, stage_name) -> dict
    print_stage_results(index, stage_name, stage_result) -> None

Port declarations and validation logic live in connections.py (pure Python,
no AiiDA dependency) so they can be imported in tier1 tests.
"""

from . import (
    vasp,
    dos,
    batch,
    bader,
    convergence,
    thickness,
    hubbard_response,
    hubbard_analysis,
    aimd,
    qe,
    cp2k,
    generate_neb_images,
    neb,
)
from .connections import (  # noqa: F401
    PORT_TYPES,
    ALL_PORTS,
    validate_connections,
    _validate_port_types,
    _evaluate_conditional,
    get_brick_info,
)


BRICK_REGISTRY = {
    'vasp': vasp,
    'dos': dos,
    'batch': batch,
    'bader': bader,
    'convergence': convergence,
    'thickness': thickness,
    'hubbard_response': hubbard_response,
    'hubbard_analysis': hubbard_analysis,
    'aimd': aimd,
    'qe': qe,
    'cp2k': cp2k,
    'generate_neb_images': generate_neb_images,
    'neb': neb,
}

VALID_BRICK_TYPES = tuple(BRICK_REGISTRY.keys())


def get_brick_module(brick_type: str):
    """Look up a brick module by type string.

    Args:
        brick_type: One of the valid brick types (vasp, dos, batch,
            bader, convergence, thickness, hubbard_response, hubbard_analysis).

    Returns:
        The brick module.

    Raises:
        ValueError: If the brick type is unknown.
    """
    try:
        return BRICK_REGISTRY[brick_type]
    except KeyError:
        raise ValueError(
            f"Unknown brick type '{brick_type}'. "
            f"Must be one of {VALID_BRICK_TYPES}"
        )


def resolve_structure_from(structure_from: str, context: dict):
    """Resolve a structure socket from a previous stage.

    Only VASP, AIMD, QE, CP2K, and NEB stages produce a meaningful structure output.
    Referencing a non-VASP/AIMD/QE/CP2K stage (dos, batch, bader, convergence,
    thickness, hubbard_response, hubbard_analysis) raises an error
    because those bricks don't produce structures.

    Args:
        structure_from: Name of the stage to get structure from.
        context: The context dict passed to create_stage_tasks.

    Returns:
        Structure socket (StructureData or task output socket).

    Raises:
        ValueError: If the referenced stage doesn't produce a structure.
    """
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    ref_stage_type = stage_types.get(structure_from, 'vasp')
    if ref_stage_type in ('vasp', 'aimd'):
        return stage_tasks[structure_from]['vasp'].outputs.structure
    elif ref_stage_type == 'qe':
        return stage_tasks[structure_from]['qe'].outputs.output_structure
    elif ref_stage_type == 'cp2k':
        return stage_tasks[structure_from]['cp2k'].outputs.output_structure
    elif ref_stage_type == 'neb':
        return stage_tasks[structure_from]['neb'].outputs.structure
    else:
        # Non-structure-producing bricks
        raise ValueError(
            f"structure_from='{structure_from}' references a '{ref_stage_type}' "
            f"stage, which doesn't produce a structure output. "
            f"Point to a VASP, AIMD, QE, CP2K, or NEB stage instead."
        )


def resolve_energy_from(energy_from: str, context: dict):
    """Resolve an energy socket from a previous stage.

    Only VASP and AIMD stages produce a meaningful energy output.
    Referencing a non-VASP/AIMD stage raises an error.

    Args:
        energy_from: Name of the stage to get energy from.
        context: The context dict passed to create_stage_tasks.

    Returns:
        Energy socket (Float or task output socket).

    Raises:
        ValueError: If the referenced stage doesn't produce an energy.
    """
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    ref_stage_type = stage_types.get(energy_from, 'vasp')
    if ref_stage_type in ('vasp', 'aimd', 'cp2k'):
        return stage_tasks[energy_from]['energy'].outputs.result
    else:
        raise ValueError(
            f"energy_from='{energy_from}' references a '{ref_stage_type}' "
            f"stage, which doesn't produce an energy output. "
            f"Point to a VASP, AIMD, or CP2K stage instead."
        )
