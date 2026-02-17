#!/usr/bin/env python3
"""
Surface thermodynamics analysis (binary oxide)
=============================================

Plots surface Gibbs free energies (gamma) vs oxygen chemical potential (Delta_mu_O)
from the quantum-lego sequential WorkGraph outputs produced by
`calculos/surface_thermo/run_surface_thermo_prepare.py`.

For a binary oxide, the surface energy depends only on the oxygen chemical potential:
    gamma(Delta_mu_O) = phi - Gamma_O * Delta_mu_O

Reference style/script:
    PS-TEROS: examples/binary_surface_thermo/results/plot_surface_thermodynamics.py
"""

import os

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from aiida import load_profile
from aiida.orm import load_node


# -----------------------------------------------------------------------------
# Configuration (override via env vars if desired)
# -----------------------------------------------------------------------------

AIIDA_PROFILE = os.environ.get("AIIDA_PROFILE", "presto")
WORKFLOW_PK = int(os.environ.get("WORKFLOW_PK", "54684"))

MATERIAL_NAME = os.environ.get("MATERIAL_NAME", "SnO2")
SURFACE_MILLER = os.environ.get("SURFACE_MILLER", "(110)")

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FORMAT = os.environ.get("OUTPUT_FORMAT", "pdf")

FIGURE_DPI = 150
TERMINATION_COLORS = sns.color_palette("deep", 10)


# -----------------------------------------------------------------------------
# Optional T scale (same convention as the PS-TEROS example script)
# -----------------------------------------------------------------------------

KB_EV = 8.617333262e-5
S_O2_298K = 0.002126  # eV/K per O2 molecule
DELTA_MU_O_REF = -0.27  # eV


def T_from_delta_mu_O(delta_mu_O, P_atm=1.0, delta_mu_O_ref=DELTA_MU_O_REF):
    """Approximate temperature from Delta_mu_O at 1 atm (ideal gas, simplified inversion)."""
    T_ref = 298.15
    T = T_ref - 2 * (delta_mu_O - delta_mu_O_ref) / S_O2_298K
    return max(T, 100)


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------

def _find_surface_gibbs_namespace(wg) -> dict:
    """Return the nested output namespace that contains surface_gibbs_energy outputs."""
    for stage_label in wg.outputs:
        stage_ns = wg.outputs[stage_label]
        if isinstance(stage_ns, dict) and "surface_gibbs_energy" in stage_ns:
            brick_ns = stage_ns["surface_gibbs_energy"]
            if isinstance(brick_ns, dict) and "surface_energies" in brick_ns:
                return brick_ns
    raise KeyError(
        "Could not find surface_gibbs_energy outputs in WorkGraph outputs. "
        "Expected a stage namespace containing 'surface_gibbs_energy.surface_energies'."
    )


def load_surface_energies(workflow_pk: int) -> dict:
    """Load per-termination gamma(Delta_mu_O) curves from the finished WorkGraph."""
    wg = load_node(workflow_pk)

    if wg.process_state.value != "finished":
        raise RuntimeError(f"Workflow {workflow_pk} not finished: {wg.process_state.value}")

    brick_ns = _find_surface_gibbs_namespace(wg)
    oxide_type = brick_ns["oxide_type"].value
    if oxide_type != "binary":
        raise NotImplementedError(
            f"This plotting script is for binary oxides (gamma vs Delta_mu_O). "
            f"Got oxide_type={oxide_type!r}."
        )

    result = {}
    for term_label in brick_ns["surface_energies"]:
        term_data = brick_ns["surface_energies"][term_label].get_dict()
        data_source = term_data.get("primary", term_data)

        result[term_label] = {
            "delta_mu_O_range": np.array(data_source["delta_mu_O_range"], dtype=float),
            "gamma_array": np.array(data_source["gamma_array"], dtype=float),
            "phi": float(data_source["phi"]),
            "Gamma_O": float(data_source["Gamma_O"]),
            "gamma_O_rich": float(data_source["gamma_O_rich"]),
            "gamma_O_poor": float(data_source["gamma_O_poor"]),
            "element_M": data_source.get("element_M", "M"),
            # Extra info
            "area_A2": term_data.get("area_A2"),
            "E_slab_eV": term_data.get("E_slab_eV"),
            "slab_atom_counts": term_data.get("slab_atom_counts", {}),
        }

    return result


# -----------------------------------------------------------------------------
# Plotting helpers (ported from the PS-TEROS example script)
# -----------------------------------------------------------------------------

