"""Visualization and summary functions for convergence analysis.

This module provides utilities for displaying and exporting convergence test results:
- print_convergence_summary(): Formatted console output with convergence tables
- plot_convergence(): Matplotlib visualization of convergence curves
- export_convergence_data(): Export results to CSV/JSON files

All functions accept WorkGraph objects, PKs (int), or PK strings for flexibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from aiida import orm
from aiida_workgraph import WorkGraph

if TYPE_CHECKING:
    import matplotlib.figure

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _load_workgraph(
    workgraph: Union[int, str, WorkGraph, orm.Node]
) -> WorkGraph:
    """
    Load WorkGraph from various input formats.

    Args:
        workgraph: Can be:
            - int: WorkGraph PK
            - str: WorkGraph PK as string
            - WorkGraph: Already loaded WorkGraph object
            - orm.Node: AiiDA node (will extract PK)

    Returns:
        WorkGraph object

    Raises:
        ValueError: If workgraph cannot be loaded
        NotExistentError: If PK does not exist
    """
    if isinstance(workgraph, WorkGraph):
        return workgraph

    if isinstance(workgraph, orm.Node):
        # Already an AiiDA node, get its PK
        return WorkGraph.load(workgraph.pk)

    try:
        pk = int(workgraph)
        return WorkGraph.load(pk)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"Cannot load WorkGraph from {workgraph!r}. "
            "Provide a PK (int/str) or WorkGraph object."
        ) from e


def _get_structure_formula(workgraph: WorkGraph) -> tuple[str, int]:
    """
    Extract structure formula and atom count from WorkGraph inputs.

    Tries multiple methods to find the structure:
    1. From convergence_scan task inputs (live WorkGraph)
    2. From stored node link traversal (completed WorkGraph)

    Args:
        workgraph: WorkGraph object

    Returns:
        tuple: (formula: str, n_atoms: int)
               Returns ("Unknown", 0) if structure cannot be found
    """
    # Method 1: Try live WorkGraph with tasks attribute
    try:
        if hasattr(workgraph, 'tasks') and 'convergence_scan' in workgraph.tasks:
            task = workgraph.tasks['convergence_scan']
            if hasattr(task.inputs, 'structure'):
                structure = task.inputs.structure.value
                if structure:
                    formula = structure.get_formula()
                    n_atoms = len(structure.sites)
                    return formula, n_atoms
    except Exception:
        pass

    # Method 2: Try stored node link traversal
    try:
        from aiida.common.links import LinkType

        # Check if workgraph has process node accessible
        if hasattr(workgraph, 'process') and workgraph.process:
            process = workgraph.process
        elif hasattr(workgraph, 'pk'):
            process = orm.load_node(workgraph.pk)
        else:
            process = None

        if process and hasattr(process, 'base'):
            # Traverse CALL_WORK links to find convergence_scan
            outgoing = process.base.links.get_outgoing(
                link_type=LinkType.CALL_WORK
            )
            for link in outgoing.all():
                if 'convergence_scan' in link.link_label:
                    # Found the convergence task, get its structure input
                    conv_node = link.node
                    incoming = conv_node.base.links.get_incoming(
                        link_type=LinkType.INPUT_WORK
                    )
                    for in_link in incoming.all():
                        if in_link.link_label == 'structure':
                            structure = in_link.node
                            formula = structure.get_formula()
                            n_atoms = len(structure.sites)
                            return formula, n_atoms
    except Exception:
        pass

    return "Unknown", 0


def _get_workgraph_pk(workgraph: WorkGraph) -> Optional[int]:
    """Get the PK of a WorkGraph if available."""
    try:
        if hasattr(workgraph, 'pk') and workgraph.pk:
            return workgraph.pk
        if hasattr(workgraph, 'process') and workgraph.process:
            return workgraph.process.pk
    except Exception:
        pass
    return None


# =============================================================================
# PRINT SUMMARY
# =============================================================================

def print_convergence_summary(
    workgraph: Union[int, str, WorkGraph, orm.Node]
) -> dict:
    """
    Print a formatted summary of convergence test results.

    Displays a detailed table with ENCUT and k-points convergence data,
    including energy values, differences from reference, and convergence status.

    Args:
        workgraph: WorkGraph PK (int), PK as string, WorkGraph object,
                   or AiiDA Node

    Returns:
        dict: The convergence results dictionary (same as get_convergence_results)

    Example:
        >>> from quantum_lego.core.common.convergence import print_convergence_summary
        >>> print_convergence_summary(12345)  # Using PK
        >>> results = print_convergence_summary(wg)  # Using WorkGraph object

    Output format:
        ═══════════════════════════════════════════════════════════════════
                      VASP CONVERGENCE TEST RESULTS
        ═══════════════════════════════════════════════════════════════════
        WorkGraph PK: 12345
        Structure: Si2 (2 atoms)
        Threshold: 1.0 meV/atom
        ───────────────────────────────────────────────────────────────────

        ENCUT Convergence:
        ┌─────────┬──────────────┬──────────────┬───────────┐
        │ ENCUT   │ Energy/atom  │ ΔE from ref  │ Converged │
        │ (eV)    │ (eV)         │ (meV)        │           │
        ├─────────┼──────────────┼──────────────┼───────────┤
        │     200 │      -5.4123 │        15.20 │ ✗         │
        │     250 │      -5.4201 │         7.40 │ ✗         │
        │     300 │      -5.4258 │         1.70 │ ✗         │
        │     350 │      -5.4270 │         0.50 │ ✓         │
        │     400 │      -5.4275 │         0.00 │ ✓ (ref)   │
        └─────────┴──────────────┴──────────────┴───────────┘
        ✓ Converged at ENCUT = 350 eV
        → Recommended: 400 eV (with safety margin)
        ...
    """
    from .workgraph import get_convergence_results

    wg = _load_workgraph(workgraph)
    results = get_convergence_results(wg)
    formula, n_atoms = _get_structure_formula(wg)
    pk = _get_workgraph_pk(wg)

    # Header
    print("\n" + "═" * 70)
    print("              VASP CONVERGENCE TEST RESULTS")
    print("═" * 70)

    if pk:
        print(f"WorkGraph PK: {pk}")

    print(f"Structure: {formula} ({n_atoms} atoms)")

    threshold = 0.001  # default
    if results['convergence_summary']:
        threshold = results['convergence_summary'].get('threshold_used', 0.001)
        print(f"Threshold: {threshold * 1000:.1f} meV/atom")

    print("─" * 70)

    # ENCUT Convergence Table
    if results['cutoff_analysis']:
        cutoff_data = results['cutoff_analysis']
        print("\nENCUT Convergence:")
        print("┌─────────┬──────────────┬──────────────┬───────────┐")
        print("│ ENCUT   │ Energy/atom  │ ΔE from ref  │ Converged │")
        print("│ (eV)    │ (eV)         │ (meV)        │           │")
        print("├─────────┼──────────────┼──────────────┼───────────┤")

        cutoff_values = cutoff_data.get('cutoff_values', [])
        energy_per_atom = cutoff_data.get('energy_per_atom', [])
        energy_diffs = cutoff_data.get('energy_diff_from_max', [])
        converged_cutoff = cutoff_data.get('converged_cutoff')

        if cutoff_values and energy_per_atom and energy_diffs:
            for i, (cutoff, e_atom, diff) in enumerate(zip(
                cutoff_values, energy_per_atom, energy_diffs
            )):
                is_ref = (i == len(cutoff_values) - 1)
                is_converged = diff <= threshold

                if is_ref:
                    status = "✓ (ref)"
                elif is_converged:
                    status = "✓"
                else:
                    status = "✗"

                print(f"│ {cutoff:7.0f} │ {e_atom:12.4f} │ {diff * 1000:12.2f} │ {status:9} │")

            print("└─────────┴──────────────┴──────────────┴───────────┘")

            if converged_cutoff:
                print(f"✓ Converged at ENCUT = {converged_cutoff} eV")
                if results['recommended_cutoff']:
                    print(f"→ Recommended: {results['recommended_cutoff']} eV (with safety margin)")
            else:
                print("✗ NOT CONVERGED - consider increasing cutoff_stop")
        else:
            print("│  (No data available)                              │")
            print("└─────────┴──────────────┴──────────────┴───────────┘")
    else:
        print("\nENCUT Convergence: No data available")

    # K-points Convergence Table
    if results['kpoints_analysis']:
        kpoints_data = results['kpoints_analysis']
        print("\nK-points Convergence:")
        print("┌──────────┬──────────────┬──────────────┬───────────┐")
        print("│ k-spacing│ Energy/atom  │ ΔE from ref  │ Converged │")
        print("│ (Å⁻¹)    │ (eV)         │ (meV)        │           │")
        print("├──────────┼──────────────┼──────────────┼───────────┤")

        kspacing_values = kpoints_data.get('kspacing_values', [])
        energy_per_atom = kpoints_data.get('energy_per_atom', [])
        energy_diffs = kpoints_data.get('energy_diff_from_densest', [])
        converged_kspacing = kpoints_data.get('converged_kspacing')

        if kspacing_values and energy_per_atom and energy_diffs:
            for i, (ksp, e_atom, diff) in enumerate(zip(
                kspacing_values, energy_per_atom, energy_diffs
            )):
                is_ref = (i == len(kspacing_values) - 1)
                is_converged = diff <= threshold

                if is_ref:
                    status = "✓ (ref)"
                elif is_converged:
                    status = "✓"
                else:
                    status = "✗"

                print(f"│ {ksp:8.4f} │ {e_atom:12.4f} │ {diff * 1000:12.2f} │ {status:9} │")

            print("└──────────┴──────────────┴──────────────┴───────────┘")

            if converged_kspacing:
                print(f"✓ Converged at k-spacing = {converged_kspacing:.4f} Å⁻¹")
                if results['recommended_kspacing']:
                    print(f"→ Recommended: {results['recommended_kspacing']:.4f} Å⁻¹ (with safety margin)")
            else:
                print("✗ NOT CONVERGED - consider decreasing kspacing_stop")
        else:
            print("│  (No data available)                               │")
            print("└──────────┴──────────────┴──────────────┴───────────┘")
    else:
        print("\nK-points Convergence: No data available")

    # Final Summary
    print("\n" + "═" * 70)
    summary_parts = []
    if results['recommended_cutoff']:
        summary_parts.append(f"ENCUT = {results['recommended_cutoff']} eV")
    else:
        summary_parts.append("ENCUT = NOT CONVERGED")

    if results['recommended_kspacing']:
        summary_parts.append(f"k-spacing = {results['recommended_kspacing']:.4f} Å⁻¹")
    else:
        summary_parts.append("k-spacing = NOT CONVERGED")

    print(f"SUMMARY: {', '.join(summary_parts)}")
    print("═" * 70 + "\n")

    return results


# =============================================================================
# PLOTTING
# =============================================================================

def plot_convergence(
    workgraph: Union[int, str, WorkGraph, orm.Node],
    save_path: Optional[str] = None,
    figsize: tuple[float, float] = (12, 5),
    dpi: int = 150,
    show: bool = True,
) -> 'matplotlib.figure.Figure':
    """
    Plot convergence curves for ENCUT and k-points.

    Creates a two-panel figure showing:
    - Left: Energy difference vs ENCUT with convergence threshold
    - Right: Energy difference vs k-spacing with convergence threshold

    Args:
        workgraph: WorkGraph PK (int), PK as string, WorkGraph object,
                   or AiiDA Node
        save_path: Optional path to save the figure (PNG, PDF, SVG, etc.)
        figsize: Figure size in inches as (width, height)
        dpi: Resolution for saved figure (dots per inch)
        show: Whether to display the plot interactively (default: True)

    Returns:
        matplotlib.figure.Figure: The figure object for further customization

    Raises:
        ImportError: If matplotlib is not installed

    Example:
        >>> from quantum_lego.core.common.convergence import plot_convergence
        >>> fig = plot_convergence(12345)  # Using PK
        >>> fig = plot_convergence(wg, save_path='convergence.png', show=False)

        # Customize the figure
        >>> fig = plot_convergence(wg, show=False)
        >>> fig.axes[0].set_xlim(200, 600)
        >>> fig.savefig('custom_plot.pdf')
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError(
            "matplotlib is required for plotting. "
            "Install with: pip install matplotlib"
        )

    from .workgraph import get_convergence_results

    wg = _load_workgraph(workgraph)
    results = get_convergence_results(wg)
    formula, n_atoms = _get_structure_formula(wg)
    pk = _get_workgraph_pk(wg)

    # Get threshold
    threshold = 0.001  # default
    if results['convergence_summary']:
        threshold = results['convergence_summary'].get('threshold_used', 0.001)
    threshold_meV = threshold * 1000

    # Create figure
    fig, axes = plt.subplots(1, 2, figsize=figsize)

    # Color scheme (colorblind-friendly)
    colors = {
        'data': '#0077BB',       # Blue
        'threshold': '#CC3311',  # Red
        'converged': '#009988',  # Teal
    }

    # ===== ENCUT Convergence (Left Panel) =====
    ax1 = axes[0]
    if results['cutoff_analysis']:
        cutoff_data = results['cutoff_analysis']
        cutoff_values = cutoff_data.get('cutoff_values', [])
        energy_diffs = cutoff_data.get('energy_diff_from_max', [])
        converged_cutoff = cutoff_data.get('converged_cutoff')

        if cutoff_values and energy_diffs:
            # Convert to meV
            energy_diffs_meV = [d * 1000 for d in energy_diffs]

            # Plot data
            ax1.plot(cutoff_values, energy_diffs_meV, 'o-', color=colors['data'],
                     markersize=8, linewidth=2, label='Energy difference')

            # Threshold line
            ax1.axhline(y=threshold_meV, color=colors['threshold'], linestyle='--',
                        linewidth=1.5, label=f'Threshold ({threshold_meV:.1f} meV)')

            # Mark converged value
            if converged_cutoff:
                ax1.axvline(x=converged_cutoff, color=colors['converged'], linestyle=':',
                            linewidth=2, label=f'Converged ({converged_cutoff} eV)')

            ax1.set_xlabel('ENCUT (eV)', fontsize=12)
            ax1.set_ylabel('ΔE from reference (meV/atom)', fontsize=12)
            ax1.set_title('ENCUT Convergence', fontsize=14, fontweight='bold')
            ax1.legend(loc='upper right', fontsize=10)
            ax1.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
            ax1.set_ylim(bottom=-0.5)

            # Add minor gridlines
            ax1.minorticks_on()
            ax1.grid(True, which='minor', alpha=0.1, linestyle='-', linewidth=0.5)
    else:
        ax1.text(0.5, 0.5, 'No ENCUT data available',
                 ha='center', va='center', transform=ax1.transAxes, fontsize=12)
        ax1.set_title('ENCUT Convergence', fontsize=14, fontweight='bold')

    # ===== K-points Convergence (Right Panel) =====
    ax2 = axes[1]
    if results['kpoints_analysis']:
        kpoints_data = results['kpoints_analysis']
        kspacing_values = kpoints_data.get('kspacing_values', [])
        energy_diffs = kpoints_data.get('energy_diff_from_densest', [])
        converged_kspacing = kpoints_data.get('converged_kspacing')

        if kspacing_values and energy_diffs:
            # Convert to meV
            energy_diffs_meV = [d * 1000 for d in energy_diffs]

            # Plot data
            ax2.plot(kspacing_values, energy_diffs_meV, 's-', color=colors['data'],
                     markersize=8, linewidth=2, label='Energy difference')

            # Threshold line
            ax2.axhline(y=threshold_meV, color=colors['threshold'], linestyle='--',
                        linewidth=1.5, label=f'Threshold ({threshold_meV:.1f} meV)')

            # Mark converged value
            if converged_kspacing:
                ax2.axvline(x=converged_kspacing, color=colors['converged'], linestyle=':',
                            linewidth=2, label=f'Converged ({converged_kspacing:.3f} Å⁻¹)')

            ax2.set_xlabel('k-spacing (Å⁻¹)', fontsize=12)
            ax2.set_ylabel('ΔE from reference (meV/atom)', fontsize=12)
            ax2.set_title('K-points Convergence', fontsize=14, fontweight='bold')
            ax2.legend(loc='upper left', fontsize=10)
            ax2.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
            ax2.set_ylim(bottom=-0.5)
            ax2.invert_xaxis()  # Finer grid (smaller k-spacing) on the right

            # Add minor gridlines
            ax2.minorticks_on()
            ax2.grid(True, which='minor', alpha=0.1, linestyle='-', linewidth=0.5)
    else:
        ax2.text(0.5, 0.5, 'No k-points data available',
                 ha='center', va='center', transform=ax2.transAxes, fontsize=12)
        ax2.set_title('K-points Convergence', fontsize=14, fontweight='bold')

    # Overall title
    title = f'Convergence Test: {formula}'
    if pk:
        title += f' (PK: {pk})'
    fig.suptitle(title, fontsize=16, fontweight='bold', y=1.02)

    plt.tight_layout()

    # Save if requested
    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches='tight', facecolor='white')
        logger.info(f"Convergence plot saved to: {save_path}")
        print(f"Plot saved to: {save_path}")

    # Show if requested
    if show:
        try:
            plt.show()
        except Exception:
            pass  # Non-interactive backend

    return fig


