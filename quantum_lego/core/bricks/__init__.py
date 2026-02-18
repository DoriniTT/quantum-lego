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
    dimer,
    dos,
    hybrid_bands,
    batch,
    fukui_analysis,
    birch_murnaghan,
    birch_murnaghan_refine,
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
    surface_enumeration,
    surface_terminations,
    dynamic_batch,
    formation_enthalpy,
    o2_reference_energy,
    surface_gibbs_energy,
    select_stable_surface,
    fukui_dynamic,
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
    'dimer': dimer,
    'dos': dos,
    'hybrid_bands': hybrid_bands,
    'batch': batch,
    'fukui_analysis': fukui_analysis,
    'birch_murnaghan': birch_murnaghan,
    'birch_murnaghan_refine': birch_murnaghan_refine,
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
    'surface_enumeration': surface_enumeration,
    'surface_terminations': surface_terminations,
    'dynamic_batch': dynamic_batch,
    'formation_enthalpy': formation_enthalpy,
    'o2_reference_energy': o2_reference_energy,
    'surface_gibbs_energy': surface_gibbs_energy,
    'select_stable_surface': select_stable_surface,
    'fukui_dynamic': fukui_dynamic,
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

    Only VASP, DIMER, AIMD, QE, CP2K, NEB, o2_reference_energy,
    birch_murnaghan, birch_murnaghan_refine, and select_stable_surface stages
    produce a meaningful structure output.  Referencing a non-structure-producing
    stage (dos, batch, bader, convergence, thickness, hubbard_response,
    hubbard_analysis, fukui_dynamic) raises an error.

    Use ``structure_from='input'`` to reference the original input structure
    passed to ``quick_vasp_sequential``. This is useful when the previous stage
    is a static calculation (nsw=0) that does not emit a structure output.

    Args:
        structure_from: Name of the stage to get structure from, or ``'input'``
            to use the original input structure.
        context: The context dict passed to create_stage_tasks.

    Returns:
        Structure socket (StructureData or task output socket).

    Raises:
        ValueError: If the referenced stage doesn't produce a structure.
    """
    # Special keyword: use the original input structure
    if structure_from == 'input':
        return context['input_structure']

    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    ref_stage_type = stage_types.get(structure_from, 'vasp')
    if ref_stage_type == 'vasp' or ref_stage_type == 'aimd':
        return stage_tasks[structure_from]['vasp'].outputs.structure
    elif ref_stage_type == 'dimer':
        # Use the CONTCAR-derived structure (dimer axis lines stripped) so that
        # subsequent stages (e.g. vib_verify) receive a clean StructureData.
        return stage_tasks[structure_from]['contcar_structure'].outputs.result
    elif ref_stage_type == 'qe':
        return stage_tasks[structure_from]['qe'].outputs.output_structure
    elif ref_stage_type == 'cp2k':
        return stage_tasks[structure_from]['cp2k'].outputs.output_structure
    elif ref_stage_type == 'neb':
        return stage_tasks[structure_from]['neb'].outputs.structure
    elif ref_stage_type == 'o2_reference_energy':
        # o2_reference_energy exposes a dummy O2 StructureData via a calcfunction
        return stage_tasks[structure_from]['structure'].outputs.result
    elif ref_stage_type in ('birch_murnaghan', 'birch_murnaghan_refine'):
        # Both BM bricks expose their volume-optimised structure via the
        # 'recommend' task (build_recommended_structure calcfunction).
        return stage_tasks[structure_from]['recommend'].outputs.result
    elif ref_stage_type == 'select_stable_surface':
        # run_select_stable_surface @task.graph returns the selected StructureData
        # via its single .outputs.result socket.
        return stage_tasks[structure_from]['graph'].outputs.result
    else:
        # Non-structure-producing bricks
        raise ValueError(
            f"structure_from='{structure_from}' references a '{ref_stage_type}' "
            f"stage, which doesn't produce a structure output. "
            f"Point to a VASP, AIMD, QE, CP2K, NEB, birch_murnaghan, or "
            f"select_stable_surface stage instead."
        )


def resolve_energy_from(energy_from: str, context: dict):
    """Resolve an energy socket from a previous stage.

    Only VASP, DIMER, AIMD, QE, CP2K, and o2_reference_energy stages produce
    a connectable energy output (exposed via an energy calcfunction task).
    DOS and hybrid_bands stages have energy accessible via get_stage_results()
    but do not expose it as a connectable WorkGraph port.
    Referencing an unsupported stage raises an error.

    Args:
        energy_from: Name of the stage to get energy from.
        context: The context dict passed to create_stage_tasks.

    Returns:
        Energy socket (Float or task output socket).

    Raises:
        ValueError: If the referenced stage doesn't produce a connectable energy.
    """
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']

    ref_stage_type = stage_types.get(energy_from, 'vasp')
    if ref_stage_type in ('vasp', 'dimer', 'aimd', 'cp2k', 'qe', 'o2_reference_energy'):
        return stage_tasks[energy_from]['energy'].outputs.result
    else:
        raise ValueError(
            f"energy_from='{energy_from}' references a '{ref_stage_type}' "
            f"stage, which doesn't produce a connectable energy output. "
            f"Point to a VASP, AIMD, QE, or CP2K stage instead."
        )
