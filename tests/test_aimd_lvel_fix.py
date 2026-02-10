"""Manual AIMD LVEL integration scenario.

Moved from `examples/aimd/test_lvel_fix.py` to keep examples focused on runnable
workflows and tests under `tests/`.
"""

import pytest

pytestmark = [pytest.mark.requires_aiida, pytest.mark.tier3]


def test_lvel_fix_manual_integration():
    """Manual integration check kept as a documented skipped test.

    This scenario requires running real AIMD jobs and inspecting retrieved files.
    """
    pytest.skip('Manual integration scenario; run examples/08_aimd/aimd_workflow.py for live checks.')
