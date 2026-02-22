# DS-STAR Paper Critique — IC9-Level Multi-Judge Review

**Date:** 2026-02-21
**Paper:** DS-STAR: A Multi-Agent Framework for Data Science Tasks (Google)
**Method:** Multi-Agent Debate + LLM-as-a-Judge with 3 IC9-level specialist judges
**Purpose:** Determine which DS-STAR patterns to adopt for Search Metric Analyzer v1.4

---

## Judges

| Judge | Perspective | Focus |
|-------|------------|-------|
| **Judge 1** | Search Systems Architect | Pattern applicability, architecture fit, blast radius |
| **Judge 2** | Metric Diagnosis Domain Expert | Domain transfer rate, what's missing, what would hurt |
| **Judge 3** | Production Engineering Pragmatist | ROI analysis, latency/reliability, minimum viable version |

---

## Consensus Verdict

**2 patterns worth stealing, adapted for our closed-domain system:**

1. **Verification (DS-STAR Verifier)** → `verify_diagnosis()` — deterministic Python assertions, not an LLM agent
2. **Delete and Regenerate (DS-STAR insight)** → Scored archetype matching — score all patterns instead of first-match

**Do NOT build:** 7-agent specialization, 20-iteration loops, LLM-based planning, Router agent

**One-line takeaway:** "DS-STAR's verification pattern is worth stealing. Everything else is either already in our system in a simpler form, or solving a problem that doesn't exist in closed-domain metric diagnosis."

---

## Where All Three Judges Agreed (Unanimous)

1. **Verification is the #1 gap.** Steal it, but as deterministic Python, not an LLM agent.
2. **7-agent specialization and 20-iteration loops are waste of time** for our closed domain.
3. **Our system's determinism, speed, and auditability are features** that DS-STAR's architecture would destroy.

## Where They Debated (and How It Resolved)

- **Verify loop vs. verify once:** Judge 1 wanted a loop, Judge 3 said "latency explosion." Resolution: single verification pass, no loop.
- **LLM verification vs. Python assertions:** Judge 1 wanted an LLM call, Judge 3 said "20 lines of Python." Resolution: Python wins for a closed domain with known field relationships.
- **Analyzer agent vs. YAML rules:** All agreed we need better data profiling, but not as an LLM agent. Deterministic validation rules are cheaper and never hallucinate.

---

## Comparative Scorecard

| DS-STAR Pattern | Applicability | ROI | Cost | Risk | Verdict |
|----------------|:---:|:---:|:---:|:---:|---------|
| 7-Agent Specialization | 2/10 | Low | High | High | DO NOT BUILD |
| Analyzer Pre-Profiling | 5/10 | Medium | Low | Low | Solve with better YAML |
| Verify-Route-Backtrack | 7/10 | High | Medium | Medium | STEAL (single pass only) |
| Delete & Regenerate | 6/10 | Medium | Low | Low | STEAL (scored matching) |
| 20-Iteration Budget | 1/10 | Negative | High | High | DO NOT BUILD |
| LLM-as-Judge Verification | 9/10 | **Highest** | Low | Low | STEAL (as Python assertions) |

---

## What DS-STAR Doesn't Do That We Need (Judge 2)

1. **Causal ordering within a metric hierarchy** — L0 → L1 → L2 → L3 cascading regressions
2. **Inverse co-movement is positive** — AI adoption trap has no analog in DS-STAR
3. **Mix-shift as first-class diagnostic outcome** — Kitagawa-Oaxaca decomposition
4. **Confidence with actionable upgrade/downgrade conditions** — `would_upgrade_if` / `would_downgrade_if`
5. **Historical pattern matching** — institutional memory from past incidents

## Where DS-STAR Would Actively Hurt Us (Judge 2)

1. **Latency:** 5.6 iterations × 30s = ~7 minutes vs. our <60 seconds
2. **Non-determinism:** Eval scores become a distribution instead of stable numbers
3. **Over-exploration:** 80% of incidents match a known archetype on first try
4. **Loss of auditability:** Iterative planning harder to explain than deterministic checks
5. **"Novel question" assumption:** We solve the same 9 root causes repeatedly

---

# Full Judge Reviews

---

## Judge 1: Search Systems Architect

---

### Executive Summary

DS-STAR is a 7-agent data science system with iterative refinement (Verify-Route-Backtrack loops). Your Search Metric Analyzer is a 4-tool linear pipeline for a narrow domain (Enterprise Search metric diagnosis). The core question is: which DS-STAR patterns solve **real problems you have**, versus which ones import complexity for a problem that doesn't exist in your system?

**Bottom line:** One pattern is high-ROI (LLM-as-Judge verification). One pattern would be a waste of time (7-agent specialization). The rest are a spectrum.

---

### 1. Multi-Agent Specialization (7 Agents) — 2/10

No. Your pipeline has 4 tools that are already functionally specialized. Each tool is a pure function: data in, JSON out. DS-STAR uses 7 agents because their problem space is unbounded — they handle arbitrary data science questions across arbitrary datasets. Your problem space is tightly scoped: Enterprise Search metrics, 4 core metrics, 9 known archetypes, fixed hypothesis priority ordering. You don't need an Analyzer agent to "profile the data" because your data schema is known at design time.

Adding agent boundaries between decompose and diagnose would introduce coordination overhead, increase token costs, and create failure modes at the handoff points. Your tools communicate via JSON dicts — this is cheaper, faster, and more debuggable than agent-to-agent message passing.

**Key quote:** "Using GPS to navigate your own house."

### 2. Analyzer Pre-Profiling — 5/10

Partially applicable. Your data quality gate only checks completeness and freshness. It doesn't profile the shape of the data — minimum rows per segment, stationarity, cardinality checks. But a full LLM-based Analyzer agent is overkill. The right approach is deterministic data validation rules added to the existing data quality gate. This gets 80% of the Analyzer's benefit at 0% of the LLM cost.

### 3. Verify-Route-Backtrack Loop — 7/10

**This is a real gap.** Your pipeline is strictly linear with no mechanism to go back. Specific failure modes:
- First-match archetype is wrong (first-match semantics in `match_co_movement_pattern()`)
- Decomposition completeness fails but pipeline continues (HALT recorded but not acted on)
- False alarm detection can misfire at P2/normal boundary
- Multi-cause overlap detected but never validated

**Recommendation:** A single verification pass, not 20 iterations. One loop, not twenty. This is the difference between "verify your work" and "iterate until perfect."

### 4. "Delete and Regenerate" — 6/10

DS-STAR's single most applicable insight. When the first archetype match is wrong, don't try to patch it — re-derive from different evidence. Translates to: instead of first-match semantics, **score all matching archetypes** and pick the best one.

### 5. 20-Iteration Budget — 1/10

Actively harmful. Your system's value proposition is fast, confident diagnosis. Iteration budgets are for systems that don't know what they're doing and need to search. Your system knows exactly what it's doing — it just needs to verify it did it right.