# =============================================================================
# DATA EXPORT
# =============================================================================

def export_convergence_data(
    workgraph: Union[int, str, WorkGraph, orm.Node],
    output_dir: str,
    prefix: str = 'convergence',
) -> dict[str, str]:
    """
    Export convergence data to CSV and JSON files.

    Creates the following files in output_dir:
    - {prefix}_cutoff.csv: ENCUT convergence data with columns:
        ENCUT_eV, Energy_eV, Energy_per_atom_eV, Delta_E_meV, Converged
    - {prefix}_kpoints.csv: K-points convergence data with columns:
        kspacing_A-1, Energy_eV, Energy_per_atom_eV, Delta_E_meV, Converged
    - {prefix}_summary.json: Summary with recommendations and metadata

    Args:
        workgraph: WorkGraph PK (int), PK as string, WorkGraph object,
                   or AiiDA Node
        output_dir: Directory to save output files (created if doesn't exist)
        prefix: Prefix for output filenames (default: 'convergence')

    Returns:
        dict: Mapping of file types to absolute file paths created
            - 'cutoff_csv': Path to ENCUT CSV (if data available)
            - 'kpoints_csv': Path to k-points CSV (if data available)
            - 'summary_json': Path to summary JSON

    Example:
        >>> from quantum_lego.core.common.convergence import export_convergence_data
        >>> files = export_convergence_data(12345, '/path/to/output')
        >>> print(files)
        {
            'cutoff_csv': '/path/to/output/convergence_cutoff.csv',
            'kpoints_csv': '/path/to/output/convergence_kpoints.csv',
            'summary_json': '/path/to/output/convergence_summary.json'
        }

        # Custom prefix
        >>> files = export_convergence_data(wg, './results', prefix='Si_conv')
    """
    from .workgraph import get_convergence_results

    wg = _load_workgraph(workgraph)
    results = get_convergence_results(wg)
    formula, n_atoms = _get_structure_formula(wg)
    pk = _get_workgraph_pk(wg)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    created_files = {}

    # Get threshold
    threshold = 0.001
    if results['convergence_summary']:
        threshold = results['convergence_summary'].get('threshold_used', 0.001)

    # ===== Export ENCUT CSV =====
    if results['cutoff_analysis']:
        cutoff_data = results['cutoff_analysis']
        cutoff_csv = output_path / f'{prefix}_cutoff.csv'

        cutoff_values = cutoff_data.get('cutoff_values', [])
        energies = cutoff_data.get('energies', [])
        energy_per_atom = cutoff_data.get('energy_per_atom', [])
        energy_diffs = cutoff_data.get('energy_diff_from_max', [])

        if cutoff_values and energies:
            with open(cutoff_csv, 'w') as f:
                f.write("# ENCUT Convergence Data\n")
                f.write(f"# Structure: {formula} ({n_atoms} atoms)\n")
                if pk:
                    f.write(f"# WorkGraph PK: {pk}\n")
                f.write(f"# Threshold: {threshold * 1000:.2f} meV/atom\n")
                f.write("# Converged at: ")
                if cutoff_data.get('converged_cutoff'):
                    f.write(f"{cutoff_data['converged_cutoff']} eV\n")
                else:
                    f.write("NOT CONVERGED\n")
                f.write("#\n")
                f.write("ENCUT_eV,Energy_eV,Energy_per_atom_eV,Delta_E_meV,Converged\n")

                for cutoff, e_total, e_atom, diff in zip(
                    cutoff_values, energies, energy_per_atom, energy_diffs
                ):
                    converged = "True" if diff <= threshold else "False"
                    f.write(f"{cutoff:.0f},{e_total:.8f},{e_atom:.8f},{diff * 1000:.6f},{converged}\n")

            created_files['cutoff_csv'] = str(cutoff_csv.absolute())
            logger.info(f"ENCUT data exported to: {cutoff_csv}")

    # ===== Export K-points CSV =====
    if results['kpoints_analysis']:
        kpoints_data = results['kpoints_analysis']
        kpoints_csv = output_path / f'{prefix}_kpoints.csv'

        kspacing_values = kpoints_data.get('kspacing_values', [])
        energies = kpoints_data.get('energies', [])
        energy_per_atom = kpoints_data.get('energy_per_atom', [])
        energy_diffs = kpoints_data.get('energy_diff_from_densest', [])

        if kspacing_values and energies:
            with open(kpoints_csv, 'w') as f:
                f.write("# K-points Convergence Data\n")
                f.write(f"# Structure: {formula} ({n_atoms} atoms)\n")
                if pk:
                    f.write(f"# WorkGraph PK: {pk}\n")
                f.write(f"# Threshold: {threshold * 1000:.2f} meV/atom\n")
                f.write("# Converged at: ")
                if kpoints_data.get('converged_kspacing'):
                    f.write(f"{kpoints_data['converged_kspacing']:.4f} A^-1\n")
                else:
                    f.write("NOT CONVERGED\n")
                f.write("#\n")
                f.write("kspacing_A-1,Energy_eV,Energy_per_atom_eV,Delta_E_meV,Converged\n")

                for ksp, e_total, e_atom, diff in zip(
                    kspacing_values, energies, energy_per_atom, energy_diffs
                ):
                    converged = "True" if diff <= threshold else "False"
                    f.write(f"{ksp:.6f},{e_total:.8f},{e_atom:.8f},{diff * 1000:.6f},{converged}\n")

            created_files['kpoints_csv'] = str(kpoints_csv.absolute())
            logger.info(f"K-points data exported to: {kpoints_csv}")

    # ===== Export Summary JSON =====
    summary_json = output_path / f'{prefix}_summary.json'

    summary = {
        'workgraph_pk': pk,
        'structure': {
            'formula': formula,
            'n_atoms': n_atoms,
        },
        'convergence_threshold': {
            'eV_per_atom': threshold,
            'meV_per_atom': threshold * 1000,
        },
        'cutoff': {
            'converged': (
                results['cutoff_analysis'].get('convergence_achieved', False)
                if results['cutoff_analysis'] else False
            ),
            'converged_value_eV': (
                results['cutoff_analysis'].get('converged_cutoff')
                if results['cutoff_analysis'] else None
            ),
            'recommended_eV': results['recommended_cutoff'],
            'n_calculations': (
                len(results['cutoff_analysis'].get('cutoff_values', []))
                if results['cutoff_analysis'] else 0
            ),
        },
        'kpoints': {
            'converged': (
                results['kpoints_analysis'].get('convergence_achieved', False)
                if results['kpoints_analysis'] else False
            ),
            'converged_value_A-1': (
                results['kpoints_analysis'].get('converged_kspacing')
                if results['kpoints_analysis'] else None
            ),
            'recommended_A-1': results['recommended_kspacing'],
            'n_calculations': (
                len(results['kpoints_analysis'].get('kspacing_values', []))
                if results['kpoints_analysis'] else 0
            ),
        },
        'recommendations': {
            'ENCUT_eV': results['recommended_cutoff'],
            'kpoints_spacing_A-1': results['recommended_kspacing'],
            'summary': (
                results['convergence_summary'].get('summary')
                if results['convergence_summary'] else None
            ),
        },
    }

    with open(summary_json, 'w') as f:
        json.dump(summary, f, indent=2)

    created_files['summary_json'] = str(summary_json.absolute())
    logger.info(f"Summary exported to: {summary_json}")

    print(f"Exported {len(created_files)} files to: {output_path}")
    for file_type, path in created_files.items():
        print(f"  - {file_type}: {Path(path).name}")

    return created_files


