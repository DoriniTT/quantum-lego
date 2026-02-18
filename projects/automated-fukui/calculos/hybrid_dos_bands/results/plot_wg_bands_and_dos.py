#!/usr/bin/env python
"""Plot band structure + DOS from a finished WorkGraph.

Example:
    python plot_wg_bands_and_dos.py 54995 --profile presto
"""

from __future__ import annotations

import argparse
import os
import tempfile

import numpy as np
from aiida import load_profile, orm
from aiida.common.links import LinkType
from aiida.orm.nodes.data.array.bands import BandsData

from pymatgen.electronic_structure.core import Spin
from pymatgen.io.vasp import Vasprun

import matplotlib

matplotlib.use('Agg')
import matplotlib.gridspec as gridspec  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workgraph_pk', type=int, help='PK of the WorkGraph node')
    parser.add_argument('--profile', default='presto', help='AiiDA profile to load (default: presto)')
    parser.add_argument(
        '--output',
        default=None,
        help='Output image path (default: bands_dos_<PK>.pdf)',
    )
    parser.add_argument(
        '--dos-sigma',
        type=float,
        default=0.1,
        help='Gaussian smearing (sigma, eV) applied to DOS/PDOS curves (default: 0.1). Use 0 to disable.',
    )
    parser.add_argument(
        '--reference',
        choices=('fermi', 'vbm'),
        default='fermi',
        help='Energy reference for E=0 (default: fermi)',
    )
    parser.add_argument(
        '--y-range',
        nargs=2,
        type=float,
        metavar=('YMIN', 'YMAX'),
        default=(-5.0, 5.0),
        help='Y-axis range in eV (default: -5 5)',
    )
    return parser.parse_args()


def _get_vbm_from_bands(bands: orm.BandsData) -> float | None:
    energies, occupations = bands.get_bands(also_occupations=True)
    if occupations is None:
        return None
    occupied = energies[occupations > 0.1]
    return float(np.max(occupied)) if occupied.size else None


