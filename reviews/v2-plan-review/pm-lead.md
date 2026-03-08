# PM Lead Review — v2.0 Holistic Redesign Plan

**Overall Assessment:** This plan is well-motivated — the IC9 audit findings are real, and "fix it structurally, not with more prompts" is the right instinct. However, the plan bundles what is effectively three separate projects (trace system, contract enforcement, dual-mode orchestrator) into a single "v2.0" without clear phasing milestones, success metrics, or a credible explanation of who benefits from each piece and when. The scope-to-value ratio concerns me: the plan adds ~14 new files and a full directory restructure, but the eval target is literally "scores unchanged." If the output is the same, what did the user get?

---

## Scores

| Dimension | Score | Justification |
|-----------|-------|---------------|
| IC9 Coverage | 8/10 | The IC9 mapping table (Step 7) is thorough — all 4 Invisible Decisions are addressed, Phase 1 vs Phase 2 prioritization is preserved, and the 3 deferred items are explicitly called out with rationale. The plan doesn't silently drop anything. Solid. |
| Search Domain Correctness | 7/10 | The contracts model the right search concepts: co-movement patterns are preserved in UnderstandResult, mix-shift decomposition flows through unchanged core tools, and the AI-click inverse relationship is structurally intact because core logic isn't touched. However, the contracts are purely structural — none of the seam rules encode domain-specific validation (e.g., "if ai_trigger rose and click_quality fell, that's expected, not a regression"). The domain knowledge stays locked in YAML files and LLM reasoning, not in the enforcement layer. |
| Architecture Soundness | 7/10 | The dual-mode design is clean in theory — shared core, two execution surfaces. But the plan underestimates the coupling risk: Mode A (skill file) calls seam_validator via subprocess with JSON files in /tmp, while Mode B calls it in-process. These are fundamentally different execution models that will diverge in behavior over time (error handling, partial state, trace completeness). The plan asserts they "share the same contracts and trace schema" but doesn't explain how you keep them in sync when one is prompt-driven and the other is code-driven. |
| Feasibility & Scope Risk | 5/10 | This is the biggest concern. See detailed feedback below. |
| Failure Mode Coverage | 6/10 | The plan specifies seam validation rules but says nothing about what happens when they fail. Does a SeamViolation at HYPOTHESIZE halt the investigation? Return a partial report? Retry with different parameters? For a production metric debugging tool, the failure path matters more than the happy path — a DS debugging a P0 at 2am doesn't want "SeamViolation: rule_has_contrarian_hypothesis failed." The plan treats enforcement as binary (pass/raise) without a degradation strategy. |
| Traceability & Auditability | 8/10 | The dual-audience trace design (human_summary + agent_context) is genuinely thoughtful. The idea that a DS can review a trace and reconstruct the "why" is strong. The TraceSpan schema captures the right dimensions — especially `swimlane` (deterministic vs LLM) and `alternatives_considered`. My concern is volume: a full investigation could generate 20+ spans, and the plan doesn't discuss trace summarization or filtering for different audiences (DS reviewing a P0 vs. weekly audit). |

---

## Detailed Feedback

### Feasibility & Scope Risk (5/10) — This is the blocker

**The plan is three projects wearing a trenchcoat.**

1. **Project A: Trace system** — new `/trace/` module, TraceSpan schema, InvestigationTrace collector, trace emission in every core tool. This alone is a meaningful piece of work with clear value (auditability).

2. **Project B: Contract enforcement** — new `/contracts/` module, 4 TypedDict schemas, seam_validator with business rules, integration into both modes. This is architecturally significant and requires careful design of the failure/degradation path.

3. **Project C: Directory restructure + dual-mode orchestrator** — renaming `/tools/` to `/core/`, updating 37+ import references across tests and eval, moving agent_orchestrator to a new harness module, and extending it to a full 4-stage orchestrator with Claude API calls.

The plan presents these as 8 sequential steps, but that obscures the risk. **Step 4 (rename /tools/ to /core/)** touches every test file and eval script. If anything breaks, you're debugging it while also trying to build two new modules that depend on the renamed paths. The plan says "571 tests still passing" after each step but doesn't account for the reality that a rename-and-restructure step will produce a wave of import errors that need manual fixing across 14 test files and 6+ eval files.

**Concrete concern: the rename risk.** The plan identifies 37 import references (31 in tests, 6 in eval) that need updating. But it doesn't mention: the skill file's `python tools/decompose.py` CLI calls, any `sys.path` manipulation in test fixtures, `__init__.py` module exports, or CI/CD paths. A rename that seems mechanical can easily consume a full session of debugging.

**My recommendation:** Split this into three PRs with independent merge points:
- PR 1: `/trace/` module (pure additive, zero risk to existing code)
- PR 2: `/contracts/` module + seam_validator (pure additive)
- PR 3: Rename + orchestrator + integration (this is where breakage lives; do it last, with a clean rollback point)

This way, if you run out of steam after PR 2, you still have a working trace system and contract schemas. The current plan has no intermediate value — it's all-or-nothing.

### IC9 Coverage (8/10) — Strong but one gap

The IC9 mapping is the best part of this plan. Every finding has a concrete implementation reference. The deferred items are honest: hypothesis re-generation breaks the one-shot constraint, memory quality is a different problem, and inter-batch context is out of scope.

