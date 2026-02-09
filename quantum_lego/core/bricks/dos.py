"""DOS brick for the lego module.

Handles DOS calculation stages using BandsWorkChain (vasp.v2.bands).
"""

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task
from .connections import DOS_PORTS as PORTS  # noqa: F401
from ..retrieve_defaults import build_vasp_retrieve


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a DOS stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'scf_incar' not in stage:
        raise ValueError(f"Stage '{name}': DOS stages require 'scf_incar'")
    if 'dos_incar' not in stage:
        raise ValueError(f"Stage '{name}': DOS stages require 'dos_incar'")
    if 'structure_from' not in stage:
        raise ValueError(f"Stage '{name}': DOS stages require 'structure_from'")

    structure_from = stage['structure_from']
    if structure_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' structure_from='{structure_from}' must reference "
            f"a previous stage name"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create DOS stage tasks in the WorkGraph.

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    from . import resolve_structure_from

    code = context['code']
    potential_family = context['potential_family']
    potential_mapping = context['potential_mapping']
    options = context['options']
    base_kpoints_spacing = context['base_kpoints_spacing']
    clean_workdir = context['clean_workdir']

    # Resolve structure from referenced stage
    structure_from = stage['structure_from']
    input_structure = resolve_structure_from(structure_from, context)

    # Get BandsWorkChain and wrap as task
    BandsWorkChain = WorkflowFactory('vasp.v2.bands')
    BandsTask = task(BandsWorkChain)

    # Handle SCF k-points: explicit mesh or spacing
    scf_kpoints_mesh = stage.get('kpoints', None)
    scf_kpoints_spacing = stage.get('kpoints_spacing', base_kpoints_spacing)

    # Handle DOS k-points: explicit mesh or spacing
    dos_kpoints_mesh = stage.get('dos_kpoints', None)
    dos_kpoints_spacing = stage.get('dos_kpoints_spacing', scf_kpoints_spacing * 0.8)

    # Prepare SCF INCAR
    scf_incar = dict(stage['scf_incar'])
    scf_incar.update({
        'nsw': 0,
        'ibrion': -1,
    })

    # Prepare DOS INCAR
    dos_incar = dict(stage['dos_incar'])
    dos_incar.setdefault('ismear', -5)
    dos_incar.setdefault('lorbit', 11)
    dos_incar.setdefault('nedos', 2000)
    dos_incar.update({
        'nsw': 0,
        'ibrion': -1,
    })

    # Files to retrieve from SCF and DOS calculations
    scf_retrieve = build_vasp_retrieve(None)
    dos_retrieve = build_vasp_retrieve(stage.get('retrieve', ['DOSCAR']))

    # Prepare SCF input dict
    scf_input = {
        'code': code,
        'parameters': orm.Dict({'incar': scf_incar}),
        'potential_family': potential_family,
        'potential_mapping': orm.Dict(potential_mapping),
        'options': orm.Dict(options),
        'settings': orm.Dict({'ADDITIONAL_RETRIEVE_LIST': scf_retrieve}),
        'clean_workdir': False,
    }

    # SCF k-points
    if scf_kpoints_mesh is not None:
        scf_kpoints = orm.KpointsData()
        scf_kpoints.set_kpoints_mesh(scf_kpoints_mesh)
        scf_input['kpoints'] = scf_kpoints
    else:
        scf_input['kpoints_spacing'] = float(scf_kpoints_spacing)

    # Prepare DOS input dict
    dos_input = {
        'code': code,
        'parameters': orm.Dict({'incar': dos_incar}),
        'potential_family': potential_family,
        'potential_mapping': orm.Dict(potential_mapping),
        'options': orm.Dict(options),
        'settings': orm.Dict({'ADDITIONAL_RETRIEVE_LIST': dos_retrieve}),
    }

    # DOS k-points
    if dos_kpoints_mesh is not None:
        dos_kpoints = orm.KpointsData()
        dos_kpoints.set_kpoints_mesh(dos_kpoints_mesh)
        dos_input['kpoints'] = dos_kpoints
        band_settings = orm.Dict({
            'only_dos': True,
            'run_dos': True,
            'dos_kpoints_distance': 0.03,
        })
    else:
        band_settings = orm.Dict({
            'only_dos': True,
            'run_dos': True,
            'dos_kpoints_distance': float(dos_kpoints_spacing),
        })

    # Add BandsWorkChain task
    bands_task = wg.add_task(
        BandsTask,
        name=f'bands_{stage_name}',
        structure=input_structure,
        scf=scf_input,
        dos=dos_input,
        band_settings=band_settings,
        clean_children_workdir=orm.Str('all') if clean_workdir else None,
    )

    return {
        'bands_task': bands_task,
        'structure': input_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose DOS stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'scf': 'stage2', 'dos': 'stage3'}. If None,
                      falls back to flat naming with stage_name prefix.
    """
    bands_task = stage_tasks_result['bands_task']

    if namespace_map is not None:
        scf_ns = namespace_map['scf']
        dos_ns = namespace_map['dos']

        # SCF outputs
        try:
            setattr(wg.outputs, f'{scf_ns}.scf.misc', bands_task.outputs.scf_misc)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{scf_ns}.scf.remote', bands_task.outputs.scf_remote_folder)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{scf_ns}.scf.retrieved', bands_task.outputs.scf_retrieved)
        except AttributeError:
            pass

        # DOS outputs
        try:
            setattr(wg.outputs, f'{dos_ns}.dos.dos', bands_task.outputs.dos)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{dos_ns}.dos.projectors', bands_task.outputs.projectors)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{dos_ns}.dos.misc', bands_task.outputs.dos_misc)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{dos_ns}.dos.remote', bands_task.outputs.dos_remote_folder)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{dos_ns}.dos.retrieved', bands_task.outputs.dos_retrieved)
        except AttributeError:
            pass
    else:
        # Expose BandsWorkChain outputs (optional)
        try:
            setattr(wg.outputs, f'{stage_name}_dos', bands_task.outputs.dos)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{stage_name}_projectors', bands_task.outputs.projectors)
        except AttributeError:
            pass

        # Expose internal SCF workchain outputs
        try:
            setattr(wg.outputs, f'{stage_name}_scf_misc', bands_task.outputs.scf_misc)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{stage_name}_scf_remote', bands_task.outputs.scf_remote_folder)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{stage_name}_scf_retrieved', bands_task.outputs.scf_retrieved)
        except AttributeError:
            pass

        # Expose internal DOS workchain outputs
        try:
            setattr(wg.outputs, f'{stage_name}_dos_misc', bands_task.outputs.dos_misc)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{stage_name}_dos_remote', bands_task.outputs.dos_remote_folder)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{stage_name}_dos_retrieved', bands_task.outputs.dos_retrieved)
        except AttributeError:
            pass


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a DOS stage in a sequential workflow.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the DOS stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'scf': 'stage2', 'dos': 'stage3'}. If None,
                      uses flat naming.

    Returns:
        Dict with keys: energy, scf_misc, scf_remote, scf_retrieved,
        dos_misc, dos_remote, files, pk, stage, type.
    """
    from ..results import _extract_energy_from_misc

    result = {
        'energy': None,
        'scf_misc': None,
        'scf_remote': None,
        'scf_retrieved': None,
        'dos_misc': None,
        'dos_remote': None,
        'files': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'dos',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            scf_ns = namespace_map['scf']
            dos_ns = namespace_map['dos']

            # SCF namespace outputs: stage_ns.scf.output
            stage_scf = getattr(outputs, scf_ns, None)
            scf_outputs = getattr(stage_scf, 'scf', None) if stage_scf is not None else None
            if scf_outputs is not None:
                if hasattr(scf_outputs, 'misc'):
                    misc_node = scf_outputs.misc
                    if hasattr(misc_node, 'get_dict'):
                        result['scf_misc'] = misc_node.get_dict()
                if hasattr(scf_outputs, 'remote'):
                    result['scf_remote'] = scf_outputs.remote
                if hasattr(scf_outputs, 'retrieved'):
                    result['scf_retrieved'] = scf_outputs.retrieved

            # DOS namespace outputs: stage_ns.dos.output
            stage_dos = getattr(outputs, dos_ns, None)
            dos_outputs = getattr(stage_dos, 'dos', None) if stage_dos is not None else None
            if dos_outputs is not None:
                if hasattr(dos_outputs, 'dos'):
                    result['dos_arraydata'] = dos_outputs.dos
                if hasattr(dos_outputs, 'projectors'):
                    result['projectors'] = dos_outputs.projectors
                if hasattr(dos_outputs, 'misc'):
                    misc_node = dos_outputs.misc
                    if hasattr(misc_node, 'get_dict'):
                        result['dos_misc'] = misc_node.get_dict()
                if hasattr(dos_outputs, 'remote'):
                    result['dos_remote'] = dos_outputs.remote
                if hasattr(dos_outputs, 'retrieved'):
                    result['files'] = dos_outputs.retrieved
        else:
            # Flat naming fallback
            # DOS ArrayData
            dos_attr = f'{stage_name}_dos'
            if hasattr(outputs, dos_attr):
                result['dos_arraydata'] = getattr(outputs, dos_attr)

            # Projectors ArrayData
            projectors_attr = f'{stage_name}_projectors'
            if hasattr(outputs, projectors_attr):
                result['projectors'] = getattr(outputs, projectors_attr)

            # SCF outputs
            scf_misc_attr = f'{stage_name}_scf_misc'
            if hasattr(outputs, scf_misc_attr):
                misc_node = getattr(outputs, scf_misc_attr)
                if hasattr(misc_node, 'get_dict'):
                    result['scf_misc'] = misc_node.get_dict()

            scf_remote_attr = f'{stage_name}_scf_remote'
            if hasattr(outputs, scf_remote_attr):
                result['scf_remote'] = getattr(outputs, scf_remote_attr)

            scf_retrieved_attr = f'{stage_name}_scf_retrieved'
            if hasattr(outputs, scf_retrieved_attr):
                result['scf_retrieved'] = getattr(outputs, scf_retrieved_attr)

            # DOS outputs
            dos_misc_attr = f'{stage_name}_dos_misc'
            if hasattr(outputs, dos_misc_attr):
                misc_node = getattr(outputs, dos_misc_attr)
                if hasattr(misc_node, 'get_dict'):
                    result['dos_misc'] = misc_node.get_dict()

            dos_remote_attr = f'{stage_name}_dos_remote'
            if hasattr(outputs, dos_remote_attr):
                result['dos_remote'] = getattr(outputs, dos_remote_attr)

            dos_retrieved_attr = f'{stage_name}_dos_retrieved'
            if hasattr(outputs, dos_retrieved_attr):
                result['files'] = getattr(outputs, dos_retrieved_attr)

    # Fallback: Traverse links
    if result['scf_misc'] is None or result['dos_misc'] is None:
        _extract_from_bands_workchain(wg_node, stage_name, result)

    # Extract energy from scf_misc
    if result['energy'] is None and result['scf_misc'] is not None:
        result['energy'] = _extract_energy_from_misc(result['scf_misc'])

    return result


def _extract_from_bands_workchain(wg_node, stage_name: str, result: dict) -> None:
    """Extract DOS stage results by traversing to BandsWorkChain.

    Args:
        wg_node: The WorkGraph node.
        stage_name: Name of the DOS stage.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    bands_task_name = f'bands_{stage_name}'

    called = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called.all():
        child_node = link.node
        link_label = link.link_label

        if bands_task_name in link_label or link_label == bands_task_name:
            if hasattr(child_node, 'outputs'):
                outputs = child_node.outputs
                if 'dos_arraydata' not in result and hasattr(outputs, 'dos'):
                    result['dos_arraydata'] = outputs.dos
                if 'projectors' not in result and hasattr(outputs, 'projectors'):
                    result['projectors'] = outputs.projectors

            if hasattr(child_node, 'base'):
                _extract_from_bands_children(child_node, result)


def _extract_from_bands_children(bands_node, result: dict) -> None:
    """Extract outputs from BandsWorkChain's child workchains.

    Args:
        bands_node: The BandsWorkChain node.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(bands_node, 'base'):
        return

    called = bands_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called.all():
        child_node = link.node
        link_label = link.link_label.lower()

        if hasattr(child_node, 'outputs'):
            outputs = child_node.outputs

            # SCF workchain
            if 'scf' in link_label:
                if result['scf_misc'] is None and hasattr(outputs, 'misc'):
                    misc = outputs.misc
                    if hasattr(misc, 'get_dict'):
                        result['scf_misc'] = misc.get_dict()
                if result['scf_remote'] is None and hasattr(outputs, 'remote_folder'):
                    result['scf_remote'] = outputs.remote_folder

            # DOS workchain
            if 'dos' in link_label and 'seekpath' not in link_label:
                if result['dos_misc'] is None and hasattr(outputs, 'misc'):
                    misc = outputs.misc
                    if hasattr(misc, 'get_dict'):
                        result['dos_misc'] = misc.get_dict()
                if result['dos_remote'] is None and hasattr(outputs, 'remote_folder'):
                    result['dos_remote'] = outputs.remote_folder
                if result['files'] is None and hasattr(outputs, 'retrieved'):
                    result['files'] = outputs.retrieved


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a DOS stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    print(f"  [{index}] {stage_name} (DOS)")

    if stage_result['energy'] is not None:
        print(f"      SCF Energy: {stage_result['energy']:.6f} eV")

    if stage_result['scf_misc'] is not None:
        scf_misc = stage_result['scf_misc']
        run_status = scf_misc.get('run_status', {})
        converged = run_status.get('electronic_converged', 'N/A')
        print(f"      SCF converged: {converged}")

    if stage_result['dos_misc'] is not None:
        dos_misc = stage_result['dos_misc']
        band_props = dos_misc.get('band_properties', {})
        band_gap = band_props.get('band_gap', None)
        if band_gap is not None:
            is_direct = band_props.get('is_direct_gap', False)
            gap_type = "direct" if is_direct else "indirect"
            print(f"      Band gap: {band_gap:.4f} eV ({gap_type})")
        fermi = dos_misc.get('fermi_level', None)
        if fermi is not None:
            print(f"      Fermi level: {fermi:.4f} eV")

    if stage_result['scf_remote'] is not None:
        print(f"      SCF Remote folder: PK {stage_result['scf_remote'].pk}")

    if stage_result['dos_remote'] is not None:
        print(f"      DOS Remote folder: PK {stage_result['dos_remote'].pk}")

    if stage_result['files'] is not None:
        files = stage_result['files'].list_object_names()
        print(f"      DOS Retrieved: {', '.join(files)}")