def plot_gamma_vs_mu_O(material_name: str, surface_miller: str, all_term_data: dict, output_path: str) -> None:
    """Plot gamma vs Delta_mu_O (binary oxide)."""
    fig, ax = plt.subplots(figsize=(8, 6), dpi=FIGURE_DPI)

    term_labels = sorted(all_term_data.keys())
    for i, term_label in enumerate(term_labels):
        data = all_term_data[term_label]
        delta_mu_O = data["delta_mu_O_range"]
        gamma = data["gamma_array"]

        color = TERMINATION_COLORS[i % len(TERMINATION_COLORS)]
        term_number = int(term_label.split("_")[1]) + 1
        ax.plot(delta_mu_O, gamma, "-", color=color, linewidth=2.0, label=f"T{term_number}")

    ax.set_xlabel(r"$\Delta\mu_{\rm O}$ (eV)")
    ax.set_ylabel(r"$\gamma$ (J/m$^2$)")

    # Secondary axis: approximate temperature at 1 atm
    x_min, x_max = ax.get_xlim()
    mu_ticks = np.arange(np.ceil(x_min * 2) / 2, np.floor(x_max * 2) / 2 + 0.25, 0.5)
    mu_ticks = mu_ticks[(mu_ticks >= x_min - 0.1) & (mu_ticks <= x_max + 0.1)]

    ax_temp = ax.secondary_xaxis("top")
    ax_temp.set_xlabel("Temperature (K) @ 1 atm")
    ax_temp.set_xticks(mu_ticks)
    ax_temp.set_xticklabels([f"{int(T_from_delta_mu_O(mu))}" for mu in mu_ticks])

    ax.legend(loc="best", framealpha=0.95, title=f"{material_name} {surface_miller}")
    plt.tight_layout()
    fig.subplots_adjust(top=0.88)
    plt.savefig(output_path, format=OUTPUT_FORMAT, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {output_path}")


def print_summary_table(all_term_data: dict) -> None:
    """Print a quick summary table for binary oxide terminations."""
    print("\n" + "=" * 70)
    print("SURFACE ENERGY SUMMARY")
    print("=" * 70)
    print(f"{'Term':<8} {'phi (J/m2)':<12} {'gamma_O-poor':<14} {'gamma_O-rich':<14} {'Gamma_O':<12}")
    print("-" * 70)
    for term_label in sorted(all_term_data.keys()):
        data = all_term_data[term_label]
        term_number = int(term_label.split("_")[1]) + 1
        print(
            f"T{term_number:<7} {data['phi']:<12.4f} {data['gamma_O_poor']:<14.4f} "
            f"{data['gamma_O_rich']:<14.4f} {data['Gamma_O']:<12.6f}"
        )
    print("-" * 70)
    print("Units: gamma in J/m^2, Gamma_O in atoms/A^2")
    print("=" * 70 + "\n")


def export_data_to_csv(all_term_data: dict, output_path: str) -> None:
    """Export gamma(Delta_mu_O) curves to a CSV file."""
    term_labels = sorted(all_term_data.keys())
    delta_mu_O = all_term_data[term_labels[0]]["delta_mu_O_range"]

    header = ["delta_mu_O_eV"]
    for term_label in term_labels:
        term_number = int(term_label.split("_")[1]) + 1
        header.append(f"gamma_T{term_number}_Jm2")

    data = np.zeros((len(delta_mu_O), len(term_labels) + 1))
    data[:, 0] = delta_mu_O
    for i, term_label in enumerate(term_labels):
        data[:, i + 1] = all_term_data[term_label]["gamma_array"]

    np.savetxt(output_path, data, delimiter=",", header=",".join(header), comments="")
    print(f"Exported: {output_path}")


def main() -> int:
    sns.set_style("whitegrid")
    sns.set_context("paper", font_scale=1.2)

    print(f"Loading AiiDA profile: {AIIDA_PROFILE}")
    load_profile(profile=AIIDA_PROFILE)

    print(f"Loading workflow data (PK: {WORKFLOW_PK})...")
    surf_energies = load_surface_energies(WORKFLOW_PK)
    print(f"Found {len(surf_energies)} termination(s): {list(surf_energies.keys())}")

    print_summary_table(surf_energies)

    safe_name = MATERIAL_NAME.lower().replace(" ", "_")
    miller_safe = SURFACE_MILLER.replace("(", "").replace(")", "")

    out_1d = os.path.join(OUTPUT_DIR, f"{safe_name}_{miller_safe}_gamma_vs_muO.{OUTPUT_FORMAT}")
    plot_gamma_vs_mu_O(MATERIAL_NAME, SURFACE_MILLER, surf_energies, out_1d)

    out_csv = os.path.join(OUTPUT_DIR, f"{safe_name}_{miller_safe}_surface_energies.csv")
    export_data_to_csv(surf_energies, out_csv)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

