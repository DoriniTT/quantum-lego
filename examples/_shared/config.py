"""Shared configuration for quantum-lego examples."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from aiida import load_profile

DEFAULT_PROFILE = os.getenv('QUANTUM_LEGO_PROFILE')
DEFAULT_VASP_CODE = os.getenv('QUANTUM_LEGO_VASP_CODE', 'VASP-6.5.1@localwork')

LOCALWORK_OPTIONS: dict[str, Any] = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 8,
    },
}

OBELIX_OPTIONS: dict[str, Any] = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 4,
    },
    'custom_scheduler_commands': (
        '#PBS -l cput=90000:00:00\n'
        '#PBS -l nodes=1:ppn=88:skylake\n'
        '#PBS -j oe'
    ),
}

SNO2_POTCAR: dict[str, Any] = {
    'family': 'PBE',
    'mapping': {'Sn': 'Sn_d', 'O': 'O'},
}

STRUCTURES_DIR = Path(__file__).resolve().parent.parent / 'structures'


def setup_profile(profile_name: str | None = None) -> None:
    """Load the configured AiiDA profile for examples.

    Args:
        profile_name: Optional profile name override. If not provided, uses
            ``QUANTUM_LEGO_PROFILE`` or the default AiiDA profile.
    """
    selected = profile_name or DEFAULT_PROFILE
    if selected:
        load_profile(selected)
    else:
        load_profile()
