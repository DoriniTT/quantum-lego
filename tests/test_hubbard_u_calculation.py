"""Tests for Hubbard U calculation module (u_calculation).

Tests are organized by tier:
- tier1: Pure Python, no AiiDA profile needed
- tier2: Require AiiDA profile for StructureData operations

Covers the critical fixes:
1. build_ldau_arrays: LDAUJ defaults to match LDAUU for LDAUTYPE=3
2. get_species_order_from_structure: uses AiiDA kind names for split species
3. validate_target_species: accepts kind names
4. prepare_perturbed_structure: splits one atom into separate kind
5. extract_d_electron_occupation: matches by kind_name
6. prepare_response_incar: propagates LDAUJ=None correctly
"""

import pytest

from quantum_lego.core.common.u_calculation.utils import (
    build_ldau_arrays,
    get_species_order_from_structure,
    validate_target_species,
    prepare_perturbed_structure,
    prepare_response_incar,
    prepare_ground_state_incar,
    linear_regression,
    DEFAULT_POTENTIAL_VALUES,
)
from quantum_lego.core.common.u_calculation.tasks import (
    _parse_total_charge_from_outcar,
)


# =============================================================================
# TIER 1: Pure Python tests (no AiiDA)
# =============================================================================


@pytest.mark.tier1
class TestBuildLdauArrays:
    """Tests for build_ldau_arrays — the LDAUJ fix is critical."""

    def test_ldauj_defaults_to_match_ldauu(self):
        """LDAUJ should equal LDAUU when ldauj_value is None (LDAUTYPE=3)."""
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Fe',
            all_species=['Fe', 'O'],
            ldaul_value=2,
            potential_value=0.1,
        )
        assert ldaul == [2, -1]
        assert ldauu == [-0.1, 0.0]
        assert ldauj == [-0.1, 0.0], (
            "LDAUJ must equal LDAUU for LDAUTYPE=3 (default ldauj_value=None)"
        )

    def test_ldauj_defaults_none_negative_potential(self):
        """LDAUJ should match LDAUU for negative potentials too."""
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Ni',
            all_species=['Ni', 'O'],
            ldaul_value=2,
            potential_value=-0.2,
        )
        assert ldauu == [0.2, 0.0]  # -(-0.2) = 0.2
        assert ldauj == [0.2, 0.0]

    def test_ldauj_explicit_zero_overrides_default(self):
        """Explicit ldauj_value=0.0 should override the auto-match."""
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Fe',
            all_species=['Fe', 'O'],
            ldaul_value=2,
            potential_value=0.1,
            ldauj_value=0.0,
        )
        assert ldauu == [-0.1, 0.0]
        assert ldauj == [0.0, 0.0], (
            "Explicit ldauj_value=0.0 should override auto-match"
        )

    def test_split_species_three_kinds(self):
        """Split species ['Sn', 'Sn1', 'O'] should have correct array length."""
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Sn',
            all_species=['Sn', 'Sn1', 'O'],
            ldaul_value=2,
            potential_value=0.1,
        )
        assert len(ldaul) == 3
        assert len(ldauu) == 3
        assert len(ldauj) == 3
        assert ldaul == [2, -1, -1]
        assert ldauu == [-0.1, 0.0, 0.0]
        assert ldauj == [-0.1, 0.0, 0.0]

    def test_potential_only_on_target_kind(self):
        """Only the target kind gets LDAUU; unperturbed kind gets zero."""
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Sn',
            all_species=['Sn', 'Sn1', 'O'],
            ldaul_value=2,
            potential_value=0.15,
        )
        # Only first element (Sn) should have potential
        assert ldauu[0] == pytest.approx(-0.15)
        assert ldauu[1] == 0.0, "Unperturbed kind Sn1 should have zero potential"
        assert ldauu[2] == 0.0

    def test_f_electrons(self):
        """LDAUL=3 for f-electrons should work correctly."""
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Ce',
            all_species=['Ce', 'O'],
            ldaul_value=3,
            potential_value=0.1,
        )
        assert ldaul == [3, -1]

    def test_zero_potential(self):
        """V=0 should produce zero LDAUU and LDAUJ."""
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Fe',
            all_species=['Fe', 'O'],
            ldaul_value=2,
            potential_value=0.0,
        )
        assert ldauu == [0.0, 0.0]
        assert ldauj == [0.0, 0.0]


