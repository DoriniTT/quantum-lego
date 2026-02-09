"""CP2K brick for lego module.

Wraps Cp2kBaseWorkChain from aiida-cp2k plugin.
Supports ENERGY, GEO_OPT, CELL_OPT, and MD calculations with restart chaining.
"""

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory

from .connections import CP2K_PORTS as PORTS  # noqa: F401


# ---------------------------------------------------------------------------
# validate_stage
# ---------------------------------------------------------------------------

def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate CP2K stage configuration before submission.

    Args:
        stage: Stage configuration dict
        stage_names: Set of all stage names seen so far (for dependency checking)

    Raises:
        ValueError: If stage configuration is invalid
    """
    stage_name = stage.get('name', 'cp2k_stage')

    # Required: parameters (CP2K nested dict with GLOBAL, FORCE_EVAL, etc.)
    if 'parameters' not in stage:
        raise ValueError(f"CP2K stage '{stage_name}' must have 'parameters' field "
                         f"(nested dict with GLOBAL, FORCE_EVAL, etc.)")

    # Required: restart (None or previous stage name)
    if 'restart' not in stage:
        raise ValueError(f"CP2K stage '{stage_name}' must have 'restart' field "
                         f"(None or previous stage name)")

    restart = stage['restart']
    if restart is not None and restart not in stage_names:
        raise ValueError(f"CP2K stage '{stage_name}' restart='{restart}' refers to "
                         f"unknown stage. Must be None or one of: {sorted(stage_names)}")

    # Required: file dict OR basis_file + pseudo_file
    has_file_dict = 'file' in stage
    has_basis = 'basis_file' in stage
    has_pseudo = 'pseudo_file' in stage

    if not has_file_dict and not (has_basis and has_pseudo):
        raise ValueError(f"CP2K stage '{stage_name}' must have either 'file' dict "
                         f"(with 'basis' and 'pseudo' keys) or both 'basis_file' and "
                         f"'pseudo_file' fields")

    if has_file_dict:
        file_dict = stage['file']
        if not isinstance(file_dict, dict):
            raise ValueError(f"CP2K stage '{stage_name}' 'file' must be a dict, "
                             f"got {type(file_dict).__name__}")
        if 'basis' not in file_dict or 'pseudo' not in file_dict:
            raise ValueError(f"CP2K stage '{stage_name}' 'file' dict must have "
                             f"'basis' and 'pseudo' keys")

    # Optional: structure_from ('previous', 'input', or previous stage name)
    structure_from = stage.get('structure_from')
    if structure_from is not None:
        if structure_from not in ('previous', 'input') and structure_from not in stage_names:
            raise ValueError(f"CP2K stage '{stage_name}' structure_from='{structure_from}' "
                             f"must be 'previous', 'input', or a previous stage name: "
                             f"{sorted(stage_names)}")

    # Optional: fix_type requires fix_thickness > 0
    fix_type = stage.get('fix_type')
    if fix_type is not None:
        valid_fix_types = ('bottom', 'center', 'top')
        if fix_type not in valid_fix_types:
            raise ValueError(f"CP2K stage '{stage_name}' fix_type='{fix_type}' must be "
                             f"one of {valid_fix_types}")
        fix_thickness = stage.get('fix_thickness', 0.0)
        if fix_thickness <= 0.0:
            raise ValueError(f"CP2K stage '{stage_name}' has fix_type='{fix_type}' but "
                             f"fix_thickness={fix_thickness}. fix_thickness must be > 0 "
                             f"when fix_type is set.")

    # Optional: supercell must be [nx, ny, nz] with positive integers
    if 'supercell' in stage:
        spec = stage['supercell']
        if not isinstance(spec, (list, tuple)) or len(spec) != 3:
            raise ValueError(f"CP2K stage '{stage_name}' supercell must be [nx, ny, nz], "
                             f"got: {spec}")
        for val in spec:
            if not isinstance(val, int) or val < 1:
                raise ValueError(f"CP2K stage '{stage_name}' supercell values must be "
                                 f"positive integers, got: {spec}")


# ---------------------------------------------------------------------------
# create_stage_tasks
# ---------------------------------------------------------------------------

def create_stage_tasks(wg, stage: dict, stage_name: str, context: dict) -> dict:
    """Create WorkGraph tasks for CP2K calculation.

    Args:
        wg: WorkGraph instance
        stage: Stage configuration dict
        stage_name: Unique stage name
        context: Shared context with code, options, stage_tasks, etc.

    Returns:
        Dict with 'cp2k', 'energy', 'input_structure' keys pointing to task objects
    """
    from aiida_workgraph import task
    from ..tasks import extract_cp2k_energy, compute_cp2k_dynamics
    from . import resolve_structure_from

    # Resolve structure for this stage
    stage_index = context.get('stage_index', 0)
    input_structure = context['input_structure']
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']
    stage_names = context['stage_names']

    if 'structure_from' not in stage or stage.get('structure_from') == 'previous':
        # Auto mode: use input structure for first stage, resolve from previous otherwise
        if stage_index == 0:
            stage_structure = input_structure
        else:
            prev_name = stage_names[stage_index - 1]
            prev_stage_type = stage_types.get(prev_name, 'vasp')
            if prev_stage_type in ('vasp', 'aimd'):
                stage_structure = stage_tasks[prev_name]['vasp'].outputs.structure
            elif prev_stage_type == 'neb':
                stage_structure = stage_tasks[prev_name]['neb'].outputs.structure
            elif prev_stage_type == 'qe':
                stage_structure = stage_tasks[prev_name]['qe'].outputs.output_structure
            elif prev_stage_type == 'cp2k':
                stage_structure = stage_tasks[prev_name]['cp2k'].outputs.output_structure
            else:
                raise ValueError(
                    f"Stage '{stage['name']}' uses structure_from='previous' (auto) "
                    f"but previous stage '{prev_name}' is a '{prev_stage_type}' "
                    f"stage that doesn't produce a structure. Use an explicit "
                    f"'structure_from' pointing to a VASP, AIMD, NEB, QE, or CP2K stage."
                )
    elif stage.get('structure_from') == 'input':
        stage_structure = input_structure
    else:
        structure_from = stage.get('structure_from')
        # Check if it's a cp2k stage
        ref_stage_type = stage_types.get(structure_from, 'vasp')
        if ref_stage_type == 'cp2k':
            stage_structure = stage_tasks[structure_from]['cp2k'].outputs.output_structure
        else:
            stage_structure = resolve_structure_from(structure_from, context)

    # Handle supercell transformation
    supercell_task = None
    if 'supercell' in stage:
        from quantum_lego.core.common.aimd.tasks import create_supercell
        supercell_spec = stage['supercell']
        supercell_task = wg.add_task(
            create_supercell,
            name=f'supercell_{stage_name}',
            structure=stage_structure,
            spec=orm.List(list=supercell_spec),
        )
        stage_structure = supercell_task.outputs.result

    # Get CP2K code
    if 'code_label' in stage:
        code_label = stage['code_label']
        code = orm.load_code(code_label)
    else:
        code = context['code']

    # Get parameters
    parameters = stage['parameters']

    # Get options
    if 'options' in stage:
        options = stage['options']
    else:
        options = context['options']

    # Get file inputs (basis and pseudo)
    if 'file' in stage:
        file_dict = stage['file']
        basis_file = file_dict['basis']
        pseudo_file = file_dict['pseudo']
    else:
        basis_file = stage['basis_file']
        pseudo_file = stage['pseudo_file']

    # Convert path strings to SinglefileData if needed
    from aiida.orm import SinglefileData
    if isinstance(basis_file, str):
        basis_file = SinglefileData(file=basis_file)
    if isinstance(pseudo_file, str):
        pseudo_file = SinglefileData(file=pseudo_file)

    file_input = {
        'basis': basis_file,
        'pseudo': pseudo_file,
    }

    # Get restart folder if requested
    restart_from = stage.get('restart')
    restart_arg = {}
    if restart_from is not None:
        # Get remote_folder from previous CP2K stage
        prev_tasks = context['stage_tasks'][restart_from]
        if 'cp2k' in prev_tasks:
            restart_arg['parent_calc_folder'] = prev_tasks['cp2k'].outputs.remote_folder
        else:
            raise ValueError(f"Stage '{restart_from}' does not have CP2K outputs for restart")

    # Get clean_workdir and max_iterations
    clean_workdir = context.get('clean_workdir', False)
    max_iterations = stage.get('max_iterations', 3)

    # Handle fixed atoms
    fix_type = stage.get('fix_type')
    dynamics_task = None
    is_structure_socket = not isinstance(stage_structure, orm.StructureData)

    if fix_type is not None:
        fix_thickness = stage.get('fix_thickness', 0.0)
        fix_elements = stage.get('fix_elements', None)
        fix_components = stage.get('fix_components', 'XYZ')

        if is_structure_socket:
            # Structure not known at build time — compute at runtime
            dynamics_task = wg.add_task(
                compute_cp2k_dynamics,
                name=f'dynamics_{stage_name}',
                structure=stage_structure,
                fix_type=orm.Str(fix_type),
                fix_thickness=orm.Float(fix_thickness),
                fix_elements=orm.List(list=fix_elements) if fix_elements else None,
                fix_components=orm.Str(fix_components),
            )
        else:
            # Structure known at build time — compute fixed atoms now
            from quantum_lego.core.common.fixed_atoms import get_fixed_atoms_list
            fixed_atoms_list = get_fixed_atoms_list(
                structure=stage_structure,
                fix_type=fix_type,
                fix_thickness=fix_thickness,
                fix_elements=fix_elements,
            )
            if fixed_atoms_list:
                # Merge FIXED_ATOMS into parameters
                if 'MOTION' not in parameters:
                    parameters['MOTION'] = {}
                if 'CONSTRAINT' not in parameters['MOTION']:
                    parameters['MOTION']['CONSTRAINT'] = {}
                parameters['MOTION']['CONSTRAINT']['FIXED_ATOMS'] = {
                    'LIST': ' '.join(map(str, fixed_atoms_list)),
                    'COMPONENTS_TO_FIX': fix_components,
                }

    # Additional retrieve list
    retrieve_list = stage.get('retrieve', [])
    settings = {}
    if retrieve_list:
        settings['additional_retrieve_list'] = retrieve_list

    # Create Cp2kBaseWorkChain task
    Cp2kBaseWorkChain = WorkflowFactory('cp2k.base')
    Cp2kTask = task(Cp2kBaseWorkChain)

    cp2k_kwargs = {
        'cp2k__structure': stage_structure,
        'cp2k__code': code,
        'cp2k__parameters': orm.Dict(dict=parameters),
        'cp2k__file': file_input,
        'cp2k__metadata': {'options': options},
        'max_iterations': orm.Int(max_iterations),
        'clean_workdir': orm.Bool(clean_workdir),
    }

    # Add restart if available
    if restart_arg:
        cp2k_kwargs['cp2k__parent_calc_folder'] = restart_arg['parent_calc_folder']

    # Add settings if we have additional retrieve
    if settings:
        cp2k_kwargs['cp2k__settings'] = orm.Dict(dict=settings)

    cp2k_task = wg.add_task(Cp2kTask, name=f'{stage_name}_cp2k', **cp2k_kwargs)

    # If dynamics computed at runtime, we need to merge it into parameters
    # This requires a calcfunction that creates parameters from base + fixed_atoms
    if dynamics_task is not None:
        # Create a task to merge fixed atoms into parameters
        merge_task = wg.add_task(
            _merge_fixed_atoms_to_params,
            name=f'merge_fixed_{stage_name}',
            base_parameters=orm.Dict(dict=parameters),
            fixed_atoms=dynamics_task.outputs.result,
        )
        # Update cp2k task to use merged parameters
        cp2k_task.set({'cp2k__parameters': merge_task.outputs.result})

    # Extract energy
    energy_task = wg.add_task(
        extract_cp2k_energy,
        name=f'{stage_name}_energy',
        output_parameters=cp2k_task.outputs.output_parameters,
    )

    return {
        'cp2k': cp2k_task,
        'energy': energy_task,
        'input_structure': stage_structure,
        'supercell': supercell_task,
    }


# ---------------------------------------------------------------------------
# Helper calcfunction to merge fixed atoms at runtime
# ---------------------------------------------------------------------------

from aiida_workgraph import task as wg_task


@wg_task.calcfunction
def _merge_fixed_atoms_to_params(base_parameters: orm.Dict, fixed_atoms: orm.Dict) -> orm.Dict:
    """Merge fixed atoms specification into CP2K parameters.

    Args:
        base_parameters: Base CP2K parameters dict
        fixed_atoms: Dict with 'fixed_atoms' key from compute_cp2k_dynamics

    Returns:
        Updated parameters Dict with FIXED_ATOMS section
    """
    params = base_parameters.get_dict()
    fixed_atoms_section = fixed_atoms.get_dict().get('fixed_atoms')

    if fixed_atoms_section is not None:
        # Ensure MOTION.CONSTRAINT exists
        if 'MOTION' not in params:
            params['MOTION'] = {}
        if 'CONSTRAINT' not in params['MOTION']:
            params['MOTION']['CONSTRAINT'] = {}
        params['MOTION']['CONSTRAINT']['FIXED_ATOMS'] = fixed_atoms_section

    return orm.Dict(dict=params)


# ---------------------------------------------------------------------------
# expose_stage_outputs
# ---------------------------------------------------------------------------

def expose_stage_outputs(wg, stage_name: str, stage_tasks_result: dict,
                         namespace_map: dict = None) -> None:
    """Wire CP2K stage outputs onto the WorkGraph.

    Args:
        wg: WorkGraph instance
        stage_name: Unique stage identifier
        stage_tasks_result: Dict returned by create_stage_tasks
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 's01_geo_opt'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    cp2k_task = stage_tasks_result['cp2k']
    energy_task = stage_tasks_result['energy']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.cp2k.energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{ns}.cp2k.structure', cp2k_task.outputs.output_structure)
        setattr(wg.outputs, f'{ns}.cp2k.output_parameters', cp2k_task.outputs.output_parameters)
        setattr(wg.outputs, f'{ns}.cp2k.remote', cp2k_task.outputs.remote_folder)
        setattr(wg.outputs, f'{ns}.cp2k.retrieved', cp2k_task.outputs.retrieved)
    else:
        setattr(wg.outputs, f'{stage_name}_energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_structure', cp2k_task.outputs.output_structure)
        setattr(wg.outputs, f'{stage_name}_output_parameters', cp2k_task.outputs.output_parameters)
        setattr(wg.outputs, f'{stage_name}_remote', cp2k_task.outputs.remote_folder)
        setattr(wg.outputs, f'{stage_name}_retrieved', cp2k_task.outputs.retrieved)


