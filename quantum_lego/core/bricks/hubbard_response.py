"""Hubbard response brick for the lego module.

Runs NSCF + SCF response calculations for each perturbation potential V,
extracts d-electron occupations, and gathers the responses. This brick
requires a prior ground state (vasp brick) stage to restart from.

Reference: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U

KNOWN ISSUE / WORKAROUND:
There is a bug in AiiDA (2.7.1) + aiida-vasp (5.0.0) where VaspCalculation
with restart_folder input doesn't produce remote_folder output. This causes
the standard VaspWorkChain to fail with exit code 11 ("missing required output").

Solution: We define VaspWorkChainNoRemote, a custom wrapper that makes the
remote_folder output optional. This allows the workflow to continue since
the response calculations don't need their own remote_folder (both NSCF and
SCF restart from the ground state's remote folder, not from each other).

See: https://github.com/aiidateam/aiida-core/issues/XXXX
See: https://github.com/aiidateam/aiida-vasp/issues/XXXX
"""

from aiida import orm
from aiida.common.links import LinkType
from aiida.engine import WorkChain
from aiida_vasp.workchains.v2.vasp import VaspWorkChain as OriginalVaspWC
from aiida_workgraph import task

from .connections import HUBBARD_RESPONSE_PORTS as PORTS  # noqa: F401

from quantum_lego.core.common.u_calculation.tasks import (
    extract_d_electron_occupation,
    calculate_occupation_response,
    gather_responses,
)
from quantum_lego.core.common.u_calculation.utils import (
    prepare_response_incar,
    get_species_order_from_structure,
    DEFAULT_POTENTIAL_VALUES,
)
from quantum_lego.core.common.utils import get_vasp_parser_settings


