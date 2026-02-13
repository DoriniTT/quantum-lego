"""Test that the public API is importable from the top-level package.

All public functions should be importable via ``from quantum_lego import ...``
rather than the internal ``from quantum_lego.core import ...``.

All tests are tier1 (requires AiiDA importable, but no running profile).
"""

import pytest


@pytest.mark.tier1
def test_core_functions_importable():
    """Core workflow functions are importable from quantum_lego."""
    from quantum_lego import (
        quick_vasp,
        quick_vasp_batch,
        quick_vasp_sequential,
        quick_dos,
        quick_dos_batch,
        quick_dos_sequential,
        quick_hubbard_u,
        quick_aimd,
        quick_qe,
        quick_qe_sequential,
    )
    assert callable(quick_vasp)
    assert callable(quick_vasp_batch)
    assert callable(quick_vasp_sequential)
    assert callable(quick_dos)
    assert callable(quick_dos_batch)
    assert callable(quick_dos_sequential)
    assert callable(quick_hubbard_u)
    assert callable(quick_aimd)
    assert callable(quick_qe)
    assert callable(quick_qe_sequential)


@pytest.mark.tier1
def test_result_functions_importable():
    """Result extraction functions are importable from quantum_lego."""
    from quantum_lego import (
        get_results,
        get_energy,
        get_batch_results,
        get_batch_energies,
        get_batch_results_from_workgraph,
        print_results,
        get_dos_results,
        print_dos_results,
        get_batch_dos_results,
        print_batch_dos_results,
        get_sequential_results,
        get_stage_results,
        print_sequential_results,
    )
    assert callable(get_results)
    assert callable(get_energy)
    assert callable(get_batch_results)
    assert callable(get_batch_energies)
    assert callable(get_batch_results_from_workgraph)
    assert callable(print_results)
    assert callable(get_dos_results)
    assert callable(print_dos_results)
    assert callable(get_batch_dos_results)
    assert callable(print_batch_dos_results)
    assert callable(get_sequential_results)
    assert callable(get_stage_results)
    assert callable(print_sequential_results)


@pytest.mark.tier1
def test_utility_functions_importable():
    """Utility functions are importable from quantum_lego."""
    from quantum_lego import (
        get_status,
        export_files,
        list_calculations,
        get_restart_info,
    )
    assert callable(get_status)
    assert callable(export_files)
    assert callable(list_calculations)
    assert callable(get_restart_info)


@pytest.mark.tier1
def test_type_definitions_importable():
    """Type definitions are importable from quantum_lego."""
    from quantum_lego import (
        ResourceDict,
        SchedulerOptions,
        StageContext,
        StageTasksResult,
        VaspResults,
        DosResults,
        BatchResults,
    )
    # Type definitions exist (TypedDict classes)
    assert ResourceDict is not None
    assert SchedulerOptions is not None
    assert StageContext is not None
    assert StageTasksResult is not None
    assert VaspResults is not None
    assert DosResults is not None
    assert BatchResults is not None


@pytest.mark.tier1
def test_all_exports_match():
    """__all__ in quantum_lego.core matches what's importable from quantum_lego."""
    import quantum_lego
    import quantum_lego.core as core

    for name in core.__all__:
        assert hasattr(quantum_lego, name), (
            f"{name!r} is in quantum_lego.core.__all__ but not importable "
            f"from quantum_lego"
        )
