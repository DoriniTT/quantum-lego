"""Slab thickness convergence workflow.

This module provides workflows for testing convergence of slab thickness
in surface energy calculations.
"""

from __future__ import annotations

import logging
import os
import typing as t

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task, dynamic, namespace, get_current_graph

from .utils import _load_structure_from_file, _get_thickness_settings
from .slabs import generate_thickness_series
from ..constants import EV_PER_ANGSTROM2_TO_J_PER_M2
from ..utils import extract_max_jobs_value, extract_total_energy

logger = logging.getLogger(__name__)


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
        energies_ns[label] = extract_total_energy(energies=relaxation.misc).result

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
        energies=bulk_task.outputs.misc,
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


__all__ = [
    'build_thickness_convergence_workgraph',
    'get_thickness_convergence_results',
    'relax_thickness_series',
    'calculate_surface_energy',
    'compute_surface_energies',
    'analyze_thickness_convergence',
    'gather_surface_energies',
]
