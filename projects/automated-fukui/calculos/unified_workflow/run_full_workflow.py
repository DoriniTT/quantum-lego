#!/usr/bin/env python
"""Unified SnO2 characterisation workflow.

Combines six sequential phases into a single WorkGraph submission:

  Phase 1 – Ground state (rough relax → BM EOS → full ionic/cell relax)
      initial_relax → volume_scan → eos_fit → eos_refine → bulk_relax
      initial_relax (ISIF=3, loose convergence) brings ionic positions and
      cell to near-equilibrium before the BM scan, ensuring the volume
      sweep explores the correct energy basin.  eos_refine then uses the
      pre-relaxed cell as the scaling base for its refined volume points.
      bulk_relax performs the final tight ionic+cell relaxation at V0.

  Phase 2 – Hubbard U (linear response on 2×2×2 supercell)
      hub_ground_state → hub_response → hub_analysis
      Independent of Phase 1 structurally (uses pre-built split supercell).
      Runs in parallel with later phases after graph launch.

  Phase 3 – Hybrid DOS + band structure (HSE06)
      hse_prerelax → hse_bands → hse_dos
      Uses the relaxed bulk_relax structure from Phase 1.

  Phase 4 – Surface enumeration (pure Python, no VASP)
      enumerate_surfaces
      Identifies all symmetrically distinct low-index surfaces of the
      relaxed structure. Hard-coded max_index=1 → typically 5 for SnO2.

  Phase 5 – Surface thermodynamics for all enumerated orientations
      sn_relax + o2_ref (shared references)
      dhf (formation enthalpy, shared)
      Per-orientation loop (hkl in miller_list):
        slab_terms_{hkl} → slab_relax_{hkl} → surface_gibbs_{hkl}

  Phase 6 – Fukui +/- on the most stable termination per orientation
      Per-orientation loop (hkl in miller_list):
        select_stable_{hkl} (picks termination with min φ at ΔμM=ΔμO=0)
        fukui_batch_{hkl}   (8 VASP static SCFs: dN ∈ {0,±0.05,±0.10,±0.15})
        fukui_plus_{hkl}    (Fukui f+ interpolation)
        fukui_minus_{hkl}   (Fukui f- interpolation)

Note on parallelism
-------------------
WorkGraph detects data dependencies automatically.  Stages that share no
data edges run simultaneously.  Expected parallel groups at launch:
  T=0 : initial_relax, hub_ground_state, sn_relax, o2_ref
  T=1 : volume_scan (after initial_relax)
         hub_response (after hub_ground_state)
  T=2 : eos_fit (after volume_scan)
         hub_analysis (after hub_response)
  T=3 : eos_refine (after eos_fit)
  T=4 : bulk_relax (after eos_refine)
  T=5 : hse_prerelax, enumerate_surfaces (after bulk_relax)
         dhf  (after bulk_relax + sn_relax + o2_ref)
         slab_terms_{hkl} for all orientations (after bulk_relax)
  T=6 : hse_bands, hse_dos (after hse_prerelax)
         slab_relax_{hkl} for all orientations (after slab_terms_{hkl})
  T=7 : surface_gibbs_{hkl} for all orientations (after slab_relax_{hkl} + dhf)
  T=8 : select_stable_{hkl} (after surface_gibbs_{hkl} + slab_relax_{hkl})
  T=9 : fukui_batch_{hkl} (after select_stable_{hkl})
  T=10: fukui_plus_{hkl}, fukui_minus_{hkl} (after fukui_batch_{hkl})

Brick changes required
----------------------
  quantum_lego/core/bricks/__init__.py     – resolve_structure_from for BM + select_stable_surface
  quantum_lego/core/bricks/select_stable_surface.py  (new brick)
  quantum_lego/core/bricks/fukui_dynamic.py          (new brick)
  quantum_lego/core/bricks/fukui_analysis.py         – fukui_dynamic branch

Usage
-----
    python run_full_workflow.py

Requirements
------------
    aiida profile 'presto' configured with:
      - VASP-6.5.1-idefix-4@obelix code
      - PBE potential family (Sn_d, O, H pseudopotentials)
    Structure files (see STRUCT_DIR below)
"""

