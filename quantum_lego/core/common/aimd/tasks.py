"""WorkGraph tasks for AIMD module."""

import typing as t
from aiida import orm
from aiida_workgraph import task, dynamic, namespace


@task.calcfunction
def create_supercell(structure: orm.StructureData, spec: orm.List) -> orm.StructureData:
    """
    Create supercell using pymatgen (as calcfunction).

    Args:
        structure: Input structure
        spec: List [nx, ny, nz] supercell dimensions

    Returns:
        StructureData: Supercell structure
    """
    from pymatgen.io.ase import AseAtomsAdaptor

    # Convert StructureData -> ASE -> pymatgen
    ase_atoms = structure.get_ase()
    adaptor = AseAtomsAdaptor()
    pmg_struct = adaptor.get_structure(ase_atoms)

    # Create supercell
    spec_list = spec.get_list()
    pmg_supercell = pmg_struct * spec_list

    # Convert back: pymatgen -> ASE -> StructureData
    ase_supercell = adaptor.get_atoms(pmg_supercell)
    supercell_data = orm.StructureData(ase=ase_supercell)

    return supercell_data


@task.graph
def create_supercells_scatter(
    slabs: dynamic(orm.StructureData), spec: orm.List
) -> t.Annotated[dict, namespace(result=dynamic(orm.StructureData))]:
    """
    Create supercells for a dictionary of slabs (Graph Builder).

    Args:
        slabs: Dictionary of {label: StructureData}
        spec: List [nx, ny, nz] supercell dimensions

    Returns:
        Dictionary of {label: SupercellStructureData} wrapped in 'result' namespace.
    """
    outputs = {}
    for label, structure in slabs.items():
        # create_supercell is a task
        sc_task = create_supercell(structure=structure, spec=spec)
        # Use .result to access the output of the task
        outputs[label] = sc_task.result

    # Return wrapped in 'result' to match the namespace annotation
    return {"result": outputs}