### 6. LLM-as-Judge Verification — 9/10

**Biggest gap.** Your pipeline has zero verification of diagnosis correctness. Specific catches:
- Archetype-evidence mismatch (ranking_regression but top segment is ai_enablement=ai_on)
- Severity-action mismatch (P0 with empty action items)
- Confidence-evidence mismatch (High confidence with HALT checks)
- Formatted output quality (TL;DR contradicts action items)

**Recommended architecture:**
```
[Intake] → [Enhanced Data Quality Gate] → [Decompose + Anomaly]
    → [Scored Archetype Matching] → [Diagnose]
    → [LLM Coherence Verifier] → [Format] → [Output]
         ↓ (if incoherent)
    [Re-diagnose with adjusted parameters] → [Format] → [Output]
```
Total new LLM calls: 1. Total new iterations: at most 1. Total new agents: 0.

---

## Judge 2: Metric Diagnosis Domain Expert

---

### Transfer Rate Assessment

**Short answer: about 30% of DS-STAR's design is relevant. The other 70% is solving problems you don't have.**

DS-STAR solves open-ended data science tasks where the steps themselves are unknown. Our problem has 4 fixed steps, 4 metrics, 9 archetypes, and ~6 decomposition dimensions. The problem space is not just constrained — it is *enumerable*. 9 archetypes × 6 dimensions = 54 possible diagnosis paths, minus the impossible combinations.

### What Transfers Genuinely

1. **The Verifier concept** — already adopted as 4 validation checks. Keep and strengthen.
2. **"Code does not guarantee correctness" insight** — treating pipeline output as a hypothesis to verify rather than ground truth.
3. **The Debugger's full-context approach** — when HALTs occur, pass full HALT context to recovery path.

### What Does NOT Transfer

1. **The Router** — our pipeline is a fixed DAG, not a state machine.
2. **The Planner's step generation** — our steps are predetermined.
3. **The Coder agent** — we have pre-written tools, no code to generate.

### The "Delete and Regenerate" Insight — Most Applicable Pattern

When `match_co_movement_pattern()` uses first-match semantics and gets the wrong match, the whole pipeline builds on the wrong archetype. DS-STAR's "delete and regenerate" translates to: **score all matching archetypes instead of committing to the first one.**

### 20-Iteration Loop — Massively Overkill

Two rounds with different hypothesis orderings would get 95% of the benefit. Round 1: full pipeline as-is. Round 2 (conditional): only if confidence is Low or explained_pct < 70%.

### Where DS-STAR Would Actively Hurt Us

- **Latency:** Minutes vs. seconds for incident response
- **Non-determinism:** Eval scores become a distribution
- **Over-exploration:** 80% of incidents match known archetype on first try
- **Loss of auditability:** Iterative planning harder to explain
- **"Novel question" assumption:** We solve the same 9 root causes repeatedly

**Key quote:** "DS-STAR is like asking a senior ER doctor to re-derive the diagnosis framework for a broken arm every time."

---

## Judge 3: Production Engineering Pragmatist

---

### ROI Analysis

| Pattern | Cost | Maintenance | Expected Improvement | Verdict |
|---------|------|-------------|---------------------|---------|
| 7 Specialized Agents | 15-20 days | HIGH (7 prompts, 7 failure modes) | NEAR ZERO | DO NOT BUILD |
| Verify-Route-Backtrack Loop | 5-8 days | Medium | Marginal | Do not build full loop |
| Analyzer Agent | 3-5 days | Low | 5-10pp on NOVEL scenarios | Solve with YAML |
| Router Agent | 2-3 days | Low | NEAR ZERO | DO NOT BUILD |

### The Damning Numbers

- Full DS-STAR (7 agents + loop): 45.24% accuracy on hard tasks
- Simple ReAct baseline: 41.0%
- Delta: **4.24 percentage points at 3.5x token cost**
- The Analyzer alone accounts for 18pp — everything else is marginal

### Production Concerns DS-STAR Ignores

- **Latency:** ~7 minutes estimated (5.6 iterations × 2.5 calls × 30s)
- **Reliability:** 0.95^7 = 69.8% for 7-agent serial chain
- **Observability:** 39 LLM calls to debug vs. traceable JSON chain
- **Graceful degradation:** DS-STAR = total failure when LLM is down. Our Python tools still work.

### The Minimum Viable Version

A single `verify_diagnosis()` Python function — ~20 lines of assertion-style checks. No LLM calls. No loops. No non-determinism. Cost: 1 day.

### Solve Without New Architecture

- **Better YAML:** Add `recommended_dimensions` per metric, `fast_path` patterns, `sanity_check` rules
- **Better Prompts:** Improve skill prompt with examples and conditional instructions
- **Better Eval:** Expand from 5 to 15-20 scenarios with real incident patterns

**Key quote:** "The highest ROI investment is better domain knowledge, not more agents."

---

## Implementation Outcome (v1.4)

Based on this critique, v1.4 implemented:

1. **verify_diagnosis()** — 5 deterministic coherence checks (Python, not LLM)
2. **Scored archetype matching** — rank all patterns, return best match + runner_up
3. **Structured subagent specs** — `confirms_if` / `rejects_if` per archetype
4. **Bug fix** — `query_understanding_regression` archetype field names

Results: 441 tests passing, 5/5 eval GREEN (91.2/100), zero verification warnings.

---
---

# Appendix: Raw Judge Reviews (Unedited)

The sections above are the synthesis. Below are the full, unedited reviews from each judge as originally generated during the IC9 multi-agent debate session.

---
---
---

# DS-STAR Architecture Review: Applicability to Search Metric Analyzer

## Executive Summary

DS-STAR is a 7-agent data science system with iterative refinement (Verify-Route-Backtrack loops). Your Search Metric Analyzer is a 4-tool linear pipeline for a narrow domain (Enterprise Search metric diagnosis). The core question is: which DS-STAR patterns solve **real problems you have**, versus which ones import complexity for a problem that doesn't exist in your system?

**Bottom line:** One pattern is high-ROI (LLM-as-Judge verification). One pattern would be a waste of time (7-agent specialization). The rest are a spectrum.

---

## Pattern-by-Pattern Critique

---

### 1. Multi-Agent Specialization (7 Agents)

**Applicability Score: 2/10**

**Does this solve a REAL problem we have?**

No. Your pipeline has 4 tools (`decompose.py`, `anomaly.py`, `diagnose.py`, `formatter.py`) that are already functionally specialized. Each tool is a pure function: data in, JSON out. DS-STAR uses 7 agents because their problem space is unbounded -- they handle arbitrary data science questions across arbitrary datasets. Your problem space is **tightly scoped**: Enterprise Search metrics, 4 core metrics, 9 known archetypes, fixed hypothesis priority ordering. You don't need an Analyzer agent to "profile the data" because your data schema is known at design time (it's always `metric_ts`, `period`, `tenant_tier`, `ai_enablement`, etc.).

