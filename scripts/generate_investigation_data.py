#!/usr/bin/env python3
"""Generate realistic synthetic search metric CSVs with planted regression scenarios.

PURPOSE:
    Creates CSV files that can be fed directly into the orchestrator pipeline
    (core/decompose.py, core/anomaly.py, core/diagnose.py) for end-to-end
    investigation testing. Each CSV contains a "baseline" period and a "current"
    period, with a specific regression/pattern planted in the current period.

WHY SEPARATE FROM generators/generate_synthetic_data.py?
    The existing generator creates raw session-level data for all 13 eval
    scenarios (S0-S12). This script creates AGGREGATE-level data specifically
    designed for running investigations through the orchestrator. The format
    matches what decompose.py expects: rows with metric values + dimension
    columns + a period column for baseline/current comparison.

SCENARIOS (5 total):
    1. ranking_regression   — CQ drops ~3.5%, SQS drops ~2%, AI stable (P1)
    2. ai_adoption_positive — CQ drops for ai_on, AI up, SQS stable (NOT a regression)
    3. connector_failure    — One connector severely degraded, others normal (P0)
    4. mix_shift            — No per-segment change, aggregate drops from composition shift
    5. normal_variance      — Small random fluctuations, no action needed

USAGE:
    python scripts/generate_investigation_data.py                        # All 5
    python scripts/generate_investigation_data.py --scenario ranking_regression
    python scripts/generate_investigation_data.py --list
    python scripts/generate_investigation_data.py --output-dir /tmp/out

OUTPUT:
    data/investigations/scenario_<name>.csv (one per scenario)

DESIGN DECISIONS:
    - stdlib only (csv, random) — no pandas/numpy per project convention
    - Deterministic with --seed for reproducibility
    - Each dimension combination gets 3-5 rows per period for meaningful decomposition
    - Small random noise (±1-2%) added to all values for realism
    - SQS computed from formula: max(click_component, ai_trigger * ai_success)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Column schema — defines what every output CSV must contain.
# These columns are what core/decompose.py expects when run with
# --dimensions tenant_tier,ai_enablement,industry_vertical,connector_type,query_type
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    # Metric columns (the values being diagnosed)
    "click_quality_value",
    "search_quality_success_value",
    "ai_trigger",
    "ai_success",
    "zero_result",
    "latency_ms",
    # Data quality columns (trust gates for the pipeline)
    "data_completeness",
    "data_freshness_min",
    # Dimension columns (for decomposition)
    "tenant_tier",
    "ai_enablement",
    "connector_type",
    "industry_vertical",
    "query_type",
    # Period column (baseline vs current for WoW comparison)
    "period",
    # Optional metadata
    "metric_ts",
    "scenario_id",
]


# ---------------------------------------------------------------------------
# Baseline metric values by segment.
# Source: data/knowledge/metric_definitions.yaml + rules/01-metric-invariants.md
#
# WHY per-segment baselines?
# Enterprise Search metrics vary significantly by segment. A 0.220 CQ for
# ai_on is healthy; the same for ai_off is a P0 incident. Generating data
# without segment-specific baselines would produce unrealistic CSVs that
# the decompose tool wouldn't meaningfully analyze.
# ---------------------------------------------------------------------------

# Click Quality baselines by tenant_tier
TIER_CQ_BASELINES = {
    "standard": 0.245,
    "premium": 0.280,
    "enterprise": 0.295,
}

# Click Quality baselines by ai_enablement
AI_CQ_BASELINES = {
    "ai_on": 0.220,
    "ai_off": 0.310,
}

# AI metric baselines by ai_enablement
# WHY ai_off = 0.0? Because AI answers are disabled — no trigger, no success.
AI_METRIC_BASELINES = {
    "ai_on": {"ai_trigger": 0.35, "ai_success": 0.65},
    "ai_off": {"ai_trigger": 0.0, "ai_success": 0.0},
}

# SQS baselines by segment (derived from CQ + AI formula)
# SQS = max(click_component, ai_trigger * ai_success)
# For ai_on: max(0.220, 0.35 * 0.65) = max(0.220, 0.2275) = 0.2275
# For ai_off: max(0.310, 0) = 0.310
SQS_BASELINE_GLOBAL = 0.378

# Latency baselines (milliseconds)
LATENCY_BASELINE = 200
LATENCY_STDDEV = 50

# Data quality healthy ranges
DATA_COMPLETENESS_HEALTHY = 0.985  # Typical: 0.96-1.0
DATA_FRESHNESS_HEALTHY = 15        # Typical: 0-30 minutes


# ---------------------------------------------------------------------------
# Dimension value sets and their traffic distributions.
# These control how many rows each dimension combination gets.
# Distributions are approximate — they create realistic-looking data
# without exactly matching production (which we don't have access to).
# ---------------------------------------------------------------------------

TENANT_TIERS = ["standard", "premium", "enterprise"]
TIER_WEIGHTS = [0.50, 0.30, 0.20]  # standard = most traffic

AI_ENABLEMENTS = ["ai_on", "ai_off"]
AI_WEIGHTS = [0.40, 0.60]  # majority still ai_off

CONNECTOR_TYPES = ["confluence", "slack", "gdrive", "jira", "sharepoint"]
CONNECTOR_WEIGHTS = [0.30, 0.20, 0.25, 0.15, 0.10]

INDUSTRY_VERTICALS = ["tech", "finance", "retail", "healthcare"]
INDUSTRY_WEIGHTS = [0.35, 0.25, 0.25, 0.15]

QUERY_TYPES = ["navigational", "informational", "action"]
QUERY_WEIGHTS = [0.40, 0.40, 0.20]

# Target rows per period (total = 2x this for baseline + current)
# We want 200-400 total, so ~100-200 per period.
ROWS_PER_PERIOD = 150


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]. Prevents metrics from going out of range.

    WHY: Random noise can push values below 0 or above 1, which is
    physically meaningless for rate metrics. Clamping is the simplest
    way to keep values in range without distorting the distribution.
    """
    return max(lo, min(hi, value))


