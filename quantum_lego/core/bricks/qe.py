"""QE brick for lego module.

Wraps Quantum ESPRESSO PwBaseWorkChain from aiida-quantumespresso.
Supports SCF, relax, and vc-relax calculations with restart chaining.
"""

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory

from .connections import QE_PORTS as PORTS  # noq: F401


# ---------------------------------------------------------------------------
# validate_stage
# ---------------------------------------------------------------------------

def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate QE stage configuration before submission.

    Args:
        stage: Stage configuration dict
        stage_names: Set of all stage names seen so far (for dependency checking)

    Raises:
        ValueError: If stage configuration is invalid
    """
    stage_name = stage.get('name', 'qe_stage')

    # Required: parameters (QE namelists dict)
    if 'parameters' not in stage:
        raise ValueError(f"QE stage '{stage_name}' must have 'parameters' field "
                         f"(QE namelists: CONTROL, SYSTEM, ELECTRONS, etc.)")

    # Required: restart (None or previous stage name)
    if 'restart' not in stage:
        raise ValueError(f"QE stage '{stage_name}' must have 'restart' field "
                         f"(None or previous stage name)")

    restart = stage['restart']
    if restart is not None and restart not in stage_names:
        raise ValueError(f"QE stage '{stage_name}' restart='{restart}' refers to "
                         f"unknown stage. Must be None or one of: {sorted(stage_names)}")

    # Optional: structure_from ('previous', 'input', or previous stage name)
    structure_from = stage.get('structure_from')
    if structure_from is not None:
        if structure_from not in ('previous', 'input') and structure_from not in stage_names:
            raise ValueError(f"QE stage '{stage_name}' structure_from='{structure_from}' must be "
                             f"'previous', 'input', or a previous stage name: {sorted(stage_names)}")


# ---------------------------------------------------------------------------
# create_stage_tasks
# ---------------------------------------------------------------------------

def create_stage_tasks(wg, stage: dict, stage_name: str, context: dict) -> dict:
    """Create WorkGraph tasks for QE calculation.

    Args:
        wg: WorkGraph instance
        stage: Stage configuration dict
        stage_name: Unique stage name
        context: Shared context with code, pseudo_family, options, etc.

    Returns:
        Dict with 'qe', 'energy', 'input_structure' keys pointing to task objects
    """
    from aiida_workgraph import task
    from ..tasks import extract_qe_energy
    from . import resolve_structure_from

    # Resolve structure for this stage following the auto(previous)/input/'stage_name' pattern
    if 'structure_from' not in stage:
        # Auto mode: use input structure for first QE stage, resolve from previous otherwise
        if len(context.get('stage_names', [])) == 0:
            stage_structure = context['input_structure']
        else:
            # Use previous stage
            prev_name = context['stage_names'][-1]
            prev_stage_type = context['stage_types'].get(prev_name, 'vasp')
            stage_tasks = context['stage_tasks']
            if prev_stage_type in ('vasp', 'aimd'):
                stage_structure = stage_tasks[prev_name]['vasp'].outputs.structure
            elif prev_stage_type == 'neb':
                stage_structure = stage_tasks[prev_name]['neb'].outputs.structure
            elif prev_stage_type == 'qe':
                stage_structure = stage_tasks[prev_name]['qe'].outputs.output_structure
            else:
                raise ValueError(
                    f"Stage '{stage['name']}' uses structure_from='previous' (auto) "
                    f"but previous stage '{prev_name}' is a '{prev_stage_type}' "
                    f"stage that doesn't produce a structure. Use an explicit "
                    f"'structure_from' pointing to a VASP, AIMD, NEB, or QE stage."
                )
    elif stage.get('structure_from') == 'input':
        stage_structure = context['input_structure']
    else:
        # Use output structure from specific stage
        structure_from = stage.get('structure_from')
        stage_structure = resolve_structure_from(structure_from, context)

    # Get QE code
    if 'code_label' in stage:
        code_label = stage['code_label']
        code = orm.load_code(code_label)
    else:
        code = context['code']

    # Get pseudo_family
    if 'pseudo_family' in stage:
        pseudo_family_name = stage['pseudo_family']
    else:
        pseudo_family_name = context['pseudo_family']

    # Resolve pseudopotentials
    try:
        from aiida_pseudo import PseudoPotentialFamily
        PseudoPotentialFamily = PseudoPotentialFamily
    except ImportError:
        raise ImportError("aiida-pseudo is required for QE calculations. "
                          "Install with: pip install aiida-pseudo")

    pseudo_family = orm.load_group(pseudo_family_name)
    if not hasattr(pseudo_family, 'get_pseudos'):
        raise ValueError(f"Group '{pseudo_family_name}' is not a PseudoPotentialFamily")

    pseudos = pseudo_family.get_pseudos(structure=stage_structure)

    # Get parameters
    parameters = stage['parameters']

    # Get options
    if 'options' in stage:
        options = stage['options']
    else:
        options = context['options']

    # Get k-points
    if 'kpoints' in stage:
        # Explicit k-points mesh [nx, ny, nz]
        kpoints_mesh = stage['kpoints']
        kpoints = orm.KpointsData()
        kpoints.set_kpoints_mesh(kpoints_mesh)
        kpoints_arg = {'pw__kpoints': kpoints}
    else:
        # Use kpoints_distance (spacing)
        if 'kpoints_spacing' in stage:
            spacing = stage['kpoints_spacing']
        else:
            spacing = context['base_kpoints_spacing']
        kpoints_arg = {'kpoints_distance': orm.Float(spacing)}

    # Get restart folder if requested
    restart_from = stage.get('restart')
    restart_arg = {}
    if restart_from is not None:
        # Get remote_folder from previous QE stage
        prev_tasks = context['stage_tasks'][restart_from]
        if 'qe' in prev_tasks:
            restart_arg = {'pw__parent_folder': prev_tasks['qe'].outputs.remote_folder}
        else:
            raise ValueError(f"Stage '{restart_from}' does not have QE outputs for restart")

    # Get clean_workdir
    clean_workdir = context.get('clean_workdir', False)

    # Create PwBaseWorkChain task
    PwBaseWorkChain = WorkflowFactory('quantumespresso.pw.base')
    QeTask = task(PwBaseWorkChain)

    qe_kwargs = {
        'pw__structure': stage_structure,
        'pw__code': code,
        'pw__parameters': orm.Dict(dict=parameters),
        'pw__pseudos': pseudos,
        'pw__metadata': {'options': options},
        **kpoints_arg,
        **restart_arg,
        'clean_workdir': orm.Bool(clean_workdir),
    }

    qe_task = wg.add_task(QeTask, name=f'{stage_name}_qe', **qe_kwargs)

    # Extract energy
    energy_task = wg.add_task(
        extract_qe_energy,
        name=f'{stage_name}_energy',
        output_parameters=qe_task.outputs.output_parameters,
    )

    return {
        'qe': qe_task,
        'energy': energy_task,
        'input_structure': stage_structure,
    }


# ---------------------------------------------------------------------------
# expose_stage_outputs
# ---------------------------------------------------------------------------

def expose_stage_outputs(wg, stage_name: str, stage_tasks_result: dict,
                         namespace_map: dict = None) -> None:
    """Wire QE stage outputs onto the WorkGraph.

    Args:
        wg: WorkGraph instance
        stage_name: Unique stage identifier
        stage_tasks_result: Dict returned by create_stage_tasks
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 's01_relax'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    qe_task = stage_tasks_result['qe']
    energy_task = stage_tasks_result['energy']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.qe.energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{ns}.qe.structure', qe_task.outputs.output_structure)
        setattr(wg.outputs, f'{ns}.qe.output_parameters', qe_task.outputs.output_parameters)
        setattr(wg.outputs, f'{ns}.qe.remote', qe_task.outputs.remote_folder)
        setattr(wg.outputs, f'{ns}.qe.retrieved', qe_task.outputs.retrieved)
    else:
        setattr(wg.outputs, f'{stage_name}_energy', energy_task.outputs.result)
        setattr(wg.outputs, f'{stage_name}_structure', qe_task.outputs.output_structure)
        setattr(wg.outputs, f'{stage_name}_output_parameters', qe_task.outputs.output_parameters)
        setattr(wg.outputs, f'{stage_name}_remote', qe_task.outputs.remote_folder)
        setattr(wg.outputs, f'{stage_name}_retrieved', qe_task.outputs.retrieved)


