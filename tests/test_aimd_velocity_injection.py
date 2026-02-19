"""Manual AIMD velocity-injection integration scenario.

Moved from `examples/aimd/test_velocity_injection.py`.
"""

import pytest

pytestmark = [pytest.mark.requires_aiida, pytest.mark.tier3, pytest.mark.localwork]


def test_velocity_injection_manual_integration():
    """Manual integration check kept as a documented skipped test.

    Validates POSCAR velocity injection in real AIMD restart workflows.
    """
    pytest.skip('Manual integration scenario; execute the AIMD example and inspect POSCAR/CONTCAR outputs.')