# ---------------------------------------------------------------------------
# get_stage_results
# ---------------------------------------------------------------------------

def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from completed CP2K stage.

    Args:
        wg_node: Completed WorkGraph node
        wg_pk: WorkGraph PK (for error messages)
        stage_name: Original stage name from config
        namespace_map: Dict mapping output group to namespace string

    Returns:
        Dict with 'energy', 'structure', 'output_parameters', 'remote', 'retrieved', 'pk', 'stage', 'type'
    """
    result = {
        'energy': None,
        'structure': None,
        'output_parameters': None,
        'remote': None,
        'retrieved': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'cp2k',
    }

    # Try to access via WorkGraph outputs (exposed outputs)
    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'cp2k', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'energy'):
                    energy_node = brick_ns.energy
                    if hasattr(energy_node, 'value'):
                        result['energy'] = energy_node.value
                    else:
                        result['energy'] = float(energy_node)
                if hasattr(brick_ns, 'structure'):
                    result['structure'] = brick_ns.structure
                if hasattr(brick_ns, 'output_parameters'):
                    params_node = brick_ns.output_parameters
                    if hasattr(params_node, 'get_dict'):
                        result['output_parameters'] = params_node.get_dict()
                if hasattr(brick_ns, 'remote'):
                    result['remote'] = brick_ns.remote
                if hasattr(brick_ns, 'retrieved'):
                    result['retrieved'] = brick_ns.retrieved
        else:
            # Flat naming fallback
            energy_attr = f'{stage_name}_energy'
            if hasattr(outputs, energy_attr):
                energy_node = getattr(outputs, energy_attr)
                if hasattr(energy_node, 'value'):
                    result['energy'] = energy_node.value
                else:
                    result['energy'] = float(energy_node)

            struct_attr = f'{stage_name}_structure'
            if hasattr(outputs, struct_attr):
                result['structure'] = getattr(outputs, struct_attr)

            params_attr = f'{stage_name}_output_parameters'
            if hasattr(outputs, params_attr):
                params_node = getattr(outputs, params_attr)
                if hasattr(params_node, 'get_dict'):
                    result['output_parameters'] = params_node.get_dict()

            remote_attr = f'{stage_name}_remote'
            if hasattr(outputs, remote_attr):
                result['remote'] = getattr(outputs, remote_attr)

            retrieved_attr = f'{stage_name}_retrieved'
            if hasattr(outputs, retrieved_attr):
                result['retrieved'] = getattr(outputs, retrieved_attr)

    # Fallback: traverse links to find Cp2kBaseWorkChain outputs
    if result['energy'] is None or result['output_parameters'] is None:
        _extract_cp2k_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_cp2k_stage_from_workgraph(wg_node, stage_name: str, result: dict) -> None:
    """Extract stage results by traversing WorkGraph links.

    Args:
        wg_node: The WorkGraph node.
        stage_name: Name of the stage to extract.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    cp2k_task_name = f'{stage_name}_cp2k'
    energy_task_name = f'{stage_name}_energy'

    # Traverse CALL_WORK links to find Cp2kBaseWorkChain
    called = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called.all():
        child_node = link.node
        link_label = link.link_label

        if cp2k_task_name in link_label or link_label == cp2k_task_name:
            if hasattr(child_node, 'outputs'):
                outputs = child_node.outputs

                if result['output_parameters'] is None and hasattr(outputs, 'output_parameters'):
                    params = outputs.output_parameters
                    if hasattr(params, 'get_dict'):
                        result['output_parameters'] = params.get_dict()

                if result['structure'] is None and hasattr(outputs, 'output_structure'):
                    result['structure'] = outputs.output_structure

                if result['remote'] is None and hasattr(outputs, 'remote_folder'):
                    result['remote'] = outputs.remote_folder

                if result['retrieved'] is None and hasattr(outputs, 'retrieved'):
                    result['retrieved'] = outputs.retrieved

    # Traverse CALL_CALC links to find energy calcfunction
    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if energy_task_name in link_label or link_label == energy_task_name:
            created = child_node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result':
                    energy_node = out_link.node
                    if hasattr(energy_node, 'value'):
                        result['energy'] = energy_node.value
                    break


