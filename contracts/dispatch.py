"""DISPATCH stage contract — the sub-agent investigation phase.

This stage dispatches sub-agents to investigate each hypothesis.
It answers: "What did we find? Does the evidence support the hypothesis?"

Key IC9 fixes:
- adjacent_observations: escape valve for unexpected findings
- rule_each_finding_has_evidence: prevents narrative-only findings
- rule_narrative_data_coherence: checks that narrative matches evidence
"""

from typing import Any, Dict, List, Optional, TypedDict


class SubAgentFinding(TypedDict, total=False):
    """A single sub-agent's investigation result.

    The evidence field must contain raw data citations, not just narrative.
    This is the IC9 fix for "narrative drift" — where the sub-agent's story
    diverges from what the data actually shows.
    """
    agent_name: str                  # Which sub-agent produced this
    hypothesis_id: str               # Links back to HypothesisBrief
    verdict: str                     # "confirmed" | "rejected" | "inconclusive"
    confidence: float                # 0.0-1.0
    evidence: List[Dict[str, Any]]   # Raw data citations — NOT just narrative
    narrative: str                   # Human-readable explanation
    adjacent_observations: List[str] # IC9 Phase 2: unexpected findings escape valve


class FindingSet(TypedDict, total=False):
    """Contract for DISPATCH → SYNTHESIZE boundary.

    Seam tier: SOFT — if validation fails (e.g., missing evidence on one
    finding), emit warning and continue. The finding is marked "low_evidence"
    so SYNTHESIZE can flag it appropriately.
    Rationale: Sub-agent failures shouldn't kill the whole investigation.
    """
    findings: List[SubAgentFinding]
    context_construction_trace: str  # IC9 Invisible Decision #3 — what context each agent got
