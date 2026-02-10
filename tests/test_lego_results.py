"""Unit tests for lego result extraction and print_stage_results() functions.

All tests are tier1 (pure Python, no AiiDA profile needed).
"""

import pytest


# ---------------------------------------------------------------------------
# TestExtractEnergyFromMisc
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestExtractEnergyFromMisc:
    """Tests for quantum_lego.core.results._extract_energy_from_misc()."""

    def _extract(self, misc):
        from quantum_lego.core.results import _extract_energy_from_misc
        return _extract_energy_from_misc(misc)

    def test_energy_extrapolated(self):
        misc = {'total_energies': {'energy_extrapolated': -123.4}}
        assert self._extract(misc) == pytest.approx(-123.4)

    def test_energy_no_entropy_fallback(self):
        misc = {'total_energies': {'energy_no_entropy': -99.0}}
        assert self._extract(misc) == pytest.approx(-99.0)

    def test_energy_key_fallback(self):
        misc = {'total_energies': {'energy': -50.0}}
        assert self._extract(misc) == pytest.approx(-50.0)

    def test_returns_none_no_keys(self):
        misc = {'total_energies': {'foo': 1}}
        assert self._extract(misc) is None

    def test_flat_dict_top_level(self):
        misc = {'energy_extrapolated': -99.9}
        assert self._extract(misc) == pytest.approx(-99.9)

    def test_returns_float_type(self):
        misc = {'total_energies': {'energy_extrapolated': -123.4}}
        result = self._extract(misc)
        assert isinstance(result, float)

    def test_empty_dict_returns_none(self):
        assert self._extract({}) is None

    def test_empty_total_energies(self):
        misc = {'total_energies': {}}
        assert self._extract(misc) is None


# ---------------------------------------------------------------------------
# TestPrintVaspStageResults
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestPrintVaspStageResults:
    """Tests for quantum_lego.core.bricks.vasp.print_stage_results()."""

    def _print(self, index, stage_name, stage_result):
        from quantum_lego.core.bricks.vasp import print_stage_results
        print_stage_results(index, stage_name, stage_result)

    def _base_result(self, **overrides):
        result = {
            'energy': None, 'structure': None, 'misc': None,
            'remote': None, 'files': None, 'pk': 1, 'stage': 'relax', 'type': 'vasp',
        }
        result.update(overrides)
        return result

    def test_prints_energy(self, capsys):
        self._print(1, 'relax', self._base_result(energy=-123.456789))
        out = capsys.readouterr().out
        assert '-123.456789' in out

    def test_prints_none_energy(self, capsys):
        self._print(1, 'relax', self._base_result(energy=None))
        out = capsys.readouterr().out
        # Should not contain "Energy:" line at all when None
        assert 'Energy:' not in out

    def test_prints_index_and_name(self, capsys):
        self._print(1, 'relax', self._base_result())
        out = capsys.readouterr().out
        assert 'Stage 1:' in out
        assert 'relax' in out

    def test_prints_force_from_misc(self, capsys):
        misc = {'run_status': 'finished', 'maximum_force': 0.0123}
        self._print(1, 'relax', self._base_result(misc=misc))
        out = capsys.readouterr().out
        assert '0.0123' in out


# ---------------------------------------------------------------------------
# TestPrintDosStageResults
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestPrintDosStageResults:
    """Tests for quantum_lego.core.bricks.dos.print_stage_results()."""

    def _print(self, index, stage_name, stage_result):
        from quantum_lego.core.bricks.dos import print_stage_results
        print_stage_results(index, stage_name, stage_result)

    def _base_result(self, **overrides):
        result = {
            'energy': None, 'scf_misc': None, 'scf_remote': None,
            'scf_retrieved': None, 'dos_misc': None, 'dos_remote': None,
            'files': None, 'pk': 1, 'stage': 'dos_calc', 'type': 'dos',
        }
        result.update(overrides)
        return result

    def test_prints_dos_label(self, capsys):
        self._print(2, 'dos_calc', self._base_result())
        out = capsys.readouterr().out
        assert '(dos)' in out.lower()

    def test_prints_scf_energy(self, capsys):
        self._print(2, 'dos_calc', self._base_result(energy=-50.123456))
        out = capsys.readouterr().out
        assert '-50.123456' in out

    def test_prints_band_gap(self, capsys):
        dos_misc = {
            'band_properties': {'band_gap': 1.2345, 'is_direct_gap': False},
            'fermi_level': 5.678,
        }
        self._print(2, 'dos_calc', self._base_result(dos_misc=dos_misc))
        out = capsys.readouterr().out
        assert '1.2345' in out
        assert 'indirect' in out


