"""Tier2 & tier3 integration tests for the AIMD lego brick.

Tier2: Tests calcfunctions with real AiiDA nodes but WITHOUT running VASP.
Tier3: Tests against pre-computed AIMD results.
"""

import numpy as np
import pytest


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

from quantum_lego.core.bricks.aimd import (  # noqa: E402
    ensure_cartesian_trajectory,
    extract_velocities_from_contcar,
    _looks_fractional_trajectory_positions,
    _fractional_to_cartesian_positions,
)
from quantum_lego.core.tasks import (  # noqa: E402
    create_poscar_file_with_velocities,
    concatenate_trajectories,
)


# ============================================================================
# TIER 2 — Calcfunction tests (no VASP needed)
# ============================================================================

@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestAimdFractionalDetection:
    """Test the fractional coordinate detection heuristic (pure Python)."""

    def test_fractional_positions_detected(self):
        """Positions in [0, 1] range with large cell should be detected as fractional."""
        positions = np.array([[[0.1, 0.2, 0.3], [0.5, 0.5, 0.5]]])
        cells = np.array([[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]])
        assert _looks_fractional_trajectory_positions(positions, cells) is True

    def test_cartesian_positions_not_detected(self):
        """Positions >> 1 should not be detected as fractional."""
        positions = np.array([[[5.0, 6.0, 7.0], [2.0, 3.0, 4.0]]])
        cells = np.array([[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]])
        assert _looks_fractional_trajectory_positions(positions, cells) is False

    def test_empty_positions_return_false(self):
        """Empty positions should return False."""
        positions = np.zeros((0, 0, 3))
        cells = np.zeros((0, 3, 3))
        assert _looks_fractional_trajectory_positions(positions, cells) is False

    def test_fractional_to_cartesian_conversion(self):
        """Fractional to Cartesian conversion should use cell vectors."""
        positions = np.array([[[0.5, 0.5, 0.5]]])
        cells = np.array([[[10.0, 0.0, 0.0], [0.0, 12.0, 0.0], [0.0, 0.0, 14.0]]])
        cartesian = _fractional_to_cartesian_positions(positions, cells)
        assert np.allclose(cartesian, [[[5.0, 6.0, 7.0]]])


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestAimdEnsureCartesianTrajectory:
    """Test ensure_cartesian_trajectory calcfunction with WorkGraph."""

    def test_converts_fractional_to_cartesian(self):
        """Fractional positions should be converted to Cartesian."""
        traj = orm.TrajectoryData()
        traj.set_trajectory(
            symbols=['Si', 'Si'],
            positions=np.array([[[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]]], dtype=float),
            stepids=np.array([0], dtype=int),
            cells=np.array([[[5.43, 0.0, 0.0], [0.0, 5.43, 0.0], [0.0, 0.0, 5.43]]], dtype=float),
        )

        wg = WorkGraph(name='test_ensure_cartesian')
        wg.add_task(
            ensure_cartesian_trajectory,
            name='normalize',
            trajectory=traj,
        )
        wg.run()

        assert wg.tasks['normalize'].state == 'FINISHED'
        result = wg.tasks['normalize'].outputs.result.value
        positions = result.get_positions()
        # 0.25 * 5.43 = 1.3575
        assert np.allclose(positions[0, 1], [1.3575, 1.3575, 1.3575], atol=0.01)

    def test_preserves_cartesian_positions(self):
        """Already-Cartesian positions should be preserved."""
        traj = orm.TrajectoryData()
        traj.set_trajectory(
            symbols=['H'],
            positions=np.array([[[5.0, 6.0, 7.0]]], dtype=float),
            stepids=np.array([0], dtype=int),
            cells=np.array([[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]], dtype=float),
        )

        wg = WorkGraph(name='test_preserve_cartesian')
        wg.add_task(
            ensure_cartesian_trajectory,
            name='normalize',
            trajectory=traj,
        )
        wg.run()

        assert wg.tasks['normalize'].state == 'FINISHED'
        result = wg.tasks['normalize'].outputs.result.value
        positions = result.get_positions()
        assert np.allclose(positions[0, 0], [5.0, 6.0, 7.0])

    def test_preserves_extra_arrays(self):
        """Extra arrays like energies should be preserved through conversion."""
        traj = orm.TrajectoryData()
        traj.set_trajectory(
            symbols=['H'],
            positions=np.array([[[0.5, 0.5, 0.5]]], dtype=float),
            stepids=np.array([0], dtype=int),
            cells=np.array([[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]], dtype=float),
        )
        traj.set_array('energies', np.array([-5.0], dtype=float))

        wg = WorkGraph(name='test_extra_arrays')
        wg.add_task(ensure_cartesian_trajectory, name='normalize', trajectory=traj)
        wg.run()

        result = wg.tasks['normalize'].outputs.result.value
        energies = result.get_array('energies')
        assert np.allclose(energies, [-5.0])


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestAimdImportAndBasic:
    """Test that AIMD brick can be imported and basic functionality works."""

    def test_aimd_brick_importable(self):
        """AIMD brick should import without errors."""
        from quantum_lego.core.bricks import aimd
        assert aimd is not None
        assert hasattr(aimd, 'validate_stage')
        assert hasattr(aimd, 'create_stage_tasks')
        assert hasattr(aimd, 'expose_stage_outputs')
        assert hasattr(aimd, 'get_stage_results')
        assert hasattr(aimd, 'print_stage_results')
        assert hasattr(aimd, 'PORTS')

    def test_aimd_ports_defined(self):
        """AIMD brick PORTS should define expected inputs/outputs."""
        from quantum_lego.core.bricks.aimd import PORTS
        assert 'inputs' in PORTS
        assert 'outputs' in PORTS
        assert 'trajectory' in PORTS['outputs']
        assert PORTS['outputs']['trajectory']['type'] == 'trajectory'

    def test_aimd_structure_fixtures(self, si_diamond_structure):
        """Test that structure fixtures work for AIMD calculations."""
        assert si_diamond_structure is not None
        assert len(si_diamond_structure.sites) == 2


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestAimdTrajectoryConcatenation:
    """Test trajectory concatenation already thoroughly tested in existing tests."""

    def test_concatenate_trajectories_basic(self):
        """concatenate_trajectories should work with basic trajectory data."""
        traj1 = orm.TrajectoryData()
        traj1.set_trajectory(
            symbols=['H'],
            positions=np.array([[[0.0, 0.0, 0.0]]], dtype=float),
            stepids=np.array([0], dtype=int),
            cells=np.array([[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]], dtype=float),
        )

        wg = WorkGraph(name='test_concat')
        wg.add_task(
            concatenate_trajectories,
            name='concat',
            trajectories={'s01_stage': traj1},
        )
        wg.run()

        assert wg.tasks['concat'].state == 'FINISHED'
        result = wg.tasks['concat'].outputs.result.value
        assert isinstance(result, orm.TrajectoryData)
        assert result.get_positions().shape == (1, 1, 3)
        assert result.get_stepids().tolist() == [0]


