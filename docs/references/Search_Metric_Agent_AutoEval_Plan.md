# Auto-Eval Plan: Search Metric Analysis Agent

**Evaluation Framework for Multi-Step Investigation Agents**
February 2026 | Status: Draft for Review

---

## 1. Executive Summary

This document defines the automated evaluation framework for the Search Metric Analysis Agent — an AI system that investigates metric movements across Search pipeline components (Query Understanding, Retrieval, Ranking, Interleaver, Third-Party Connectors, Search Experience).

### The Core Problem

SQL eval has clean ground truth: a query either returns the expected results or it doesn't. Investigation eval is fundamentally messier. The agent's value lies in multi-step reasoning — choosing the right hypotheses, decomposition dimensions, and causal analysis — not just writing correct SQL. Evaluating only SQL correctness is like testing a doctor by checking their lab order form while ignoring whether they ordered the right tests.

### Design Principles

- **Human-authored, machine-applied:** Senior DS judgment is captured once per eval case in a scoring spec, then applied automatically by LLM-as-judge on every run.
- **Tripwire, not benchmark:** The eval catches catastrophic regressions, not subtle quality gradients. 3 well-chosen cases beat 50 poorly-designed ones.
- **Layer separation:** Tool correctness (SQL) and reasoning correctness (investigation quality) are evaluated independently because they have different failure modes.
- **Non-determinism tolerance:** The agent's output is non-deterministic by design. The eval uses multiple runs with aggregate scoring rather than brittle single-run pass/fail.

---

## 2. Eval Architecture: Three Layers

The eval framework consists of three layers, each targeting different failure surfaces. Layers are additive — a higher layer doesn't replace lower ones.

| Layer | What It Tests | Scoring Method | Failure Modes Caught | Cost / Run |
|-------|--------------|----------------|---------------------|------------|
| **Layer 1: SQL Correctness** | Can the agent write valid, semantically correct SQL against known schemas? | Binary: query output matches expected result set | Schema errors, syntax bugs, wrong table joins | Low (Databricks query only) |
| **Layer 1.5: Investigation Quality (MVE)** | Can the agent reach a defensible conclusion through proper decomposition? | Structured rubric via LLM-as-judge (3 runs, majority vote) | Wrong hypothesis, premature stopping, causal overclaim, missed decomposition | Medium (agent run + LLM judge) |
| **Layer 2: Full Regression Suite (Future)** | Comprehensive coverage across 24+ historical SEVs + perturbation cases | Full rubric with LLM-as-judge + quarterly human calibration | All Layer 1.5 + pattern matching vs. genuine reasoning (via perturbations) | High (24+ cases × 3 runs each) |

---

## 3. Scoring Criteria

Each eval case is scored across three dimensions. These dimensions are evaluated independently because an agent can succeed on one while failing on another.

### 3.1 Required Findings (Binary, Automatable)

These are hard requirements. A case fails if any required finding is missed.

- **Root cause identification:** Did the agent arrive at the known root cause? Scored as semantic match via LLM-as-judge against a set of acceptable phrasings (not string match). The agent may phrase the conclusion differently than the human DS — that's acceptable as long as the meaning is equivalent.
- **Critical dimensions checked:** Did the agent examine the minimum required slices? Expressed as a checklist of dimensions that must appear in the investigation trace (e.g., connector_id, date grain, latency metric). The agent may check additional dimensions — that's fine. Missing a required dimension is a failure.

### 3.2 Investigation Quality (Rubric-Scored, LLM-as-Judge)

These criteria address the messier aspects of investigation quality. Each is scored on a 3-point scale.

