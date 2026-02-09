"""WorkGraph builder for Hubbard U calculation using VASP linear response method.

This module implements the linear response approach to calculate the Hubbard U
parameter for LSDA+U calculations. The workflow follows the VASP wiki method:

1. Ground State: DFT calculation without +U, saves CHGCAR/WAVECAR
2. Non-SCF Response: With LDAUTYPE=3 and ICHARG=11 (fixed charge)
3. SCF Response: With LDAUTYPE=3, no ICHARG (charge evolves)

Steps 2-3 are repeated for multiple potential values, and U is calculated
from linear regression of the occupation changes.

Reference: https://www.vasp.at/wiki/index.php/Calculate_U_for_LSDA+U
"""

import typing as t

from aiida import orm
from aiida.plugins import WorkflowFactory
from aiida_workgraph import WorkGraph, task

from ..utils import get_vasp_parser_settings
from .tasks import (
    extract_d_electron_occupation,
    calculate_occupation_response,
    calculate_hubbard_u_linear_regression,
    gather_responses,
    compile_u_calculation_summary,
)
from .utils import (
    prepare_ground_state_incar,
    prepare_response_incar,
    validate_target_species,
    get_species_order_from_structure,
    DEFAULT_POTENTIAL_VALUES,
)


def build_u_calculation_workgraph(
    structure: orm.StructureData,
    code_label: str,
    potential_family: str,
    potential_mapping: dict,
    target_species: str,
    potential_values: t.Optional[t.List[float]] = None,
    ldaul: int = 2,
    ldauj: float = 0.0,
    ground_state_parameters: t.Optional[dict] = None,
    response_parameters: t.Optional[dict] = None,
    options: t.Optional[dict] = None,
    kpoints_spacing: float = 0.03,
    clean_workdir: bool = False,
    name: str = 'HubbardUCalculation',
) -> WorkGraph:
    """
    Build a WorkGraph to calculate the Hubbard U parameter using linear response.

    The workflow performs:
    1. Ground state calculation (no +U) to establish baseline d-occupancy
    2. For each potential value V in potential_values:
       - Non-SCF response (ICHARG=11): Fixed charge, apply potential
       - SCF response: Allow charge to evolve
    3. Linear regression to calculate U from multiple responses

    Args:
        structure: AiiDA StructureData for the material
        code_label: VASP code label (e.g., 'VASP-6.5.1@cluster')
        potential_family: POTCAR family name (e.g., 'PBE.54')
        potential_mapping: Element to potential mapping (e.g., {'Fe': 'Fe', 'O': 'O'})
        target_species: Element symbol for Hubbard U (e.g., 'Fe', 'Ni', 'Mn')
        potential_values: List of potentials to apply (eV). Default: [-0.2, -0.1, 0.0, 0.1, 0.2]
        ldaul: Angular momentum (2=d electrons, 3=f electrons). Default: 2
        ldauj: Exchange J parameter. Default: 0.0
        ground_state_parameters: Base INCAR for ground state (ENCUT, EDIFF, etc.)
        response_parameters: Base INCAR for response calculations (can override)
        options: Scheduler options (resources, queue_name, etc.)
        kpoints_spacing: K-point spacing in 1/Angstrom. Default: 0.03
        clean_workdir: Whether to clean remote work directories. Default: False
        name: WorkGraph name. Default: 'HubbardUCalculation'

    Returns:
        WorkGraph ready to submit

    Example:
        >>> from aiida import orm
        >>> structure = orm.load_node(123)  # Your NiO structure
        >>> wg = build_u_calculation_workgraph(
        ...     structure=structure,
        ...     code_label='VASP-6.5.1@cluster',
        ...     potential_family='PBE.54',
        ...     potential_mapping={'Ni': 'Ni', 'O': 'O'},
        ...     target_species='Ni',
        ...     ground_state_parameters={'ENCUT': 520, 'EDIFF': 1e-6, 'ISMEAR': 0, 'SIGMA': 0.05},
        ...     options={'resources': {'num_machines': 1, 'num_cores_per_machine': 24}},
        ... )
        >>> wg.submit()
    """
    # Validate inputs
    validate_target_species(structure, target_species)

    # Set defaults
    if potential_values is None:
        potential_values = DEFAULT_POTENTIAL_VALUES

    if ground_state_parameters is None:
        ground_state_parameters = {
            'ENCUT': 520,
            'EDIFF': 1e-6,
            'ISMEAR': 0,
            'SIGMA': 0.05,
            'PREC': 'Accurate',
            'ALGO': 'Normal',
            'NELM': 100,
        }

    if response_parameters is None:
        response_parameters = ground_state_parameters.copy()

    if options is None:
        options = {
            'resources': {'num_machines': 1, 'num_cores_per_machine': 24},
            'max_wallclock_seconds': 86400,
        }

    # Get species order for LDAU arrays
    all_species = get_species_order_from_structure(structure)

    # Load VASP code and wrap as task
    code = orm.load_code(code_label)
    VaspWorkChain = WorkflowFactory('vasp.v2.vasp')
    VaspTask = task(VaspWorkChain)

    # Get parser settings that request orbital data
    settings = get_vasp_parser_settings(
        add_energy=True,
        add_trajectory=True,
        add_structure=True,
        add_kpoints=True,
    )

    # Create WorkGraph
    wg = WorkGraph(name=name)

    # =========================================================================
    # STEP 1: Ground State Calculation
    # =========================================================================
    gs_incar = prepare_ground_state_incar(
        base_params=ground_state_parameters,
        lmaxmix=4 if ldaul == 2 else 6,  # 4 for d, 6 for f electrons
    )

    ground_state = wg.add_task(
        VaspTask,
        name='ground_state',
        structure=structure,
        code=code,
        parameters=orm.Dict(dict={'incar': gs_incar}),
        options=orm.Dict(dict=options),
        potential_family=potential_family,
        potential_mapping=orm.Dict(dict=potential_mapping),
        kpoints_spacing=kpoints_spacing,
        clean_workdir=False,  # MUST keep CHGCAR/WAVECAR
        settings=orm.Dict(dict=settings),
    )

    # Extract ground state d-electron occupation
    gs_occupation = wg.add_task(
        extract_d_electron_occupation,
        name='gs_occupation',
        retrieved=ground_state.outputs.retrieved,
        target_species=orm.Str(target_species),
        structure=structure,
    )

    # =========================================================================
    # STEP 2-3: Response Calculations for Each Potential Value
    # =========================================================================
    response_tasks = {}

    for i, V in enumerate(potential_values):
        label = f'V_{i}'
        V_str = f'{V:+.2f}'.replace('.', 'p').replace('-', 'm').replace('+', 'p')

        # ----- Non-SCF Response (ICHARG=11) -----
        nscf_incar = prepare_response_incar(
            base_params=response_parameters,
            potential_value=V,
            target_species=target_species,
            all_species=all_species,
            ldaul=ldaul,
            ldauj=ldauj,
            is_scf=False,  # ICHARG=11
            lmaxmix=4 if ldaul == 2 else 6,
        )

        nscf_task = wg.add_task(
            VaspTask,
            name=f'nscf_{V_str}',
            structure=structure,
            code=code,
            parameters=orm.Dict(dict={'incar': nscf_incar}),
            options=orm.Dict(dict=options),
            potential_family=potential_family,
            potential_mapping=orm.Dict(dict=potential_mapping),
            kpoints_spacing=kpoints_spacing,
            restart_folder=ground_state.outputs.remote_folder,
            clean_workdir=clean_workdir,
            settings=orm.Dict(dict=settings),
        )

        # Extract NSCF d-occupation
        nscf_occ = wg.add_task(
            extract_d_electron_occupation,
            name=f'nscf_occ_{V_str}',
            retrieved=nscf_task.outputs.retrieved,
            target_species=orm.Str(target_species),
            structure=structure,
        )

        # ----- SCF Response (no ICHARG) -----
        scf_incar = prepare_response_incar(
            base_params=response_parameters,
            potential_value=V,
            target_species=target_species,
            all_species=all_species,
            ldaul=ldaul,
            ldauj=ldauj,
            is_scf=True,  # No ICHARG
            lmaxmix=4 if ldaul == 2 else 6,
        )

        scf_task = wg.add_task(
            VaspTask,
            name=f'scf_{V_str}',
            structure=structure,
            code=code,
            parameters=orm.Dict(dict={'incar': scf_incar}),
            options=orm.Dict(dict=options),
            potential_family=potential_family,
            potential_mapping=orm.Dict(dict=potential_mapping),
            kpoints_spacing=kpoints_spacing,
            restart_folder=ground_state.outputs.remote_folder,
            clean_workdir=clean_workdir,
            settings=orm.Dict(dict=settings),
        )

        # Extract SCF d-occupation
        scf_occ = wg.add_task(
            extract_d_electron_occupation,
            name=f'scf_occ_{V_str}',
            retrieved=scf_task.outputs.retrieved,
            target_species=orm.Str(target_species),
            structure=structure,
        )

        # Calculate response for this potential
        response = wg.add_task(
            calculate_occupation_response,
            name=f'response_{V_str}',
            ground_state_occupation=gs_occupation.outputs.result,
            nscf_occupation=nscf_occ.outputs.result,
            scf_occupation=scf_occ.outputs.result,
            potential_value=orm.Float(V),
        )

        response_tasks[label] = response

    # =========================================================================
    # STEP 4: Gather Responses and Calculate U
    # =========================================================================
    # Gather all responses into a list
    gather_kwargs = {label: task.outputs.result for label, task in response_tasks.items()}
    gathered = wg.add_task(
        gather_responses,
        name='gather_responses',
        **gather_kwargs,
    )

    # Calculate U via linear regression
    calc_u = wg.add_task(
        calculate_hubbard_u_linear_regression,
        name='calculate_u',
        responses=gathered.outputs.result,
    )

    # =========================================================================
    # STEP 5: Compile Comprehensive Summary
    # =========================================================================
    summary = wg.add_task(
        compile_u_calculation_summary,
        name='compile_summary',
        hubbard_u_result=calc_u.outputs.result,
        ground_state_occupation=gs_occupation.outputs.result,
        structure=structure,
        target_species=orm.Str(target_species),
        ldaul=orm.Int(ldaul),
    )

    # =========================================================================
    # Set WorkGraph Outputs
    # =========================================================================
    # Primary output: comprehensive summary
    wg.outputs.summary = summary.outputs.result

    # Raw U calculation result (for backward compatibility)
    wg.outputs.hubbard_u_result = calc_u.outputs.result

    # Ground state outputs
    wg.outputs.ground_state_occupation = gs_occupation.outputs.result
    wg.outputs.ground_state_misc = ground_state.outputs.misc
    wg.outputs.ground_state_remote = ground_state.outputs.remote_folder
    # Note: ground state is a static SCF (NSW=0), so no relaxed structure output

    # Response data (gathered list of all responses)
    wg.outputs.all_responses = gathered.outputs.result

    return wg