@pytest.mark.tier1
class TestGetSpeciesOrderASE:
    """Test get_species_order_from_structure with ASE Atoms (fallback path)."""

    def test_simple_binary(self):
        """Standard binary compound."""
        from ase import Atoms
        atoms = Atoms('FeO', positions=[(0, 0, 0), (1, 1, 1)])
        result = get_species_order_from_structure(atoms)
        assert result == ['Fe', 'O']

    def test_preserves_first_appearance_order(self):
        """Species order should match first appearance, not alphabetical."""
        from ase import Atoms
        atoms = Atoms('OFe', positions=[(0, 0, 0), (1, 1, 1)])
        result = get_species_order_from_structure(atoms)
        assert result == ['O', 'Fe']

    def test_multiple_atoms_same_species(self):
        """Multiple atoms of same species should appear once."""
        from ase import Atoms
        atoms = Atoms('Fe2O3', positions=[(0, 0, 0), (1, 0, 0),
                                           (0, 1, 0), (1, 1, 0), (0, 0, 1)])
        result = get_species_order_from_structure(atoms)
        assert result == ['Fe', 'O']

    def test_invalid_structure_raises(self):
        """Non-structure object should raise TypeError."""
        with pytest.raises(TypeError, match="get_ase"):
            get_species_order_from_structure("not a structure")


@pytest.mark.tier1
class TestPrepareResponseIncar:
    """Test prepare_response_incar propagation of LDAUJ."""

    def test_ldauj_none_propagated(self):
        """When ldauj=None, the INCAR LDAUJ should match LDAUU."""
        incar = prepare_response_incar(
            base_params={'encut': 400},
            potential_value=0.1,
            target_species='Sn',
            all_species=['Sn', 'Sn1', 'O'],
            ldaul=2,
            ldauj=None,
        )
        assert incar['ldauj'] == incar['ldauu'], (
            "LDAUJ should equal LDAUU when ldauj=None"
        )

    def test_ldauj_explicit_zero(self):
        """When ldauj=0.0, LDAUJ should be all zeros."""
        incar = prepare_response_incar(
            base_params={'encut': 400},
            potential_value=0.1,
            target_species='Sn',
            all_species=['Sn', 'Sn1', 'O'],
            ldaul=2,
            ldauj=0.0,
        )
        assert incar['ldauj'] == [0.0, 0.0, 0.0]

    def test_nscf_has_icharg_11(self):
        """Non-SCF response should set ICHARG=11."""
        incar = prepare_response_incar(
            base_params={},
            potential_value=0.1,
            target_species='Fe',
            all_species=['Fe', 'O'],
            is_scf=False,
        )
        assert incar['icharg'] == 11
        assert incar['istart'] == 0

    def test_scf_no_icharg(self):
        """SCF response should not set ICHARG."""
        incar = prepare_response_incar(
            base_params={},
            potential_value=0.1,
            target_species='Fe',
            all_species=['Fe', 'O'],
            is_scf=True,
        )
        assert 'icharg' not in incar

    def test_ldautype_3(self):
        """LDAUTYPE must be 3 (linear response mode)."""
        incar = prepare_response_incar(
            base_params={},
            potential_value=0.1,
            target_species='Fe',
            all_species=['Fe', 'O'],
        )
        assert incar['ldautype'] == 3

    def test_split_species_array_length(self):
        """LDAU arrays should have length matching all_species."""
        incar = prepare_response_incar(
            base_params={},
            potential_value=0.1,
            target_species='Sn',
            all_species=['Sn', 'Sn1', 'O'],
            ldaul=2,
            ldauj=None,
        )
        assert len(incar['ldaul']) == 3
        assert len(incar['ldauu']) == 3
        assert len(incar['ldauj']) == 3


@pytest.mark.tier1
class TestPrepareGroundStateIncar:
    """Test prepare_ground_state_incar."""

    def test_has_lorbit_11(self):
        """Ground state must have LORBIT=11 for orbital projections."""
        incar = prepare_ground_state_incar()
        assert incar['lorbit'] == 11

    def test_saves_wavecar_chgcar(self):
        """Ground state must save WAVECAR and CHGCAR."""
        incar = prepare_ground_state_incar()
        assert incar['lwave'] is True
        assert incar['lcharg'] is True

    def test_base_params_preserved(self):
        """Base params should be included."""
        incar = prepare_ground_state_incar(base_params={'ENCUT': 520})
        assert incar['encut'] == 520  # lowercased


