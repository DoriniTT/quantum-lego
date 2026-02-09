"""WorkGraph builders for VASP convergence testing.

This module provides workflows for:
1. ENCUT and k-points convergence testing (build_convergence_workgraph)
2. Slab thickness convergence testing (build_thickness_convergence_workgraph)
"""

from __future__ import annotations

import logging
import os
import typing as t

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task, dynamic, namespace, get_current_graph
from ase.io import read

from .tasks import (
    analyze_cutoff_convergence,
    analyze_kpoints_convergence,
    extract_recommended_parameters,
    gather_cutoff_results,
    gather_kpoints_results,
)
from .slabs import generate_thickness_series
from ..utils import deep_merge_dicts, get_vasp_parser_settings, extract_max_jobs_value
from ..constants import EV_PER_ANGSTROM2_TO_J_PER_M2

logger = logging.getLogger(__name__)


# Default convergence settings
DEFAULT_CONV_SETTINGS = {
    'cutoff_start': 200,
    'cutoff_stop': 800,
    'cutoff_step': 50,
    'kspacing_start': 0.08,
    'kspacing_stop': 0.02,
    'kspacing_step': 0.01,
    'cutoff_kconv': 520,
    'kspacing_cutconv': 0.03,
}


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


# =============================================================================
# THICKNESS CONVERGENCE
# =============================================================================

def _load_structure_from_file(filepath: str) -> orm.StructureData:
    """Load structure from a file using ASE."""
    atoms = read(filepath)
    return orm.StructureData(ase=atoms)


def _get_thickness_settings():
    """Parser settings for thickness convergence calculations."""
    return get_vasp_parser_settings(add_energy=True)


@task.calcfunction
def extract_total_energy(misc: orm.Dict) -> orm.Float:
    """
    Extract total energy from VASP misc output.

    Args:
        misc: Dictionary containing energy outputs from VASP

    Returns:
        Total energy as Float
    """
    energy_dict = misc.get_dict()
    if 'total_energies' in energy_dict:
        energy_dict = energy_dict['total_energies']

    for key in ('energy_extrapolated', 'energy_no_entropy', 'energy'):
        if key in energy_dict:
            return orm.Float(energy_dict[key])

    available = ', '.join(sorted(energy_dict.keys()))
    raise ValueError(f'Unable to find total energy. Available keys: {available}')


@task.graph
def relax_thickness_series(
    slabs: t.Annotated[dict[str, orm.StructureData], dynamic(orm.StructureData)],
    code_pk: int,
    potential_family: str,
    potential_mapping: dict,
    parameters: dict,
    options: dict,
    kpoints_spacing: float = None,
    clean_workdir: bool = True,
    max_number_jobs: int = None,
) -> t.Annotated[dict, namespace(
    relaxed_structures=dynamic(orm.StructureData),
    energies=dynamic(orm.Float),
)]:
    """
    Relax all slabs in the thickness series with concurrency control.

    Uses scatter-gather pattern for VASP relaxations with max_number_jobs control.

    Args:
        slabs: Dictionary of slab structures keyed by layer count
        code_pk: PK of AiiDA code for VASP (as int)
        potential_family: Pseudopotential family
        potential_mapping: Element to potential mapping
        parameters: VASP INCAR parameters
        options: Scheduler options
        kpoints_spacing: K-points spacing
        clean_workdir: Whether to clean remote directories
        max_number_jobs: Maximum number of concurrent VASP calculations

    Returns:
        Dictionary with relaxed_structures and energies namespaces
    """
    # Set max_number_jobs on this workgraph to control concurrency
    if max_number_jobs is not None:
        wg = get_current_graph()
        max_jobs_value = extract_max_jobs_value(max_number_jobs)
        wg.max_number_jobs = max_jobs_value

    # Get VASP workchain
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Load code from PK
    code = orm.load_node(code_pk)

    relaxed: dict[str, orm.StructureData] = {}
    energies_ns: dict[str, orm.Float] = {}

    for label, structure in slabs.items():
        vasp_inputs = {
            'structure': structure,
            'code': code,
            'parameters': {'incar': dict(parameters)},
            'options': dict(options),
            'potential_family': potential_family,
            'potential_mapping': orm.Dict(dict=dict(potential_mapping)),
            'clean_workdir': clean_workdir,
            'settings': orm.Dict(dict=_get_thickness_settings()),
        }
        if kpoints_spacing is not None:
            kpts_val = kpoints_spacing.value if hasattr(kpoints_spacing, 'value') else kpoints_spacing
            vasp_inputs['kpoints_spacing'] = kpts_val

        relaxation = VaspTask(**vasp_inputs)
        relaxed[label] = relaxation.structure
        energies_ns[label] = extract_total_energy(misc=relaxation.misc).result

    return {
        'relaxed_structures': relaxed,
        'energies': energies_ns,
    }


