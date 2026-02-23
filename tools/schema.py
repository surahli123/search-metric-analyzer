#!/usr/bin/env python3
"""Schema normalization helpers for v1 contract alignment.

This module provides a one-release compatibility bridge between legacy metric
field names and canonical v1 names.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List

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
