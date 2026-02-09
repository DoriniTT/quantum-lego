#!/usr/bin/env python
"""
Check results from an explorer WorkGraph.

Usage:
    python check_results.py <PK>
"""

import sys
from aiida import orm, load_profile
from quantum_lego.core import get_status

load_profile('presto')

pk = int(sys.argv[1])
node = orm.load_node(pk)

print(f"PK: {pk}")
print(f"Status: {get_status(pk)}")

# Extract energies from tasks
if hasattr(node, 'tasks'):
    print("\nEnergies:")
    for name in sorted(node.tasks):
        if name.startswith('energy_'):
            key = name.replace('energy_', '')
            task = node.tasks[name]
            if hasattr(task.outputs, 'result') and task.outputs.result.value:
                energy = task.outputs.result.value.value
                print(f"  {key}: {energy:.6f} eV")