@task.calcfunction
def calculate_surface_energy(
    bulk_structure: orm.StructureData,
    bulk_energy: orm.Float,
    slab_structure: orm.StructureData,
    slab_energy: orm.Float,
    n_layers: orm.Int,
) -> orm.Dict:
    """
    Calculate surface energy for a single slab.

    Uses the formula: gamma = (E_slab - N_slab * E_bulk/atom) / (2 * Area)

    Args:
        bulk_structure: Relaxed bulk structure
        bulk_energy: Bulk total energy
        slab_structure: Relaxed slab structure
        slab_energy: Slab total energy
        n_layers: Number of layers in this slab

    Returns:
        Dict with surface energy data
    """
    import numpy as np

    # Get bulk info
    bulk_ase = bulk_structure.get_ase()
    n_bulk = len(bulk_ase)
    E_bulk_per_atom = bulk_energy.value / n_bulk

    # Get slab info
    slab_ase = slab_structure.get_ase()
    n_slab = len(slab_ase)

    # Calculate surface area
    cell = slab_ase.get_cell()
    a_vec = cell[0]
    b_vec = cell[1]
    cross = np.cross(a_vec, b_vec)
    area_A2 = float(np.linalg.norm(cross))

    # Calculate surface energy
    gamma_eV_A2 = (slab_energy.value - n_slab * E_bulk_per_atom) / (2 * area_A2)
    gamma_J_m2 = gamma_eV_A2 * EV_PER_ANGSTROM2_TO_J_PER_M2

    return orm.Dict(dict={
        'n_layers': n_layers.value,
        'gamma_eV_A2': float(gamma_eV_A2),
        'gamma_J_m2': float(gamma_J_m2),
        'area_A2': float(area_A2),
        'E_slab_eV': float(slab_energy.value),
        'E_bulk_per_atom_eV': float(E_bulk_per_atom),
        'N_slab': int(n_slab),
        'N_bulk': int(n_bulk),
    })


@task.graph
def compute_surface_energies(
    slabs: t.Annotated[dict[str, orm.StructureData], dynamic(orm.StructureData)],
    energies: t.Annotated[dict[str, orm.Float], dynamic(orm.Float)],
    bulk_structure: orm.StructureData,
    bulk_energy: orm.Float,
) -> t.Annotated[dict, namespace(surface_energies=dynamic(orm.Dict))]:
    """
    Compute surface energies for all slabs in the thickness series.

    Args:
        slabs: Dictionary of relaxed slab structures
        energies: Dictionary of slab energies
        bulk_structure: Relaxed bulk structure
        bulk_energy: Bulk total energy

    Returns:
        Dict with surface_energies namespace
    """
    surface_results = {}

    for key, slab_structure in slabs.items():
        slab_energy = energies[key]
        # Extract layer count from key (e.g., 'layers_5' -> 5)
        n_layers = int(key.split('_')[1])

        surface_data = calculate_surface_energy(
            bulk_structure=bulk_structure,
            bulk_energy=bulk_energy,
            slab_structure=slab_structure,
            slab_energy=slab_energy,
            n_layers=orm.Int(n_layers),
        ).result

        surface_results[key] = surface_data

    return {'surface_energies': surface_results}


