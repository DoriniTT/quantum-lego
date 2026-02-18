#!/usr/bin/env python
"""Plot Birch-Murnaghan EOS results from a completed WorkGraph.

Reads coarse and refined EOS data from exposed WorkGraph outputs and
generates two side-by-side plots with data points and fitted BM curves.

Usage:
    python plot_birch_murnaghan.py <workgraph_pk>
"""

import sys
import numpy as np
import matplotlib.pyplot as plt
from aiida import load_profile, orm

load_profile(profile='presto')


def birch_murnaghan_energy(v, v0, e0, b0, b1):
    """Third-order Birch-Murnaghan equation of state.

    Args:
        v: Volume(s) in Angstrom^3.
        v0: Equilibrium volume (Angstrom^3).
        e0: Equilibrium energy (eV).
        b0: Bulk modulus (eV/Angstrom^3).
        b1: Pressure derivative of bulk modulus.

    Returns:
        Energy(ies) in eV.
    """
    eta = (v0 / v) ** (2.0 / 3.0)
    return e0 + (9.0 * v0 * b0 / 16.0) * (
        (eta - 1.0) ** 3 * b1 + (eta - 1.0) ** 2 * (6.0 - 4.0 * eta)
    )


def plot_eos(ax, eos_dict, title):
    """Plot a single EOS panel.

    Args:
        ax: Matplotlib axes.
        eos_dict: Dict from fit_birch_murnaghan_eos.
        title: Panel title.
    """
    volumes = np.array(eos_dict['volumes'])
    energies = np.array(eos_dict['energies'])
    v0 = eos_dict['v0']
    e0 = eos_dict['e0']
    b0 = eos_dict['b0_eV_per_A3']
    b1 = eos_dict['b1']
    b0_GPa = eos_dict['b0_GPa']
    rms = eos_dict['rms_residual_eV']

    # Smooth fitted curve
    v_min = volumes.min() - 0.5
    v_max = volumes.max() + 0.5
    v_fit = np.linspace(v_min, v_max, 200)
    e_fit = birch_murnaghan_energy(v_fit, v0, e0, b0, b1)

    # Plot
    ax.plot(v_fit, e_fit, '-', color='#2563eb', linewidth=1.5, label='BM fit')
    ax.plot(volumes, energies, 'o', color='#dc2626', markersize=6,
            markeredgecolor='black', markeredgewidth=0.5, label='DFT data')
    ax.axvline(v0, color='#9ca3af', linestyle='--', linewidth=0.8, alpha=0.7)

    # Annotation box
    text = (
        f'$V_0$ = {v0:.4f} $\\AA^3$\n'
        f'$E_0$ = {e0:.6f} eV\n'
        f'$B_0$ = {b0_GPa:.2f} GPa\n'
        f"$B_0'$ = {b1:.2f}\n"
        f'RMS = {rms:.2e} eV'
    )
    if 'recommended_label' in eos_dict:
        text += f"\nClosest: {eos_dict['recommended_label']}"
        text += f" ({eos_dict['recommended_volume_error_pct']:.4f}%)"

    ax.text(0.03, 0.97, text, transform=ax.transAxes, fontsize=8,
            verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='wheat', alpha=0.8))

    ax.set_xlabel('Volume ($\\AA^3$)')
    ax.set_ylabel('Energy (eV)')
    ax.set_title(title)
    ax.legend(loc='lower right', fontsize=8)


def main():
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <workgraph_pk>')
        sys.exit(1)

    pk = int(sys.argv[1])
    wg_node = orm.load_node(pk)

    # Extract EOS results from exposed outputs
    coarse_eos = wg_node.outputs.s02_eos_fit.birch_murnaghan.eos_result
    refined_eos = wg_node.outputs.s03_eos_refine.birch_murnaghan_refine.eos_result

    coarse_dict = coarse_eos.get_dict()
    refined_dict = refined_eos.get_dict()

    # Create figure
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    plot_eos(ax1, coarse_dict, 'Coarse Birch-Murnaghan EOS')
    plot_eos(ax2, refined_dict, 'Refined Birch-Murnaghan EOS')

    fig.suptitle(f'SnO$_2$ Birch-Murnaghan EOS  (PK {pk})', fontsize=13)
    fig.tight_layout()

    outfile = f'birch_murnaghan_pk{pk}.pdf'
    fig.savefig(outfile, dpi=200)
    print(f'Saved: {outfile}')

    # Print summary
    print(f'\nCoarse:  V0 = {coarse_dict["v0"]:.4f} A^3,  '
          f'B0 = {coarse_dict["b0_GPa"]:.2f} GPa,  '
          f'RMS = {coarse_dict["rms_residual_eV"]:.2e} eV')
    print(f'Refined: V0 = {refined_dict["v0"]:.4f} A^3,  '
          f'B0 = {refined_dict["b0_GPa"]:.2f} GPa,  '
          f'RMS = {refined_dict["rms_residual_eV"]:.2e} eV')
    dv = abs(coarse_dict['v0'] - refined_dict['v0'])
    print(f'V0 difference: {dv:.4f} A^3 ({dv / coarse_dict["v0"] * 100:.4f}%)')


if __name__ == '__main__':
    main()
