"""WorkGraph builders for the lego module (permanent compatibility facade).

This module re-exports all workflow builder functions from their
respective domain modules to maintain backward compatibility.
All imports from this module continue to work as before.

This facade is permanent - existing code using
``from quantum_lego.core.workgraph import quick_vasp`` will always work.

The actual implementations live in:
- vasp_workflows.py: quick_vasp, quick_vasp_batch, quick_vasp_sequential
- dos_workflows.py: quick_dos, quick_dos_batch, quick_dos_sequential
- qe_workflows.py: quick_qe, quick_qe_sequential
- specialized_workflows.py: quick_hubbard_u, quick_aimd
- workflow_utils.py: shared utilities and get_batch_results_from_workgraph
"""

from .vasp_workflows import quick_vasp, quick_vasp_batch, quick_vasp_sequential
from .dos_workflows import quick_dos, quick_dos_batch, quick_dos_sequential
from .qe_workflows import quick_qe, quick_qe_sequential
from .specialized_workflows import quick_hubbard_u, quick_aimd
from .workflow_utils import (
    get_batch_results_from_workgraph,
    _builder_to_dict,
    _prepare_builder_inputs,
    _wait_for_completion,
    _validate_stages,
    _build_indexed_output_name,
    _build_combined_trajectory_output_name,
)

__all__ = [
    'quick_vasp',
    'quick_vasp_batch',
    'quick_vasp_sequential',
    'quick_dos',
    'quick_dos_batch',
    'quick_dos_sequential',
    'quick_qe',
    'quick_qe_sequential',
    'quick_hubbard_u',
    'quick_aimd',
    'get_batch_results_from_workgraph',
    '_builder_to_dict',
    '_prepare_builder_inputs',
    '_wait_for_completion',
    '_validate_stages',
    '_build_indexed_output_name',
    '_build_combined_trajectory_output_name',
]