def _get_dos_from_vasprun(retrieved: orm.FolderData) -> tuple[object, dict[str, object], float, bool]:
    """Return (pymatgen tdos, element_dos, efermi, is_spin)."""
    if 'vasprun.xml' not in retrieved.list_object_names():
        raise FileNotFoundError(f"vasprun.xml not found in retrieved folder PK={retrieved.pk}")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.xml', encoding='utf-8') as tmp:
            tmp.write(retrieved.get_object_content('vasprun.xml'))
            tmp_path = tmp.name
        # Avoid POTCAR warnings: we only need DOS + Efermi.
        vrun = Vasprun(
            tmp_path,
            parse_eigen=False,
            parse_projected_eigen=False,
            parse_potcar_file=False,
        )
        element_dos: dict[str, object] = {}
        try:
            complete_dos = vrun.complete_dos
            if complete_dos is not None:
                for element, dos in complete_dos.get_element_dos().items():
                    element_dos[element.symbol] = dos
        except Exception:
            element_dos = {}
        return vrun.tdos, element_dos, float(vrun.efermi), bool(vrun.is_spin)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def main() -> None:
    args = _parse_args()
    load_profile(profile=args.profile)

    wg = orm.load_node(args.workgraph_pk)
    bands = None
    dos_retrieved = None

    # Default output paths for this repo's `run_hybrid_dos_bands.py` example.
    try:
        bands = wg.outputs.s02_hse_bands.bands.band_structure
    except Exception:
        pass
    try:
        dos_retrieved = wg.outputs.s03_hse_dos.dos.retrieved
    except Exception:
        pass

    # Fallback: scan exposed RETURN outputs (e.g. if stage names differ).
    if bands is None or dos_retrieved is None:
        for link in wg.base.links.get_outgoing(link_type=LinkType.RETURN).all():
            node = link.node
            if bands is None and isinstance(node, BandsData):
                bands = node
            if dos_retrieved is None and isinstance(node, orm.FolderData):
                names = set(node.list_object_names())
                if 'vasprun.xml' in names and 'DOSCAR' in names:
                    dos_retrieved = node

    if bands is None:
        raise RuntimeError('Could not find a BandsData node in WorkGraph outputs.')
    if dos_retrieved is None:
        raise RuntimeError('Could not find a DOS retrieved FolderData (with vasprun.xml + DOSCAR) in WorkGraph outputs.')

    tdos, element_dos, dos_efermi, is_spin_dos = _get_dos_from_vasprun(dos_retrieved)

    if args.reference == 'vbm':
        y_origin = _get_vbm_from_bands(bands) or dos_efermi
        y_label = r'$E - E_{VBM}$ (eV)' if y_origin != dos_efermi else r'$E - E_F$ (eV)'
    else:
        y_origin = dos_efermi
        y_label = r'$E - E_F$ (eV)'

    # --- Setup figure ---
    output = args.output or f'bands_dos_{args.workgraph_pk}.pdf'
    fig = plt.figure(figsize=(10, 6), dpi=150)
    gs = gridspec.GridSpec(1, 2, width_ratios=[2.0, 1.2], wspace=0.05)
    ax_bs = fig.add_subplot(gs[0])
    ax_dos = fig.add_subplot(gs[1], sharey=ax_bs)

    # --- Bands (left) ---
    bs_plot = bands._get_bandplot_data(cartesian=False, y_origin=y_origin)
    x_coords = np.asarray(bs_plot['x'])
    y_coords = np.asarray(bs_plot['y'])

    for iband in range(y_coords.shape[1]):
        ax_bs.plot(x_coords, y_coords[:, iband], color='#004488', lw=1.2)

    labels = bs_plot.get('labels', [])
    xtick_locs = [x for x, _ in labels]
    xtick_labs = [lab.replace('GAMMA', 'Γ') for _, lab in labels]
    ax_bs.set_xticks(xtick_locs)
    ax_bs.set_xticklabels(xtick_labs)
    for x_loc in xtick_locs:
        ax_bs.axvline(x_loc, ls='--', color='#AAAAAA', lw=0.8)

    ax_bs.set_xlim(x_coords[0], x_coords[-1])
    ax_bs.set_xlabel('Symmetry path')
    ax_bs.set_ylabel(y_label)

    # --- DOS (right) ---
    dos_energies = np.asarray(tdos.energies) - y_origin
    dos_sigma = float(args.dos_sigma)
    if dos_sigma > 0:
        tdos_up = np.asarray(tdos.get_smeared_densities(dos_sigma)[Spin.up])
    else:
        tdos_up = np.asarray(tdos.densities[Spin.up])

    # Plot TDOS first (thicker, neutral color)
    ax_dos.plot(tdos_up, dos_energies, color='#444444', lw=1.6, label='TDOS')
    ax_dos.fill_betweenx(dos_energies, 0.0, tdos_up, color='#888888', alpha=0.12)

    # Plot element-projected DOS (PDOS)
    element_curves: dict[str, np.ndarray] = {}
    for idx, symbol in enumerate(sorted(element_dos.keys())):
        dos_obj = element_dos[symbol]
        if dos_sigma > 0:
            dens = np.asarray(dos_obj.get_smeared_densities(dos_sigma)[Spin.up])
        else:
            dens = np.asarray(dos_obj.densities[Spin.up])
        element_curves[symbol] = dens

        color = plt.cm.tab10(idx % 10)
        ax_dos.plot(dens, dos_energies, color=color, lw=1.1, label=f'{symbol} PDOS')

    plt.setp(ax_dos.get_yticklabels(), visible=False)
    ax_dos.set_xlabel('DOS')
    if element_curves:
        ax_dos.legend(frameon=False, fontsize=9, loc='upper right')

    # --- Shared cosmetics ---
    for ax in (ax_bs, ax_dos):
        ax.set_ylim(args.y_range)
        ax.axhline(0.0, ls='--', color='#222222', lw=1.0)

    # DOS x-limits: scale to what is actually visible in the chosen energy window.
    # (Otherwise a large DOS peak far outside `--y-range` can flatten the plot.)
    y_min, y_max = args.y_range
    mask = (dos_energies >= y_min) & (dos_energies <= y_max)
    curves = [tdos_up] + list(element_curves.values())
    max_dos = 1.0
    for curve in curves:
        if curve.size == 0:
            continue
        if mask.any():
            curve = curve[mask]
        if curve.size:
            max_dos = max(max_dos, float(np.max(curve)))

    # Up-spin only: DOS is always positive.
    ax_dos.set_xlim(0.0, 1.1 * max_dos)

    fig.savefig(output, bbox_inches='tight')
    print(f'Wrote: {output}')


if __name__ == '__main__':
    main()
