#!/usr/bin/env python3
"""
Surface thermodynamics plotting (binary oxide)
=============================================

Plots surface Gibbs free energies (gamma) vs oxygen chemical potential (Delta_mu_O)
from the Quantum Lego sequential WorkGraph output of the
`binary_surface_thermo` example.

Usage:
    python examples/06_surface/binary_surface_thermo/plot_surface_thermodynamics.py --pk <PK>
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import matplotlib.pyplot as plt
from aiida.orm import load_node

from examples._shared.config import setup_profile


def _maybe_set_style():
    try:
        import seaborn as sns  # type: ignore

        sns.set_style("whitegrid")
        sns.set_context("paper", font_scale=1.2)
    except Exception:
        pass


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
        }

    return result


def plot_gamma_vs_mu_O(all_term_data: dict, output_path: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    term_labels = sorted(all_term_data.keys())

    for term_label in term_labels:
        data = all_term_data[term_label]
        delta_mu_O = data["delta_mu_O_range"]
        gamma = data["gamma_array"]
        term_number = int(term_label.split("_")[1]) + 1
        ax.plot(delta_mu_O, gamma, "-", linewidth=2.0, label=f"T{term_number}")

    ax.set_xlabel(r"$\Delta\mu_{\rm O}$ (eV)")
    ax.set_ylabel(r"$\gamma$ (J/m$^2$)")
    ax.legend(loc="best", framealpha=0.95)

    plt.tight_layout()
    plt.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {output_path}")


def export_data_to_csv(all_term_data: dict, output_path: str) -> None:
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--pk", type=int, default=int(os.environ.get("WORKFLOW_PK", "0")))
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()

    if args.pk <= 0:
        parser.error("Provide --pk <WORKGRAPH_PK> (or set WORKFLOW_PK env var)")

    setup_profile(args.profile)
    _maybe_set_style()

    data = load_surface_energies(args.pk)
    out_dir = os.path.dirname(os.path.abspath(__file__))
    plot_gamma_vs_mu_O(data, os.path.join(out_dir, "gamma_vs_muO.pdf"))
    export_data_to_csv(data, os.path.join(out_dir, "surface_energies.csv"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