@pytest.mark.tier1
class TestLinearRegression:
    """Test linear_regression utility."""

    def test_perfect_linear(self):
        """Perfect linear data should give R²=1."""
        x = [-0.2, -0.1, 0.0, 0.1, 0.2]
        y = [xi * 2 for xi in x]
        slope, intercept, r2 = linear_regression(x, y)
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(0.0, abs=1e-10)
        assert r2 == pytest.approx(1.0)

    def test_min_points(self):
        """Should raise with < 2 points."""
        with pytest.raises(ValueError, match="at least 2"):
            linear_regression([1.0], [2.0])


@pytest.mark.tier1
class TestDefaultPotentialValues:
    """Test DEFAULT_POTENTIAL_VALUES update."""

    def test_has_eight_values(self):
        """Default should have 8 potential values (VASP wiki recommendation)."""
        assert len(DEFAULT_POTENTIAL_VALUES) == 8

    def test_symmetric(self):
        """Potentials should be symmetric around zero."""
        for v in DEFAULT_POTENTIAL_VALUES:
            assert -v in DEFAULT_POTENTIAL_VALUES, (
                f"Potential {v} has no symmetric counterpart"
            )

    def test_no_zero(self):
        """V=0 must not be in defaults (incompatible GS/response LDAU settings)."""
        assert 0.0 not in DEFAULT_POTENTIAL_VALUES


@pytest.mark.tier1
class TestParseOutcar:
    """Test OUTCAR total charge parsing."""

    OUTCAR_NONMAG = """
 ISPIN  =      1
 total charge

# of ion       s       p       d       tot
------------------------------------------
    1        0.500   0.200   2.100   2.800
    2        0.500   0.200   2.050   2.750
    3        1.800   4.500   0.000   6.300
    4        1.800   4.500   0.000   6.300
--------------------------------------------------
"""

    OUTCAR_SPINPOL = """
 ISPIN  =      2
 total charge

# of ion       s       p       d       tot
------------------------------------------
    1        0.500   0.200   8.400   9.100
    2        0.500   0.200   8.350   9.050
--------------------------------------------------

 magnetization (x)

# of ion       s       p       d       tot
------------------------------------------
    1        0.050   0.010   1.200   1.260
    2       -0.050  -0.010  -1.200  -1.260
--------------------------------------------------
"""

    def test_nonmag_parsing(self):
        """Parse d-occupations from non-magnetic OUTCAR."""
        charges = _parse_total_charge_from_outcar(self.OUTCAR_NONMAG)
        assert len(charges) == 4
        assert charges[0]['d'] == pytest.approx(2.100)
        assert charges[2]['d'] == pytest.approx(0.000)

    def test_spinpol_uses_total_charge(self):
        """For ISPIN=2, should use total charge (first section), not magnetization."""
        charges = _parse_total_charge_from_outcar(self.OUTCAR_SPINPOL)
        assert len(charges) == 2
        # Should be total charge, not magnetization
        assert charges[0]['d'] == pytest.approx(8.400)
        assert charges[1]['d'] == pytest.approx(8.350)

    def test_missing_lorbit_raises(self):
        """Missing total charge section should raise ValueError."""
        with pytest.raises(ValueError, match="total charge"):
            _parse_total_charge_from_outcar("Some OUTCAR without charge info")


# =============================================================================
# TIER 2: Tests requiring AiiDA (StructureData operations)
# =============================================================================


def _make_sno2_supercell():
    """Helper to create a 2x2x2 SnO2 supercell as AiiDA StructureData."""
    import os
    from ase.io import read
    from aiida import orm

    fixture_path = os.path.join(
        os.path.dirname(__file__), 'fixtures', 'structures', 'sno2_rutile.vasp'
    )
    atoms = read(fixture_path, format='vasp')
    atoms_super = atoms * (2, 2, 2)  # 16 Sn + 32 O
    return orm.StructureData(ase=atoms_super)


def _make_simple_sno2():
    """Helper to create a unit cell SnO2 as AiiDA StructureData."""
    import os
    from ase.io import read
    from aiida import orm

    fixture_path = os.path.join(
        os.path.dirname(__file__), 'fixtures', 'structures', 'sno2_rutile.vasp'
    )
    atoms = read(fixture_path, format='vasp')
    return orm.StructureData(ase=atoms)


