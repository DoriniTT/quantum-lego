"""Configuration and constants for convergence testing.

This module provides default settings and validation for convergence workflows.
"""

from __future__ import annotations


# Default convergence settings
DEFAULT_CONV_SETTINGS = {
    'cutoff_start': 200,
    'cutoff_stop': 800,
    'cutoff_step': 50,
    'kspacing_start': 0.08,
    'kspacing_stop': 0.02,
    'kspacing_step': 0.01,
    'cutoff_kconv': 520,
    'kspacing_cutconv': 0.03,
}


__all__ = [
    'DEFAULT_CONV_SETTINGS',
]
