#!/usr/bin/env python
"""SnO2(110) binary oxide surface thermodynamics (single WorkGraph).

API functions: quick_vasp_sequential
Difficulty: advanced
Usage:
    python examples/06_surface/binary_surface_thermo/run_surface_thermo_prepare.py

Workflow:
  1) Relax bulk SnO2 (vasp)
  2) Relax Sn reference (vasp)
  3) Compute O2 reference energy via water splitting (o2_reference_energy: H2 + H2O)
  4) Generate all symmetrized SnO2(110) slab terminations (surface_terminations)
  5) Relax all terminations in parallel (dynamic_batch)
  6) Compute bulk formation enthalpy ΔHf(SnO2) (formation_enthalpy)
  7) Compute surface Gibbs free energies γ(ΔμO) for each termination (surface_gibbs_energy)
"""

from __future__ import annotations

from pathlib import Path

from ase.io import read
from aiida import orm

from examples._shared.config import (
    DEFAULT_VASP_CODE,
    LOCALWORK_OPTIONS,
    SNO2_POTCAR,
    setup_profile,
)
from examples._shared.structures import load_sno2
from quantum_lego import quick_vasp_sequential


STRUCT_DIR = Path(__file__).resolve().parent / "structures"

# --- Structures ---
bulk_sno2 = load_sno2()
ref_sn = orm.StructureData(ase=read(STRUCT_DIR / "Sn.cif"))
ref_h2 = orm.StructureData(ase=read(STRUCT_DIR / "H2.cif"))
ref_h2o = orm.StructureData(ase=read(STRUCT_DIR / "H2O.cif"))


# --- INCAR presets (edit to match your standards) ---
bulk_incar = {
    "encut": 520,
    "ediff": 1e-6,
    "nsw": 80,
    "ibrion": 2,
    "isif": 3,
    "ismear": 0,
    "sigma": 0.05,
    "prec": "Accurate",
    "lreal": "Auto",
    "lwave": False,
    "lcharg": False,
}

sn_incar = {
    "encut": 520,
    "ediff": 1e-6,
    "nsw": 80,
    "ibrion": 2,
    "isif": 3,
    "ismear": 1,
    "sigma": 0.2,
    "prec": "Accurate",
    "lreal": "Auto",
    "lwave": False,
    "lcharg": False,
}

h2_incar = {
    "encut": 520,
    "ediff": 1e-6,
    "nsw": 60,
    "ibrion": 2,
    "isif": 2,
    "ismear": 0,
    "sigma": 0.05,
    "ispin": 1,
    "prec": "Accurate",
    "lreal": "Auto",
    "lwave": False,
    "lcharg": False,
}

h2o_incar = {
    "encut": 520,
    "ediff": 1e-6,
    "nsw": 80,
    "ibrion": 2,
    "isif": 2,
    "ismear": 0,
    "sigma": 0.05,
    "ispin": 1,
    "prec": "Accurate",
    "lreal": "Auto",
    "lwave": False,
    "lcharg": False,
}

slab_incar = {
    "encut": 520,
    "ediff": 1e-6,
    "nsw": 80,
    "ibrion": 2,
    "isif": 2,
    "ismear": 0,
    "sigma": 0.05,
    "prec": "Accurate",
    "lreal": "Auto",
    "lwave": False,
    "lcharg": False,
}


stages = [
    # Bulk SnO2 relaxation
    {
        "name": "bulk_relax",
        "type": "vasp",
        "incar": bulk_incar,
        "restart": None,
        "kpoints_spacing": 0.03,
    },
    # Reference: Sn
    {
        "name": "sn_relax",
        "type": "vasp",
        "structure": ref_sn,
        "incar": sn_incar,
        "restart": None,
        "kpoints_spacing": 0.03,
    },
    # Reference: O2 via water splitting (H2 + H2O), gamma-only
    {
        "name": "o2_ref",
        "type": "o2_reference_energy",
        "h2_structure": ref_h2,
        "h2o_structure": ref_h2o,
        "h2_incar": h2_incar,
        "h2o_incar": h2o_incar,
        "kpoints": [1, 1, 1],
    },
    # Generate all SnO2(110) terminations (18 A slab, 15 A vacuum by default)
    {
        "name": "slab_terms",
        "type": "surface_terminations",
        "structure_from": "bulk_relax",
        "miller_indices": [1, 1, 0],
        "min_slab_size": 18.0,
        "min_vacuum_size": 15.0,
        "lll_reduce": True,
        "center_slab": True,
        "primitive": True,
        "reorient_lattice": True,
    },
    # Relax all terminations in parallel (dynamic fan-out)
    {
        "name": "slab_relax",
        "type": "dynamic_batch",
        "structures_from": "slab_terms",
        "base_incar": slab_incar,
        "kpoints_spacing": 0.05,
    },
    # Bulk formation enthalpy ΔHf(SnO2), with oxygen reference from o2_ref
    {
        "name": "dhf",
        "type": "formation_enthalpy",
        "structure_from": "bulk_relax",
        "energy_from": "bulk_relax",
        "references": {
            "Sn": "sn_relax",
            "O": "o2_ref",
        },
    },
    # Surface Gibbs free energies γ(ΔμO) for each termination (binary oxide case)
    {
        "name": "surface_gibbs",
        "type": "surface_gibbs_energy",
        "bulk_structure_from": "bulk_relax",
        "bulk_energy_from": "bulk_relax",
        "slab_structures_from": "slab_relax",
        "slab_energies_from": "slab_relax",
        "formation_enthalpy_from": "dhf",
        "sampling": 100,
    },
]


if __name__ == "__main__":
    setup_profile()

    # Extend the canonical SnO2 POTCAR mapping with hydrogen for H2/H2O references.
    potcar_mapping = dict(SNO2_POTCAR["mapping"])
    potcar_mapping["H"] = "H"

    result = quick_vasp_sequential(
        structure=bulk_sno2,
        stages=stages,
        code_label=DEFAULT_VASP_CODE,
        kpoints_spacing=0.03,
        potential_family=SNO2_POTCAR["family"],
        potential_mapping=potcar_mapping,
        options=LOCALWORK_OPTIONS,
        max_concurrent_jobs=4,
        name="example_sno2_surface_thermo_binary",
    )

    pk = result["__workgraph_pk__"]
    print(f"Submitted WorkGraph PK: {pk}")
    print(f"Monitor with: verdi process show {pk}")
    print(f"Detailed report: verdi process report {pk}")