# ---------------------------------------------------------------------------
# TestPrintBatchStageResults
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestPrintBatchStageResults:
    """Tests for quantum_lego.core.bricks.batch.print_stage_results()."""

    def _print(self, index, stage_name, stage_result):
        from quantum_lego.core.bricks.batch import print_stage_results
        print_stage_results(index, stage_name, stage_result)

    def _base_result(self, **overrides):
        result = {
            'calculations': {}, 'pk': 1, 'stage': 'fukui', 'type': 'batch',
        }
        result.update(overrides)
        return result

    def test_prints_batch_label(self, capsys):
        self._print(3, 'fukui', self._base_result())
        out = capsys.readouterr().out
        assert '(batch)' in out.lower()

    def test_prints_per_calc_energies(self, capsys):
        calcs = {
            'neutral': {'energy': -100.0, 'misc': None, 'remote': None, 'files': None},
            'cation': {'energy': -95.5, 'misc': None, 'remote': None, 'files': None},
        }
        self._print(3, 'fukui', self._base_result(calculations=calcs))
        out = capsys.readouterr().out
        assert 'neutral' in out
        assert '-100.000000' in out
        assert 'cation' in out
        assert '-95.500000' in out

    def test_prints_empty_calculations(self, capsys):
        self._print(3, 'fukui', self._base_result(calculations={}))
        out = capsys.readouterr().out
        assert 'No calculation results' in out


# ---------------------------------------------------------------------------
# TestPrintBaderStageResults
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestPrintBaderStageResults:
    """Tests for quantum_lego.core.bricks.bader.print_stage_results()."""

    def _print(self, index, stage_name, stage_result):
        from quantum_lego.core.bricks.bader import print_stage_results
        print_stage_results(index, stage_name, stage_result)

    def _base_result(self, **overrides):
        result = {
            'charges': None, 'dat_files': {}, 'pk': 1,
            'stage': 'bader', 'type': 'bader',
        }
        result.update(overrides)
        return result

    def test_prints_bader_label(self, capsys):
        self._print(4, 'bader', self._base_result())
        out = capsys.readouterr().out
        assert '(bader)' in out.lower()

    def test_prints_atom_count_and_charge(self, capsys):
        charges = {
            'atoms': [
                {'index': 1, 'x': 0, 'y': 0, 'z': 0, 'charge': 6.5, 'min_dist': 1.0, 'volume': 10.0,
                 'element': 'Sn', 'valence': 14.0, 'bader_charge': 7.5},
                {'index': 2, 'x': 1, 'y': 1, 'z': 1, 'charge': 8.0, 'min_dist': 0.9, 'volume': 12.0,
                 'element': 'O', 'valence': 6.0, 'bader_charge': -2.0},
            ],
            'total_charge': 14.5,
            'vacuum_charge': 0.0,
            'vacuum_volume': 0.0,
        }
        self._print(4, 'bader', self._base_result(charges=charges))
        out = capsys.readouterr().out
        assert 'Atoms analyzed: 2' in out
        assert '14.50000' in out

    def test_prints_per_atom_charges(self, capsys):
        charges = {
            'atoms': [
                {'index': 1, 'x': 0, 'y': 0, 'z': 0, 'charge': 6.5, 'min_dist': 1.0, 'volume': 10.0,
                 'element': 'Sn', 'valence': 14.0, 'bader_charge': 7.5},
            ],
            'total_charge': 6.5,
            'vacuum_charge': 0.0,
            'vacuum_volume': 0.0,
        }
        self._print(4, 'bader', self._base_result(charges=charges))
        out = capsys.readouterr().out
        assert 'Sn' in out
        assert 'valence=14.0' in out


