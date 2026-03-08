"""Stage contracts for Search Metric Analyzer v2.

Each stage boundary (UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE) has a
TypedDict contract that defines the required fields and a set of business rules
that enforce domain-specific invariants.

Design principle: Contracts enforce SUBSTANCE, not just FORM.
- Form: "does the field exist?" (TypedDict handles this)
- Substance: "is the value correct given search domain rules?" (business rules handle this)

Key domain rules encoded here:
- AI-click inverse co-movement is expected, not anomalous (Amendment 2)
- Mix-shift must be surfaced when detected (Amendment 3)
- P0 severity requires proportional language (IC9 Phase 2)
"""

from contracts.understand import UnderstandResult, MixShiftResult
from contracts.hypothesize import HypothesisBrief, HypothesisSet, ExcludedHypothesis
from contracts.dispatch import SubAgentFinding, FindingSet
from contracts.synthesize import SynthesisReport, ActionItem
from contracts.seam_validator import validate_seam, SeamViolation
