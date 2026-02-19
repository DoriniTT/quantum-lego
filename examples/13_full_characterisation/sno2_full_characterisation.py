#!/usr/bin/env python
"""Complete SnO2 characterisation workflow — six phases in a single WorkGraph.

This example demonstrates combining every major quantum-lego brick type into
one fully automated pipeline for rutile SnO2:

  Phase 1 – Ground state (rough relax → Birch-Murnaghan EOS → full relax)
      initial_relax → volume_scan → eos_fit → eos_refine → bulk_relax

  Phase 2 – Hubbard U (linear-response on 2×2×2 supercell)
      hub_ground_state → hub_response → hub_analysis

  Phase 3 – Hybrid DOS + band structure (HSE06)
      hse_prerelax → hse_bands → hse_dos

  Phase 4 – Surface enumeration (pure Python, no VASP)
      enumerate_surfaces

  Phase 5 – Surface thermodynamics for each orientation
      sn_relax + o2_ref + dhf (shared references)
      slab_terms_{hkl} → slab_relax_{hkl} → surface_gibbs_{hkl}

  Phase 6 – Fukui f+/f- on the most stable termination
      select_stable_{hkl} → fukui_batch_{hkl} → fukui_plus_{hkl} + fukui_minus_{hkl}

WorkGraph detects data dependencies automatically.  Phases without shared
data edges (e.g. Phase 1 and Phase 2) run in parallel.

Expected parallel schedule:
  T=0 : initial_relax, hub_ground_state, sn_relax, o2_ref
  T=1 : volume_scan, hub_response
  T=2 : eos_fit, hub_analysis
  T=3 : eos_refine
  T=4 : bulk_relax
  T=5 : hse_prerelax, enumerate_surfaces, dhf, slab_terms_{hkl}
  T=6 : hse_bands, hse_dos, slab_relax_{hkl}
  T=7 : surface_gibbs_{hkl}
  T=8 : select_stable_{hkl}
  T=9 : fukui_batch_{hkl}
  T=10: fukui_plus_{hkl}, fukui_minus_{hkl}

API functions: quick_vasp_sequential, print_sequential_results
Difficulty: advanced (production)
Cluster: obelix (VASP-6.5.1-idefix-4@obelix)
Usage:
    python examples/13_full_characterisation/sno2_full_characterisation.py

After completion:
    from quantum_lego import print_sequential_results
    print_sequential_results(<PK>)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from ase.io import read
from aiida import orm
from pymatgen.core import Structure
from pymatgen.core.surface import get_symmetrically_distinct_miller_indices

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples._shared.config import (  # noqa: E402
    STRUCTURES_DIR,
    setup_profile,
)
from quantum_lego import quick_vasp_sequential, print_sequential_results  # noqa: E402
from quantum_lego.core.common.u_calculation.utils import prepare_perturbed_structure  # noqa: E402

# ---------------------------------------------------------------------------
# Cluster configuration (obelix, hybrid MPI+OpenMP)
# Change code_label and options to run on a different cluster.
# ---------------------------------------------------------------------------
CODE_LABEL = 'VASP-6.5.1-idefix-4@obelix'

OBELIX_OPTIONS = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 4,   # 4 MPI × 22 OMP on 88 cores
    },
    'custom_scheduler_commands': (
        '#PBS -l cput=90000:00:00\n'
        '#PBS -l nodes=1:ppn=88:skylake\n'
        '#PBS -j oe\n'
        '#PBS -N sno2_full'
    ),
}

POTENTIAL_FAMILY = 'PBE'
POTENTIAL_MAPPING = {
    'Sn':  'Sn_d',
    'Sn1': 'Sn_d',   # unperturbed Sn in Hubbard supercell
    'O':   'O',
    'H':   'H',
}

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------
# Phase 1/3–6: SnO2 primitive cell
sno2_atoms  = read(str(STRUCTURES_DIR / 'sno2.vasp'))
sno2_prim   = orm.StructureData(ase=sno2_atoms)

# Phase 2: 2×2×2 supercell with a single Sn split into 'Sn' (perturbed)
# and 'Sn1' (unperturbed) for linear-response Hubbard U
_pmg_super = Structure.from_file(str(STRUCTURES_DIR / 'sno2.vasp'))
_pmg_super.make_supercell([2, 2, 2])           # 16 Sn + 32 O = 48 atoms
_super_aiida = orm.StructureData(pymatgen=_pmg_super)
split_supercell, _, _ = prepare_perturbed_structure(_super_aiida, target_species='Sn')

# Phase 5: reference structures (Sn metal, H2, H2O)
ref_sn  = orm.StructureData(ase=read(str(STRUCTURES_DIR / 'Sn.cif')))
ref_h2  = orm.StructureData(ase=read(str(STRUCTURES_DIR / 'H2.cif')))
ref_h2o = orm.StructureData(ase=read(str(STRUCTURES_DIR / 'H2O.cif')))

# Pre-enumerate Miller indices at submission time so we can build the stage
# list in a plain Python loop (the WorkGraph enumerate_surfaces stage still
# runs as an in-graph verification step).
_pmg_sno2   = Structure.from_file(str(STRUCTURES_DIR / 'sno2.vasp'))
miller_list  = get_symmetrically_distinct_miller_indices(_pmg_sno2, max_index=1)
print(f'Miller indices (max_index=1): {miller_list}')


def hkl_str(hkl: tuple) -> str:
    """Convert a Miller tuple to a safe stage-name suffix: (1,1,0) → '110'."""
    return ''.join(str(abs(h)) for h in hkl)


# ---------------------------------------------------------------------------
# Phase 1: BM volume scan — pre-build 7 scaled structures
# ---------------------------------------------------------------------------
_base_vol = sno2_atoms.get_volume()
_strains  = np.linspace(-0.06, 0.06, 7)

volume_calcs: dict = {}   # {label: {'structure': StructureData}}
volume_map:   dict = {}   # {label: volume_Å³}

for _strain in _strains:
    _sign  = 'm' if _strain < 0 else 'p'
    _label = f'v_{_sign}{abs(_strain * 100):03.0f}'
    _sf    = (1.0 + _strain) ** (1.0 / 3.0)
    _scaled = sno2_atoms.copy()
    _scaled.set_cell(sno2_atoms.cell * _sf, scale_atoms=True)
    volume_calcs[_label] = {'structure': orm.StructureData(ase=_scaled)}
    volume_map[_label]   = _scaled.get_volume()

# ---------------------------------------------------------------------------
# INCAR blocks
# ---------------------------------------------------------------------------

# ── Phase 1 ─────────────────────────────────────────────────────────────────
ROUGH_RELAX_INCAR = {
    'encut': 520, 'ediff': 1e-4, 'ediffg': -0.05,
    'nsw': 50, 'ibrion': 2, 'isif': 3,
    'ismear': 0, 'sigma': 0.05,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lwave': False, 'lcharg': False,
}

BM_SCF_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'nsw': 0, 'ibrion': -1,
    'ismear': 0, 'sigma': 0.05,
    'prec': 'Accurate', 'lreal': False,
}

BULK_RELAX_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'nsw': 80, 'ibrion': 2, 'isif': 3,
    'ismear': 0, 'sigma': 0.05,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lwave': False, 'lcharg': False,
}

# ── Phase 2: Hubbard U ───────────────────────────────────────────────────────
HUB_BASE_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'ismear': 0, 'sigma': 0.05,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lmaxmix': 4,                        # required for d-electrons
}

HUB_GS_INCAR = {
    **HUB_BASE_INCAR,
    'nsw': 0, 'ibrion': -1,
    'ldau': True, 'ldautype': 3,
    'ldaul': [2, -1, -1],
    'ldauu': [0.0, 0.0, 0.0],
    'ldauj': [0.0, 0.0, 0.0],
    'lorbit': 11,
    'lwave': True, 'lcharg': True,
}

# ── Phase 3: HSE06 ──────────────────────────────────────────────────────────
_HSE_COMMON = {
    'encut': 500, 'ediff': 1e-5,
    'prec': 'Accurate', 'ncore': 4,
    'ispin': 1, 'lasph': True, 'lreal': 'Auto',
}

GGA_PRE_INCAR = {
    **_HSE_COMMON,
    'algo': 'Fast', 'ismear': 0, 'sigma': 0.05,
    'nsw': 0, 'ibrion': -1,
    'lwave': True, 'lcharg': False,
}

HSE_SCF_INCAR = {
    **_HSE_COMMON,
    'algo': 'Normal', 'nelm': 120,
    'ismear': 0, 'sigma': 0.01, 'lorbit': 11,
    'lhfcalc': True, 'hfscreen': 0.2, 'gga': 'PE',
    'lwave': True, 'lcharg': True,
}

HSE_DOS_INCAR = {
    **_HSE_COMMON,
    'algo': 'Normal', 'nelm': 100,
    'ismear': 0, 'sigma': 0.01, 'lorbit': 11,
    'lhfcalc': True, 'hfscreen': 0.2, 'gga': 'PE',
    'lreal': False,
    'nedos': 2000, 'emin': -10.0, 'emax': 10.0,
    'lwave': False, 'lcharg': False,
}

# ── Phase 5: reference + slab relaxations ───────────────────────────────────
SN_RELAX_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'nsw': 80, 'ibrion': 2, 'isif': 3,
    'ismear': 1, 'sigma': 0.2,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lwave': False, 'lcharg': False,
}

H2_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'nsw': 60, 'ibrion': 2, 'isif': 2,
    'ismear': 0, 'sigma': 0.05, 'ispin': 1,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lwave': False, 'lcharg': False,
}

H2O_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'nsw': 80, 'ibrion': 2, 'isif': 2,
    'ismear': 0, 'sigma': 0.05, 'ispin': 1,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lwave': False, 'lcharg': False,
}

SLAB_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'nsw': 80, 'ibrion': 2, 'isif': 2,   # ions only (fixed cell)
    'ismear': 0, 'sigma': 0.05,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lwave': False, 'lcharg': False,
}

# ── Phase 6: Fukui static SCF ────────────────────────────────────────────────
FUKUI_INCAR = {
    'encut': 520, 'ediff': 1e-6,
    'nsw': 0, 'ibrion': -1,
    'ismear': 0, 'sigma': 0.05,
    'prec': 'Accurate', 'lreal': 'Auto',
    'lwave': False, 'lcharg': True,      # CHGCAR required for fukui_analysis
}

# ---------------------------------------------------------------------------
# Stage list
# ---------------------------------------------------------------------------
stages = [

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 1 – GROUND STATE
    # ════════════════════════════════════════════════════════════════════════

    # 1. Quick ISIF=3 relax to bring cell close to equilibrium before EOS scan
    {
        'name': 'initial_relax',
        'type': 'vasp',
        'structure_from': 'input',
        'incar': ROUGH_RELAX_INCAR,
        'kpoints_spacing': 0.03,
        'restart': None,
    },

    # 2. Static SCF at 7 volume points for the coarse BM scan
    {
        'name': 'volume_scan',
        'type': 'batch',
        'structure_from': 'input',
        'base_incar': BM_SCF_INCAR,
        'kpoints_spacing': 0.03,
        'calculations': volume_calcs,
    },

    # 3. Fit coarse Birch-Murnaghan EOS → V0, E0, B0, B0'
    {
        'name': 'eos_fit',
        'type': 'birch_murnaghan',
        'batch_from': 'volume_scan',
        'volumes': volume_map,
    },

    # 4. Refine EOS with ±2 % / 7 points around V0
    {
        'name': 'eos_refine',
        'type': 'birch_murnaghan_refine',
        'eos_from': 'eos_fit',
        'structure_from': 'initial_relax',
        'base_incar': BM_SCF_INCAR,
        'kpoints_spacing': 0.03,
        'refine_strain_range': 0.02,
        'refine_n_points': 7,
    },

    # 5. Full ionic + cell relaxation starting from the refined V0 cell
    {
        'name': 'bulk_relax',
        'type': 'vasp',
        'structure_from': 'eos_refine',
        'incar': BULK_RELAX_INCAR,
        'kpoints_spacing': 0.03,
        'restart': None,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 2 – HUBBARD U  (independent of Phase 1 structure chain)
    # ════════════════════════════════════════════════════════════════════════

    # 6. Ground-state on the split 2×2×2 supercell (U = 0, lorbit=11)
    {
        'name': 'hub_ground_state',
        'type': 'vasp',
        'structure': split_supercell,
        'incar': HUB_GS_INCAR,
        'kpoints_spacing': 0.03,
        'retrieve': ['OUTCAR'],
        'restart': None,
    },

    # 7. Eight response calculations (±0.05 … ±0.20 eV perturbations)
    {
        'name': 'hub_response',
        'type': 'hubbard_response',
        'ground_state_from': 'hub_ground_state',
        'structure_from': 'hub_ground_state',
        'target_species': 'Sn',
        'potential_values': [-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20],
        'ldaul': 2,
        'incar': HUB_BASE_INCAR,
        'kpoints_spacing': 0.03,
    },

    # 8. Linear regression → U(Sn-d) in eV
    {
        'name': 'hub_analysis',
        'type': 'hubbard_analysis',
        'response_from': 'hub_response',
        'structure_from': 'hub_ground_state',
        'target_species': 'Sn',
        'ldaul': 2,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 3 – HYBRID FUNCTIONAL (HSE06)
    # ════════════════════════════════════════════════════════════════════════

    # 9. PBE pre-SCF to seed WAVECAR
    {
        'name': 'hse_prerelax',
        'type': 'vasp',
        'structure_from': 'bulk_relax',
        'incar': GGA_PRE_INCAR,
        'kpoints_spacing': 0.05,
        'restart': None,
    },

    # 10. HSE06 band structure (seekpath k-path)
    {
        'name': 'hse_bands',
        'type': 'hybrid_bands',
        'structure_from': 'bulk_relax',
        'scf_incar': HSE_SCF_INCAR,
        'band_settings': {
            'band_mode': 'seekpath-aiida',
            'symprec': 1e-4,
            'band_kpoints_distance': 0.05,
            'kpoints_per_split': 90,
            'hybrid_reuse_wavecar': False,
            'additional_band_analysis_parameters': {
                'with_time_reversal': True,
                'threshold': 1e-5,
            },
        },
        'kpoints_spacing': 0.05,
    },

    # 11. HSE06 DOS (separate stage — VaspHybridBandsWorkChain skips DOS)
    {
        'name': 'hse_dos',
        'type': 'dos',
        'structure_from': 'bulk_relax',
        'scf_incar': HSE_SCF_INCAR,
        'dos_incar': HSE_DOS_INCAR,
        'kpoints_spacing': 0.05,
        'dos_kpoints_spacing': 0.04,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 4 – SURFACE ENUMERATION (verification step, no VASP)
    # ════════════════════════════════════════════════════════════════════════

    # 12. Enumerate symmetrically distinct low-index surfaces (max_index=1)
    {
        'name': 'enumerate_surfaces',
        'type': 'surface_enumeration',
        'structure_from': 'bulk_relax',
        'max_index': 1,
        'symprec': 0.1,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 5 – SHARED THERMODYNAMIC REFERENCES (start at T=0)
    # ════════════════════════════════════════════════════════════════════════

    # 13. Relax Sn metal reference
    {
        'name': 'sn_relax',
        'type': 'vasp',
        'structure': ref_sn,
        'incar': SN_RELAX_INCAR,
        'kpoints_spacing': 0.03,
        'restart': None,
    },

    # 14. O2 reference energy via water-splitting thermochemistry
    {
        'name': 'o2_ref',
        'type': 'o2_reference_energy',
        'h2_structure': ref_h2,
        'h2o_structure': ref_h2o,
        'h2_incar': H2_INCAR,
        'h2o_incar': H2O_INCAR,
        'kpoints': [1, 1, 1],
    },

    # 15. Formation enthalpy ΔHf(SnO2) — shared by all surface_gibbs stages
    {
        'name': 'dhf',
        'type': 'formation_enthalpy',
        'structure_from': 'bulk_relax',
        'energy_from': 'bulk_relax',
        'references': {
            'Sn': 'sn_relax',
            'O': 'o2_ref',
        },
    },
]

# ════════════════════════════════════════════════════════════════════════════
# PHASES 5 (cont.) + 6 — per-orientation loop
# Appends 7 stages per Miller index:
#   slab_terms, slab_relax, surface_gibbs,
#   select_stable, fukui_batch, fukui_plus, fukui_minus
# ════════════════════════════════════════════════════════════════════════════

DELTA_N_MAP = {
    'neutral':   0.00,
    'delta_005': 0.05,
    'delta_010': 0.10,
    'delta_015': 0.15,
}

for _hkl in miller_list:
    _s = hkl_str(_hkl)

    stages += [
        # Generate all symmetrized slab terminations
        {
            'name': f'slab_terms_{_s}',
            'type': 'surface_terminations',
            'structure_from': 'bulk_relax',
            'miller_indices': list(_hkl),
            'min_slab_size': 18.0,
            'min_vacuum_size': 15.0,
            'lll_reduce': True,
            'center_slab': True,
            'primitive': True,
            'reorient_lattice': True,
        },

        # Relax all terminations simultaneously (dynamic_batch)
        {
            'name': f'slab_relax_{_s}',
            'type': 'dynamic_batch',
            'structures_from': f'slab_terms_{_s}',
            'base_incar': SLAB_INCAR,
            'kpoints_spacing': 0.05,
        },

        # Compute γ(ΔμSn, ΔμO) for every termination
        {
            'name': f'surface_gibbs_{_s}',
            'type': 'surface_gibbs_energy',
            'bulk_structure_from': 'bulk_relax',
            'bulk_energy_from': 'bulk_relax',
            'slab_structures_from': f'slab_relax_{_s}',
            'slab_energies_from': f'slab_relax_{_s}',
            'formation_enthalpy_from': 'dhf',
            'sampling': 100,
        },

        # Pick termination with minimum φ at ΔμSn=ΔμO=0
        {
            'name': f'select_stable_{_s}',
            'type': 'select_stable_surface',
            'summary_from': f'surface_gibbs_{_s}',
            'structures_from': f'slab_relax_{_s}',
        },

        # 8 fractional-charge SCFs (4 for f-, 4 for f+)
        {
            'name': f'fukui_batch_{_s}',
            'type': 'fukui_dynamic',
            'structure_from': f'select_stable_{_s}',
            'base_incar': FUKUI_INCAR,
            'kpoints_spacing': 0.05,
            'retrieve': ['CHGCAR'],
        },

        # Interpolate f+(r) — electrophilic susceptibility
        {
            'name': f'fukui_plus_{_s}',
            'type': 'fukui_analysis',
            'batch_from': f'fukui_batch_{_s}',
            'fukui_type': 'plus',
            'delta_n_map': DELTA_N_MAP,
        },

        # Interpolate f-(r) — nucleophilic susceptibility
        {
            'name': f'fukui_minus_{_s}',
            'type': 'fukui_analysis',
            'batch_from': f'fukui_batch_{_s}',
            'fukui_type': 'minus',
            'delta_n_map': DELTA_N_MAP,
        },
    ]

print(f'Total stages: {len(stages)}  '
      f'(15 shared + {len(miller_list)} × 7 per-surface)')


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    setup_profile()

    result = quick_vasp_sequential(
        structure=sno2_prim,
        stages=stages,
        code_label=CODE_LABEL,
        kpoints_spacing=0.03,
        potential_family=POTENTIAL_FAMILY,
        potential_mapping=POTENTIAL_MAPPING,
        options=OBELIX_OPTIONS,
        max_concurrent_jobs=4,
        serialize_stages=False,
        name='sno2_full_characterisation',
    )

    pk = result['__workgraph_pk__']
    n  = len(stages)
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Total stages: {n}')
    print()
    print('Monitor:')
    print(f'  verdi process show {pk}')
    print(f'  verdi process report {pk}')
    print()
    print('After completion:')
    print(f'  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()
    print('Key outputs:')
    print('  Phase 1 → bulk_relax:           equilibrium structure + energy')
    print('  Phase 2 → hub_analysis:          U(Sn-d) in eV, R²')
    print('  Phase 3 → hse_bands / hse_dos:  HSE06 band gap, DOS')
    print('  Phase 4 → enumerate_surfaces:   distinct Miller indices')
    for _hkl in miller_list:
        _s = hkl_str(_hkl)
        print(f'  Phase 5/6 {_hkl}:')
        print(f'    surface_gibbs_{_s}:  γ(ΔμSn,ΔμO) per termination')
        print(f'    select_stable_{_s}:  most stable termination')
        print(f'    fukui_plus_{_s}:     f+(r) CHGCAR_FUKUI.vasp')
        print(f'    fukui_minus_{_s}:    f-(r) CHGCAR_FUKUI.vasp')
