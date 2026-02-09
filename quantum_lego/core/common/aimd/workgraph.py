"""Main workgraph builder for AIMD module."""
import typing as t
from aiida import orm
from aiida_workgraph import WorkGraph
from .utils import (
    validate_stage_sequence,
    validate_supercell_spec,
)
from .tasks import create_supercell


def build_aimd_workgraph(
    structures: dict[str, t.Union[orm.StructureData, int]],
    aimd_stages: list[dict],
    code_label: str,
    builder_inputs: dict,
    supercell_specs: dict[str, list[int]] = None,
    structure_overrides: dict[str, dict] = None,
    stage_overrides: dict[int, dict] = None,
    matrix_overrides: dict[tuple, dict] = None,
    max_concurrent_jobs: int = None,
    name: str = 'AIMDWorkGraph',
) -> WorkGraph:
    """
    Build AIMD workgraph with sequential stages.

    Args:
        structures: {name: StructureData or PK} - input structures
        aimd_stages: [{'TEBEG': K, 'NSW': N, ...}, ...] - sequential AIMD stages with VASP INCAR parameters
                     Required: TEBEG (initial temperature), NSW (MD steps)
                     Optional: TEEND (final temperature, defaults to TEBEG), POTIM (timestep fs),
                              MDALGO (thermostat algorithm), SMASS (Nosé mass parameter)
        code_label: VASP code label (e.g., 'VASP6.5.0@cluster02')
        builder_inputs: Default builder config for all (structure, stage) combinations
        supercell_specs: {structure_name: [nx, ny, nz]} - optional supercell per structure
        structure_overrides: Per-structure builder overrides.
                           Only 'parameters'/'incar' keys are applied.
                           Other keys (kpoints, options, etc.) are ignored.
                           Format: {structure_name: {'parameters': {'incar': {...}}}}
        stage_overrides: Per-stage builder overrides (0-indexed).
                        Only 'parameters'/'incar' keys are applied.
                        Format: {stage_idx: {'parameters': {'incar': {...}}}}
        matrix_overrides: Per-(structure, stage) builder overrides.
                         Only 'parameters'/'incar' keys are applied.
                         Format: {(structure_name, stage_idx): {'parameters': {'incar': {...}}}}
        max_concurrent_jobs: Limit parallel VASP calculations (None = unlimited)
        name: WorkGraph name

    Returns:
        WorkGraph ready to submit

    Override priority: matrix_overrides > stage_overrides > structure_overrides > builder_inputs

    Note: Only INCAR parameters can be overridden. kpoints_spacing, options,
          potential_mapping, and other builder inputs remain uniform across all structures.

    Example:
        wg = build_aimd_workgraph(
            structures={'slab1': structure1, 'slab2': pk2},
            aimd_stages=[
                {'TEBEG': 300, 'NSW': 100, 'POTIM': 2.0},
                {'TEBEG': 300, 'NSW': 500, 'POTIM': 1.5},
            ],
            code_label='VASP6.5.0@cluster02',
            builder_inputs={
                'parameters': {'incar': {'PREC': 'Normal', 'ENCUT': 400}},
                'kpoints_spacing': 0.5,
                'potential_family': 'PBE',
                'potential_mapping': {},
                'options': {'resources': {'num_machines': 1, 'num_cores_per_machine': 24}},
                'clean_workdir': False,
            },
            # Optional overrides
            structure_overrides={
                'slab2': {'parameters': {'incar': {'ENCUT': 500}}}  # slab2 uses ENCUT=500
            },
            stage_overrides={
                1: {'parameters': {'incar': {'PREC': 'Accurate'}}}  # stage 1 uses Accurate
            },
            matrix_overrides={
                ('slab1', 1): {'parameters': {'incar': {'ALGO': 'Fast'}}}  # slab1+stage1 specific
            },
            max_concurrent_jobs=4,
        )
    """
    # Validate inputs
    validate_stage_sequence(aimd_stages)

    if supercell_specs:
        for struct_name, spec in supercell_specs.items():
            if struct_name not in structures:
                raise ValueError(f"supercell_specs key '{struct_name}' not in structures")
            validate_supercell_spec(spec)

    # Initialize defaults
    if structure_overrides is None:
        structure_overrides = {}
    if stage_overrides is None:
        stage_overrides = {}
    if matrix_overrides is None:
        matrix_overrides = {}

    # Create workgraph
    wg = WorkGraph(name=name)

    if max_concurrent_jobs:
        wg.max_number_jobs = max_concurrent_jobs

    # 1. Load and prepare structures
    prepared_structures = {}
    supercell_outputs = {}

    for struct_name, struct_input in structures.items():
        # Load structure if PK
        if isinstance(struct_input, int):
            struct = orm.load_node(struct_input)
            if not isinstance(struct, orm.StructureData):
                raise ValueError(
                    f"PK {struct_input} for '{struct_name}' is not a StructureData node"
                )
        else:
            struct = struct_input

        # Create supercell if requested
        if supercell_specs and struct_name in supercell_specs:
            sc_task = wg.add_task(
                create_supercell,
                structure=struct,
                spec=orm.List(list=supercell_specs[struct_name]),
                name=f'create_supercell_{struct_name}',
            )
            prepared_structures[struct_name] = sc_task.outputs.result
            supercell_outputs[struct_name] = sc_task.outputs.result
        else:
            prepared_structures[struct_name] = struct

    # 2. Run sequential AIMD stages
    # Import aimd_single_stage_scatter from parent aimd_functions module
    from quantum_lego.core.common.aimd_functions import aimd_single_stage_scatter

    stage_results = {}
    current_structures = prepared_structures
    current_remote_folders = {}  # Empty dict, will be populated after first stage

    for stage_idx, stage_config in enumerate(aimd_stages):
        # Validate required AIMD parameters
        if 'TEBEG' not in stage_config or 'NSW' not in stage_config:
            raise ValueError(
                f"Stage {stage_idx}: aimd_stages must contain 'TEBEG' and 'NSW'. "
                f"Got: {list(stage_config.keys())}"
            )

        # Build per-structure INCAR overrides for this stage
        structure_incar_overrides = {}

        for struct_name in prepared_structures:
            # Start with empty override
            override = {}

            # Apply structure-level override (if exists)
            if structure_overrides and struct_name in structure_overrides:
                struct_override = structure_overrides[struct_name]
                if 'parameters' in struct_override and 'incar' in struct_override['parameters']:
                    override.update(struct_override['parameters']['incar'])

            # Apply stage-level override (if exists)
            if stage_overrides and stage_idx in stage_overrides:
                stage_override = stage_overrides[stage_idx]
                if 'parameters' in stage_override and 'incar' in stage_override['parameters']:
                    override.update(stage_override['parameters']['incar'])

            # Apply matrix-level override (highest priority)
            matrix_key = (struct_name, stage_idx)
            if matrix_overrides and matrix_key in matrix_overrides:
                matrix_override = matrix_overrides[matrix_key]
                if 'parameters' in matrix_override and 'incar' in matrix_override['parameters']:
                    override.update(matrix_override['parameters']['incar'])

            # Only add to dict if we have actual overrides
            if override:
                structure_incar_overrides[struct_name] = override

        # Extract base INCAR from builder_inputs
        if 'parameters' in builder_inputs and 'incar' in builder_inputs['parameters']:
            base_incar = builder_inputs['parameters']['incar'].copy()
        else:
            base_incar = {}

        # Load code
        code = orm.load_code(code_label)

        # Create stage task
        stage_task = wg.add_task(
            aimd_single_stage_scatter,
            slabs=current_structures,
            stage_config=stage_config,
            code=code,
            base_aimd_parameters=base_incar,
            structure_aimd_overrides=structure_incar_overrides if structure_incar_overrides else None,
            potential_family=builder_inputs.get('potential_family', 'PBE'),
            potential_mapping=builder_inputs.get('potential_mapping', {}),
            options=builder_inputs.get('options', {}),
            kpoints_spacing=builder_inputs.get('kpoints_spacing', 0.5),
            clean_workdir=builder_inputs.get('clean_workdir', False),
            restart_folders=current_remote_folders,
            max_number_jobs=max_concurrent_jobs,
            name=f'stage_{stage_idx}_aimd',
        )

        # Update for next stage
        current_structures = stage_task.outputs.structures
        current_remote_folders = stage_task.outputs.remote_folders

    # Note: We don't expose outputs explicitly because they're nested dicts of Sockets
    # Users can access results through the WorkGraph node after completion:
    #   wg_node = orm.load_node(wg.pk)
    #   results = wg_node.outputs

    return wg
