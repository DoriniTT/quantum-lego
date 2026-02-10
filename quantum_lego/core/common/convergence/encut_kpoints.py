"""ENCUT and k-points convergence workflow.

This module provides workflows for testing convergence of ENCUT (plane-wave cutoff)
and k-points spacing parameters in VASP calculations.
"""

from __future__ import annotations

import logging
import typing as t

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task, get_current_graph

from .config import DEFAULT_CONV_SETTINGS
from .tasks import (
    analyze_cutoff_convergence,
    analyze_kpoints_convergence,
    extract_recommended_parameters,
    gather_cutoff_results,
    gather_kpoints_results,
)
from ..utils import (
    deep_merge_dicts,
    get_vasp_parser_settings,
    extract_max_jobs_value,
)

logger = logging.getLogger(__name__)


def _build_cutoff_list(settings: dict) -> list:
    """Build list of ENCUT values to scan.

    Replicates the logic from VaspConvergenceWorkChain.setup() so we can
    replace that workchain with individual VaspTasks.

    Args:
        settings: Convergence settings dict with cutoff_start/stop/step.

    Returns:
        List of ENCUT values, or empty list if start >= stop.
    """
    start = settings['cutoff_start']
    stop = settings['cutoff_stop']
    step = settings['cutoff_step']

    if start >= stop:
        return []

    cutoff_list = [start]
    cut = start
    while True:
        cut += step
        if cut < stop:
            cutoff_list.append(cut)
        else:
            cutoff_list.append(stop)
            break

    return cutoff_list


def _build_kspacing_list(settings: dict) -> list:
    """Build list of k-spacing values to scan.

    Replicates the logic from VaspConvergenceWorkChain.setup() with the
    corrected sign convention (step is positive, subtracted internally).

    Args:
        settings: Convergence settings dict with kspacing_start/stop/step.

    Returns:
        List of k-spacing values (descending, coarse to fine),
        or empty list if start <= stop.
    """
    start = settings['kspacing_start']
    stop = settings['kspacing_stop']
    step = settings['kspacing_step']

    if start <= stop:
        return []

    kspacing_list = [start]
    spacing = start
    while True:
        spacing -= step  # step is positive; subtracting moves toward finer grid
        if spacing > stop:
            kspacing_list.append(round(spacing, 6))
        else:
            kspacing_list.append(stop)
            break

    return kspacing_list


@task.graph(outputs=['cutoff_conv_data', 'kpoints_conv_data'])
def convergence_scan(
    structure: orm.StructureData,
    code_pk: int,
    base_incar: dict,
    options: dict,
    potential_family: str,
    potential_mapping: dict,
    conv_settings: dict,
    clean_workdir: bool = True,
    max_number_jobs: int = None,
):
    """Run ENCUT and k-points convergence scans with concurrency control.

    Replaces VaspConvergenceWorkChain with individual VaspTasks that respect
    max_number_jobs for concurrency control. Produces the same outputs:
    cutoff_conv_data and kpoints_conv_data.

    Args:
        structure: Input structure.
        code_pk: PK of AiiDA VASP code.
        base_incar: Base INCAR parameters dict.
        options: Scheduler options dict.
        potential_family: Pseudopotential family name.
        potential_mapping: Element to potential mapping dict.
        conv_settings: Convergence scan settings dict.
        clean_workdir: Clean work directories after completion.
        max_number_jobs: Maximum concurrent VASP calculations.

    Returns:
        Dict with cutoff_conv_data and kpoints_conv_data.
    """
    if max_number_jobs is not None:
        wg = get_current_graph()
        wg.max_number_jobs = extract_max_jobs_value(max_number_jobs)

    settings_dict = (
        conv_settings if isinstance(conv_settings, dict)
        else conv_settings.get_dict()
    )
    cutoff_list = _build_cutoff_list(settings_dict)
    kspacing_list = _build_kspacing_list(settings_dict)

    code = orm.load_node(code_pk)
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)
    parser_settings = orm.Dict(dict=get_vasp_parser_settings(add_energy=True))

    # ── Cutoff convergence scans ──────────────────────────────────────
    cutoff_kwargs = {'cutoff_values': orm.List(list=cutoff_list)}
    kspacing_for_cutconv = settings_dict.get('kspacing_cutconv', 0.03)

    for i, cutoff in enumerate(cutoff_list):
        incar = dict(base_incar)
        incar['encut'] = cutoff
        vasp = VaspTask(
            structure=structure,
            code=code,
            parameters={'incar': incar},
            options=dict(options),
            kpoints_spacing=kspacing_for_cutconv,
            potential_family=potential_family,
            potential_mapping=orm.Dict(dict=dict(potential_mapping)),
            clean_workdir=clean_workdir,
            settings=parser_settings,
        )
        cutoff_kwargs[f'c_{i}'] = vasp.misc

    cutoff_conv = gather_cutoff_results(**cutoff_kwargs)

    # ── K-spacing convergence scans ───────────────────────────────────
    kpoints_kwargs = {'kspacing_values': orm.List(list=kspacing_list)}
    cutoff_for_kconv = settings_dict.get('cutoff_kconv', 520)
    k_incar = dict(base_incar)
    k_incar['encut'] = cutoff_for_kconv

    for i, ksp in enumerate(kspacing_list):
        vasp = VaspTask(
            structure=structure,
            code=code,
            parameters={'incar': k_incar},
            options=dict(options),
            kpoints_spacing=ksp,
            potential_family=potential_family,
            potential_mapping=orm.Dict(dict=dict(potential_mapping)),
            clean_workdir=clean_workdir,
            settings=parser_settings,
        )
        kpoints_kwargs[f'k_{i}'] = vasp.misc

    kpoints_conv = gather_kpoints_results(**kpoints_kwargs)

    return {
        'cutoff_conv_data': cutoff_conv.result,
        'kpoints_conv_data': kpoints_conv.result,
    }