@task.calcfunction
def analyze_thickness_convergence(
    miller_indices: orm.List,
    convergence_threshold: orm.Float,
    **kwargs
) -> orm.Dict:
    """
    Analyze thickness convergence from surface energy results.

    Convergence criterion: |gamma(N) - gamma(N-1)| < threshold

    Args:
        miller_indices: Miller indices used
        convergence_threshold: Energy difference threshold in J/m^2 (default: 0.01)
        **kwargs: Individual surface energy Dict nodes keyed by layer count

    Returns:
        Combined Dict with all results and convergence analysis
    """
    threshold = convergence_threshold.value

    results = {}
    thicknesses = []
    energies_list = []

    for key, val in kwargs.items():
        if isinstance(val, orm.Dict):
            data = val.get_dict()
        else:
            data = val

        results[key] = data
        thicknesses.append(data['n_layers'])
        energies_list.append(data['gamma_J_m2'])

    # Sort by thickness
    sorted_indices = sorted(range(len(thicknesses)), key=lambda i: thicknesses[i])
    thicknesses = [thicknesses[i] for i in sorted_indices]
    energies_list = [energies_list[i] for i in sorted_indices]

    # Check convergence (energy change < threshold between consecutive points)
    converged = False
    recommended = thicknesses[-1]

    if len(energies_list) >= 2:
        for i in range(len(energies_list) - 1, 0, -1):
            delta = abs(energies_list[i] - energies_list[i - 1])
            if delta < threshold:
                converged = True
                recommended = thicknesses[i - 1]
                break

    return orm.Dict(dict={
        'miller_indices': miller_indices.get_list(),
        'results': results,
        'summary': {
            'thicknesses': thicknesses,
            'surface_energies_J_m2': energies_list,
            'converged': converged,
            'recommended_layers': recommended,
            'max_tested_layers': max(thicknesses) if thicknesses else 0,
            'convergence_threshold': threshold,
        }
    })


@task.graph
def gather_surface_energies(
    surface_energies: t.Annotated[dict[str, orm.Dict], dynamic(orm.Dict)],
    miller_indices: orm.List,
    convergence_threshold: orm.Float,
) -> orm.Dict:
    """
    Gather surface energies from dynamic namespace and analyze convergence.

    Args:
        surface_energies: Dynamic namespace of surface energy Dicts
        miller_indices: Miller indices used
        convergence_threshold: Energy difference threshold in J/m^2

    Returns:
        Combined Dict with convergence analysis
    """
    gather_kwargs = {
        'miller_indices': miller_indices,
        'convergence_threshold': convergence_threshold,
    }
    for key, surface_data in surface_energies.items():
        gather_kwargs[key] = surface_data

    result = analyze_thickness_convergence(**gather_kwargs)
    return result.result


