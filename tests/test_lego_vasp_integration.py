"""Tier2 & tier3 integration tests for the VASP lego brick.

Tier2: Tests calcfunctions and WorkGraph construction with real AiiDA nodes
       but WITHOUT running VASP.
Tier3: Tests against pre-computed VASP results stored in the AiiDA database.
"""

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# AiiDA availability guard
# ---------------------------------------------------------------------------


def _check_aiida():
    try:
        from aiida import load_profile
        load_profile()
        return True
    except Exception:
        return False


AIIDA_AVAILABLE = _check_aiida()

if not AIIDA_AVAILABLE:
    pytest.skip("AiiDA not configured", allow_module_level=True)

from aiida import orm  # noqa: E402
from aiida_workgraph import WorkGraph, task  # noqa: E402

from quantum_lego.core.common.utils import extract_total_energy  # noqa: E402
from quantum_lego.core.tasks import compute_dynamics  # noqa: E402
from quantum_lego.core.tasks import prepare_poscar_with_velocities  # noqa: E402


# ============================================================================
# TIER 2 — Calcfunction tests (no VASP needed)
# ============================================================================

@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestVaspExtractEnergy:
    """Test the extract_total_energy calcfunction with mock misc data."""

    def test_extract_energy_from_total_energies(self):
        """extract_total_energy should find energy_extrapolated inside total_energies."""
        energies = orm.Dict(dict={
            'total_energies': {
                'energy_extrapolated': -10.12345,
                'energy_no_entropy': -10.12300,
            }
        })

        wg = WorkGraph(name='test_extract_energy')
        wg.add_task(extract_total_energy, name='extract', energies=energies)
        wg.run()

        assert wg.tasks['extract'].state == 'FINISHED'
        result = wg.tasks['extract'].outputs.result.value
        assert isinstance(result, orm.Float)
        assert abs(float(result) - (-10.12345)) < 1e-8

    def test_extract_energy_flat_keys(self):
        """extract_total_energy should work with flat energy keys (no total_energies nesting)."""
        energies = orm.Dict(dict={'energy_extrapolated': -5.678})

        wg = WorkGraph(name='test_extract_energy_flat')
        wg.add_task(extract_total_energy, name='extract', energies=energies)
        wg.run()

        result = wg.tasks['extract'].outputs.result.value
        assert abs(float(result) - (-5.678)) < 1e-8

    def test_extract_energy_fallback_keys(self):
        """extract_total_energy should try energy_no_entropy, then energy as fallbacks."""
        energies = orm.Dict(dict={
            'total_energies': {'energy_no_entropy': -7.0}
        })

        wg = WorkGraph(name='test_extract_energy_fallback')
        wg.add_task(extract_total_energy, name='extract', energies=energies)
        wg.run()

        result = wg.tasks['extract'].outputs.result.value
        assert abs(float(result) - (-7.0)) < 1e-8

    def test_extract_energy_missing_raises(self):
        """extract_total_energy should fail when no recognized key is found."""
        energies = orm.Dict(dict={'some_other_key': 42})

        wg = WorkGraph(name='test_extract_energy_missing')
        wg.add_task(extract_total_energy, name='extract', energies=energies)
        wg.run()

        assert wg.tasks['extract'].state == 'FAILED'

    def test_extract_energy_outcar_fallback(self):
        """extract_total_energy should parse OUTCAR when misc keys are missing."""
        # Create mock OUTCAR content
        outcar_content = """
 free  energy   TOTEN  =      -832.63657516 eV

 energy  without entropy=     -832.63657516  energy(sigma->0) =     -832.63657516
"""
        # Create a FolderData with OUTCAR
        from aiida.orm import FolderData
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            outcar_path = os.path.join(tmpdir, 'OUTCAR')
            with open(outcar_path, 'w') as f:
                f.write(outcar_content)

            retrieved = FolderData()
            retrieved.put_object_from_filelike(open(outcar_path, 'rb'), 'OUTCAR')

        energies = orm.Dict(dict={'some_other_key': 42})

        wg = WorkGraph(name='test_extract_energy_outcar')
        wg.add_task(extract_total_energy, name='extract', energies=energies, retrieved=retrieved)
        wg.run()

        assert wg.tasks['extract'].state == 'FINISHED'
        result = wg.tasks['extract'].outputs.result.value
        assert isinstance(result, orm.Float)
        assert abs(float(result) - (-832.63657516)) < 1e-6


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestVaspComputeDynamics:
    """Test the compute_dynamics calcfunction with a real structure."""

    def test_compute_dynamics_bottom_fix(self, sno2_rutile_structure):
        """compute_dynamics should produce positions_dof for bottom-fixing."""
        wg = WorkGraph(name='test_compute_dynamics')
        wg.add_task(
            compute_dynamics,
            name='dynamics',
            structure=sno2_rutile_structure,
            fix_type=orm.Str('bottom'),
            fix_thickness=orm.Float(2.0),
        )
        wg.run()

        assert wg.tasks['dynamics'].state == 'FINISHED'
        result = wg.tasks['dynamics'].outputs.result.value
        assert isinstance(result, orm.Dict)
        dof = result.get_dict()['positions_dof']
        assert len(dof) == 6  # 2 Sn + 4 O atoms
        # Each entry should be [bool, bool, bool]
        for entry in dof:
            assert len(entry) == 3
            assert all(isinstance(v, bool) for v in entry)

    def test_compute_dynamics_no_fix_elements(self, si_diamond_structure):
        """compute_dynamics with no fix_elements should work on Si."""
        wg = WorkGraph(name='test_compute_dynamics_si')
        wg.add_task(
            compute_dynamics,
            name='dynamics',
            structure=si_diamond_structure,
            fix_type=orm.Str('bottom'),
            fix_thickness=orm.Float(1.0),
        )
        wg.run()

        assert wg.tasks['dynamics'].state == 'FINISHED'
        dof = wg.tasks['dynamics'].outputs.result.value.get_dict()['positions_dof']
        assert len(dof) == 2  # 2 Si atoms


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestVaspPreparePoscar:
    """Test the prepare_poscar_with_velocities calcfunction."""

    def test_prepare_poscar_with_velocities(self, si_diamond_structure):
        """Should generate POSCAR content with velocity block."""
        velocities = [[0.001, -0.002, 0.003], [0.004, 0.005, -0.006]]
        vel_dict = orm.Dict(dict={
            'has_velocities': True,
            'velocities': velocities,
            'n_atoms': 2,
            'units': 'Angstrom/fs',
        })

        wg = WorkGraph(name='test_prepare_poscar')
        wg.add_task(
            prepare_poscar_with_velocities,
            name='poscar',
            structure=si_diamond_structure,
            velocities_dict=vel_dict,
        )
        wg.run()

        assert wg.tasks['poscar'].state == 'FINISHED'
        result = wg.tasks['poscar'].outputs.result.value.get_dict()
        assert result['has_velocities'] is True
        assert result['n_atoms'] == 2
        assert 'poscar_content' in result
        poscar_content = result['poscar_content']
        assert isinstance(poscar_content, str)
        assert len(poscar_content) > 0

    def test_prepare_poscar_without_velocities(self, si_diamond_structure):
        """Should generate POSCAR without velocity block when none available."""
        vel_dict = orm.Dict(dict={
            'has_velocities': False,
            'velocities': [],
            'n_atoms': 2,
            'units': 'Angstrom/fs',
        })

        wg = WorkGraph(name='test_prepare_poscar_no_vel')
        wg.add_task(
            prepare_poscar_with_velocities,
            name='poscar',
            structure=si_diamond_structure,
            velocities_dict=vel_dict,
        )
        wg.run()

        assert wg.tasks['poscar'].state == 'FINISHED'
        result = wg.tasks['poscar'].outputs.result.value.get_dict()
        assert result['has_velocities'] is False