| Criterion | Pass (2) | Partial (1) | Fail (0) |
|-----------|----------|-------------|----------|
| **Hypothesis Quality** | Generated multiple competing hypotheses and tested each against evidence | Generated hypotheses but didn't test all, or tested only the first plausible one | Jumped to a single hypothesis without considering alternatives |
| **Decomposition Path** | Chose dimensions that efficiently isolate the root cause, even if different from the human DS path | Chose reasonable but inefficient dimensions requiring extra steps to reach conclusion | Investigated irrelevant dimensions or failed to decompose at all |
| **Depth Calibration** | Stopped at the right level of depth — sufficient evidence to support conclusion without unnecessary drilling | Slightly too shallow (missing one confirming check) or too deep (unnecessary queries after answer was clear) | Stopped prematurely with insufficient evidence, or went far too deep without convergence |
| **Confidence Calibration** | Confidence level matches evidence strength (HIGH when data is conclusive, MEDIUM when ambiguous) | Slightly miscalibrated but direction is correct | Claimed HIGH confidence with weak evidence, or LOW confidence with conclusive evidence |

### Scoring Edge Cases

- **Different path, correct answer:** Not penalized. The rubric scores evidence sufficiency, not path replication. A different decomposition that reaches the correct root cause with adequate evidence is a full pass.
- **MEDIUM vs. HIGH confidence:** Depends on evidence strength per case. The scoring spec includes an "appropriate confidence range." If available data genuinely supports HIGH, MEDIUM is a minor deduction. If data is ambiguous, MEDIUM is more correct than HIGH.
- **Novel secondary finding:** Scored as a bonus signal, never penalized if absent. Findings outside the "known findings" list are flagged for human review — this is how the agent adds value beyond replay.

### 3.3 Anti-Patterns (Binary, Automatable)

These are investigation failure modes that can be detected programmatically from the investigation trace. Any anti-pattern triggers a flag.

- **Premature stopping:** Concluded after finding the first correlate without testing alternative explanations.
- **Causal overclaim:** Stated causation (e.g., "X caused the drop") without decomposition evidence showing contribution.
- **Irrelevant investigation:** Spent significant effort on dimensions unrelated to the metric in question.
- **Archive anchoring:** Conclusion mirrors a known SEV without evidence from current data supporting the match (detectable via perturbation cases).

---

## 4. Eval Set Collection

### 4.1 Historical Cases (Ship with v1)

**Source:** SEV archive with 24 incidents with documented root causes, plus M2 stage investigation outputs with cross-validation findings.

#### Case Selection for MVE (3 Cases)

Select 3 cases representing distinct investigation archetypes to maximize coverage across failure modes:

| Archetype | Selection Criteria | What It Validates |
|-----------|--------------------|-------------------|
| **Single-Cause, Clean Signal** | SEV with obvious metric cliff, single root cause (e.g., connector timeout). Data shows clear before/after pattern. | Agent can follow a straightforward investigation to a clean conclusion. Baseline capability — if this fails, everything is broken. |
| **Multi-Factor** | SEV where metric moved due to two or more overlapping causes. Requires decomposition to separate contributions. | Agent can handle complexity, doesn't anchor on first finding, properly attributes partial contributions. |
| **False Alarm** | Metric movement that was expected or seasonal. Correct answer is "no action needed." | Agent doesn't overclaim. Can recognize when a metric movement is not anomalous. Tests restraint, not just detection. |

#### Authoring Lightweight Scoring Specs

Each case requires a scoring spec authored by a senior DS. Target: ~15 minutes per case (not the full 30–60 min rubric). The spec captures:

- **Must-find root cause:** 1–2 sentences with 2–3 acceptable phrasings for semantic match.
- **Must-check dimensions:** 3–5 required slices as a checklist.
- **Must-not-do anti-patterns:** 2–3 binary flags specific to this case.
- **Appropriate confidence range:** What confidence level the evidence supports (e.g., HIGH for clean cases, MEDIUM for ambiguous).

#### YAML Spec Format

```yaml
case_id: sev-012-connector-timeout
entry_question: "Why did QSR drop the week of April 17?"
data_window: "2024-04-14 to 2024-04-21"

scoring:
  root_cause:
    acceptable_conclusions:
      - "3P connector timeout caused QSR degradation"
      - "Connector X latency spike reduced search quality"
    match_type: semantic

  required_dimensions:
    - connector_id
    - date (daily grain minimum)
    - latency or timeout metric

  anti_patterns:
    - premature_stopping
    - causal_overclaim

  confidence_range: [HIGH]

run_config:
  n_runs: 3
  pass_threshold: 2
  timeout_minutes: 10
```

