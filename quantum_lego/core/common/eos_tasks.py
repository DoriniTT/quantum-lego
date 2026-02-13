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
        pairs.append((float(vol), energy))

    # Sort by volume
    pairs.sort(key=lambda p: p[0])

    return orm.Dict(dict={
        'volumes': [p[0] for p in pairs],
        'energies': [p[1] for p in pairs],
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

    return orm.Dict(dict={
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
    })
