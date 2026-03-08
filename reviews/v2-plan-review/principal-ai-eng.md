### Principal AI Engineer Review

**Overall Assessment:** The plan correctly identifies the inverted control architecture as the core problem and proposes a structurally sound fix: Python-enforced seam contracts at stage boundaries with a unified trace system. The dual-mode design (skill file + orchestrator) is the right call for the adoption curve. However, the plan has meaningful gaps in failure mode handling, the trace system's production viability under context window constraints, and the seam validator's runtime behavior when things go wrong mid-investigation — which is exactly when this system matters most.

#### Scores

| Dimension | Score | Justification |
|-----------|-------|---------------|
| IC9 Coverage | 8/10 | Comprehensive mapping table covers all Phase 1 and Phase 2 items. The 4 Invisible Decisions are explicitly traced. Deferred items (hypothesis re-generation loop, memory quality) are correctly deferred with rationale. Minor gap: no discussion of how `narrative_selection` tracing actually works in practice — it's listed but the mechanism for capturing LLM narrative choices is hand-waved. |
| Search Domain Correctness | 7/10 | Contracts preserve the key metric relationships (SQS formula, co-movement patterns, mix-shift). The `UnderstandResult` correctly surfaces `co_movement_pattern` and `metric_direction`. However, the contracts do not explicitly model the AI-click inverse relationship anywhere — it lives implicitly in the co-movement pattern matching from `core.anomaly`, but neither `HypothesisBrief` nor the seam rules encode a check that prevents the system from flagging expected AI-driven CQ drops as anomalous. The `expected_magnitude` field in `HypothesisBrief` is a step toward this, but there is no seam rule that cross-references it against known co-movement signatures. |
| Architecture Soundness | 7/10 | The separation of `/core/`, `/contracts/`, `/trace/`, and `/harness/` is clean and the boundaries are well-chosen. The optional `trace` parameter approach for backwards compatibility is pragmatic. Two concerns pull this down: (1) Mode A's enforcement via subprocess calls to `seam_validator.py` with JSON files in `/tmp/` is fragile — race conditions, stale files, and no cleanup strategy are unaddressed; (2) the dual-mode design shares contracts but not orchestration logic, meaning behavioral drift between Mode A and Mode B is inevitable unless there's a conformance test suite (not proposed). |
| Feasibility & Scope Risk | 7/10 | The execution order is well-sequenced — pure-new-code steps before rename steps is correct risk management. The rename from `tools/` to `core/` across 571 tests is the highest-risk mechanical step and the plan acknowledges it. However, Step 6 (extending `agent_orchestrator.py` into a full 4-stage orchestrator calling Claude API) is significantly under-scoped — the existing orchestrator is a post-process hook for verification, and the proposed orchestrator is a full pipeline controller. That is not an "extend," it is a rewrite with a different control flow model. Calling it an extension understates the work and risk. |
| Failure Mode Coverage | 5/10 | This is the weakest dimension. The plan describes what happens when `data_quality_status == "fail"` (early exit with blocked report) but is silent on every other failure mode. What happens when HYPOTHESIZE seam validation fails — does the orchestrator halt, return a partial trace, retry with relaxed constraints? What if a sub-agent in DISPATCH times out or returns contradictory evidence against the co-movement pattern? What does Mode A (skill file) do when `seam_validator.py` exits non-zero — does Claude Code see the error, retry, or proceed without validation? The `rule_narrative_data_coherence` check is listed but has no specification of what "plausible" means or how it handles mix-shift scenarios where proportions are counterintuitive. For a system that diagnoses metric movements during incidents (when everything is already broken), the failure mode design needs to be first-class, not implicit. |
| Traceability & Auditability | 8/10 | The dual-audience design (`human_summary` + `agent_context`) is well-conceived and directly addresses the IC9 finding. The `alternatives_considered` field in `TraceSpan` is a strong addition — it captures the decision space, not just the decision. The `agent_context_for(stage)` method on `InvestigationTrace` is the right abstraction for downstream agents. Concern: the trace schema has 13 fields per span, and a full investigation will emit dozens of spans. For Mode A (skill file), this accumulates in `/tmp/investigation_trace.json` and gets read back into the context window. No discussion of trace size budgets, summarization, or what happens when the trace exceeds Claude's context window during SYNTHESIZE — which is the exact stage where full trace context is most critical. |

#### Detailed Feedback

**Architecture Soundness — Mode A Fragility**

The skill file mode relies on subprocess calls to `seam_validator.py` with intermediate JSON in `/tmp/`. This creates several problems:

1. **No atomicity.** If Claude Code writes the UNDERSTAND output to `/tmp/understand_out.json` and then calls the validator, there is no guarantee the file is complete before validation reads it. This is unlikely to fail in practice (single-user CLI), but it is architecturally sloppy for a system that is supposed to model "enforcement at seam boundaries."

2. **No cleanup.** What happens to `/tmp/investigation_trace.json` across sessions? If a user runs two investigations in the same Claude Code session, does the trace from investigation #1 contaminate investigation #2? The `trace_id` field suggests awareness of this, but the plan does not specify file lifecycle.

3. **Error propagation.** When `seam_validator.py` raises `SeamViolation`, what does Claude Code see? A non-zero exit code and stderr output. The plan does not specify the error format or how the skill file instructions handle it. This matters because the whole point of v2 is preventing the LLM from silently proceeding past failed validations — but if the error message is not structured, the LLM can misinterpret or ignore it just as easily as it ignored prompt instructions in v1.

**Concrete suggestion:** Define a structured error output format for `seam_validator.py` (JSON to stdout with `{"passed": false, "violations": [...], "remediation": "..."}`) and add explicit skill file instructions for each failure case. Better yet, consider whether Mode A should use Python imports rather than subprocess calls — the skill file can run Python directly via Claude Code's tool use.

**Architecture Soundness — Behavioral Drift Between Modes**

The plan shares contracts and trace schema between modes but not orchestration behavior. Mode A's stage transitions are controlled by LLM instruction-following (skill file markdown); Mode B's are controlled by Python code (`orchestrator.py`). Over time, these will diverge — someone will add a check to the orchestrator that never makes it into the skill file, or vice versa. The plan does not propose a conformance test suite that runs the same scenarios through both modes and verifies equivalent outcomes.

**Concrete suggestion:** Add a cross-mode conformance test to the eval framework. Run at least 2 scenarios through both Mode A and Mode B, compare the trace outputs, and verify that the same seam validations fire with the same results. This is the only way to prevent silent drift.

**Feasibility — The Orchestrator Is a Rewrite, Not an Extension**

The existing `agent_orchestrator.py` (which I reviewed) is a post-process verification hook. It takes a completed diagnosis, runs specialist agents against it, and fuses verdicts. The proposed `harness/orchestrator.py` is a fundamentally different thing: a full pipeline controller that manages 4 sequential stages, each with contract validation, trace emission, and Claude API calls. The plan says "Move + extend," but the control flow, responsibility, and interface are entirely different. The only reusable piece is the verdict fusion logic.

This matters because "extend" implies low risk and incremental work. A rewrite of the orchestration model carries integration risk (does the new orchestrator correctly invoke the same core tools?), API risk (Claude API error handling, rate limits, token budgets), and testing risk (the existing orchestrator tests verify post-process verification, not pipeline control).

**Concrete suggestion:** Acknowledge this as a rewrite. Create `harness/orchestrator.py` as a new file that imports verdict fusion from the old orchestrator rather than trying to evolve the old file. Keep the old orchestrator functional (renamed to `harness/verdict_fuser.py` or similar) so the existing test suite continues to pass without modification.

**Failure Mode Coverage — The Critical Gap**

The plan's silence on mid-pipeline failures is a blocker-level concern for a system that runs during incidents. Specific scenarios that need design:

1. **HYPOTHESIZE seam fails** (fewer than 3 hypotheses, no contrarian). Does the orchestrator halt? Ask Claude to regenerate? Return a degraded report? The plan explicitly defers hypothesis re-generation to v2+, which means in v1 the pipeline just... stops? During an incident? That is worse than the current system, which at least produces a report (even if unchecked).

2. **DISPATCH sub-agent returns contradictory evidence.** Two sub-agents confirm the same hypothesis with conflicting magnitude estimates (e.g., one says mix-shift explains 60%, another says 20%). The `FindingSet` schema has no mechanism for surfacing or resolving this. The existing `verify_diagnosis()` in `core/diagnose.py` has coherence checks — are these still invoked? Where?

3. **SYNTHESIZE seam fails** (missing mandatory section). This is the highest-stakes failure. The system has done all the expensive work (sub-agent calls, decomposition, trace accumulation) and then fails at the output gate. What is the recovery path? Retry SYNTHESIZE only (reasonable)? Discard everything (wasteful)? The plan needs a retry budget for SYNTHESIZE specifically, since the LLM can usually fix section completeness issues on a second attempt.

