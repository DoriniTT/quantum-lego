"""Surface Gibbs free energy brick for the lego module.

Computes surface free energies as a function of chemical potentials using the
ab initio atomistic thermodynamics framework (binary and ternary oxides).

This brick is a pure-Python post-processing step: it consumes DFT energies and
structures produced by earlier stages (bulk + slabs + formation enthalpy).

Implementation note:
  The equations are copied from PS-TEROS (teros/core/thermodynamics.py) to avoid
  introducing a hard dependency between the two projects. The output format is
  kept compatible with PS-TEROS for downstream plotting/phase-diagram tooling.
"""

from __future__ import annotations

import typing as t
from collections import Counter
from functools import reduce
from math import gcd

import numpy as np
from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import dynamic, namespace, task

from .connections import SURFACE_GIBBS_ENERGY_PORTS as PORTS  # noqa: F401
from ..common.constants import EV_PER_ANGSTROM2_TO_J_PER_M2


# ---------------------------------------------------------------------------
# Adapters: quantum-lego formation_enthalpy -> thermodynamics inputs
# ---------------------------------------------------------------------------

@task.calcfunction
def identify_oxide_type(bulk_structure: orm.StructureData) -> orm.Str:
    """Identify whether a bulk structure is a binary or ternary oxide."""
    bulk_ase = bulk_structure.get_ase()
    bulk_counts = Counter(bulk_ase.get_chemical_symbols())

    if 'O' not in bulk_counts:
        raise ValueError('Structure contains no oxygen; not an oxide.')

    metals = sorted(el for el in bulk_counts if el != 'O')
    if len(metals) == 1:
        return orm.Str('binary')
    if len(metals) == 2:
        return orm.Str('ternary')

    raise ValueError(
        f'Found {len(metals)} non-oxygen elements: {metals}. '
        'Only binary (1 metal) and ternary (2 metals) oxides are supported.'
    )


@task.calcfunction
def adapt_formation_enthalpy_inputs(
    bulk_structure: orm.StructureData,
    formation_enthalpy: orm.Dict,
) -> t.Annotated[dict, namespace(reference_energies=orm.Dict, formation_enthalpy=orm.Dict)]:
    """Build PS-TEROS-compatible reference/ΔHf dicts from lego formation_enthalpy output."""
    data = formation_enthalpy.get_dict()
    refs = data.get('references') or {}

    if 'delta_h_formation_eV_per_fu' not in data:
        raise ValueError("formation_enthalpy Dict missing 'delta_h_formation_eV_per_fu'")

    # Identify elements from bulk structure
    bulk_counts = Counter(bulk_structure.get_ase().get_chemical_symbols())
    if 'O' not in bulk_counts:
        raise ValueError('Bulk structure contains no oxygen; expected an oxide.')

    non_o = sorted(el for el in bulk_counts if el != 'O')
    if len(non_o) not in (1, 2):
        raise ValueError(
            f'Expected 1 or 2 non-oxygen elements, got {non_o} (n={len(non_o)})'
        )

    # Pull per-atom reference energies from lego output
    mu: dict[str, float] = {}
    for el in ['O', *non_o]:
        el_ref = refs.get(el)
        if not isinstance(el_ref, dict) or 'energy_per_atom_eV' not in el_ref:
            raise ValueError(
                f"formation_enthalpy Dict missing references['{el}']['energy_per_atom_eV']"
            )
        mu[el] = float(el_ref['energy_per_atom_eV'])

    ref_dict = {
        'metal_energy_per_atom': mu[non_o[0]],
        'oxygen_energy_per_atom': mu['O'],
    }
    if len(non_o) == 2:
        ref_dict['nonmetal_energy_per_atom'] = mu[non_o[1]]

    return {
        'reference_energies': orm.Dict(dict=ref_dict),
        'formation_enthalpy': orm.Dict(
            dict={'formation_enthalpy_ev': float(data['delta_h_formation_eV_per_fu'])}
        ),
    }


