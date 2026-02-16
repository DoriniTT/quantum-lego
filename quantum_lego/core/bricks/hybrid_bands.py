"""Hybrid bands brick for the lego module.

Handles hybrid functional band structure and DOS calculation stages
using VaspHybridBandsWorkChain (vasp.v2.hybrid_bands).

Unlike the DOS brick (which wraps vasp.v2.bands for GGA DOS), this brick
wraps vasp.v2.hybrid_bands which adds band path segments as zero-weighted
k-points to SCF calculations. This is necessary for hybrid functionals
(e.g. HSE06) where non-SCF methods don't work.

Note on DOS support:
    VaspHybridBandsWorkChain does NOT run a separate DOS calculation.
    Its outline only performs split SCF+bands calculations (run_scf_multi).
    The 'dos' input namespace is inherited from the parent VaspBandsWorkChain
    but is never processed. DOS inputs are accepted silently but ignored.

    To get DOS with hybrid functionals, run a separate 'vasp' stage with
    ISMEAR=-5 and hybrid INCAR settings after the hybrid_bands stage.

    SCF misc/remote/retrieved outputs are also NOT directly exposed by the
    workchain, but can be extracted from the split calculation children
    via link traversal (handled by get_stage_results fallback).
"""

from typing import Dict, Set, Any

from aiida import orm
from aiida.common.links import LinkType
from aiida.plugins import WorkflowFactory
from aiida_workgraph import task, WorkGraph
from .connections import HYBRID_BANDS_PORTS as PORTS  # noqa: F401
from ..retrieve_defaults import build_vasp_retrieve
from ..types import StageContext, StageTasksResult, HybridBandsResults


def validate_stage(stage: Dict[str, Any], stage_names: Set[str]) -> None:
    """Validate a hybrid_bands stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'scf_incar' not in stage:
        raise ValueError(f"Stage '{name}': hybrid_bands stages require 'scf_incar'")

    # Check that hybrid settings are present
    scf_incar = stage['scf_incar']
    if not scf_incar.get('lhfcalc', False):
        import warnings
        warnings.warn(
            f"Stage '{name}': scf_incar does not have 'lhfcalc': True. "
            f"hybrid_bands is intended for hybrid functional calculations."
        )

    has_structure = 'structure' in stage
    has_structure_from = 'structure_from' in stage

    if has_structure and has_structure_from:
        raise ValueError(
            f"Stage '{name}': hybrid_bands stages accept either 'structure' or "
            f"'structure_from', not both"
        )
    if not has_structure and not has_structure_from:
        raise ValueError(
            f"Stage '{name}': hybrid_bands stages require a structure source "
            f"('structure' or 'structure_from')"
        )

    if has_structure_from:
        structure_from = stage['structure_from']
        if structure_from not in stage_names:
            raise ValueError(
                f"Stage '{name}' structure_from='{structure_from}' must reference "
                f"a previous stage name"
            )


def create_stage_tasks(
    wg: WorkGraph,
    stage: Dict[str, Any],
    stage_name: str,
    context: StageContext
) -> StageTasksResult:
    """Create hybrid bands stage tasks in the WorkGraph.

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

    # Resolve structure either from explicit stage input or from a previous stage.
    if 'structure' in stage:
        explicit = stage['structure']
        input_structure = orm.load_node(explicit) if isinstance(explicit, int) else explicit
    else:
        structure_from = stage['structure_from']
        input_structure = resolve_structure_from(structure_from, context)

    # Get VaspHybridBandsWorkChain and wrap as task
    HybridBandsWorkChain = WorkflowFactory('vasp.v2.hybrid_bands')
    HybridBandsTask = task(HybridBandsWorkChain)

    # Handle SCF k-points: explicit mesh or spacing
    scf_kpoints_mesh = stage.get('kpoints', None)
    scf_kpoints_spacing = stage.get('kpoints_spacing', base_kpoints_spacing)

    # Prepare SCF INCAR
    scf_incar = dict(stage['scf_incar'])
    scf_incar.update({
        'nsw': 0,
        'ibrion': -1,
    })

    # Files to retrieve from SCF
    scf_retrieve = build_vasp_retrieve(stage.get('retrieve', None))

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

    # Build band_settings with ALL required keys.
    # VaspHybridBandsWorkChain (and parent VaspBandsWorkChain) accesses many
    # keys via __getitem__ (e.g. band_settings['only_dos']), so ALL keys
    # defined in BandOptions must be present — defaults are NOT auto-filled.
    dos_kpoints_spacing = stage.get(
        'dos_kpoints_spacing', scf_kpoints_spacing * 0.8
    )
    band_settings_dict = {
        'only_dos': False,
        'run_dos': False,  # Hybrid workchain ignores this; DOS never runs
        'band_mode': 'seekpath-aiida',
        'band_kpoints_distance': 0.025,
        'symprec': 1e-4,
        'line_density': 20,
        'dos_kpoints_distance': float(dos_kpoints_spacing),
        'kpoints_per_split': 25,
        'hybrid_reuse_wavecar': False,  # Must be False when relax is external
        'additional_band_analysis_parameters': {},
    }

    # Merge user-provided band_settings overrides
    user_band_settings = stage.get('band_settings', {})
    band_settings_dict.update(user_band_settings)

    # Prepare task kwargs
    # NOTE: We intentionally do NOT pass a 'dos' namespace because
    # VaspHybridBandsWorkChain's outline omits DOS execution steps entirely.
    # The 'dos' namespace is inherited from parent but never processed.
    task_kwargs = {
        'structure': input_structure,
        'scf': scf_input,
        'band_settings': orm.Dict(band_settings_dict),
        'clean_children_workdir': orm.Str('all') if clean_workdir else None,
    }

    # Add HybridBandsWorkChain task
    hybrid_bands_task = wg.add_task(
        HybridBandsTask,
        name=f'hybrid_bands_{stage_name}',
        **task_kwargs,
    )

    return {
        'hybrid_bands_task': hybrid_bands_task,
        'structure': input_structure,
    }


