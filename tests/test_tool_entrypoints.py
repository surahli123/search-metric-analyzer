"""CLI entrypoint compatibility tests for tool scripts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
EVAL_DIR = ROOT / "eval"


@pytest.mark.parametrize(
    "script_name",
    [
        "anomaly.py",
        "decompose.py",
        "diagnose.py",
        "formatter.py",
        "generate_synthetic_data.py",
        "validate_scenarios.py",
    ],
)
def test_tool_scripts_support_help(script_name: str):
    """Direct script execution should work for help invocation."""
    script_path = TOOLS_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    combined = f"{result.stdout}\n{result.stderr}".lower()
    assert result.returncode == 0, combined
    assert "usage" in combined


def test_stress_test_help_lists_connector_spike_flag():
    """Stress-test CLI should advertise connector spike switch."""
    script_path = EVAL_DIR / "run_stress_test.py"
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, combined
    assert "--enable-connector-spike" in combined
