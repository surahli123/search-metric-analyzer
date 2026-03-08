# IC9 Architectural Review Rubric — Search Metric Analyzer v2.0

## Domain Context

This rubric evaluates an architectural redesign plan for a **Search Metric Debugging Agent** — a system that diagnoses why enterprise search metrics (Click Quality, Search Quality Success, AI trigger/success rates) moved unexpectedly. The system operates in a 4-stage pipeline (UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE) and was audited at IC9 level, revealing an inverted control architecture where enforcement was strongest at the lowest-stakes stage.

**Reviewers must understand:**
- Enterprise search metric co-movement (AI adoption → CQ drops = expected, not alarming)
- Mix-shift as a dominant driver (~30-40% of metric movements)
- The difference between deterministic tools (anomaly detection, decomposition) and LLM-generated analysis (hypothesis generation, synthesis)
- Why SYNTHESIZE is the highest-stakes stage (it's what stakeholders read and act on)

## Target Ranges

| Dimension | Target Min | Target Max | Weight | Description |
|-----------|-----------|-----------|--------|-------------|
| IC9 Coverage | 7 | 10 | 0.20 | Does the plan address the specific IC9 audit findings? Are the 4 Invisible Decisions properly traced? Are Phase 1 (immediate) vs Phase 2 (next sprint) items correctly prioritized? Any IC9 findings silently dropped? |
| Search Domain Correctness | 7 | 10 | 0.20 | Do the contracts and trace schemas accurately model search metric concepts? Is the metric co-movement logic preserved? Does the architecture handle AI-click inverse relationships, mix-shift decomposition, and connector-specific patterns correctly? |
| Architecture Soundness | 6 | 9 | 0.20 | Is the dual-mode architecture (skill + orchestrator) well-designed? Are seam boundaries at the right places? Is the trace system appropriately lightweight vs. comprehensive? Are there hidden coupling risks between modes? |
| Feasibility & Scope Risk | 6 | 9 | 0.15 | Is the scope realistic for implementation? Are there hidden dependencies or integration risks? Does the plan account for the existing 571-test suite and 5-scenario eval? Is the rename risk (tools/ → core/) properly mitigated? |
| Failure Mode Coverage | 6 | 9 | 0.15 | Does the plan address failure modes in the metric debugging pipeline? What happens when seam validation fails mid-investigation? How does the system handle ambiguous metrics, conflicting sub-agent findings, or novel patterns not in the playbook? |
| Traceability & Auditability | 7 | 10 | 0.10 | Will the trace system actually help humans audit investigations and agents reason about prior stages? Is the dual-audience design (human_summary + agent_context) well-thought-out? Can a DS reviewing a trace reconstruct why the system reached its conclusion? |

**Weights sum to 1.0.**

## Scoring Instructions

- Score each dimension on a **1-10 scale** (1 = completely inadequate, 10 = exceptional)
- Provide a **1-2 sentence justification** for every score — no naked numbers
- Be honest — do not inflate scores to avoid conflict or to reach targets faster
- A score of 5 means "meets bare minimum" — most professional work should land 6-8
- Reserve 9-10 for genuinely exceptional work that goes beyond expectations
- **Search domain specificity is required.** Generic architecture feedback without referencing search metrics, co-movement patterns, or investigation workflows will be scored as insufficient regardless of how polished it sounds.

## Calibration Thresholds

- **GREEN** — Score is within [Target Min, Target Max] → calibrated
- **YELLOW** — Score is within +/-1 of the range → borderline, may pass
- **RED** — Score is outside the range by more than 1 → needs iteration

A reviewer is **calibrated** when they have zero RED scores and at most one YELLOW.

## Reviewer-Specific Guidance

### DS Lead
Focus on: IC9 Coverage, Search Domain Correctness, Traceability. Ask whether the contracts enforce the right statistical properties (e.g., does `expected_magnitude` actually prevent false alarms? Does `rule_narrative_data_coherence` have teeth or is it a rubber stamp?). Challenge whether the trace captures enough for reproducibility.

### PM Lead
Focus on: Feasibility & Scope Risk, IC9 Coverage, Architecture Soundness. Push on whether this scope is realistic. Question the dual-mode design — does it add value or complexity? Are the deferred items truly safe to defer? What's the cost of being wrong about scope?

### Principal AI Engineer
Focus on: Architecture Soundness, Failure Mode Coverage, Traceability. Challenge the seam boundaries — are they at the right granularity? What happens when a seam validation fails at HYPOTHESIZE — does the whole pipeline halt, degrade gracefully, or silently continue? Push on whether the trace system will survive production load and context window limits.
