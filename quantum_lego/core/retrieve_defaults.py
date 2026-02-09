"""Default file retrieval settings for lego VASP workflows."""

import typing as t

DEFAULT_VASP_RETRIEVE = [
    'INCAR',
    'KPOINTS',
    'POTCAR',
    'POSCAR',
    'CONTCAR',
    'OUTCAR',
    'vasprun.xml',
    'OSZICAR',
]


def merge_retrieve_lists(*lists: t.Optional[t.Iterable[str]]) -> t.List[str]:
    """Merge retrieve lists while preserving order and removing duplicates."""
    merged: t.List[str] = []
    seen: t.Set[str] = set()

    for items in lists:
        if not items:
            continue
        for item in items:
            if item is None:
                continue
            if item not in seen:
                merged.append(item)
                seen.add(item)

    return merged


def build_vasp_retrieve(
    retrieve: t.Optional[t.Iterable[str]],
    extra: t.Optional[t.Iterable[str]] = None,
) -> t.List[str]:
    """Return the effective retrieve list for VASP workflows."""
    return merge_retrieve_lists(DEFAULT_VASP_RETRIEVE, retrieve, extra)
