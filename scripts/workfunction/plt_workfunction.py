#!/usr/bin/env python3
"""Calcula e plota a função de trabalho para todos os cálculos de superfície do Ag2MoO4.

Uso: forneça apenas o PK do WorkGraph principal. O script extrai
automaticamente todos os sub-nós (dos.retrieved, scf.misc) percorrendo
os links de saída do WorkGraph.

Usa pymatgen.analysis.surface_analysis.WorkFunctionAnalyzer para calcular
Φ = E_vac − E_F.

Saída: results/workfunction/<surface>_<config>_wf.{png,pdf}
       results/workfunction/workfunction_summary.csv
"""

import re
import shutil
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch

from aiida import load_profile, orm
from aiida.common.links import LinkType
from pymatgen.analysis.surface_analysis import WorkFunctionAnalyzer
from pymatgen.io.vasp.outputs import Locpot, Vasprun

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
PROFILE       = 'presto'
WORKGRAPH_PK  = 46202    # PK do WorkGraph principal

# ---------------------------------------------------------------------------
# Extração automática dos PKs a partir do WorkGraph
# ---------------------------------------------------------------------------

def _parse_dos_step(label: str):
    """Extrai (surface, config) de labels como 's07_dos_011_h2o'."""
    m = re.match(r's\d+_dos_(\d+)_(.+)', label)
    if m:
        return m.group(1), m.group(2)
    return None


def build_calcs_from_workgraph(wg_pk: int) -> dict:
    """Percorre os links de saída do WorkGraph e monta o mapeamento

    {(surface, config): {'dos_retrieved_pk': ..., 'scf_retrieved_pk': ...,
                          'scf_misc_pk': ...}}
    """
    wg = orm.load_node(wg_pk)
    calcs: dict = {}

    for link in wg.base.links.get_outgoing(link_type=LinkType.RETURN).all():
        label = link.link_label          # e.g. 's07_dos_011_h2o__scf__misc'
        parts = label.split('__')
        if len(parts) < 3:
            continue
        step, sub, field = parts[0], parts[1], parts[2]
        parsed = _parse_dos_step(step)
        if parsed is None:
            continue
        surface, config = parsed
        key = (surface, config)
        calcs.setdefault(key, {})

        if sub == 'scf' and field == 'retrieved':
            calcs[key]['scf_retrieved_pk'] = link.node.pk
        elif sub == 'scf' and field == 'misc':
            calcs[key]['scf_misc_pk'] = link.node.pk
        elif sub == 'dos' and field == 'retrieved':
            calcs[key]['dos_retrieved_pk'] = link.node.pk

    complete = {
        k: v for k, v in calcs.items()
        if all(f in v for f in ('dos_retrieved_pk', 'scf_retrieved_pk', 'scf_misc_pk'))
    }
    return complete

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_file(folder_data: orm.FolderData, filename: str,
                 dest_dir: Path) -> Path:
    dest = dest_dir / filename
    with folder_data.open(filename, 'rb') as src, open(dest, 'wb') as dst:
        shutil.copyfileobj(src, dst)
    return dest


def get_efermi(scf_misc_pk: int, scf_folder: orm.FolderData,
               tmpdir: Path) -> float:
    """Obtém E_fermi: tenta o Dict misc do AiiDA, depois vasprun.xml (parse_dos=True)."""
    misc = orm.load_node(scf_misc_pk)
    d = misc.get_dict()
    if 'efermi' in d and d['efermi'] is not None:
        return float(d['efermi'])

    print('    [aviso] efermi não encontrado no misc Dict – lendo vasprun.xml...')
    vasprun_path = extract_file(scf_folder, 'vasprun.xml', tmpdir)
    vr = Vasprun(str(vasprun_path), parse_dos=True, parse_eigen=False,
                 parse_potcar_file=False)
    if vr.efermi is None:
        raise ValueError('Não foi possível obter efermi do misc Dict nem do vasprun.xml')
    return float(vr.efermi)

# ---------------------------------------------------------------------------
# Cálculo e gráfico
# ---------------------------------------------------------------------------

def compute_workfunction(surface: str, config: str, pks: dict,
                         out_dir: Path) -> dict:
    label = f'{surface}_{config}'
    print(f'\n=== {label} ===')

    dos_folder = orm.load_node(pks['dos_retrieved_pk'])
    scf_folder = orm.load_node(pks['scf_retrieved_pk'])

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        efermi = get_efermi(pks['scf_misc_pk'], scf_folder, tmpdir)
        print(f'  E_fermi (SCF) = {efermi:.4f} eV')

        locpot_path = extract_file(dos_folder, 'LOCPOT', tmpdir)
        locpot = Locpot.from_file(str(locpot_path))

    locpot_along_c = locpot.get_average_along_axis(2)
    structure = locpot.structure

    wfa = WorkFunctionAnalyzer(
        structure=structure,
        locpot_along_c=locpot_along_c,
        efermi=efermi,
    )

    phi     = wfa.work_function
    e_vac   = wfa.vacuum_locpot
    lc      = structure.lattice.c
    z_coords = np.array(wfa.along_c) * lc

    print(f'  E_vac         = {e_vac:.4f} eV')
    print(f'  Φ             = {phi:.4f} eV')

    _plot_wf(z_coords, np.array(locpot_along_c), efermi, e_vac, phi,
             label, out_dir)

    return {'surface': surface, 'config': config,
            'efermi_eV': efermi, 'e_vac_eV': e_vac, 'phi_eV': phi}