# ---------------------------------------------------------------------------
# print_stage_results
# ---------------------------------------------------------------------------

def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for CP2K stage.

    Args:
        index: Stage index (for display numbering)
        stage_name: Original stage name from config
        stage_result: Dict returned by get_stage_results
    """
    print(f"  [{index}] {stage_name} (CP2K)")

    if stage_result.get('energy') is not None:
        print(f"      Energy: {stage_result['energy']:.6f} eV")

    if stage_result.get('structure') is not None:
        struct = stage_result['structure']
        formula = struct.get_formula()
        n_atoms = len(struct.sites)
        print(f"      Structure: {formula} ({n_atoms} atoms, PK: {struct.pk})")

    if stage_result.get('output_parameters') is not None:
        params = stage_result['output_parameters']
        # Display run_type if available
        run_type = params.get('run_type', 'N/A')
        print(f"      Run type: {run_type}")
        # Display motion_step_info if available (for GEO_OPT, MD)
        if 'motion_step_info' in params:
            step_info = params['motion_step_info']
            if isinstance(step_info, dict):
                nsteps = step_info.get('nsteps', 'N/A')
                print(f"      Steps: {nsteps}")

    if stage_result.get('remote') is not None:
        print(f"      Remote folder: PK {stage_result['remote'].pk}")

    if stage_result.get('retrieved') is not None:
        files = stage_result['retrieved'].list_object_names()
        print(f"      Retrieved: {', '.join(files[:5])}{'...' if len(files) > 5 else ''}")