def _add_noise(value: float, noise_pct: float = 0.015) -> float:
    """Add small random noise to a value for realism.

    Args:
        value: The base value to add noise to.
        noise_pct: Maximum noise as a fraction of the value (default ±1.5%).

    WHY: Real metric data has variance. Perfectly clean data would be
    unrealistic and might not exercise the decomposition tool's noise
    tolerance logic properly.

    WHY the zero guard? When AI is disabled (ai_off), trigger and success
    are exactly 0.0. Adding noise would make them non-zero, which is
    physically wrong — you can't have fractional AI triggers when the
    feature is off. The downstream SQS formula also depends on exact zeros.
    """
    if value == 0.0:
        return 0.0  # Don't add noise to zero values (e.g., AI metrics when AI is off)
    noise = random.gauss(0, noise_pct * max(value, 0.01))
    return value + noise


def _weighted_choice(values: list, weights: list) -> str:
    """Pick a value from a weighted distribution.

    Uses random.choices (Python 3.6+) which does weighted sampling.
    Returns a single value (we always pick 1 item).
    """
    return random.choices(values, weights=weights, k=1)[0]


def _compute_baseline_cq(tier: str, ai: str) -> float:
    """Compute baseline Click Quality for a (tier, ai_enablement) combination.

    WHY blend both signals?
    CQ depends on BOTH tenant tier (index quality) and AI enablement
    (click cannibalization). We blend them with equal weight because
    both effects are roughly equal in magnitude in real data.
    """
    tier_cq = TIER_CQ_BASELINES[tier]
    ai_cq = AI_CQ_BASELINES[ai]
    # Simple average of the two baselines — in production this would be
    # a more complex interaction, but for synthetic data this gives
    # realistic per-segment variation.
    return (tier_cq + ai_cq) / 2.0


