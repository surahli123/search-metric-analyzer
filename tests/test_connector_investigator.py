"""Shared fixtures/fakes for connector investigator test contracts."""

from __future__ import annotations

import time
from typing import Any, Dict

from tools.connector_investigator import ConnectorInvestigator


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


def test_max_three_queries_enforced():
    inv = ConnectorInvestigator(max_queries=3, timeout_seconds=120)
    result = inv.run(hypothesis=sample_hypothesis(), execute_query=fake_execute_ok)
    assert len(result["queries"]) <= 3


def test_timeout_returns_rejected_verdict():
    inv = ConnectorInvestigator(max_queries=3, timeout_seconds=0)
    result = inv.run(hypothesis=sample_hypothesis(), execute_query=fake_execute_slow)
    assert result["verdict"] == "rejected"
    assert "timeout" in result["reason"].lower()


def test_timeout_during_query_execution_returns_partial_evidence():
    inv = ConnectorInvestigator(max_queries=3, timeout_seconds=0.08)
    calls = {"count": 0}

    def fake_execute_with_slow_second_query(sql: str) -> Dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"rows": [{"matched": 1}], "elapsed_seconds": 0.0, "sql": sql}
        time.sleep(0.2)
        return {"rows": [{"matched": 1}], "elapsed_seconds": 0.2, "sql": sql}

    result = inv.run(
        hypothesis=sample_hypothesis(),
        execute_query=fake_execute_with_slow_second_query,
    )

    assert result["verdict"] == "rejected"
    assert "timeout" in result["reason"].lower()
    assert calls["count"] >= 2
    assert len(result["queries"]) == 1
    assert len(result["evidence"]) == 1
