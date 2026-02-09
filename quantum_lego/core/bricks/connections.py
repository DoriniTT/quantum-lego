"""Port declarations and connection validation for the lego brick system.

This module contains ONLY pure-Python code with no AiiDA dependencies,
so it can be imported in tier1 tests without a running AiiDA profile.

Each brick's PORTS dict declares its inputs and outputs. The
validate_connections() function checks all inter-stage connections
before submission.
"""

from ..retrieve_defaults import build_vasp_retrieve


_VASP_RETRIEVE_STAGE_TYPES = {
    'vasp',
    'batch',
    'aimd',
    'neb',
    'dos',
}

# ---------------------------------------------------------------------------
# Recognized port types — every port's 'type' field must be in this set.
# ---------------------------------------------------------------------------

PORT_TYPES = {
    'structure',
    'energy',
    'misc',
    'remote_folder',
    'retrieved',
    'dos_data',
    'projectors',
    'bader_charges',
    'trajectory',
    'convergence',
    'file',
    'hubbard_responses',
    'hubbard_occupation',
    'hubbard_result',
    'neb_images',
}


# ---------------------------------------------------------------------------
# PORTS declarations for each brick type
# ---------------------------------------------------------------------------

VASP_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'auto',
            'description': 'Atomic structure',
        },
        'restart_folder': {
            'type': 'remote_folder',
            'required': False,
            'source': 'restart',
            'description': 'Remote folder for WAVECAR/CHGCAR restart',
        },
    },
    'outputs': {
        'structure': {
            'type': 'structure',
            'conditional': {'incar_key': 'nsw', 'operator': '>', 'value': 0},
            'description': 'Relaxed structure (only meaningful if nsw > 0)',
        },
        'energy': {
            'type': 'energy',
            'description': 'Total energy (eV)',
        },
        'misc': {
            'type': 'misc',
            'description': 'Parsed VASP results dict',
        },
        'remote_folder': {
            'type': 'remote_folder',
            'description': 'Remote calculation directory',
        },
        'retrieved': {
            'type': 'retrieved',
            'description': 'Retrieved files from cluster',
        },
    },
}

DOS_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'structure_from',
            'description': 'Structure to compute DOS for',
        },
    },
    'outputs': {
        'energy': {
            'type': 'energy',
            'description': 'SCF energy',
        },
        'scf_misc': {
            'type': 'misc',
            'description': 'SCF parsed results',
        },
        'dos_misc': {
            'type': 'misc',
            'description': 'DOS parsed results',
        },
        'dos': {
            'type': 'dos_data',
            'description': 'DOS ArrayData',
        },
        'projectors': {
            'type': 'projectors',
            'description': 'Projected DOS data',
        },
        'scf_remote': {
            'type': 'remote_folder',
            'description': 'SCF remote folder',
        },
        'scf_retrieved': {
            'type': 'retrieved',
            'description': 'SCF retrieved files',
        },
        'dos_remote': {
            'type': 'remote_folder',
            'description': 'DOS remote folder',
        },
        'dos_retrieved': {
            'type': 'retrieved',
            'description': 'DOS retrieved files',
        },
        # NOTE: no 'structure' output — DOS doesn't modify structure
    },
}

BATCH_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'structure_from',
            'description': 'Structure for all sub-calculations',
        },
    },
    'outputs': {
        '{label}_energy': {
            'type': 'energy',
            'description': 'Energy per sub-calculation',
            'per_calculation': True,
        },
        '{label}_misc': {
            'type': 'misc',
            'description': 'Parsed results per sub-calculation',
            'per_calculation': True,
        },
        '{label}_remote_folder': {
            'type': 'remote_folder',
            'description': 'Remote folder per sub-calculation',
            'per_calculation': True,
        },
        '{label}_retrieved': {
            'type': 'retrieved',
            'description': 'Retrieved files per sub-calculation',
            'per_calculation': True,
        },
        # NOTE: no 'structure' output — batch does not produce structures
    },
}