# ---------------------------------------------------------------------------
# get_stage_results
# ---------------------------------------------------------------------------

def get_stage_results(wg_node, wg_pk: int, stage_name: str) -> dict:
    """Extract results from completed QE stage.

    Args:
        wg_node: Completed WorkGraph node
        wg_pk: WorkGraph PK (for error messages)
        stage_name: Stage namespace prefix (e.g., 's01_relax')

    Returns:
        Dict with 'energy', 'structure', 'output_parameters', 'remote', 'retrieved'

    Raises:
        ValueError: If expected outputs not found
    """
    result = {}

    # Helper to traverse links
    def get_output(namespace_path):
        """Navigate wg_node.outputs.{namespace_path} via link traversal."""
        parts = namespace_path.split('.')
        current = wg_node
        for part in parts:
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                # Try link traversal (for stored nodes)
                found = False
                if hasattr(current, 'base'):
                    for link in current.base.links.get_outgoing(link_type=LinkType.RETURN).all():
                        if link.link_label == part:
                            current = link.node
                            found = True
                            break
                if not found:
                    return None
        return current

    # Extract energy
    energy_node = get_output(f'{stage_name}.qe.energy')
    if energy_node is not None:
        result['energy'] = energy_node.value

    # Extract structure
    structure_node = get_output(f'{stage_name}.qe.structure')
    if structure_node is not None:
        result['structure'] = structure_node

    # Extract output_parameters
    output_params_node = get_output(f'{stage_name}.qe.output_parameters')
    if output_params_node is not None:
        result['output_parameters'] = output_params_node.get_dict()

    # Extract remote and retrieved
    result['remote'] = get_output(f'{stage_name}.qe.remote')
    result['retrieved'] = get_output(f'{stage_name}.qe.retrieved')

    return result


# ---------------------------------------------------------------------------
# print_stage_results
# ---------------------------------------------------------------------------

def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for QE stage.

    Args:
        index: Stage index (for display numbering)
        stage_name: Original stage name from config
        stage_result: Dict returned by get_stage_results
    """
    print(f"\n{'=' * 70}")
    print(f"Stage {index}: {stage_name} (QE)")
    print(f"{'=' * 70}")

    # Energy
    if 'energy' in stage_result:
        print(f"Energy: {stage_result['energy']:.6f} eV")

    # Structure formula
    if 'structure' in stage_result:
        structure = stage_result['structure']
        if hasattr(structure, 'get_formula'):
            formula = structure.get_formula()
            print(f"Structure: {formula}")

    # Output parameters highlights
    if 'output_parameters' in stage_result:
        params = stage_result['output_parameters']
        if 'fermi_energy' in params:
            print(f"Fermi Energy: {params['fermi_energy']:.4f} eV")
        if 'total_force' in params:
            print(f"Total Force: {params['total_force']:.4f} eV/Å")

    print(f"{'=' * 70}\n")