# ---------------------------------------------------------------------------
# Thermodynamics equations (copied from PS-TEROS)
# ---------------------------------------------------------------------------

@task.calcfunction
def calculate_surface_energy_ternary(
    bulk_structure: orm.StructureData,
    bulk_energy: orm.Float,
    slab_structure: orm.StructureData,
    slab_energy: orm.Float,
    reference_energies: orm.Dict,
    formation_enthalpy: orm.Dict,
    sampling: orm.Int,
) -> orm.Dict:
    """Compute γ(Δμ_M, Δμ_O) surface energy for a single ternary oxide slab."""
    grid_points = sampling.value
    if grid_points <= 0:
        raise ValueError('Sampling must be a positive integer')

    bulk_ase = bulk_structure.get_ase()
    bulk_counts = Counter(bulk_ase.get_chemical_symbols())

    if 'O' not in bulk_counts:
        raise ValueError('The bulk structure contains no oxygen; expected a ternary oxide.')

    metal_elements = sorted(el for el in bulk_counts if el != 'O')
    if len(metal_elements) != 2:
        raise ValueError(f'Expected exactly two distinct metal species; found: {metal_elements}')

    element_M = metal_elements[0]
    element_N_ref = metal_elements[1]
    element_O = 'O'

    stoichiometric_counts = [
        bulk_counts[element_M],
        bulk_counts[element_N_ref],
        bulk_counts[element_O],
    ]
    common_divisor = reduce(gcd, stoichiometric_counts)
    x_M = bulk_counts[element_M] // common_divisor
    y_N = bulk_counts[element_N_ref] // common_divisor
    z_O = bulk_counts[element_O] // common_divisor

    # Bulk energy per formula unit (informational)
    formula_units_in_bulk = bulk_counts[element_N_ref] / y_N
    bulk_energy_per_fu = bulk_energy.value / formula_units_in_bulk

    ref_data = reference_energies.get_dict()
    formation_data = formation_enthalpy.get_dict()

    ref_energies = {
        element_M: float(ref_data['metal_energy_per_atom']),
        element_N_ref: float(ref_data['nonmetal_energy_per_atom']),
        element_O: float(ref_data['oxygen_energy_per_atom']),
    }
    delta_h = float(formation_data['formation_enthalpy_ev'])

    slab_ase = slab_structure.get_ase()
    cell = slab_ase.get_cell()
    a_vec = cell[0]
    b_vec = cell[1]
    cross = np.cross(a_vec, b_vec)
    area = float(np.linalg.norm(cross))

    slab_counts = Counter(slab_ase.get_chemical_symbols())
    N_M_slab = slab_counts.get(element_M, 0)
    N_N_slab = slab_counts.get(element_N_ref, 0)
    N_O_slab = slab_counts.get(element_O, 0)

    gamma_M = (N_M_slab - (x_M / y_N) * N_N_slab) / (2 * area)
    gamma_O = (N_O_slab - (z_O / y_N) * N_N_slab) / (2 * area)

    # φ at Δμ_M = Δμ_O = 0
    phi = (
        slab_energy.value
        - N_M_slab * ref_energies[element_M]
        - N_N_slab * ref_energies[element_N_ref]
        - N_O_slab * ref_energies[element_O]
        - (N_N_slab / y_N) * delta_h
    ) / (2 * area)

    delta_mu_M_range = np.linspace(delta_h / x_M, 0, grid_points)
    delta_mu_O_range = np.linspace(delta_h / z_O, 0, grid_points)

    gamma_grid_2d = []
    for delta_mu_M in delta_mu_M_range:
        gamma_row = []
        for delta_mu_O in delta_mu_O_range:
            gamma = phi - gamma_M * float(delta_mu_M) - gamma_O * float(delta_mu_O)
            gamma_row.append(float(gamma))
        gamma_grid_2d.append(gamma_row)

    gamma_at_muM_zero = []
    for delta_mu_O in delta_mu_O_range:
        gamma = phi - gamma_O * float(delta_mu_O)
        gamma_at_muM_zero.append(float(gamma))

    gamma_at_muO_zero = []
    for delta_mu_M in delta_mu_M_range:
        gamma = phi - gamma_M * float(delta_mu_M)
        gamma_at_muO_zero.append(float(gamma))

    # --- Alternative formulation (B-based) ---
    N_N_stoich = (N_M_slab * y_N) / x_M
    N_O_stoich_B = (N_M_slab * z_O) / x_M
    gamma_N = (N_N_stoich - N_N_slab) / (2 * area)
    gamma_O_B = (N_O_stoich_B - N_O_slab) / (2 * area)

    phi_B = (
        slab_energy.value
        - N_M_slab * ref_energies[element_M]
        - N_N_slab * ref_energies[element_N_ref]
        - N_O_slab * ref_energies['O']
        - (N_M_slab / x_M) * delta_h
    ) / (2 * area)

    delta_mu_N_range = np.linspace(delta_h / y_N, 0.0, grid_points)

    gamma_grid_2d_B = []
    for delta_mu_N in delta_mu_N_range:
        gamma_row_B = []
        for delta_mu_O in delta_mu_O_range:
            gamma_B = phi_B - gamma_N * float(delta_mu_N) - gamma_O_B * float(delta_mu_O)
            gamma_row_B.append(float(gamma_B))
        gamma_grid_2d_B.append(gamma_row_B)

    gamma_at_muN_zero = []
    for delta_mu_O in delta_mu_O_range:
        gamma_B = phi_B - gamma_O_B * float(delta_mu_O)
        gamma_at_muN_zero.append(float(gamma_B))

    gamma_at_muO_zero_B = []
    for delta_mu_N in delta_mu_N_range:
        gamma_B = phi_B - gamma_N * float(delta_mu_N)
        gamma_at_muO_zero_B.append(float(gamma_B))

    return orm.Dict(
        dict={
            'primary': {
                'phi': float(phi),
                'Gamma_M': float(gamma_M),
                'Gamma_O': float(gamma_O),
                'delta_mu_M_range': [float(x) for x in delta_mu_M_range],
                'delta_mu_O_range': [float(x) for x in delta_mu_O_range],
                'gamma_grid': gamma_grid_2d,
                'gamma_at_muM_zero': gamma_at_muM_zero,
                'gamma_at_muO_zero': gamma_at_muO_zero,
                'gamma_at_reference': float(phi),
                'element_M_independent': element_M,
                'element_N_reference': element_N_ref,
            },
            'A_based': {
                'phi': float(phi),
                'Gamma_A': float(gamma_M),
                'Gamma_O': float(gamma_O),
                'delta_mu_A_range': [float(x) for x in delta_mu_M_range],
                'delta_mu_O_range': [float(x) for x in delta_mu_O_range],
                'gamma_grid': gamma_grid_2d,
                'gamma_at_muA_zero': gamma_at_muM_zero,
                'gamma_at_muO_zero': gamma_at_muO_zero,
                'gamma_at_reference': float(phi),
                'element_A_independent': element_M,
                'element_B_reference': element_N_ref,
            },
            'B_based': {
                'phi': float(phi_B),
                'Gamma_B': float(gamma_N),
                'Gamma_O': float(gamma_O_B),
                'delta_mu_B_range': [float(x) for x in delta_mu_N_range],
                'delta_mu_O_range': [float(x) for x in delta_mu_O_range],
                'gamma_grid': gamma_grid_2d_B,
                'gamma_at_muB_zero': gamma_at_muN_zero,
                'gamma_at_muO_zero': gamma_at_muO_zero_B,
                'gamma_at_reference': float(phi_B),
                'element_B_independent': element_N_ref,
                'element_A_reference': element_M,
            },
            'oxide_type': 'ternary',
            'area_A2': float(area),
            'bulk_stoichiometry': {
                f'x_{element_M}': int(x_M),
                f'y_{element_N_ref}': int(y_N),
                'z_O': int(z_O),
            },
            'slab_atom_counts': {
                f'N_{element_M}': int(N_M_slab),
                f'N_{element_N_ref}': int(N_N_slab),
                'N_O': int(N_O_slab),
            },
            'reference_energies_per_atom': {k: float(v) for k, v in ref_energies.items()},
            'E_slab_eV': float(slab_energy.value),
            'E_bulk_per_fu_eV': float(bulk_energy_per_fu),
            'formation_enthalpy_eV': float(delta_h),
            # Legacy keys
            'bulk_stoichiometry_AxByOz': {
                f'x_{element_M}': int(x_M),
                f'y_{element_N_ref}': int(y_N),
                'z_O': int(z_O),
            },
            'E_bulk_fu_eV': float(bulk_energy_per_fu),
        }
    )


