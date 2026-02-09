"""Bader brick for the lego module.

Handles Bader charge analysis stages.
"""

import re
import os
import glob
import shutil
import tempfile
import subprocess
from pathlib import Path

from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import task
from .connections import BADER_PORTS as PORTS  # noqa: F401


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a Bader stage configuration.

    Args:
        stage: Stage configuration dict.
        stage_names: Set of stage names defined so far (before this stage).

    Raises:
        ValueError: If validation fails.
    """
    name = stage['name']

    if 'charge_from' not in stage:
        raise ValueError(
            f"Stage '{name}': bader stages require 'charge_from' "
            f"(name of stage with AECCAR files in retrieved)"
        )

    charge_from = stage['charge_from']
    if charge_from not in stage_names:
        raise ValueError(
            f"Stage '{name}' charge_from='{charge_from}' must reference "
            f"a previous stage name"
        )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create Bader stage tasks in the WorkGraph.

    Args:
        wg: WorkGraph to add tasks to.
        stage: Stage configuration dict.
        stage_name: Unique stage identifier.
        context: Dict with shared context.

    Returns:
        Dict with task references for later stages.
    """
    stage_tasks = context['stage_tasks']
    stage_types = context['stage_types']
    stages = context['stages']

    charge_from = stage['charge_from']

    # Get the retrieved FolderData from the referenced stage
    ref_stage_type = stage_types.get(charge_from, 'vasp')
    if ref_stage_type == 'vasp':
        retrieved_socket = stage_tasks[charge_from]['vasp'].outputs.retrieved
    else:
        raise ValueError(
            f"Bader stage '{stage_name}' charge_from='{charge_from}' must "
            f"reference a VASP stage (got type='{ref_stage_type}')"
        )

    # Resolve structure: prefer output structure (from relaxation),
    # fall back to input structure (for SCF with NSW=0)
    charge_from_stage = stage_tasks[charge_from]
    charge_from_incar = next(
        (s.get('incar', {}) for s in stages if s['name'] == charge_from),
        {},
    )
    if charge_from_incar.get('nsw', 0) > 0:
        stage_structure = charge_from_stage['vasp'].outputs.structure
    else:
        stage_structure = charge_from_stage.get(
            'input_structure',
            charge_from_stage['vasp'].outputs.structure,
        )

    # Add bader analysis task
    bader_task = wg.add_task(
        run_bader_analysis,
        name=f'bader_{stage_name}',
        retrieved=retrieved_socket,
        structure=stage_structure,
    )

    return {
        'bader': bader_task,
        'structure': stage_structure,
    }


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose Bader stage outputs on the WorkGraph.

    Args:
        wg: WorkGraph instance.
        stage_name: Unique stage identifier.
        stage_tasks_result: Dict returned by create_stage_tasks.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, falls back to
                      flat naming with stage_name prefix.
    """
    bader_task = stage_tasks_result['bader']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(wg.outputs, f'{ns}.bader.charges', bader_task.outputs.charges)
        setattr(wg.outputs, f'{ns}.bader.acf', bader_task.outputs.acf)
        setattr(wg.outputs, f'{ns}.bader.bcf', bader_task.outputs.bcf)
        setattr(wg.outputs, f'{ns}.bader.avf', bader_task.outputs.avf)
    else:
        setattr(wg.outputs, f'{stage_name}_charges', bader_task.outputs.charges)
        setattr(wg.outputs, f'{stage_name}_acf', bader_task.outputs.acf)
        setattr(wg.outputs, f'{stage_name}_bcf', bader_task.outputs.bcf)
        setattr(wg.outputs, f'{stage_name}_avf', bader_task.outputs.avf)


def get_stage_results(wg_node, wg_pk: int, stage_name: str,
                      namespace_map: dict = None) -> dict:
    """Extract results from a Bader stage in a sequential workflow.

    Args:
        wg_node: The WorkGraph ProcessNode.
        wg_pk: WorkGraph PK.
        stage_name: Name of the Bader stage.
        namespace_map: Dict mapping output group to namespace string,
                      e.g. {'main': 'stage1'}. If None, uses flat naming.

    Returns:
        Dict with keys: charges, dat_files, pk, stage, type.
    """
    result = {
        'charges': None,
        'dat_files': {},
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'bader',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs

        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'bader', None) if stage_ns is not None else None
            if brick_ns is not None:
                if hasattr(brick_ns, 'charges'):
                    charges_node = brick_ns.charges
                    if hasattr(charges_node, 'get_dict'):
                        result['charges'] = charges_node.get_dict()
                for dat_key in ('acf', 'bcf', 'avf'):
                    if hasattr(brick_ns, dat_key):
                        result['dat_files'][dat_key] = getattr(brick_ns, dat_key)
        else:
            # Flat naming fallback
            # Charges Dict
            charges_attr = f'{stage_name}_charges'
            if hasattr(outputs, charges_attr):
                charges_node = getattr(outputs, charges_attr)
                if hasattr(charges_node, 'get_dict'):
                    result['charges'] = charges_node.get_dict()

            # .dat files: acf, bcf, avf
            for dat_key in ('acf', 'bcf', 'avf'):
                dat_attr = f'{stage_name}_{dat_key}'
                if hasattr(outputs, dat_attr):
                    result['dat_files'][dat_key] = getattr(outputs, dat_attr)

    # Fallback: traverse links
    if result['charges'] is None:
        _extract_bader_stage_from_workgraph(wg_node, stage_name, result)

    return result


def _extract_bader_stage_from_workgraph(
    wg_node, stage_name: str, result: dict
) -> None:
    """Extract Bader stage results by traversing WorkGraph links.

    Args:
        wg_node: The WorkGraph ProcessNode.
        stage_name: Name of the Bader stage.
        result: Result dict to populate (modified in place).
    """
    if not hasattr(wg_node, 'base'):
        return

    bader_task_name = f'bader_{stage_name}'

    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        child_node = link.node
        link_label = link.link_label

        if bader_task_name in link_label or link_label == bader_task_name:
            created = child_node.base.links.get_outgoing(link_type=LinkType.CREATE)
            for out_link in created.all():
                out_label = out_link.link_label
                out_node = out_link.node

                if out_label == 'charges' and hasattr(out_node, 'get_dict'):
                    result['charges'] = out_node.get_dict()
                elif out_label in ('acf', 'bcf', 'avf'):
                    result['dat_files'][out_label] = out_node
            break


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a Bader stage.

    Args:
        index: 1-based stage index.
        stage_name: Name of the stage.
        stage_result: Result dict from get_stage_results.
    """
    print(f"  [{index}] {stage_name} (BADER)")

    if stage_result['charges'] is not None:
        charges = stage_result['charges']
        atoms = charges.get('atoms', [])
        total = charges.get('total_charge', 0.0)
        vacuum = charges.get('vacuum_charge', 0.0)
        print(f"      Atoms analyzed: {len(atoms)}")
        print(f"      Total charge: {total:.5f}")
        print(f"      Vacuum charge: {vacuum:.5f}")

        # Print per-atom charges
        if atoms:
            print("      Per-atom Bader charges:")
            for atom in atoms:
                elem = atom.get('element', '?')
                bader_q = atom.get('bader_charge', None)
                valence = atom.get('valence', None)
                if bader_q is not None:
                    print(
                        f"        #{atom['index']:>3d} {elem:>2s}  "
                        f"charge={bader_q:+.5f}  "
                        f"valence={valence:.1f}  "
                        f"raw={atom['charge']:.5f}"
                    )
                else:
                    print(
                        f"        #{atom['index']:>3d}  "
                        f"charge={atom['charge']:.5f}  "
                        f"vol={atom['volume']:.3f}"
                    )

    dat_files = stage_result.get('dat_files', {})
    if dat_files:
        file_names = ', '.join(
            f"{k}.dat (PK {v.pk})" for k, v in dat_files.items()
        )
        print(f"      Dat files: {file_names}")


