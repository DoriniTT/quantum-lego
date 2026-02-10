#!/usr/bin/env python
"""Inspect status and energies for a submitted calculation or WorkGraph PK.

API functions: get_status, get_energy, get_results
Difficulty: beginner
Usage:
    python examples/01_getting_started/check_results.py <PK>
"""

import argparse

from aiida import orm

from examples._shared.config import setup_profile
from quantum_lego import get_energy, get_results, get_status


def _print_task_energies(node: orm.ProcessNode) -> None:
    if not hasattr(node, 'tasks'):
        return

    print('\nEnergies by task:')
    for name in sorted(node.tasks):
        if not name.startswith('energy_'):
            continue
        task = node.tasks[name]
        if not hasattr(task.outputs, 'result'):
            continue
        result = task.outputs.result
        if not getattr(result, 'value', None):
            continue
        energy = result.value.value
        key = name.replace('energy_', '')
        print(f'  {key}: {energy:.6f} eV')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Inspect a quantum-lego WorkGraph PK.')
    parser.add_argument('pk', type=int, help='WorkGraph PK to inspect')
    args = parser.parse_args()

    setup_profile()
    node = orm.load_node(args.pk)

    print(f'PK: {args.pk}')
    print(f'Status: {get_status(args.pk)}')

    try:
        energy = get_energy(args.pk)
        print(f'Energy: {energy:.6f} eV')
    except Exception:
        print('Energy: unavailable (not a finished single-energy result)')

    try:
        results = get_results(args.pk)
        if isinstance(results, dict):
            print(f'Result keys: {sorted(results.keys())}')
    except Exception:
        print('Detailed results: unavailable for this node type')

    _print_task_energies(node)
