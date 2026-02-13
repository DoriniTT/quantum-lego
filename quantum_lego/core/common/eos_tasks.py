"""AiiDA calcfunction tasks for Birch-Murnaghan equation of state fitting.

These tasks gather energy-volume data from batch calculations and fit
the Birch-Murnaghan EOS using pymatgen's EOS class.
"""

import numpy as np
from aiida import orm
from aiida_workgraph import task


@task.calcfunction
def gather_eos_data(
    volumes: orm.List,
    labels: orm.List,
    **energy_kwargs: orm.Float,
) -> orm.Dict:
    """Gather volume-energy pairs from batch energy outputs.

    Takes volume and label lists plus individual energy Float kwargs
    keyed by calculation label, and returns paired volume/energy lists.

    Args:
        volumes: List of volumes in Angstrom^3 (ordered by label).
        labels: List of calculation labels (matching energy_kwargs keys).
        **energy_kwargs: Individual orm.Float energies keyed by calc label.

    Returns:
        Dict with 'volumes' and 'energies' as paired lists sorted by volume.

    Raises:
        ValueError: If labels don't match energy kwargs or lengths mismatch.
    """
    vol_list = volumes.get_list()
    label_list = labels.get_list()

    if len(vol_list) != len(label_list):
        raise ValueError(
            f"volumes ({len(vol_list)}) and labels ({len(label_list)}) "
            f"must have the same length"
        )

    # Collect volume-energy pairs
    pairs = []
    for vol, label in zip(vol_list, label_list):
        if label not in energy_kwargs:
            raise ValueError(
                f"Label '{label}' not found in energy kwargs. "
                f"Available: {sorted(energy_kwargs.keys())}"
            )
        energy_node = energy_kwargs[label]
        energy = energy_node.value if hasattr(energy_node, 'value') else float(energy_node)
        pairs.append((float(vol), energy, label))

    # Sort by volume
    pairs.sort(key=lambda p: p[0])

    return orm.Dict(dict={
        'volumes': [p[0] for p in pairs],
        'energies': [p[1] for p in pairs],
        'labels': [p[2] for p in pairs],
    })


@task.calcfunction
def fit_birch_murnaghan_eos(
    eos_data: orm.Dict,
) -> orm.Dict:
    """Fit a Birch-Murnaghan equation of state to volume-energy data.

    Uses pymatgen's EOS class with the 'birch_murnaghan' model.

    Args:
        eos_data: Dict with 'volumes' (Angstrom^3) and 'energies' (eV) lists.

    Returns:
        Dict with:
            - v0: Equilibrium volume (Angstrom^3)
            - e0: Equilibrium energy (eV)
            - b0_eV_per_A3: Bulk modulus (eV/Angstrom^3)
            - b0_GPa: Bulk modulus (GPa)
            - b1: Pressure derivative of bulk modulus
            - volumes: Input volumes (sorted)
            - energies: Input energies (sorted by volume)
            - n_points: Number of data points
            - residuals_eV: Per-point residuals (eV)
            - rms_residual_eV: RMS residual (eV)

    Raises:
        ValueError: If fewer than 4 data points provided.
    """
    from pymatgen.analysis.eos import EOS

    data = eos_data.get_dict()
    volumes = np.array(data['volumes'])
    energies = np.array(data['energies'])

    if len(volumes) < 4:
        raise ValueError(
            f"Birch-Murnaghan EOS requires at least 4 data points, "
            f"got {len(volumes)}"
        )

    # Sort by volume
    sort_idx = np.argsort(volumes)
    volumes = volumes[sort_idx]
    energies = energies[sort_idx]

    # Fit EOS
    eos = EOS(eos_name='birch_murnaghan')
    eos_fit = eos.fit(volumes, energies)

    v0 = float(eos_fit.v0)
    e0 = float(eos_fit.e0)
    b0_eV_A3 = float(eos_fit.b0)  # eV/Angstrom^3
    b1 = float(eos_fit.b1)

    # Convert bulk modulus to GPa: 1 eV/A^3 = 160.21766208 GPa
    eV_per_A3_to_GPa = 160.21766208
    b0_GPa = b0_eV_A3 * eV_per_A3_to_GPa

    # Calculate residuals
    fitted_energies = np.array([eos_fit.func(v) for v in volumes])
    residuals = energies - fitted_energies
    rms_residual = float(np.sqrt(np.mean(residuals**2)))

    # Find recommended data point (closest volume to V0)
    result_dict = {
        'v0': v0,
        'e0': e0,
        'b0_eV_per_A3': b0_eV_A3,
        'b0_GPa': b0_GPa,
        'b1': b1,
        'volumes': volumes.tolist(),
        'energies': energies.tolist(),
        'n_points': len(volumes),
        'residuals_eV': residuals.tolist(),
        'rms_residual_eV': rms_residual,
    }

    labels = data.get('labels')
    if labels is not None:
        labels = np.array(labels)[sort_idx].tolist()
        result_dict['labels'] = labels
        # Find the data point closest to V0
        vol_diffs = np.abs(volumes - v0)
        closest_idx = int(np.argmin(vol_diffs))
        closest_vol = float(volumes[closest_idx])
        result_dict['recommended_label'] = labels[closest_idx]
        result_dict['recommended_volume'] = closest_vol
        result_dict['recommended_volume_error_pct'] = (
            abs(closest_vol - v0) / v0 * 100.0
        )

    return orm.Dict(dict=result_dict)


@task.calcfunction
def build_recommended_structure(
    structure: orm.StructureData,
    eos_result: orm.Dict,
) -> orm.StructureData:
    """Scale input structure uniformly to the fitted equilibrium volume V0.

    Args:
        structure: Base structure to scale.
        eos_result: Dict from fit_birch_murnaghan_eos containing 'v0'.

    Returns:
        StructureData scaled to V0.
    """
    pmg = structure.get_pymatgen()
    v0 = eos_result['v0']
    pmg.scale_lattice(v0)
    return orm.StructureData(pymatgen=pmg)


@task.calcfunction
def build_refined_structures(
    structure: orm.StructureData,
    eos_result: orm.Dict,
    strain_range: orm.Float,
    n_points: orm.Int,
) -> dict:
    """Generate N volume-scaled structures around V0 for refined EOS scan.

    Creates structures uniformly distributed in the range
    [V0*(1 - strain_range), V0*(1 + strain_range)].

    Args:
        structure: Base structure for scaling.
        eos_result: Dict from fit_birch_murnaghan_eos containing 'v0'.
        strain_range: Fractional range around V0 (e.g. 0.02 for +/-2%).
        n_points: Number of volume points to generate.

    Returns:
        Dict with:
            - 'refine_00', 'refine_01', ...: StructureData nodes
            - 'volumes': orm.List of target volumes
            - 'labels': orm.List of labels
    """
    v0 = eos_result['v0']
    n = n_points.value
    sr = strain_range.value

    results = {}
    volumes, labels = [], []
    for i, frac in enumerate(np.linspace(-1, 1, n)):
        target_vol = v0 * (1 + frac * sr)
        label = f'refine_{i:02d}'
        pmg = structure.get_pymatgen()
        pmg.scale_lattice(target_vol)
        results[label] = orm.StructureData(pymatgen=pmg)
        volumes.append(target_vol)
        labels.append(label)

    results['volumes'] = orm.List(list=volumes)
    results['labels'] = orm.List(list=labels)
    return results