def get_u_calculation_results(workgraph) -> dict:
    """
    Extract comprehensive results from a completed U calculation WorkGraph.

    Returns the full summary Dict containing all organized results including
    the calculated U value, linear fit statistics, response data, and
    ground state information.

    Args:
        workgraph: Completed WorkGraph (live object or loaded node PK/UUID)
            Can be a WorkGraph object, an AiiDA Node, or a PK/UUID integer/string.

    Returns:
        dict with organized sections:
            - summary: Key results (U, target_species, structure info)
            - linear_fit: Regression statistics (slopes, R², intercepts)
            - response_data: Raw response values per potential
            - ground_state: Ground state occupation details
            - metadata: Calculation metadata

    Example:
        >>> results = get_u_calculation_results(completed_wg)
        >>> print(f"Hubbard U = {results['summary']['hubbard_u_eV']:.2f} eV")
        >>> print(f"Target: {results['summary']['target_species']} {results['summary']['orbital_type']}-electrons")
        >>> print(f"SCF fit R² = {results['linear_fit']['chi_scf']['r_squared']:.4f}")
    """
    from aiida.common.links import LinkType

    # Handle different input types
    if isinstance(workgraph, (int, str)):
        workgraph = orm.load_node(workgraph)

    # For stored AiiDA nodes (WorkGraphNode), traverse called calcfunctions
    if hasattr(workgraph, 'base') and hasattr(workgraph.base, 'links'):
        calcfuncs = workgraph.base.links.get_outgoing(link_type=LinkType.CALL_CALC)

        # Try to find compile_summary first (comprehensive results)
        for link in calcfuncs.all():
            if link.link_label == 'compile_summary':
                # Get the 'result' output of the calcfunction
                for out_link in link.node.base.links.get_outgoing(
                    link_type=LinkType.CREATE
                ).all():
                    if out_link.link_label == 'result':
                        return out_link.node.get_dict()

        # Fallback: try calculate_u (raw U calculation output)
        for link in calcfuncs.all():
            if link.link_label == 'calculate_u':
                for out_link in link.node.base.links.get_outgoing(
                    link_type=LinkType.CREATE
                ).all():
                    if out_link.link_label == 'result':
                        return out_link.node.get_dict()

    # For WorkGraph objects with tasks attribute (live objects)
    if hasattr(workgraph, 'tasks'):
        try:
            summary_task = workgraph.tasks.get('compile_summary')
            if summary_task and hasattr(summary_task.outputs, 'result'):
                return summary_task.outputs.result.value.get_dict()
        except Exception:
            pass

        try:
            calc_u_task = workgraph.tasks.get('calculate_u')
            if calc_u_task and hasattr(calc_u_task.outputs, 'result'):
                return calc_u_task.outputs.result.value.get_dict()
        except Exception:
            pass

    raise ValueError(
        "Could not find results in workgraph outputs. "
        "Ensure the workgraph has completed successfully."
    )