# ============================================================================
# TIER 3 — Result extraction from pre-computed AIMD calculations
# ============================================================================

@pytest.mark.tier3
@pytest.mark.localwork
@pytest.mark.requires_aiida
class TestAimdResultExtraction:
    """Validate result extraction from a completed AIMD calculation (Si)."""

    def test_aimd_stage_results_schema(self, reference_pks):
        """get_stage_results should return aimd-type dict with trajectory."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['aimd']['aimd_si']
        seq_result = build_sequential_result(scenario)

        stage_names = seq_result['__stage_names__']
        assert len(stage_names) >= 1, "AIMD pipeline should have at least 1 stage"

        # Get the first AIMD stage
        aimd_stage_name = stage_names[0]
        result = get_stage_results(seq_result, aimd_stage_name)

        assert result['type'] == 'aimd'
        assert result['stage'] == aimd_stage_name
        assert result['pk'] == seq_result['__workgraph_pk__']

    def test_aimd_returns_energy(self, reference_pks):
        """AIMD stage should return an energy value."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['aimd']['aimd_si']
        seq_result = build_sequential_result(scenario)

        aimd_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, aimd_stage_name)

        assert result['energy'] is not None, "AIMD should return energy"
        assert isinstance(result['energy'], (int, float)), f"Energy should be numeric, got {type(result['energy'])}"

    def test_aimd_returns_trajectory(self, reference_pks):
        """AIMD stage should return a TrajectoryData with correct dimensions."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['aimd']['aimd_si']
        seq_result = build_sequential_result(scenario)

        aimd_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, aimd_stage_name)

        assert result['trajectory'] is not None, "AIMD should produce a trajectory"
        traj = result['trajectory']
        positions = traj.get_positions()
        # 5 MD steps, 2 Si atoms, 3 coordinates
        assert positions.shape[1] == 2, f"Si diamond has 2 atoms, got {positions.shape[1]}"
        assert positions.shape[2] == 3, "Positions should have 3 coordinates"
        assert positions.shape[0] >= 1, "Trajectory should have at least 1 step"

    def test_aimd_returns_misc(self, reference_pks):
        """AIMD stage should return misc dict."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['aimd']['aimd_si']
        seq_result = build_sequential_result(scenario)

        aimd_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, aimd_stage_name)

        assert result['misc'] is not None, "AIMD should return misc dict"
        assert isinstance(result['misc'], dict)

    def test_aimd_trajectory_positions_are_cartesian(self, reference_pks):
        """AIMD trajectory positions should be in Cartesian coordinates (not fractional)."""
        from conftest import build_sequential_result
        from quantum_lego.core.results import get_stage_results

        scenario = reference_pks['aimd']['aimd_si']
        seq_result = build_sequential_result(scenario)

        aimd_stage_name = seq_result['__stage_names__'][0]
        result = get_stage_results(seq_result, aimd_stage_name)

        traj = result['trajectory']
        positions = traj.get_positions()

        # Si diamond lattice ~3.87 Å → atom positions should be > 1 Å
        # (fractional would be in [0, 1])
        max_pos = np.abs(positions).max()
        # If positions are Cartesian, max should be comparable to cell dimensions
        assert max_pos > 1.0, (
            f"Positions look fractional (max={max_pos:.3f}), expected Cartesian"
        )
