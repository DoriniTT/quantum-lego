"""
Physical Constants and Unit Conversions for PS-TEROS

This module centralizes all physical constants and unit conversion factors
used throughout PS-TEROS. Using named constants improves code readability
and ensures consistency across modules.

References:
    - CODATA 2018 values for fundamental constants
    - NIST reference values for unit conversions
"""

# =============================================================================
# Energy Unit Conversions
# =============================================================================

# eV/Å² to J/m²
# Derivation: 1 eV = 1.602176634e-19 J, 1 Å = 1e-10 m
# 1 eV/Å² = 1.602176634e-19 J / (1e-10 m)² = 1.602176634e-19 / 1e-20 = 16.02176634 J/m²
EV_PER_ANGSTROM2_TO_J_PER_M2 = 16.0217663

# eV to kJ/mol
# Derivation: 1 eV = 1.602176634e-19 J, N_A = 6.02214076e23 mol⁻¹
# 1 eV × N_A = 1.602176634e-19 × 6.02214076e23 = 96485.33212 J/mol = 96.48533212 kJ/mol
EV_TO_KJ_PER_MOL = 96.485

# eV to J
EV_TO_JOULE = 1.602176634e-19

# eV to meV
EV_TO_MEV = 1000.0

# Hartree to eV
HARTREE_TO_EV = 27.211386245988

# Rydberg to eV
RYDBERG_TO_EV = 13.605693122994


# =============================================================================
# Length Unit Conversions
# =============================================================================

# Ångström to meter
ANGSTROM_TO_METER = 1e-10

# Bohr radius to Ångström
BOHR_TO_ANGSTROM = 0.529177210903

# Ångström to Bohr
ANGSTROM_TO_BOHR = 1.0 / BOHR_TO_ANGSTROM


# =============================================================================
# Fundamental Constants
# =============================================================================

# Avogadro constant (mol⁻¹)
AVOGADRO = 6.02214076e23

# Boltzmann constant (eV/K)
BOLTZMANN_EV = 8.617333262e-5

# Boltzmann constant (J/K)
BOLTZMANN_J = 1.380649e-23

# Gas constant (J/(mol·K))
GAS_CONSTANT = 8.314462618

# Planck constant (eV·s)
PLANCK_EV = 4.135667696e-15


# =============================================================================
# Numerical Tolerances
# =============================================================================

# Relative tolerance for stoichiometry comparisons
# Used when comparing atom counts between slabs for cleavage calculations
STOICHIOMETRY_RTOL = 1e-3

# Absolute tolerance for floating point comparisons
FLOAT_ATOL = 1e-10


# =============================================================================
# VASP-Specific Constants
# =============================================================================

# Default k-point spacing (Å⁻¹)
# A good balance between accuracy and computational cost for most systems
DEFAULT_KPOINTS_SPACING = 0.03

# Common ENCUT values (eV)
ENCUT_LOW = 400      # Fast calculations, screening
ENCUT_STANDARD = 520  # Production calculations
ENCUT_HIGH = 600     # High-precision calculations


# =============================================================================
# Temperature Constants
# =============================================================================

# Room temperature (K)
ROOM_TEMPERATURE = 298.15

# Standard state temperature for thermodynamic calculations (K)
STANDARD_TEMPERATURE = 298.15

# Absolute zero (K)
ABSOLUTE_ZERO = 0.0