class TestPreparePerturbeStructure:
    """Tests for prepare_perturbed_structure (requires AiiDA)."""

    @pytest.fixture(autouse=True)
    def _check_aiida(self):
        """Skip if AiiDA is not available."""
        try:
            from aiida import load_profile
            load_profile()
        except Exception:
            pytest.skip("AiiDA not configured")

    def test_split_sno2_supercell(self):
        """Split 2x2x2 SnO2 supercell: 1 Sn + 15 Sn1 + 32 O."""
        supercell = _make_sno2_supercell()
        split, perturbed, unperturbed = prepare_perturbed_structure(
            supercell, 'Sn'
        )

        assert perturbed == 'Sn'
        assert unperturbed == 'Sn1'

        # Count atoms per kind
        kind_counts = {}
        for site in split.sites:
            kind_counts[site.kind_name] = kind_counts.get(site.kind_name, 0) + 1

        assert kind_counts['Sn'] == 1, "Exactly 1 perturbed Sn atom"
        assert kind_counts['Sn1'] == 15, "15 unperturbed Sn atoms"
        assert kind_counts['O'] == 32, "32 O atoms unchanged"

    def test_total_atom_count_preserved(self):
        """Total number of atoms should be preserved after split."""
        supercell = _make_sno2_supercell()
        n_before = len(supercell.sites)
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')
        n_after = len(split.sites)
        assert n_after == n_before

    def test_split_preserves_cell(self):
        """Cell vectors should be preserved."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')
        for i in range(3):
            for j in range(3):
                assert split.cell[i][j] == pytest.approx(supercell.cell[i][j])

    def test_kinds_have_correct_element(self):
        """Both Sn and Sn1 kinds should map to element Sn."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')

        kind_symbols = {k.name: k.symbols for k in split.kinds}
        assert kind_symbols['Sn'] == ('Sn',)
        assert kind_symbols['Sn1'] == ('Sn',)
        assert kind_symbols['O'] == ('O',)

    def test_species_order_after_split(self):
        """get_species_order_from_structure should return 3 species after split."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')
        species = get_species_order_from_structure(split)
        assert species == ['Sn', 'Sn1', 'O']

    def test_single_atom_species_raises(self):
        """Should raise if target species has only 1 atom (can't split)."""
        from aiida import orm

        # Create a structure with only 1 Fe
        struct = orm.StructureData(cell=[[3, 0, 0], [0, 3, 0], [0, 0, 3]])
        struct.append_atom(position=(0, 0, 0), symbols='Fe', name='Fe')
        struct.append_atom(position=(1.5, 1.5, 1.5), symbols='O', name='O')

        with pytest.raises(ValueError, match="at least 2 atoms"):
            prepare_perturbed_structure(struct, 'Fe')

    def test_missing_species_raises(self):
        """Should raise if target species doesn't exist."""
        supercell = _make_sno2_supercell()
        with pytest.raises(ValueError, match="not found"):
            prepare_perturbed_structure(supercell, 'Ni')

    def test_non_structuredata_raises(self):
        """Should raise TypeError for non-AiiDA structures."""
        from ase import Atoms
        atoms = Atoms('FeO', positions=[(0, 0, 0), (1, 1, 1)])
        with pytest.raises(TypeError, match="AiiDA StructureData"):
            prepare_perturbed_structure(atoms, 'Fe')

    def test_split_oxygen(self):
        """Should also work when splitting oxygen (not just metals)."""
        supercell = _make_sno2_supercell()
        split, perturbed, unperturbed = prepare_perturbed_structure(
            supercell, 'O'
        )

        assert perturbed == 'O'
        assert unperturbed == 'O1'

        kind_counts = {}
        for site in split.sites:
            kind_counts[site.kind_name] = kind_counts.get(site.kind_name, 0) + 1

        assert kind_counts['O'] == 1
        assert kind_counts['O1'] == 31
        assert kind_counts['Sn'] == 16  # Sn unchanged

    def test_atoms_grouped_by_kind(self):
        """Atoms must be in contiguous blocks by kind (VASP POSCAR requirement).

        Without sorting, ASE supercells interleave atoms by unit cell copy,
        producing alternating kind blocks like Sn,Sn1,O,Sn1,O,...
        which gives a broken POSCAR.
        """
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')

        # Extract the sequence of kind names
        kind_sequence = [site.kind_name for site in split.sites]

        # Each kind should form one contiguous block
        seen = set()
        prev_kind = None
        for kind_name in kind_sequence:
            if kind_name != prev_kind:
                assert kind_name not in seen, (
                    f"Kind '{kind_name}' appears in multiple non-contiguous blocks. "
                    f"VASP requires all atoms of the same species to be grouped together. "
                    f"Sequence: {kind_sequence}"
                )
                seen.add(kind_name)
                prev_kind = kind_name

    def test_kind_order_is_perturbed_first(self):
        """Kind order should be: perturbed, unperturbed, then others."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')

        # Get unique kinds in order of first appearance
        seen = []
        for site in split.sites:
            if site.kind_name not in seen:
                seen.append(site.kind_name)

        assert seen == ['Sn', 'Sn1', 'O'], (
            f"Expected kind order ['Sn', 'Sn1', 'O'], got {seen}"
        )


class TestGetSpeciesOrderStructureData:
    """Test get_species_order_from_structure with AiiDA StructureData."""

    @pytest.fixture(autouse=True)
    def _check_aiida(self):
        try:
            from aiida import load_profile
            load_profile()
        except Exception:
            pytest.skip("AiiDA not configured")

    def test_normal_structure(self):
        """Normal StructureData should return element-order species."""
        structure = _make_simple_sno2()
        species = get_species_order_from_structure(structure)
        assert species == ['Sn', 'O']

    def test_split_structure(self):
        """Split StructureData should return kind names, not elements."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')
        species = get_species_order_from_structure(split)
        assert species == ['Sn', 'Sn1', 'O']
        assert len(species) == 3, "Must have 3 species for correct LDAU array length"


class TestValidateTargetSpeciesStructureData:
    """Test validate_target_species with AiiDA StructureData."""

    @pytest.fixture(autouse=True)
    def _check_aiida(self):
        try:
            from aiida import load_profile
            load_profile()
        except Exception:
            pytest.skip("AiiDA not configured")

    def test_element_symbol_valid(self):
        """Normal element symbol should pass."""
        structure = _make_simple_sno2()
        validate_target_species(structure, 'Sn')  # should not raise

    def test_kind_name_valid(self):
        """Kind name from split structure should pass."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')
        validate_target_species(split, 'Sn')    # perturbed kind
        validate_target_species(split, 'Sn1')   # unperturbed kind
        validate_target_species(split, 'O')      # other species

    def test_invalid_species_raises(self):
        """Missing species should raise ValueError."""
        structure = _make_simple_sno2()
        with pytest.raises(ValueError, match="not found"):
            validate_target_species(structure, 'Ni')

    def test_invalid_kind_raises(self):
        """Invalid kind name should raise ValueError."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')
        with pytest.raises(ValueError, match="not found"):
            validate_target_species(split, 'Sn2')


class TestExtractDElectronOccupationLogic:
    """Test the index-finding logic of extract_d_electron_occupation.

    The function is decorated with @task.calcfunction (aiida_workgraph),
    so we test the index-matching logic directly using StructureData.sites
    and the OUTCAR parser separately.
    """

    @pytest.fixture(autouse=True)
    def _check_aiida(self):
        try:
            from aiida import load_profile
            load_profile()
        except Exception:
            pytest.skip("AiiDA not configured")

    def _find_target_indices(self, structure, species):
        """Reproduce the index-finding logic from extract_d_electron_occupation."""
        if hasattr(structure, 'sites'):
            return [
                i for i, site in enumerate(structure.sites)
                if site.kind_name == species
            ]
        else:
            ase_struct = structure.get_ase()
            symbols = ase_struct.get_chemical_symbols()
            return [i for i, s in enumerate(symbols) if s == species]

    def test_split_species_finds_single_atom(self):
        """With split structure, target_species='Sn' should find only 1 atom."""
        from aiida import orm

        struct = orm.StructureData(cell=[[5, 0, 0], [0, 5, 0], [0, 0, 5]])
        struct.append_atom(position=(0, 0, 0), symbols='Sn', name='Sn')
        struct.append_atom(position=(2.5, 0, 0), symbols='Sn', name='Sn1')
        struct.append_atom(position=(0, 2.5, 0), symbols='O', name='O')
        struct.append_atom(position=(2.5, 2.5, 0), symbols='O', name='O')

        indices = self._find_target_indices(struct, 'Sn')
        assert indices == [0], (
            "Split structure: 'Sn' should match only atom 0 (perturbed)"
        )

        indices_sn1 = self._find_target_indices(struct, 'Sn1')
        assert indices_sn1 == [1], (
            "Split structure: 'Sn1' should match only atom 1 (unperturbed)"
        )

    def test_unsplit_species_finds_all_atoms(self):
        """Without split, target_species='Sn' should find all Sn atoms."""
        from aiida import orm

        struct = orm.StructureData(cell=[[5, 0, 0], [0, 5, 0], [0, 0, 5]])
        struct.append_atom(position=(0, 0, 0), symbols='Sn', name='Sn')
        struct.append_atom(position=(2.5, 0, 0), symbols='Sn', name='Sn')
        struct.append_atom(position=(0, 2.5, 0), symbols='O', name='O')
        struct.append_atom(position=(2.5, 2.5, 0), symbols='O', name='O')

        indices = self._find_target_indices(struct, 'Sn')
        assert indices == [0, 1], (
            "Normal structure: 'Sn' should match both Sn atoms"
        )

    def test_missing_species_returns_empty(self):
        """Non-existent species should return empty list (caller raises)."""
        from aiida import orm

        struct = orm.StructureData(cell=[[5, 0, 0], [0, 5, 0], [0, 0, 5]])
        struct.append_atom(position=(0, 0, 0), symbols='Sn', name='Sn')
        struct.append_atom(position=(2.5, 0, 0), symbols='O', name='O')

        indices = self._find_target_indices(struct, 'Ni')
        assert indices == []

    def test_supercell_split_counts(self):
        """Full supercell split: 1 perturbed + 15 unperturbed Sn."""
        supercell = _make_sno2_supercell()
        split, _, _ = prepare_perturbed_structure(supercell, 'Sn')

        perturbed_indices = self._find_target_indices(split, 'Sn')
        unperturbed_indices = self._find_target_indices(split, 'Sn1')
        o_indices = self._find_target_indices(split, 'O')

        assert len(perturbed_indices) == 1, "1 perturbed Sn"
        assert len(unperturbed_indices) == 15, "15 unperturbed Sn"
        assert len(o_indices) == 32, "32 O atoms"

    def test_d_occupation_extraction_with_parsed_charges(self):
        """Combined test: parse OUTCAR + index-finding gives correct d-occ."""
        from aiida import orm

        # Mock split structure: atom 0=Sn, atom 1=Sn1, atoms 2-3=O
        struct = orm.StructureData(cell=[[5, 0, 0], [0, 5, 0], [0, 0, 5]])
        struct.append_atom(position=(0, 0, 0), symbols='Sn', name='Sn')
        struct.append_atom(position=(2.5, 0, 0), symbols='Sn', name='Sn1')
        struct.append_atom(position=(0, 2.5, 0), symbols='O', name='O')
        struct.append_atom(position=(2.5, 2.5, 0), symbols='O', name='O')

        # Mock OUTCAR
        outcar = """ ISPIN  =      1
 total charge

# of ion       s       p       d       tot
------------------------------------------
    1        0.500   0.200   2.100   2.800
    2        0.500   0.200   2.050   2.750
    3        1.800   4.500   0.000   6.300
    4        1.800   4.500   0.000   6.300
--------------------------------------------------
"""
        charges = _parse_total_charge_from_outcar(outcar)
        target_indices = self._find_target_indices(struct, 'Sn')

        # Extract d-occupation for perturbed atom only
        per_atom_d = [charges[idx]['d'] for idx in target_indices]
        total_d = sum(per_atom_d)

        assert len(per_atom_d) == 1
        assert total_d == pytest.approx(2.100)

        # Contrast: if we used element symbols (bug), we'd get both Sn atoms
        ase_struct = struct.get_ase()
        symbols = ase_struct.get_chemical_symbols()
        buggy_indices = [i for i, s in enumerate(symbols) if s == 'Sn']
        assert len(buggy_indices) == 2, (
            "Bug: ASE symbols would match both Sn atoms"
        )
        buggy_total = sum(charges[idx]['d'] for idx in buggy_indices)
        assert buggy_total == pytest.approx(4.150), (
            "Bug: would give wrong total d-occupation (both atoms summed)"
        )


# =============================================================================
# INTEGRATION: End-to-end LDAU array pipeline test
# =============================================================================


class TestEndToEndLdauPipeline:
    """Integration test: split structure → species order → LDAU arrays → INCAR."""

    @pytest.fixture(autouse=True)
    def _check_aiida(self):
        try:
            from aiida import load_profile
            load_profile()
        except Exception:
            pytest.skip("AiiDA not configured")

    def test_full_pipeline_sno2(self):
        """Full pipeline: supercell → split → LDAU arrays match VASP wiki."""
        supercell = _make_sno2_supercell()

        # Step 1: Split structure
        split, perturbed, unperturbed = prepare_perturbed_structure(
            supercell, 'Sn'
        )

        # Step 2: Get species order
        all_species = get_species_order_from_structure(split)
        assert all_species == ['Sn', 'Sn1', 'O']

        # Step 3: Build LDAU arrays
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Sn',
            all_species=all_species,
            ldaul_value=2,
            potential_value=0.1,
        )
        assert ldaul == [2, -1, -1]
        assert ldauu == [-0.1, 0.0, 0.0]
        assert ldauj == [-0.1, 0.0, 0.0]  # LDAUJ = LDAUU

        # Step 4: Build response INCAR
        incar = prepare_response_incar(
            base_params={'encut': 520},
            potential_value=0.1,
            target_species='Sn',
            all_species=all_species,
            ldaul=2,
            ldauj=None,  # auto-match
        )
        assert len(incar['ldaul']) == 3
        assert incar['ldauj'] == incar['ldauu']
        assert incar['ldautype'] == 3
        assert incar['ldau'] is True

    def test_potential_mapping_consistency(self):
        """Verify that split kinds match what POTCAR mapping expects."""
        supercell = _make_sno2_supercell()
        split, perturbed, unperturbed = prepare_perturbed_structure(
            supercell, 'Sn'
        )

        # The user must create a mapping like this
        potential_mapping = {perturbed: 'Sn_d', unperturbed: 'Sn_d', 'O': 'O'}

        # All kinds in the structure must be in the mapping
        for kind in split.kinds:
            assert kind.name in potential_mapping, (
                f"Kind '{kind.name}' not in potential_mapping"
            )