def _prepare_convergence_inputs(
    builder_inputs: dict,
    code: orm.InstalledCode,
) -> dict:
    """
    Prepare builder inputs for the vasp.v2.converge workchain.

    The converge workchain expects VASP inputs under a 'vasp' namespace.

    Args:
        builder_inputs: dict with VASP builder parameters
        code: The VASP code node

    Returns:
        dict with 'vasp' namespace containing AiiDA-compatible types
    """
    vasp_inputs = {}

    # Add code
    vasp_inputs['code'] = code

    # Convert parameters dict to orm.Dict
    if 'parameters' in builder_inputs:
        if isinstance(builder_inputs['parameters'], dict):
            vasp_inputs['parameters'] = orm.Dict(dict=builder_inputs['parameters'])
        else:
            vasp_inputs['parameters'] = builder_inputs['parameters']

    # Convert options dict to orm.Dict
    if 'options' in builder_inputs:
        if isinstance(builder_inputs['options'], dict):
            vasp_inputs['options'] = orm.Dict(dict=builder_inputs['options'])
        else:
            vasp_inputs['options'] = builder_inputs['options']

    # Convert potential_mapping dict to orm.Dict
    if 'potential_mapping' in builder_inputs:
        if isinstance(builder_inputs['potential_mapping'], dict):
            vasp_inputs['potential_mapping'] = orm.Dict(dict=builder_inputs['potential_mapping'])
        else:
            vasp_inputs['potential_mapping'] = builder_inputs['potential_mapping']

    # Convert settings dict to orm.Dict if present
    if 'settings' in builder_inputs:
        if isinstance(builder_inputs['settings'], dict):
            vasp_inputs['settings'] = orm.Dict(dict=builder_inputs['settings'])
        else:
            vasp_inputs['settings'] = builder_inputs['settings']

    # Handle kpoints_spacing - ensure it's a float
    if 'kpoints_spacing' in builder_inputs:
        kps = builder_inputs['kpoints_spacing']
        if isinstance(kps, (int, float)):
            vasp_inputs['kpoints_spacing'] = float(kps)
        else:
            vasp_inputs['kpoints_spacing'] = kps

    # Copy string/bool values directly
    if 'potential_family' in builder_inputs:
        vasp_inputs['potential_family'] = builder_inputs['potential_family']
    if 'clean_workdir' in builder_inputs:
        vasp_inputs['clean_workdir'] = builder_inputs['clean_workdir']

    return {'vasp': vasp_inputs}