# ============================================================================
# THICKNESS CONVERGENCE VISUALIZATION
# ============================================================================


def _get_thickness_structure_info(workgraph: WorkGraph) -> tuple[str, int, list]:
    """
    Extract formula, n_atoms, and miller_indices from thickness WorkGraph.

    Args:
        workgraph: Thickness convergence WorkGraph

    Returns:
        tuple: (formula, n_atoms, miller_indices)
    """
    formula = "Unknown"
    n_atoms = 0
    miller_indices = [0, 0, 0]

    try:
        # Try to get structure from bulk_relax task
        if 'bulk_relax' in workgraph.tasks:
            task = workgraph.tasks['bulk_relax']
            if hasattr(task.inputs, 'structure'):
                structure = task.inputs.structure.value
                if structure:
                    formula = structure.get_formula()
                    n_atoms = len(structure.sites)

        # Get miller indices from generate_slabs task
        if 'generate_slabs' in workgraph.tasks:
            task = workgraph.tasks['generate_slabs']
            if hasattr(task.inputs, 'miller_indices'):
                miller_node = task.inputs.miller_indices.value
                if miller_node:
                    miller_indices = miller_node.get_list()
    except Exception:
        pass

    return formula, n_atoms, miller_indices


def print_thickness_convergence_summary(workgraph: Union[int, str, WorkGraph]) -> None:
    """
    Print a formatted summary of thickness convergence test results.

    Args:
        workgraph: WorkGraph PK (int), PK as string, or WorkGraph object

    Example:
        >>> from quantum_lego.core.common.convergence import print_thickness_convergence_summary
        >>> print_thickness_convergence_summary(12345)  # Using PK
        >>> print_thickness_convergence_summary(wg)      # Using WorkGraph object
    """
    from .workgraph import get_thickness_convergence_results

    wg = _load_workgraph(workgraph)
    results = get_thickness_convergence_results(wg)
    formula, n_atoms, miller_indices = _get_thickness_structure_info(wg)

    # Extract convergence data
    conv_results = results.get('convergence_results')
    if not conv_results:
        print("\nNo convergence results available")
        return

    summary = conv_results.get('summary', {})
    thicknesses = summary.get('thicknesses', [])
    surface_energies = summary.get('surface_energies_J_m2', [])
    threshold = summary.get('convergence_threshold', 0.01)
    recommended_layers = results.get('recommended_layers')
    converged = results.get('converged', False)

    # Header
    print("\n" + "═" * 70)
    print("          THICKNESS CONVERGENCE TEST RESULTS")
    print("═" * 70)
    print(f"Structure: {formula} ({n_atoms} atoms)")
    print(f"Miller indices: ({miller_indices[0]} {miller_indices[1]} {miller_indices[2]})")
    print(f"Threshold: {threshold * 1000:.1f} mJ/m²")
    print("─" * 70)

    # Thickness Convergence Table
    print("\nSlab Thickness Convergence:")
    print("┌─────────┬───────────────────┬──────────────┬───────────┐")
    print("│ Layers  │ Surface Energy    │ ΔE from prev │ Converged │")
    print("│         │ (J/m²)            │ (mJ/m²)      │           │")
    print("├─────────┼───────────────────┼──────────────┼───────────┤")

    # Calculate deltas
    for i, (layers, gamma) in enumerate(zip(thicknesses, surface_energies)):
        if i == 0:
            delta_mJ = 0.0
            status = "─"
        else:
            delta = abs(gamma - surface_energies[i - 1])
            delta_mJ = delta * 1000  # Convert J/m² to mJ/m²
            is_converged = delta < threshold
            if is_converged:
                status = "✓"
            else:
                status = "✗"

        print(f"│ {layers:7} │ {gamma:17.4f} │ {delta_mJ:12.2f} │ {status:9} │")

    print("└─────────┴───────────────────┴──────────────┴───────────┘")

    # Convergence status
    if converged and recommended_layers:
        print(f"\n✓ Converged at {recommended_layers} layers")
        print(f"→ Recommended: {recommended_layers} layers")
    else:
        print("\n✗ NOT CONVERGED - consider testing thicker slabs")
        if thicknesses:
            print(f"→ Maximum tested: {thicknesses[-1]} layers")

    print("═" * 70 + "\n")


