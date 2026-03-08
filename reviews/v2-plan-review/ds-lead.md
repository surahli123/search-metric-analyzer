### DS Lead Review

**Overall Assessment:** This plan is architecturally coherent and directly addresses the IC9 audit's most damning finding — the inverted control architecture. The trace system and stage contracts are the right structural response. However, the plan is stronger on *where* to put enforcement than on *what* the enforcement actually checks. Several "business rules" are named but left undefined, and the statistical properties they should enforce are unspecified. The plan also underinvests in how the trace system enables reproducibility — the hardest problem in LLM-driven diagnostic pipelines.

#### Scores

| Dimension | Score | Justification |
|-----------|-------|---------------|
| IC9 Coverage | 8/10 | All 4 Invisible Decisions are explicitly mapped to trace spans. Phase 1 vs Phase 2 prioritization is clear. The IC9 fix mapping table (Step 7) is thorough. Deferred items are identified. Minor gap: the "Memory Time Bomb" deferral is acknowledged but the plan doesn't address how trace accumulation interacts with context window limits during long investigations. |
| Search Domain Correctness | 6/10 | The contracts reference the right metric names (CQ, SQS, AI trigger/success) and the co-movement logic is preserved via `match_co_movement_pattern`. But the contracts themselves are structurally generic — `UnderstandResult` has a `co_movement_pattern` field but no contract rule validates that AI-click inverse relationships are interpreted correctly. The `expected_magnitude` field is required but there is zero specification of how magnitude is estimated or validated. Mix-shift decomposition output is not explicitly modeled in any contract. |
| Architecture Soundness | 7/10 | Dual-mode design is reasonable — shared core with two orchestration layers. The seam boundaries at stage transitions are the right granularity. The optional `trace` parameter for backwards compatibility is pragmatic. Concern: Mode A (skill file) runs seam validation via subprocess, which introduces a failure mode where the skill file could silently skip the subprocess call without detection. The two modes may drift over time since they don't share orchestration code. |
| Feasibility & Scope Risk | 7/10 | The execution order is well-sequenced to minimize blast radius (new code first, renames last). The 571-test suite provides a safety net. However, the plan casually states "no logic changes" to core tools while adding a trace parameter to every function signature — this is a larger surface area change than acknowledged. Every test that mocks or patches these functions will need updating. |
| Failure Mode Coverage | 6/10 | The plan addresses structural failure modes (missing sections, missing evidence) but not diagnostic failure modes. What happens when `rule_narrative_data_coherence` detects an inconsistency — does the pipeline halt, retry, or flag-and-continue? What happens when `match_co_movement_pattern` returns a low-confidence match and the contrarian hypothesis rule forces a contrarian that is pure noise? No specification of degradation behavior. |
| Traceability & Auditability | 7/10 | The dual-audience design (`human_summary` + `agent_context`) is a genuinely good idea. The trace captures decision points and alternatives considered. However, the plan doesn't specify what goes into `alternatives_considered` for LLM-generated spans — who populates this, the LLM itself? If so, this is self-reported provenance, which is unreliable. For deterministic spans it works; for LLM spans it's theater unless validated. |

#### Detailed Feedback

**IC9 Coverage (8/10)**

The IC9 mapping table is the strongest part of this plan. Every Phase 1 item has a concrete implementation location. The `narrative_selection` span at SYNTHESIZE directly addresses the highest-stakes Invisible Decision. Two concerns:

- The plan maps `hypothesis_inclusion` to "HYPOTHESIZE stage (LLM-generated span)" — but this is exactly the kind of decision that benefits from code enforcement, not just tracing. The `exclusions` field in `HypothesisSet` is a good start, but the plan doesn't specify who populates it. If the LLM decides which hypotheses to exclude and also writes the exclusion rationale, you have a fox-guarding-henhouse problem. This needs a deterministic check: does the exclusion list include all archetypes from `match_co_movement_pattern` that scored above some threshold? Otherwise hypothesis suppression is invisible even with the trace.

- The deferral of "hypothesis re-generation loop" is reasonable for v2, but the plan should explicitly state what happens when the HYPOTHESIZE seam validation fails. Does the pipeline halt and return a "cannot diagnose" result? That's acceptable — but it should be stated.

**Search Domain Correctness (6/10)**

This is where the plan is weakest from a DS perspective. The contracts are structurally sound but semantically thin.

1. **`expected_magnitude` is required but undefined.** The plan says this field prevents false alarms, but doesn't specify how magnitude is estimated. Is it derived from the z-score in `check_against_baseline`? From the `weekly_std` in `metric_definitions.yaml`? From the decomposition's `explained_pct`? Without this, `expected_magnitude` is a free-text field the LLM fills with whatever sounds reasonable. This needs to change because an unvalidated magnitude field gives false confidence — reviewers see the field is "required" and assume it's checked, but it's not.

2. **Mix-shift is a first-class diagnostic pattern but has no first-class contract representation.** The existing `decompose.py` outputs mix-shift contribution percentages. The `UnderstandResult` contract has `step_change` and `co_movement_pattern` but no `mix_shift_result`. Given that mix-shift causes 30-40% of metric movements, this is a significant omission. The HYPOTHESIZE stage needs to know whether mix-shift was detected to generate appropriate hypotheses.