def build_convergence_workgraph(
    structure: orm.StructureData,
    code_label: str,
    builder_inputs: dict,
    conv_settings: dict = None,
    convergence_threshold: float = 0.001,
    max_concurrent_jobs: int = None,
    name: str = 'convergence_test',
) -> WorkGraph:
    """
    Build a WorkGraph for VASP convergence testing.

    Uses individual VaspTasks with concurrency control via max_number_jobs,
    replacing VaspConvergenceWorkChain which launched all calculations
    simultaneously without any concurrency limit.

    Args:
        structure: StructureData to test convergence on
        code_label: str, VASP code label (e.g., 'VASP-6.5.1@cluster02')
        builder_inputs: dict with base VASP builder parameters:
            - parameters: Dict with nested 'incar' dict
            - options: Dict with resources, queue, etc.
            - kpoints_spacing: float (starting value, will be overridden in scan)
            - potential_family: str
            - potential_mapping: dict
            - clean_workdir: bool
            - settings: Dict (optional)
        conv_settings: dict with convergence scan ranges:
            - cutoff_start: int (default: 200 eV)
            - cutoff_stop: int (default: 800 eV)
            - cutoff_step: int (default: 50 eV)
            - kspacing_start: float (default: 0.08 A^-1)
            - kspacing_stop: float (default: 0.02 A^-1)
            - kspacing_step: float (default: 0.01 A^-1)
            - cutoff_kconv: int (cutoff for k-points convergence, default: 520 eV)
            - kspacing_cutconv: float (k-spacing for cutoff convergence, default: 0.03 A^-1)
        convergence_threshold: float, energy threshold in eV/atom for determining
            convergence (default: 0.001 = 1 meV/atom)
        max_concurrent_jobs: int, maximum number of parallel VASP jobs
            (default: None = unlimited)
        name: str, WorkGraph name

    Returns:
        WorkGraph ready to submit

    Example:
        >>> from quantum_lego.core.common.convergence import build_convergence_workgraph
        >>>
        >>> wg = build_convergence_workgraph(
        ...     structure=my_structure,
        ...     code_label='VASP-6.5.1@cluster02',
        ...     builder_inputs={
        ...         'parameters': {'incar': {'PREC': 'Accurate', 'ISMEAR': 0}},
        ...         'options': {'resources': {'num_machines': 1, 'num_cores_per_machine': 24}},
        ...         'kpoints_spacing': 0.05,
        ...         'potential_family': 'PBE.54',
        ...         'potential_mapping': {'Ag': 'Ag', 'O': 'O'},
        ...     },
        ...     conv_settings={
        ...         'cutoff_start': 300,
        ...         'cutoff_stop': 700,
        ...         'cutoff_step': 50,
        ...     },
        ...     convergence_threshold=0.001,  # 1 meV/atom
        ...     max_concurrent_jobs=4,
        ... )
        >>> wg.submit()
    """
    logger.info(f"Building convergence WorkGraph: {name}")

    # Load code
    code = orm.load_code(code_label)
    logger.info(f"  Using code: {code_label}")

    # Merge conv_settings with defaults
    if conv_settings is not None:
        merged_settings = deep_merge_dicts(DEFAULT_CONV_SETTINGS, conv_settings)
    else:
        merged_settings = DEFAULT_CONV_SETTINGS.copy()

    logger.info(f"  Convergence settings: {merged_settings}")

    # Extract INCAR from builder_inputs
    params = builder_inputs.get('parameters', {})
    base_incar = params.get('incar', {}) if isinstance(params, dict) else {}

    # Build WorkGraph
    wg = WorkGraph(name=name)

    # Add convergence scan task (uses individual VaspTasks with concurrency control)
    converge_task = wg.add_task(
        convergence_scan,
        name='convergence_scan',
        structure=structure,
        code_pk=code.pk,
        base_incar=base_incar,
        options=builder_inputs.get('options', {}),
        potential_family=builder_inputs.get('potential_family', 'PBE'),
        potential_mapping=builder_inputs.get('potential_mapping', {}),
        conv_settings=merged_settings,
        clean_workdir=builder_inputs.get('clean_workdir', True),
        max_number_jobs=max_concurrent_jobs,
    )

    # Store threshold for analysis tasks
    threshold_node = orm.Float(convergence_threshold)

    # Add analysis task for cutoff convergence
    cutoff_analysis = wg.add_task(
        analyze_cutoff_convergence,
        name='analyze_cutoff',
        conv_data=converge_task.outputs.cutoff_conv_data,
        threshold=threshold_node,
        structure=structure,
    )

    # Add analysis task for k-points convergence
    kpoints_analysis = wg.add_task(
        analyze_kpoints_convergence,
        name='analyze_kpoints',
        conv_data=converge_task.outputs.kpoints_conv_data,
        threshold=threshold_node,
        structure=structure,
    )

    # Add final recommendation extraction task
    recommendation_task = wg.add_task(
        extract_recommended_parameters,
        name='extract_recommendations',
        cutoff_analysis=cutoff_analysis.outputs.result,
        kpoints_analysis=kpoints_analysis.outputs.result,
        threshold=threshold_node,
    )

    # Expose WorkGraph outputs
    wg.add_output(
        'any', 'cutoff_conv_data',
        from_socket=converge_task.outputs.cutoff_conv_data
    )
    wg.add_output(
        'any', 'kpoints_conv_data',
        from_socket=converge_task.outputs.kpoints_conv_data
    )
    wg.add_output(
        'any', 'cutoff_analysis',
        from_socket=cutoff_analysis.outputs.result
    )
    wg.add_output(
        'any', 'kpoints_analysis',
        from_socket=kpoints_analysis.outputs.result
    )
    wg.add_output(
        'any', 'recommendations',
        from_socket=recommendation_task.outputs.result
    )

    logger.info(f"  Threshold: {convergence_threshold * 1000:.1f} meV/atom")
    logger.info("  WorkGraph built successfully")

    return wg


