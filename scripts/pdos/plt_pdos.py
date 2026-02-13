#!/usr/bin/env python3
"""Plot PDOS por elemento para todos os cálculos de superfície do Ag2MoO4.

Uso: forneça apenas o PK do WorkGraph principal. O script extrai
automaticamente todos os sub-nós (dos.retrieved, scf.misc) percorrendo
os links de saída do WorkGraph.

Saída: results/pdos/<surface>_<config>_pdos.{png,pdf,csv}
"""

import re
import shutil
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from aiida import load_profile, orm
from aiida.common.links import LinkType
from pymatgen.electronic_structure.core import Spin
from pymatgen.io.vasp.outputs import Vasprun

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
PROFILE        = 'presto'
WORKGRAPH_PK   = 46202        # PK do WorkGraph principal

ENERGY_RANGE   = (-5.0, 3.0)  # janela de energia relativa ao E_F (eV)

ELEMENT_COLORS = {
    'Ag': '#808080',
    'Mo': '#009688',
    'O':  '#1565C0',
    'H':  '#E53935',
}

# ---------------------------------------------------------------------------
# Extração automática dos PKs a partir do WorkGraph
# ---------------------------------------------------------------------------

def _parse_dos_step(label: str):
    """Tenta extrair (surface, config) de um label como 's07_dos_011_h2o'.

    Retorna (surface, config) ou None se o label não corresponder.
    """
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

    # Filtra apenas os cálculos com todos os campos necessários
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
# Plot
# ---------------------------------------------------------------------------

def plot_pdos(surface: str, config: str, pks: dict, out_dir: Path) -> None:
    label = f'{surface}_{config}'
    print(f'\n=== {label} ===')

    dos_folder = orm.load_node(pks['dos_retrieved_pk'])
    scf_folder = orm.load_node(pks['scf_retrieved_pk'])

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        efermi = get_efermi(pks['scf_misc_pk'], scf_folder, tmpdir)
        print(f'  E_fermi (SCF) = {efermi:.4f} eV')

        dos_vasprun_path = extract_file(dos_folder, 'vasprun.xml', tmpdir)
        vr = Vasprun(str(dos_vasprun_path), parse_dos=True, parse_eigen=False,
                     parse_potcar_file=False)

        cdos = vr.complete_dos
        energies = cdos.energies - efermi
        is_spin = len(cdos.densities) > 1

        element_dos = cdos.get_element_dos()
        elements = sorted(element_dos.keys(), key=lambda e: e.symbol)

        plt.rcParams.update({
            'font.family': 'serif',
            'font.size': 14,
            'axes.linewidth': 1.5,
            'xtick.direction': 'in',
            'ytick.direction': 'in',
            'xtick.minor.visible': True,
            'ytick.minor.visible': True,
        })

        fig, ax = plt.subplots(figsize=(9, 6))

        # TDOS (fundo semitransparente)
        tdos_up = cdos.densities.get(Spin.up, np.zeros_like(energies))
        tdos_dn = cdos.densities.get(Spin.down, np.zeros_like(energies))
        ax.fill_between(energies,  tdos_up,  color='lightgray', alpha=0.5,
                        label='TDOS')
        if is_spin:
            ax.fill_between(energies, -tdos_dn, color='lightgray', alpha=0.5)

        # Máscara da janela de energia para calcular os limites do eixo y
        e_lo, e_hi = ENERGY_RANGE
        mask = (energies >= e_lo) & (energies <= e_hi)

        csv_data: dict = {'Energy_eV': energies}
        peak_pos = 0.0   # maior valor positivo dentro da janela
        peak_neg = 0.0   # maior valor absoluto negativo dentro da janela

        for elem in elements:
            color = ELEMENT_COLORS.get(elem.symbol)
            dos_obj = element_dos[elem]
            up = dos_obj.densities.get(Spin.up, np.zeros_like(energies))
            dn = dos_obj.densities.get(Spin.down, np.zeros_like(energies))

            ax.plot(energies,  up, color=color, lw=1.8,
                    label=f'{elem.symbol} ↑' if is_spin else elem.symbol)
            if is_spin:
                ax.plot(energies, -dn, color=color, lw=1.8, ls='--',
                        label=f'{elem.symbol} ↓')

            # Picos dentro da janela
            peak_pos = max(peak_pos, float(np.max(up[mask])))
            if is_spin:
                peak_neg = max(peak_neg, float(np.max(dn[mask])))

            csv_data[f'{elem.symbol}_up'] = up
            if is_spin:
                csv_data[f'{elem.symbol}_dn'] = dn

        # Inclui também o TDOS na estimativa dos limites
        peak_pos = max(peak_pos, float(np.max(tdos_up[mask])))
        if is_spin:
            peak_neg = max(peak_neg, float(np.max(tdos_dn[mask])))

        ax.axvline(0, color='black', ls='--', lw=1.2, alpha=0.7)
        ax.axhline(0, color='black', lw=0.8, alpha=0.5)

        ax.set_xlim(ENERGY_RANGE)
        y_max = peak_pos * 1.10
        y_min = -peak_neg * 1.10 if is_spin else 0.0
        ax.set_ylim(y_min, y_max)
        ax.set_xlabel('$E - E_F$ (eV)', fontsize=15)
        ax.set_ylabel('DOS (states/eV)' + (' ↑ / ↓' if is_spin else ''),
                      fontsize=15)
        ax.text(0.02, 0.97, '$E_F = 0$ eV', transform=ax.transAxes,
                fontsize=12, va='top',
                bbox=dict(facecolor='white', alpha=0.8, boxstyle='round,pad=0.3'))
        ax.legend(loc='upper right', fontsize=11, framealpha=0.9,
                  edgecolor='gray', ncol=2 if is_spin else 1)

        fig.tight_layout()
        out_prefix = out_dir / f'{label}_pdos'
        fig.savefig(f'{out_prefix}.png', dpi=300, bbox_inches='tight')
        fig.savefig(f'{out_prefix}.pdf', bbox_inches='tight')
        plt.close(fig)

        df = pd.DataFrame(csv_data)
        df.to_csv(f'{out_prefix}.csv', index=False)
        print(f'  Salvo: {out_prefix}.png / .pdf / .csv')

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_profile(PROFILE)

    out_dir = Path(__file__).parent / 'pdos'
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f'Extraindo cálculos do WorkGraph PK={WORKGRAPH_PK}...')
    calcs = build_calcs_from_workgraph(WORKGRAPH_PK)
    print(f'  Encontrados {len(calcs)} cálculos DOS: '
          f'{sorted(calcs.keys())}')

    for (surface, config), pks in sorted(calcs.items()):
        try:
            plot_pdos(surface, config, pks, out_dir)
        except Exception as exc:
            print(f'  ERRO em {surface}_{config}: {exc}')

    print('\nConcluído. Figuras em:', out_dir)


if __name__ == '__main__':
    main()