The production architecture (main agent dispatching subagents per hypothesis, each calling a Coder Agent for SQL) already achieves the right level of specialization -- you have task-level parallelism where it matters (hypothesis investigation) without gratuitous agent boundaries.

**Is this the RIGHT solution?**

No. The simpler approach is what you already have: well-defined Python functions with clear interfaces. Adding agent boundaries between decompose and diagnose would introduce coordination overhead, increase token costs, and create failure modes at the handoff points. Your tools communicate via JSON dicts -- this is cheaper, faster, and more debuggable than agent-to-agent message passing.

**Blast radius if implemented wrong?**

High. Agent-to-agent interfaces are the #1 source of bugs in multi-agent systems. Each boundary is a point where context can be dropped, formats can mismatch, and latency accumulates. You'd go from "function calls that never fail" to "agents that occasionally misinterpret each other's output."

**What DS-STAR got wrong for our case?**

DS-STAR needs 7 agents because their agents are LLM-powered (each agent is a prompted Claude/GPT call). Your tools are deterministic Python -- they don't need to be "agents" at all. The distinction matters: an agent makes decisions, a tool executes logic. Your decompose.py doesn't decide anything; it computes Kitagawa-Oaxaca decomposition. Making it an "agent" would mean replacing deterministic math with probabilistic LLM reasoning, which is strictly worse for this use case.

---

### 2. Analyzer Pre-Profiling

**Applicability Score: 5/10**

**Does this solve a REAL problem we have?**

Partially. Your pipeline assumes a fixed data schema (the CSV has known columns). But in production, there's a real failure mode: the data quality gate in `anomaly.py` (`check_data_quality`) only checks completeness and freshness. It doesn't profile the **shape** of the data -- things like:
- Are there enough rows per segment to make decomposition meaningful? (If `connector_type=sharepoint` has 3 rows, the decomposition is noise.)
- Is the metric distribution within each period roughly stationary, or is there a trend within the "current" period?
- Are there unexpected NULL patterns or segment values that would break the decomposition?

The DS-STAR ablation showing accuracy dropping from 45% to 27% without the Analyzer is telling, but that's on arbitrary datasets. Your datasets have known structure.

**Is this the RIGHT solution?**

