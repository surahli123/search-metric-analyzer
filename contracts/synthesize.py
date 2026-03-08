"""SYNTHESIZE stage contract — the final report generation phase.

This is the HIGHEST-STAKES stage. It's what stakeholders read and act on.
The IC9 audit found ~50% compliance on mandatory sections in v1 — this
contract exists to make that impossible.

Key IC9 fixes:
- All 7 mandatory sections must be non-empty
- Effect-size proportionality: P0 severity → no "minor" / "slight" language
- upgrade_condition: must state "Would upgrade to X if Y"
"""

from typing import Any, Dict, List, Optional, TypedDict


class ActionItem(TypedDict):
    """A recommended action from the investigation.

    Every action must have an owner — "someone should look at this" is not
    acceptable in a diagnostic report read by engineering leads.
    """
    action: str                      # What to do
    owner: str                       # Who should do it (role, not person)
    priority: str                    # "immediate" | "this_sprint" | "backlog"
    rationale: str                   # Why this action is recommended


class SynthesisReport(TypedDict, total=False):
    """Contract for SYNTHESIZE output — the final investigation report.

    Seam tier: RETRY (1 attempt) then SOFT.
    Rationale: SYNTHESIZE is the highest-value stage. Missing a section
    is usually fixable on retry (the LLM just needs explicit instruction).
    After 1 retry, emit with a warning banner rather than discarding
    all the expensive investigation work.
    """
    # The 7 mandatory sections (IC9 Phase 1: code-enforce mandatory sections)
    tldr: str                        # <= 3 sentences
    confidence_grade: str            # "High" | "Medium" | "Low"
    severity: str                    # "P0" | "P1" | "P2" | "normal"
    root_cause: str                  # Primary explanation
    dimensional_breakdown: str       # Which dimensions drove the movement
    hypothesis_and_evidence: str     # What was investigated and found
    validation_summary: str          # Cross-checks and coherence

    # Actions and escalation
    recommended_actions: List[ActionItem]  # Each has owner field
    upgrade_condition: str           # Required — "Would upgrade to X if Y"

    # Metadata
    investigation_id: str            # Links to trace_id
    completeness_warnings: List[str] # Populated if seam failed + degraded
