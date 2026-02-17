"""Formation enthalpy brick for the lego module.

Pure-Python analysis brick that computes the enthalpy of formation (ΔHf) of a
compound from DFT total energies and reference energies.

The intended usage is:
1) relax/compute energy for the target compound (e.g. SnO2)
2) relax/compute energy for reference phases (e.g. Sn metal, O2 molecule)
3) compute ΔHf per reduced formula unit (and per atom)
"""

from __future__ import annotations

import typing as t

from aiida import orm
from aiida.common.links import LinkType
from aiida_workgraph import task

from .connections import FORMATION_ENTHALPY_PORTS as PORTS  # noqa: F401


@task.calcfunction
def compute_formation_enthalpy(
    target_structure: orm.StructureData,
    target_energy: orm.Float,
    **kwargs,
) -> orm.Dict:
    """Compute formation enthalpy from target + reference energies."""
    from ..common.utils import (
        get_atom_counts,
        get_formula_units,
        get_reduced_stoichiometry,
    )

    # Parse references from kwargs:
    #   ref_{EL}_structure, ref_{EL}_energy
    refs: dict[str, dict[str, t.Any]] = {}
    for key, node in kwargs.items():
        if not key.startswith('ref_'):
            continue
        if key.endswith('_structure'):
            el = key[len('ref_'):-len('_structure')]
            refs.setdefault(el, {})['structure'] = node
        elif key.endswith('_energy'):
            el = key[len('ref_'):-len('_energy')]
            refs.setdefault(el, {})['energy'] = node

    missing = sorted(
        el for el, data in refs.items()
        if 'structure' not in data or 'energy' not in data
    )
    if missing:
        raise ValueError(
            f"Missing reference structure/energy pair(s) for: {missing}. "
            f"Expected inputs: ref_<EL>_structure and ref_<EL>_energy."
        )

    # Target composition and reduced stoichiometry
    target_counts = get_atom_counts(target_structure)
    n_fu = get_formula_units(target_counts)
    reduced = get_reduced_stoichiometry(target_counts)  # per formula unit
    n_atoms_total = sum(target_counts.values())
    n_atoms_fu = sum(reduced.values())

    e_target_total = float(target_energy.value)
    e_target_per_fu = e_target_total / n_fu
    e_target_per_atom = e_target_total / n_atoms_total if n_atoms_total else e_target_total

    ref_energies_per_atom: dict[str, float] = {}
    ref_details: dict[str, dict[str, t.Any]] = {}

    for el, data in refs.items():
        ref_struct = data['structure']
        ref_energy = data['energy']

        ref_counts = get_atom_counts(ref_struct)
        if set(ref_counts.keys()) != {el}:
            raise ValueError(
                f"Reference for element '{el}' must contain only '{el}', got {ref_counts}"
            )
        n_ref_atoms = int(ref_counts[el])
        if n_ref_atoms < 1:
            raise ValueError(
                f"Reference for element '{el}' has no atoms?"
            )

        e_ref_total = float(ref_energy.value)
        mu_ref = e_ref_total / n_ref_atoms

        ref_energies_per_atom[el] = mu_ref
        ref_details[el] = {
            'n_atoms': n_ref_atoms,
            'energy_total_eV': e_ref_total,
            'energy_per_atom_eV': mu_ref,
        }

    # Ensure every element in the target reduced stoichiometry has a reference.
    missing_refs = sorted(el for el in reduced.keys() if el not in ref_energies_per_atom)
    if missing_refs:
        raise ValueError(
            f"Missing reference energies for element(s): {missing_refs}. "
            f"Provided references: {sorted(ref_energies_per_atom.keys())}"
        )

    sum_refs = 0.0
    for el, n_el in reduced.items():
        sum_refs += float(n_el) * ref_energies_per_atom[el]

    delta_h_fu = e_target_per_fu - sum_refs
    delta_h_atom = delta_h_fu / n_atoms_fu if n_atoms_fu else delta_h_fu

    return orm.Dict(
        dict={
            'target': {
                'atom_counts': target_counts,
                'reduced_stoichiometry': reduced,
                'n_formula_units': int(n_fu),
                'energy_total_eV': e_target_total,
                'energy_per_fu_eV': float(e_target_per_fu),
                'energy_per_atom_eV': float(e_target_per_atom),
            },
            'references': ref_details,
            'delta_h_formation_eV_per_fu': float(delta_h_fu),
            'delta_h_formation_eV_per_atom': float(delta_h_atom),
        }
    )


def validate_stage(stage: dict, stage_names: set) -> None:
    """Validate a formation_enthalpy stage configuration."""
    name = stage['name']

    # Target: use standard structure_from/energy_from fields for port validation.
    for key in ('structure_from', 'energy_from'):
        if key not in stage:
            raise ValueError(
                f"Stage '{name}': formation_enthalpy stages require '{key}'"
            )
        ref = stage[key]
        if ref == 'input':
            raise ValueError(
                f"Stage '{name}': {key}='input' is not supported for formation_enthalpy"
            )
        if ref not in stage_names:
            raise ValueError(
                f"Stage '{name}': {key}='{ref}' must reference a previous stage name"
            )

    references = stage.get('references')
    if not isinstance(references, dict) or not references:
        raise ValueError(
            f"Stage '{name}': formation_enthalpy stages require non-empty 'references' dict "
            f"(e.g. {{'Sn': 'sn_relax', 'O': 'o2_relax'}})"
        )

    for el, ref_stage in references.items():
        if not isinstance(el, str) or not el:
            raise ValueError(
                f"Stage '{name}': reference element keys must be non-empty strings, got {el!r}"
            )
        if not isinstance(ref_stage, str) or not ref_stage:
            raise ValueError(
                f"Stage '{name}': reference stage for '{el}' must be a stage name string"
            )
        if ref_stage == 'input':
            raise ValueError(
                f"Stage '{name}': reference stage for '{el}' cannot be 'input'"
            )
        if ref_stage not in stage_names:
            raise ValueError(
                f"Stage '{name}': references['{el}']='{ref_stage}' must reference a previous stage name"
            )


