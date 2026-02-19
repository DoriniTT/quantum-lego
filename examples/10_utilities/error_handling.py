#!/usr/bin/env python
"""Error handling patterns for quantum-lego calculations.

Demonstrates how to monitor calculations, detect failures, and apply common
recovery strategies using the quantum-lego utilities.

API functions: get_status, get_results, get_energy
Difficulty: beginner
Usage:
    python examples/10_utilities/error_handling.py
"""

from __future__ import annotations

import time

from quantum_lego.core.console import (
    console,
    print_error,
    print_section_header,
    print_success,
    print_warning,
)


# ---------------------------------------------------------------------------
# Pattern 1: Poll-until-done with timeout
# ---------------------------------------------------------------------------

def wait_for_calculation(pk: int, poll_interval: int = 30, timeout: int = 3600) -> str:
    """Poll a calculation until it finishes or times out.

    Args:
        pk: AiiDA process PK to monitor.
        poll_interval: Seconds between status checks.
        timeout: Maximum seconds to wait before giving up.

    Returns:
        Final status string ('finished', 'failed', 'excepted', 'killed').
    """
    from quantum_lego import get_status

    elapsed = 0
    while elapsed < timeout:
        status = get_status(pk)
        console.print(f'  [dim]PK {pk}: status = {status}[/dim]')

        if status in ('finished', 'failed', 'excepted', 'killed'):
            return status

        time.sleep(poll_interval)
        elapsed += poll_interval

    print_warning(f'Timeout after {timeout}s waiting for PK {pk}')
    return 'timeout'


# ---------------------------------------------------------------------------
# Pattern 2: Check status and read results safely
# ---------------------------------------------------------------------------

def safe_get_results(pk: int) -> dict | None:
    """Return results only if the calculation finished successfully.

    Args:
        pk: AiiDA process PK.

    Returns:
        Results dict if successful, None otherwise.
    """
    from quantum_lego import get_results, get_status

    status = get_status(pk)
    if status != 'finished':
        print_error(f'PK {pk} has status "{status}" — skipping result extraction')
        return None

    results = get_results(pk)
    energy = results.get('energy')
    if energy is None:
        print_warning(f'PK {pk}: calculation finished but no energy found')
        return None

    return results


# ---------------------------------------------------------------------------
# Pattern 3: Inspect a WorkGraph for per-stage failures
# ---------------------------------------------------------------------------

def check_workgraph_stages(wg_pk: int) -> dict[str, str]:
    """Return a per-stage status map for a sequential WorkGraph.

    Args:
        wg_pk: PK of a WorkGraph node (e.g. from quick_vasp_sequential).

    Returns:
        Dict mapping stage name -> AiiDA task state string.
    """
    from aiida.orm import load_node

    wg = load_node(wg_pk)
    stage_states: dict[str, str] = {}

    # WorkGraph stores task metadata in its attributes
    tasks_info = getattr(wg.attributes, 'tasks', None)
    if tasks_info is None and hasattr(wg, 'base'):
        tasks_info = wg.base.attributes.get('tasks', {})

    if not tasks_info:
        print_warning(f'WorkGraph PK {wg_pk}: no task metadata found')
        return stage_states

    for task_name, task_data in tasks_info.items():
        state = task_data.get('state', 'unknown')
        stage_states[task_name] = state

    return stage_states


# ---------------------------------------------------------------------------
# Pattern 4: Retry a failed single calculation
# ---------------------------------------------------------------------------

def retry_vasp(
    structure,
    code_label: str,
    incar: dict,
    kpoints_spacing: float,
    potential_family: str,
    potential_mapping: dict,
    options: dict,
    max_attempts: int = 3,
    name: str = 'retry_example',
) -> int | None:
    """Submit a VASP calculation and retry up to max_attempts times on failure.

    Args:
        structure: AiiDA StructureData.
        code_label: VASP code label.
        incar: INCAR dict.
        kpoints_spacing: K-points spacing in 2π/Å.
        potential_family: POTCAR family name.
        potential_mapping: Species-to-POTCAR mapping.
        options: AiiDA scheduler options.
        max_attempts: Number of submission attempts before giving up.
        name: Base name for submitted calculations.

    Returns:
        PK of the successful calculation, or None if all attempts fail.
    """
    from quantum_lego import get_status, quick_vasp

    for attempt in range(1, max_attempts + 1):
        console.print(f'  Attempt {attempt}/{max_attempts}…')
        pk = quick_vasp(
            structure=structure,
            code_label=code_label,
            incar=incar,
            kpoints_spacing=kpoints_spacing,
            potential_family=potential_family,
            potential_mapping=potential_mapping,
            options=options,
            name=f'{name}_attempt{attempt}',
        )

        status = wait_for_calculation(pk, poll_interval=10, timeout=300)
        if status == 'finished':
            print_success(f'Attempt {attempt} succeeded (PK {pk})')
            return pk

        print_warning(f'Attempt {attempt} ended with status "{status}" (PK {pk})')

    print_error(f'All {max_attempts} attempts failed for "{name}"')
    return None