@task.calcfunction
def calculate_surface_energy_binary(
    bulk_structure: orm.StructureData,
    bulk_energy: orm.Float,
    slab_structure: orm.StructureData,
    slab_energy: orm.Float,
    reference_energies: orm.Dict,
    formation_enthalpy: orm.Dict,
    sampling: orm.Int,
) -> orm.Dict:
    """Compute γ(Δμ_O) surface energy for a single binary oxide slab."""
    grid_points = sampling.value
    if grid_points <= 0:
        raise ValueError('Sampling must be a positive integer')

    bulk_ase = bulk_structure.get_ase()
    bulk_counts = Counter(bulk_ase.get_chemical_symbols())

    if 'O' not in bulk_counts:
        raise ValueError('The bulk structure contains no oxygen; expected a binary oxide.')

    metal_elements = [el for el in bulk_counts if el != 'O']
    if len(metal_elements) != 1:
        raise ValueError(f'Expected exactly one metal species; found: {metal_elements}')

    element_M = metal_elements[0]
    element_O = 'O'

    x = bulk_counts[element_M]
    y = bulk_counts[element_O]

    common_divisor = gcd(x, y)
    x_reduced = x // common_divisor
    y_reduced = y // common_divisor

    ref_data = reference_energies.get_dict()
    formation_data = formation_enthalpy.get_dict()

    E_M_ref = float(ref_data['metal_energy_per_atom'])
    E_O_ref = float(ref_data['oxygen_energy_per_atom'])
    delta_h = float(formation_data['formation_enthalpy_ev'])

    slab_ase = slab_structure.get_ase()
    cell = slab_ase.get_cell()
    a_vec = cell[0]
    b_vec = cell[1]
    cross = np.cross(a_vec, b_vec)
    area = float(np.linalg.norm(cross))

    slab_counts = Counter(slab_ase.get_chemical_symbols())
    N_M_slab = slab_counts.get(element_M, 0)
    N_O_slab = slab_counts.get(element_O, 0)

    expected_O = (y / x) * N_M_slab
    stoichiometric_imbalance = expected_O - N_O_slab

    delta_mu_O_min = delta_h / y_reduced
    delta_mu_O_max = 0.0
    delta_mu_O_range = np.linspace(delta_mu_O_min, delta_mu_O_max, grid_points)

    phi = (
        slab_energy.value
        - N_M_slab * (bulk_energy.value / x)
        + (y / x) * N_M_slab * E_O_ref
        - N_O_slab * E_O_ref
    ) / (2 * area)

    Gamma_O = -stoichiometric_imbalance / (2 * area)

    gamma_array = []
    for delta_mu_O in delta_mu_O_range:
        gamma = phi - Gamma_O * float(delta_mu_O)
        gamma_array.append(float(gamma))

    gamma_O_poor_raw = gamma_array[0]
    gamma_O_rich_raw = gamma_array[-1]

    phi_Jm2 = phi * EV_PER_ANGSTROM2_TO_J_PER_M2
    gamma_array_Jm2 = [g * EV_PER_ANGSTROM2_TO_J_PER_M2 for g in gamma_array]
    gamma_O_poor = gamma_O_poor_raw * EV_PER_ANGSTROM2_TO_J_PER_M2
    gamma_O_rich = gamma_O_rich_raw * EV_PER_ANGSTROM2_TO_J_PER_M2

    formula_units_in_bulk = bulk_counts[element_M] / x_reduced
    bulk_energy_per_fu = bulk_energy.value / formula_units_in_bulk

    return orm.Dict(
        dict={
            'primary': {
                'phi': float(phi_Jm2),
                'Gamma_O': float(Gamma_O),
                'delta_mu_O_range': [float(x) for x in delta_mu_O_range],
                'gamma_array': gamma_array_Jm2,
                'gamma_O_poor': float(gamma_O_poor),
                'gamma_O_rich': float(gamma_O_rich),
                'gamma_at_reference': float(phi_Jm2),
                'element_M': element_M,
            },
            'oxide_type': 'binary',
            'area_A2': float(area),
            'bulk_stoichiometry': {f'x_{element_M}': int(x_reduced), 'y_O': int(y_reduced)},
            'slab_atom_counts': {f'N_{element_M}': int(N_M_slab), 'N_O': int(N_O_slab)},
            'reference_energies_per_atom': {element_M: float(E_M_ref), 'O': float(E_O_ref)},
            'E_slab_eV': float(slab_energy.value),
            'E_bulk_per_fu_eV': float(bulk_energy_per_fu),
            'formation_enthalpy_eV': float(delta_h),
            'stoichiometric_imbalance': float(stoichiometric_imbalance),
            'delta_mu_O_min': float(delta_mu_O_min),
            'delta_mu_O_max': float(delta_mu_O_max),
            # Legacy keys
            'phi': float(phi_Jm2),
            'Gamma_O': float(Gamma_O),
            'delta_mu_O_range': [float(x) for x in delta_mu_O_range],
            'gamma_array': gamma_array_Jm2,
            'gamma_O_poor': float(gamma_O_poor),
            'gamma_O_rich': float(gamma_O_rich),
            'gamma_at_reference': float(phi_Jm2),
            'element_M': element_M,
            'E_bulk_eV': float(bulk_energy.value),
            'bulk_stoichiometry_MxOy': {f'x_{element_M}': int(x_reduced), 'y_O': int(y_reduced)},
        }
    )