def expose_stage_outputs(
    wg: WorkGraph,
    stage_name: str,
    stage_tasks_result: StageTasksResult,
    namespace_map: Dict[str, str] = None
) -> None:
    """Expose hybrid bands stage outputs on the WorkGraph.

    VaspHybridBandsWorkChain only produces band_structure,
    primitive_structure, and seekpath_parameters as direct outputs.
    SCF and DOS outputs are NOT produced by this workchain, but
    get_stage_results() can extract them via link traversal.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string.
    """
    hb_task = stage_tasks_result['hybrid_bands_task']

    if namespace_map is not None:
        scf_ns = namespace_map['scf']

        # Band structure outputs (the only direct outputs)
        try:
            setattr(wg.outputs, f'{scf_ns}.bands.band_structure', hb_task.outputs.band_structure)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{scf_ns}.bands.seekpath_parameters', hb_task.outputs.seekpath_parameters)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{scf_ns}.bands.primitive_structure', hb_task.outputs.primitive_structure)
        except AttributeError:
            pass
    else:
        # Flat naming fallback — only band structure outputs
        try:
            setattr(wg.outputs, f'{stage_name}_band_structure', hb_task.outputs.band_structure)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{stage_name}_seekpath_parameters', hb_task.outputs.seekpath_parameters)
        except AttributeError:
            pass
        try:
            setattr(wg.outputs, f'{stage_name}_primitive_structure', hb_task.outputs.primitive_structure)
        except AttributeError:
            pass


