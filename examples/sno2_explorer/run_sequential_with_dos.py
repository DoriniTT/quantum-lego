"""
Sequential VASP workflow with DOS: SnO2 relaxation + DOS calculation.

This example tests:
  1. Connection validation (port/connections system)
  2. max_concurrent_jobs (limits parallel execution)
  3. Nested output namespaces (grouped by stage in WorkGraph)

Stages:
  stage1/vasp       (relax) - Relax primitive SnO2 cell
  stage2/scf + /dos (dos)   - DOS on relaxed structure (SCF + non-SCF DOS)

Monitor:  verdi process show <PK>
Results:  print_sequential_results(result)
"""

from aiida import orm, load_profile
from ase.io import read
from pathlib import Path

load_profile('presto')

from quantum_lego.core import quick_vasp_sequential, print_sequential_results
from quantum_lego.core.bricks.connections import get_brick_info

# Show available ports for each brick type used
print("=== Connection system: brick port info ===")
for brick_type in ['vasp', 'dos']:
    info = get_brick_info(brick_type)
    print(f"\n{brick_type} brick:")
    print(f"  Inputs:  {list(info['inputs'].keys())}")
    print(f"  Outputs: {list(info['outputs'].keys())}")

# Load structure
structure_file = Path(__file__).parent / 'sno2.vasp'
structure = orm.StructureData(ase=read(str(structure_file), format='vasp'))

# Localwork configuration (test locally first)
code_label = 'VASP-6.5.1@localwork'
potential_family = 'PBE'
potential_mapping = {'Sn': 'Sn_d', 'O': 'O'}

options = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 8,
    },
}

# Light INCAR for testing (6-atom cell)
incar_relax = {
    'nsw': 50,
    'ibrion': 2,
    'isif': 2,
    'ediff': 1e-4,
    'encut': 400,
    'prec': 'Normal',
    'ismear': 0,
    'sigma': 0.05,
    'algo': 'Normal',
    'lwave': True,
    'lcharg': True,
}

# Stage definitions (three-section pattern: identity / connections / configuration)
stages = [
    # Stage 1: VASP relaxation
    {
        # ── Identity ──
        'name': 'relax',
        'type': 'vasp',
        'incar': incar_relax,
        'restart': None,
        # structure: auto (first stage → uses initial input)
        'kpoints_spacing': 0.06,
        'retrieve': ['CONTCAR', 'OUTCAR'],
    },
    # Stage 2: DOS calculation on relaxed structure
    {
        # ── Identity ──
        'name': 'dos',
        'type': 'dos',
        'structure_from': 'relax',  # Connection validated by port system
        'scf_incar': {
            'encut': 400,
            'ediff': 1e-5,
            'ismear': 0,
            'sigma': 0.05,
            'prec': 'Normal',
            'algo': 'Normal',
            'nsw': 0,
            'ibrion': -1,
        },
        'dos_incar': {
            'encut': 400,
            'prec': 'Normal',
            'nedos': 2000,
            'lorbit': 11,
            'ismear': -5,
            'nsw': 0,
            'ibrion': -1,
        },
        'kpoints_spacing': 0.06,
        'dos_kpoints_spacing': 0.04,
        'retrieve': ['DOSCAR'],
    },
]

if __name__ == '__main__':
    # max_concurrent_jobs=1: localwork runs ONE job at a time
    result = quick_vasp_sequential(
        structure=structure,
        stages=stages,
        code_label=code_label,
        potential_family=potential_family,
        potential_mapping=potential_mapping,
        options=options,
        name='sno2_sequential_with_dos',
        max_concurrent_jobs=1,
    )

    pk = result['__workgraph_pk__']
    stage_names = result['__stage_names__']
    stage_types = result['__stage_types__']
    stage_namespaces = result['__stage_namespaces__']

    print(f"\nWorkGraph PK: {pk}")
    print(f"Stage names: {stage_names}")
    print(f"Stage types: {stage_types}")
    print(f"Stage namespaces: {stage_namespaces}")

    # Show expected namespaced outputs
    print("\n=== Expected namespaced outputs ===")
    for name in stage_names:
        ns_map = stage_namespaces[name]
        brick_type = stage_types[name]
        info = get_brick_info(brick_type)
        if brick_type == 'dos':
            scf_ns = ns_map['scf']
            dos_ns = ns_map['dos']
            print(f"  {name} ({brick_type}):")
            print(f"    {scf_ns}/scf: misc, remote, retrieved")
            print(f"    {dos_ns}/dos: dos, projectors, misc, remote, retrieved")
        else:
            ns = ns_map['main']
            output_names = list(info['outputs'].keys())
            print(f"  {name} ({brick_type}): {ns}/{brick_type} -> {output_names}")

    print(f"\nMonitor: verdi process show {pk}")
    print("\nAfter completion, view results with:")
    print("  from quantum_lego.core import print_sequential_results, get_stage_results")
    print(f"  result = {{'__workgraph_pk__': {pk}, "
          f"'__stage_names__': {stage_names}, "
          f"'__stage_types__': {stage_types}, "
          f"'__stage_namespaces__': {stage_namespaces}}}")
    print("  print_sequential_results(result)")
    print("  dos_result = get_stage_results(result, 'dos')")
    print("  print(dos_result)")
    print(f"\nVerify outputs: verdi process show {pk}")
    print("  (outputs grouped: stage1/vasp, stage2/scf + stage2/dos)")
