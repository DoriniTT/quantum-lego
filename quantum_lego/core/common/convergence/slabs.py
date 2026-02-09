"""
Slab Generation for Thickness Convergence Testing.

This module provides functions to generate surface slabs at multiple thicknesses
with the same termination, for determining the minimum slab thickness needed
for converged surface energies.
"""

from __future__ import annotations

import typing as t

from aiida import orm
from aiida_workgraph import task, namespace, dynamic
from pymatgen.core.surface import SlabGenerator
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


@task.calcfunction
def generate_thickness_series(
    bulk_structure: orm.StructureData,
    miller_indices: orm.List,
    layer_counts: orm.List,
    min_vacuum_thickness: orm.Float,
    lll_reduce: orm.Bool,
    center_slab: orm.Bool,
    primitive: orm.Bool,
    termination_index: orm.Int,
) -> t.Annotated[dict, namespace(slabs=dynamic(orm.StructureData))]:
    """
    Generate slab structures at multiple thicknesses with the same termination.

    Uses pymatgen's SlabGenerator with in_unit_planes=True to ensure consistent
    layer counting across different thicknesses. The same termination (identified
    by shift value) is used for all thicknesses to enable valid convergence testing.

    Args:
        bulk_structure: AiiDA StructureData of the bulk crystal
        miller_indices: Miller indices for the surface (e.g., [1, 1, 1])
        layer_counts: List of layer counts to generate (e.g., [3, 5, 7, 9])
        min_vacuum_thickness: Minimum vacuum thickness in Angstroms
        lll_reduce: Reduce cell using LLL algorithm
        center_slab: Center the slab in the c direction
        primitive: Find primitive cell before generating slabs
        termination_index: Which termination to use (0 = first/lowest-index)

    Returns:
        Dictionary with key 'slabs' containing slab structures keyed by layer count
        (e.g., {'layers_3': StructureData, 'layers_5': StructureData, ...})
    """
    adaptor = AseAtomsAdaptor()

    # Convert bulk structure to pymatgen
    ase_structure = bulk_structure.get_ase()
    pymatgen_structure = adaptor.get_structure(ase_structure)

    if primitive.value:
        analyzer = SpacegroupAnalyzer(pymatgen_structure)
        pymatgen_structure = analyzer.get_primitive_standard_structure()

    miller_tuple = tuple(miller_indices.get_list())
    layer_list = layer_counts.get_list()
    term_idx = termination_index.value

    # Calculate d-spacing for the Miller plane
    # When in_unit_planes=True, min_vacuum_thickness is interpreted as number of
    # unit planes, not Angstroms. We need to convert from Angstroms to unit planes.
    d_spacing = pymatgen_structure.lattice.d_hkl(miller_tuple)
    vacuum_in_unit_planes = min_vacuum_thickness.value / d_spacing

    # First, determine the reference shift from the thickest slab
    # This ensures we use a valid termination that exists at all thicknesses
    max_layers = max(layer_list)

    ref_generator = SlabGenerator(
        pymatgen_structure,
        miller_tuple,
        max_layers,
        vacuum_in_unit_planes,
        center_slab=center_slab.value,
        in_unit_planes=True,
        lll_reduce=lll_reduce.value,
    )

    ref_slabs = ref_generator.get_slabs(symmetrize=True)
    if not ref_slabs:
        raise ValueError(
            f"No slabs were generated for Miller indices {miller_tuple}. "
            f"Check if the Miller indices are valid for this structure."
        )

    if term_idx >= len(ref_slabs):
        raise ValueError(
            f"Requested termination index {term_idx} but only "
            f"{len(ref_slabs)} terminations available."
        )

    # Get the reference shift for our chosen termination
    reference_shift = ref_slabs[term_idx].shift

    # Generate slabs at each thickness with the same termination
    slab_nodes: dict[str, orm.StructureData] = {}

    for n_layers in layer_list:
        generator = SlabGenerator(
            pymatgen_structure,
            miller_tuple,
            n_layers,
            vacuum_in_unit_planes,
            center_slab=center_slab.value,
            in_unit_planes=True,
            lll_reduce=lll_reduce.value,
        )

        # Get all slabs and find the one matching our reference shift
        all_slabs = generator.get_slabs(symmetrize=True)

        # Find slab with matching shift (within tolerance)
        matching_slab = None
        shift_tolerance = 1e-4

        for slab in all_slabs:
            if abs(slab.shift - reference_shift) < shift_tolerance:
                matching_slab = slab
                break

        if matching_slab is None:
            # Fallback: use the termination at the same index
            # This can happen if shifts differ slightly due to numerical precision
            if term_idx < len(all_slabs):
                matching_slab = all_slabs[term_idx]
            else:
                matching_slab = all_slabs[0]

        # Convert to orthogonal c-axis and store
        orthogonal_slab = matching_slab.get_orthogonal_c_slab()
        ase_slab = adaptor.get_atoms(orthogonal_slab)
        slab_nodes[f"layers_{n_layers}"] = orm.StructureData(ase=ase_slab)

    return {'slabs': slab_nodes}


@task.calcfunction
def extract_recommended_layers(convergence_results: orm.Dict) -> orm.Int:
    """
    Extract recommended layer count from thickness convergence results.

    This function extracts the recommended slab thickness (in layers) from
    the convergence test results. If convergence was not reached, it raises
    an error to fail the workflow.

    Args:
        convergence_results: Dict containing convergence test results with structure:
            {
                'miller_indices': [1, 1, 1],
                'results': {
                    'layers_3': {...},
                    'layers_5': {...},
                    ...
                },
                'summary': {
                    'converged': True/False,
                    'recommended_layers': int,
                    'max_tested_layers': int,
                    'convergence_threshold': float,
                }
            }

    Returns:
        Int with the recommended number of layers

    Raises:
        ValueError: If convergence was not reached
    """
    results = convergence_results.get_dict()
    summary = results.get('summary', {})

    if not summary.get('converged', False):
        max_tested = summary.get('max_tested_layers', 'unknown')
        threshold = summary.get('convergence_threshold', 'unknown')
        raise ValueError(
            f"Thickness convergence not reached. "
            f"Tested up to {max_tested} layers with threshold {threshold} J/m². "
            f"Consider testing more layers or adjusting convergence threshold."
        )

    recommended = summary.get('recommended_layers')
    if recommended is None:
        raise ValueError(
            "Convergence results missing 'recommended_layers' in summary. "
            "This may indicate an issue with the convergence calculation."
        )

    return orm.Int(recommended)