def plot_thickness_convergence(
    workgraph: Union[int, str, WorkGraph],
    save_path: Optional[str] = None,
    figsize: tuple[float, float] = (8, 6),
    dpi: int = 150,
):
    """
    Plot thickness convergence curve for slab calculations.

    Creates a figure showing surface energy vs number of layers with:
    - Convergence threshold band
    - Recommended thickness marked with vertical line

    Args:
        workgraph: WorkGraph PK (int), PK as string, or WorkGraph object
        save_path: Optional path to save the figure (PNG, PDF, etc.)
        figsize: Figure size in inches (width, height)
        dpi: Resolution for saved figure

    Returns:
        matplotlib.figure.Figure: The figure object for further customization

    Example:
        >>> from quantum_lego.core.common.convergence import plot_thickness_convergence
        >>> fig = plot_thickness_convergence(12345)
        >>> fig = plot_thickness_convergence(wg, save_path='thickness_conv.png')
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError(
            "matplotlib is required for plotting. "
            "Install with: pip install matplotlib"
        )

    from .workgraph import get_thickness_convergence_results

    wg = _load_workgraph(workgraph)
    results = get_thickness_convergence_results(wg)
    formula, n_atoms, miller_indices = _get_thickness_structure_info(wg)

    # Extract data
    conv_results = results.get('convergence_results')
    if not conv_results:
        raise ValueError("No convergence results available")

    summary = conv_results.get('summary', {})
    thicknesses = summary.get('thicknesses', [])
    surface_energies = summary.get('surface_energies_J_m2', [])
    threshold = summary.get('convergence_threshold', 0.01)
    recommended_layers = results.get('recommended_layers')

    if not thicknesses or not surface_energies:
        raise ValueError("No thickness data available for plotting")

    # Create figure
    fig, ax = plt.subplots(figsize=figsize)

    # Plot data
    ax.plot(thicknesses, surface_energies, 'o-', color='#1f77b4',
            markersize=10, linewidth=2, label='Surface energy')

    # Add threshold band (around the last point as reference)
    if len(surface_energies) > 0:
        ref_energy = surface_energies[-1]
        ax.axhspan(
            ref_energy - threshold, ref_energy + threshold,
            color='#d62728', alpha=0.2,
            label=f'Threshold (±{threshold * 1000:.1f} mJ/m²)'
        )

    # Mark recommended thickness
    if recommended_layers:
        ax.axvline(x=recommended_layers, color='#2ca02c', linestyle=':',
                   linewidth=2, label=f'Recommended ({recommended_layers} layers)')

    # Labels and formatting
    ax.set_xlabel('Number of Layers', fontsize=12)
    ax.set_ylabel('Surface Energy (J/m²)', fontsize=12)

    miller_str = f"({miller_indices[0]} {miller_indices[1]} {miller_indices[2]})"
    ax.set_title(
        f'Thickness Convergence: {formula} {miller_str}',
        fontsize=14, fontweight='bold'
    )

    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Set x-axis to show only integer ticks
    if thicknesses:
        ax.set_xticks(thicknesses)

    plt.tight_layout()

    # Save if requested
    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches='tight')
        logger.info(f"Thickness convergence plot saved to: {save_path}")

    return fig


def export_thickness_convergence_data(
    workgraph: Union[int, str, WorkGraph],
    output_dir: str,
    prefix: str = 'thickness_conv',
) -> dict[str, str]:
    """
    Export thickness convergence data to CSV and JSON files.

    Creates:
    - {prefix}.csv: Thickness convergence data (layers, gamma, delta, converged)
    - {prefix}_summary.json: Summary with recommendations

    Args:
        workgraph: WorkGraph PK (int), PK as string, or WorkGraph object
        output_dir: Directory to save output files
        prefix: Prefix for output filenames (default: 'thickness_conv')

    Returns:
        dict: Mapping of file types to file paths created

    Example:
        >>> from quantum_lego.core.common.convergence import export_thickness_convergence_data
        >>> files = export_thickness_convergence_data(12345, '/path/to/output')
        >>> print(files)
        {'csv': '/path/to/output/thickness_conv.csv', 'summary_json': '...'}
    """
    from .workgraph import get_thickness_convergence_results

    wg = _load_workgraph(workgraph)
    results = get_thickness_convergence_results(wg)
    formula, n_atoms, miller_indices = _get_thickness_structure_info(wg)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    created_files = {}

    # Extract data
    conv_results = results.get('convergence_results')
    if not conv_results:
        raise ValueError("No convergence results available")

    summary = conv_results.get('summary', {})
    thicknesses = summary.get('thicknesses', [])
    surface_energies = summary.get('surface_energies_J_m2', [])
    threshold = summary.get('convergence_threshold', 0.01)
    recommended_layers = results.get('recommended_layers')
    converged = results.get('converged', False)

    # ===== Export CSV =====
    csv_path = output_path / f'{prefix}.csv'

    with open(csv_path, 'w') as f:
        f.write("# Thickness Convergence Data\n")
        f.write(f"# Structure: {formula} ({n_atoms} atoms)\n")
        f.write(f"# Miller indices: ({miller_indices[0]} {miller_indices[1]} {miller_indices[2]})\n")
        f.write(f"# Threshold: {threshold * 1000:.2f} mJ/m²\n")
        f.write("layers,gamma_J_m2,delta_mJ_m2,converged\n")

        for i, (layers, gamma) in enumerate(zip(thicknesses, surface_energies)):
            if i == 0:
                delta_mJ = 0.0
                is_converged = False
            else:
                delta = abs(gamma - surface_energies[i - 1])
                delta_mJ = delta * 1000  # Convert to mJ/m²
                is_converged = delta < threshold

            converged_str = "True" if is_converged else "False"
            f.write(f"{layers},{gamma:.6f},{delta_mJ:.4f},{converged_str}\n")

    created_files['csv'] = str(csv_path)
    logger.info(f"Thickness data exported to: {csv_path}")

    # ===== Export Summary JSON =====
    summary_json = output_path / f'{prefix}_summary.json'

    summary_dict = {
        'structure': {
            'formula': formula,
            'n_atoms': n_atoms,
        },
        'miller_indices': miller_indices,
        'convergence_threshold_J_m2': threshold,
        'convergence_threshold_mJ_m2': threshold * 1000,
        'converged': converged,
        'recommended_layers': recommended_layers,
        'max_tested_layers': thicknesses[-1] if thicknesses else None,
        'thickness_data': {
            'layers': thicknesses,
            'surface_energies_J_m2': surface_energies,
        },
        'bulk_energy_eV': results.get('bulk_energy'),
    }

    with open(summary_json, 'w') as f:
        json.dump(summary_dict, f, indent=2)

    created_files['summary_json'] = str(summary_json)
    logger.info(f"Summary exported to: {summary_json}")

    return created_files