def _compute_sqs(cq: float, ai_trigger: float, ai_success: float) -> float:
    """Compute Search Quality Success from the canonical formula.

    SQS = max(click_component, ai_trigger * ai_success)

    This formula is a DOMAIN INVARIANT — see rules/01-metric-invariants.md.
    The idea: a query is "successful" if the user EITHER clicked a good
    result OR got a satisfying AI answer.
    """
    ai_component = ai_trigger * ai_success
    return max(cq, ai_component)


def _make_timestamp(period: str, row_index: int) -> str:
    """Generate a plausible ISO 8601 timestamp for a row.

    Baseline timestamps are from 7 days ago; current from today.
    This matches the typical WoW (week-over-week) comparison pattern.
    """
    if period == "baseline":
        base_date = dt.datetime(2026, 3, 14, 8, 0, 0)
    else:
        base_date = dt.datetime(2026, 3, 21, 8, 0, 0)
    # Spread rows across the day (86400 seconds)
    offset_seconds = (row_index * 60) % 86400
    ts = base_date + dt.timedelta(seconds=offset_seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_dimension_combos(rows_per_period: int) -> List[Dict[str, str]]:
    """Generate a list of dimension combinations for one period.

    Each combination of (tier, ai, connector, industry, query_type) gets
    represented. We use weighted random sampling to create realistic
    distributions — enterprise tier appears less often than standard, etc.

    Returns a list of dicts, each with the 5 dimension columns filled in.
    """
    combos = []
    for _ in range(rows_per_period):
        combos.append({
            "tenant_tier": _weighted_choice(TENANT_TIERS, TIER_WEIGHTS),
            "ai_enablement": _weighted_choice(AI_ENABLEMENTS, AI_WEIGHTS),
            "connector_type": _weighted_choice(CONNECTOR_TYPES, CONNECTOR_WEIGHTS),
            "industry_vertical": _weighted_choice(INDUSTRY_VERTICALS, INDUSTRY_WEIGHTS),
            "query_type": _weighted_choice(QUERY_TYPES, QUERY_WEIGHTS),
        })
    return combos


def _generate_baseline_row(
    dims: Dict[str, str],
    row_index: int,
    scenario_id: str,
) -> Dict[str, Any]:
    """Generate a single baseline row with healthy metric values.

    This is the "normal" state — no regressions, no anomalies.
    All scenarios share the same baseline generation logic because
    the baseline period should look the same regardless of what
    happens in the current period.
    """
    tier = dims["tenant_tier"]
    ai = dims["ai_enablement"]

    # Click Quality — blended baseline for this segment
    cq = _add_noise(_compute_baseline_cq(tier, ai))
    cq = _clamp(cq)

    # AI metrics — dependent on ai_enablement
    ai_baselines = AI_METRIC_BASELINES[ai]
    ai_trigger = _clamp(_add_noise(ai_baselines["ai_trigger"]))
    ai_success = _clamp(_add_noise(ai_baselines["ai_success"]))

    # SQS from canonical formula (noise already in components)
    sqs = _clamp(_compute_sqs(cq, ai_trigger, ai_success))

    # Zero result — rare in healthy state (~3% of queries)
    zero_result = 1 if random.random() < 0.03 else 0

    # Latency — normally distributed around baseline
    latency = max(50, int(random.gauss(LATENCY_BASELINE, LATENCY_STDDEV)))

    # Data quality — healthy values
    completeness = _clamp(random.gauss(DATA_COMPLETENESS_HEALTHY, 0.005), 0.95, 1.0)
    freshness = max(0, int(random.gauss(DATA_FRESHNESS_HEALTHY, 5)))

    return {
        "click_quality_value": f"{cq:.6f}",
        "search_quality_success_value": f"{sqs:.6f}",
        "ai_trigger": f"{ai_trigger:.6f}",
        "ai_success": f"{ai_success:.6f}",
        "zero_result": str(zero_result),
        "latency_ms": str(latency),
        "data_completeness": f"{completeness:.6f}",
        "data_freshness_min": str(freshness),
        **dims,
        "period": "baseline",
        "metric_ts": _make_timestamp("baseline", row_index),
        "scenario_id": scenario_id,
    }


# ---------------------------------------------------------------------------
# Scenario generators — each returns a list of rows for the current period.
#
# PATTERN: Every scenario generator takes the same baseline dimension combos
# and applies scenario-specific modifications to the current period values.
# This ensures the baseline/current rows are dimensionally comparable
# (same segment distribution) unless the scenario deliberately changes
# the distribution (e.g., mix-shift).
# ---------------------------------------------------------------------------

def _generate_ranking_regression_current(
    dims: Dict[str, str],
    row_index: int,
    scenario_id: str,
) -> Dict[str, Any]:
    """Generate a current-period row for the ranking regression scenario.

    WHAT HAPPENS:
        Ranking model regression causes CQ to drop ~3.5% across ALL segments.
        SQS also drops ~2% because click_component is part of the SQS formula.
        AI metrics are unaffected (ranking model doesn't touch AI answers).

    CO-MOVEMENT PATTERN:
        CQ↓, SQS↓, AI stable → "Ranking regression" in the co-movement table.
        See rules/03-diagnostic-patterns.md, row 1.

    SEVERITY: P1 (CQ drops 2-5%)
    """
    tier = dims["tenant_tier"]
    ai = dims["ai_enablement"]

    # CQ drops ~3.5% relative to baseline
    # WHY relative, not absolute? Because a 3.5% relative drop means
    # different absolute drops for different segments (enterprise loses
    # more absolute value than standard). This is realistic.
    base_cq = _compute_baseline_cq(tier, ai)
    cq = _add_noise(base_cq * (1.0 - 0.035))
    cq = _clamp(cq)

    # AI metrics — unchanged from baseline (ranking doesn't affect AI)
    ai_baselines = AI_METRIC_BASELINES[ai]
    ai_trigger = _clamp(_add_noise(ai_baselines["ai_trigger"]))
    ai_success = _clamp(_add_noise(ai_baselines["ai_success"]))

    # SQS drops because CQ dropped (SQS = max(CQ, AI component))
    sqs = _clamp(_compute_sqs(cq, ai_trigger, ai_success))

    zero_result = 1 if random.random() < 0.04 else 0  # Slightly elevated
    latency = max(50, int(random.gauss(LATENCY_BASELINE, LATENCY_STDDEV)))
    completeness = _clamp(random.gauss(DATA_COMPLETENESS_HEALTHY, 0.005), 0.95, 1.0)
    freshness = max(0, int(random.gauss(DATA_FRESHNESS_HEALTHY, 5)))

    return {
        "click_quality_value": f"{cq:.6f}",
        "search_quality_success_value": f"{sqs:.6f}",
        "ai_trigger": f"{ai_trigger:.6f}",
        "ai_success": f"{ai_success:.6f}",
        "zero_result": str(zero_result),
        "latency_ms": str(latency),
        "data_completeness": f"{completeness:.6f}",
        "data_freshness_min": str(freshness),
        **dims,
        "period": "current",
        "metric_ts": _make_timestamp("current", row_index),
        "scenario_id": scenario_id,
    }


def _generate_ai_adoption_current(
    dims: Dict[str, str],
    row_index: int,
    scenario_id: str,
) -> Dict[str, Any]:
    """Generate a current-period row for the AI adoption positive signal scenario.

    WHAT HAPPENS:
        AI answers are rolling out successfully. For ai_on segments:
        - AI trigger rate UP ~15% (more queries get AI answers)
        - AI success rate UP ~8% (AI answers are better quality)
        - Click Quality DOWN ~4% (users click less because AI answered)
        - SQS STABLE or UP (AI component compensates for lost clicks)

        For ai_off segments: no change (they don't have AI answers).

    CO-MOVEMENT PATTERN:
        CQ↓ + AI↑ + SQS stable → "AI answers working" in co-movement table.
        This is a POSITIVE signal — do NOT flag as regression!
        See rules/01-metric-invariants.md: "Inverse Co-Movement (critical)"

    CRITICAL: The orchestrator must NOT misdiagnose this as a regression.
    """
    tier = dims["tenant_tier"]
    ai = dims["ai_enablement"]

    base_cq = _compute_baseline_cq(tier, ai)
    ai_baselines = AI_METRIC_BASELINES[ai]

    if ai == "ai_on":
        # CQ drops because users get answers from AI instead of clicking
        cq = _add_noise(base_cq * (1.0 - 0.04))

        # AI metrics improve — this is the rollout effect
        ai_trigger = _clamp(_add_noise(ai_baselines["ai_trigger"] * 1.15))
        ai_success = _clamp(_add_noise(ai_baselines["ai_success"] * 1.08))
    else:
        # ai_off segments are unaffected
        cq = _add_noise(base_cq)
        ai_trigger = _clamp(_add_noise(ai_baselines["ai_trigger"]))
        ai_success = _clamp(_add_noise(ai_baselines["ai_success"]))

    cq = _clamp(cq)
    sqs = _clamp(_compute_sqs(cq, ai_trigger, ai_success))

    zero_result = 1 if random.random() < 0.03 else 0
    latency = max(50, int(random.gauss(LATENCY_BASELINE, LATENCY_STDDEV)))
    completeness = _clamp(random.gauss(DATA_COMPLETENESS_HEALTHY, 0.005), 0.95, 1.0)
    freshness = max(0, int(random.gauss(DATA_FRESHNESS_HEALTHY, 5)))

    return {
        "click_quality_value": f"{cq:.6f}",
        "search_quality_success_value": f"{sqs:.6f}",
        "ai_trigger": f"{ai_trigger:.6f}",
        "ai_success": f"{ai_success:.6f}",
        "zero_result": str(zero_result),
        "latency_ms": str(latency),
        "data_completeness": f"{completeness:.6f}",
        "data_freshness_min": str(freshness),
        **dims,
        "period": "current",
        "metric_ts": _make_timestamp("current", row_index),
        "scenario_id": scenario_id,
    }


def _generate_connector_failure_current(
    dims: Dict[str, str],
    row_index: int,
    scenario_id: str,
    failing_connector: str = "confluence",
) -> Dict[str, Any]:
    """Generate a current-period row for the connector failure scenario.

    WHAT HAPPENS:
        One connector (confluence) has severe degradation:
        - CQ drops >8% for queries hitting that connector
        - Zero-result rate spikes (connector not returning documents)
        - Data freshness degrades (stale index)
        - All other connectors are completely unaffected

    WHY CONFLUENCE?
        Confluence is the most common connector (30% of traffic), so a
        failure there has high impact on aggregate metrics. This tests
        the decomposition tool's ability to isolate the dimension.

    SEVERITY: P0 (CQ drops >5% for the affected segment, >8% actually)
    """
    tier = dims["tenant_tier"]
    ai = dims["ai_enablement"]
    connector = dims["connector_type"]

    base_cq = _compute_baseline_cq(tier, ai)
    ai_baselines = AI_METRIC_BASELINES[ai]

    if connector == failing_connector:
        # Severe degradation for the failing connector
        cq = _add_noise(base_cq * (1.0 - 0.12), noise_pct=0.02)  # ~12% drop
        ai_trigger = _clamp(_add_noise(ai_baselines["ai_trigger"] * 0.7))  # AI also hurt
        ai_success = _clamp(_add_noise(ai_baselines["ai_success"] * 0.8))

        # High zero-result rate — connector not returning documents
        zero_result = 1 if random.random() < 0.25 else 0

        # Stale data for failing connector
        if random.random() < 0.3:
            freshness = random.randint(60, 180)  # Stale: 60-180 minutes
        else:
            freshness = max(0, int(random.gauss(30, 10)))
        completeness = _clamp(random.gauss(0.92, 0.02), 0.85, 1.0)

        # Latency spike for failing connector
        latency = max(50, int(random.gauss(350, 80)))
    else:
        # Other connectors are unaffected — normal baseline values
        cq = _add_noise(base_cq)
        ai_trigger = _clamp(_add_noise(ai_baselines["ai_trigger"]))
        ai_success = _clamp(_add_noise(ai_baselines["ai_success"]))
        zero_result = 1 if random.random() < 0.03 else 0
        freshness = max(0, int(random.gauss(DATA_FRESHNESS_HEALTHY, 5)))
        completeness = _clamp(random.gauss(DATA_COMPLETENESS_HEALTHY, 0.005), 0.95, 1.0)
        latency = max(50, int(random.gauss(LATENCY_BASELINE, LATENCY_STDDEV)))

    cq = _clamp(cq)
    sqs = _clamp(_compute_sqs(cq, ai_trigger, ai_success))

    return {
        "click_quality_value": f"{cq:.6f}",
        "search_quality_success_value": f"{sqs:.6f}",
        "ai_trigger": f"{ai_trigger:.6f}",
        "ai_success": f"{ai_success:.6f}",
        "zero_result": str(zero_result),
        "latency_ms": str(latency),
        "data_completeness": f"{completeness:.6f}",
        "data_freshness_min": str(freshness),
        **dims,
        "period": "current",
        "metric_ts": _make_timestamp("current", row_index),
        "scenario_id": scenario_id,
    }


def _generate_mix_shift_scenario(
    scenario_id: str,
    rows_per_period: int,
) -> List[Dict[str, Any]]:
    """Generate the full mix-shift scenario (both baseline and current).

    WHAT HAPPENS:
        No per-segment metric change — every tier's CQ stays the same.
        But the COMPOSITION of traffic shifts: more standard tier (which has
        lower baseline CQ), fewer enterprise tier. The aggregate average
        drops purely from this population shift.

    WHY SPECIAL HANDLING?
        Mix-shift is unique because it requires changing the DIMENSION
        DISTRIBUTION between baseline and current, not the metric values.
        Other scenarios use the same dimension distribution for both periods
        and only change the metric values. This one does the opposite.

    CO-MOVEMENT PATTERN:
        CQ↓ at aggregate level, but stable per-segment → mix-shift.
        See rules/03-diagnostic-patterns.md: "Enterprise onboarding wave"
    """
    all_rows = []

    # Baseline period: normal tier distribution
    # Standard=50%, Premium=30%, Enterprise=20%
    baseline_tier_weights = [0.50, 0.30, 0.20]
    baseline_combos = []
    for _ in range(rows_per_period):
        baseline_combos.append({
            "tenant_tier": _weighted_choice(TENANT_TIERS, baseline_tier_weights),
            "ai_enablement": _weighted_choice(AI_ENABLEMENTS, AI_WEIGHTS),
            "connector_type": _weighted_choice(CONNECTOR_TYPES, CONNECTOR_WEIGHTS),
            "industry_vertical": _weighted_choice(INDUSTRY_VERTICALS, INDUSTRY_WEIGHTS),
            "query_type": _weighted_choice(QUERY_TYPES, QUERY_WEIGHTS),
        })

    for i, dims in enumerate(baseline_combos):
        all_rows.append(_generate_baseline_row(dims, i, scenario_id))

    # Current period: shifted tier distribution — MORE standard tier
    # Standard=65%, Premium=20%, Enterprise=15%
    # This simulates a wave of new standard-tier tenant onboardings,
    # which is a common real-world pattern in Enterprise SaaS.
    current_tier_weights = [0.65, 0.20, 0.15]
    current_combos = []
    for _ in range(rows_per_period):
        current_combos.append({
            "tenant_tier": _weighted_choice(TENANT_TIERS, current_tier_weights),
            "ai_enablement": _weighted_choice(AI_ENABLEMENTS, AI_WEIGHTS),
            "connector_type": _weighted_choice(CONNECTOR_TYPES, CONNECTOR_WEIGHTS),
            "industry_vertical": _weighted_choice(INDUSTRY_VERTICALS, INDUSTRY_WEIGHTS),
            "query_type": _weighted_choice(QUERY_TYPES, QUERY_WEIGHTS),
        })

    for i, dims in enumerate(current_combos):
        # Use baseline row generation (no metric changes) but mark as current
        row = _generate_baseline_row(dims, i, scenario_id)
        row["period"] = "current"
        row["metric_ts"] = _make_timestamp("current", i)
        all_rows.append(row)

    return all_rows


def _generate_normal_variance_current(
    dims: Dict[str, str],
    row_index: int,
    scenario_id: str,
) -> Dict[str, Any]:
    """Generate a current-period row for the normal variance scenario.

    WHAT HAPPENS:
        Nothing. All metrics are within normal fluctuation range (<1%).
        This scenario is the control — it tests that the orchestrator
        correctly classifies this as "no action needed" / P2.

    WHY THIS MATTERS:
        A diagnostic system that flags normal variance as a regression
        is worse than useless — it erodes trust and wastes engineer time.
        This scenario tests the system's ability to say "everything is fine."
    """
    tier = dims["tenant_tier"]
    ai = dims["ai_enablement"]

    # Normal values with standard noise — no modifications
    base_cq = _compute_baseline_cq(tier, ai)
    cq = _add_noise(base_cq)
    cq = _clamp(cq)

    ai_baselines = AI_METRIC_BASELINES[ai]
    ai_trigger = _clamp(_add_noise(ai_baselines["ai_trigger"]))
    ai_success = _clamp(_add_noise(ai_baselines["ai_success"]))

    sqs = _clamp(_compute_sqs(cq, ai_trigger, ai_success))

    zero_result = 1 if random.random() < 0.03 else 0
    latency = max(50, int(random.gauss(LATENCY_BASELINE, LATENCY_STDDEV)))
    completeness = _clamp(random.gauss(DATA_COMPLETENESS_HEALTHY, 0.005), 0.95, 1.0)
    freshness = max(0, int(random.gauss(DATA_FRESHNESS_HEALTHY, 5)))

    return {
        "click_quality_value": f"{cq:.6f}",
        "search_quality_success_value": f"{sqs:.6f}",
        "ai_trigger": f"{ai_trigger:.6f}",
        "ai_success": f"{ai_success:.6f}",
        "zero_result": str(zero_result),
        "latency_ms": str(latency),
        "data_completeness": f"{completeness:.6f}",
        "data_freshness_min": str(freshness),
        **dims,
        "period": "current",
        "metric_ts": _make_timestamp("current", row_index),
        "scenario_id": scenario_id,
    }


# ---------------------------------------------------------------------------
# Scenario registry — maps scenario names to their generator functions.
# ---------------------------------------------------------------------------

SCENARIOS = {
    "ranking_regression": {
        "description": "Ranking model regression — CQ drops ~3.5%, SQS drops ~2%, AI stable (P1)",
        "current_generator": _generate_ranking_regression_current,
    },
    "ai_adoption_positive": {
        "description": "AI adoption positive signal — CQ drops for ai_on, AI up, SQS stable (NOT a regression)",
        "current_generator": _generate_ai_adoption_current,
    },
    "connector_failure": {
        "description": "Connector failure (confluence) — severe degradation isolated to one connector (P0)",
        "current_generator": _generate_connector_failure_current,
    },
    "mix_shift": {
        "description": "Tenant mix-shift — no per-segment change, aggregate drops from composition",
        "current_generator": None,  # Uses special full-scenario generator
    },
    "normal_variance": {
        "description": "Normal variance — small random fluctuations, no action needed (P2/none)",
        "current_generator": _generate_normal_variance_current,
    },
}


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def generate_scenario(
    scenario_name: str,
    rows_per_period: int = ROWS_PER_PERIOD,
    seed: Optional[int] = 42,
) -> List[Dict[str, Any]]:
    """Generate all rows for a single scenario.

    Args:
        scenario_name: One of the keys in SCENARIOS.
        rows_per_period: How many rows to generate per period (baseline/current).
        seed: Random seed for reproducibility. None for non-deterministic.

    Returns:
        List of row dicts ready to write to CSV.
    """
    if seed is not None:
        random.seed(seed)

    scenario = SCENARIOS[scenario_name]
    scenario_id = scenario_name

    # Mix-shift has its own full generator (needs different dimension
    # distributions for baseline vs current)
    if scenario_name == "mix_shift":
        return _generate_mix_shift_scenario(scenario_id, rows_per_period)

    # All other scenarios: generate matching dimension combos, then
    # apply baseline generator to baseline period and scenario-specific
    # generator to current period.
    current_gen = scenario["current_generator"]
    all_rows = []

    # Generate dimension combos (same for baseline and current so they're
    # dimensionally comparable — this is important for decomposition)
    combos = _generate_dimension_combos(rows_per_period)

    # Baseline period
    for i, dims in enumerate(combos):
        all_rows.append(_generate_baseline_row(dims, i, scenario_id))

    # Current period (same dimension combos, scenario-specific metrics)
    for i, dims in enumerate(combos):
        all_rows.append(current_gen(dims, i, scenario_id))

    return all_rows


def write_csv(rows: List[Dict[str, Any]], output_path: Path) -> None:
    """Write rows to a CSV file.

    Uses csv.DictWriter with the standard column order. This ensures
    all CSVs have consistent column ordering regardless of dict key order.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def generate_all(
    output_dir: Path,
    rows_per_period: int = ROWS_PER_PERIOD,
    seed: int = 42,
) -> None:
    """Generate all 5 scenario CSVs to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, scenario_name in enumerate(SCENARIOS):
        # WHY seed + i? Each scenario gets its own deterministic seed so that
        # adding, removing, or reordering scenarios doesn't change other
        # scenarios' data. Without this, all scenarios share state from a
        # single random.seed(seed) call, creating invisible coupling.
        rows = generate_scenario(scenario_name, rows_per_period, seed=seed + i)
        output_path = output_dir / f"scenario_{scenario_name}.csv"
        write_csv(rows, output_path)
        print(f"  Generated: {output_path.name} ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic investigation data for the Search Metric Analyzer."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "investigations",
        help="Output directory for CSV files (default: data/investigations/)",
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        help="Generate only a specific scenario (default: all)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--rows-per-period",
        type=int,
        default=ROWS_PER_PERIOD,
        help=f"Rows per period per scenario (default: {ROWS_PER_PERIOD})",
    )
    args = parser.parse_args()

    if args.list:
        print("Available scenarios:")
        for name, info in SCENARIOS.items():
            print(f"  {name}: {info['description']}")
        return

    if args.scenario:
        # Generate a single scenario
        rows = generate_scenario(args.scenario, args.rows_per_period, seed=args.seed)
        output_path = args.output_dir / f"scenario_{args.scenario}.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(rows, output_path)
        print(f"Generated: {output_path} ({len(rows)} rows)")
    else:
        # Generate all scenarios
        print(f"Generating 5 investigation scenarios to {args.output_dir}/")
        generate_all(args.output_dir, args.rows_per_period, seed=args.seed)
        print("Done.")


if __name__ == "__main__":
    main()