BADER_PORTS = {
    'inputs': {
        'charge_files': {
            'type': 'retrieved',
            'required': True,
            'source': 'charge_from',
            'compatible_bricks': ['vasp'],
            'prerequisites': {
                'incar': {'laechg': True, 'lcharg': True},
                'retrieve': ['AECCAR0', 'AECCAR2', 'CHGCAR', 'OUTCAR'],
            },
            'description': 'Retrieved folder with AECCAR0, AECCAR2, CHGCAR',
        },
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'charge_from',
            'compatible_bricks': ['vasp'],
            'description': 'Structure for element-to-atom mapping',
        },
    },
    'outputs': {
        'charges': {
            'type': 'bader_charges',
            'description': 'Per-atom Bader charges (Dict)',
        },
        'acf': {
            'type': 'file',
            'description': 'ACF.dat (SinglefileData)',
        },
        'bcf': {
            'type': 'file',
            'description': 'BCF.dat (SinglefileData)',
        },
        'avf': {
            'type': 'file',
            'description': 'AVF.dat (SinglefileData)',
        },
    },
}

HUBBARD_RESPONSE_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'structure_from',
            'description': 'Structure for response calculations',
        },
        'ground_state_remote': {
            'type': 'remote_folder',
            'required': True,
            'source': 'ground_state_from',
            'compatible_bricks': ['vasp'],
            'prerequisites': {
                'incar': {'lorbit': 11, 'lwave': True, 'lcharg': True},
                'retrieve': ['OUTCAR'],
            },
            'description': 'Ground state remote folder for WAVECAR/CHGCAR restart',
        },
        'ground_state_retrieved': {
            'type': 'retrieved',
            'required': True,
            'source': 'ground_state_from',
            'compatible_bricks': ['vasp'],
            'description': 'Ground state retrieved files (OUTCAR for occupation)',
        },
    },
    'outputs': {
        'responses': {
            'type': 'hubbard_responses',
            'description': 'Gathered response data (List of dicts)',
        },
        'ground_state_occupation': {
            'type': 'hubbard_occupation',
            'description': 'Ground state d-electron occupation',
        },
        # NOTE: no 'structure' output — responses don't modify structure
    },
}

HUBBARD_ANALYSIS_PORTS = {
    'inputs': {
        'responses': {
            'type': 'hubbard_responses',
            'required': True,
            'source': 'response_from',
            'compatible_bricks': ['hubbard_response'],
            'description': 'Gathered response data from hubbard_response stage',
        },
        'ground_state_occupation': {
            'type': 'hubbard_occupation',
            'required': True,
            'source': 'response_from',
            'compatible_bricks': ['hubbard_response'],
            'description': 'Ground state occupation from hubbard_response stage',
        },
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'structure_from',
            'description': 'Structure for summary metadata',
        },
    },
    'outputs': {
        'summary': {
            'type': 'hubbard_result',
            'description': 'Full U calculation summary (Dict)',
        },
        'hubbard_u_result': {
            'type': 'hubbard_result',
            'description': 'Linear regression result (Dict)',
        },
        # NOTE: no 'structure' output
    },
}

CONVERGENCE_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': False,
            'source': 'structure_from',
            'description': 'Structure (optional, falls back to initial)',
        },
    },
    'outputs': {
        'cutoff_analysis': {
            'type': 'convergence',
            'description': 'ENCUT convergence analysis',
        },
        'kpoints_analysis': {
            'type': 'convergence',
            'description': 'K-points convergence analysis',
        },
        'recommendations': {
            'type': 'convergence',
            'description': 'Recommended parameters',
        },
        # NOTE: no 'structure' output
    },
}

AIMD_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'auto',
            'description': 'Atomic structure (or supercell)',
        },
        'restart_folder': {
            'type': 'remote_folder',
            'required': False,
            'source': 'restart',
            'description': 'Remote folder for WAVECAR restart from previous AIMD stage',
        },
    },
    'outputs': {
        'structure': {
            'type': 'structure',
            'description': 'Final MD structure',
        },
        'energy': {
            'type': 'energy',
            'description': 'Final total energy (eV)',
        },
        'misc': {
            'type': 'misc',
            'description': 'Parsed VASP results dict',
        },
        'remote_folder': {
            'type': 'remote_folder',
            'description': 'Remote calculation directory',
        },
        'retrieved': {
            'type': 'retrieved',
            'description': 'Retrieved files from cluster',
        },
        'trajectory': {
            'type': 'trajectory',
            'description': 'MD trajectory (positions, cells, energies per step)',
        },
    },
}