**One gap:** The plan maps `hypothesis_inclusion` (Invisible Decision #2) to a trace span emitted by "the HYPOTHESIZE stage (LLM-generated span)." But LLM-generated spans are by definition unverifiable — the LLM decides what to include in `alternatives_considered` and `exclusions`. The IC9 audit flagged this as an Invisible Decision precisely because the LLM controls what hypotheses get surfaced. The plan traces the output but doesn't constrain the input. How do you know the LLM didn't silently drop the most important hypothesis? The `rule_has_contrarian_hypothesis` helps, but it's a weak structural check (does ANY contrarian exist?) rather than a content check (is the RIGHT contrarian included?).

**Suggestion:** Add a deterministic pre-filter that generates candidate hypotheses from the archetype playbook BEFORE the LLM sees them. The LLM can add novel hypotheses, but the playbook-derived ones must appear in the exclusions list if dropped. This makes `hypothesis_inclusion` partially code-enforced rather than fully LLM-controlled.

### Architecture Soundness (7/10) — Dual-mode divergence risk

The dual-mode design is appealing on paper but creates a maintenance trap. Consider the lifecycle:

1. You build Mode A (skill file) with subprocess calls to seam_validator
2. You build Mode B (orchestrator) with in-process seam validation
3. You discover a bug in seam validation logic — you fix it in `contracts/seam_validator.py`
4. Mode B picks it up immediately. Mode A picks it up too (same code), but the _behavior_ differs because Mode A's error handling is in the skill file (prompt instructions) while Mode B's is in Python

**The real question:** Who is the Mode B user? The plan says "production teams" but this is an open-source side project with a user base of... you. Mode B requires Claude API calls, which means API keys, rate limits, cost management, and model-specific prompt tuning. Is there a concrete production team waiting for this, or is it aspirational?

If Mode B is aspirational, I'd argue: **build Mode A properly first, then extract Mode B when you have a real consumer.** Building both in parallel doubles the integration testing surface without doubling the user value.

### Search Domain Correctness (7/10) — Contracts don't encode domain invariants

The contracts capture structural requirements (min 3 hypotheses, all sections present, evidence attached) but miss domain-specific invariants that would actually catch bad investigations:

- **No co-movement coherence check at SYNTHESIZE.** If the root_cause says "ranking regression" but the co-movement pattern shows AI-click inverse movement (which is expected behavior), the synthesis is wrong. This is catchable deterministically but isn't in the seam rules.
- **No severity-to-metric proportionality.** A 0.3% CQ drop being labeled P0 is a false alarm. The contracts check that severity exists and that language matches severity, but not that severity matches the actual metric movement magnitude.
- **`expected_magnitude` is required but unchecked.** The HypothesisBrief requires it (good), but no seam rule validates that the actual findings are within the expected range. It's a field that exists for show.

These are exactly the kind of domain-specific enforcement gaps that the IC9 audit warned about. The contracts enforce form, not substance.

### Failure Mode Coverage (6/10) — No degradation strategy

The plan's failure handling is: `Raises SeamViolation on failure.` Full stop. For a debugging tool that runs during incidents, this is insufficient. Specific scenarios unaddressed:

1. **HYPOTHESIZE seam fails** (fewer than 3 hypotheses generated). Does the investigation abort? The DS still needs *something* — even a partial analysis is better than nothing during a P0.
2. **DISPATCH returns conflicting findings** (one sub-agent says "ranking regression confirmed," another says "mix-shift explains everything"). The contracts check that evidence exists but don't handle contradiction resolution.
3. **Novel metric pattern** not in the playbook. The `co_movement_pattern` matching returns no strong match. What happens at the UNDERSTAND seam? The `metric_direction` field is required, but what if the direction is ambiguous (metric oscillating, not clearly up or down)?

**Suggestion:** Add a `degraded_mode` flag to each contract. When a seam fails non-critically, emit a trace warning and continue with explicit "low confidence" markers rather than halting. Reserve hard failures for data quality issues (garbage in = stop) and let structural violations degrade gracefully.

---

## Key Questions for the Author

1. **Who is the Mode B user, concretely?** You say "production teams" but this is an open-source side project. If the answer is "me, eventually, when I have Databricks MCP wired up" — that's fine, but then Mode B should be a stub in v2.0 and a real implementation in v2.1. Building a full orchestrator with Claude API integration for a hypothetical consumer is scope creep hiding behind architecture diagrams.

2. **What is the measurable success metric for v2.0?** The plan's "done" criteria is "eval scores unchanged + trace JSON shows 4 spans + seam catches a missing section." That's a verification checklist, not a success metric. If you shipped v2.0, what would you tell your stakeholders that's different? "We restructured the code and added tracing" is not a user outcome. What investigation failure mode that exists today will v2.0 prevent? Put a number on it — how many of the 40+ IC9 failure modes are eliminated vs. mitigated vs. deferred?

3. **What's your rollback plan if the `/tools/` to `/core/` rename breaks more than expected?** The plan assumes this is mechanical (update 37 import paths), but you have 14 test files, eval scripts, a skill file with CLI paths, and possibly CI configuration. If you're 60% through the rename and discover the eval harness has hardcoded paths you didn't anticipate, do you push forward or revert? The plan doesn't address this, and for a codebase with 571 passing tests, a botched rename could cost an entire session to untangle.
