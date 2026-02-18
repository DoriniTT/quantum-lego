"""Utilities for parsing vibrational analysis (IBRION=5) OUTCAR output.

The main entry point is the ``parse_vibrational_modes`` AiiDA calcfunction,
which reads a retrieved FolderData, parses all imaginary modes, and returns
a summary ``orm.Dict`` that is exposed as a WorkGraph output port.

Diagnostic guidance for transition-state verification
------------------------------------------------------
After an IDM dimer run, perform a frequency calculation (IBRION=5, NWRITE=3)
on the relaxed structure to confirm it is a first-order saddle point:

  - Exactly **one** large imaginary mode (typically tens–hundreds of cm⁻¹)
    corresponding to the reaction coordinate.  This is the TS mode.
  - Possibly a few very small imaginary modes (< 5 cm⁻¹) that are
    translational artefacts.  These arise because the unit cell is not
    periodic along all directions for a molecule in a box.
    They can be recognised by large "dx" / near-zero "dy", "dz" values.
    Ignore them when computing thermodynamic properties.
  - All other modes should be real (positive frequencies).

If more than one large imaginary mode is present the structure is NOT a
first-order saddle point (it is a higher-order saddle point).
"""

from __future__ import annotations

import re

from aiida import orm
from aiida_workgraph import task

_MODE_HEADER_RE = re.compile(
    r'^\s*(\d+)\s+(f(?:/i)?)\s*=\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*THz'
    r'.*?'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*cm-1',
    re.IGNORECASE,
)
_EIGENVEC_HEADER_RE = re.compile(r'^\s*X\s+Y\s+Z\s+dx\s+dy\s+dz\s*$', re.IGNORECASE)

#: Threshold below which an imaginary mode is considered a translational artefact.
TRANSLATIONAL_THRESHOLD_CM1 = 5.0


def _parse_imaginary_modes_from_outcar(outcar_content: str) -> list[dict]:
    """Return a list of all imaginary mode dicts from the OUTCAR.

    Each dict contains:
        index          int   — mode index as printed by VASP (1-based)
        freq_thz       float
        freq_cm1       float — magnitude (always positive)
        is_translational  bool — True if freq_cm1 < TRANSLATIONAL_THRESHOLD_CM1
        is_ts_mode     bool  — True if imaginary AND not translational
    """
    # Use the last occurrence of the eigenvector section (after all relaxation steps)
    marker = 'Eigenvectors after division by SQRT(mass)'
    lower = outcar_content.lower()
    start = lower.rfind(marker.lower())
    section = outcar_content[start:] if start != -1 else outcar_content

    modes: list[dict] = []
    lines = section.splitlines()
    i = 0
    while i < len(lines):
        m = _MODE_HEADER_RE.match(lines[i])
        if m:
            mode_index = int(m.group(1))
            mode_type = m.group(2).lower()   # 'f/i' → imaginary, 'f' → real
            freq_thz = float(m.group(3))
            freq_cm1 = float(m.group(4))
            is_imaginary = 'i' in mode_type

            if is_imaginary:
                is_trans = freq_cm1 < TRANSLATIONAL_THRESHOLD_CM1
                modes.append({
                    'index': mode_index,
                    'freq_thz': freq_thz,
                    'freq_cm1': freq_cm1,
                    'is_translational': is_trans,
                    'is_ts_mode': not is_trans,
                })
        i += 1

    return modes


@task.calcfunction
def parse_vibrational_modes(retrieved: orm.FolderData) -> orm.Dict:
    """Parse imaginary modes from a vibrational analysis (IBRION=5) OUTCAR.

    Returns an ``orm.Dict`` with keys:

        imaginary_modes        list[dict]  — all imaginary modes (see below)
        n_large_imaginary      int         — imaginary modes above threshold
        n_translational_artifacts  int     — imaginary modes below threshold
        ts_frequency_cm1       float|None  — frequency of the primary TS mode
        saddle_point_status    str         — "confirmed" | "uncertain" | "failed"
        assessment             str         — human-readable one-liner

    Each entry in ``imaginary_modes``:
        index             int
        freq_thz          float
        freq_cm1          float
        is_translational  bool
        is_ts_mode        bool

    Status logic:
        confirmed  → exactly 1 large imaginary mode (first-order saddle point)
        uncertain  → 0 large imaginary modes (all real or only artefacts)
        failed     → >1 large imaginary modes (higher-order saddle point)
    """
    try:
        content = retrieved.get_object_content('OUTCAR')
    except Exception:
        return orm.Dict(dict={
            'imaginary_modes': [],
            'n_large_imaginary': 0,
            'n_translational_artifacts': 0,
            'ts_frequency_cm1': None,
            'saddle_point_status': 'unknown',
            'assessment': 'OUTCAR not available',
        })

    text = content.decode(errors='replace') if isinstance(content, bytes) else str(content)
    modes = _parse_imaginary_modes_from_outcar(text)

    ts_modes = [m for m in modes if m['is_ts_mode']]
    trans_modes = [m for m in modes if m['is_translational']]
    n_large = len(ts_modes)
    n_trans = len(trans_modes)

    # Primary TS mode = largest imaginary (highest freq_cm1 among large imaginary)
    ts_freq = max((m['freq_cm1'] for m in ts_modes), default=None)

    if n_large == 1:
        status = 'confirmed'
        assessment = (
            f'1 large imaginary mode ({ts_freq:.2f} cm\u207b\u00b9) '
            f'+ {n_trans} translational artefact(s) \u2014 first-order saddle point \u2713'
        )
    elif n_large == 0:
        status = 'uncertain'
        assessment = (
            f'No large imaginary mode found ({n_trans} translational artefact(s)) '
            f'\u2014 structure may not be a TS'
        )
    else:
        status = 'failed'
        freqs = ', '.join(f'{m["freq_cm1"]:.2f}' for m in ts_modes)
        assessment = (
            f'{n_large} large imaginary modes ({freqs} cm\u207b\u00b9) '
            f'\u2014 higher-order saddle point, not a true TS \u2717'
        )

    return orm.Dict(dict={
        'imaginary_modes': modes,
        'n_large_imaginary': n_large,
        'n_translational_artifacts': n_trans,
        'ts_frequency_cm1': ts_freq,
        'saddle_point_status': status,
        'assessment': assessment,
    })