QE_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'auto',
            'description': 'Atomic structure for QE pw.x calculation',
        },
        'restart_folder': {
            'type': 'remote_folder',
            'required': False,
            'source': 'restart',
            'description': 'Remote folder for parent_folder restart',
        },
    },
    'outputs': {
        'structure': {
            'type': 'structure',
            'conditional': {
                'config_path': ['parameters', 'CONTROL', 'calculation'],
                'operator': 'in',
                'value': ['relax', 'vc-relax'],
            },
            'description': 'Relaxed structure (only if calculation is relax or vc-relax)',
        },
        'energy': {
            'type': 'energy',
            'description': 'Total energy (eV)',
        },
        'output_parameters': {
            'type': 'misc',
            'description': 'Parsed QE output dict',
        },
        'remote_folder': {
            'type': 'remote_folder',
            'description': 'Remote calc directory',
        },
        'retrieved': {
            'type': 'retrieved',
            'description': 'Retrieved files',
        },
    },
}

CP2K_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': True,
            'source': 'auto',
            'description': 'Atomic structure for CP2K calculation',
        },
        'restart_folder': {
            'type': 'remote_folder',
            'required': False,
            'source': 'restart',
            'description': 'Remote folder for parent_calc_folder restart',
        },
    },
    'outputs': {
        'structure': {
            'type': 'structure',
            'conditional': {
                'config_path': ['parameters', 'GLOBAL', 'RUN_TYPE'],
                'operator': 'in',
                'value': ['GEO_OPT', 'CELL_OPT', 'MD'],
            },
            'description': 'Relaxed/final structure (only if RUN_TYPE produces new structure)',
        },
        'energy': {
            'type': 'energy',
            'description': 'Total energy (eV, converted from Hartree)',
        },
        'output_parameters': {
            'type': 'misc',
            'description': 'Parsed CP2K output dict',
        },
        'remote_folder': {
            'type': 'remote_folder',
            'description': 'Remote calculation directory',
        },
        'retrieved': {
            'type': 'retrieved',
            'description': 'Retrieved files from cluster',
        },
        'trajectory': {
            'type': 'trajectory',
            'conditional': {
                'config_path': ['parameters', 'GLOBAL', 'RUN_TYPE'],
                'operator': '==',
                'value': 'MD',
            },
            'description': 'Trajectory data (MD runs only)',
        },
    },
}

THICKNESS_PORTS = {
    'inputs': {
        'structure': {
            'type': 'structure',
            'required': False,
            'source': 'structure_from',
            'description': 'Bulk structure (optional, falls back to initial)',
        },
        'energy': {
            'type': 'energy',
            'required': False,
            'source': 'energy_from',
            'compatible_bricks': ['vasp'],
            'description': 'Bulk energy from a previous VASP stage',
        },
    },
    'outputs': {
        'convergence_results': {
            'type': 'convergence',
            'description': 'Thickness convergence analysis with surface energies',
        },
        # NOTE: no 'structure' output — produces convergence analysis only
    },
}

GENERATE_NEB_IMAGES_PORTS = {
    'inputs': {
        'initial_structure': {
            'type': 'structure',
            'required': True,
            'source': 'initial_from',
            'compatible_bricks': ['vasp'],
            'description': 'Initial relaxed structure from a VASP stage',
        },
        'final_structure': {
            'type': 'structure',
            'required': True,
            'source': 'final_from',
            'compatible_bricks': ['vasp'],
            'description': 'Final relaxed structure from a VASP stage',
        },
    },
    'outputs': {
        'images': {
            'type': 'neb_images',
            'description': 'Generated intermediate NEB image structures',
        },
    },
}

