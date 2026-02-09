"""Helper tasks for convergence analysis."""

from aiida import orm
from aiida_workgraph import task


@task.calcfunction
def gather_cutoff_results(cutoff_values: orm.List, **kwargs) -> orm.Dict:
    """Gather cutoff convergence scan results into a summary Dict.

    Collects energy from individual VASP misc outputs keyed as c_0, c_1, ...
    and assembles them into the format expected by analyze_cutoff_convergence.

    Args:
        cutoff_values: Ordered list of ENCUT values tested.
        **kwargs: c_0, c_1, ... orm.Dict nodes containing VASP misc output.

    Returns:
        Dict with 'cutoff' and 'energy' lists.
    """
    cutoffs = cutoff_values.get_list()
    energies = []

    for i in range(len(cutoffs)):
        misc = kwargs[f'c_{i}']
        data = misc.get_dict()
        total_energies = data.get('total_energies', {})
        energy = total_energies.get(
            'energy_extrapolated',
            total_energies.get('energy_no_entropy'),
        )
        energies.append(energy)

    return orm.Dict(dict={
        'cutoff': cutoffs,
        'energy': energies,
    })


@task.calcfunction
def gather_kpoints_results(kspacing_values: orm.List, **kwargs) -> orm.Dict:
    """Gather k-points convergence scan results into a summary Dict.

    Collects energy from individual VASP misc outputs keyed as k_0, k_1, ...
    and assembles them into the format expected by analyze_kpoints_convergence.

    Args:
        kspacing_values: Ordered list of k-spacing values tested.
        **kwargs: k_0, k_1, ... orm.Dict nodes containing VASP misc output.

    Returns:
        Dict with 'kpoints_spacing' and 'energy' lists.
    """
    spacings = kspacing_values.get_list()
    energies = []

    for i in range(len(spacings)):
        misc = kwargs[f'k_{i}']
        data = misc.get_dict()
        total_energies = data.get('total_energies', {})
        energy = total_energies.get(
            'energy_extrapolated',
            total_energies.get('energy_no_entropy'),
        )
        energies.append(energy)

    return orm.Dict(dict={
        'kpoints_spacing': spacings,
        'energy': energies,
    })


@task.calcfunction
def analyze_cutoff_convergence(
    conv_data: orm.Dict,
    threshold: orm.Float,
    structure: orm.StructureData,
) -> orm.Dict:
    """
    Analyze cutoff energy convergence data.

    Processes raw convergence data and determines the cutoff value
    at which energy is converged within the specified threshold.

    Args:
        conv_data: Dict from vasp.v2.converge with cutoff convergence results
        threshold: Energy threshold in eV/atom
        structure: Input structure (for atom count normalization)

    Returns:
        Dict with:
            - cutoff_values: list of tested ENCUT values
            - energies: list of total energies (eV)
            - energy_per_atom: list of energies per atom (eV/atom)
            - converged_cutoff: int, first ENCUT where convergence is achieved
            - energy_diff_from_max: list of energy differences from highest cutoff
            - convergence_achieved: bool
    """
    data = conv_data.get_dict()
    threshold_val = threshold.value
    n_atoms = len(structure.sites)

    # Extract cutoff values and energies from convergence data
    # Handle multiple possible formats from aiida-vasp
    cutoff_values = data.get('cutoff', data.get('encut', data.get('cutoff_values', [])))
    energies = data.get('energy', data.get('total_energy', data.get('energies', [])))

    # Handle nested format: {'data': [{'cutoff': x, 'energy': y}, ...]}
    if 'data' in data and isinstance(data['data'], list):
        cutoff_values = [item.get('cutoff', item.get('encut', 0)) for item in data['data']]
        energies = [item.get('energy', item.get('total_energy', 0)) for item in data['data']]

    # Sort by cutoff value (ascending)
    if cutoff_values and energies:
        sorted_pairs = sorted(zip(cutoff_values, energies), key=lambda x: x[0])
        cutoff_values = [p[0] for p in sorted_pairs]
        energies = [p[1] for p in sorted_pairs]

    # Normalize to per-atom energies
    energy_per_atom = [e / n_atoms for e in energies] if energies else []

    # Reference energy (highest cutoff, assumed most accurate)
    ref_energy = energy_per_atom[-1] if energy_per_atom else 0.0

    # Calculate energy differences from reference
    energy_diffs = [abs(e - ref_energy) for e in energy_per_atom]

    # Find first cutoff where convergence is achieved
    converged_cutoff = None
    for cutoff, diff in zip(cutoff_values, energy_diffs):
        if diff <= threshold_val:
            converged_cutoff = int(cutoff)
            break

    return orm.Dict(dict={
        'cutoff_values': cutoff_values,
        'energies': energies,
        'energy_per_atom': energy_per_atom,
        'energy_diff_from_max': energy_diffs,
        'converged_cutoff': converged_cutoff,
        'convergence_achieved': converged_cutoff is not None,
        'reference_energy_per_atom': ref_energy,
        'n_atoms': n_atoms,
    })