# ---------------------------------------------------------------------------
# Demo: show the patterns without running real calculations
# ---------------------------------------------------------------------------

def demo_status_handling() -> None:
    """Illustrate status-checking logic with mock return values."""
    print_section_header('Pattern 1 — Status polling (mock)')
    console.print()
    console.print('  [dim]  In real usage:[/dim]')
    console.print('  [dim]  status = wait_for_calculation(pk, poll_interval=30, timeout=3600)[/dim]')
    console.print('  [dim]  if status == "finished":[/dim]')
    console.print('  [dim]      results = safe_get_results(pk)[/dim]')
    console.print()

    for mock_status in ('finished', 'failed', 'excepted'):
        if mock_status == 'finished':
            print_success(f'status = "{mock_status}" → proceed to result extraction')
        else:
            print_error(f'status = "{mock_status}" → skip or retry')
    console.print()


def demo_result_validation() -> None:
    """Illustrate result validation with mock data."""
    print_section_header('Pattern 2 — Result validation (mock)')
    console.print()

    mock_results = [
        {'pk': 111, 'energy': -42.1234, 'structure': '<StructureData>', 'status': 'ok'},
        {'pk': 222, 'energy': None, 'status': 'no energy'},
        {'pk': 333, 'energy': -42.9876, 'structure': None, 'status': 'no structure'},
    ]

    for r in mock_results:
        pk = r['pk']
        energy = r.get('energy')
        structure = r.get('structure')

        if energy is None:
            print_warning(f'  PK {pk}: energy missing — check OUTCAR retrieval')
        elif structure is None:
            print_warning(f'  PK {pk}: energy = {energy:.4f} eV, but no structure (static calc)')
        else:
            print_success(f'  PK {pk}: energy = {energy:.4f} eV, structure OK')
    console.print()


def demo_workgraph_inspection() -> None:
    """Illustrate WorkGraph stage inspection."""
    print_section_header('Pattern 3 — WorkGraph stage inspection (mock)')
    console.print()
    console.print('  [dim]  In real usage:[/dim]')
    console.print('  [dim]  stages = check_workgraph_stages(wg_pk)[/dim]')
    console.print('  [dim]  for stage_name, state in stages.items():[/dim]')
    console.print('  [dim]      print(stage_name, state)[/dim]')
    console.print()

    mock_stages = {
        'relax': 'finished',
        'scf': 'finished',
        'dos_calc': 'failed',
    }
    for stage_name, state in mock_stages.items():
        if state == 'finished':
            print_success(f'  {stage_name}: {state}')
        else:
            print_error(f'  {stage_name}: {state} — inspect with: verdi process report <wg_pk>')
    console.print()


def main() -> None:
    console.print()
    console.print('[bold cyan]============================================================[/bold cyan]')
    console.print('[bold cyan]  Quantum Lego — Error Handling Patterns[/bold cyan]')
    console.print('[bold cyan]============================================================[/bold cyan]')
    console.print()
    console.print('[dim]Demonstrates error-handling patterns without running calculations.[/dim]')
    console.print()

    demo_status_handling()
    demo_result_validation()
    demo_workgraph_inspection()

    console.print('[bold green]Done[/bold green] Patterns demonstrated.')
    console.print()
    console.print('See source code for:')
    console.print('  wait_for_calculation()    — poll until done with timeout')
    console.print('  safe_get_results()        — status-guarded result extraction')
    console.print('  check_workgraph_stages()  — per-stage state from a WorkGraph node')
    console.print('  retry_vasp()              — automatic retry on failure')
    console.print()


if __name__ == '__main__':
    main()