NEB_PORTS = {
    'inputs': {
        'initial_structure': {
            'type': 'structure',
            'required': True,
            'source': 'initial_from',
            'compatible_bricks': ['vasp'],
            'description': 'Initial endpoint structure from a VASP stage',
        },
        'final_structure': {
            'type': 'structure',
            'required': True,
            'source': 'final_from',
            'compatible_bricks': ['vasp'],
            'description': 'Final endpoint structure from a VASP stage',
        },
        'images': {
            'type': 'neb_images',
            'required': False,
            'source': 'images_from',
            'compatible_bricks': ['generate_neb_images'],
            'description': 'Intermediate images from generate_neb_images stage',
        },
        'restart_folder': {
            'type': 'remote_folder',
            'required': False,
            'source': 'restart',
            'compatible_bricks': ['neb'],
            'description': 'Remote folder from previous NEB stage for restart',
        },
    },
    'outputs': {
        'structure': {
            'type': 'structure',
            'description': 'NEB images structure output',
        },
        'misc': {
            'type': 'misc',
            'description': 'Parsed NEB results dict',
        },
        'remote_folder': {
            'type': 'remote_folder',
            'description': 'Remote NEB calculation directory',
        },
        'retrieved': {
            'type': 'retrieved',
            'description': 'Retrieved files from NEB calculation',
        },
        'trajectory': {
            'type': 'trajectory',
            'description': 'NEB trajectory data (if parser produced it)',
        },
        'dos': {
            'type': 'dos_data',
            'description': 'DOS ArrayData output (optional)',
        },
        'projectors': {
            'type': 'projectors',
            'description': 'Projected DOS data (optional)',
        },
    },
}

# Registry mapping brick type name -> PORTS dict
ALL_PORTS = {
    'vasp': VASP_PORTS,
    'dos': DOS_PORTS,
    'batch': BATCH_PORTS,
    'bader': BADER_PORTS,
    'hubbard_response': HUBBARD_RESPONSE_PORTS,
    'hubbard_analysis': HUBBARD_ANALYSIS_PORTS,
    'convergence': CONVERGENCE_PORTS,
    'thickness': THICKNESS_PORTS,
    'aimd': AIMD_PORTS,
    'qe': QE_PORTS,
    'cp2k': CP2K_PORTS,
    'generate_neb_images': GENERATE_NEB_IMAGES_PORTS,
    'neb': NEB_PORTS,
}


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------

def get_brick_info(brick_type: str) -> dict:
    """Get port information for a brick type.

    Args:
        brick_type: One of the valid brick types.

    Returns:
        Dict with 'inputs' and 'outputs' port declarations.
    """
    return _get_ports(brick_type)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _get_ports(brick_type: str) -> dict:
    """Look up PORTS dict for a brick type.

    Args:
        brick_type: One of 'vasp', 'dos', 'batch', 'bader', 'convergence'.

    Returns:
        The PORTS dict for that brick type.

    Raises:
        ValueError: If the brick type is unknown.
    """
    if brick_type not in ALL_PORTS:
        raise ValueError(
            f"Unknown brick type '{brick_type}'. "
            f"Must be one of {tuple(ALL_PORTS.keys())}"
        )
    return ALL_PORTS[brick_type]


def _validate_port_types(ports: dict, brick_name: str) -> None:
    """Validate that all port type strings are recognized.

    Args:
        ports: PORTS dict with 'inputs' and 'outputs'.
        brick_name: Brick type name (for error messages).

    Raises:
        ValueError: If any port type is unrecognized.
    """
    for section in ('inputs', 'outputs'):
        for port_name, port in ports.get(section, {}).items():
            ptype = port['type']
            if ptype not in PORT_TYPES:
                raise ValueError(
                    f"Unknown port type '{ptype}' in "
                    f"{brick_name}.{section}.{port_name}"
                )