@task.calcfunction
def analyze_kpoints_convergence(
    conv_data: orm.Dict,
    threshold: orm.Float,
    structure: orm.StructureData,
) -> orm.Dict:
    """
    Analyze k-points convergence data.

    Processes raw convergence data and determines the k-spacing value
    at which energy is converged within the specified threshold.

    Args:
        conv_data: Dict from vasp.v2.converge with k-points convergence results
        threshold: Energy threshold in eV/atom
        structure: Input structure (for atom count normalization)

    Returns:
        Dict with:
            - kspacing_values: list of tested k-spacing values (A^-1)
            - energies: list of total energies (eV)
            - energy_per_atom: list of energies per atom (eV/atom)
            - converged_kspacing: float, coarsest k-spacing achieving convergence
            - energy_diff_from_densest: list of energy differences from finest grid
            - convergence_achieved: bool
    """
    data = conv_data.get_dict()
    threshold_val = threshold.value
    n_atoms = len(structure.sites)

    # Extract k-spacing values and energies
    kspacing_values = data.get('kspacing', data.get('kpoints_spacing',
                               data.get('kspacing_values', [])))
    energies = data.get('energy', data.get('total_energy', data.get('energies', [])))

    # Handle nested format: {'data': [{'kspacing': x, 'energy': y}, ...]}
    if 'data' in data and isinstance(data['data'], list):
        kspacing_values = [
            item.get('kspacing', item.get('kpoints_spacing', 0))
            for item in data['data']
        ]
        energies = [
            item.get('energy', item.get('total_energy', 0))
            for item in data['data']
        ]

    # Sort by k-spacing value (ascending = finer to coarser... wait, smaller = finer)
    # Sort descending so index 0 is coarsest, last is finest
    if kspacing_values and energies:
        sorted_pairs = sorted(zip(kspacing_values, energies), key=lambda x: x[0],
                              reverse=True)
        kspacing_values = [p[0] for p in sorted_pairs]
        energies = [p[1] for p in sorted_pairs]

    # Normalize to per-atom energies
    energy_per_atom = [e / n_atoms for e in energies] if energies else []

    # Reference energy (finest grid = smallest k-spacing = last element)
    ref_energy = energy_per_atom[-1] if energy_per_atom else 0.0

    # Calculate energy differences from reference
    energy_diffs = [abs(e - ref_energy) for e in energy_per_atom]

    # Find coarsest k-spacing (largest value) where convergence is achieved
    # We iterate from coarsest to finest, stop at first converged
    converged_kspacing = None
    for ksp, diff in zip(kspacing_values, energy_diffs):
        if diff <= threshold_val:
            converged_kspacing = float(ksp)
            break

    return orm.Dict(dict={
        'kspacing_values': kspacing_values,
        'energies': energies,
        'energy_per_atom': energy_per_atom,
        'energy_diff_from_densest': energy_diffs,
        'converged_kspacing': converged_kspacing,
        'convergence_achieved': converged_kspacing is not None,
        'reference_energy_per_atom': ref_energy,
        'n_atoms': n_atoms,
    })


@task.calcfunction
def extract_recommended_parameters(
    cutoff_analysis: orm.Dict,
    kpoints_analysis: orm.Dict,
    threshold: orm.Float,
) -> orm.Dict:
    """
    Extract final recommended parameters from convergence analysis.

    Combines cutoff and k-points analysis to provide final recommendations
    with a safety margin.

    Args:
        cutoff_analysis: Dict from analyze_cutoff_convergence
        kpoints_analysis: Dict from analyze_kpoints_convergence
        threshold: Energy threshold used for analysis

    Returns:
        Dict with:
            - recommended_cutoff: int, recommended ENCUT (with safety margin)
            - recommended_kspacing: float, recommended k-spacing
            - threshold_used: float, the convergence threshold
            - cutoff_converged: bool
            - kpoints_converged: bool
            - summary: str, human-readable summary
    """
    cutoff_data = cutoff_analysis.get_dict()
    kpoints_data = kpoints_analysis.get_dict()
    threshold_val = threshold.value

    # Get converged values
    converged_cutoff = cutoff_data.get('converged_cutoff')
    converged_kspacing = kpoints_data.get('converged_kspacing')

    # Apply safety margin to cutoff (add one step, typically 50 eV)
    recommended_cutoff = None
    if converged_cutoff is not None:
        cutoff_values = cutoff_data.get('cutoff_values', [])
        if cutoff_values:
            # Find next higher cutoff if available
            higher_cutoffs = [c for c in cutoff_values if c > converged_cutoff]
            if higher_cutoffs:
                recommended_cutoff = int(min(higher_cutoffs))
            else:
                recommended_cutoff = int(converged_cutoff)

    # Apply safety margin to k-spacing (use slightly denser grid)
    recommended_kspacing = None
    if converged_kspacing is not None:
        kspacing_values = kpoints_data.get('kspacing_values', [])
        if kspacing_values:
            # Find next finer k-spacing (smaller value) if available
            finer_spacings = [k for k in kspacing_values if k < converged_kspacing]
            if finer_spacings:
                recommended_kspacing = float(max(finer_spacings))
            else:
                recommended_kspacing = float(converged_kspacing)

    # Build summary
    summary_parts = []
    if recommended_cutoff:
        summary_parts.append(
            f"ENCUT: {recommended_cutoff} eV (converged at {converged_cutoff} eV)"
        )
    else:
        summary_parts.append("ENCUT: NOT CONVERGED - increase cutoff_stop")

    if recommended_kspacing:
        summary_parts.append(
            f"k-spacing: {recommended_kspacing} A^-1 "
            f"(converged at {converged_kspacing} A^-1)"
        )
    else:
        summary_parts.append("k-spacing: NOT CONVERGED - decrease kspacing_stop")

    summary_parts.append(f"Threshold: {threshold_val * 1000:.1f} meV/atom")

    return orm.Dict(dict={
        'recommended_cutoff': recommended_cutoff,
        'recommended_kspacing': recommended_kspacing,
        'threshold_used': threshold_val,
        'cutoff_converged': converged_cutoff is not None,
        'kpoints_converged': converged_kspacing is not None,
        'converged_cutoff_raw': converged_cutoff,
        'converged_kspacing_raw': converged_kspacing,
        'summary': '\n'.join(summary_parts),
    })