# ---------------------------------------------------------------------------
# TestPrintHubbardResponseStageResults
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestPrintHubbardResponseStageResults:
    """Tests for quantum_lego.core.bricks.hubbard_response.print_stage_results()."""

    def _print(self, index, stage_name, stage_result):
        from quantum_lego.core.bricks.hubbard_response import print_stage_results
        print_stage_results(index, stage_name, stage_result)

    def _base_result(self, **overrides):
        result = {
            'responses': None,
            'ground_state_occupation': None,
            'pk': 1,
            'stage': 'response', 'type': 'hubbard_response',
        }
        result.update(overrides)
        return result

    def test_prints_response_label(self, capsys):
        self._print(2, 'response', self._base_result())
        out = capsys.readouterr().out
        assert '(hubbard_response)' in out.lower()

    def test_prints_response_count(self, capsys):
        responses = [
            {'potential': -0.2, 'delta_n_scf': 0.01, 'delta_n_nscf': 0.005},
            {'potential': 0.2, 'delta_n_scf': -0.01, 'delta_n_nscf': -0.005},
        ]
        self._print(2, 'response', self._base_result(responses=responses))
        out = capsys.readouterr().out
        assert '2' in out

    def test_prints_potentials(self, capsys):
        responses = [
            {'potential': -0.2}, {'potential': 0.2},
        ]
        self._print(2, 'response', self._base_result(responses=responses))
        out = capsys.readouterr().out
        assert '-0.2' in out
        assert '0.2' in out

    def test_prints_gs_occupation(self, capsys):
        gs_occ = {
            'total_d_occupation': 16.468,
            'atom_count': 2,
            'target_species': 'Ni',
        }
        self._print(2, 'response', self._base_result(
            ground_state_occupation=gs_occ))
        out = capsys.readouterr().out
        assert '8.234' in out
        assert 'Ni' in out

    def test_prints_none_values_gracefully(self, capsys):
        """All None values should not raise."""
        self._print(1, 'response', self._base_result())
        out = capsys.readouterr().out
        assert 'hubbard_response' in out.lower()


# ---------------------------------------------------------------------------
# TestPrintHubbardAnalysisStageResults
# ---------------------------------------------------------------------------

@pytest.mark.tier1
class TestPrintHubbardAnalysisStageResults:
    """Tests for quantum_lego.core.bricks.hubbard_analysis.print_stage_results()."""

    def _print(self, index, stage_name, stage_result):
        from quantum_lego.core.bricks.hubbard_analysis import print_stage_results
        print_stage_results(index, stage_name, stage_result)

    def _base_result(self, **overrides):
        result = {
            'summary': None, 'hubbard_u_eV': None,
            'target_species': None, 'chi_r2': None, 'chi_0_r2': None,
            'response_data': None, 'pk': 1,
            'stage': 'analysis', 'type': 'hubbard_analysis',
        }
        result.update(overrides)
        return result

    def test_prints_analysis_label(self, capsys):
        self._print(3, 'analysis', self._base_result())
        out = capsys.readouterr().out
        assert '(hubbard_analysis)' in out.lower()

    def test_prints_u_value(self, capsys):
        self._print(3, 'analysis', self._base_result(hubbard_u_eV=3.456))
        out = capsys.readouterr().out
        assert '3.456' in out

    def test_prints_target_species(self, capsys):
        self._print(3, 'analysis', self._base_result(target_species='Ni'))
        out = capsys.readouterr().out
        assert 'Ni' in out

    def test_prints_r_squared(self, capsys):
        self._print(3, 'analysis', self._base_result(
            chi_r2=0.998765, chi_0_r2=0.999123))
        out = capsys.readouterr().out
        assert '0.998765' in out
        assert '0.999123' in out

    def test_prints_potentials(self, capsys):
        rd = {'potential_values_eV': [-0.2, -0.1, 0.1, 0.2]}
        self._print(3, 'analysis', self._base_result(response_data=rd))
        out = capsys.readouterr().out
        assert '-0.2' in out
        assert '0.2' in out

    def test_prints_avg_d_occupation(self, capsys):
        summary = {
            'summary': {'hubbard_u_eV': 3.5, 'target_species': 'Ni'},
            'ground_state': {'average_d_per_atom': 8.234},
        }
        self._print(3, 'analysis', self._base_result(
            summary=summary, target_species='Ni'))
        out = capsys.readouterr().out
        assert '8.234' in out

    def test_prints_none_values_gracefully(self, capsys):
        """All None values should not raise."""
        self._print(1, 'analysis', self._base_result())
        out = capsys.readouterr().out
        assert 'hubbard_analysis' in out.lower()