# ─── Bader calcfunction tasks ────────────────────────────────────────────────


@task.calcfunction(outputs=['charges', 'acf', 'bcf', 'avf'])
def run_bader_analysis(retrieved: orm.FolderData, structure: orm.StructureData) -> dict:
    """
    Run Bader charge analysis on AECCAR files from a VASP SCF calculation.

    This calcfunction:
    1. Extracts AECCAR0, AECCAR2, CHGCAR from the retrieved FolderData
    2. Sums AECCAR0 + AECCAR2 using pymatgen to create CHGCAR_sum
    3. Runs the bader binary: ``bader CHGCAR -ref CHGCAR_sum``
    4. Parses ACF.dat and returns charges + all .dat files

    Args:
        retrieved: FolderData from a VASP SCF calculation that produced
                   AECCAR0, AECCAR2, and CHGCAR (requires ``laechg: True``
                   in INCAR and these files in ADDITIONAL_RETRIEVE_LIST)
        structure: StructureData with the same atom ordering as the VASP
                   calculation. Used to map atoms to elements and look up
                   valence electron counts (ZVAL) from the OUTCAR.

    Returns:
        dict with:
            - 'charges': orm.Dict with parsed ACF.dat data
            - 'acf': orm.SinglefileData for enriched ACF.dat
            - 'bcf': orm.SinglefileData for BCF.dat
            - 'avf': orm.SinglefileData for AVF.dat
    """
    from pymatgen.io.vasp.outputs import Chgcar

    # Find the bader binary
    bader_path = Path.home() / '.local' / 'bin' / 'bader'
    if not bader_path.exists():
        raise FileNotFoundError(
            f"Bader binary not found at {bader_path}. "
            f"Install it to ~/.local/bin/bader"
        )

    # Create a temporary working directory
    tmpdir = tempfile.mkdtemp(prefix='bader_')
    try:
        # Extract required files from retrieved FolderData
        required_files = ['AECCAR0', 'AECCAR2', 'CHGCAR', 'OUTCAR']
        for fname in required_files:
            try:
                content = retrieved.get_object_content(fname, mode='rb')
            except (FileNotFoundError, OSError):
                raise FileNotFoundError(
                    f"File '{fname}' not found in retrieved FolderData (PK {retrieved.pk}). "
                    f"Ensure the SCF stage has 'laechg': True in INCAR and "
                    f"['AECCAR0', 'AECCAR2', 'CHGCAR'] in the retrieve list."
                )
            filepath = os.path.join(tmpdir, fname)
            with open(filepath, 'wb') as f:
                f.write(content)

        # Sum AECCAR0 + AECCAR2 -> CHGCAR_sum using pymatgen
        aeccar0 = Chgcar.from_file(os.path.join(tmpdir, 'AECCAR0'))
        aeccar2 = Chgcar.from_file(os.path.join(tmpdir, 'AECCAR2'))
        chgcar_sum = aeccar0 + aeccar2
        chgcar_sum_path = os.path.join(tmpdir, 'CHGCAR_sum')
        chgcar_sum.write_file(chgcar_sum_path)

        # Run bader binary
        bader_result = subprocess.run(
            [str(bader_path), 'CHGCAR', '-ref', 'CHGCAR_sum'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )

        if bader_result.returncode != 0:
            raise RuntimeError(
                f"Bader analysis failed (return code {bader_result.returncode}).\n"
                f"stdout: {bader_result.stdout}\n"
                f"stderr: {bader_result.stderr}"
            )

        # Parse ZVAL from OUTCAR using pymatgen
        from pymatgen.io.vasp import Outcar
        zval_dict = {}
        try:
            outcar = Outcar(os.path.join(tmpdir, 'OUTCAR'))
            outcar.read_pseudo_zval()
            zval_dict = outcar.zval_dict
        except Exception:
            pass

        # Build element list from structure
        elements = [site.kind_name for site in structure.sites]

        # Collect all .dat files
        dat_files = glob.glob(os.path.join(tmpdir, '*.dat'))

        # Parse ACF.dat for charges
        acf_path = os.path.join(tmpdir, 'ACF.dat')
        charges_data = _parse_acf_dat(acf_path)

        # Enrich charges data with element, valence, and bader_charge
        for idx, atom in enumerate(charges_data.get('atoms', [])):
            if idx < len(elements):
                elem = elements[idx]
                atom['element'] = elem
                valence = zval_dict.get(elem, 0.0)
                atom['valence'] = valence
                atom['bader_charge'] = valence - atom['charge']

        # Enrich ACF.dat file with ELEMENT, VALENCE, BADER_CHARGE columns
        _enrich_acf_dat(acf_path, elements, zval_dict)

        # Build output dict
        outputs = {}
        outputs['charges'] = orm.Dict(dict=charges_data)

        # Store each .dat file as SinglefileData
        for dat_path in dat_files:
            basename = os.path.basename(dat_path)
            key = basename.replace('.dat', '').lower()
            outputs[key] = orm.SinglefileData(file=dat_path)

        return outputs

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_acf_dat(filepath: str) -> dict:
    """
    Parse ACF.dat file from Bader analysis.

    Args:
        filepath: Path to ACF.dat file

    Returns:
        dict with atoms, total_charge, vacuum_charge, vacuum_volume.
    """
    atoms = []
    total_charge = 0.0
    vacuum_charge = 0.0
    vacuum_volume = 0.0

    with open(filepath, 'r') as f:
        lines = f.readlines()

    for line in lines[2:]:
        line = line.strip()
        if not line or line.startswith('-'):
            continue

        parts = line.split()

        if 'electrons' in line.lower():
            try:
                total_charge = float(parts[-1])
            except (ValueError, IndexError):
                pass
            continue
        if 'vacuum' in line.lower() and 'charge' in line.lower():
            try:
                vacuum_charge = float(parts[-1])
            except (ValueError, IndexError):
                pass
            continue
        if 'vacuum' in line.lower() and 'volume' in line.lower():
            try:
                vacuum_volume = float(parts[-1])
            except (ValueError, IndexError):
                pass
            continue

        try:
            if len(parts) >= 7:
                atom = {
                    'index': int(parts[0]),
                    'x': float(parts[1]),
                    'y': float(parts[2]),
                    'z': float(parts[3]),
                    'charge': float(parts[4]),
                    'min_dist': float(parts[5]),
                    'volume': float(parts[6]),
                }
                atoms.append(atom)
        except (ValueError, IndexError):
            continue

    return {
        'atoms': atoms,
        'total_charge': total_charge,
        'vacuum_charge': vacuum_charge,
        'vacuum_volume': vacuum_volume,
    }


def _enrich_acf_dat(filepath: str, elements: list, zval_dict: dict) -> None:
    """
    Rewrite ACF.dat in place with added ELEMENT, VALENCE, and BADER_CHARGE columns.

    Args:
        filepath: Path to ACF.dat file
        elements: List of element symbols matching atom order
        zval_dict: Dict mapping element symbol to ZVAL
    """
    with open(filepath, 'r') as f:
        lines = f.readlines()

    if len(lines) < 3:
        return

    new_lines = []
    atom_idx = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        if i == 0:
            new_lines.append(
                stripped + '  ELEMENT  VALENCE  BADER_CHARGE\n'
            )
        elif stripped.startswith('-'):
            new_lines.append(
                stripped + '----------------------------\n'
            )
        elif (
            'electrons' in stripped.lower()
            or ('vacuum' in stripped.lower() and 'charge' in stripped.lower())
            or ('vacuum' in stripped.lower() and 'volume' in stripped.lower())
            or not stripped
        ):
            new_lines.append(line)
        else:
            parts = stripped.split()
            try:
                if len(parts) >= 7 and atom_idx < len(elements):
                    elem = elements[atom_idx]
                    valence = zval_dict.get(elem, 0.0)
                    charge = float(parts[4])
                    bader_charge = valence - charge
                    new_lines.append(
                        f'{stripped}  {elem:>7s}  {valence:7.1f}  '
                        f'{bader_charge:12.6f}\n'
                    )
                    atom_idx += 1
                else:
                    new_lines.append(line)
            except (ValueError, IndexError):
                new_lines.append(line)

    with open(filepath, 'w') as f:
        f.writelines(new_lines)