@task.graph
def compute_surface_energies_scatter(
    slabs: t.Annotated[dict[str, orm.StructureData], dynamic(orm.StructureData)],
    energies: t.Annotated[dict[str, orm.Float], dynamic(orm.Float)],
    bulk_structure: orm.StructureData,
    bulk_energy: orm.Float,
    reference_energies: orm.Dict,
    formation_enthalpy: orm.Dict,
    oxide_type: orm.Str,
    sampling: int = 100,
) -> t.Annotated[dict, namespace(surface_energies=dynamic(orm.Dict))]:
    """Scatter-gather pattern for computing surface energies for many slabs."""
    surface_results = {}
    sampling_node = orm.Int(int(sampling))

    oxide_type_str = oxide_type.value
    if oxide_type_str == 'ternary':
        calc_func = calculate_surface_energy_ternary
    elif oxide_type_str == 'binary':
        calc_func = calculate_surface_energy_binary
    else:
        raise ValueError(f'Unknown oxide_type: {oxide_type_str}. Must be \"binary\" or \"ternary\".')

    for key, slab_structure in slabs.items():
        slab_energy = energies[key]
        surface_data = calc_func(
            bulk_structure=bulk_structure,
            bulk_energy=bulk_energy,
            slab_structure=slab_structure,
            slab_energy=slab_energy,
            reference_energies=reference_energies,
            formation_enthalpy=formation_enthalpy,
            sampling=sampling_node,
        ).result
        surface_results[key] = surface_data

    return {'surface_energies': surface_results}