def _evaluate_conditional(conditional, stage_config: dict) -> bool:
    """Evaluate a conditional dict against a stage's config.

    Conditionals determine whether an output is meaningful. For example,
    VASP's structure output is only meaningful when nsw > 0, and QE's
    structure output is only meaningful for relax/vc-relax calculations.

    Args:
        conditional: None (always True), or dict with
            'operator', 'value', and either 'incar_key' (for VASP) or
            'config_path' (for nested dict lookups like QE).
        stage_config: The raw stage configuration dict.

    Returns:
        True if the condition is met (output is available).

    Raises:
        ValueError: If conditional is a string (no eval) or has
            unknown operator.
    """
    if conditional is None:
        return True
    if isinstance(conditional, str):
        raise ValueError(
            f"Conditional must be a dict, not a string: '{conditional}'. "
            f"Use {{'incar_key': 'nsw', 'operator': '>', 'value': 0}} instead."
        )

    op = conditional['operator']
    threshold = conditional['value']

    # Resolve actual value from either incar_key (VASP) or config_path (QE, nested)
    if 'incar_key' in conditional:
        # VASP-style: read from stage['incar'][key]
        incar = stage_config.get('incar', {})
        key = conditional['incar_key']
        actual = incar.get(key, 0)  # VASP defaults most keys to 0
    elif 'config_path' in conditional:
        # Nested lookup: config_path = ['parameters', 'CONTROL', 'calculation']
        # traverses stage['parameters']['CONTROL']['calculation']
        config_path = conditional['config_path']
        if not isinstance(config_path, list):
            raise ValueError(f"config_path must be a list, got {type(config_path)}")

        actual = stage_config
        for key in config_path:
            if isinstance(actual, dict):
                actual = actual.get(key)
                if actual is None:
                    break
            else:
                actual = None
                break

        # If path not resolved, default to None (won't match numeric comparisons)
        if actual is None:
            actual = 0  # Default for numeric comparisons
    else:
        raise ValueError("Conditional must have either 'incar_key' or 'config_path'")

    # Apply operator
    if op == '>':
        return actual > threshold
    elif op == '>=':
        return actual >= threshold
    elif op == '==':
        return actual == threshold
    elif op == '!=':
        return actual != threshold
    elif op == '<':
        return actual < threshold
    elif op == '<=':
        return actual <= threshold
    elif op == 'in':
        # Check if actual_value is in the expected list
        if not isinstance(threshold, (list, tuple)):
            raise ValueError(f"'in' operator requires value to be a list, "
                             f"got {type(threshold)}")
        return actual in threshold
    else:
        raise ValueError(f"Unknown operator '{op}' in conditional")


def _get_nested_value(config: dict, path: list):
    """Traverse a nested dict using a path list.

    Args:
        config: The configuration dict to traverse.
        path: List of keys, e.g., ['parameters', 'CONTROL', 'calculation']

    Returns:
        The value at the path, or None if any key is missing.
    """
    value = config
    for key in path:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return None
        else:
            return None
    return value


