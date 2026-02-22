#!/usr/bin/env python3
"""Generate synthetic search session and metric aggregate CSVs for scenarios S0-S12.

Extends the original S0-S8 generator with:
- Enterprise dimensions (tenant_tier, ai_enablement, industry_vertical, connector_type)
- Period column (baseline vs current) for WoW comparison
- 4 new Enterprise-specific scenarios (S9-S12)

Stdlib-only implementation.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import random
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Global baselines — these are the "healthy" reference values for all metrics.
# They represent what a typical Enterprise Search deployment looks like
# when nothing is broken.
# ---------------------------------------------------------------------------

BASELINE = {
    "click_quality_mean": 0.280,
    "ai_trigger_rate": 0.220,
    "ai_success_rate": 0.620,
    "p3_click_share": 0.270,
    "mean_clicked_rank": 2.6,
    "exploratory_share": 0.50,
}

# Baseline expected Search Quality Success from canonical formula using baseline rates.
# Search Quality Success = max(click_component, ai_component)
# At the population level: Search Quality Success ~ Click Quality + (trigger * success) * (1 - Click Quality)
BASELINE_QSR = BASELINE["click_quality_mean"] + (
    BASELINE["ai_trigger_rate"] * BASELINE["ai_success_rate"]
) * (1 - BASELINE["click_quality_mean"])

# ---------------------------------------------------------------------------
# Enterprise dimension distributions
# These define how traffic is distributed across Enterprise-specific segments.
# Values come from metric_definitions.yaml baseline_by_segment.
# ---------------------------------------------------------------------------

# tenant_tier: determines quality of search index (more connectors = better results)
TENANT_TIER_DIST = {
    "standard":   {"weight": 0.50, "click_quality_baseline": 0.245},
    "premium":    {"weight": 0.30, "click_quality_baseline": 0.280},
    "enterprise": {"weight": 0.20, "click_quality_baseline": 0.295},
}

# ai_enablement: whether tenant has AI answers turned on
# ai_on tenants have LOWER Click Quality because users get answers without clicking
# This is GOOD behavior, not a regression (inverse co-movement)
AI_ENABLEMENT_DIST = {
    "ai_off": {"weight": 0.60},
    "ai_on":  {"weight": 0.40, "click_quality_baseline": 0.220},
}

# industry_vertical: different industries have different search patterns
INDUSTRY_DIST = {
    "tech":       {"weight": 0.35},
    "finance":    {"weight": 0.25},
    "healthcare": {"weight": 0.20},
    "retail":     {"weight": 0.15},
    "other":      {"weight": 0.05},
}

# connector_type: source of documents in the search index
# Different connectors have different content quality and freshness
CONNECTOR_DIST = {
    "confluence":  {"weight": 0.30},
    "gdrive":      {"weight": 0.25},
    "slack":       {"weight": 0.20},
    "jira":        {"weight": 0.15},
    "sharepoint":  {"weight": 0.10},
}

# ---------------------------------------------------------------------------
# Scenario definitions S0-S12
# S0-S8: Original scenarios (generic metric movements)
# S9-S12: Enterprise-specific scenarios (dimension-dependent effects)
#
# For S0-S8, the enterprise dimensions act as background noise — the
# scenario effect is applied uniformly across all segments.
#
# For S9-S12, the scenario effect is localized to specific dimension
# values (e.g., S10 only affects confluence connector_type).
# ---------------------------------------------------------------------------

SCENARIOS: Dict[str, Dict] = {
    "S0": {
        "name": "Baseline stable",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": 0.000,
        "expected_search_quality_success_delta": 0.000,
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": False,
        "enterprise_effect": None,  # No enterprise-specific behavior
    },
    "S1": {
        "name": "Normal seasonality",
        "volume_delta_rel": 0.06,
        "exploratory_delta": 0.04,
        "p3_delta": 0.00,
        "rank_delta": 0.10,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": 0.000,
        "expected_search_quality_success_delta": 0.000,
        "seasonality": "weekly_pattern",
        "l3_marker": False,
        "ai_marker": False,
        "enterprise_effect": None,
    },
    "S2": {
        "name": "Seasonality shock",
        "volume_delta_rel": 0.18,
        "exploratory_delta": 0.12,
        "p3_delta": 0.00,
        "rank_delta": 0.20,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": -0.015,
        "expected_search_quality_success_delta": -0.010,
        "seasonality": "holiday_shock",
        "l3_marker": False,
        "ai_marker": False,
        "enterprise_effect": None,
    },
    "S3": {
        "name": "L3 3P boost benign",
        "volume_delta_rel": 0.02,
        "exploratory_delta": 0.08,
        "p3_delta": 0.08,
        "rank_delta": 0.20,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": -0.006,
        "expected_search_quality_success_delta": 0.004,
        "seasonality": "none",
        "l3_marker": True,
        "ai_marker": False,
        "enterprise_effect": None,
    },
    "S4": {
        "name": "L3 3P overboost regression",
        "volume_delta_rel": 0.01,
        "exploratory_delta": -0.05,
        "p3_delta": 0.18,
        "rank_delta": 0.80,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": -0.035,
        "expected_search_quality_success_delta": -0.022,
        "seasonality": "none",
        "l3_marker": True,
        "ai_marker": False,
        "enterprise_effect": None,
    },
    "S5": {
        "name": "AI Answer uplift with click cannibalization",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.50,
        "ai_trigger_delta": 0.12,
        "ai_success_delta": 0.10,
        "expected_click_quality_delta": -0.020,
        "expected_search_quality_success_delta": 0.006,
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": True,
        "enterprise_effect": None,
    },
    "S6": {
        "name": "AI Answer regression",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.10,
        "ai_trigger_delta": 0.10,
        "ai_success_delta": -0.25,
        "expected_click_quality_delta": 0.000,
        "expected_search_quality_success_delta": -0.030,
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": True,
        "enterprise_effect": None,
    },
    "S7": {
        "name": "Overlap seasonality + L3",
        "volume_delta_rel": 0.19,
        "exploratory_delta": 0.07,
        "p3_delta": 0.18,
        "rank_delta": 1.00,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": -0.045,
        "expected_search_quality_success_delta": -0.030,
        "seasonality": "holiday_shock",
        "l3_marker": True,
        "ai_marker": False,
        "enterprise_effect": None,
    },
    "S8": {
        "name": "Logging anomaly",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": 0.000,
        "expected_search_quality_success_delta": 0.000,
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": False,
        "enterprise_effect": None,
    },
    # -------------------------------------------------------------------
    # Enterprise-specific scenarios S9-S12
    # These test the decomposition tool's ability to detect dimension-
    # localized effects that are unique to Enterprise Search.
    # -------------------------------------------------------------------
    "S9": {
        "name": "Tenant portfolio mix-shift",
        # No per-row metric change — aggregate drops purely from composition shift.
        # Baseline: 50% standard, 30% premium, 20% enterprise
        # Current: 65% standard, 20% premium, 15% enterprise
        # Standard tier has lower Click Quality baseline (0.245 vs 0.280/0.295),
        # so shifting traffic toward standard lowers the aggregate.
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": -0.007,  # ~2-3% relative Click Quality drop from mix-shift
        "expected_search_quality_success_delta": -0.005,
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": False,
        "enterprise_effect": "mix_shift",
    },
    "S10": {
        "name": "Connector extraction quality regression (silent)",
        # Confluence connector extraction quality degrades.
        # Only confluence is affected; other connectors are stable.
        # Click Quality drops 3-4% for confluence, zero-result rate increases slightly.
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": -0.010,  # aggregate ~1% Click Quality from 30% confluence share
        "expected_search_quality_success_delta": -0.008,
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": False,
        "enterprise_effect": "connector_regression",
    },
    "S11": {
        "name": "Auth credential expiry (silent connector failure)",
        # Sharepoint connector auth expires, documents stop syncing.
        # Sharepoint zero_result_rate jumps sharply, Click Quality drops.
        # Other connectors are completely unaffected.
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": -0.005,  # small aggregate impact (10% share)
        "expected_search_quality_success_delta": -0.004,
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": False,
        "enterprise_effect": "auth_expiry",
    },
    "S12": {
        "name": "LLM provider / model migration",
        # AI answer quality changes after model swap.
        # ai_success drops ~8% for ai_on tenants.
        # AI answer trigger rate may increase slightly (new model more aggressive).
        # ai_off tenants completely unaffected.
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "ai_trigger_delta": 0.00,
        "ai_success_delta": 0.00,
        "expected_click_quality_delta": 0.000,
        "expected_search_quality_success_delta": -0.012,  # ~3% relative Search Quality Success drop from AI Answer degradation
        "seasonality": "none",
        "l3_marker": False,
        "ai_marker": True,
        "enterprise_effect": "llm_migration",
    },
}

# ---------------------------------------------------------------------------
# CSV column headers
# Enterprise dimensions and period are added to BOTH session log and metric
# aggregate outputs so decompose.py can slice by any combination.
# ---------------------------------------------------------------------------

SESSION_HEADERS = [
    "session_id",
    "query_id",
    "event_ts",
    "query_token",
    "query_class",
    "seasonality_tag",
    "ai_experience_type",
    "ai_trigger",
    "ai_success",
    "ai_engaged",
    "ranked_results_json",
    "clicked_rank",
    "clicked_doc_token",
    "clicked_connector",
    "click_ts",
    "release_id",
    "experiment_id",
    # Enterprise dimensions — added for dimensional decomposition
    "tenant_tier",
    "ai_enablement",
    "industry_vertical",
    "connector_type",
    # Period — enables baseline vs current (WoW) comparison
    "period",
    "scenario_id",
]

METRIC_HEADERS = [
    "session_id",
    "query_id",
    "metric_ts",
    "click_quality_value",
    "is_long_click",
    "click_quality_discount_weight",
    "ai_trigger",
    "ai_success",
    "search_quality_success_component_click",
    "search_quality_success_component_ai",
    "search_quality_success_value",
    "search_quality_success_dominant_component",
    "p3_click_share",
    "mean_clicked_rank",
    "clicked_flag",
    "freshness_lag_min",
    "completeness_pct",
    "join_coverage_pct",
    # Enterprise dimensions — propagated from session log for convenience
    "tenant_tier",
    "ai_enablement",
    "industry_vertical",
    "connector_type",
    # Period — propagated from session log
    "period",
    "scenario_id",
]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def discount(rank: int) -> float:
    return 1.0 / math.log2(rank + 1)


def rank_from_mean(mean_rank: float, rng: random.Random) -> int:
    sampled = int(round(rng.gauss(mean_rank, 1.2)))
    return int(clamp(sampled, 1, 10))


def estimate_discount_from_sampler(mean_rank: float, seed: int, samples: int = 4000) -> float:
    """Estimate expected discount using the same rank sampler as generation."""
    est_rng = random.Random(seed)
    vals: List[float] = []
    for _ in range(samples):
        vals.append(discount(rank_from_mean(mean_rank, est_rng)))
    return sum(vals) / len(vals)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic search validation datasets")
    parser.add_argument("--rows-per-scenario", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="data/synthetic")
    parser.add_argument("--write-templates-only", action="store_true")
    return parser.parse_args()


def derive_success_prob(target_dlctr: float, target_qsr: float, trigger_rate: float) -> float:
    if trigger_rate <= 0:
        return 0.0
    # search_quality_success = click_quality + p_ai * (1 - click_quality), where p_ai = trigger * success
    required_p_sain = (target_qsr - target_dlctr) / max(1e-9, (1 - target_dlctr))
    required_p_sain = clamp(required_p_sain, 0.0, 1.0)
    return clamp(required_p_sain / trigger_rate, 0.0, 1.0)


def scenario_markers(sid: str) -> Tuple[str, str]:
    if sid in {"S3", "S4"}:
        return "", f"exp_l3_{sid.lower()}"
    if sid == "S7":
        return "rel_l3_overlap", "exp_l3_overlap"
    if sid in {"S5", "S6"}:
        return f"rel_ai_{sid.lower()}", ""
    return "", ""


def scenario_ai_experience(sid: str, rng: random.Random) -> str:
    if sid in {"S5", "S6"}:
        return rng.choice(["BOOKMARK", "PEOPLE_ENTITY_CARD", "NLQ_ANSWER"])
    if rng.random() < 0.18:
        return rng.choice(["BOOKMARK", "PEOPLE_ENTITY_CARD", "NLQ_ANSWER"])
    return "NONE"


def build_ranked_results(sid: str, row_idx: int, p3_share: float, rng: random.Random) -> List[Dict[str, str | int]]:
    ranked: List[Dict[str, str | int]] = []
    for rank in range(1, 11):
        connector = "3P" if rng.random() < p3_share else "1P"
        ranked.append(
            {
                "rank": rank,
                "doc_token": f"{sid.lower()}_doc_{row_idx}_{rank}",
                "connector": connector,
            }
        )
    return ranked


# ---------------------------------------------------------------------------
# Enterprise dimension assignment
# ---------------------------------------------------------------------------

def weighted_choice(dist: Dict[str, Dict], rng: random.Random) -> str:
    """Pick a value from a distribution dict based on 'weight' keys.

    This is like a categorical sampler — given {"standard": {"weight": 0.5}, ...},
    it returns "standard" with 50% probability.
    """
    items = list(dist.keys())
    weights = [dist[k]["weight"] for k in items]
    # random.choices returns a list; we want a single value
    return rng.choices(items, weights=weights, k=1)[0]


def assign_enterprise_dims(
    rng: random.Random,
    tier_dist: Dict[str, Dict] | None = None,
    connector_dist: Dict[str, Dict] | None = None,
) -> Dict[str, str]:
    """Assign enterprise dimensions to a single row.

    Allows overriding tier and connector distributions for scenarios
    that shift the mix (S9) or target specific connectors (S10, S11).
    """
    effective_tier_dist = tier_dist or TENANT_TIER_DIST
    effective_connector_dist = connector_dist or CONNECTOR_DIST

    return {
        "tenant_tier": weighted_choice(effective_tier_dist, rng),
        "ai_enablement": weighted_choice(AI_ENABLEMENT_DIST, rng),
        "industry_vertical": weighted_choice(INDUSTRY_DIST, rng),
        "connector_type": weighted_choice(effective_connector_dist, rng),
    }


# ---------------------------------------------------------------------------
# Enterprise scenario-specific adjustments
# These functions modify click probability, trigger rate, etc. based on
# the enterprise dimensions assigned to a row. Only called for S9-S12.
# ---------------------------------------------------------------------------

def apply_s9_mix_shift_dims(period: str, rng: random.Random) -> Dict[str, str]:
    """S9: Change tenant tier distribution between baseline and current.

    Baseline: 50% standard, 30% premium, 20% enterprise (normal)
    Current: 65% standard, 20% premium, 15% enterprise (more standard onboarded)

    The key insight: per-segment Click Quality stays the SAME. The aggregate drops
    because the mix shifts toward the lower-performing segment.
    This is a classic Simpson's Paradox scenario.
    """
    if period == "baseline":
        # Normal distribution
        tier_dist = {
            "standard":   {"weight": 0.50},
            "premium":    {"weight": 0.30},
            "enterprise": {"weight": 0.20},
        }
    else:
        # Current: more standard-tier tenants onboarded
        tier_dist = {
            "standard":   {"weight": 0.65},
            "premium":    {"weight": 0.20},
            "enterprise": {"weight": 0.15},
        }

    return assign_enterprise_dims(rng, tier_dist=tier_dist)


def get_s9_click_prob_adjustment(tier: str) -> float:
    """S9: Return Click Quality multiplier based on tenant tier.

    Per-segment Click Quality must stay the same between baseline and current.
    Standard tier has lower Click Quality than premium/enterprise.
    """
    tier_multipliers = {
        "standard":   0.245 / BASELINE["click_quality_mean"],   # ~0.875
        "premium":    0.280 / BASELINE["click_quality_mean"],   # 1.0
        "enterprise": 0.295 / BASELINE["click_quality_mean"],   # ~1.054
    }
    return tier_multipliers.get(tier, 1.0)


def get_s10_click_prob_adjustment(connector: str, period: str) -> float:
    """S10: Confluence extraction quality degrades in current period.

    Only confluence connector is affected. Returns a multiplier on click_prob.
    Baseline: all connectors at 1.0x
    Current: confluence drops to ~0.88x (3-4% Click Quality drop), others stable
    """
    if period == "current" and connector == "confluence":
        return 0.88  # ~3-4% Click Quality drop for confluence
    return 1.0


def get_s11_zero_result_override(connector: str, period: str, rng: random.Random) -> bool | None:
    """S11: Sharepoint auth expiry causes zero results.

    In current period, sharepoint queries have ~40% chance of zero results
    (documents stop syncing, so many queries find nothing).
    Returns True to force zero result, False for normal, None for no override.
    """
    if period == "current" and connector == "sharepoint":
        # 40% of sharepoint queries return zero results due to auth expiry
        return rng.random() < 0.40
    return None


def get_s11_click_prob_adjustment(connector: str, period: str) -> float:
    """S11: Sharepoint Click Quality drops in current period (stale/missing results)."""
    if period == "current" and connector == "sharepoint":
        return 0.70  # significant drop for sharepoint
    return 1.0


def get_s12_ai_adjustments(ai_enablement: str, period: str) -> Tuple[float, float]:
    """S12: LLM model migration affects AI answer quality for ai_on tenants.

    Returns (trigger_rate_multiplier, success_rate_multiplier).
    ai_off tenants: no effect (1.0, 1.0)
    ai_on tenants in current: trigger slightly up (aggressive), success down ~8%
    """
    if period == "current" and ai_enablement == "ai_on":
        # New model is more aggressive at triggering but less accurate
        return (1.05, 0.92)  # +5% trigger, -8% success
    return (1.0, 1.0)


# ---------------------------------------------------------------------------
# Template writing
# ---------------------------------------------------------------------------

def write_templates(project_root: Path) -> None:
    templates_dir = project_root / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Scenario knobs template
    knobs_headers = [
        "scenario_id",
        "volume_delta_rel",
        "exploratory_query_share_delta_abs",
        "p3_click_share_delta_abs",
        "mean_clicked_rank_delta_abs",
        "ai_trigger_rate_delta_abs",
        "ai_success_rate_delta_abs",
        "expected_click_quality_delta_abs",
        "expected_click_quality_delta_rel",
        "expected_search_quality_success_delta_abs",
        "expected_search_quality_success_delta_rel",
    ]
    knobs_path = templates_dir / "scenario_knobs_template.csv"
    with knobs_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=knobs_headers)
        writer.writeheader()
        for sid, cfg in SCENARIOS.items():
            rel_dlctr = cfg["expected_click_quality_delta"] / BASELINE["click_quality_mean"] if BASELINE["click_quality_mean"] else 0.0
            rel_qsr = cfg["expected_search_quality_success_delta"] / BASELINE_QSR if BASELINE_QSR else 0.0
            writer.writerow(
                {
                    "scenario_id": sid,
                    "volume_delta_rel": cfg["volume_delta_rel"],
                    "exploratory_query_share_delta_abs": cfg["exploratory_delta"],
                    "p3_click_share_delta_abs": cfg["p3_delta"],
                    "mean_clicked_rank_delta_abs": cfg["rank_delta"],
                    "ai_trigger_rate_delta_abs": cfg["ai_trigger_delta"],
                    "ai_success_rate_delta_abs": cfg["ai_success_delta"],
                    "expected_click_quality_delta_abs": cfg["expected_click_quality_delta"],
                    "expected_click_quality_delta_rel": f"{rel_dlctr:.4f}",
                    "expected_search_quality_success_delta_abs": cfg["expected_search_quality_success_delta"],
                    "expected_search_quality_success_delta_rel": f"{rel_qsr:.4f}",
                }
            )

    # Session template — now includes enterprise dimensions and period
    session_path = templates_dir / "session_log_template.csv"
    with session_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SESSION_HEADERS)
        writer.writeheader()
        writer.writerow(
            {
                "session_id": "S0_sess_0",
                "query_id": "S0_q_0",
                "event_ts": "2026-01-05T00:00:00Z",
                "query_token": "query_tok_x",
                "query_class": "exploratory",
                "seasonality_tag": "none",
                "ai_experience_type": "NONE",
                "ai_trigger": 0,
                "ai_success": 0,
                "ai_engaged": 0,
                "ranked_results_json": "[]",
                "clicked_rank": "",
                "clicked_doc_token": "",
                "clicked_connector": "",
                "click_ts": "",
                "release_id": "",
                "experiment_id": "",
                "tenant_tier": "standard",
                "ai_enablement": "ai_off",
                "industry_vertical": "tech",
                "connector_type": "confluence",
                "period": "baseline",
                "scenario_id": "S0",
            }
        )

    # Metric aggregate template — now includes enterprise dimensions and period
    metric_path = templates_dir / "metric_aggregate_template.csv"
    with metric_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METRIC_HEADERS)
        writer.writeheader()
        writer.writerow(
            {
                "session_id": "S0_sess_0",
                "query_id": "S0_q_0",
                "metric_ts": "2026-01-05T00:00:00Z",
                "click_quality_value": "0.000000",
                "is_long_click": 0,
                "click_quality_discount_weight": "0.000000",
                "ai_trigger": 0,
                "ai_success": 0,
                "search_quality_success_component_click": "0.000000",
                "search_quality_success_component_ai": "0.000000",
                "search_quality_success_value": "0.000000",
                "search_quality_success_dominant_component": "click_quality",
                "p3_click_share": "0.000000",
                "mean_clicked_rank": "",
                "clicked_flag": 0,
                "freshness_lag_min": 30,
                "completeness_pct": "99.700",
                "join_coverage_pct": "99.300",
                "tenant_tier": "standard",
                "ai_enablement": "ai_off",
                "industry_vertical": "tech",
                "connector_type": "confluence",
                "period": "baseline",
                "scenario_id": "S0",
            }
        )


# ---------------------------------------------------------------------------
# Main data generation
# ---------------------------------------------------------------------------

def generate_scenario_rows(
    sid: str,
    cfg: Dict,
    period: str,
    rows_per_period: int,
    rng: random.Random,
    seed: int,
    start_ts: dt.datetime,
) -> List[Dict[str, str | int]]:
    """Generate session-level rows for one scenario + one period.

    This is the core row-generation loop, extracted from the original
    generate_data() to support the baseline/current period split.

    For S0-S8 (generic scenarios), enterprise dimensions are assigned
    randomly from the default distributions and the scenario effect is
    applied uniformly.

    For S9-S12 (enterprise scenarios), enterprise dimensions may be
    assigned with scenario-specific distributions, and the scenario
    effect is localized to specific dimension values.
    """
    enterprise_effect = cfg.get("enterprise_effect")

    # Compute scenario-level metric targets from baseline + deltas.
    # For the "baseline" period, we use the base BASELINE values (no delta).
    # For the "current" period, we apply the scenario's delta.
    if period == "baseline":
        target_dlctr = BASELINE["click_quality_mean"]
        target_qsr = BASELINE_QSR
        trigger_rate = BASELINE["ai_trigger_rate"]
        p3_share = BASELINE["p3_click_share"]
        mean_rank_target = BASELINE["mean_clicked_rank"]
        exploratory_share = BASELINE["exploratory_share"]
    else:
        target_dlctr = clamp(BASELINE["click_quality_mean"] + float(cfg["expected_click_quality_delta"]), 0.01, 0.95)
        target_qsr = clamp(BASELINE_QSR + float(cfg["expected_search_quality_success_delta"]), 0.01, 0.99)
        trigger_rate = clamp(
            BASELINE["ai_trigger_rate"] + float(cfg["ai_trigger_delta"]), 0.0, 1.0
        )
        p3_share = clamp(BASELINE["p3_click_share"] + float(cfg["p3_delta"]), 0.02, 0.98)
        mean_rank_target = clamp(BASELINE["mean_clicked_rank"] + float(cfg["rank_delta"]), 1.0, 10.0)
        exploratory_share = clamp(
            BASELINE["exploratory_share"] + float(cfg["exploratory_delta"]), 0.05, 0.95
        )

    success_prob = derive_success_prob(target_dlctr, target_qsr, trigger_rate)

    expected_weight = estimate_discount_from_sampler(
        mean_rank_target, seed + (sum(ord(c) for c in sid) * 17)
    )
    click_prob_base = clamp(target_dlctr / max(1e-9, expected_weight), 0.01, 0.98)

    release_id, experiment_id = scenario_markers(sid)

    rows: List[Dict[str, str | int]] = []
    for i in range(rows_per_period):
        # Spread timestamps over 14 days for periodicity inspection.
        # Baseline period: days 1-14, Current period: days 15-28
        day_offset = 0 if period == "baseline" else 14
        minute_offset = i % (14 * 24 * 60)
        event_ts = start_ts + dt.timedelta(days=day_offset, minutes=minute_offset, seconds=i % 41)

        # Use a unique row index that doesn't collide between periods
        global_idx = i if period == "baseline" else i + rows_per_period

        # -- Assign enterprise dimensions --
        # S9 uses period-specific tier distributions for mix-shift
        if enterprise_effect == "mix_shift":
            dims = apply_s9_mix_shift_dims(period, rng)
        else:
            dims = assign_enterprise_dims(rng)

        # -- Seasonality --
        seasonality_tag = str(cfg["seasonality"])
        row_click_prob = click_prob_base

        if sid == "S1":
            dow = event_ts.weekday()
            periodic = math.sin((2 * math.pi * dow) / 7.0)
            row_click_prob = clamp(click_prob_base * (1.0 + 0.18 * periodic), 0.01, 0.99)

        if sid == "S2":
            if i < int(rows_per_period * 0.30):
                seasonality_tag = "holiday_shock"
        if sid == "S7":
            seasonality_tag = "holiday_shock"

        # -- Query class --
        query_class = "exploratory" if rng.random() < exploratory_share else "navigational"
        if sid == "S4" and rng.random() < 0.15:
            query_class = "navigational"

        # -- AI trigger/success --
        row_trigger_rate = trigger_rate
        row_success_prob = success_prob

        # S12: LLM migration adjusts AI rates for ai_on tenants
        if enterprise_effect == "llm_migration":
            trigger_mult, success_mult = get_s12_ai_adjustments(
                dims["ai_enablement"], period
            )
            row_trigger_rate = clamp(trigger_rate * trigger_mult, 0.0, 1.0)
            row_success_prob = clamp(success_prob * success_mult, 0.0, 1.0)

        ai_trigger = 1 if rng.random() < row_trigger_rate else 0
        if ai_trigger:
            ai_experience_type = rng.choice(["BOOKMARK", "PEOPLE_ENTITY_CARD", "NLQ_ANSWER"])
        else:
            ai_experience_type = "NONE"
        ai_success = 1 if (ai_trigger and rng.random() < row_success_prob) else 0
        ai_engaged = ai_success

        # -- Ranked results --
        ranked_results = build_ranked_results(sid, global_idx, p3_share, rng)

        # -- Click probability adjustments for enterprise scenarios --

        # S9: Per-segment Click Quality varies by tier but stays constant across periods
        if enterprise_effect == "mix_shift":
            row_click_prob = click_prob_base * get_s9_click_prob_adjustment(dims["tenant_tier"])

        # S10: Confluence extraction quality regression
        if enterprise_effect == "connector_regression":
            row_click_prob = click_prob_base * get_s10_click_prob_adjustment(
                dims["connector_type"], period
            )

        # S11: Sharepoint auth expiry
        if enterprise_effect == "auth_expiry":
            row_click_prob = click_prob_base * get_s11_click_prob_adjustment(
                dims["connector_type"], period
            )

        # -- Check for forced zero-result (S11 sharepoint auth expiry) --
        force_zero_result = None
        if enterprise_effect == "auth_expiry":
            force_zero_result = get_s11_zero_result_override(
                dims["connector_type"], period, rng
            )

        # -- Click generation --
        clicked = False
        if force_zero_result is True:
            # Forced zero result — no click possible
            clicked = False
        elif force_zero_result is False or force_zero_result is None:
            clicked = rng.random() < row_click_prob

        clicked_rank = ""
        clicked_doc_token = ""
        clicked_connector = ""
        click_ts_str = ""
        if clicked:
            rank = rank_from_mean(mean_rank_target, rng)
            clicked_rank = rank
            chosen = ranked_results[rank - 1]
            clicked_doc_token = str(chosen["doc_token"])
            clicked_connector = str(chosen["connector"])
            click_ts_str = (event_ts + dt.timedelta(seconds=rng.randint(2, 8))).isoformat().replace("+00:00", "Z")

        rows.append(
            {
                "session_id": f"{sid}_sess_{global_idx}",
                "query_id": f"{sid}_q_{global_idx}",
                "event_ts": event_ts.isoformat().replace("+00:00", "Z"),
                "query_token": f"qt_{sid.lower()}_{global_idx}",
                "query_class": query_class,
                "seasonality_tag": seasonality_tag,
                "ai_experience_type": ai_experience_type,
                "ai_trigger": ai_trigger,
                "ai_success": ai_success,
                "ai_engaged": ai_engaged,
                "ranked_results_json": json.dumps(ranked_results, separators=(",", ":")),
                "clicked_rank": clicked_rank,
                "clicked_doc_token": clicked_doc_token,
                "clicked_connector": clicked_connector,
                "click_ts": click_ts_str,
                "release_id": release_id,
                "experiment_id": experiment_id,
                # Enterprise dimensions
                "tenant_tier": dims["tenant_tier"],
                "ai_enablement": dims["ai_enablement"],
                "industry_vertical": dims["industry_vertical"],
                "connector_type": dims["connector_type"],
                # Period
                "period": period,
                "scenario_id": sid,
            }
        )

    return rows


def generate_data(project_root: Path, output_dir: Path, rows_per_scenario: int, seed: int) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_ts = dt.datetime(2026, 1, 5, 0, 0, 0, tzinfo=dt.timezone.utc)
    session_rows: List[Dict[str, str | int]] = []

    # Each scenario gets rows_per_scenario total rows, split evenly
    # between baseline and current periods (half each).
    rows_per_period = rows_per_scenario // 2

    for sid in sorted(SCENARIOS.keys(), key=lambda s: int(s[1:])):
        cfg = SCENARIOS[sid]

        # Generate baseline period rows (the "before" state)
        baseline_rows = generate_scenario_rows(
            sid, cfg, "baseline", rows_per_period, rng, seed, start_ts
        )
        session_rows.extend(baseline_rows)

        # Generate current period rows (the "after" state with changes)
        current_rows = generate_scenario_rows(
            sid, cfg, "current", rows_per_period, rng, seed, start_ts
        )
        session_rows.extend(current_rows)

    # Compute metric rows with long-click from next query in session sequence.
    # (Each generated session usually has one query; rule still applies.)
    sorted_rows = sorted(session_rows, key=lambda r: (r["session_id"], r["event_ts"], r["query_id"]))
    metric_rows: List[Dict[str, str | int | float]] = []
    for idx, row in enumerate(sorted_rows):
        next_event_ts = None
        if idx + 1 < len(sorted_rows) and sorted_rows[idx + 1]["session_id"] == row["session_id"]:
            next_event_ts = dt.datetime.fromisoformat(str(sorted_rows[idx + 1]["event_ts"]).replace("Z", "+00:00"))

        clicked_rank_raw = row["clicked_rank"]
        clicked_rank = int(clicked_rank_raw) if str(clicked_rank_raw).strip() else None
        clicked_flag = 1 if clicked_rank is not None else 0

        is_long_click = 0
        anomaly = 0
        dlctr_discount = 0.0

        click_ts_raw = str(row["click_ts"])
        click_ts = (
            dt.datetime.fromisoformat(click_ts_raw.replace("Z", "+00:00"))
            if click_ts_raw.strip()
            else None
        )

        if clicked_rank is not None:
            if next_event_ts is None:
                is_long_click = 1
            elif click_ts is None:
                is_long_click = 0
            elif next_event_ts <= click_ts:
                anomaly = 1
                is_long_click = 0
            else:
                delta_sec = (next_event_ts - click_ts).total_seconds()
                is_long_click = 1 if delta_sec >= 40 else 0

            if is_long_click:
                dlctr_discount = discount(clicked_rank)

        click_quality_value = dlctr_discount
        ai_trigger = int(row["ai_trigger"])
        ai_success = int(row["ai_success"])
        search_quality_success_component_click = click_quality_value
        search_quality_success_component_ai = float(ai_success * ai_trigger)
        search_quality_success_value = max(search_quality_success_component_click, search_quality_success_component_ai)
        search_quality_success_dominant = "click_quality" if search_quality_success_component_click >= search_quality_success_component_ai else "ai_answer"

        sid = str(row["scenario_id"])
        if sid == "S8":
            freshness = 240
            completeness = 96.5
            join_coverage = 96.0
        else:
            freshness = 30
            completeness = 99.7
            join_coverage = 99.3
            if anomaly:
                completeness = 98.9

        p3_click_share = 1.0 if (clicked_flag and row["clicked_connector"] == "3P") else 0.0
        mean_clicked_rank = clicked_rank if clicked_flag else ""

        metric_rows.append(
            {
                "session_id": row["session_id"],
                "query_id": row["query_id"],
                "metric_ts": row["event_ts"],
                "click_quality_value": f"{click_quality_value:.6f}",
                "is_long_click": is_long_click,
                "click_quality_discount_weight": f"{dlctr_discount:.6f}",
                "ai_trigger": ai_trigger,
                "ai_success": ai_success,
                "search_quality_success_component_click": f"{search_quality_success_component_click:.6f}",
                "search_quality_success_component_ai": f"{search_quality_success_component_ai:.6f}",
                "search_quality_success_value": f"{search_quality_success_value:.6f}",
                "search_quality_success_dominant_component": search_quality_success_dominant,
                "p3_click_share": f"{p3_click_share:.6f}",
                "mean_clicked_rank": mean_clicked_rank,
                "clicked_flag": clicked_flag,
                "freshness_lag_min": freshness,
                "completeness_pct": f"{completeness:.3f}",
                "join_coverage_pct": f"{join_coverage:.3f}",
                # Propagate enterprise dimensions from session row
                "tenant_tier": row["tenant_tier"],
                "ai_enablement": row["ai_enablement"],
                "industry_vertical": row["industry_vertical"],
                "connector_type": row["connector_type"],
                # Propagate period
                "period": row["period"],
                "scenario_id": sid,
            }
        )

    session_path = output_dir / "synthetic_search_session_log.csv"
    with session_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SESSION_HEADERS)
        writer.writeheader()
        writer.writerows(session_rows)

    metric_path = output_dir / "synthetic_metric_aggregate.csv"
    with metric_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METRIC_HEADERS)
        writer.writeheader()
        writer.writerows(metric_rows)

    summary = {
        "seed": seed,
        "rows_per_scenario": rows_per_scenario,
        "scenario_count": len(SCENARIOS),
        "session_rows": len(session_rows),
        "metric_rows": len(metric_rows),
        "baseline_search_quality_success_reference": round(BASELINE_QSR, 6),
    }
    with (output_dir / "generation_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent

    write_templates(project_root)
    if args.write_templates_only:
        return

    output_dir = (project_root / args.output_dir).resolve()
    generate_data(project_root, output_dir, args.rows_per_scenario, args.seed)


if __name__ == "__main__":
    main()
