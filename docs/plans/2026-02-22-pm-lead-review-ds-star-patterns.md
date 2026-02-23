# PM Lead Review: DS-STAR Patterns vs. Search Metric Debug System

**Date:** February 22, 2026
**Role:** AI PM Lead
**Topic:** Evaluating DS-STAR (Google paper replication) patterns for adoption into the Search Metric Debug System
**Reference:** DS-STAR repo (github.com/MatinKhajavi/DS-STAR), arXiv: 2509.21825

---

## Framing

DS-STAR and the Search Metric Debug System are fundamentally different product archetypes solving different user problems:

| Dimension | DS-STAR | Search Metric Debug System |
|-----------|---------|-------------|
| **User problem** | "Answer this factoid question about this dataset" | "Why did this metric drop and what should we do?" |
| **Reasoning type** | Exploratory data analysis (compute → check → iterate) | Investigative diagnosis (hypothesize → evidence → debate → validate) |
| **Output** | A single answer (string match) | A root cause narrative with actionable recommendations |
| **Quality measure** | Binary correctness (answer matches or doesn't) | Multi-dimensional rubric (analysis rigor + communication + domain accuracy) |
| **Data relationship** | Agent discovers the data structure at runtime | Agent knows the domain deeply (pipeline stages, metric relationships, decomposition trees) |
| **Knowledge** | Zero domain knowledge — general-purpose | Deep domain knowledge — Search pipeline specialist |

**The PM frame:** DS-STAR is a *generalist analyst who's good at any dataset* — think a new-hire DS who can code well but doesn't know the domain. Your system is a *senior DS who's deeply embedded in the Search team* — they know what changed last week, who owns each pipeline stage, and what "normal" looks like. DS-STAR's patterns are most valuable where they address **mechanical execution gaps** in your system, not where they'd dilute the domain-specificity that makes your system valuable.

---

## Dimension 1: Adopt / Skip Analysis

### ADOPT (with adaptation)

#### 1. Iterative Verification Loop → Adapt for Validation Agent (Phase 4)

DS-STAR's Verifier asks "is this sufficient?" after each step. Your architecture has a Validation Agent in Phase 4 that does independent re-derivation, but it runs **once at the end**, not iteratively.

**PM reasoning:** Your Phase 2 investigation agents (Decomposition, Change Detection, Counterfactual) run in parallel and produce findings. Currently, the first quality gate is Phase 3 (Debate) or Phase 4 (Validation). DS-STAR's pattern suggests a **per-step sufficiency check** — after each decomposition level, ask "have we explained enough of the drop?" Your spec already has this in the Decomposition Completeness Check (≥90% threshold), but it's a post-hoc validation, not an iterative control.

**Recommendation:** Add an **inline verification checkpoint** to the Decomposition Agent. After each decomposition level, check: "Does the biggest mover at this level explain ≥70% of the remaining drop?" If yes, stop drilling (depth calibration). If no, go deeper. This is DS-STAR's verify-then-continue pattern, adapted to your decomposition context. You already have the `--depth` parameter (shallow/standard/deep) — this makes depth **adaptive** rather than preset.

**Risk:** Over-engineering. The `--depth` presets might be "good enough" for v1. **Recommendation: defer to v1.5** unless testing reveals depth calibration is a frequent failure mode.

---

#### 2. Backtracking / Router → Adapt for Hypothesis Pruning

DS-STAR's Router can say "Step 3 was wrong, remove it and rebuild." Your system has the Debate phase (AGREE/DISAGREE/EXTEND) which serves a similar purpose — hypotheses get challenged and rejected.

**PM reasoning:** These solve the same problem (self-correction when the analysis goes wrong) through different mechanisms. DS-STAR backtracks mechanically (remove step, rebuild code). Your system backtracks through argumentation (specialists challenge each other with evidence). Your mechanism is **better for your use case** because investigative root-cause analysis requires *reasoning about why a path was wrong*, not just removing it.

**However:** Your current architecture has no mechanism for **Phase 2 self-correction**. If the Decomposition Agent goes down a wrong path (e.g., decomposes by platform when the issue is connector-specific), there's no backtracking until Phase 3 Debate. DS-STAR's pattern suggests the investigation agents themselves should have a mini-verification step.

**Recommendation:** Add a lightweight "direction check" after Level 2 decomposition: "Is the biggest segment at Level 2 consistent with the triage hypothesis?" If the triage said "likely Connector issue" but decomposition shows the drop is uniform across all connector vs. organic results, flag it early rather than waiting for Debate. **This is a v1 candidate** — it's cheap (one LLM call) and prevents wasted investigation depth.

---

#### 3. Description Caching (Data Profiling) → Adopt for Data Quality Pre-Flight

DS-STAR runs an Analyzer agent that profiles each data file once and caches the result. When running 450 tasks against the same files, this avoids redundant work.

**PM reasoning:** Your system's equivalent is the Domain Knowledge Skill — it's the "cached understanding" of the Search pipeline. But DS-STAR's pattern suggests something you're missing: **profiling the actual metric data** before investigation begins. Your Metric Intake Agent (Phase 0) classifies the drop, but it doesn't profile the data shape (distribution, outliers, missing values, time range).

**Recommendation:** Add a **data profiling step** to Phase 0 Metric Intake. Before hypothesizing, the agent should understand: what's the data shape, are there obvious data quality issues (nulls, duplicates, coverage gaps), what's the baseline period look like? This is distinct from domain knowledge (which is about the *system*) — it's about the *data quality* of the specific metric investigation. **v1 candidate.**

---

#### 4. Incremental Result Saving → Adopt for Investigation Logging

DS-STAR writes results to JSONL after each task. Your auto-eval plan mentions prompt logging, but the architecture spec doesn't specify logging granularity during a single investigation.

**PM reasoning:** A metric debug investigation can take 8-18 API calls across 6 phases. If it fails at Phase 4, you want to see everything that happened in Phases 0-3 without re-running.

**Recommendation:** Add **per-phase state snapshots** to the debug-architect orchestrator. After each phase checkpoint, serialize the current state (triage output, hypotheses, investigation findings, debate outcome) to a structured log. Serves: (1) debugging failed runs, (2) audit trail for auto-eval LLM-as-judge, (3) human review. **v1 candidate.**

---

#### 5. Prompt Logging for Auditability → Adopt

DS-STAR logs every LLM call with timestamps and agent names. Your auto-eval plan requires investigation traces but doesn't specify how they're captured.

**Recommendation:** Part of per-phase state snapshots (#4 above). **v1 candidate.**

---

### SKIP (not relevant to your design)

#### 6. Code Execution Sandbox → Skip

DS-STAR uses `exec()` with stdout capture and SIGALRM timeout. Your system's investigation agents generate SQL for Databricks, not arbitrary Python scripts. Execution layer is Databricks MCP, not a code sandbox.

#### 7. Multi-Provider LLM Abstraction → Skip

DS-STAR supports Gemini, OpenAI, and Anthropic. Your system runs on Claude Code with Opus 4.6 — the LLM provider is fixed by the platform.

#### 8. General-Purpose Data Profiling (Analyzer Agent) → Skip in current form

Your system already has deep domain knowledge about Search metrics — you know what the data looks like before you start. The general profiler adds value for DS-STAR because it has zero domain knowledge. Adopt the targeted data quality check (#3 above) instead.

#### 9. Finalizer Agent (Output Formatting) → Skip

Your Communication Standards skill (7-field actionable recommendations, confidence calibration, audience awareness, anti-patterns) is far more sophisticated than DS-STAR's Finalizer.

---

## Dimension 2: DABStep as Testbed Viability

**Short answer: No, DABStep is not a useful testbed for your system.**

| Aspect | DABStep | Your System |
|--------|---------|-------------|
| **Question type** | Factoid ("What is the average fee?") | Investigative ("Why did QSR drop?") |
| **Evaluation** | Exact string match | Multi-dimensional rubric |
| **Data** | Payment transactions — unrelated to Search | Search pipeline metrics via Databricks |
| **Reasoning depth** | Shallow (compute → verify → answer) | Deep (hypothesize → debate → validate → synthesize) |

DABStep tests general-purpose data wrangling. Your system needs to test investigative reasoning with domain context. Your auto-eval plan (3-layer: SQL correctness → Investigation quality MVE → Full regression suite) is already better designed for your needs.

**One borrowable element:** The approach of human-authored YAML scoring specs per case — which you've already designed in the auto-eval plan.

**Verdict: Don't adopt DABStep. Stick with your auto-eval plan.**

---

## Dimension 3: Architecture Gap Analysis

### Gap 1: No explicit iteration budget or convergence mechanism

DS-STAR has `max_rounds=20`. Your spec says Phase 4 Validation "failure sends back to Phase 3" — but no max loop count.

**Risk:** Phase 3↔4 ping-pong, silent cost burn.

**Recommendation:** Add `--max-validation-retries 2` (default: 2). After 2 retries, force "INCONCLUSIVE" output. **v1 must-have.**

### Gap 2: No data quality pre-check before investigation

DS-STAR's Analyzer profiles data before analysis. Your Logging Artifact Detection check triggers in Phase 4, not Phase 0.

**Risk:** Agent spends 6 phases investigating a logging artifact.

**Recommendation:** Promote Logging Artifact Detection to **Phase 0 as pre-flight check**. Before hypothesizing, check for logging pipeline deploys, sampling rate changes, metric definition changes. **v1 must-have.**

### Gap 3: No explicit state model for the investigation

DS-STAR has `IterationState` dataclass capturing full snapshots. Your phase outputs are described in prose, no structured schema.

**Risk:** Debugging failed investigations is hard. Auto-eval requires "investigation traces" without defining the data structure.

**Recommendation:** Define a structured investigation state model:

```yaml
investigation_state:
  triage: {metric, pipeline_stage, personas, co_movements}
  hypotheses: [{id, statement, category, confidence, domain_grounding}]
  investigation: {decomposition_results, change_detection_results, counterfactual_results}
  debate: {surviving_hypotheses, rejected_hypotheses, proposed_root_cause}
  validation: {checks_passed, checks_failed, residual_percentage}
  synthesis: {root_cause, confidence, recommendations}
```

Serves as: (1) contract between phases, (2) investigation trace for auto-eval, (3) audit log for human review. **v1 must-have.**

### Gap 4: No cost tracking or token budget enforcement

Your system has cost management table and domain knowledge token budgets (~51.5k total). No mechanism to **enforce** these budgets.

**Recommendation:** Add cost checkpoint to debug-architect orchestrator. After each phase, tally actual token usage against budget. Warn if phase exceeds 150% of budget. **v1 nice-to-have, v1.5 must-have.**

### Things you already have that DS-STAR lacks

- **Domain knowledge integration** — DS-STAR has zero
- **Communication quality** — 7-field actionable recommendations vs. a string
- **Self-correction through reasoning** — Adversarial debate vs. mechanical backtracking
- **Evaluation framework** — Multi-dimensional rubric vs. binary exact-match
- **Downstream quality gate** — Phase 6 Review Agent vs. nothing

---

## Decision Matrix

| DS-STAR Pattern | Verdict | Priority | Rationale |
|----------------|---------|----------|-----------|
| Iterative verification (Verifier) | **Adapt** → inline decomp checkpoint | v1.5 | `--depth` presets may suffice for v1 |
| Backtracking (Router) | **Adapt** → direction check after Level 2 | v1 | Cheap early-warning for wrong path |
| Data profiling (Analyzer) | **Adapt** → data quality pre-flight Phase 0 | v1 | Catches logging artifacts early |
| Incremental saves | **Adopt** → per-phase state snapshots | v1 | Essential for auto-eval |
| Prompt logging | **Adopt** → part of state snapshots | v1 | Audit trail for LLM-as-judge |
| Code execution sandbox | **Skip** | — | Uses Databricks MCP |
| Multi-provider LLM | **Skip** | — | Claude Code native |
| General data profiling | **Skip** | — | Domain knowledge already provides |
| Finalizer | **Skip** | — | Communication Standards better |
| DABStep benchmark | **Skip** | — | Wrong problem type |
| Max iteration budget | **New gap** | v1 | Prevents infinite loop |
| Structured state model | **New gap** | v1 | Phase contract + auto-eval dependency |
| Cost tracking | **New gap** | v1.5 | Budget enforcement |

---

## Bottom Line

DS-STAR confirms the multi-agent phased approach is the winning pattern. But its contributions to your system are **operational, not architectural**: state management, iteration budgets, logging, and early-exit checks. Your intellectual core (domain knowledge, debate, validation rules, communication standards) is already superior. Think of DS-STAR as offering plumbing improvements, not blueprint changes.
