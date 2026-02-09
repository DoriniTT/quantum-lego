"""Shared utility functions for WorkGraph builders.

This module contains helper functions used across all workflow types
(VASP, QE, DOS, specialized). These utilities handle common tasks like
converting ProcessBuilder objects, preparing builder inputs, waiting for
workflow completion, validating stage configurations, and building
output names.
"""

import typing as t
import time

from aiida import orm

from .utils import get_status
from .retrieve_defaults import build_vasp_retrieve


def _builder_to_dict(builder) -> dict:
    """
    Recursively convert a ProcessBuilder to a plain dict.

    ProcessBuilderNamespace objects need to be converted to regular dicts
    for use with WorkGraph add_task().

    Args:
        builder: ProcessBuilder or ProcessBuilderNamespace

    Returns:
        Plain dict with all nested namespaces converted
    """
    from aiida.engine.processes.builder import ProcessBuilderNamespace

    result = {}
    for key, value in builder.items():
        if isinstance(value, ProcessBuilderNamespace):
            # Recursively convert nested namespaces
            nested = _builder_to_dict(value)
            if nested:  # Only include non-empty namespaces
                result[key] = nested
        elif value is not None:
            result[key] = value
    return result


def _prepare_builder_inputs(
    incar: dict,
    kpoints_spacing: float,
    potential_family: str,
    potential_mapping: dict,
    options: dict,
    retrieve: t.List[str] = None,
    restart_folder=None,
    clean_workdir: bool = False,
    kpoints_mesh: t.List[int] = None,
    structure: orm.StructureData = None,
    fix_type: str = None,
    fix_thickness: float = 0.0,
    fix_elements: t.List[str] = None,
) -> dict:
    """
    Prepare builder inputs for VaspWorkChain.

    Args:
        incar: INCAR parameters dict
        kpoints_spacing: K-points spacing (used if kpoints_mesh not provided)
        potential_family: POTCAR family
        potential_mapping: Element to POTCAR mapping
        options: Scheduler options
        retrieve: Additional files to retrieve (merged with defaults)
        restart_folder: RemoteData for restart
        clean_workdir: Whether to clean work directory
        kpoints_mesh: Explicit k-points mesh [nx, ny, nz] (overrides kpoints_spacing)
        structure: StructureData (required for selective dynamics)
        fix_type: Where to fix atoms ('bottom', 'center', 'top', or None)
        fix_thickness: Thickness in Angstroms for fixing region
        fix_elements: Optional list of element symbols to fix

    Returns:
        Dict of prepared inputs for VaspWorkChain
    """
    from .common.fixed_atoms import get_fixed_atoms_list

    prepared = {}

    # Parameters (INCAR)
    prepared['parameters'] = orm.Dict(dict={'incar': incar})

    # K-points: explicit mesh or spacing
    if kpoints_mesh is not None:
        kpoints = orm.KpointsData()
        kpoints.set_kpoints_mesh(kpoints_mesh)
        prepared['kpoints'] = kpoints
    else:
        prepared['kpoints_spacing'] = float(kpoints_spacing)

    # Potentials
    prepared['potential_family'] = potential_family
    prepared['potential_mapping'] = orm.Dict(dict=potential_mapping)

    # Options
    prepared['options'] = orm.Dict(dict=options)

    # Clean workdir
    prepared['clean_workdir'] = clean_workdir

    # Settings (for file retrieval)
    # Note: aiida-vasp expects UPPERCASE keys for settings
    settings = {}
    retrieve_list = build_vasp_retrieve(retrieve)
    if retrieve_list:
        settings['ADDITIONAL_RETRIEVE_LIST'] = retrieve_list
    if settings:
        prepared['settings'] = orm.Dict(dict=settings)

    # Restart folder
    if restart_folder is not None:
        prepared['restart'] = {'folder': restart_folder}

    # Selective dynamics (fix atoms)
    if structure is not None and fix_type is not None and fix_thickness > 0.0:
        fixed_atoms_list = get_fixed_atoms_list(
            structure=structure,
            fix_type=fix_type,
            fix_thickness=fix_thickness,
            fix_elements=fix_elements,
        )

        if fixed_atoms_list:
            # Create positions_dof array: True = relax, False = fix
            num_atoms = len(structure.sites)
            positions_dof = []

            for i in range(1, num_atoms + 1):  # 1-based indexing
                if i in fixed_atoms_list:
                    positions_dof.append([False, False, False])  # Fix atom
                else:
                    positions_dof.append([True, True, True])  # Relax atom

            prepared['dynamics'] = orm.Dict(dict={'positions_dof': positions_dof})

    return prepared