# ============================================================================
# TIER 3 — Result extraction from pre-computed VASP calculations
# ============================================================================

@pytest.mark.tier3
@pytest.mark.localwork
@pytest.mark.requires_aiida
class TestVaspRelaxResultExtraction:
    """Validate result extraction from a completed VASP relaxation (Si diamond)."""

    def test_get_results_returns_energy(self, reference_pks):
        """get_results should return a negative energy for Si relaxation."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results

        pk = reference_pks['vasp']['relax_si']['pk']
        load_node_or_skip(pk)  # skip if node missing

        result = get_results(pk)
        assert result['energy'] is not None, "Energy must not be None"
        assert isinstance(result['energy'], float)
        assert result['energy'] < 0, f"Si relaxation energy should be negative, got {result['energy']}"

    def test_get_results_returns_structure(self, reference_pks):
        """get_results should return a relaxed Si structure (NSW > 0)."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results

        pk = reference_pks['vasp']['relax_si']['pk']
        load_node_or_skip(pk)

        result = get_results(pk)
        assert result['structure'] is not None, "Relaxation must produce a structure"
        formula = result['structure'].get_formula()
        assert 'Si' in formula, f"Structure formula should contain Si, got {formula}"
        assert len(result['structure'].sites) == 2, "Si diamond should have 2 atoms"

    def test_get_results_returns_misc(self, reference_pks):
        """get_results should return misc dict with total_energies."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results

        pk = reference_pks['vasp']['relax_si']['pk']
        load_node_or_skip(pk)

        result = get_results(pk)
        assert result['misc'] is not None, "misc must not be None"
        assert isinstance(result['misc'], dict)
        # VASP misc should contain total_energies or flat energy keys
        has_energy_key = (
            'total_energies' in result['misc']
            or 'energy_extrapolated' in result['misc']
        )
        assert has_energy_key, f"misc should have energy keys, got: {list(result['misc'].keys())}"

    def test_get_results_returns_files(self, reference_pks):
        """get_results should return retrieved FolderData."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results

        pk = reference_pks['vasp']['relax_si']['pk']
        load_node_or_skip(pk)

        result = get_results(pk)
        assert result['files'] is not None, "Retrieved files must not be None"
        file_names = result['files'].list_object_names()
        assert len(file_names) > 0, "Retrieved files should not be empty"

    def test_get_energy_matches_get_results(self, reference_pks):
        """get_energy should return the same value as get_results energy."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results, get_energy

        pk = reference_pks['vasp']['relax_si']['pk']
        load_node_or_skip(pk)

        result = get_results(pk)
        energy = get_energy(pk)
        assert abs(result['energy'] - energy) < 1e-10, "get_energy should match get_results"


@pytest.mark.tier3
@pytest.mark.localwork
@pytest.mark.requires_aiida
class TestVaspScfResultExtraction:
    """Validate result extraction from a completed VASP SCF (SnO2 rutile)."""

    def test_scf_returns_energy(self, reference_pks):
        """get_results should return a negative energy for SnO2 SCF."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results

        pk = reference_pks['vasp']['scf_sno2']['pk']
        load_node_or_skip(pk)

        result = get_results(pk)
        assert result['energy'] is not None
        assert result['energy'] < 0, f"SnO2 SCF energy should be negative, got {result['energy']}"

    def test_scf_no_output_structure(self, reference_pks):
        """SCF (NSW=0) should NOT produce an output structure."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results

        pk = reference_pks['vasp']['scf_sno2']['pk']
        load_node_or_skip(pk)

        result = get_results(pk)
        # NSW=0 means no ionic relaxation → no output structure
        assert result['structure'] is None, "SCF (NSW=0) should not produce output structure"

    def test_scf_returns_misc(self, reference_pks):
        """SCF should return misc dict with VASP outputs."""
        from conftest import load_node_or_skip
        from quantum_lego.core.results import get_results

        pk = reference_pks['vasp']['scf_sno2']['pk']
        load_node_or_skip(pk)

        result = get_results(pk)
        assert result['misc'] is not None
        assert isinstance(result['misc'], dict)