def get_stage_results(
    wg_node: Any,
    wg_pk: int,
    stage_name: str,
    namespace_map: Dict[str, str] = None
) -> HybridBandsResults:
    """Extract results from a hybrid bands stage in a sequential workflow.

    VaspHybridBandsWorkChain only directly exposes band_structure,
    seekpath_parameters, and primitive_structure. SCF misc and remote
    data are extracted from the split calculation children via link
    traversal. DOS outputs are not available (workchain doesn't run DOS).

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the hybrid bands stage.
        namespace_map: Dict mapping output group to namespace string.

    Returns:
        Dict with keys: energy, scf_misc, band_structure,
        seekpath_parameters, primitive_structure, scf_remote,
        pk, stage, type.
    """
    from ..results import _extract_energy_from_misc

    result = {
        'energy': None,
        'scf_misc': None,
        'scf_remote': None,
        'band_structure': None,
        'seekpath_parameters': None,
        'primitive_structure': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'hybrid_bands',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            scf_ns = namespace_map['scf']

            # Band structure outputs (from workchain direct outputs)
            stage_scf = getattr(outputs, scf_ns, None)
            bands_outputs = getattr(stage_scf, 'bands', None) if stage_scf is not None else None
            if bands_outputs is not None:
                if hasattr(bands_outputs, 'band_structure'):
                    result['band_structure'] = bands_outputs.band_structure
                if hasattr(bands_outputs, 'seekpath_parameters'):
                    result['seekpath_parameters'] = bands_outputs.seekpath_parameters
                if hasattr(bands_outputs, 'primitive_structure'):
                    result['primitive_structure'] = bands_outputs.primitive_structure
        else:
            # Flat naming fallback
            bs_attr = f'{stage_name}_band_structure'
            if hasattr(outputs, bs_attr):
                result['band_structure'] = getattr(outputs, bs_attr)

            sp_attr = f'{stage_name}_seekpath_parameters'
            if hasattr(outputs, sp_attr):
                result['seekpath_parameters'] = getattr(outputs, sp_attr)

            ps_attr = f'{stage_name}_primitive_structure'
            if hasattr(outputs, ps_attr):
                result['primitive_structure'] = getattr(outputs, ps_attr)

    # Always traverse links for SCF misc/remote (not directly exposed)
    _extract_from_hybrid_bands_workchain(wg_node, stage_name, result)

    # Extract energy from scf_misc
    if result['energy'] is None and result['scf_misc'] is not None:
        result['energy'] = _extract_energy_from_misc(result['scf_misc'])

    return result


def _extract_from_hybrid_bands_workchain(wg_node: Any, stage_name: str, result: Dict[str, Any]) -> None:
    """Extract hybrid bands stage results by traversing to HybridBandsWorkChain.

    The HybridBandsWorkChain doesn't expose SCF misc/remote as direct outputs.
    We traverse its children to find the split band calculation workchains
    (labeled 'bandstructure_split_NNN') and extract misc from the first one.

    Args:
        wg_node: The WorkGraph node.
        stage_name: Name of the hybrid bands stage.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    hb_task_name = f'hybrid_bands_{stage_name}'

    called = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called.all():
        child_node = link.node
        link_label = link.link_label

        if hb_task_name in link_label or link_label == hb_task_name:
            # Extract direct outputs from the HybridBandsWorkChain
            if hasattr(child_node, 'outputs'):
                outputs = child_node.outputs
                if result['band_structure'] is None and hasattr(outputs, 'band_structure'):
                    result['band_structure'] = outputs.band_structure
                if result.get('seekpath_parameters') is None and hasattr(outputs, 'seekpath_parameters'):
                    result['seekpath_parameters'] = outputs.seekpath_parameters
                if result.get('primitive_structure') is None and hasattr(outputs, 'primitive_structure'):
                    result['primitive_structure'] = outputs.primitive_structure

            # Traverse children for SCF misc/remote
            if hasattr(child_node, 'base'):
                _extract_from_hybrid_bands_children(child_node, result)


def _extract_from_hybrid_bands_children(hb_node: Any, result: Dict[str, Any]) -> None:
    """Extract outputs from HybridBandsWorkChain's child workchains.

    The hybrid workchain launches children with link labels:
      - 'relax' (optional relaxation)
      - 'scf_for_kpoints' (optional, if k-points need to be determined)
      - 'bandstructure_split_000', 'bandstructure_split_001', ... (the actual SCF+bands calcs)

    Each split calculation is a full SCF with zero-weighted band k-points,
    so its 'misc' output contains valid SCF energy and convergence info.
    We use the first split's outputs for SCF results.

    Args:
        hb_node: The HybridBandsWorkChain node.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(hb_node, 'base'):
        return

    called = hb_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)

    # Collect split calculations sorted by index
    split_nodes = []
    for link in called.all():
        child_node = link.node
        link_label = link.link_label.lower()

        if 'bandstructure_split' in link_label:
            split_nodes.append(child_node)
        elif 'scf_for_kpoints' in link_label:
            # The SCF-for-kpoints calculation also has misc
            if result['scf_misc'] is None and hasattr(child_node, 'outputs'):
                outputs = child_node.outputs
                if hasattr(outputs, 'misc') and hasattr(outputs.misc, 'get_dict'):
                    result['scf_misc'] = outputs.misc.get_dict()
                if result['scf_remote'] is None and hasattr(outputs, 'remote_folder'):
                    result['scf_remote'] = outputs.remote_folder

    # Use the first split calculation for SCF misc/remote
    # All splits contain full SCF k-points so energy is consistent
    if split_nodes and result['scf_misc'] is None:
        for node in split_nodes:
            if hasattr(node, 'outputs'):
                outputs = node.outputs
                if hasattr(outputs, 'misc') and hasattr(outputs.misc, 'get_dict'):
                    result['scf_misc'] = outputs.misc.get_dict()
                if result['scf_remote'] is None and hasattr(outputs, 'remote_folder'):
                    result['scf_remote'] = outputs.remote_folder
                break  # First successful split is enough


def print_stage_results(index: int, stage_name: str, stage_result: Dict[str, Any]) -> None:
    """Print formatted results for a hybrid bands stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="hybrid_bands")

    if stage_result['energy'] is not None:
        console.print(f"      [bold]SCF Energy:[/bold] [energy]{stage_result['energy']:.6f}[/energy] eV")

    if stage_result['scf_misc'] is not None:
        scf_misc = stage_result['scf_misc']
        run_status = scf_misc.get('run_status', {})
        converged = run_status.get('electronic_converged', 'N/A')
        console.print(f"      [bold]SCF converged:[/bold] {converged}")

        band_props = scf_misc.get('band_properties', {})
        band_gap = band_props.get('band_gap', None)
        if band_gap is not None:
            is_direct = band_props.get('is_direct_gap', False)
            gap_type = "direct" if is_direct else "indirect"
            console.print(f"      [bold]Band gap:[/bold] [energy]{band_gap:.4f}[/energy] eV ({gap_type})")
        fermi = scf_misc.get('fermi_level', None)
        if fermi is not None:
            console.print(f"      [bold]Fermi level:[/bold] [energy]{fermi:.4f}[/energy] eV")

    if stage_result['band_structure'] is not None:
        console.print(f"      [bold]Band structure:[/bold] PK [pk]{stage_result['band_structure'].pk}[/pk]")

    if stage_result['scf_remote'] is not None:
        console.print(f"      [bold]SCF Remote folder:[/bold] PK [pk]{stage_result['scf_remote'].pk}[/pk]")