### 4.2 Synthetic / Perturbation Cases (Post-v1)

**Purpose:** Distinguish genuine reasoning from pattern matching against the SEV archive. These cases are deferred from v1 because they require solving the data mutation problem (Databricks production tables cannot be altered).

#### Three Approaches to Synthetic Cases

**Approach 1 — Synthetic Perturbations on Real Cases:** Take a known SEV but mutate the data so the root cause is different while surface symptoms are similar. If the agent still concludes the original root cause, it's pattern matching. Example: replay SEV-012's metric drop but inject data where the connector is healthy and the actual cause is a ranking model regression.

**Approach 2 — Chimera Cases:** Combine elements from two unrelated SEVs into a scenario that has no single archive match. Forces the agent to decompose rather than retrieve.

**Approach 3 — Ablation Eval:** Run the same case twice — once with full archive context, once with archive stripped. Compare not just the final answer but the investigation trace. If the reasoning steps are substantively identical, the agent is reasoning from data. If the no-archive version collapses, memorization dependency is confirmed.

#### Data Mutation Strategy

Since production Databricks tables cannot be altered, synthetic cases require one of the following approaches:

- **Shadow tables:** Create a parallel set of tables with mutated data in a dev/staging Databricks workspace. Agent MCP schema points to shadow tables during eval.
- **Query interception layer:** Intercept the agent's SQL at execution time and rewrite table references to point to pre-staged synthetic datasets.
- **Mock data layer:** For pure reasoning tests, provide the agent with pre-computed query results rather than live Databricks access, eliminating compute cost entirely.

### 4.3 Production Feedback Loop (Ongoing)

The most sustainable source of new eval cases is production usage itself.

- **Override logging:** Every investigation where a human DS overrides the agent's conclusion becomes a candidate eval case.
- **Case promotion:** Quarterly, review overrides and promote the most informative ones to the eval suite. Each requires one senior DS pass (~15 min) to create the scoring spec.
- **Novel case coverage:** This is the only realistic path to evaluating the agent on genuinely novel movements — you can't synthetically generate scenarios you've never seen.

---

## 5. Execution Mechanics

### 5.1 Handling Non-Determinism

The agent's output is non-deterministic by design — it freely chooses hypotheses, SQL, and decomposition paths. A single-run pass/fail eval will produce flaky results that erode trust. The team will start ignoring red results because "it probably just took a weird path." That's worse than no eval.

Each case runs 3 times with aggregate scoring via majority vote:

| Result | Interpretation | Action |
|--------|---------------|--------|
| **3/3 pass** | Agent reliably handles this archetype | 🟢 Green — no action |
| **2/3 pass** | Non-determinism is causing outcome variance — investigate which path fails and why | 🟡 Yellow — investigate |
| **0–1/3 pass** | Genuine regression or capability gap | 🔴 Red — block deployment |

### 5.2 LLM-as-Judge Configuration

The judge LLM scores each agent run against the case's scoring spec. To minimize judge non-determinism (separate from agent non-determinism):

- **Temperature 0:** on the judge call. All creative variance belongs to the agent; the judge should be boring and consistent.
- **Structured output:** Judge returns a JSON object with scores per criterion, not free-text assessment.
- **Rubric-in-prompt:** The case's scoring spec is included verbatim in the judge prompt. The judge evaluates against explicit criteria, not vibes.
- **Separate model:** Use a different model or at minimum a separate API call for judging. Never have the agent self-evaluate.

### 5.3 Run Cadence and Triggers

This eval is not a CI/CD gate on every PR. It's a regression suite with the following run cadence:

| Trigger | What Runs | Expected Duration |
|---------|-----------|-------------------|
| **Agent logic change** | Full suite: Layer 1 (6 YAML) + Layer 1.5 (3 cases × 3 runs) | ~15–50 min (parallelizable) |
| **Weekly canary** | Layer 1.5 only (3 cases × 3 runs) | ~10–45 min |
| **On-demand** | Specific cases as needed for debugging | Variable |

### 5.4 Cost Management

Each full eval run costs real Databricks compute and LLM tokens. For the MVE:

- **Databricks:** 9 investigation runs (3 cases × 3 runs), each executing multiple SQL queries.
- **LLM tokens:** 9 agent investigation runs (sub-agent SQL + finding generation) + 9 LLM-as-judge calls.
- **Estimated cost per full suite:** Approximately $5–15 in LLM costs + Databricks compute, depending on investigation depth.

As the suite expands to 24+ cases, monitor which cases exhibit stable results across runs. Cases with consistent 3/3 pass rates can drop to 1 run, reserving 3 runs for volatile cases.

---

## 6. What This Eval Does and Doesn't Tell You

| This Eval Validates | This Eval Does Not Validate |
|--------------------|-----------------------------|
| The agent's SQL tool-use substrate works correctly | Performance on genuinely novel metric movements never seen before |
| The agent can reach correct conclusions on known archetypes (single-cause, multi-factor, false alarm) | Subtle quality differences between good and great investigations |
| Code changes haven't introduced catastrophic regressions | Whether the agent genuinely reasons vs. pattern-matches (until perturbation cases are built) |
| The agent doesn't exhibit known anti-patterns (premature stopping, causal overclaim) | Communication quality of the final finding.md (deferred to separate eval dimension) |

This is a deliberate scope choice. The MVE is a tripwire for reasoning regressions, not a comprehensive benchmark. Novel-case performance is the least validated capability, and the team should set expectations accordingly. Production monitoring with human override logging is the path to closing this gap over time.

---

## 7. Implementation Roadmap

| Phase | Deliverable | Effort | Dependency | Timeline |
|-------|-------------|--------|------------|----------|
| **Phase 1** | Layer 1: 6 YAML SQL-correctness benchmarks (already built) | Done | None | Complete |
| **Phase 2** | Layer 1.5 MVE: 3 golden investigation cases with lightweight scoring specs + eval runner | ~2 hours eng + 45 min senior DS (15 min × 3 specs) | Senior DS availability | This sprint |
| **Phase 3** | Expand to 24 historical cases with full scoring specs | ~2–3 days senior DS (30–60 min × 24 specs) | Phase 2 validated | Next quarter |
| **Phase 4** | Perturbation suite: 5–8 synthetic mutations for reasoning validation | ~1 week eng (data mutation infrastructure) + DS case design | Shadow table / mock data infrastructure | Q3+ |
| **Ongoing** | Production feedback loop: promote human overrides to eval suite quarterly | ~15 min per new case (senior DS) | Override logging in production | Continuous |

---

## 8. Appendix: Reasoning vs. Pattern Matching

A key tension in evaluating investigation agents: the SEV archive and playbooks are literally in the agent's context. An agent could score perfectly on historical cases by memorizing the archive rather than reasoning from evidence.

Production metric movements fall into three buckets with different implications for this tension:

- **Recurrences (~40–50%):** Same root cause seen before. Pattern matching against the archive is the correct strategy. We want the agent to say "this looks like SEV-017."
- **Analogues (~30–40%):** Novel surface symptom, but underlying mechanism maps to a known archetype. Reasoning by analogy from the archive is legitimate and valuable.
- **Genuinely novel (~10–20%):** Root cause never encountered. Pattern matching fails catastrophically. This is where the agent's value is highest but our eval confidence is lowest.

The MVE (Phase 2) primarily validates buckets 1 and 2. The perturbation suite (Phase 4) targets bucket 3. Production monitoring targets all three with real-world ground truth. This layered approach matches eval sophistication to the realistic shipping timeline rather than blocking deployment on a fully-solved eval for the hardest 10–20% of cases.