def build_thickness_convergence_workgraph(
    # Structure input
    bulk_structure_path: str = None,
    bulk_structure: orm.StructureData = None,

    # VASP configuration
    code_label: str = 'VASP-6.5.1@cluster',
    potential_family: str = 'PBE',
    potential_mapping: dict = None,
    kpoints_spacing: float = 0.03,
    clean_workdir: bool = False,

    # Bulk parameters
    bulk_parameters: dict = None,
    bulk_options: dict = None,

    # Surface configuration
    miller_indices: list = None,
    layer_counts: list = None,
    min_vacuum_thickness: float = 15.0,
    lll_reduce: bool = True,
    center_slab: bool = True,
    primitive: bool = True,
    termination_index: int = 0,

    # Slab relaxation
    slab_parameters: dict = None,
    slab_options: dict = None,
    slab_kpoints_spacing: float = None,

    # Convergence settings
    convergence_threshold: float = 0.01,

    # Concurrency
    max_concurrent_jobs: int = 4,

    # Workflow name
    name: str = 'ThicknessConvergence',
) -> WorkGraph:
    """
    Build a WorkGraph for slab thickness convergence testing.

    This workflow:
    1. Relaxes the bulk structure once
    2. Generates slabs at multiple thicknesses with the same termination
    3. Relaxes all slabs in parallel
    4. Calculates surface energy for each thickness
    5. Reports convergence status and recommended thickness

    Args:
        bulk_structure_path: Path to bulk structure file
        bulk_structure: Bulk structure as StructureData (alternative to path)
        code_label: VASP code label in AiiDA
        potential_family: Potential family name
        potential_mapping: Element to potential mapping
        kpoints_spacing: K-points spacing for bulk
        clean_workdir: Clean work directory after completion
        bulk_parameters: VASP INCAR parameters for bulk
        bulk_options: Scheduler options for bulk
        miller_indices: Miller indices (e.g., [1, 1, 1])
        layer_counts: List of layer counts (e.g., [3, 5, 7, 9, 11])
        min_vacuum_thickness: Vacuum thickness in Angstroms
        lll_reduce: Use LLL reduction
        center_slab: Center slab in c direction
        primitive: Find primitive cell
        termination_index: Which termination to use (0 = first)
        slab_parameters: VASP INCAR parameters for slabs
        slab_options: Scheduler options for slabs
        slab_kpoints_spacing: K-points spacing for slabs
        convergence_threshold: Surface energy difference threshold in J/m^2
        max_concurrent_jobs: Maximum concurrent VASP calculations
        name: Name for the WorkGraph

    Returns:
        WorkGraph ready for submission

    Outputs:
        - bulk_energy: Total bulk energy
        - bulk_structure: Relaxed bulk structure
        - convergence_results: Dict with all surface energies and convergence analysis

    Example:
        >>> from quantum_lego.core.common.convergence import build_thickness_convergence_workgraph
        >>>
        >>> wg = build_thickness_convergence_workgraph(
        ...     bulk_structure_path='/path/to/bulk.cif',
        ...     code_label='VASP-6.5.1@cluster',
        ...     potential_family='PBE.54',
        ...     potential_mapping={'Au': 'Au'},
        ...     miller_indices=[1, 1, 1],
        ...     layer_counts=[3, 5, 7, 9, 11],
        ...     bulk_parameters={'ENCUT': 500, 'ISMEAR': 1, ...},
        ...     bulk_options={'resources': {...}},
        ...     convergence_threshold=0.01,  # J/m^2
        ...     max_concurrent_jobs=4,
        ... )
        >>> wg.submit()
    """
    logger.info(f"Building thickness convergence WorkGraph: {name}")

    # Validate inputs
    if bulk_structure_path is None and bulk_structure is None:
        raise ValueError("Either bulk_structure_path or bulk_structure must be provided")

    if miller_indices is None:
        raise ValueError("miller_indices must be provided (e.g., [1, 1, 1])")

    if layer_counts is None or len(layer_counts) < 2:
        raise ValueError("layer_counts must have at least 2 thicknesses (e.g., [3, 5, 7, 9])")

    if potential_mapping is None:
        raise ValueError("potential_mapping must be provided (e.g., {'Au': 'Au'})")

    if bulk_parameters is None:
        raise ValueError("bulk_parameters must be provided")

    if bulk_options is None:
        raise ValueError("bulk_options must be provided")

    # Load structure
    if bulk_structure is None:
        if not os.path.isabs(bulk_structure_path):
            raise ValueError(f"bulk_structure_path must be absolute: {bulk_structure_path}")
        bulk_structure = _load_structure_from_file(bulk_structure_path)
        logger.info(f"  Loaded structure from: {bulk_structure_path}")

    # Load code
    code = orm.load_code(code_label)
    logger.info(f"  Using code: {code_label}")

    # Get VASP workchain
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Build workflow
    wg = WorkGraph(name=name)
    logger.info(f"  Miller indices: {miller_indices}")
    logger.info(f"  Layer counts: {layer_counts}")

    # ===== BULK RELAXATION =====
    bulk_task = wg.add_task(
        VaspTask,
        name='bulk_relax',
        structure=bulk_structure,
        code=code,
        parameters={'incar': bulk_parameters},
        options=bulk_options,
        kpoints_spacing=kpoints_spacing,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        clean_workdir=clean_workdir,
        settings=orm.Dict(dict=_get_thickness_settings()),
    )

    bulk_energy_task = wg.add_task(
        extract_total_energy,
        name='bulk_energy',
        misc=bulk_task.outputs.misc,
    )

    # ===== SLAB GENERATION =====
    miller_list = orm.List(list=[int(m) for m in miller_indices])
    layers_list = orm.List(list=[int(n) for n in layer_counts])

    slab_gen_task = wg.add_task(
        generate_thickness_series,
        name='generate_slabs',
        bulk_structure=bulk_task.outputs.structure,
        miller_indices=miller_list,
        layer_counts=layers_list,
        min_vacuum_thickness=orm.Float(min_vacuum_thickness),
        lll_reduce=orm.Bool(lll_reduce),
        center_slab=orm.Bool(center_slab),
        primitive=orm.Bool(primitive),
        termination_index=orm.Int(termination_index),
    )

    # ===== SLAB RELAXATION =====
    slab_params = slab_parameters if slab_parameters is not None else bulk_parameters
    slab_opts = slab_options if slab_options is not None else bulk_options
    slab_kpts = slab_kpoints_spacing if slab_kpoints_spacing is not None else kpoints_spacing

    relax_task = wg.add_task(
        relax_thickness_series,
        name='relax_slabs',
        slabs=slab_gen_task.outputs.slabs,
        code_pk=code.pk,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        parameters=slab_params,
        options=slab_opts,
        kpoints_spacing=slab_kpts,
        clean_workdir=clean_workdir,
        max_number_jobs=max_concurrent_jobs,
    )

    # ===== SURFACE ENERGY CALCULATION =====
    surface_energy_task = wg.add_task(
        compute_surface_energies,
        name='compute_surface_energies',
        slabs=relax_task.outputs.relaxed_structures,
        energies=relax_task.outputs.energies,
        bulk_structure=bulk_task.outputs.structure,
        bulk_energy=bulk_energy_task.outputs.result,
    )

    # ===== GATHER RESULTS =====
    gather_task = wg.add_task(
        gather_surface_energies,
        name='gather_results',
        surface_energies=surface_energy_task.outputs.surface_energies,
        miller_indices=miller_list,
        convergence_threshold=orm.Float(convergence_threshold),
    )

    # Expose outputs
    wg.outputs.bulk_energy = bulk_energy_task.outputs.result
    wg.outputs.bulk_structure = bulk_task.outputs.structure
    wg.outputs.convergence_results = gather_task.outputs.result

    # Set concurrency limit
    if max_concurrent_jobs is not None:
        wg.max_number_jobs = max_concurrent_jobs

    logger.info(f"  Convergence threshold: {convergence_threshold} J/m^2")
    logger.info("  WorkGraph built successfully")

    return wg