from __future__ import annotations

import numpy as np
from pathlib import Path
from datetime import datetime

from pymatgen.core import Structure
from pymatgen.core.surface import get_symmetrically_distinct_miller_indices
from ase.io import read
from aiida import orm, load_profile
from quantum_lego import quick_vasp_sequential, print_sequential_results
from quantum_lego.core.common.u_calculation.utils import prepare_perturbed_structure

load_profile(profile='presto')

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# All structures live in the surface_thermo structures folder (complete set).
STRUCT_DIR = Path(__file__).parent.parent / 'surface_thermo' / 'structures'

SNO2_VASP = STRUCT_DIR / 'sno2.vasp'
SN_CIF    = STRUCT_DIR / 'Sn.cif'
H2_CIF    = STRUCT_DIR / 'H2.cif'
H2O_CIF   = STRUCT_DIR / 'H2O.cif'

# ---------------------------------------------------------------------------
# Phase 1 structures: SnO2 primitive cell (main workflow input)
# ---------------------------------------------------------------------------
atoms     = read(str(SNO2_VASP))
sno2_prim = orm.StructureData(ase=atoms)

# ---------------------------------------------------------------------------
# Phase 2 structures: 2×2×2 supercell with single-atom species split
#
# One Sn atom → kind 'Sn'  (perturbed, receives LDAUU potential)
# Other 15 Sn → kind 'Sn1' (unperturbed, LDAUU = 0)
# Built at submission time from the primitive cell (standard practice – U is
# an electronic property insensitive to ~1 % volume differences).
# ---------------------------------------------------------------------------
pmg_supercell = Structure.from_file(str(SNO2_VASP))
pmg_supercell.make_supercell([2, 2, 2])           # 16 Sn + 32 O = 48 atoms
supercell_aiida = orm.StructureData(pymatgen=pmg_supercell)
split_supercell, _perturbed_kind, _unperturbed_kind = prepare_perturbed_structure(
    supercell_aiida, target_species='Sn'
)

# ---------------------------------------------------------------------------
# Phase 5/6 reference structures (shared across all orientations)
# ---------------------------------------------------------------------------
ref_sn  = orm.StructureData(ase=read(str(SN_CIF)))
ref_h2  = orm.StructureData(ase=read(str(H2_CIF)))
ref_h2o = orm.StructureData(ase=read(str(H2O_CIF)))

# ---------------------------------------------------------------------------
# Phase 5 – pre-enumerate all distinct low-index surface orientations
#
# We run pymatgen at submission time so we can build stage configs in a Python
# loop without AiiDA.  The WorkGraph enumerate_surfaces stage (Phase 4) still
# runs as a verification step.
# ---------------------------------------------------------------------------
pmg_sno2    = Structure.from_file(str(SNO2_VASP))
miller_list = get_symmetrically_distinct_miller_indices(pmg_sno2, max_index=1)
# Typical output for SnO2 rutile: (0,0,1), (1,0,0), (1,1,0), (1,0,1), (1,1,1)
print(f'Distinct low-index surfaces (max_index=1): {miller_list}')

def hkl_str(hkl: tuple) -> str:
    """Convert Miller index tuple to a safe stage-name suffix, e.g. (1,1,0) → '110'."""
    return ''.join(str(abs(h)) for h in hkl)

# ---------------------------------------------------------------------------
# INCAR blocks
# ---------------------------------------------------------------------------

# ── Phase 1: rough pre-relax (ISIF=3, loose convergence) ─────────────────
rough_relax_incar = {
    'encut': 520,
    'ediff': 1e-4,
    'ediffg': -0.05,
    'nsw': 50,
    'ibrion': 2,
    'isif': 3,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

# ── Phase 1: BM volume scan (static SCF, very accurate) ──────────────────
bm_scf_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 0,
    'ibrion': -1,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': False,
}

