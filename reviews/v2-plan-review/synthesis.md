# Review Synthesis — v2.0 Holistic Redesign Plan

**Date:** 2026-03-07
**Iterations:** 1
**Calibration status:** Calibrated (all 3 roles)

## Consensus Points

All three reviewers agree on:

1. **IC9 coverage is strong (8/8/8).** The fix mapping table is thorough, all 4 Invisible Decisions are traced, Phase 1 vs Phase 2 prioritization is clear, deferred items are honestly identified.

2. **Contracts enforce form, not substance.** All three independently flagged that the TypedDict schemas capture structural requirements (fields exist, counts met) but miss domain-specific invariants (co-movement coherence, severity-to-magnitude proportionality, `expected_magnitude` validation).

3. **Failure mode behavior is unspecified.** `SeamViolation` is raised, but what the user gets (partial report? stack trace? retry?) is never defined. All three call this a critical gap for a system that runs during incidents.

4. **Mode A/B behavioral drift is inevitable.** Shared schemas but different orchestration logic (prompt-driven vs code-driven) will diverge over time. No conformance test is proposed.

5. **`rule_narrative_data_coherence` is named but not defined.** All three question whether this is a rubber stamp or real enforcement. No algorithm is specified.

6. **Dual-audience trace design is genuinely good (7/8/8).** `human_summary` + `agent_context` is the right abstraction.

## Conflicts & Tensions

### Scope: Monolith vs Incremental

- **PM Lead (blocker-level, score 5):** "Three projects wearing a trenchcoat." Recommends splitting into 3 independent PRs with intermediate merge points. Argues the current plan has no intermediate value — if you stop halfway, you have nothing shippable.
- **DS Lead & Principal (score 7/7):** Accept the scope as feasible given the execution order and test safety net.
- **Tension:** PM is right that the plan is all-or-nothing with no intermediate user value. DS/Principal are right that the execution order minimizes technical risk. The question is whether the plan needs *business* risk mitigation (intermediate deliverables) or just *technical* risk mitigation (sequenced steps).

### Mode B: Build Now vs Build Later

- **PM Lead (concern):** "Who is the Mode B user? If aspirational, build Mode A properly first, then extract Mode B when you have a real consumer."
- **Principal (accepts it):** Mode B is architecturally justified — it's the enforcement layer that Mode A can't provide (prompt instructions vs code gates).
- **Tension:** PM is asking a business question (is there demand?). Principal is answering an architecture question (is it needed for correctness?). Both are valid. The decision depends on whether the user values correctness guarantees now or wants to optimize for shipping speed.

### Orchestrator: Extend vs Rewrite

- **Principal (concern):** "The orchestrator is a rewrite, not an extension. The existing agent_orchestrator.py is a post-process verification hook; the proposed orchestrator is a full pipeline controller. Calling it an extension understates the risk."
- **DS Lead & PM Lead:** Flag this as a feasibility risk but don't call it a blocker.
- **Tension:** The plan says "move + extend" which implies low risk. The Principal correctly identifies this as a fundamentally different control flow model. This is a labeling problem that could lead to underestimating effort.

## Decision Points for Product Owner

### Decision 1: Monolith vs 3 PRs
**What's at stake:** If you go monolith and run out of steam at Step 5, you have renamed directories but no working trace or contracts. If you go 3 PRs, each PR ships value independently but you lose the "clean break" feeling of a v2 release.

**Options:**
- **(A) Keep monolith, add checkpoints.** Keep the 8-step plan but add git tags at Steps 3, 4, and 6 so you can revert to a known-good state. (DS/Principal lean here)
- **(B) Split into 3 PRs.** PR1: trace/, PR2: contracts/, PR3: rename + orchestrator + integration. Each independently mergeable. (PM strongly recommends)
- **(C) Hybrid: 2 PRs.** PR1: trace/ + contracts/ (pure additive, zero risk). PR2: rename + orchestrator + core tool trace emission + integration. (Compromise)

### Decision 2: Failure Mode Strategy
**What's at stake:** Without a degradation strategy, `SeamViolation` during a P0 investigation returns nothing — worse than the current system.

**Options:**
- **(A) Hard gates.** Seam failures halt the pipeline. Acceptable if you add a retry budget for SYNTHESIZE (1-2 retries) and a "degraded report" fallback for HYPOTHESIZE failures.
- **(B) Soft gates.** Seam failures emit warnings in the trace, set confidence to "Low", and continue. Full enforcement is advisory in v2, mandatory in v3.
- **(C) Tiered gates.** UNDERSTAND failures = hard halt (garbage in). HYPOTHESIZE/DISPATCH failures = soft (flag + continue). SYNTHESIZE failures = retry once, then soft.

### Decision 3: Mode B Scope
**What's at stake:** Building a full Claude API orchestrator doubles integration testing surface.

**Options:**
- **(A) Full orchestrator now.** Build `harness/orchestrator.py` with Claude API calls, 4-stage pipeline, full seam enforcement. Ship Mode A and Mode B together.
- **(B) Stub orchestrator.** Build the pipeline skeleton with contract validation but mock the Claude API calls. Wire up real API in v2.1 when there's a concrete consumer.
- **(C) Mode A only.** Skip Mode B entirely in v2. Build it when Databricks MCP is wired up and there's a real production use case.

### Decision 4: Plan Amendments
**What's at stake:** The reviews surfaced 5 concrete gaps that should be addressed before implementation.

**Amendments to consider adding:**
1. **Failure Mode Matrix** — For each seam, specify: failure behavior, retry budget, degraded output format, trace recording.
2. **`rule_hypotheses_consistent_with_co_movement`** — HYPOTHESIZE seam rule that prevents flagging expected AI-driven CQ drops as anomalous.
3. **`mix_shift_result` field in UnderstandResult** — First-class representation of mix-shift decomposition output.
4. **`agent_context_for()` token budget** — Specify max ~1,500 tokens per stage, contents = decision values + evidence counts + anomaly flags.
5. **Cross-mode conformance test** — Run 2+ scenarios through both Mode A and Mode B, compare trace outputs.

## Score Summary

| Dimension | DS Lead | PM Lead | Principal | Avg |
|-----------|---------|---------|-----------|-----|
| IC9 Coverage | 8 | 8 | 8 | 8.0 |
| Search Domain Correctness | 6 | 7 | 7 | 6.7 |
| Architecture Soundness | 7 | 7 | 7 | 7.0 |
| Feasibility & Scope Risk | 7 | 5 | 7 | 6.3 |
| Failure Mode Coverage | 6 | 6 | 5 | 5.7 |
| Traceability & Auditability | 7 | 8 | 8 | 7.7 |

**Weighted average: 6.9/10**

## Individual Reviews
- [DS Lead Review](ds-lead.md)
- [PM Lead Review](pm-lead.md)
- [Principal AI Engineer Review](principal-ai-eng.md)
