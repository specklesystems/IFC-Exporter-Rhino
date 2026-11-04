"""Run the function end to end against a real Speckle server and automation.

Needs SPECKLE_TOKEN, SPECKLE_SERVER_URL, SPECKLE_PROJECT_ID and
SPECKLE_AUTOMATION_ID (environment or .env); skipped otherwise.
"""

import os
from pathlib import Path

import pytest
from speckle_automate import (
    AutomationContext,
    AutomationRunData,
    AutomationStatus,
    run_function,
)
from speckle_automate.fixtures import *  # noqa: F403

from main import FunctionInputs, automate_function

pytestmark = pytest.mark.skipif(
    not (os.getenv("SPECKLE_TOKEN") or Path(".env").exists()),
    reason="needs a Speckle server and test automation (see module docstring)",
)


def test_function_run(
    test_automation_run_data: AutomationRunData, test_automation_token: str
):
    automation_context = AutomationContext.initialize(
        test_automation_run_data, test_automation_token
    )
    automate_sdk = run_function(
        automation_context,
        automate_function,
        FunctionInputs(
            file_name="test_output",
            IFC_PROJECT_NAME="Speckle Export",
            IFC_SITE_NAME="Site",
            IFC_BUILDING_NAME="Building",
        ),
    )

    assert automate_sdk.run_status == AutomationStatus.SUCCEEDED