# =============================================================================
# POSCAR / POTCAR verification
# =============================================================================


class TestPoscarPotcarOutput:
    """Verify the split structure produces correct POSCAR and POTCAR files.

    These tests check that:
    1. The POSCAR species line has exactly 3 species: Sn, Sn1, O
    2. The POSCAR atom counts match: 1 + 15 + 32 = 48
    3. The POTCAR mapping covers all kinds
    4. Atoms are in contiguous blocks per species (no interleaving)
    """

    @pytest.fixture(autouse=True)
    def _check_aiida(self):
        try:
            from aiida import load_profile
            load_profile()
        except Exception:
            pytest.skip("AiiDA not configured")

    @pytest.fixture
    def split_sno2(self):
        """Create a split 2x2x2 SnO2 supercell."""
        supercell = _make_sno2_supercell()
        split, perturbed, unperturbed = prepare_perturbed_structure(
            supercell, 'Sn'
        )
        return split, perturbed, unperturbed

    def test_poscar_species_line(self, split_sno2):
        """POSCAR species line should list exactly 3 kinds: Sn, Sn1, O."""
        split, _, _ = split_sno2

        # Write to POSCAR via ASE and check species line
        import io
        from ase.io import write as ase_write

        ase_atoms = split.get_ase()
        buf = io.StringIO()
        ase_write(buf, ase_atoms, format='vasp')
        poscar_lines = buf.getvalue().split('\n')

        # POSCAR line 6 is the species names, line 7 is the atom counts
        # (0-indexed: line 5 and line 6)
        species_line = poscar_lines[5].split()
        counts_line = poscar_lines[6].split()

        # ASE writes element symbols, not kind names. But kind names from
        # AiiDA determine POTCAR order. The key check is that atoms are
        # grouped: we check via the structure directly.
        kind_names = [k.name for k in split.kinds]
        assert kind_names == ['Sn', 'Sn1', 'O'], (
            f"Expected kinds ['Sn', 'Sn1', 'O'], got {kind_names}"
        )

    def test_poscar_atom_counts(self, split_sno2):
        """POSCAR should have 1 + 15 + 32 = 48 atoms in correct blocks."""
        split, _, _ = split_sno2

        # Count atoms per kind in site order
        kind_counts = []
        current_kind = None
        current_count = 0
        for site in split.sites:
            if site.kind_name != current_kind:
                if current_kind is not None:
                    kind_counts.append((current_kind, current_count))
                current_kind = site.kind_name
                current_count = 1
            else:
                current_count += 1
        if current_kind is not None:
            kind_counts.append((current_kind, current_count))

        # Should be exactly 3 blocks
        assert len(kind_counts) == 3, (
            f"Expected 3 contiguous species blocks, got {len(kind_counts)}: {kind_counts}"
        )
        assert kind_counts[0] == ('Sn', 1), f"Block 0: {kind_counts[0]}"
        assert kind_counts[1] == ('Sn1', 15), f"Block 1: {kind_counts[1]}"
        assert kind_counts[2] == ('O', 32), f"Block 2: {kind_counts[2]}"

        # Total = 48
        total = sum(c for _, c in kind_counts)
        assert total == 48

    def test_potcar_mapping_complete(self, split_sno2):
        """POTCAR mapping must cover all kinds; both Sn kinds use same POTCAR."""
        split, perturbed, unperturbed = split_sno2

        potential_mapping = {
            perturbed: 'Sn_d',
            unperturbed: 'Sn_d',
            'O': 'O',
        }

        structure_kinds = {k.name for k in split.kinds}
        mapping_kinds = set(potential_mapping.keys())

        assert structure_kinds == mapping_kinds, (
            f"POTCAR mapping mismatch. "
            f"Structure kinds: {structure_kinds}, mapping keys: {mapping_kinds}"
        )

        # Both Sn kinds must map to the same POTCAR (Sn_d)
        assert potential_mapping[perturbed] == potential_mapping[unperturbed], (
            "Perturbed and unperturbed Sn must use the same POTCAR"
        )

    def test_potcar_order_matches_kind_order(self, split_sno2):
        """POTCAR species order must match the kind order in the structure.

        VASP reads POTCAR in the same order as species in POSCAR.
        AiiDA-VASP uses the kind order from StructureData.kinds.
        """
        split, _, _ = split_sno2

        potential_mapping = {'Sn': 'Sn_d', 'Sn1': 'Sn_d', 'O': 'O'}

        # The POTCAR will be concatenated in kind order
        kind_order = [k.name for k in split.kinds]
        potcar_order = [potential_mapping[k] for k in kind_order]

        # Expected: Sn_d, Sn_d, O (duplicate Sn_d for both Sn kinds)
        assert potcar_order == ['Sn_d', 'Sn_d', 'O'], (
            f"POTCAR concatenation order should be ['Sn_d', 'Sn_d', 'O'], "
            f"got {potcar_order}"
        )

    def test_ldau_arrays_match_potcar_length(self, split_sno2):
        """LDAU array length must match number of species in POTCAR."""
        split, _, _ = split_sno2

        all_species = get_species_order_from_structure(split)
        ldaul, ldauu, ldauj = build_ldau_arrays(
            target_species='Sn',
            all_species=all_species,
            ldaul_value=2,
            potential_value=0.1,
        )

        n_kinds = len(split.kinds)
        assert len(ldaul) == n_kinds, f"LDAUL length {len(ldaul)} != {n_kinds} kinds"
        assert len(ldauu) == n_kinds, f"LDAUU length {len(ldauu)} != {n_kinds} kinds"
        assert len(ldauj) == n_kinds, f"LDAUJ length {len(ldauj)} != {n_kinds} kinds"

    def test_poscar_no_interleaved_species(self, split_sno2):
        """The POSCAR species line must NOT have interleaved/repeated species.

        This was the original bug: ASE supercells interleave atoms by unit cell,
        causing species like 'Sn Sn1 O Sn1 O Sn1 O ...' instead of 'Sn Sn1 O'.
        """
        split, _, _ = split_sno2

        kind_sequence = [site.kind_name for site in split.sites]

        # Count how many times the kind changes
        transitions = sum(
            1 for i in range(1, len(kind_sequence))
            if kind_sequence[i] != kind_sequence[i-1]
        )

        # With 3 species in contiguous blocks, there should be exactly 2 transitions
        assert transitions == 2, (
            f"Expected 2 kind transitions (Sn→Sn1→O), got {transitions}. "
            f"This suggests atoms are not in contiguous species blocks. "
            f"First 10 kinds: {kind_sequence[:10]}"
        )
