#!/usr/bin/env python3
"""Schema normalization helpers for v1 contract alignment.

This module provides a one-release compatibility bridge between legacy metric
field names and canonical v1 names.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, TypedDict

# Canonical metric names for v1.
CANONICAL_METRICS = {
    "click_quality_value",
    "search_quality_success_value",
    "ai_trigger",
    "ai_success",
}

# Legacy -> canonical bridge (one-release alias support).
LEGACY_TO_CANONICAL = {
    "dlctr": "click_quality_value",
    "dlctr_value": "click_quality_value",
    "qsr": "search_quality_success_value",
    "qsr_value": "search_quality_success_value",
    "sain_trigger": "ai_trigger",
    "sain_success": "ai_success",
}

# Canonical -> preferred legacy alias (for backward-compatible output fields).
CANONICAL_TO_LEGACY = {
    "click_quality_value": "dlctr_value",
    "search_quality_success_value": "qsr_value",
    "ai_trigger": "sain_trigger",
    "ai_success": "sain_success",
}


def _to_float(value: Any) -> float | None:
    """Convert values to float safely; return None if unparsable."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_metric_name(metric_name: str) -> str:
    """Return canonical metric name when a legacy alias is provided."""
    if metric_name is None:
        return metric_name
    return LEGACY_TO_CANONICAL.get(metric_name, metric_name)


def _normalize_trust_fields(row: Dict[str, Any]) -> None:
    """Normalize trust-gate aliases in-place.

    Canonical trust fields expected by analysis tools:
    - data_completeness (ratio 0-1)
    - data_freshness_min (minutes)

    CSV-facing aliases:
    - completeness_pct (0-100)
    - freshness_lag_min (minutes)
    """
    raw_completeness = _to_float(row.get("data_completeness"))
    if raw_completeness is None:
        raw_completeness = _to_float(row.get("completeness_pct"))
        if raw_completeness is not None:
            raw_completeness /= 100.0
    elif raw_completeness > 1.0:
        # Defensive handling when completeness is accidentally encoded as percent.
        raw_completeness /= 100.0

    raw_freshness = _to_float(row.get("data_freshness_min"))
    if raw_freshness is None:
        raw_freshness = _to_float(row.get("freshness_lag_min"))

    if raw_completeness is not None:
        row["data_completeness"] = raw_completeness
        row.setdefault("completeness_pct", round(raw_completeness * 100.0, 6))

    if raw_freshness is not None:
        row["data_freshness_min"] = raw_freshness
        row.setdefault("freshness_lag_min", raw_freshness)


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a row and add one-release alias bridge keys."""
    normalized = dict(row)

    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        if canonical not in normalized and legacy in normalized:
            normalized[canonical] = normalized[legacy]

    for canonical, legacy in CANONICAL_TO_LEGACY.items():
        if legacy not in normalized and canonical in normalized:
            normalized[legacy] = normalized[canonical]

    _normalize_trust_fields(normalized)
    return normalized


def normalize_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize a list of rows with metric aliases and trust fields."""
    return [normalize_row(r) for r in rows]