# ── Phase 1: bulk full relax (ionic + cell, ISIF=3) ──────────────────────
bulk_relax_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 3,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

# ── Phase 2: Hubbard U base INCAR (no LDAU – handled by the brick) ───────
hub_base_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lmaxmix': 4,
}

# ── Phase 3: HSE06 common settings ───────────────────────────────────────
hse_common = {
    'encut': 500,
    'ediff': 1e-5,
    'prec': 'Accurate',
    'ncore': 4,
    'ispin': 1,
    'lasph': True,
    'lreal': 'Auto',
}

hse_scf_incar = {
    **hse_common,
    'algo': 'Normal',
    'nelm': 120,
    'ismear': 0,
    'sigma': 0.01,
    'lorbit': 11,
    'lhfcalc': True,
    'hfscreen': 0.2,
    'gga': 'PE',
    'lwave': True,
    'lcharg': True,
}

hse_dos_incar = {
    **hse_common,
    'algo': 'Normal',
    'nelm': 100,
    'sigma': 0.01,
    'lhfcalc': True,
    'hfscreen': 0.2,
    'gga': 'PE',
    'ismear': 0,
    'lreal': False,
    'lorbit': 11,
    'nedos': 2000,
    'emin': -10.0,
    'emax': 10.0,
    'lwave': False,
    'lcharg': False,
}

# ── Phase 3: GGA pre-SCF (seeds WAVECAR for optional HSE restart) ─────────
gga_pre_incar = {
    'encut': 500,
    'ediff': 1e-5,
    'prec': 'Accurate',
    'ncore': 4,
    'algo': 'Fast',
    'ismear': 0,
    'sigma': 0.05,
    'nsw': 0,
    'ibrion': -1,
    'lwave': True,
    'lcharg': False,
}

# ── Phase 5: reference and slab relaxations ───────────────────────────────
sn_relax_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 3,
    'ismear': 1,
    'sigma': 0.2,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

h2_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 60,
    'ibrion': 2,
    'isif': 2,
    'ismear': 0,
    'sigma': 0.05,
    'ispin': 1,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

h2o_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 2,
    'ismear': 0,
    'sigma': 0.05,
    'ispin': 1,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

slab_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 80,
    'ibrion': 2,
    'isif': 2,          # relax ions only (cell shape fixed for slab)
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': False,
}

# ── Phase 6: Fukui static SCF (CHGCAR mandatory) ─────────────────────────
# NELECT is injected at runtime by the fukui_dynamic brick.
fukui_incar = {
    'encut': 520,
    'ediff': 1e-6,
    'nsw': 0,           # static SCF only
    'ibrion': -1,
    'ismear': 0,
    'sigma': 0.05,
    'prec': 'Accurate',
    'lreal': 'Auto',
    'lwave': False,
    'lcharg': True,     # CHGCAR required by fukui_analysis
}

# ---------------------------------------------------------------------------
# Phase 1: BM volume scan – pre-compute scaled structures
# ---------------------------------------------------------------------------
base_volume  = atoms.get_volume()
strains      = np.linspace(-0.06, 0.06, 7)
volume_calcs = {}   # {label: {'structure': StructureData}}
volume_map   = {}   # {label: volume_Å³}   – fed to the birch_murnaghan brick

for strain in strains:
    sign  = 'm' if strain < 0 else 'p'
    label = f'v_{sign}{abs(strain * 100):03.0f}'

    scale_factor = (1.0 + strain) ** (1.0 / 3.0)
    scaled       = atoms.copy()
    scaled.set_cell(atoms.cell * scale_factor, scale_atoms=True)

    volume_calcs[label] = {'structure': orm.StructureData(ase=scaled)}
    volume_map[label]   = scaled.get_volume()

# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
stages = [

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 1 – GROUND STATE (ROUGH RELAX + BM EOS + FULL RELAX)
    # ════════════════════════════════════════════════════════════════════════

    # 1. Rough ISIF=3 relax – bring positions and cell to near-equilibrium.
    {
        'name': 'initial_relax',
        'type': 'vasp',
        'structure_from': 'input',
        'incar': rough_relax_incar,
        'kpoints_spacing': 0.03,
        'restart': None,
    },

    # 2. Static SCF at 7 volume points (-6 % … +6 %)
    {
        'name': 'volume_scan',
        'type': 'batch',
        'structure_from': 'input',
        'base_incar': bm_scf_incar,
        'kpoints_spacing': 0.03,
        'calculations': volume_calcs,
    },

    # 3. Fit Birch-Murnaghan EOS → V0, E0, B0, B1
    {
        'name': 'eos_fit',
        'type': 'birch_murnaghan',
        'batch_from': 'volume_scan',
        'volumes': volume_map,
    },

    # 4. Refined BM scan (±2 % / 7 pts around V0) for tighter EOS.
    {
        'name': 'eos_refine',
        'type': 'birch_murnaghan_refine',
        'eos_from': 'eos_fit',
        'structure_from': 'initial_relax',
        'base_incar': bm_scf_incar,
        'kpoints_spacing': 0.03,
        'refine_strain_range': 0.02,
        'refine_n_points': 7,
    },

    # 5. Full ionic + cell relaxation at BM-recommended volume.
    {
        'name': 'bulk_relax',
        'type': 'vasp',
        'structure_from': 'eos_refine',
        'incar': bulk_relax_incar,
        'kpoints_spacing': 0.03,
        'restart': None,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 2 – HUBBARD U  (independent of Phase 1 structure chain)
    # ════════════════════════════════════════════════════════════════════════

    # 6. Ground state on the split 2×2×2 supercell (LDAUU=0, lorbit=11)
    {
        'name': 'hub_ground_state',
        'type': 'vasp',
        'structure': split_supercell,
        'incar': {
            **hub_base_incar,
            'nsw': 0,
            'ibrion': -1,
            'ldau': True,
            'ldautype': 3,
            'ldaul': [2, -1, -1],
            'ldauu': [0.0, 0.0, 0.0],
            'ldauj': [0.0, 0.0, 0.0],
            'lorbit': 11,
            'lwave': True,
            'lcharg': True,
        },
        'kpoints_spacing': 0.03,
        'retrieve': ['OUTCAR'],
        'restart': None,
    },

    # 7. Response calculations at 8 perturbation potentials (±0.05 … ±0.20 eV)
    {
        'name': 'hub_response',
        'type': 'hubbard_response',
        'ground_state_from': 'hub_ground_state',
        'structure_from': 'hub_ground_state',
        'target_species': 'Sn',
        'potential_values': [-0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.20],
        'ldaul': 2,
        'incar': hub_base_incar,
        'kpoints_spacing': 0.03,
    },

    # 8. Linear regression → Hubbard U (eV) + R²
    {
        'name': 'hub_analysis',
        'type': 'hubbard_analysis',
        'response_from': 'hub_response',
        'structure_from': 'hub_ground_state',
        'target_species': 'Sn',
        'ldaul': 2,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 3 – HYBRID DOS + BAND STRUCTURE (HSE06)
    # ════════════════════════════════════════════════════════════════════════

    # 9. GGA PBE static on relaxed structure
    {
        'name': 'hse_prerelax',
        'type': 'vasp',
        'structure_from': 'bulk_relax',
        'incar': gga_pre_incar,
        'kpoints_spacing': 0.05,
        'restart': None,
    },

    # 10. HSE06 band structure
    {
        'name': 'hse_bands',
        'type': 'hybrid_bands',
        'structure_from': 'bulk_relax',
        'scf_incar': hse_scf_incar,
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

    # 11. HSE06 DOS (separate stage: VaspHybridBandsWorkChain does not run DOS)
    {
        'name': 'hse_dos',
        'type': 'dos',
        'structure_from': 'bulk_relax',
        'scf_incar': hse_scf_incar,
        'dos_incar': hse_dos_incar,
        'kpoints_spacing': 0.05,
        'dos_kpoints_spacing': 0.04,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 4 – SURFACE ENUMERATION (verification, pure Python / no VASP)
    # ════════════════════════════════════════════════════════════════════════

    # 12. Enumerate symmetrically distinct surfaces (max_index=1 → 5 for SnO2)
    {
        'name': 'enumerate_surfaces',
        'type': 'surface_enumeration',
        'structure_from': 'bulk_relax',
        'max_index': 1,
        'symprec': 0.1,
    },

    # ════════════════════════════════════════════════════════════════════════
    # PHASE 5 – SHARED REFERENCES (start at T=0, independent of Phase 1)
    # ════════════════════════════════════════════════════════════════════════

    # 13. Relax Sn metal reference
    {
        'name': 'sn_relax',
        'type': 'vasp',
        'structure': ref_sn,
        'incar': sn_relax_incar,
        'kpoints_spacing': 0.03,
        'restart': None,
    },

    # 14. O2 reference energy via water-splitting: E_ref(O2) = E(H2O) - E(H2)
    {
        'name': 'o2_ref',
        'type': 'o2_reference_energy',
        'h2_structure': ref_h2,
        'h2o_structure': ref_h2o,
        'h2_incar': h2_incar,
        'h2o_incar': h2o_incar,
        'kpoints': [1, 1, 1],
    },

    # 15. Formation enthalpy ΔHf(SnO2) – shared by all surface_gibbs stages
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
# PHASE 5 (cont.) + PHASE 6 – per-orientation surface thermo + Fukui
#
# For each symmetrically distinct Miller index (hkl) we append 7 stages:
#   slab_terms_{hkl}   – generate all terminations for this orientation
#   slab_relax_{hkl}   – relax them in parallel (dynamic_batch)
#   surface_gibbs_{hkl}– compute γ(ΔμSn, ΔμO) for each termination
#   select_stable_{hkl}– pick the termination with minimum φ at ΔμM=ΔμO=0
#   fukui_batch_{hkl}  – 4 VASP static SCFs (NELECT = base-1..+2)
#   fukui_plus_{hkl}   – f+ Fukui function
#   fukui_minus_{hkl}  – f- Fukui function
# ════════════════════════════════════════════════════════════════════════════

# Stage counter offset (stages 1–15 defined above)
_stage_n = 15

for hkl in miller_list:
    s = hkl_str(hkl)  # e.g. '110'
    _stage_n += 7

    stages += [
        # ── Surface terminations ────────────────────────────────────────────
        {
            'name': f'slab_terms_{s}',
            'type': 'surface_terminations',
            'structure_from': 'bulk_relax',
            'miller_indices': list(hkl),
            'min_slab_size': 18.0,
            'min_vacuum_size': 15.0,
            'lll_reduce': True,
            'center_slab': True,
            'primitive': True,
            'reorient_lattice': True,
        },

        # ── Relax all terminations in parallel ──────────────────────────────
        {
            'name': f'slab_relax_{s}',
            'type': 'dynamic_batch',
            'structures_from': f'slab_terms_{s}',
            'base_incar': slab_incar,
            'kpoints_spacing': 0.05,
        },

        # ── Surface Gibbs free energies γ(ΔμSn, ΔμO) ────────────────────────
        {
            'name': f'surface_gibbs_{s}',
            'type': 'surface_gibbs_energy',
            'bulk_structure_from': 'bulk_relax',
            'bulk_energy_from': 'bulk_relax',
            'slab_structures_from': f'slab_relax_{s}',
            'slab_energies_from': f'slab_relax_{s}',
            'formation_enthalpy_from': 'dhf',
            'sampling': 100,
        },

        # ── Select most stable termination (min φ at ΔμM=ΔμO=0) ────────────
        {
            'name': f'select_stable_{s}',
            'type': 'select_stable_surface',
            'summary_from': f'surface_gibbs_{s}',
            'structures_from': f'slab_relax_{s}',
        },

        # ── 8 VASP static SCFs (4 for f−, 4 for f+) with fractional NELECT ──
        {
            'name': f'fukui_batch_{s}',
            'type': 'fukui_dynamic',
            'structure_from': f'select_stable_{s}',
            'base_incar': fukui_incar,
            'kpoints_spacing': 0.05,
            'retrieve': ['CHGCAR'],
        },

        # ── Fukui f+ (electrophilic susceptibility) ─────────────────────────
        {
            'name': f'fukui_plus_{s}',
            'type': 'fukui_analysis',
            'batch_from': f'fukui_batch_{s}',
            'fukui_type': 'plus',
            'delta_n_map': {'neutral': 0.00, 'delta_005': 0.05, 'delta_010': 0.10, 'delta_015': 0.15},
        },

        # ── Fukui f− (nucleophilic susceptibility) ──────────────────────────
        {
            'name': f'fukui_minus_{s}',
            'type': 'fukui_analysis',
            'batch_from': f'fukui_batch_{s}',
            'fukui_type': 'minus',
            'delta_n_map': {'neutral': 0.00, 'delta_005': 0.05, 'delta_010': 0.10, 'delta_015': 0.15},
        },
    ]

print(f'Total stages: {len(stages)}  '
      f'({_stage_n} = 15 shared + {len(miller_list)} × 7 per-surface)')

# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    result = quick_vasp_sequential(
        structure=sno2_prim,
        stages=stages,
        code_label='VASP-6.5.1-idefix-4@obelix',
        kpoints_spacing=0.03,
        potential_family='PBE',
        potential_mapping={
            'Sn':  'Sn_d',
            'Sn1': 'Sn_d',
            'O':   'O',
            'H':   'H',
        },
        options={
            'resources': {
                'num_machines': 1,
                'num_mpiprocs_per_machine': 4,  # Hybrid MPI+OpenMP: 4 MPI × ~22 OMP on 88 cores
            },
            'custom_scheduler_commands': (
                '#PBS -l cput=90000:00:00\n'
                '#PBS -l nodes=1:ppn=88:skylake\n'
                '#PBS -j oe\n'
                '#PBS -N sno2_full_workflow\n'
            ),
        },
        max_concurrent_jobs=4,
        serialize_stages=True,
        name='sno2_full_workflow',
    )

    pk = result['__workgraph_pk__']
    n_stages = len(stages)
    print(f'Submitted WorkGraph PK: {pk}')
    print(f'Total stages: {n_stages}')
    print()
    print('Monitor:')
    print(f'  verdi process show {pk}')
    print(f'  verdi process report {pk}')
    print()
    print('After completion, inspect all results:')
    print(f'  from quantum_lego import print_sequential_results')
    print(f'  print_sequential_results({pk})')
    print()
    print('Key results to look for:')
    print('  Phase 1 → bulk_relax:           equilibrium structure + energy')
    print('  Phase 2 → hub_analysis:          Sn-d Hubbard U (eV), R²')
    print('  Phase 3 → hse_bands/hse_dos:    HSE06 band gap, DOS')
    print('  Phase 4 → enumerate_surfaces:   distinct Miller indices')
    for hkl in miller_list:
        s = hkl_str(hkl)
        print(f'  Phase 5/6 ({hkl}):')
        print(f'    surface_gibbs_{s}:   γ(ΔμSn, ΔμO) per termination')
        print(f'    select_stable_{s}:   most stable slab (min φ)')
        print(f'    fukui_plus_{s}:      f+ Fukui function CHGCAR')
        print(f'    fukui_minus_{s}:     f- Fukui function CHGCAR')
    print()

    # Persist PK for later retrieval
    pk_file = Path(__file__).parent / 'full_workflow_pks.txt'
    with open(pk_file, 'a') as f:
        timestamp = datetime.now().isoformat()
        f.write(f'{timestamp}  sno2_full_workflow  PK={pk}\n')
    print(f'PK saved to {pk_file}')