def validate_connections(stages: list) -> list:
    """Validate all inter-stage connections before submission.

    Checks port type compatibility, brick compatibility constraints,
    prerequisites (INCAR settings, retrieve lists), conditional output
    warnings, and auto-resolution for VASP structure input.

    Args:
        stages: List of stage configuration dicts.

    Returns:
        List of warning strings (empty if no warnings).

    Raises:
        ValueError: If any connection is invalid.
    """
    available_outputs = {}    # stage_name -> {port_name: port_type}
    stage_configs = {}        # stage_name -> raw stage dict
    stage_types = {}          # stage_name -> brick type string
    output_conditionals = {}  # stage_name -> {port_name: conditional_dict}
    warn_list = []

    for i, stage in enumerate(stages):
        name = stage['name']
        brick_type = stage.get('type', 'vasp')
        ports = _get_ports(brick_type)

        # Brick-specific schema constraints not expressible with PORTS alone.
        if brick_type == 'neb':
            has_images_from = stage.get('images_from') is not None
            has_images_dir = stage.get('images_dir') is not None
            if has_images_from == has_images_dir:
                raise ValueError(
                    f"Stage '{name}': NEB stages require exactly one of "
                    f"'images_from' or 'images_dir'"
                )

        stage_configs[name] = stage
        stage_types[name] = brick_type

        # Validate port type strings are recognized
        _validate_port_types(ports, brick_type)

        # Check every required input can be satisfied
        for input_name, input_port in ports['inputs'].items():
            if input_port.get('required', True) is False:
                # Optional port — skip if source field not present
                source_key = input_port['source']
                if stage.get(source_key) is None:
                    continue

            source_key = input_port['source']

            # ── Handle 'auto' source (VASP structure) ──
            if source_key == 'auto':
                structure_from = stage.get('structure_from', 'previous')

                if i == 0:
                    # First stage: always uses initial structure
                    pass
                elif structure_from == 'input':
                    # Explicit initial structure → always valid
                    pass
                elif structure_from == 'previous':
                    # Check previous stage has a structure output
                    prev_name = stages[i - 1]['name']
                    if prev_name in available_outputs:
                        prev_types = {
                            pname: ptype
                            for pname, ptype in
                            available_outputs[prev_name].items()
                        }
                        has_structure = any(
                            t == 'structure' for t in prev_types.values()
                        )
                        if not has_structure:
                            producers = [
                                sn for sn, outs in available_outputs.items()
                                if any(
                                    t == 'structure' for t in outs.values()
                                )
                            ]
                            raise ValueError(
                                f"Stage '{name}': previous stage "
                                f"'{prev_name}' "
                                f"(type: {stage_types[prev_name]}) doesn't "
                                f"produce a 'structure' output. Use "
                                f"'structure_from' to reference a stage "
                                f"that does. "
                                f"Stages with structure: {producers}"
                            )
                        # Check conditional warning
                        prev_conds = output_conditionals.get(
                            prev_name, {}
                        )
                        if 'structure' in prev_conds:
                            cond = prev_conds['structure']
                            if not _evaluate_conditional(
                                cond, stage_configs[prev_name]
                            ):
                                # Build warning message based on conditional type
                                if 'incar_key' in cond:
                                    cond_key = cond['incar_key']
                                    cond_val = stage_configs[prev_name].get('incar', {}).get(cond_key, 0)
                                    warn_list.append(
                                        f"Warning: Stage '{prev_name}' has "
                                        f"{cond_key}={cond_val} "
                                        f"(static calculation). Its 'structure' "
                                        f"output may not be meaningful."
                                    )
                                elif 'config_path' in cond:
                                    path = cond['config_path']
                                    cond_val = _get_nested_value(stage_configs[prev_name], path)
                                    warn_list.append(
                                        f"Warning: Stage '{prev_name}' has "
                                        f"{'.'.join(path)}={cond_val} "
                                        f"(static calculation). Its 'structure' "
                                        f"output may not be meaningful."
                                    )
                else:
                    # structure_from is an explicit stage name
                    if structure_from not in available_outputs:
                        raise ValueError(
                            f"Stage '{name}': "
                            f"structure_from='{structure_from}' "
                            f"references unknown stage"
                        )
                    ref_outputs = available_outputs[structure_from]
                    if not any(
                        t == 'structure' for t in ref_outputs.values()
                    ):
                        producers = [
                            sn for sn, outs in available_outputs.items()
                            if any(
                                t == 'structure' for t in outs.values()
                            )
                        ]
                        raise ValueError(
                            f"Stage '{name}': "
                            f"structure_from='{structure_from}' "
                            f"references stage '{structure_from}' "
                            f"(type: {stage_types[structure_from]}), which "
                            f"doesn't produce a 'structure' output. "
                            f"Stages with structure: {producers}"
                        )
                    # Check conditional warning
                    ref_conds = output_conditionals.get(
                        structure_from, {}
                    )
                    if 'structure' in ref_conds:
                        cond = ref_conds['structure']
                        if not _evaluate_conditional(
                            cond, stage_configs[structure_from]
                        ):
                            # Build warning message based on conditional type
                            if 'incar_key' in cond:
                                cond_key = cond['incar_key']
                                cond_val = stage_configs[structure_from].get('incar', {}).get(cond_key, 0)
                                warn_list.append(
                                    f"Warning: Stage '{structure_from}' has "
                                    f"{cond_key}={cond_val} "
                                    f"(static calculation). Its 'structure' "
                                    f"output may not be meaningful."
                                )
                            elif 'config_path' in cond:
                                path = cond['config_path']
                                cond_val = _get_nested_value(stage_configs[structure_from], path)
                                warn_list.append(
                                    f"Warning: Stage '{structure_from}' has "
                                    f"{'.'.join(path)}={cond_val} "
                                    f"(static calculation). Its 'structure' "
                                    f"output may not be meaningful."
                                )
                continue  # auto handling done

            # ── Handle explicit source fields ──
            ref_stage_name = stage.get(source_key)
            if ref_stage_name is None:
                if input_port.get('required', True):
                    raise ValueError(
                        f"Stage '{name}': input '{input_name}' requires "
                        f"'{source_key}' field but it's missing"
                    )
                continue

            # 'input' means use initial structure → always valid
            if ref_stage_name == 'input':
                continue

            # Check referenced stage exists
            if ref_stage_name not in available_outputs:
                raise ValueError(
                    f"Stage '{name}': '{source_key}={ref_stage_name}' "
                    f"references unknown stage"
                )

            # Check type compatibility
            ref_outputs = available_outputs[ref_stage_name]
            matching = [
                pname for pname, ptype in ref_outputs.items()
                if ptype == input_port['type']
            ]
            if not matching:
                producers = [
                    sn for sn, outs in available_outputs.items()
                    if any(
                        t == input_port['type'] for t in outs.values()
                    )
                ]
                raise ValueError(
                    f"Stage '{name}': input '{input_name}' needs type "
                    f"'{input_port['type']}' but stage "
                    f"'{ref_stage_name}' "
                    f"(type: {stage_types[ref_stage_name]}) doesn't "
                    f"produce it. "
                    f"Stages with '{input_port['type']}': {producers}"
                )

            # Check brick compatibility constraint
            if 'compatible_bricks' in input_port:
                ref_brick_type = stage_types[ref_stage_name]
                if ref_brick_type not in input_port['compatible_bricks']:
                    raise ValueError(
                        f"Stage '{name}': input '{input_name}' is only "
                        f"compatible with bricks: "
                        f"{input_port['compatible_bricks']}, "
                        f"but '{ref_stage_name}' is type "
                        f"'{ref_brick_type}'"
                    )

            # Check prerequisites
            prereqs = input_port.get('prerequisites')
            if prereqs:
                ref_config = stage_configs[ref_stage_name]
                ref_incar = ref_config.get('incar', {})
                ref_retrieve = ref_config.get('retrieve', [])
                if stage_types.get(ref_stage_name) in _VASP_RETRIEVE_STAGE_TYPES:
                    ref_retrieve = build_vasp_retrieve(ref_retrieve)

                missing_incar = {}
                for key, required_val in prereqs.get('incar', {}).items():
                    if ref_incar.get(key) != required_val:
                        missing_incar[key] = required_val

                missing_retrieve = [
                    f for f in prereqs.get('retrieve', [])
                    if f not in ref_retrieve
                ]

                if missing_incar or missing_retrieve:
                    msg = (
                        f"Stage '{name}' connects to stage "
                        f"'{ref_stage_name}' via '{source_key}', but "
                        f"'{ref_stage_name}' is missing required settings:"
                    )
                    if missing_incar:
                        items = ', '.join(
                            f"{k}={v}" for k, v in missing_incar.items()
                        )
                        msg += f"\n  Missing INCAR: {items}"
                    if missing_retrieve:
                        msg += (
                            f"\n  Missing retrieve: "
                            f"{', '.join(missing_retrieve)}"
                        )
                    raise ValueError(msg)

            # Check conditional warning on the referenced output
            ref_conds = output_conditionals.get(ref_stage_name, {})
            for matched_port in matching:
                if matched_port in ref_conds:
                    cond = ref_conds[matched_port]
                    if not _evaluate_conditional(
                        cond, stage_configs[ref_stage_name]
                    ):
                        # Suppress for bricks that handle it themselves
                        if not input_port.get(
                            'handles_conditional', False
                        ):
                            # Build warning message based on conditional type
                            if 'incar_key' in cond:
                                cond_key = cond['incar_key']
                                cond_val = stage_configs[ref_stage_name].get('incar', {}).get(cond_key, 0)
                                warn_list.append(
                                    f"Warning: Stage '{ref_stage_name}' has "
                                    f"{cond_key}={cond_val} "
                                    f"(static calculation). Its "
                                    f"'{matched_port}' output may not be "
                                    f"meaningful."
                                )
                            elif 'config_path' in cond:
                                path = cond['config_path']
                                cond_val = _get_nested_value(stage_configs[ref_stage_name], path)
                                warn_list.append(
                                    f"Warning: Stage '{ref_stage_name}' has "
                                    f"{'.'.join(path)}={cond_val} "
                                    f"(static calculation). Its "
                                    f"'{matched_port}' output may not be "
                                    f"meaningful."
                                )

        # ── Register this stage's outputs ──
        stage_outputs = {}
        stage_conds = {}
        for port_name, port in ports['outputs'].items():
            stage_outputs[port_name] = port['type']
            if 'conditional' in port:
                stage_conds[port_name] = port['conditional']

        available_outputs[name] = stage_outputs
        output_conditionals[name] = stage_conds

    return warn_list