3. **Co-movement validation is not enforced.** The `co_movement_pattern` field in `UnderstandResult` captures the pattern match, but no business rule validates that the interpretation is correct. Example: if CQ drops and AI trigger rises, the system should flag this as expected inverse co-movement — but there's no rule in `UNDERSTAND_RULES` that checks whether the `metric_direction` is consistent with the matched co-movement pattern. The current `rule_metric_direction_set` only checks the field is non-empty.

4. **`rule_narrative_data_coherence` is named but not specified.** What does "numbers in narrative plausible vs evidence" mean concretely? Is it checking that a percentage cited in the narrative appears (within some tolerance) in the evidence data? Is it checking sign consistency (narrative says "dropped" but evidence shows increase)? Without specification, this is either a rubber stamp or an over-sensitive blocker depending on who implements it.

**Architecture Soundness (7/10)**

The architecture is clean on paper. Two structural risks:

- **Mode A subprocess escape hatch.** The skill file calls `python -m contracts.seam_validator` as a subprocess. But skill files are prompt instructions — there is no mechanism to verify the subprocess was actually called. A future edit to the skill file could remove the subprocess call and the system would silently degrade to the pre-v2 unvalidated state. This is the same class of problem the IC9 audit identified: enforcement via prompt instruction, not code. Consider: could Mode A validation be moved into the core tools themselves (e.g., `core.anomaly` refuses to return results without a valid trace context)?

- **Trace parameter threading.** Adding `trace: Optional[InvestigationTrace] = None` to every core function is backwards compatible but creates a maintenance burden. Every new function must remember to accept and emit trace spans. A decorator pattern (`@traced(stage="UNDERSTAND", decision="data_quality_gate")`) would reduce boilerplate and make omission visible.

**Failure Mode Coverage (6/10)**

The plan specifies what the seam validators check but not what happens when they fail. This is a critical gap for a diagnostic pipeline.

- **Seam failure behavior is unspecified.** `validate_seam` raises `SeamViolation` on failure. In Mode B (orchestrator), this presumably halts the pipeline. But what does the user get? A stack trace? A partial report with a "pipeline halted at HYPOTHESIZE" message? For a tool used by Senior DSs debugging production incidents, the failure UX matters. A P0 metric drop that triggers a seam violation and returns nothing is worse than a degraded analysis with caveats.

- **Conflicting sub-agent findings.** The `FindingSet` contract requires each finding to have evidence, but doesn't address what happens when two sub-agents return conflicting verdicts on the same hypothesis. The SYNTHESIZE stage presumably resolves this, but without a contract rule, the LLM can silently ignore the conflict. A `rule_conflicting_verdicts_surfaced` check would catch this.

- **Novel patterns.** The `unknown_pattern` archetype fallback is acknowledged as having "no archetype-specific actions" (deferred to v2+). But the contrarian hypothesis rule (`rule_has_contrarian_hypothesis`) could interact badly with novel patterns — forcing a contrarian hypothesis when the system has no matched archetype could generate noise hypotheses.

**Traceability & Auditability (7/10)**

The trace schema is well-designed for deterministic spans. For LLM-generated spans, it's aspirational.

- **`alternatives_considered` for LLM spans.** This field is meaningful when a deterministic function evaluates multiple options (e.g., `match_co_movement_pattern` scores all patterns and picks the best). For LLM-generated decisions like `narrative_selection`, who populates `alternatives_considered`? If the LLM is asked "what alternatives did you consider?", the answer is post-hoc rationalization, not genuine provenance. Suggestion: for LLM spans, replace `alternatives_considered` with `constrained_by` — a list of contract rules and trace context that bounded the LLM's output space. This is verifiable; self-reported alternatives are not.

- **Reproducibility gap.** The trace captures inputs, outputs, and decisions — but not the model version, temperature, or system prompt used for LLM-generated stages. Two runs of the same investigation with different Claude model versions could produce different diagnoses with identical traces up to the LLM span. For a DS reproducing a past investigation, this is a blind spot.

#### Key Questions for the Author

1. **How is `expected_magnitude` actually computed?** The plan makes this a required field in `HypothesisBrief` but never specifies the estimation method. If the LLM fills it in free-form, it's a cosmetic requirement. If it's derived from `weekly_std` and baseline values in `metric_definitions.yaml`, say so — and specify the formula. Without this, you cannot validate whether the magnitude estimate prevented a false alarm or enabled one.

2. **What is the concrete implementation of `rule_narrative_data_coherence`?** This is arguably the most important business rule in the entire plan — it's the one that catches the IC9 "narrative drift" failure mode. But it's described in one line. Does it do string matching on numbers? Does it verify sign consistency? Does it check effect sizes? If this rule is a rubber stamp, the entire DISPATCH seam validation is theater. Spell out the algorithm.

3. **Why is mix-shift decomposition absent from the stage contracts?** Decompose.py already computes mix-shift contribution percentages and this is the dominant driver of Enterprise metric movements. Yet `UnderstandResult` has no `mix_shift_result` field, `HypothesisBrief` has no way to indicate a mix-shift-driven hypothesis vs. a behavioral-change hypothesis, and no business rule checks that mix-shift was considered when it should have been. Is this an intentional omission or an oversight? If intentional, what's the reasoning — because from a diagnostic accuracy standpoint, this is a significant gap.