def _plot_wf(z: np.ndarray, zavg: np.ndarray, efermi: float, e_vac: float,
             phi: float, label: str, out_dir: Path) -> None:
    plt.rcParams.update({
        'font.family': 'serif',
        'font.size': 13,
        'axes.linewidth': 1.5,
        'xtick.direction': 'in',
        'ytick.direction': 'in',
        'xtick.minor.visible': True,
        'ytick.minor.visible': True,
    })

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(z, zavg, color='#1565C0', lw=2.0,
            label=r'$\langle V \rangle_{xy}(z)$')
    ax.axhline(efermi, color='#E53935', ls='--', lw=1.8,
               label=f'$E_F = {efermi:.3f}$ eV')
    ax.axhline(e_vac, color='#2E7D32', ls='--', lw=1.8,
               label=f'$E_{{\\mathrm{{vac}}}} = {e_vac:.3f}$ eV')

    arrow_x = 0.87 * float(z[-1])
    ax.add_patch(FancyArrowPatch(
        (arrow_x, efermi), (arrow_x, e_vac),
        arrowstyle='<|-|>', color='#FF6F00', lw=2.0, mutation_scale=18,
    ))
    ax.text(arrow_x + 0.4, (efermi + e_vac) / 2.0,
            f'$\\Phi = {phi:.3f}$ eV',
            fontsize=13, color='#FF6F00', va='center',
            bbox=dict(facecolor='white', alpha=0.85,
                      boxstyle='round,pad=0.35', edgecolor='#FF6F00'))

    _annotate_slab_vacuum(ax, z, zavg, e_vac)

    ax.set_xlabel('$z$ (Å)', fontsize=15)
    ax.set_ylabel('Electrostatic potential (eV)', fontsize=15)
    ax.set_xlim(float(z[0]), float(z[-1]))
    ax.legend(loc='lower right', fontsize=11, framealpha=0.9, edgecolor='gray')

    fig.tight_layout()
    out_prefix = out_dir / f'{label}_wf'
    fig.savefig(f'{out_prefix}.png', dpi=300, bbox_inches='tight')
    fig.savefig(f'{out_prefix}.pdf', bbox_inches='tight')
    plt.close(fig)
    print(f'  Saved: {out_prefix}.png / .pdf')


def _annotate_slab_vacuum(ax: plt.Axes, z: np.ndarray, zavg: np.ndarray,
                           e_vac: float) -> None:
    threshold = e_vac - 2.0
    in_slab = zavg < threshold
    idx = np.where(in_slab)[0]
    if len(idx) == 0:
        return

    z_start = float(z[idx[0]])
    z_end   = float(z[idx[-1]])

    ax.axvspan(float(z[0]),   z_start, alpha=0.08, color='steelblue')
    ax.axvspan(z_start,        z_end,  alpha=0.08, color='sienna')
    ax.axvspan(z_end,  float(z[-1]),   alpha=0.08, color='steelblue')

    ylim   = ax.get_ylim()
    y_text = ylim[1] - 0.04 * (ylim[1] - ylim[0])
    ax.text(z_start / 2,                  y_text, 'Vacuum', ha='center',
            va='top', fontsize=10, color='steelblue', alpha=0.8)
    ax.text((z_start + z_end) / 2,        y_text, 'Slab',  ha='center',
            va='top', fontsize=10, color='sienna',    alpha=0.9)
    ax.text((z_end + float(z[-1])) / 2,   y_text, 'Vacuum', ha='center',
            va='top', fontsize=10, color='steelblue', alpha=0.8)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_profile(PROFILE)

    out_dir = Path(__file__).parent / 'workfunction'
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f'Extraindo cálculos do WorkGraph PK={WORKGRAPH_PK}...')
    calcs = build_calcs_from_workgraph(WORKGRAPH_PK)
    print(f'  Encontrados {len(calcs)} cálculos DOS: '
          f'{sorted(calcs.keys())}')

    rows = []
    for (surface, config), pks in sorted(calcs.items()):
        try:
            row = compute_workfunction(surface, config, pks, out_dir)
            rows.append(row)
        except Exception as exc:
            print(f'  ERRO em {surface}_{config}: {exc}')

    if rows:
        df = pd.DataFrame(rows)
        df = df.sort_values(['surface', 'config']).reset_index(drop=True)
        csv_path = out_dir / 'workfunction_summary.csv'
        df.to_csv(csv_path, index=False, float_format='%.4f')
        print(f'\nResumo salvo em: {csv_path}')
        print(df.to_string(index=False))

    print('\nConcluído. Figuras em:', out_dir)


if __name__ == '__main__':
    main()