def normalize_diagnosis_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize diagnosis payload fields consumed by formatter/eval tools."""
    normalized = deepcopy(payload)
    aggregate = normalized.get("aggregate")
    if isinstance(aggregate, dict) and "metric" in aggregate:
        aggregate["metric"] = normalize_metric_name(aggregate["metric"])

    normalized.setdefault("decision_status", "diagnosed")
    return normalized


# ---------------------------------------------------------------------------
# Multi-agent schemas (Phase 2.1)
#
# WHY TypedDict?
# The codebase uses plain dicts everywhere.  TypedDict is the lightest-weight
# way to declare "a dict with these expected keys" without adding dataclasses,
# Pydantic, or any runtime dependency.  It gives us IDE autocomplete and
# type-checker support while remaining 100% dict-compatible at runtime.
#
# Think of TypedDict as a "schema declaration" — it tells humans and tools
# what shape the data should have, but at runtime it's still just a dict.
# ---------------------------------------------------------------------------

# The four valid verdict strings any specialist agent can return.
# Using a set for O(1) membership checks (like checking if a value is in
# an allowed-list — same idea as validating an enum in an API contract).
VALID_VERDICTS = {"confirmed", "rejected", "inconclusive", "blocked"}


class AgentVerdict(TypedDict, total=False):
    """Normalized payload shape for every specialist agent.

    Every agent in the multi-agent system returns a dict that conforms to
    this shape.  Using total=False means all fields are optional at the
    type-checker level — the normalize_agent_verdict() function below is
    responsible for filling in safe defaults at runtime.

    Fields:
        agent:    Name of the specialist agent (e.g., "ranking", "data_quality").
        ran:      Whether the agent actually executed its analysis.
        verdict:  One of VALID_VERDICTS — the agent's conclusion.
        reason:   Human-readable explanation of the verdict.
        queries:  List of queries/commands the agent ran (for audit trail).
        evidence: List of evidence dicts supporting the verdict.
        cost:     Resource usage dict with 'queries' (int) and 'seconds' (float).
    """

    agent: str
    ran: bool
    verdict: str
    reason: str
    queries: list
    evidence: list
    cost: dict


class OrchestrationResult(TypedDict, total=False):
    """Normalized payload shape for the orchestrator's fused output.

    After all specialist agents report back, the orchestrator fuses their
    individual verdicts into a single orchestration result.  This is the
    "final answer" payload that downstream consumers (formatters, UI, logs)
    will read.

    Fields:
        orchestrated:           Whether orchestration actually ran.
        agents_run:             List of agent names that were invoked.
        fused_verdict:          The combined verdict across all agents.
        fused_reason:           Human-readable summary of the fused reasoning.
        updated_decision_status: The new decision status after orchestration.
        run_log:                List of per-agent run metadata for debugging.
    """

    orchestrated: bool
    agents_run: list
    fused_verdict: str
    fused_reason: str
    updated_decision_status: str
    run_log: list


def normalize_agent_verdict(raw: dict) -> dict:
    """Normalize a raw agent verdict dict by filling in safe defaults.

    WHY this function exists:
    Specialist agents are unreliable — they might crash, timeout, or return
    partial results.  Rather than letting KeyError exceptions cascade through
    the orchestrator, we normalize every agent's output into a predictable
    shape BEFORE any downstream code touches it.

    This is the same pattern as API input validation: sanitize at the boundary,
    so internal code can trust the data shape.  Think of it like a data pipeline
    stage that cleans messy upstream data before it enters your analytics layer.

    Design decisions:
    - Uses .setdefault() so existing keys are NEVER overwritten (additive-only).
    - Unknown verdict values are clamped to "inconclusive" (conservative default).
    - Extra keys beyond the schema are preserved (agents may attach debug info).
    - Returns a new dict (shallow copy) to avoid mutating the caller's data.

    Args:
        raw: A dict from a specialist agent.  May be empty, partial, or complete.

    Returns:
        A dict guaranteed to have all AgentVerdict keys with safe values.
    """
    # Shallow copy so we don't mutate the caller's dict.
    # (Same reason you'd copy a DataFrame before transforming it in a pipeline.)
    result = dict(raw)

    # --- Fill in missing keys with conservative defaults ---
    # .setdefault(key, default) only sets the value if the key is ABSENT.
    # If the key already exists (even with a falsy value like False or 0),
    # it leaves the existing value untouched.  This is the "additive-only" guarantee.

    result.setdefault("agent", "unknown")           # Who reported this?
    result.setdefault("ran", False)                  # Did the agent actually run?
    result.setdefault("verdict", "inconclusive")     # What did it conclude?
    result.setdefault("reason", "no reason provided") # Why?
    result.setdefault("queries", [])                 # What queries did it execute?
    result.setdefault("evidence", [])                # What evidence supports the verdict?
    result.setdefault("cost", {"queries": 0, "seconds": 0.0})  # Resource usage

    # --- Validate the verdict value ---
    # If the agent returned a verdict string that's not in our allowed set
    # (e.g., "maybe", "yes", or a typo), clamp it to "inconclusive".
    # This prevents garbage from propagating to downstream consumers.
    if result["verdict"] not in VALID_VERDICTS:
        result["verdict"] = "inconclusive"

    return result