def get_u_value(workgraph) -> float:
    """
    Get just the Hubbard U value from a completed WorkGraph.

    Convenience function for quick access to the U value.

    Args:
        workgraph: Completed WorkGraph from build_u_calculation_workgraph

    Returns:
        Hubbard U value in eV

    Example:
        >>> U = get_u_value(completed_wg)
        >>> print(f"U = {U:.2f} eV")
    """
    results = get_u_calculation_results(workgraph)

    # Handle both new summary format and old format
    if 'summary' in results:
        return results['summary']['hubbard_u_eV']
    else:
        return results['U']


def print_u_calculation_summary(workgraph) -> None:
    """
    Print a formatted summary of the Hubbard U calculation results.

    Args:
        workgraph: Completed WorkGraph from build_u_calculation_workgraph

    Example:
        >>> print_u_calculation_summary(completed_wg)
    """
    results = get_u_calculation_results(workgraph)

    # Handle both new and old format
    if 'summary' not in results:
        # Old format - just print raw values
        print(f"Hubbard U = {results['U']:.3f} eV")
        print(f"SCF response slope (χ): {results['chi_slope']:.4f}")
        print(f"NSCF response slope (χ₀): {results['chi_0_slope']:.4f}")
        print(f"SCF fit R²: {results['chi_r2']:.4f}")
        print(f"NSCF fit R²: {results['chi_0_r2']:.4f}")
        return

    # New comprehensive format
    s = results['summary']
    lf = results['linear_fit']
    gs = results['ground_state']

    print("=" * 60)
    print("HUBBARD U CALCULATION RESULTS")
    print("=" * 60)

    print(f"\n{'MAIN RESULT':^60}")
    print("-" * 60)
    print(f"  Hubbard U = {s['hubbard_u_eV']:.3f} eV")
    print(f"  Target: {s['target_species']} {s['orbital_type']}-electrons (L={s['ldaul']})")

    print(f"\n{'STRUCTURE':^60}")
    print("-" * 60)
    print(f"  Formula: {s['structure_formula']}")
    print(f"  Total atoms: {s['n_atoms_total']}")
    print(f"  Target atoms ({s['target_species']}): {s['n_target_atoms']}")
    print(f"  Cell volume: {s['cell_volume_A3']:.2f} Å³")

    print(f"\n{'LINEAR REGRESSION':^60}")
    print("-" * 60)
    print(f"  SCF response (χ):")
    print(f"    Slope: {lf['chi_scf']['slope']:.6f}")
    print(f"    R²: {lf['chi_scf']['r_squared']:.6f}")
    print(f"  NSCF response (χ₀):")
    print(f"    Slope: {lf['chi_0_nscf']['slope']:.6f}")
    print(f"    R²: {lf['chi_0_nscf']['r_squared']:.6f}")
    print(f"  Data points: {lf['n_data_points']}")
    print(f"  Formula: {lf['formula_used']}")

    print(f"\n{'GROUND STATE':^60}")
    print("-" * 60)
    print(f"  Average {s['orbital_type']}-occupation per {s['target_species']}: {gs['average_d_per_atom']:.3f} electrons")
    print(f"  Total {s['orbital_type']}-occupation: {gs['total_d_occupation']:.3f} electrons")

    print("\n" + "=" * 60)
