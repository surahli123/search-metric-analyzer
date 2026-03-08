"""HYPOTHESIZE stage contract — the hypothesis generation phase.

This stage is LLM-driven but constrained by the UNDERSTAND output.
It answers: "What could explain this movement? What should we investigate?"

Key IC9 fixes:
- source field: tracks whether hypothesis is data_driven, playbook, or novel
- expected_magnitude: prevents false alarms by setting investigation expectations
- is_contrarian: at least one hypothesis must challenge the obvious explanation

Key Amendment:
- rule_hypotheses_consistent_with_co_movement: prevents flagging expected
  AI-driven CQ drops as anomalous (the "AI adoption trap")
"""

from typing import Dict, List, Optional, TypedDict


class HypothesisBrief(TypedDict, total=False):
    """A single hypothesis to investigate.

    The confirms_if and rejects_if fields are critical: they define what
    evidence would support or refute this hypothesis, BEFORE investigation
    begins. This prevents post-hoc rationalization.
    """
    hypothesis_id: str               # Unique ID for tracking through dispatch
    archetype: str                   # e.g. "ranking_regression", "mix_shift", "ai_adoption"
    priority: int                    # 1 = highest priority to investigate
    confirms_if: List[str]           # Non-empty required — what evidence confirms this
    rejects_if: List[str]            # What evidence would refute this
    expected_magnitude: str          # IC9 Phase 2 — "CQ drop of 2-4% expected if..."
    source: str                      # "data_driven" | "playbook" | "novel"
    is_contrarian: bool              # True if this challenges the obvious explanation


class ExcludedHypothesis(TypedDict):
    """A hypothesis that was considered but excluded.

    IC9 Invisible Decision #2 (hypothesis_inclusion): we trace WHAT was
    excluded and WHY, so that auditors can verify nothing important was dropped.
    """
    archetype: str
    reason: str                      # Why it was excluded
    score: Optional[float]           # Match score if from co-movement matching


class HypothesisSet(TypedDict, total=False):
    """Contract for HYPOTHESIZE → DISPATCH boundary.

    Seam tier: SOFT — if validation fails, emit warning and continue
    with whatever hypotheses exist.
    Rationale: A DS debugging a P0 needs something. 2 hypotheses with
    a warning is better than nothing.
    """
    hypotheses: List[HypothesisBrief]    # >= 3 required at seam
    exclusions: List[ExcludedHypothesis]  # What was excluded + why (Invisible Decision #2)
    investigation_context: str           # User question + movement significance for sub-agents
