"""Convergence testing module for PS-TEROS.

This module provides:
1. Automated ENCUT and k-points convergence testing using aiida-vasp
2. Slab thickness convergence testing for surface energy calculations
3. Visualization and export utilities for convergence analysis

Usage:
    # ENCUT/k-points convergence
    from quantum_lego.core.common.convergence import build_convergence_workgraph
    wg = build_convergence_workgraph(structure=..., code_label=..., ...)

    # After completion, visualize results
    from quantum_lego.core.common.convergence import print_convergence_summary, plot_convergence
    print_convergence_summary(wg)  # Formatted console output
    plot_convergence(wg, save_path='convergence.png')  # Plot curves

    # Thickness convergence
    from quantum_lego.core.common.convergence import build_thickness_convergence_workgraph
    wg = build_thickness_convergence_workgraph(
        bulk_structure_path='/path/to/bulk.cif',
        miller_indices=[1, 1, 1],
        layer_counts=[3, 5, 7, 9, 11],
        ...
    )

    # After thickness convergence completion, visualize results
    from quantum_lego.core.common.convergence import (
        print_thickness_convergence_summary,
        plot_thickness_convergence,
        export_thickness_convergence_data,
    )
    print_thickness_convergence_summary(wg)  # Formatted console output
    plot_thickness_convergence(wg, save_path='thickness_conv.png')  # Plot curve
    export_thickness_convergence_data(wg, output_dir='./results')  # Export data
"""

from .workgraph import (
    # ENCUT/k-points convergence
    build_convergence_workgraph,
    get_convergence_results,
    convergence_scan,
    # Thickness convergence
    build_thickness_convergence_workgraph,
    get_thickness_convergence_results,
    calculate_surface_energy,
    analyze_thickness_convergence,
    relax_thickness_series,
    compute_surface_energies,
    gather_surface_energies,
)
from ..utils import extract_total_energy
from .slabs import (
    generate_thickness_series,
    extract_recommended_layers,
)
from .visualization import (
    # ENCUT/k-points visualization
    print_convergence_summary,
    plot_convergence,
    export_convergence_data,
    # Thickness convergence visualization
    print_thickness_convergence_summary,
    plot_thickness_convergence,
    export_thickness_convergence_data,
)

__all__ = [
    # ENCUT/k-points convergence
    'build_convergence_workgraph',
    'get_convergence_results',
    'convergence_scan',
    # ENCUT/k-points visualization and export
    'print_convergence_summary',
    'plot_convergence',
    'export_convergence_data',
    # Thickness convergence workflow
    'build_thickness_convergence_workgraph',
    'get_thickness_convergence_results',
    'generate_thickness_series',
    'extract_recommended_layers',
    'extract_total_energy',
    'calculate_surface_energy',
    'analyze_thickness_convergence',
    'relax_thickness_series',
    'compute_surface_energies',
    'gather_surface_energies',
    # Thickness convergence visualization and export
    'print_thickness_convergence_summary',
    'plot_thickness_convergence',
    'export_thickness_convergence_data',
]
