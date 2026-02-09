"""Regression tests for AIMD trajectory concatenation."""

import numpy as np
import pytest


def check_aiida():
    """Check if AiiDA is available and configured."""
    try:
        from aiida import load_profile
        load_profile()
        return True
    except Exception:
        return False


AIIDA_AVAILABLE = check_aiida()

if not AIIDA_AVAILABLE:
    pytest.skip("AiiDA not configured", allow_module_level=True)


from aiida import orm  # noqa: E402
from aiida.engine import WorkChain  # noqa: E402
from aiida_workgraph import WorkGraph, task  # noqa: E402

from quantum_lego.core.tasks import concatenate_trajectories  # noqa: E402
from quantum_lego.core.bricks.aimd import ensure_cartesian_trajectory  # noqa: E402


class DummyNoTrajectoryWorkChain(WorkChain):
    """WorkChain that optionally exposes trajectory but does not emit it."""

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.output('trajectory', valid_type=orm.TrajectoryData, required=False)
        spec.outline(cls._run)

    def _run(self):
        """No-op run method."""


@task.calcfunction
def make_test_trajectory(offset: orm.Int) -> orm.TrajectoryData:
    """Create a minimal valid TrajectoryData for concatenation tests."""
    value = int(offset)

    traj = orm.TrajectoryData()
    traj.set_trajectory(
        symbols=['H'],
        positions=np.array(
            [[[float(value), 0.0, 0.0]], [[float(value) + 1.0, 0.0, 0.0]]],
            dtype=float,
        ),
        stepids=np.array([0, 1], dtype=int),
        cells=np.array([np.eye(3), np.eye(3)], dtype=float),
        times=np.array([0.0, 1.0], dtype=float),
    )
    traj.set_array('energies', np.array([float(value), float(value) + 0.5], dtype=float))
    return traj


@pytest.mark.tier2
@pytest.mark.requires_aiida
class TestAimdTrajectoryConcatenation:
    """Regression coverage for concatenate_trajectories behavior."""

    def test_missing_upstream_trajectory_does_not_fail(self):
        """Missing optional trajectory outputs should not fail concatenation."""
        no_traj_task = task(DummyNoTrajectoryWorkChain)

        wg = WorkGraph(name='test_missing_upstream_trajectory')
        producer = wg.add_task(no_traj_task, name='producer')
        wg.add_task(
            concatenate_trajectories,
            name='concatenate_trajectories',
            trajectories={'s01_stage': producer.outputs.trajectory},
        )

        wg.run()

        assert wg.tasks['producer'].state == 'FINISHED'
        assert wg.tasks['concatenate_trajectories'].state == 'FINISHED'

        combined = wg.tasks['concatenate_trajectories'].outputs.result.value
        assert isinstance(combined, orm.TrajectoryData)
        assert combined.get_positions().shape == (0, 0, 3)
        assert combined.get_stepids().size == 0

    def test_concatenates_frames_in_sorted_stage_order(self):
        """Stage keys should be sorted before frame concatenation."""
        wg = WorkGraph(name='test_concatenate_stage_order')
        stage_b = wg.add_task(make_test_trajectory, name='stage_b', offset=orm.Int(10))
        stage_a = wg.add_task(make_test_trajectory, name='stage_a', offset=orm.Int(0))
        wg.add_task(
            concatenate_trajectories,
            name='concatenate_trajectories',
            trajectories={
                's02_production': stage_b.outputs.result,
                's01_equilibration': stage_a.outputs.result,
            },
        )

        wg.run()

        assert wg.tasks['concatenate_trajectories'].state == 'FINISHED'
        combined = wg.tasks['concatenate_trajectories'].outputs.result.value

        positions = combined.get_positions()
        energies = combined.get_array('energies')
        stepids = combined.get_stepids()

        assert positions.shape == (4, 1, 3)
        assert np.allclose(positions[:, 0, 0], np.array([0.0, 1.0, 10.0, 11.0]))
        assert np.allclose(energies, np.array([0.0, 0.5, 10.0, 10.5]))
        assert stepids.tolist() == [0, 1, 2, 3]
        assert combined.base.attributes.get('symbols') == ['H']

    def test_ensure_cartesian_trajectory_converts_fractional_positions(self):
        """Fractional trajectory positions should be converted to Cartesian."""
        traj = orm.TrajectoryData()
        traj.set_trajectory(
            symbols=['H'],
            positions=np.array([[[0.5, 0.5, 0.5]]], dtype=float),
            stepids=np.array([0], dtype=int),
            cells=np.array([[[10.0, 0.0, 0.0], [0.0, 12.0, 0.0], [0.0, 0.0, 14.0]]], dtype=float),
        )

        wg = WorkGraph(name='test_ensure_cartesian_trajectory')
        normalize = wg.add_task(
            ensure_cartesian_trajectory,
            name='normalize_trajectory',
            trajectory=traj,
        )
        wg.run()

        assert wg.tasks['normalize_trajectory'].state == 'FINISHED'
        normalized = normalize.outputs.result.value
        converted = normalized.get_positions()[0, 0]
        assert np.allclose(converted, np.array([5.0, 6.0, 7.0]))