A full LLM-based "Analyzer agent" is overkill. The right approach is **deterministic data validation rules** added to your existing data quality gate. Think of it as expanding `check_data_quality()` from 2 checks (completeness, freshness) to 5-6 checks:
- Minimum rows per segment (e.g., >=10 rows per `tenant_tier` value)
- Stationarity check within each period (no mid-period regime change)
- Cardinality check (unexpected segment values)
- Zero-variance detection (a metric that's constant is uninformative)

This gets you 80% of the Analyzer's benefit at 0% of the LLM cost.

**Blast radius if implemented wrong?**

Low. Adding more data quality checks is additive -- worst case, you reject data that should have been accepted (false positive on the gate). This is annoying but not dangerous.

**What DS-STAR got wrong for our case?**

Their Analyzer is LLM-powered because they don't know the schema in advance. We do. Using an LLM to profile data with a known schema is like using GPS to navigate your own house. Deterministic validation rules are cheaper, faster, and never hallucinate.

---

### 3. Verify-Route-Backtrack Loop

**Applicability Score: 7/10**

**Does this solve a REAL problem we have?**

**Yes, this is a real gap.** Your pipeline is strictly linear: Decompose then Anomaly then Diagnose then Format. There is no mechanism to go back. Here are specific failure modes in your current system:

1. **First-match archetype is wrong.** `match_co_movement_pattern()` in `anomaly.py` uses first-match semantics against the co-movement diagnostic table. If the observed directions happen to match `ranking_relevance_regression` but the real cause is `query_understanding_regression` (which has an overlapping pattern for 3 of 4 metrics), the pipeline commits to the wrong archetype and never reconsiders. Lines 310-331 of `anomaly.py` show the loop exits at the first match.

2. **Decomposition completeness fails but pipeline continues.** Your Check #2 (`check_decomposition_completeness`) can return HALT at <70% explained, but `run_diagnosis()` doesn't actually halt -- it continues and just records the HALT status. The diagnosis proceeds with incomplete data. There's no mechanism to say "go back and add more dimensions."

3. **False alarm detection can misfire.** The false alarm logic in `diagnose.py` (lines 1094-1116) has two paths: co-movement confirmed (path a) and inferred from P2 severity + no dominant segment (path b). Path b can misclassify a real movement as noise if the metric happens to be at the P2/normal boundary. With a verification loop, the system could check: "We classified this as false alarm, but does the formatted output actually make sense given the raw data?"

4. **Multi-cause overlap is detected but never validated.** `_detect_multi_cause()` finds two top segments from different dimensions, but there's no check that these two causes are actually independent. The correlated-pairs check (lines 812-816) only handles `ai_enablement + tenant_tier`. What about `industry_vertical + connector_type` (healthcare tenants use SharePoint more)?

**Is this the RIGHT solution?**

A full Verify-Route-Backtrack loop with 20 iterations is overkill. But a **single verification pass** would have enormous value. The architecture would be:

```
Decompose -> Anomaly -> Diagnose -> VERIFY -> (if fail: adjust parameters, re-run Diagnose) -> Format
```

The Verify step checks:
- Does the archetype match the decomposition evidence? (e.g., if archetype is `ranking_regression` but the top segment is `ai_enablement=ai_on`, something is wrong)
- Is the confidence level consistent with the evidence count? (sanity check)
- Does the formatted output pass basic coherence checks? (e.g., severity says P0 but TL;DR says "no action needed")

One loop, not twenty. This is the difference between "verify your work" and "iterate until perfect."

**Blast radius if implemented wrong?**

Medium. The risk is infinite loops or oscillation (diagnosis flips between two archetypes on each pass). Mitigation: hard cap at 2 iterations, and the second pass can only **narrow** the diagnosis (remove an archetype), not widen it (add new hypotheses).

**What DS-STAR got wrong for our case?**

20 iterations is for open-ended data science. Your problem space has 9 archetypes and 4 validation checks -- the search space is tiny. One verification pass is the right-sized version of their pattern.

---

### 4. "Delete and Regenerate" vs. "Patch in Place"

**Applicability Score: 6/10**

**Does this solve a REAL problem we have?**

Yes, but not in the way DS-STAR means. DS-STAR's insight is about code: when a code step is wrong, patching it makes it worse. In your system, the analogous problem is **archetype assignment**. Currently, when archetype recognition is wrong (lines 1073-1085 of `diagnose.py`), the rest of the pipeline builds on top of the wrong archetype: severity gets overridden incorrectly, hypothesis description uses the wrong template, action items are for the wrong team.

The current code tries to "patch" by adding mix-shift activation on top of an `unknown_pattern` (lines 1083-1085), and false alarm detection overwrites the archetype after the fact (lines 1114-1116). This is patching -- it layers corrections on top of corrections. The ARCHETYPE_MAP lookup at line 1077, the mix-shift override at 1084, and the false alarm override at 1115 are three sequential mutations of the same variable (`archetype_info`), each trying to fix what the previous one got wrong.

**Is this the RIGHT solution?**

DS-STAR's approach (delete the step and regenerate fresh) translates to: **don't try to fix the archetype; re-run archetype recognition with different parameters.** For example, if the first pass matched `ranking_relevance_regression` but Check #2 shows only 60% explained, instead of continuing with a weak diagnosis, re-run co-movement matching with relaxed direction thresholds (e.g., treat "borderline stable/down" as "down") and see if a different pattern fits better.

The simpler version: instead of first-match semantics, **score all matching archetypes** and pick the best one. This is "regenerate" in the sense that you don't commit to the first answer.

**Blast radius if implemented wrong?**

Low. Scoring all archetypes instead of first-match is a local change to `match_co_movement_pattern()`. It doesn't affect the rest of the pipeline structurally.

**What DS-STAR got wrong for our case?**

"Delete and regenerate" makes sense for code generation where each step depends on the previous one. In your system, the archetype is chosen independently of the decomposition -- they're parallel inputs to the diagnosis, not sequential steps. So the pattern applies to archetype selection, not to the pipeline structure.

---

### 5. 20-Iteration Budget

**Applicability Score: 1/10**

**Does this solve a REAL problem we have?**

No. Your system runs in a Claude Code session where latency matters. The eval stress test already takes meaningful time to run 5 scenarios. Adding iterative refinement with up to 20 loops would make each diagnosis take 20x longer. DS-STAR's average of 5.6 iterations for hard tasks means ~6x the cost. At $0.23/task, DS-STAR costs 3.5x the ReAct baseline in input tokens.

Your system's strength is **speed of diagnosis** -- an Eng Lead asks "why did DLCTR drop?" and gets an answer in seconds, not minutes. A 20-iteration loop would destroy this value proposition.

**Is this the RIGHT solution?**

No. The right number of iterations for your system is 1-2 (see Pattern #3 above). One verification pass catches the obvious mismatches. Two passes handle the case where the first verification reveals a different archetype. Beyond that, you're over-fitting to noise.

**Blast radius if implemented wrong?**

High. Runaway iteration loops in a Claude Code session would consume context window, increase cost, and potentially time out. The user experience goes from "instant diagnosis" to "I'll check back in 10 minutes."

**What DS-STAR got wrong for our case?**

DS-STAR's iteration budget is calibrated for arbitrary data science tasks where the system might need to try multiple analytical approaches (pandas pivot, sklearn regression, matplotlib plot...). Your analytical approaches are fixed (Kitagawa-Oaxaca decomposition, z-score comparison, co-movement matching). There's nothing to iterate on -- the math is deterministic.

---

### 6. LLM-as-Judge Verification

**Applicability Score: 9/10**

**Does this solve a REAL problem we have?**

**This is your biggest gap.** Your pipeline has zero verification of diagnosis correctness. The eval stress test (`run_stress_test.py`) checks correctness after the fact, but in production, there's no mechanism to ask: "Does this diagnosis actually make sense?"

Specific failure modes this would catch:

1. **Archetype-evidence mismatch.** Diagnosis says `ranking_regression` but the top contributing segment is `ai_enablement=ai_on`. A judge would flag: "The hypothesis claims a ranking regression, but the evidence points to AI adoption. These are contradictory."

2. **Severity-action mismatch.** Diagnosis severity is P0 ("requires immediate attention") but action items list is empty (because the archetype was `false_alarm` and the severity override didn't fire). A judge would flag: "P0 severity with no action items is incoherent."

3. **Confidence-evidence mismatch.** Diagnosis says "High confidence" but only 2 of 4 validation checks passed. Currently your system handles this via compute_confidence(), but the formula can produce edge cases where the confidence level doesn't match the reader's intuition (e.g., High confidence on a false alarm where a HALT check was overridden by `false_alarm_from_co_movement`).

4. **Formatted output quality.** The TL;DR says "No action needed" but the action items section lists 3 actions. A judge catches this without needing to understand the underlying data -- it's a coherence check on the output.

**Is this the RIGHT solution?**

Yes, and it's simpler than it sounds. You don't need a separate "Verifier agent." You need a single LLM call after `run_diagnosis()` and before `format_diagnosis_output()` that takes the diagnosis dict and asks:

```
Given this diagnosis:
- Archetype: {archetype}
- Top segment: {dimension}={segment} ({contribution}%)
- Severity: {severity}
- Confidence: {confidence}
- Action items: {count}

Does this diagnosis contain any contradictions? Check:
1. Does the archetype match the evidence?
2. Is severity consistent with action items?
3. Is confidence consistent with validation checks?
4. Are there any logical contradictions in the hypothesis?

Return: {"coherent": true/false, "issues": [...]}
```

This is a cheap, fast call. The LLM doesn't need to re-analyze the data -- it just checks logical coherence of the diagnosis output. Think of it like a copy editor, not a co-author.

**Blast radius if implemented wrong?**

Low-medium. The verification step is read-only -- it doesn't modify the diagnosis, it just flags issues. Worst case: it generates false positives (flags a valid diagnosis as incoherent), which you'd surface as a "review recommended" note rather than blocking the output.

The risk increases if you make the verifier a gate (block output on verification failure). Start with advisory mode: "Verification flagged 1 issue: [description]. Diagnosis produced anyway."

**What DS-STAR got wrong for our case?**

DS-STAR's Verifier checks "did the code answer the question?" -- it's verifying code execution results. Your verifier should check "is the diagnosis internally coherent?" -- it's verifying logical consistency of a structured output. This is actually easier than DS-STAR's problem because your output has a fixed schema with known relationships between fields.

---

## Comparative Scorecard

| Pattern | Applicability | ROI | Implementation Cost | Risk |
|---------|:---:|:---:|:---:|:---:|
| 7-Agent Specialization | 2/10 | Low | High | High |
| Analyzer Pre-Profiling | 5/10 | Medium | Low | Low |
| Verify-Route-Backtrack | 7/10 | High | Medium | Medium |
| Delete & Regenerate | 6/10 | Medium | Low | Low |
| 20-Iteration Budget | 1/10 | Negative | High | High |
| LLM-as-Judge Verification | 9/10 | **Highest** | Low | Low |

---

## The Verdict

### Highest ROI: LLM-as-Judge Verification (9/10)

This solves the specific problem identified in MEMORY.md as a known gap: "no verification of diagnosis correctness." It's cheap to implement (one additional LLM call), low risk (advisory mode, read-only), and catches the exact failure modes your eval has surfaced -- archetype-evidence mismatches, severity-action contradictions, and confidence-evidence inconsistencies.

The implementation path is clean: add a `verify_diagnosis()` function in `diagnose.py` that takes the diagnosis dict, constructs a coherence-checking prompt, and returns a verification result. Wire it into `run_diagnosis()` as a post-processing step. If coherence fails, log the issue but still return the diagnosis (advisory mode).

Over time, you could make this a gate (block incoherent diagnoses and trigger a re-diagnosis with adjusted parameters), which naturally leads into a minimal Verify-Route-Backtrack loop -- but start advisory.

### Waste of Time: 7-Agent Specialization (2/10) tied with 20-Iteration Budget (1/10)

Seven agents solve a problem you don't have (unbounded task diversity) and import problems you don't want (coordination overhead, handoff failures, token cost multiplication). Your tools are deterministic Python functions with clear JSON interfaces. Making them into LLM-powered agents would make them slower, more expensive, and less reliable.

The 20-iteration budget is actively harmful for your use case. Your system's value proposition is fast, confident diagnosis. Iteration budgets are for systems that don't know what they're doing and need to search. Your system knows exactly what it's doing (9 archetypes, 4 validation checks, fixed hypothesis ordering) -- it just needs to verify it did it right.

---

## What DS-STAR Gets Fundamentally Wrong for Enterprise Search Metric Diagnosis

DS-STAR is built for **open-ended data science** -- arbitrary questions on arbitrary datasets. Your system is built for **closed-domain expert reasoning** -- specific questions on known data schemas with domain-encoded heuristics. The architectural implications are opposite:

| DS-STAR's assumption | Your reality |
|---|---|
| Don't know the data schema in advance | Schema is fixed (`tenant_tier`, `ai_enablement`, etc.) |
| Don't know which analysis to run | Analysis pipeline is fixed (decompose, co-movement, diagnose) |
| Need to generate code | Code is pre-written (Python tools) |
| Need to debug code execution failures | Tools are deterministic, tested (433 tests passing) |
| Quality comes from iteration | Quality comes from domain knowledge (archetypes, co-movement table) |
| Broad competence across tasks | Deep competence on one task |

The one thing DS-STAR got right that you should steal: **verify the output before declaring victory.** Everything else is either already in your system in a simpler form, or solving a problem that doesn't apply to closed-domain diagnosis.

---

## Recommended v2 Architecture (If You Wanted to Apply DS-STAR Learnings)

```
[Intake]
  |
  v
[Enhanced Data Quality Gate]  <-- Pattern #2: deterministic pre-profiling
  |                                (5-6 validation rules, not an LLM agent)
  v
[Decompose + Anomaly]         <-- unchanged
  |
  v
[Scored Archetype Matching]   <-- Pattern #4: score all archetypes, not first-match
  |
  v
[Diagnose]                    <-- unchanged
  |
  v
[LLM Coherence Verifier]     <-- Pattern #6: one LLM call checking logical coherence
  |                                (advisory mode, doesn't block)
  +--[if incoherent]----------+
  |                           |
  v                           v
[Format]               [Re-diagnose with       <-- Pattern #3: single retry,
  |                     adjusted parameters]         not 20 iterations
  v                           |
[Output]                      +---> [Format] --> [Output]
```

Total new LLM calls: 1 (the coherence verifier). Total new iterations: at most 1. Total new agents: 0. This captures the best of DS-STAR at minimal cost.
---
---

# Raw Review: Judge 2 — Metric Diagnosis Domain Expert

Now I have a thorough understanding of both your system and the questions you're asking about DS-STAR. Let me write my critique.

---

# DS-STAR Critique: What Transfers to Search Metric Diagnosis and What Doesn't

Here is my unvarnished assessment as someone who has spent the better part of two decades staring at search quality dashboards.

---

## 1. DS-STAR Solves Open-Ended Questions. We Solve Structured Diagnosis. How Much Transfers?

**Short answer: about 30% of DS-STAR's design is relevant. The other 70% is solving problems you don't have.**

DS-STAR's core innovation is handling unbounded analytical questions where the *steps themselves* are unknown. "What's the average revenue for NextPay?" could require joins across 12 tables, currency normalization, date range disambiguation, etc. The Planner generates steps because the step space is combinatorial.

Your problem is the opposite. You have **4 fixed steps** (intake, decompose, validate, synthesize), **4 metrics** (DLCTR, QSR, SAIN trigger, SAIN success), **9 archetypes** in the `ARCHETYPE_MAP`, and **~6 decomposition dimensions** (tenant_tier, ai_enablement, industry_vertical, connector_type, query_type, position_bucket). The problem space is not just constrained -- it is *enumerable*. I can literally count the cells in your hypothesis matrix: 9 archetypes x 6 dimensions = 54 possible diagnosis paths, minus the impossible combinations.

**What transfers genuinely:**
- **The Verifier concept.** DS-STAR's separate verification step maps directly to your validation checks in `diagnose.py` (logging artifact, decomposition completeness, temporal consistency, mix-shift). This is the one thing DS-STAR does that you have already adopted well. Your system checks #1-#4 are a domain-specific verifier.
- **The "code does not guarantee correctness" insight.** Your `run_diagnosis()` produces a structured answer, but the answer might be wrong (first archetype match wins, explained_pct can be inflated by abs-sum). Treating pipeline output as a *hypothesis* to verify rather than ground truth -- that's real.
- **The Debugger's approach of using full context.** When your decomposition returns <70% explained, your system HALTs. DS-STAR would say: "use the full traceback + schema context to diagnose the failure, not just the error code." For you, this means: when completeness HALTs, the HALT itself should carry information about *which dimensions were tried and failed*, not just "add more dimensions."

**What does NOT transfer:**
- **The Router.** DS-STAR routes between Planning, Coding, Debugging, and Verification. Your pipeline is a fixed DAG: decompose -> anomaly -> diagnose -> format. There is nothing to route. Adding a Router would add latency and decision points to a pipeline that should be deterministic given inputs.
- **The Planner's step generation.** Your steps are predetermined. The Planner's value is in *inventing* steps for novel questions. You never have novel questions -- you always ask "Why did metric X move?" with the same set of analytical tools.
- **The Coder agent.** DS-STAR generates SQL and Python on the fly. You have pre-written tools (`decompose.py`, `anomaly.py`). There is no code to generate.

**The honest summary:** DS-STAR is a general-purpose problem solver. Your system is a domain-specific diagnostic engine. You share the verification architecture, but the planning/routing/code-generation machinery is overhead for a constrained problem.

---

## 2. The 20-Iteration Loop: Is This Overkill for 9 Archetypes?

**Yes. Massively overkill. Two rounds with different hypothesis orderings would get you 95% of the benefit.**

DS-STAR needs 20 iterations because open-ended data questions have combinatorial dead ends. A wrong JOIN, a misunderstood schema, an ambiguous column name -- each requires a retry. Their finding that "98% of hard tasks need at least 1 refinement iteration" is about *coding errors*, not *diagnostic errors*.

Your diagnosis has a different failure mode. When `match_co_movement_pattern()` in `anomaly.py` scans the table in order (lines 310-332), it returns the **first match**. If the first match is wrong, iterations 2-20 don't help because the same function will return the same wrong match. The iteration isn't the bottleneck -- the matching algorithm is.

**What your iteration budget should actually be:**

- **Round 1:** Run the full pipeline as-is. This covers 80% of cases correctly (your eval shows 5/5 GREEN at 91.2/100 average).
- **Round 2 (conditional):** Only trigger if confidence is "Low" or explained_pct < 70%. In Round 2, do one of two things:
  1. **Try different dimensions.** If `tenant_tier` didn't explain enough, try `connector_type` or `product_source` as the primary dimension.
  2. **Try the second-best archetype match.** If `ranking_regression` was matched but doesn't fit the evidence, try `behavior_change`.
- **No Round 3.** If two rounds don't converge, HALT with "manual investigation required" -- this is the correct answer for genuinely ambiguous situations.

**Why 2 rounds, not 1 or 3:**
- 1 round fails on multi-cause scenarios (your S7 test case) and novel patterns.
- 3+ rounds adds latency without adding diagnostic information. Your hypothesis space is finite; if you've tried the top 2 hypotheses and neither explains >70%, the third-best is unlikely to be the answer.

**The real insight from DS-STAR here:** Their "delete and regenerate" approach is more valuable than their iteration count. See answer #4 below.

---

## 3. Does Iterative Planning Help When the Pipeline Is Predetermined?

**No for the macro pipeline. Yes for the micro-decisions within diagnosis.**

Your macro pipeline (decompose -> anomaly -> diagnose -> format) should remain fixed. These are not "planned steps" -- they are engineering stages that always run in order. Making them dynamically planned adds fragility with no diagnostic benefit.

But look at **inside `diagnose.py`** -- that is where iterative planning would help. Specifically:

**Where iteration has value:**
- **Archetype selection (lines 1076-1085).** Currently a one-shot lookup. If the first archetype doesn't fit, there is no fallback besides "unknown_pattern." An iterative approach here would try the second-best match.
- **Dimension selection for decomposition.** Your `run_decomposition()` takes a fixed list of dimensions. But the right dimensions depend on the scenario -- a connector outage should decompose by `connector_type`, not `tenant_tier`. An iterative approach would decompose by the co-movement-suggested dimension first, then expand.
- **False alarm detection (lines 1094-1116).** The current logic is a complex conditional chain (path a, path b, noise thresholds, delta guards). This is essentially a hand-coded decision tree. An iterative approach would ask: "Did the false alarm classification survive verification?" and re-check if not.

**Where iteration would hurt:**
- **The format step.** `formatter.py` is a pure template rendering pass. No iteration needed or useful.
- **The decomposition step.** `decompose.py` is a mathematical computation (Kitagawa-Oaxaca). It produces a deterministic result for given inputs. Iterating on it means changing inputs (dimensions), not re-running the same computation.
- **Co-movement matching.** `match_co_movement_pattern()` is a table lookup. Same input always produces same output. Iteration is meaningless unless you change the observed directions (which means re-measuring, not re-planning).

**The architectural implication:** You don't need DS-STAR's Planner. You need a **Retry Controller** that sits inside `run_diagnosis()` and triggers conditional re-analysis when confidence is Low. This is a much simpler abstraction than a general-purpose planning agent.

---

## 4. The "Delete and Regenerate" Insight -- Does This Apply to Archetype Matching?

**This is DS-STAR's single most applicable insight to your system, and it highlights your biggest architectural weakness.**

DS-STAR found that when a plan step produces wrong results, it's better to **delete the step entirely and regenerate from scratch** rather than patching the wrong output. The intuition: a wrong intermediate result poisons all downstream reasoning. Better to start fresh.

In your system, the equivalent is: **if the first archetype match is wrong, you should NOT try the second-best match. You should re-classify the co-movement pattern entirely.**

Here is why. Your `match_co_movement_pattern()` (anomaly.py, lines 307-341) is a linear scan -- first match wins. If it matches `ranking_relevance_regression` but the decomposition shows the drop is in `ai_enablement=ai_on` (suggesting AI adoption, not ranking), your current system will:
1. Use the wrong archetype's template
2. Suggest wrong action items
3. Assign wrong severity

"Trying the second-best match" would mean falling through to the next pattern in the YAML table. But the second pattern might also be wrong -- it is just the second row in a linear scan.

**What "delete and regenerate" means for you:**

1. When validation checks fail (decomposition completeness < 70%, or temporal inconsistency), throw away the archetype classification entirely.
2. Re-run `match_co_movement_pattern()` with **relaxed matching** (e.g., allow "stable_or_down" to match "down") to see if a different pattern emerges.
3. Alternatively, skip co-movement entirely and fall through to **decomposition-first diagnosis** -- let the dimensional data speak instead of the pattern table.

**Concretely, the change would be in `run_diagnosis()` around line 1076:**

Instead of:
```python
likely_cause = co_movement_result.get("likely_cause", "unknown_pattern")
archetype_info = ARCHETYPE_MAP.get(likely_cause)
```

Consider:
```python
likely_cause = co_movement_result.get("likely_cause", "unknown_pattern")
archetype_info = ARCHETYPE_MAP.get(likely_cause)

# DS-STAR "delete and regenerate" pattern: if the archetype doesn't
# survive validation, discard it and re-derive from decomposition alone
if archetype_info and not _archetype_survives_validation(archetype_info, decomposition, all_checks):
    archetype_info = _infer_archetype_from_decomposition(decomposition)
    likely_cause = archetype_info.get("likely_cause", "unknown_pattern") if archetype_info else "unknown_pattern"
```

This is the "regenerate from scratch" pattern -- don't patch the wrong match, derive a new one from different evidence (decomposition instead of co-movement).

---

## 5. What DS-STAR Doesn't Do That Matters for Search Metric Diagnosis

DS-STAR is missing several domain-specific patterns that are essential for search quality work:

**a. Causal ordering within a metric hierarchy.**
DS-STAR treats all data questions as flat. But search metrics have a **causal DAG**: query understanding (L0) -> retrieval (L1) -> reranking (L2) -> interleaving (L3) -> click/engagement. A regression at L0 (query reformulation) cascades to all downstream metrics. Your system captures this in the `hypothesis_priority` ordering (check query_understanding before algorithm_model), but DS-STAR's generic planning has no concept of metric hierarchy. You would lose this if you adopted their Planner wholesale.

**b. The "inverse co-movement is positive" pattern.**
The AI adoption trap (DLCTR goes down because AI answers work = GOOD) is a domain-specific insight that has no analog in DS-STAR. Their Verifier would never learn that "metric went down" can be positive. Your `ARCHETYPE_MAP` with `is_positive: True` and `severity_cap: "P2"` for `ai_answers_working` (diagnose.py line 106) is irreplaceable domain logic.

**c. Mix-shift as a first-class diagnostic outcome.**
DS-STAR doesn't distinguish behavioral change from compositional change. Your Kitagawa-Oaxaca decomposition in `compute_mix_shift()` (decompose.py, lines 250-354) is a methodological contribution that DS-STAR's framework has no slot for. In their world, mix-shift would just be "the answer" -- not a special diagnostic category requiring different action items.

**d. Confidence with actionable upgrade/downgrade conditions.**
Your `compute_confidence()` returns `would_upgrade_if` and `would_downgrade_if` (diagnose.py, lines 453-609). DS-STAR's Verifier returns pass/fail. Your approach is better for stakeholder communication because Eng Leads need to know what would change the assessment, not just whether it passed.

**e. Historical pattern matching.**
Your `historical_patterns.yaml` encodes institutional memory (past incidents, seasonal patterns, diagnostic shortcuts). DS-STAR has no concept of institutional memory -- it approaches each question fresh. For search quality, where the same 5 root causes explain 80% of incidents, historical pattern matching is a massive shortcut.

**f. Stakeholder-aware output formatting.**
Your `formatter.py` generates Slack messages (5-15 lines for Eng Leads) and short reports (1 page for async review). DS-STAR generates a single answer. The multi-format output with audience awareness (TL;DR first, severity emoji, owner on every action) is a production concern that academic systems ignore.

---

## 6. Where DS-STAR's Approach Would Actively Hurt Your System

**a. Latency.**
Your pipeline runs in seconds (decompose + anomaly + diagnose + format on synthetic data). DS-STAR's 20-iteration loop with LLM-in-the-loop planning would take minutes per diagnosis. For a P0 metric drop where the on-call DS needs an answer in 5 minutes, this latency is unacceptable. Your fixed pipeline is fast *because* it's fixed.

**b. Non-determinism.**
Your system is deterministic: same input always produces same output. This is why your eval framework works -- you can score S4/S5/S7/S9/S0 and know the scores are stable. DS-STAR's LLM-based planning introduces non-determinism. Your 91.2/100 eval score would become a distribution (maybe 75-95 range), and debugging regressions becomes much harder.

**c. Over-exploration of obvious cases.**
Your S4 (ranking regression) and S5 (AI adoption trap) are straightforward -- co-movement matches on the first try, confidence is High. DS-STAR's iterative approach would still "plan, execute, observe, plan again" through unnecessary cycles. For the ~80% of incidents that match a known archetype, the first pass is correct. Adding iteration to those cases is pure waste.

**d. Loss of auditability.**
Your `validation_checks` array is a deterministic, auditable trace: 4 checks, each with status and detail. Eng Leads can see exactly why a diagnosis was made. DS-STAR's iterative planning produces a plan history that's harder to audit ("why did the planner delete step 3 and regenerate?"). For a diagnostic tool used by engineering leadership, the ability to explain *every decision* is non-negotiable.

**e. The "novel question" assumption.**
DS-STAR optimizes for questions it has never seen. Your system optimizes for questions it has seen *many times*. The 9 archetypes in your `ARCHETYPE_MAP` are the 9 root causes that explain 95%+ of Enterprise Search metric movements. Treating each diagnosis as a novel open-ended question would be like asking a senior ER doctor to re-derive the diagnosis framework for a broken arm every time.

---

## Bottom Line

DS-STAR is a genuinely good paper for its problem domain (open-ended data science questions). But your problem is not their problem. Here is what to take and what to leave:

**Take:**
1. The **Verifier pattern** -- you already have this as your 4 validation checks. Keep and strengthen it.
2. The **"delete and regenerate" pattern** -- apply it to archetype matching. When the first match fails validation, re-derive from decomposition rather than patching.
3. The **Debugger's full-context approach** -- when your pipeline HALTs, pass the full HALT context (which dimensions were tried, what completeness was achieved) to the recovery path, not just "HALT."

**Leave:**
1. The **Router** -- your pipeline is a fixed DAG, not a state machine.
2. The **20-iteration Planner** -- 2 rounds max, conditional on Low confidence.
3. The **dynamic step generation** -- your steps are predetermined and that's a feature, not a limitation.
4. The **LLM-in-the-loop planning** -- determinism and speed are more valuable than flexibility for a constrained diagnostic domain.

The most dangerous thing you could do is look at DS-STAR's impressive benchmark numbers and conclude "we should adopt their architecture." Their architecture solves open-ended questions where the steps are unknown. Your architecture solves structured diagnoses where the steps are known but the *interpretation* needs intelligence. Those are fundamentally different problems, and the right solution for one is wrong for the other.

If I had to put a number on it: DS-STAR gives you **2 actionable improvements** (Verifier strengthening and delete-and-regenerate for archetype matching) out of their **5 major architectural components** (Router, Planner, Coder, Debugger, Verifier). That's a 40% transfer rate, which is actually pretty good for an academic paper applied to a production domain problem.
---
---

# Raw Review: Judge 3 — Production Engineering Pragmatist

Here is the full critique. I have read every line of your production codebase before rendering judgment.

---

# DS-STAR Paper Critique: Production Readiness Analysis

## 1. ROI Analysis for Each DS-STAR Pattern

### 7 Specialized Agents

**Implementation cost:** 15-20 days. **Ongoing maintenance:** HIGH (7 system prompts, 7 failure modes, version skew). **Expected accuracy improvement for YOUR problem:** NEAR ZERO.

The reason is fundamental: DS-STAR solves open-ended data science tasks (Kaggle-style). You solve a CLOSED problem -- 4 metrics, ~10 archetypes in `ARCHETYPE_MAP` (at `/Users/surahli/Documents/New project/Search_Metric_Analyzer/tools/diagnose.py` lines 87-232), 6 decomposition dimensions, and a finite co-movement diagnostic table (at `/Users/surahli/Documents/New project/Search_Metric_Analyzer/data/knowledge/metric_definitions.yaml` lines 168-272). Your hypothesis space is already enumerated as deterministic Python. No LLM is needed for the core diagnostic logic.

### Verify-Route-Backtrack Loop

**Implementation cost:** 5-8 days for basic, 15+ for robust with circuit breakers. **Latency impact:** SEVERE. DS-STAR averages 5.6 iterations on hard tasks. At ~30s per LLM call, that is 2-3 minutes of pure LLM time before any SQL. For a DS team waiting during an incident, this is unacceptable.

**Verdict: Do not build the full loop.** A single verification pass has merit (see Section 4).

### Analyzer Agent (18pp drop without it -- DS-STAR's highest-value component)

**Implementation cost:** 3-5 days. **Expected improvement for us:** 5-10pp on NOVEL scenarios not in the archetype map. Near-zero on known archetypes.

**Verdict: Partially build, but not as an agent.** The Analyzer's core value is "understand the data schema before writing queries." In your system, this translates to making the skill prompt smarter about which dimensions to decompose -- solvable by improving the YAML config and skill prompt, not by adding an agent.

### Router Agent (5pp drop without it)

**Implementation cost:** 2-3 days. **Expected improvement for us:** NEAR ZERO.

**Verdict: Do not build.** Routing is for heterogeneous task types. You have one task type. Your pipeline at `/Users/surahli/Documents/New project/Search_Metric_Analyzer/tools/diagnose.py` (`run_diagnosis()`, lines 1005-1211) already runs the same 4 checks for every diagnosis. There is nothing to route.

---

## 2. The 4.24pp Improvement Question

The numbers are damning for the complexity:

- Full system (7 agents + loop): 45.24% accuracy on hard tasks
- Simple ReAct baseline: 41.0%
- Delta: 4.24 percentage points at 3.5x token cost

**The Analyzer is doing almost ALL the work.** Without the Analyzer, accuracy drops from 45% to 27% (18pp). Without the Router, it drops to 40% (5pp). The other 5 agents collectively add roughly nothing beyond what the Analyzer and Router contribute.

**For your system specifically:** You are at 91.2/100 on your eval. The gap between 91.2 and 100 is:
- Synthetic data noise (not fixable by architecture)
- Missing real-world calibration (fixable by V1.3 knowledge calibration, already planned in `docs/plans/V1_3_KNOWLEDGE_CALIBRATION_SESSION_PROMPT.md`)
- Edge cases in multi-cause attribution (fixable by better YAML patterns, not more agents)

None of these gaps are addressable by adding agents. They are all addressable by better domain knowledge.

---

## 3. Production Concerns DS-STAR Does Not Address

### Latency SLAs

DS-STAR reports cost but not latency. My estimate: 5.6 iterations x 2.5 LLM calls per iteration x 30s = **7 minutes**. Your current pipeline runs in under 60 seconds of wall clock. For incident response, 7 minutes is unacceptable.

### Reliability

DS-STAR's 7-agent serial chain: if each agent succeeds 95% of the time, chain success rate = 0.95^7 = **69.8%**. Your 4-tool Python pipeline (`decompose.py` -> `anomaly.py` -> `diagnose.py` -> `formatter.py`) has near-100% reliability because the tools are deterministic Python functions with 433 tests passing.

### Observability

Debugging a 7-agent chain with 5.6 iterations means inspecting ~39 LLM calls, each with its own context window. Your system produces a traceable JSON chain: decomposition JSON -> anomaly JSON -> diagnosis JSON -> formatted output. Every intermediate result can be inspected, replayed, and unit-tested.

### Graceful Degradation

When Claude is down: DS-STAR is complete failure. Your system: the Python tools still work. A human DS can run `python tools/decompose.py --input data.csv --metric dlctr_value` manually. The skill prompt is a convenience layer, not a hard dependency.

---

## 4. The MINIMUM Viable Version

The one DS-STAR idea worth stealing:

### A Single Verification Pass (Not a Loop)

Add a `verify_diagnosis()` function to `diagnose.py` -- a Python function, not an agent. It checks:

1. **Archetype-action consistency:** If archetype is `false_alarm`, verify `action_items` is empty. If `ranking_regression`, verify actions mention ranking team.
2. **Confidence-evidence consistency:** If confidence is "High", verify explained_pct >= 90%.
3. **Severity-archetype consistency:** If archetype is `ai_adoption`, verify severity capped at P2.
4. **Multi-cause coherence:** If multi_cause flagged, verify confidence is not "High".

**Cost:** 1 day. ~20 lines of assertion-style checks. No LLM calls. No loops. No non-determinism. Returns a list of contradictions; if any are found, log them and include a caveat in output.

---

## 5. Build vs. Do Not Build

### Solve with Better YAML (not code)
- DS-STAR Analyzer -> Add `recommended_dimensions` per metric in `metric_definitions.yaml`
- DS-STAR Router -> Add `fast_path` patterns in YAML (connector outage shortcut already partially exists in your skill file)
- DS-STAR Reflector -> Add `sanity_check` rules in YAML (compile-time checks, not runtime reflection)

### Solve with Better Prompts (not architecture)
- DS-STAR's 7 system prompts -> Improve the single skill prompt at `/Users/surahli/Documents/New project/Search_Metric_Analyzer/skills/search-metric-analyzer.md`. It is already 336 lines and well-structured. Adding examples is cheaper than adding agents.
- DS-STAR Backtrack -> Add "If first decomposition explains < 70%, try adding connector_type and query_type dimensions" to the skill prompt. This is a prompt instruction, not code.

### Solve with Better Eval (not runtime logic)
- DS-STAR Verifier -> Expand eval from 5 to 15-20 scenarios covering real incident patterns from V1.3 calibration
- DS-STAR Aggregator -> Add adversarial eval scenarios where the correct diagnosis is counter-intuitive

---

## 6. The "7 Agents" Question

You already have the functional equivalents of 6 out of 7 DS-STAR agents, implemented as deterministic Python tools:

| DS-STAR Agent | Your Equivalent |
|---|---|
| Retriever | Coder Agent runs SQL on Databricks |
| Analyzer | YAML metric definitions + skill prompt |
| Solver | `decompose.py`, `anomaly.py` (deterministic Python) |
| Reflector | `diagnose.py` validation checks (4 checks, lines 239-446) |
| Router | Skill prompt linear workflow |
| Verifier | Eval framework (5 scoring specs) |
| Aggregator | `formatter.py` |

You do not need more agent specialization. You need better orchestration of what you already have. The highest-ROI next step is V1.3 knowledge calibration -- real Enterprise Search knowledge will improve diagnosis accuracy more than any architectural change.

---

## Summary Recommendations

| Priority | Action | Cost | Impact |
|---|---|---|---|
| 1 (NOW) | Complete V1.3 knowledge calibration | 2-3 sessions | +5-10 eval points |
| 2 (NEXT) | Add `verify_diagnosis()` Python function | 1 day | Catches self-contradictions |
| 3 (NEXT) | Expand eval from 5 to 15+ scenarios | 2-3 days | Better coverage |
| 4 (LATER) | Add fast-path patterns in YAML | 1 day | Faster common-case diagnosis |
| 5 (LATER) | Data Schema MCP server integration | 2-3 days | Better SQL generation |
| DO NOT BUILD | 7-agent architecture | 15-20 days | Marginal gain, severe complexity |
| DO NOT BUILD | Verify-Route-Backtrack loop | 5-8 days | Latency explosion, non-determinism |

**Bottom line:** DS-STAR is an impressive academic contribution to general-purpose data science agents. But your problem is not general-purpose. You have a closed diagnostic domain with known failure modes, deterministic tools, and a comprehensive eval framework. The highest ROI investment is better domain knowledge, not more agents. The one idea worth stealing is a lightweight verification function -- 20 lines of Python, not a new agent.