def create_stage_tasks(wg, stage, stage_name, context):
    """Create formation_enthalpy stage tasks in the WorkGraph."""
    input_structure = context['input_structure']

    structure_from = stage['structure_from']
    energy_from = stage['energy_from']

    if structure_from == 'input':
        target_structure = input_structure
    else:
        from . import resolve_structure_from
        target_structure = resolve_structure_from(structure_from, context)

    from . import resolve_energy_from
    target_energy = resolve_energy_from(energy_from, context)

    kwargs = {
        'target_structure': target_structure,
        'target_energy': target_energy,
    }

    references: dict[str, str] = stage['references']
    for el, ref_stage in references.items():
        if ref_stage == 'input':
            raise ValueError(
                f"Stage '{stage_name}': references['{el}']='input' is not supported"
            )
        kwargs[f'ref_{el}_structure'] = resolve_structure_from(ref_stage, context)
        kwargs[f'ref_{el}_energy'] = resolve_energy_from(ref_stage, context)

    task_node = wg.add_task(
        compute_formation_enthalpy,
        name=f'formation_enthalpy_{stage_name}',
        **kwargs,
    )

    return {'formation_enthalpy': task_node}


def expose_stage_outputs(wg, stage_name, stage_tasks_result, namespace_map=None):
    """Expose formation_enthalpy outputs on the WorkGraph."""
    task_node = stage_tasks_result['formation_enthalpy']

    if namespace_map is not None:
        ns = namespace_map['main']
        setattr(
            wg.outputs,
            f'{ns}.formation_enthalpy.formation_enthalpy',
            task_node.outputs.result,
        )
    else:
        setattr(wg.outputs, f'{stage_name}_formation_enthalpy', task_node.outputs.result)


def get_stage_results(wg_node, wg_pk: int, stage_name: str, namespace_map: dict = None) -> dict:
    """Extract results from a formation_enthalpy stage."""
    result = {
        'formation_enthalpy': None,
        'pk': wg_pk,
        'stage': stage_name,
        'type': 'formation_enthalpy',
    }

    if hasattr(wg_node, 'outputs'):
        outputs = wg_node.outputs
        if namespace_map is not None:
            ns = namespace_map['main']
            stage_ns = getattr(outputs, ns, None)
            brick_ns = getattr(stage_ns, 'formation_enthalpy', None) if stage_ns is not None else None
            if brick_ns is not None and hasattr(brick_ns, 'formation_enthalpy'):
                node = brick_ns.formation_enthalpy
                if hasattr(node, 'get_dict'):
                    result['formation_enthalpy'] = node.get_dict()
        else:
            attr = f'{stage_name}_formation_enthalpy'
            if hasattr(outputs, attr):
                node = getattr(outputs, attr)
                if hasattr(node, 'get_dict'):
                    result['formation_enthalpy'] = node.get_dict()

    if result['formation_enthalpy'] is None:
        _extract_from_links(wg_node, stage_name, result)

    return result


def _extract_from_links(wg_node, stage_name: str, result: dict) -> None:
    """Fallback: traverse WorkGraph links to find the formation enthalpy Dict."""
    if not hasattr(wg_node, 'base'):
        return

    task_name = f'formation_enthalpy_{stage_name}'
    called_calc = wg_node.base.links.get_outgoing(link_type=LinkType.CALL_CALC)
    for link in called_calc.all():
        if task_name not in link.link_label:
            continue
        child = link.node
        created = child.base.links.get_outgoing(link_type=LinkType.CREATE)
        for out_link in created.all():
            if out_link.link_label == 'result' and hasattr(out_link.node, 'get_dict'):
                result['formation_enthalpy'] = out_link.node.get_dict()
                return


def print_stage_results(index: int, stage_name: str, stage_result: dict) -> None:
    """Print formatted results for a formation_enthalpy stage."""
    from ..console import console, print_stage_header

    print_stage_header(index, stage_name, brick_type="formation_enthalpy")

    data = stage_result.get('formation_enthalpy') or {}
    dh_fu = data.get('delta_h_formation_eV_per_fu')
    dh_atom = data.get('delta_h_formation_eV_per_atom')
    reduced = (data.get('target') or {}).get('reduced_stoichiometry')

    if reduced:
        console.print(f"      [bold]Reduced formula:[/bold] {reduced}")
    if dh_fu is not None:
        console.print(f"      [bold]ΔHf:[/bold] {dh_fu:.6f} eV / formula unit")
    if dh_atom is not None:
        console.print(f"      [bold]ΔHf:[/bold] {dh_atom:.6f} eV / atom")