class VaspWorkChainNoRemote(OriginalVaspWC):
    """VaspWorkChain wrapper that makes remote_folder output optional.

    This works around the AiiDA bug where VaspCalculation with restart_folder
    input doesn't produce remote_folder output, which would cause the original
    VaspWorkChain to fail with exit code 11.

    Since the hubbard_response workflow doesn't need remote_folder from the
    response calculations (both NSCF and SCF restart from the ground state's
    remote folder), making this output optional allows the workflow to proceed.
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)
        # Make remote_folder output not required
        spec.outputs['remote_folder'].required = False


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a hubbard_response stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'target_species' not in stage:
        raise ValueError(
            f"Stage '{name}': hubbard_response stages require 'target_species' "
            f"(element symbol for U calculation, e.g., 'Ni', 'Fe')"
        )

    if 'ground_state_from' not in stage:
        raise ValueError(
            f"Stage '{name}': hubbard_response stages require 'ground_state_from' "
            f"(name of the ground state vasp stage to restart from)"
        )

    ground_state_from = stage['ground_state_from']
    if ground_state_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' ground_state_from='{ground_state_from}' must be "
            f"a previous stage name"
        )

    # structure_from is required
    if 'structure_from' not in stage:
        raise ValueError(
            f"Stage '{name}': hubbard_response stages require 'structure_from' "
            f"('input' or a previous stage name)"
        )

    structure_from = stage['structure_from']
    if structure_from != 'input' and structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must be 'input' "
            f"or a previous stage name"
        )

    # Validate potential_values if provided
    potential_values = stage.get('potential_values', None)
    if potential_values is not None:
        if not isinstance(potential_values, (list, tuple)):
            raise ValueError(
                f"Stage '{name}' potential_values must be a list of floats"
            )
        if len(potential_values) < 2:
            raise ValueError(
                f"Stage '{name}' potential_values needs at least 2 values "
                f"for linear regression"
            )
        if 0.0 in potential_values:
            raise ValueError(
                f"Stage '{name}' potential_values must not include 0.0 "
                f"(ground state has LDAU=False, response has LDAU=True)"
            )

    # Validate ldaul if provided
    ldaul = stage.get('ldaul', 2)
    if ldaul not in (2, 3):
        raise ValueError(
            f"Stage '{name}' ldaul={ldaul} must be 2 (d-electrons) or "
            f"3 (f-electrons)"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create hubbard_response stage tasks in the WorkGraph.

    This creates:
    1. Ground state occupation extraction (from the referenced ground state)
    2. For each potential V: NSCF response + SCF response + occupation extraction
    3. Gather all responses into a list

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    from ..workgraph import _prepare_builder_inputs

    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    options = context['options']
    base_kpoints_spacing = context['base_kpoints_spacing']
    clean_workdir = context['clean_workdir']
    input_structure = context['input_structure']
    stage_tasks = context['stage_tasks']

    # Use custom wrapper that makes remote_folder output optional
    VaspTask = task(VaspWorkChainNoRemote)

    # Stage configuration
    target_species = stage['target_species']
    potential_values = stage.get('potential_values', DEFAULT_POTENTIAL_VALUES)
    ldaul = stage.get('ldaul', 2)
    ldauj = stage.get('ldauj', 0.0)
    stage_kpoints_spacing = stage.get('kpoints_spacing', base_kpoints_spacing)
    base_incar = stage.get('incar', {})

    # Resolve input structure
    structure_from = stage['structure_from']
    if structure_from == 'input':
        stage_structure = input_structure
    else:
        from . import resolve_structure_from
        stage_structure = resolve_structure_from(structure_from, context)

    # Get species order for LDAU arrays
    if isinstance(stage_structure, orm.StructureData):
        all_species = get_species_order_from_structure(stage_structure)
    else:
        all_species = get_species_order_from_structure(input_structure)

    lmaxmix = 4 if ldaul == 2 else 6

    # Parser settings
    settings = get_vasp_parser_settings(
        add_energy=True,
        add_trajectory=True,
        add_structure=True,
        add_kpoints=True,
    )

    # Get ground state outputs from the referenced stage
    ground_state_from = stage['ground_state_from']
    gs_remote_folder = stage_tasks[ground_state_from]['vasp'].outputs.remote_folder
    gs_retrieved = stage_tasks[ground_state_from]['vasp'].outputs.retrieved

    # Extract ground state d-electron occupation
    gs_occupation = wg.add_task(
        extract_d_electron_occupation,
        name=f'gs_occ_{stage_name}',
        retrieved=gs_retrieved,
        target_species=orm.Str(target_species),
        structure=stage_structure,
    )

    # Response calculations for each potential value
    # Note: tasks are created with sequential dependencies to avoid AiiDA race
    # conditions when multiple VaspCalculations upload to the same computer
    # simultaneously. Each NSCF+SCF pair waits for the previous pair to complete.
    response_tasks = {}
    prev_response = None  # Track previous response task for serialization

    for i, V in enumerate(potential_values):
        label = f'V_{i}'
        V_str = f'{V:+.2f}'.replace('.', 'p').replace('-', 'm').replace('+', 'p')

        # ----- Non-SCF Response (ICHARG=11) -----
        nscf_incar = prepare_response_incar(
            base_params=base_incar,
            potential_value=V,
            target_species=target_species,
            all_species=all_species,
            ldaul=ldaul,
            ldauj=ldauj,
            is_scf=False,
            lmaxmix=lmaxmix,
        )

        nscf_builder_inputs = _prepare_builder_inputs(
            incar=nscf_incar,
            kpoints_spacing=stage_kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping,
            options=options,
            retrieve=['OUTCAR'],
            restart_folder=None,
            clean_workdir=clean_workdir,
        )
        if 'settings' in nscf_builder_inputs:
            existing = nscf_builder_inputs['settings'].get_dict()
            existing.update(settings)
            nscf_builder_inputs['settings'] = orm.Dict(dict=existing)
        else:
            nscf_builder_inputs['settings'] = orm.Dict(dict=settings)

        nscf_task = wg.add_task(
            VaspTask,
            name=f'nscf_{V_str}_{stage_name}',
            structure=stage_structure,
            code=code,
            restart_folder=gs_remote_folder,
            **nscf_builder_inputs,
        )

        # Add sequential dependency: wait for previous response to complete
        # This avoids AiiDA race conditions with concurrent calcjob uploads when
        # multiple VaspCalculations access the same remote restart folder simultaneously.
        # Each NSCF waits for the previous complete response cycle (NSCF+SCF+extraction).
        if prev_response is not None:
            wg.add_link(prev_response.outputs._wait, nscf_task.inputs._wait)

        nscf_occ = wg.add_task(
            extract_d_electron_occupation,
            name=f'nscf_occ_{V_str}_{stage_name}',
            retrieved=nscf_task.outputs.retrieved,
            target_species=orm.Str(target_species),
            structure=stage_structure,
        )

        # ----- SCF Response -----
        scf_incar = prepare_response_incar(
            base_params=base_incar,
            potential_value=V,
            target_species=target_species,
            all_species=all_species,
            ldaul=ldaul,
            ldauj=ldauj,
            is_scf=True,
            lmaxmix=lmaxmix,
        )

        scf_builder_inputs = _prepare_builder_inputs(
            incar=scf_incar,
            kpoints_spacing=stage_kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping,
            options=options,
            retrieve=['OUTCAR'],
            restart_folder=None,
            clean_workdir=clean_workdir,
        )
        if 'settings' in scf_builder_inputs:
            existing = scf_builder_inputs['settings'].get_dict()
            existing.update(settings)
            scf_builder_inputs['settings'] = orm.Dict(dict=existing)
        else:
            scf_builder_inputs['settings'] = orm.Dict(dict=settings)

        scf_task = wg.add_task(
            VaspTask,
            name=f'scf_{V_str}_{stage_name}',
            structure=stage_structure,
            code=code,
            restart_folder=gs_remote_folder,
            **scf_builder_inputs,
        )

        # Note: Both NSCF (ICHARG=11) and SCF restart from ground state's remote_folder.
        # NSCF reads the charge density but doesn't modify it; SCF reads WAVECAR/CHGCAR.
        # We do NOT add a dependency between NSCF and SCF here because:
        # 1. Both independently need only the GS remote folder (no intermediate products)
        # 2. Adding this link created a broken chain due to AiiDA bug where VaspCalculation
        #    with restart_folder input doesn't produce remote_folder output.
        # See: https://github.com/aiidateam/aiida-core/issues/
        # Serialization is maintained at the prev_response level above (each new V waits
        # for previous V's complete response to finish).

        scf_occ = wg.add_task(
            extract_d_electron_occupation,
            name=f'scf_occ_{V_str}_{stage_name}',
            retrieved=scf_task.outputs.retrieved,
            target_species=orm.Str(target_species),
            structure=stage_structure,
        )

        # Calculate response for this potential
        response = wg.add_task(
            calculate_occupation_response,
            name=f'response_{V_str}_{stage_name}',
            ground_state_occupation=gs_occupation.outputs.result,
            nscf_occupation=nscf_occ.outputs.result,
            scf_occupation=scf_occ.outputs.result,
            potential_value=orm.Float(V),
        )

        response_tasks[label] = response
        prev_response = response  # Track for next iteration's dependency

    # Gather all responses
    gather_kwargs = {
        label: resp_task.outputs.result
        for label, resp_task in response_tasks.items()
    }
    gathered = wg.add_task(
        gather_responses,
        name=f'gather_{stage_name}',
        **gather_kwargs,
    )

    return {
        'responses': gathered,
        'gs_occupation': gs_occupation,
        'structure': stage_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose hubbard_response stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    gathered = stage_tasks_result['responses']
    gs_occupation = stage_tasks_result['gs_occupation']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.hubbard_response.responses',
                gathered.outputs.result)
        setattr(wg.outputs, f'{ns}.hubbard_response.ground_state_occupation',
                gs_occupation.outputs.result)
    else:
        setattr(wg.outputs, f'{stage_name}_responses',
                gathered.outputs.result)
        setattr(wg.outputs, f'{stage_name}_ground_state_occupation',
                gs_occupation.outputs.result)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a hubbard_response stage.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: responses, ground_state_occupation, pk, stage, type.
    """
    result = {
        'responses': None,
        'ground_state_occupation': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'hubbard_response',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'hubbard_response', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'responses'):
                    responses_node = brick_ns.responses
                    if hasattr(responses_node, 'get_list'):
                        result['responses'] = responses_node.get_list()
                if hasattr(brick_ns, 'ground_state_occupation'):
                    gs_occ_node = brick_ns.ground_state_occupation
                    if hasattr(gs_occ_node, 'get_dict'):
                        result['ground_state_occupation'] = gs_occ_node.get_dict()
        else:
            responses_attr = f'{stage_name}_responses'
            if hasattr(outputs, responses_attr):
                responses_node = getattr(outputs, responses_attr)
                if hasattr(responses_node, 'get_list'):
                    result['responses'] = responses_node.get_list()

            gs_occ_attr = f'{stage_name}_ground_state_occupation'
            if hasattr(outputs, gs_occ_attr):
                gs_occ_node = getattr(outputs, gs_occ_attr)
                if hasattr(gs_occ_node, 'get_dict'):
                    result['ground_state_occupation'] = gs_occ_node.get_dict()

    # Fallback: traverse links
    if result['responses'] is None:
        _extract_response_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_response_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract response stage results by traversing WorkGraph links."""
    if not hasattr(wg_node, 'base'):
        return

    gather_task_name = f'gather_{stage_name}'
    gs_occ_task_name = f'gs_occ_{stage_name}'

    called_calc = wg_node.base.links.get_outgoing(
        link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if gather_task_name in link_label or link_label == gather_task_name:
            created = child_node.base.links.get_outgoing(
                link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result' and hasattr(out_link.node, 'get_list'):
                    result['responses'] = out_link.node.get_list()

        if gs_occ_task_name in link_label or link_label == gs_occ_task_name:
            created = child_node.base.links.get_outgoing(
                link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result' and hasattr(out_link.node, 'get_dict'):
                    result['ground_state_occupation'] = out_link.node.get_dict()


def print_stage_results(
    index: int, stage_name: str, stage_result: dict
) -> None:
    """Print formatted results for a hubbard_response stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="hubbard_response")

    if stage_result['responses'] is not None:
        responses = stage_result['responses']
        console.print(f"      [bold]Responses gathered:[/bold] {len(responses)}")
        potentials = [r.get('potential', 0.0) for r in responses]
        if potentials:
            potentials_str = ', '.join(f"[energy]{p:.3f}[/energy]" for p in potentials)
            console.print(f"      [bold]Potentials:[/bold] {potentials_str} eV")

    if stage_result['ground_state_occupation'] is not None:
        gs = stage_result['ground_state_occupation']
        species = gs.get('target_species', '?')
        avg_d = gs.get('total_d_occupation', 0.0) / max(gs.get('atom_count', 1), 1)
        console.print(f"      [bold]GS avg d-occupation per {species}:[/bold] [energy]{avg_d:.3f}[/energy]")