def get_convergence_results(workgraph) -> dict:
    """
    Extract results from completed convergence WorkGraph.

    Args:
        workgraph: Completed WorkGraph from build_convergence_workgraph

    Returns:
        dict with:
            - cutoff_conv_data: dict with raw cutoff convergence data
            - kpoints_conv_data: dict with raw k-points convergence data
            - cutoff_analysis: dict with detailed cutoff analysis
            - kpoints_analysis: dict with detailed k-points analysis
            - recommended_cutoff: int, recommended ENCUT in eV (or None if not converged)
            - recommended_kspacing: float, recommended k-spacing in A^-1 (or None)
            - convergence_summary: dict with analysis summary

    Example:
        >>> results = get_convergence_results(wg)
        >>> print(f"Recommended ENCUT: {results['recommended_cutoff']} eV")
        >>> print(f"Recommended k-spacing: {results['recommended_kspacing']} A^-1")
        >>> print(results['convergence_summary']['summary'])
    """
    results = {}

    # Helper to get dict from socket output
    def _get_dict(socket):
        node = socket.value
        return node.get_dict() if node else None

    # Extract raw convergence data
    if hasattr(workgraph.outputs, 'cutoff_conv_data'):
        results['cutoff_conv_data'] = _get_dict(workgraph.outputs.cutoff_conv_data)
    else:
        results['cutoff_conv_data'] = None

    if hasattr(workgraph.outputs, 'kpoints_conv_data'):
        results['kpoints_conv_data'] = _get_dict(workgraph.outputs.kpoints_conv_data)
    else:
        results['kpoints_conv_data'] = None

    # Extract analysis results
    if hasattr(workgraph.outputs, 'cutoff_analysis'):
        results['cutoff_analysis'] = _get_dict(workgraph.outputs.cutoff_analysis)
    else:
        results['cutoff_analysis'] = None

    if hasattr(workgraph.outputs, 'kpoints_analysis'):
        results['kpoints_analysis'] = _get_dict(workgraph.outputs.kpoints_analysis)
    else:
        results['kpoints_analysis'] = None

    # Extract recommendations
    if hasattr(workgraph.outputs, 'recommendations'):
        recommendations = _get_dict(workgraph.outputs.recommendations)
        results['recommended_cutoff'] = recommendations.get('recommended_cutoff')
        results['recommended_kspacing'] = recommendations.get('recommended_kspacing')
        results['convergence_summary'] = {
            'threshold_used': recommendations.get('threshold_used'),
            'cutoff_converged_at': recommendations.get('converged_cutoff_raw'),
            'kspacing_converged_at': recommendations.get('converged_kspacing_raw'),
            'cutoff_converged': recommendations.get('cutoff_converged'),
            'kpoints_converged': recommendations.get('kpoints_converged'),
            'summary': recommendations.get('summary'),
        }
    else:
        results['recommended_cutoff'] = None
        results['recommended_kspacing'] = None
        results['convergence_summary'] = None

    return results


__all__ = [
    'build_convergence_workgraph',
    'get_convergence_results',
    'convergence_scan',
]
