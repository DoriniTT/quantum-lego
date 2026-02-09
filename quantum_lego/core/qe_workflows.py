"""Quantum ESPRESSO workflow builders for the lego module.

This module provides QE-specific workflow functions for single and
sequential calculations using PwBaseWorkChain from aiida-quantumespresso.
"""

import typing as t

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task

from .workflow_utils import (
    _validate_stages,
    _wait_for_completion,
)


def quick_qe(
    structure: t.Union[orm.StructureData, int] = None,
    code_label: str = None,
    parameters: dict = None,
    kpoints_spacing: float = 0.03,
    kpoints: t.List[int] = None,
    pseudo_family: str = None,
    options: dict = None,
    restart_from: int = None,
    name: str = 'quick_qe',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> int:
    """
    Submit a single Quantum ESPRESSO calculation with minimal boilerplate.

    This wraps PwBaseWorkChain from aiida-quantumespresso for SCF, relax,
    and vc-relax calculations.

    Args:
        structure: StructureData or PK. Required.
        code_label: QE pw.x code label (e.g., 'pw@localhost')
        parameters: QE namelists dict (CONTROL, SYSTEM, ELECTRONS, etc.)
                   Example: {'CONTROL': {'calculation': 'scf'},
                            'SYSTEM': {'ecutwfc': 50, 'ecutrho': 400},
                            'ELECTRONS': {'conv_thr': 1e-8}}
        kpoints_spacing: K-points spacing in A^-1 (default: 0.03)
        kpoints: Explicit k-points mesh [nx, ny, nz] (overrides kpoints_spacing)
        pseudo_family: Pseudopotential family name (required, no default)
        options: Scheduler options dict with 'resources' key
        restart_from: PK of previous QE WorkGraph to restart from
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean the work directory after completion

    Returns:
        PK of the submitted WorkGraph

    Example:
        >>> pk = quick_qe(
        ...     structure=si_structure,
        ...     code_label='pw@localhost',
        ...     parameters={
        ...         'CONTROL': {'calculation': 'relax'},
        ...         'SYSTEM': {'ecutwfc': 50, 'ecutrho': 400},
        ...         'ELECTRONS': {'conv_thr': 1e-8},
        ...         'IONS': {},
        ...     },
        ...     kpoints_spacing=0.03,
        ...     pseudo_family='SSSP/1.3/PBE/efficiency',
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 4}},
        ...     name='si_relax',
        ... )
    """
    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if code_label is None:
        raise ValueError("code_label is required")
    if parameters is None:
        raise ValueError("parameters is required - specify QE namelists (CONTROL, SYSTEM, etc.)")
    if pseudo_family is None:
        raise ValueError("pseudo_family is required - specify pseudopotential family name")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Load structure if PK
    if isinstance(structure, int):
        structure = orm.load_node(structure)

    # Load code
    code = orm.load_code(code_label)

    # Load pseudo family and get pseudos
    pseudo_family_group = orm.load_group(pseudo_family)
    if not hasattr(pseudo_family_group, 'get_pseudos'):
        raise ValueError(f"Group '{pseudo_family}' is not a PseudoPotentialFamily")
    pseudos = pseudo_family_group.get_pseudos(structure=structure)

    # Get PwBaseWorkChain and wrap as task
    PwBaseWorkChain = WorkflowFactory('quantumespresso.pw.base')
    QeTask = task(PwBaseWorkChain)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    # Build k-points argument
    if kpoints is not None:
        kpoints_data = orm.KpointsData()
        kpoints_data.set_kpoints_mesh(kpoints)
        kpoints_arg = {'pw__kpoints': kpoints_data}
    else:
        kpoints_arg = {'kpoints_distance': orm.Float(kpoints_spacing)}

    # Handle restart
    restart_arg = {}
    if restart_from is not None:
        restart_node = orm.load_node(restart_from)
        # Navigate to remote_folder output
        if hasattr(restart_node, 'outputs'):
            # Try to get remote folder from the QE task output
            from aiida.common.links import LinkType
            for link in restart_node.base.links.get_outgoing(link_type=LinkType.RETURN).all():
                if 'remote' in link.link_label.lower():
                    restart_arg = {'pw__parent_folder': link.node}
                    break

    # Build task inputs
    qe_kwargs = {
        'pw__structure': structure,
        'pw__code': code,
        'pw__parameters': orm.Dict(dict=parameters),
        'pw__pseudos': pseudos,
        'pw__metadata': {'options': options},
        **kpoints_arg,
        **restart_arg,
        'clean_workdir': orm.Bool(clean_workdir),
    }

    # Add QE task
    qe_task = wg.add_task(QeTask, name='qe_calc', **qe_kwargs)

    # Add energy extraction task
    from .tasks import extract_qe_energy
    energy_task = wg.add_task(
        extract_qe_energy,
        name='extract_energy',
        output_parameters=qe_task.outputs.output_parameters,
    )

    # Set WorkGraph outputs
    wg.outputs.energy = energy_task.outputs.result
    wg.outputs.structure = qe_task.outputs.output_structure
    wg.outputs.output_parameters = qe_task.outputs.output_parameters
    wg.outputs.remote = qe_task.outputs.remote_folder
    wg.outputs.retrieved = qe_task.outputs.retrieved

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    return wg.pk


def quick_qe_sequential(
    structure: t.Union[orm.StructureData, int] = None,
    stages: t.List[dict] = None,
    code_label: str = None,
    kpoints_spacing: float = 0.03,
    pseudo_family: str = None,
    options: dict = None,
    max_concurrent_jobs: int = None,
    name: str = 'quick_qe_sequential',
    wait: bool = False,
    poll_interval: float = 10.0,
    clean_workdir: bool = False,
) -> dict:
    """
    Submit a multi-stage sequential QE calculation with automatic restart chaining.

    Each stage runs after the previous one completes, automatically using the
    previous stage's output structure and remote_folder for restart.

    Args:
        structure: Initial StructureData or PK
        stages: List of stage configuration dicts (see Stage Configuration below)
        code_label: QE pw.x code label (e.g., 'pw@localhost')
        kpoints_spacing: Default k-points spacing in A^-1 (default: 0.03)
        pseudo_family: Pseudopotential family name (required, no default)
        options: Scheduler options dict with 'resources' key
        max_concurrent_jobs: Maximum number of jobs running simultaneously
        name: WorkGraph name for identification
        wait: If True, block until calculation finishes (default: False)
        poll_interval: Seconds between status checks when wait=True
        clean_workdir: Whether to clean work directories after completion

    Returns:
        Dict with:
            - __workgraph_pk__: WorkGraph PK
            - __stage_names__: List of stage names in order
            - __stage_types__: Dict mapping stage names to types
            - __stage_namespaces__: Dict mapping stage names to namespace_map dicts
            - <stage_name>: WorkGraph PK (for each stage)

    Stage Configuration (type='qe'):
        - name (required): Unique stage identifier
        - type: 'qe' (required for QE stages)
        - parameters (required): QE namelists dict (CONTROL, SYSTEM, ELECTRONS, etc.)
        - restart (required): None or stage name to restart from
        - structure_from: 'previous' (default), 'input', or specific stage name
        - kpoints_spacing: Override k-points spacing for this stage
        - kpoints: Explicit k-points mesh [nx, ny, nz] (overrides kpoints_spacing)
        - pseudo_family: Override pseudo family for this stage
        - code_label: Override code label for this stage

    Example:
        >>> stages = [
        ...     {
        ...         'name': 'relax',
        ...         'type': 'qe',
        ...         'parameters': {
        ...             'CONTROL': {'calculation': 'relax'},
        ...             'SYSTEM': {'ecutwfc': 50, 'ecutrho': 400},
        ...             'ELECTRONS': {'conv_thr': 1e-8},
        ...             'IONS': {},
        ...         },
        ...         'restart': None,
        ...     },
        ...     {
        ...         'name': 'scf',
        ...         'type': 'qe',
        ...         'parameters': {
        ...             'CONTROL': {'calculation': 'scf'},
        ...             'SYSTEM': {'ecutwfc': 60, 'ecutrho': 480},
        ...             'ELECTRONS': {'conv_thr': 1e-10},
        ...         },
        ...         'restart': 'relax',
        ...         'kpoints_spacing': 0.02,
        ...     },
        ... ]
        >>>
        >>> result = quick_qe_sequential(
        ...     structure=si_structure,
        ...     stages=stages,
        ...     code_label='pw@localhost',
        ...     pseudo_family='SSSP/1.3/PBE/efficiency',
        ...     options={'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 4}},
        ... )
    """
    # Validate required inputs
    if structure is None:
        raise ValueError("structure is required")
    if stages is None:
        raise ValueError("stages is required - provide list of stage configurations")
    if code_label is None:
        raise ValueError("code_label is required")
    if pseudo_family is None:
        raise ValueError("pseudo_family is required - specify pseudopotential family name")
    if options is None:
        raise ValueError("options is required - specify scheduler resources")

    # Validate that all stages are QE type
    for i, stage in enumerate(stages):
        stage_type = stage.get('type', 'qe')
        if stage_type != 'qe':
            raise ValueError(
                f"quick_qe_sequential only supports 'qe' stages, but stage {i} "
                f"has type='{stage_type}'. Use quick_vasp_sequential for mixed pipelines."
            )
        # Ensure type is set for validation
        stage['type'] = 'qe'

    # Validate stages
    _validate_stages(stages)

    # Load structure if PK
    if isinstance(structure, int):
        structure = orm.load_node(structure)

    # Load code
    code = orm.load_code(code_label)

    # Build WorkGraph
    wg = WorkGraph(name=name)

    if max_concurrent_jobs is not None:
        wg.max_number_jobs = max_concurrent_jobs

    # Track structures and remote folders across stages
    stage_tasks = {}  # name -> task result dict
    stage_names = []  # Ordered list
    stage_types = {}  # name -> 'qe'
    stage_namespaces = {}  # name -> namespace_map

    for i, stage in enumerate(stages):
        stage_name = stage['name']
        stage_type = 'qe'
        stage_names.append(stage_name)
        stage_types[stage_name] = stage_type

        # Build context for brick modules
        context = {
            'wg': wg,
            'code': code,
            'pseudo_family': pseudo_family,
            'options': options,
            'base_kpoints_spacing': kpoints_spacing,
            'clean_workdir': clean_workdir,
            'stage_tasks': stage_tasks,
            'stage_types': stage_types,
            'stage_names': stage_names,
            'stages': stages,
            'input_structure': structure,
            'stage_index': i,
            'max_concurrent_jobs': max_concurrent_jobs,
        }

        # Delegate to QE brick module
        from .bricks import get_brick_module
        brick = get_brick_module('qe')
        tasks_result = brick.create_stage_tasks(wg, stage, stage_name, context)
        stage_tasks[stage_name] = tasks_result

        # Build namespace_map with index prefix for ordered display
        indexed_name = f's{i + 1:02d}_{stage_name}'
        namespace_map = {'main': indexed_name}

        stage_namespaces[stage_name] = namespace_map
        brick.expose_stage_outputs(wg, stage_name, tasks_result, namespace_map)

    # Submit
    wg.submit()

    # Wait if requested
    if wait:
        _wait_for_completion(wg.pk, poll_interval)

    # Return result dict
    return {
        '__workgraph_pk__': wg.pk,
        '__stage_names__': stage_names,
        '__stage_types__': stage_types,
        '__stage_namespaces__': stage_namespaces,
        **{name: wg.pk for name in stage_names},
    }