def _wait_for_completion(pk: int, poll_interval: float) -> None:
    """
    Block until a WorkGraph completes.

    Args:
        pk: WorkGraph PK
        poll_interval: Seconds between status checks
    """
    print(f"Waiting for WorkGraph PK {pk} to complete...")

    while True:
        status = get_status(pk)

        if status in ('finished', 'failed', 'excepted', 'killed'):
            print(f"WorkGraph PK {pk} completed with status: {status}")
            break

        time.sleep(poll_interval)


def _validate_stages(stages: t.List[dict]) -> None:
    """
    Validate sequential stage configuration.

    Delegates type-specific validation to each brick module.

    Args:
        stages: List of stage configuration dicts

    Raises:
        ValueError: If validation fails
    """
    import warnings as _warnings
    from .bricks import get_brick_module, VALID_BRICK_TYPES, validate_connections

    if not stages:
        raise ValueError("stages list cannot be empty")

    stage_names = set()
    for i, stage in enumerate(stages):
        # Require name
        if 'name' not in stage:
            raise ValueError(f"Stage {i} missing required 'name' field")

        name = stage['name']
        if name in stage_names:
            raise ValueError(f"Duplicate stage name: '{name}'")
        stage_names.add(name)

        # Get stage type (default to 'vasp')
        stage_type = stage.get('type', 'vasp')
        if stage_type not in VALID_BRICK_TYPES:
            raise ValueError(
                f"Stage '{name}' type='{stage_type}' must be one of {VALID_BRICK_TYPES}"
            )

        # Delegate type-specific validation to brick module
        brick = get_brick_module(stage_type)
        brick.validate_stage(stage, stage_names)

    # Validate inter-stage connections using port declarations
    connection_warnings = validate_connections(stages)
    for w in connection_warnings:
        _warnings.warn(w, stacklevel=3)


def _build_indexed_output_name(index: int, name: str) -> str:
    """Build a stable indexed output name (e.g. ``s01_relax``)."""
    return f's{index:02d}_{name}'


def _build_combined_trajectory_output_name(stage_count: int) -> str:
    """Build indexed output name for the final combined trajectory."""
    return _build_indexed_output_name(stage_count + 1, 'combined_trajectory')


def get_batch_results_from_workgraph(batch_result: dict) -> t.Dict[str, dict]:
    """
    Extract results from a quick_vasp_batch result.

    Args:
        batch_result: Return value from quick_vasp_batch

    Returns:
        Dict mapping structure keys to result dicts
    """
    from .results import get_results

    wg_pk = batch_result['__workgraph_pk__']
    task_map = batch_result['__task_map__']

    wg_node = orm.load_node(wg_pk)

    results = {}
    for key, task_info in task_map.items():
        # Extract results for this key
        result = {
            'energy': None,
            'structure': None,
            'misc': None,
            'files': None,
            'pk': wg_pk,
            'key': key,
        }

        # Access task outputs
        vasp_task_name = task_info['vasp_task']
        energy_task_name = task_info['energy_task']

        if hasattr(wg_node, 'tasks'):
            # Live WorkGraph
            tasks = wg_node.tasks
            if vasp_task_name in tasks:
                vasp_task = tasks[vasp_task_name]
                if hasattr(vasp_task.outputs, 'misc'):
                    misc_val = vasp_task.outputs.misc.value
                    if hasattr(misc_val, 'get_dict'):
                        result['misc'] = misc_val.get_dict()
                if hasattr(vasp_task.outputs, 'structure'):
                    struct_val = vasp_task.outputs.structure.value
                    if struct_val is not None:
                        result['structure'] = struct_val
                if hasattr(vasp_task.outputs, 'retrieved'):
                    result['files'] = vasp_task.outputs.retrieved.value

            if energy_task_name in tasks:
                energy_task = tasks[energy_task_name]
                if hasattr(energy_task.outputs, 'result'):
                    energy_val = energy_task.outputs.result.value
                    if energy_val is not None:
                        result['energy'] = energy_val.value if hasattr(energy_val, 'value') else float(energy_val)

        # Extract energy from misc if not found
        if result['energy'] is None and result['misc'] is not None:
            from .results import _extract_energy_from_misc
            result['energy'] = _extract_energy_from_misc(result['misc'])

        results[key] = result

    return results
