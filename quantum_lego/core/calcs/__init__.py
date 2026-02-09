"""Custom CalcJob and WorkChain implementations for the lego module."""

from .aimd_vasp import AimdVaspCalculation, AimdVaspWorkChain

__all__ = ['AimdVaspCalculation', 'AimdVaspWorkChain']
