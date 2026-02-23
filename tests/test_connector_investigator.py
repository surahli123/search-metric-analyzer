"""Shared fixtures/fakes for connector investigator test contracts."""

from __future__ import annotations

import time
from typing import Any, Dict


def decomp_high_confidence() -> Dict[str, Any]:
    """Build a decomposition payload that yields High confidence."""
    return {
        "aggregate": {
            "metric": "click_quality_value",
            "severity": "P1",
            "relative_delta_pct": -12.5,
            "direction": "down",
        },
        "dominant_dimension": "tenant_tier",
        "drill_down_recommended": True,
        "dimensional_breakdown": {
            "tenant_tier": {
                "segments": [
                    {"segment_value": "standard", "contribution_pct": 70.0},
                    {"segment_value": "premium", "contribution_pct": 25.0},
                ]
            }
        },
        "mix_shift": {"mix_shift_contribution_pct": 8.0},
    }


def decomp_medium_confidence() -> Dict[str, Any]:
    """Build a decomposition payload that yields Medium confidence."""
    return {
        "aggregate": {
            "metric": "click_quality_value",
            "severity": "P1",
            "relative_delta_pct": -8.5,
            "direction": "down",
        },
        "dominant_dimension": "tenant_tier",
        "drill_down_recommended": False,
        "dimensional_breakdown": {
            "tenant_tier": {
                "segments": [
                    {"segment_value": "standard", "contribution_pct": 55.0},
                    {"segment_value": "premium", "contribution_pct": 30.0},
                ]
            }
        },
        "mix_shift": {"mix_shift_contribution_pct": 12.0},
    }


def sample_hypothesis() -> Dict[str, Any]:
    return {
        "archetype": "ranking_regression",
        "confirms_if": [
            "Click Quality drop concentrated in specific connector cohorts",
            "No compensating AI metric improvements",
            "Connector query latency stable during the movement window",
        ],
    }


def fake_inv(hypothesis: Dict[str, Any], decomposition: Dict[str, Any]) -> Dict[str, Any]:
    del hypothesis, decomposition
    return {
        "ran": True,
        "verdict": "confirmed",
        "reason": "all bounded checks passed",
        "queries": ["SELECT 1"],
        "evidence": [],
    }


def fake_rejecting_inv(
    hypothesis: Dict[str, Any], decomposition: Dict[str, Any]
) -> Dict[str, Any]:
    del hypothesis, decomposition
    return {
        "ran": True,
        "verdict": "rejected",
        "reason": "connector checks did not confirm hypothesis",
        "queries": ["SELECT 1"],
        "evidence": [],
    }


def fake_execute_ok(sql: str) -> Dict[str, Any]:
    del sql
    return {"rows": [{"matched": 1}], "elapsed_seconds": 0.01}


def fake_execute_slow(sql: str) -> Dict[str, Any]:
    del sql
    time.sleep(0.02)
    return {"rows": [{"matched": 0}], "elapsed_seconds": 0.02}