4. **Connector-specific patterns not in playbook.** A novel connector type (say, a new ServiceNow integration) causes metric movements that do not match any archetype in `historical_patterns.yaml`. The `unknown_pattern` fallback exists in `core/diagnose.py`, but the HYPOTHESIZE contract requires `source: "data_driven" | "playbook" | "novel"`. How does "novel" interact with the `confirms_if` requirement? If the hypothesis is genuinely novel, there may be no well-defined confirmation criteria.

**Concrete suggestion:** Add a "Failure Mode Matrix" section to the design doc. For each seam (UNDERSTAND, HYPOTHESIZE, DISPATCH, SYNTHESIZE), specify: (a) what happens on validation failure, (b) whether retry is allowed and how many times, (c) what degraded output looks like, (d) how the trace records the failure. This is table-stakes for a production diagnostic system.

**Traceability — Context Window Budget**

The trace system is well-designed for auditability but has no accounting for its own size. A `TraceSpan` with 13 fields, multiplied by the number of spans emitted across 4 stages (conservatively: 3-4 spans in UNDERSTAND, 1 in HYPOTHESIZE, N in DISPATCH where N = number of sub-agents, 1 in SYNTHESIZE, plus 4 seam validation spans), produces a trace that could easily be 5,000-10,000 tokens. In Mode B (Python orchestrator), this is fine — it is in-process data. In Mode A (skill file), this trace is read back into the context window for SYNTHESIZE, where the model already needs to hold the full investigation context.

The `agent_context_for(stage)` method is the right abstraction for summarization, but the plan does not specify what it returns. Is it the full trace filtered by stage? A compressed summary? A fixed-length digest? Without a specification, this method is a placeholder that will either return too much (context window overflow) or too little (information loss at SYNTHESIZE).

**Concrete suggestion:** Specify a token budget for `agent_context_for()` output. Something like: "Returns a structured summary of at most 1,500 tokens per stage, containing: decision values, evidence counts, and anomaly flags — but not raw inputs/outputs." This forces the design to be explicit about what information survives the compression.

**Search Domain Correctness — Missing Co-Movement Guard**

The contracts define the right fields but do not encode the most critical domain rule: AI-click inverse co-movement is expected behavior, not an anomaly. The `co_movement_pattern` field in `UnderstandResult` captures the pattern, but there is no seam rule that prevents HYPOTHESIZE from generating "CQ degradation" hypotheses when the co-movement pattern is `ai_adoption_expected`. This is the exact failure mode the IC9 audit identified as the "AI adoption trap" (eval scenario S5, which currently scores 100/100).

The existing `match_co_movement_pattern()` in `core/anomaly.py` handles this correctly at the tool level. But the v2 architecture moves enforcement to seam boundaries — and if the seam does not check this, the LLM at HYPOTHESIZE could generate hypotheses that contradict the deterministic co-movement analysis. The whole point of v2 is that seams are the enforcement layer, not individual tools.

**Concrete suggestion:** Add a HYPOTHESIZE seam rule: `rule_hypotheses_consistent_with_co_movement`. If the UNDERSTAND stage identified `ai_adoption_expected` co-movement, no hypothesis should have archetype `click_quality_degradation` without explicit justification in the `is_contrarian` field.

#### Key Questions for the Author

1. **What is the concrete recovery behavior when SYNTHESIZE seam validation fails?** The system has spent 30-60 seconds on sub-agent investigation, accumulated a full trace, and then the synthesis fails a mandatory section check. Does it retry SYNTHESIZE (if so, how many times?), return a raw findings dump, or fail entirely? This is the single most important failure mode for a system that runs during incidents, and the plan is silent on it.

2. **How does `agent_context_for()` decide what to include and what to drop?** This method is the bridge between trace completeness and context window feasibility. If it returns the full trace, Mode A breaks on large investigations. If it returns a fixed summary, you lose the "every decision is traceable" property at the exact moment traceability matters most (SYNTHESIZE). What is the compression strategy, and how do you validate that it preserves the information SYNTHESIZE needs to produce accurate reports?

3. **How will you detect behavioral drift between Mode A and Mode B?** The plan shares schemas but not orchestration logic between modes. Six months from now, someone adds a "check for Simpson's Paradox" step to the orchestrator but forgets to update the skill file. The two modes now produce different diagnoses for the same input. What mechanism prevents this? If the answer is "discipline," that is the same answer v1 had for SYNTHESIZE compliance, and it failed at 50%.