@task.calcfunction
def collect_surface_gibbs_energies(oxide_type: orm.Str, **kwargs) -> orm.Dict:
    """Collect per-termination Dict nodes into a single Dict."""
    collected: dict[str, t.Any] = {}
    for key, val in kwargs.items():
        if isinstance(val, orm.Dict):
            collected[key] = val.get_dict()
        else:
            collected[key] = val
    return orm.Dict(dict={'oxide_type': oxide_type.value, 'surface_energies': collected})


@task.graph
def gather_surface_gibbs_energies(
    surface_energies: t.Annotated[dict[str, orm.Dict], dynamic(orm.Dict)],
    oxide_type: orm.Str,
) -> orm.Dict:
    gather_kwargs: dict[str, t.Any] = {'oxide_type': oxide_type}
    for key, surface_data in surface_energies.items():
        gather_kwargs[key] = surface_data
    result = collect_surface_gibbs_energies(**gather_kwargs)
    return result.result


# ---------------------------------------------------------------------------
# Brick interface
# ---------------------------------------------------------------------------

def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a surface_gibbs_energy stage configuration."""
    name = stage['name']

    required = (
        'bulk_structure_from',
        'bulk_energy_from',
        'slab_structures_from',
        'slab_energies_from',
        'formation_enthalpy_from',
    )
    for key in required:
        if key not in stage:
            raise ValueError(f"Stage '{name}': surface_gibbs_energy stages require '{key}'")

        ref = stage[key]
        if ref == 'input':
            raise ValueError(f"Stage '{name}': {key}='input' is not supported")
        if ref not in stage_names:
            raise ValueError(
                f"Stage '{name}': {key}='{ref}' must reference a previous stage name"
            )

    sampling = stage.get('sampling', 100)
    if not isinstance(sampling, int) or sampling <= 0:
        raise ValueError(f"Stage '{name}': sampling must be a positive int, got {sampling!r}")


def create_stage_tasks(wg, stage, stage_name, context):
    """Create surface_gibbs_energy stage tasks in the WorkGraph."""
    from . import resolve_structure_from, resolve_energy_from

    stage_tasks = context['stage_tasks']

    bulk_structure = resolve_structure_from(stage['bulk_structure_from'], context)
    bulk_energy = resolve_energy_from(stage['bulk_energy_from'], context)

    # Slabs + energies come from dynamic namespaces (e.g., dynamic_batch)
    slab_structures_from = stage['slab_structures_from']
    slab_energies_from = stage['slab_energies_from']

    upstream_structs = stage_tasks.get(slab_structures_from, {})
    upstream_energies = stage_tasks.get(slab_energies_from, {})

    if 'structures' not in upstream_structs:
        raise ValueError(
            f"Stage '{stage_name}': slab_structures_from='{slab_structures_from}' "
            f"does not provide a 'structures' output."
        )
    if 'energies' not in upstream_energies:
        raise ValueError(
            f"Stage '{stage_name}': slab_energies_from='{slab_energies_from}' "
            f"does not provide an 'energies' output."
        )

    slabs_socket = upstream_structs['structures']
    energies_socket = upstream_energies['energies']

    fh_from = stage['formation_enthalpy_from']
    fh_task = stage_tasks.get(fh_from, {}).get('formation_enthalpy')
    if fh_task is None:
        raise ValueError(
            f"Stage '{stage_name}': formation_enthalpy_from='{fh_from}' does not provide "
            f"a formation_enthalpy task."
        )

    oxide_type_task = wg.add_task(
        identify_oxide_type,
        name=f'oxide_type_{stage_name}',
        bulk_structure=bulk_structure,
    )

    adapt_task = wg.add_task(
        adapt_formation_enthalpy_inputs,
        name=f'adapt_surface_thermo_inputs_{stage_name}',
        bulk_structure=bulk_structure,
        formation_enthalpy=fh_task.outputs.result,
    )

    surface_task = wg.add_task(
        compute_surface_energies_scatter,
        name=f'surface_gibbs_{stage_name}',
        slabs=slabs_socket,
        energies=energies_socket,
        bulk_structure=bulk_structure,
        bulk_energy=bulk_energy,
        reference_energies=adapt_task.outputs.reference_energies,
        formation_enthalpy=adapt_task.outputs.formation_enthalpy,
        oxide_type=oxide_type_task.outputs.result,
        sampling=int(stage.get('sampling', 100)),
    )

    summary_task = wg.add_task(
        gather_surface_gibbs_energies,
        name=f'gather_surface_gibbs_{stage_name}',
        surface_energies=surface_task.outputs.surface_energies,
        oxide_type=oxide_type_task.outputs.result,
    )

    return {
        'surface_task': surface_task,
        'surface_energies': surface_task.outputs.surface_energies,
        'summary': summary_task,
        'oxide_type': oxide_type_task,
        'reference_energies': adapt_task.outputs.reference_energies,
        'formation_enthalpy': adapt_task.outputs.formation_enthalpy,
        'bulk_structure': bulk_structure,
        'bulk_energy': bulk_energy,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose surface_gibbs_energy outputs on the WorkGraph."""
    surface_task = stage_tasks_result['surface_task']
    summary_task = stage_tasks_result['summary']
    oxide_type_task = stage_tasks_result['oxide_type']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(
            wg.outputs,
            f'{ns}.surface_gibbs_energy.surface_energies',
            surface_task.outputs.surface_energies,
        )
        setattr(
            wg.outputs,
            f'{ns}.surface_gibbs_energy.summary',
            summary_task.outputs.result,
        )
        setattr(
            wg.outputs,
            f'{ns}.surface_gibbs_energy.oxide_type',
            oxide_type_task.outputs.result,
        )
    else:
        setattr(
            wg.outputs,
            f'{stage_name}_surface_gibbs_surface_energies',
            surface_task.outputs.surface_energies,
        )
        setattr(
            wg.outputs,
            f'{stage_name}_surface_gibbs_summary',
            summary_task.outputs.result,
        )
        setattr(
            wg.outputs,
            f'{stage_name}_surface_gibbs_oxide_type',
            oxide_type_task.outputs.result,
        )


