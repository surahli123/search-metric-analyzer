"""Search-specific quality gate rules for the seam validator.

These rules encode Enterprise Search domain invariants that are NOT applicable
to other domains (e.g., data_analysis for KDD). They were extracted from
contracts/seam_validator.py during Wave 7A.2 domain extraction.

RULES IN THIS FILE:
1. rule_question_brief_valid — validates search-specific question types
2. rule_hypotheses_consistent_with_co_movement — AI adoption trap detection
3. rule_mix_shift_considered_when_detected — mix-shift investigation requirement
4. rule_effect_size_proportionality — P0 severity language consistency

WHY THESE ARE DOMAIN-SPECIFIC:
- rule_question_brief_valid: VALID_QUESTION_TYPES is search-specific
  (sev, experiment, trend, deep_dive, system_understanding, adhoc)
- rule_hypotheses_consistent_with_co_movement: AI adoption trap is a search metric
  concept (CQ↓ + AI↑ = positive signal, not regression)
- rule_mix_shift_considered_when_detected: mix-shift is common in Enterprise Search
  (tenant tier shifts cause 30-40% of metric movements)
- rule_effect_size_proportionality: P0/P1/P2 severity classification is from the
  search metric alert threshold system

BACKWARD COMPATIBILITY:
These rules are also imported by contracts/seam_validator.py and included
in STAGE_RULES — so all existing tests continue to pass. When a non-search
domain (data_analysis) runs, it provides its OWN rules via get_quality_rules()
and the orchestrator will use those instead of the search defaults.

All functions follow the same signature:
    rule_fn(result: dict, **kwargs) -> Optional[str]
    Returns None if the rule passes, or a violation string if it fails.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


# =============================================================================
# Search-specific question types
# =============================================================================

VALID_QUESTION_TYPES = {
    "sev",                    # Severity incident (metric dropped significantly)
    "experiment",             # A/B test analysis
    "trend",                  # Gradual metric movement over time
    "deep_dive",              # In-depth investigation of a specific area
    "system_understanding",   # How does X work? (knowledge lookup)
    "adhoc",                  # Freeform question that doesn't fit other types
}


# =============================================================================
# QUESTION_PARSE rule
# =============================================================================

def rule_question_brief_valid(result: Dict, **kwargs) -> Optional[str]:
    """HARD CHECK on question_type validity; SOFT warning on missing metric hints.

    The question parser produces a QuestionBrief that routes investigations
    to the right mode (Simple/Medium/Complex). If the question_type is invalid,
    mode selection will route incorrectly — garbage in, garbage out (HARD).

    WHY DOMAIN-SPECIFIC: The valid question types (sev, experiment, trend, etc.)
    are specific to search metric analysis. A data analysis domain would have
    different types (e.g., aggregation, comparison, correlation).
    """
    question_type = result.get("question_type")
    if question_type not in VALID_QUESTION_TYPES:
        return (
            f"question_type '{question_type}' is invalid — "
            f"must be one of {sorted(VALID_QUESTION_TYPES)}. "
            f"Re-parse the question with a valid classification."
        )
    return None


# =============================================================================
# HYPOTHESIZE rules
# =============================================================================

def rule_hypotheses_consistent_with_co_movement(result: Dict, **kwargs) -> Optional[str]:
    """Prevent flagging expected AI-driven CQ drops as anomalous.

    If UNDERSTAND identified 'ai_adoption_expected' co-movement, no hypothesis
    should have archetype 'click_quality_degradation' unless explicitly marked
    as contrarian (is_contrarian=True).

    This is the signature domain rule of the Search Metric Analyzer — the
    "AI adoption trap" where AI answers work well → users click less →
    CQ drops → team panics → but it's actually a POSITIVE signal.

    The understand_result is passed via kwargs so this rule can cross-reference
    the UNDERSTAND output.
    """
    understand = kwargs.get("understand_result", {})
    co_movement = understand.get("co_movement_pattern", {})
    pattern = co_movement.get("pattern_name", "")

    if pattern == "ai_adoption_expected":
        for h in result.get("hypotheses", []):
            if (h.get("archetype") == "click_quality_degradation"
                    and not h.get("is_contrarian")):
                return (
                    f"Hypothesis '{h.get('hypothesis_id', 'unknown')}' has archetype "
                    f"'click_quality_degradation' but co-movement pattern is "
                    f"'ai_adoption_expected' (AI answers working → fewer clicks → "
                    f"expected CQ drop). Must be marked is_contrarian=True or removed."
                )
    return None


def rule_mix_shift_considered_when_detected(result: Dict, **kwargs) -> Optional[str]:
    """If mix-shift was detected, at least one hypothesis must address it.

    Mix-shift causes 30-40% of Enterprise metric movements. If UNDERSTAND
    detected significant mix-shift (contribution > 25%), HYPOTHESIZE must
    include at least one mix-shift hypothesis.
    """
    understand = kwargs.get("understand_result", {})
    mix_shift = understand.get("mix_shift_result", {})

    if mix_shift and mix_shift.get("detected") and mix_shift.get("contribution_pct", 0) > 0.25:
        hyps = result.get("hypotheses", [])
        has_mix_shift_hyp = any(
            h.get("archetype") in ("mix_shift", "segment_mix_shift")
            for h in hyps
        )
        if not has_mix_shift_hyp:
            pct = mix_shift.get("contribution_pct", 0)
            return (
                f"Mix-shift explains {pct:.0%} of metric movement but no "
                f"mix-shift hypothesis was generated. Mix-shift causes 30-40% "
                f"of Enterprise metric movements — this must be investigated. "
                f"Add a hypothesis with archetype='mix_shift' or 'segment_mix_shift' to the hypothesis set."
            )
    return None


# =============================================================================
# SYNTHESIZE rule
# =============================================================================

def rule_effect_size_proportionality(result: Dict, **kwargs) -> Optional[str]:
    """P0 severity must use proportional language.

    If severity is P0 (critical incident), the report should not contain
    minimizing language like "minor", "slight", "small". This catches
    the case where the LLM hedges on a genuinely severe issue.

    WHY DOMAIN-SPECIFIC: The P0/P1/P2 severity system is part of the search
    metric alert threshold system. Other domains may not use this classification.
    """
    if result.get("severity") == "P0":
        minimizing_words = {"minor", "slight", "small", "marginal", "negligible", "trivial"}
        for field in ["tldr", "root_cause"]:
            text = result.get(field, "").lower()
            found = [w for w in minimizing_words if re.search(r'\b' + w + r'\b', text)]
            if found:
                return (
                    f"P0 severity but '{field}' uses minimizing language: "
                    f"{', '.join(found)}. A P0 is a critical incident — "
                    f"language must match severity to avoid downplaying impact. "
                    f"Replace minimizing words (minor/slight/small) with proportional language (significant/substantial/critical)."
                )
    return None


# =============================================================================
# Rule registry — for SearchMetricsDomain.get_quality_rules()
# =============================================================================

# Each entry: {name, stage, check} — the format expected by the domain interface.
SEARCH_METRIC_RULES = [
    {
        "name": "question_brief_valid",
        "stage": "QUESTION_PARSE",
        "check": rule_question_brief_valid,
    },
    {
        "name": "hypotheses_consistent_with_co_movement",
        "stage": "HYPOTHESIZE",
        "check": rule_hypotheses_consistent_with_co_movement,
    },
    {
        "name": "mix_shift_considered_when_detected",
        "stage": "HYPOTHESIZE",
        "check": rule_mix_shift_considered_when_detected,
    },
    {
        "name": "effect_size_proportionality",
        "stage": "SYNTHESIZE",
        "check": rule_effect_size_proportionality,
    },
]