def get_thickness_convergence_results(workgraph) -> dict:
    """
    Extract results from completed thickness convergence WorkGraph.

    Args:
        workgraph: Completed WorkGraph from build_thickness_convergence_workgraph

    Returns:
        dict with:
            - bulk_energy: float, bulk total energy (eV)
            - convergence_results: dict with full convergence analysis
            - recommended_layers: int, recommended slab thickness
            - converged: bool, whether convergence was achieved
            - surface_energies: dict mapping layer count to surface energy (J/m^2)

    Example:
        >>> results = get_thickness_convergence_results(wg)
        >>> print(f"Converged: {results['converged']}")
        >>> print(f"Recommended layers: {results['recommended_layers']}")
        >>> for layers, gamma in results['surface_energies'].items():
        ...     print(f"  {layers} layers: {gamma:.3f} J/m^2")
    """
    results = {}

    # Extract bulk energy
    if hasattr(workgraph.outputs, 'bulk_energy'):
        bulk_node = workgraph.outputs.bulk_energy.value
        results['bulk_energy'] = bulk_node.value if hasattr(bulk_node, 'value') else float(bulk_node)
    else:
        results['bulk_energy'] = None

    # Extract convergence results
    if hasattr(workgraph.outputs, 'convergence_results'):
        conv_node = workgraph.outputs.convergence_results.value
        conv_data = conv_node.get_dict()
        results['convergence_results'] = conv_data

        summary = conv_data.get('summary', {})
        results['recommended_layers'] = summary.get('recommended_layers')
        results['converged'] = summary.get('converged', False)

        # Extract surface energies as simple dict
        thicknesses = summary.get('thicknesses', [])
        energies = summary.get('surface_energies_J_m2', [])
        results['surface_energies'] = dict(zip(thicknesses, energies))
    else:
        results['convergence_results'] = None
        results['recommended_layers'] = None
        results['converged'] = False
        results['surface_energies'] = {}

    return results