def get_stage_results(wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from a surface_gibbs_energy stage."""
    result = {
        'oxide_type': None,
        'summary': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'surface_gibbs_energy',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'surface_gibbs_energy', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'oxide_type'):
                    node = brick_ns.oxide_type
                    result['oxide_type'] = node.value if hasattr(node, 'value') else str(node)
                if hasattr(brick_ns, 'summary') and hasattr(brick_ns.summary, 'get_dict'):
                    result['summary'] = brick_ns.summary.get_dict()
        else:
            ot_attr = f'{stage_name}_surface_gibbs_oxide_type'
            if hasattr(outputs, ot_attr):
                node = getattr(outputs, ot_attr)
                result['oxide_type'] = node.value if hasattr(node, 'value') else str(node)

            s_attr = f'{stage_name}_surface_gibbs_summary'
            if hasattr(outputs, s_attr):
                node = getattr(outputs, s_attr)
                if hasattr(node, 'get_dict'):
                    result['summary'] = node.get_dict()

    if result['summary'] is None:
        _extract_from_links(wg_node, stage_name, result)

    return result


def _extract_from_links(wg_node, stage_name: str, result: dict) -> None:
    """Fallback: traverse WorkGraph links to find the summary Dict."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'gather_surface_gibbs_{stage_name}'
    called_work = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_WORK)
    for link in called_work.all():
        if task_name not in link.link_label and link.link_label != task_name:
            continue
        child = link.node
        called_calc = child.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
        for calc_link in called_calc.all():
            created = calc_link.node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                if out_link.link_label == 'result' and hasattr(out_link.node, 'get_dict'):
                    result['summary'] = out_link.node.get_dict()
                    return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a surface_gibbs_energy stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="surface_gibbs_energy")

    oxide_type = stage_result.get('oxide_type')
    if oxide_type:
        console.print(f"      [bold]Oxide type:[/bold] {oxide_type}")
    summary = stage_result.get('summary') or {}
    n_terms = len((summary.get('surface_energies') or {}).keys())
    if n_terms:
        console.print(f"      [bold]Terminations:[/bold] {n_terms}")

