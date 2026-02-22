# Session Log: Search Metric Analysis Agent — Eval Design Discussion

**Date:** February 21, 2026
**Participants:** Sarah (DS Lead) + Principal AI Engineer (interviewer)
**Format:** 5-round Socratic design discussion on building auto-eval for a multi-step investigation agent

---

## Context

The discussion centers on building evaluation for a Search metric movement/analysis agent — a system that investigates why metrics moved across Search pipeline components. The principal AI engineer challenges the eval design through increasingly specific questions, stress-testing whether the proposed framework handles the real complexity of evaluating open-ended, multi-step reasoning tasks.

---

## Round 1: The Fundamental Failure Mode

### Question

You are building eval for an agent that investigates metrics movement, a fundamentally open-ended, multi-step reasoning task. The original plan has you writing 6 YAML benchmarks that store expected-sql and question pairs, which is the same format as the downstream agent (which can call Databricks, have table schema MCP, can run SQL) whose eval is single-turn SQL eval. So what failure mode are you most worried about in production, and does a SQL-correctness benchmark actually catch it?

### Response

**The failure mode I'm most worried about is *wrong investigation strategy*, not wrong SQL.**

A metric movement agent fails in production when it:

1. **Asks the wrong questions** — e.g., revenue dropped but the agent investigates user counts instead of ARPU
2. **Stops too early** — finds a correlate and declares it causal without drilling further
3. **Misses the right decomposition** — doesn't slice by the dimensions that actually explain the movement
4. **Draws incorrect causal conclusions** — confuses correlation with contribution

**Does SQL-correctness catch it?** No. A SQL-correctness benchmark validates the *last mile* — can the agent write a syntactically and semantically correct query against a known schema. That's necessary but deeply insufficient. You can write perfect SQL for the completely wrong investigation path. It's the equivalent of evaluating a doctor by checking whether they filled out the lab order form correctly, while ignoring whether they ordered the right tests.

**Recommendation:** A two-layer eval:

- **Layer 1 (keep, cheap):** SQL correctness — the YAML benchmarks. Validates the tool-use substrate works.
- **Layer 2 (build, critical):** Investigation quality — evaluated against curated case studies of known metric movements with documented root causes. Score on decomposition quality, hypothesis generation, root cause accuracy, and depth calibration.

### Interviewer Feedback

Acknowledged the two-layer distinction and the importance of evaluating reasoning, not just tool use.

---

## Round 2: Memorization vs. Genuine Reasoning

### Question

You said Layer 2 should evaluate against "curated case studies of known metric movements with documented root causes." You already have raw materials — the SEV archive has 24 incidents with documented root causes, and M2 produced full investigations with cross-validation findings.

But here is a tension: an investigation agent's value is precisely that it can handle novel movements — ones DS has never seen before. If you only eval against historical cases where the root cause is already known, you are testing pattern matching against your own training data. The SEV archive and playbook are literally in the agent's context. The agent could score perfectly on Layer 2 by memorizing the archive rather than reasoning from evidence.

How do you distinguish between an agent that is genuinely reasoning from data versus one that's just pattern matching against the SEV archive — and does that distinction even matter for your use case?

### Response

**Yes, the distinction matters — but not equally across all cases.**

Production metric movements fall into three buckets:

- **Recurrences (~40–50%):** Same root cause seen before. Pattern matching is *the correct strategy*.
- **Analogues (~30–40%):** Novel surface symptom, known underlying mechanism. Reasoning by analogy from archive is legitimate.
- **Genuinely novel (~10–20%):** Root cause never encountered. Pure pattern matching fails catastrophically. Highest-stakes but smallest bucket.

**The memorization problem is real but testable via three approaches:**

1. **Synthetic perturbations:** Take a known SEV, mutate the data so the root cause is different while surface symptoms are similar. If the agent still concludes the original root cause, it's pattern matching.
2. **Chimera cases:** Combine elements from two unrelated SEVs into a scenario with no single archive match.
3. **Ablation eval:** Run the same case with and without archive context. Compare investigation traces, not just conclusions.

**Pragmatic counterpoint:** For v1, pattern matching that covers buckets 1 and 2 is already enormously valuable (80–90% of incidents). Novel-case eval is the least validated capability — be transparent about this and let production monitoring close the gap.

### Interviewer Feedback

"The three-bucket framing is honest and the shipping strategy is pragmatic — don't let perfect novel-case coverage block a system that handles 80–90% of real incidents."

---

## Round 3: How Do You Actually Score Investigation Quality?

### Question

You've defined *what* to evaluate against (historical SEVs, synthetic perturbations, production feedback) but haven't defined *how to score it*. SQL eval has clean ground truth — the expected query either returns the same results or it doesn't. Investigation eval is fundamentally messier.

Take Layer 2a: you run the agent against SEV-012 (connector timeout). The agent produces a finding.md. You said score on "right decomposition, competing hypotheses, correct root cause, right depth." But consider:

- The agent might identify the correct root cause via a *different* decomposition path than the human DS originally took — is that a pass or a fail?
- The agent might identify the correct root cause but with MEDIUM confidence instead of HIGH — is that a penalty or actually more appropriate?
- The agent might surface a *secondary* finding the human DS missed — how do you score that?

Investigation quality isn't a single scalar. It's a multi-dimensional judgment that currently lives entirely in a senior DS's head.

What does the scoring rubric for a Layer 2 eval case concretely look like — and can it be applied by something other than a senior DS reviewing every run, or does this eval fundamentally require a human in the loop?

### Response

**Yes, this eval fundamentally requires human judgment — but not on every run.**

The goal is to convert senior DS judgment into a reusable rubric *once per case*, then automate scoring against that rubric. Human-in-the-loop at authoring time, not at evaluation time.

**Concrete rubric structure per case — three components:**

**1. Required Findings (binary, automatable):**
- Root cause identification via semantic match (LLM-as-judge, not string match)
- Critical dimensions checked (checklist)

**2. Investigation Quality (rubric-scored, LLM-as-judge):**
- Hypothesis quality, decomposition path, depth calibration, confidence calibration
- Each on a 3-point scale (Pass/Partial/Fail)
- Edge cases addressed directly:
  - Different path, correct answer → not penalized (score evidence sufficiency, not path replication)
  - MEDIUM vs HIGH confidence → depends on evidence strength per case (scoring spec includes "appropriate confidence range")
  - Novel secondary finding → scored as bonus signal, flagged for human review

**3. Anti-Patterns (binary, automatable):**
- Premature stopping, causal overclaim, irrelevant investigation

**Scaling model:**
- Authoring cost: Senior DS writes scoring spec once per case (~30–60 min)
- Run cost: Fully automated via LLM-as-judge after that
- Calibration cost: Senior DS reviews ~10–15% of judge scores quarterly

This is a **human-authored, machine-applied** eval pattern.

### Interviewer Feedback

"That's a well-structured answer. The 'human at authoring time, LLM at evaluation time' pattern is the right tradeoff for this domain. And 32 cases is a meaningful regression suite — you're not trying to build a benchmark leaderboard, you're trying to catch regressions."

---

## Round 4: Minimum Viable Eval Under Real Constraints

### Question

Let's shift from the ideal to the practical. You've designed a sophisticated three-layer eval (SQL benchmarks, historical SEVs with rubrics, perturbation suite). The scoring spec per case requires ~30–60 min of senior DS time. The perturbation cases require even more — you need to figure out how to "mutate the data" when the data lives in Databricks and you can't actually alter production tables.

Meanwhile, you're in Session 8 of building this agent. M0 and M2 are done. The Confluence refresh pipeline (M1) hasn't started. The sub-agent reliability bug is still open. And the user just told me to execute a 5-task plan that includes a real 3P investigation, an MCP fallback test, and eval framework creation — all in one session.

Given that the full Layer 2 eval requires authoring 24+ scoring specs and solving the synthetic data problem — neither of which can happen in this session — what is the minimum viable eval you'd actually ship today that still gives you a meaningful quality signal, and how does it differ from the 6 YAML benchmarks in the current plan?

### Response

**3 cases, 2 layers, zero synthetic data. Built in ~2 hours.**

- **Layer 1 (keep as-is):** 6 YAML SQL-correctness benchmarks. Already built.
- **Layer 1.5 (new, the actual MVE):** 3 "golden investigation" cases — not 24.

**Case selection — 3 archetypes for maximum coverage:**
1. Single-cause, clean signal (baseline capability)
2. Multi-factor (complexity handling)
3. False alarm (restraint, not just detection)

**Lightweight scoring spec per case (~15 min each, not 30–60 min):**
- Must-find root cause (1–2 sentences, semantic match)
- Must-check dimensions (3–5 required slices)
- Must-not-do anti-patterns (2–3 binary flags)

**Key difference from YAML benchmarks:**

| Dimension | YAML Benchmarks | MVE Layer 1.5 |
|-----------|----------------|---------------|
| What's tested | Can the agent write correct SQL | Can the agent reach a defensible conclusion |
| Eval unit | Single query → result match | Full investigation trace → finding quality |
| Scoring | Binary (match/no-match) | Structured rubric via LLM-as-judge |
| Failure modes caught | Broken tool use, schema errors | Wrong hypothesis, premature stopping, missed decomposition |

The YAML benchmarks tell you the *hands* work. The MVE tells you the *brain* works.

**Explicitly deferred:** Full 24-case coverage, perturbation/synthetic cases, confidence calibration scoring, novel-case eval.

### Interviewer Feedback

"Strong. Three cases as a reasoning smoke test is the right scope — it's a tripwire, not a benchmark. And the 15-min lightweight scoring spec is an honest authoring budget."

---

## Round 5: Non-Determinism and Run Mechanics

### Question

You've converged on a clean design. Let me push on the one remaining mechanical question before we move to planning.

A Layer 1.5 eval case means re-running an investigation against historical data that still exists in Databricks (partitioned by day). But the agent's entry point is a natural language question like "why did QSR drop the week of April 17?" — and the agent then freely chooses its hypotheses, SQL, and decomposition path.

This means each eval run costs real Databricks compute, real LLM tokens (sub-agent SQL + finding generation + LLM-as-judge scoring), and takes 1–5 minutes wall time. And the output is non-deterministic — the agent might choose different hypotheses or decomposition paths on successive runs of the same case.

Given the non-determinism, how many times do you need to run each case to trust the score — and does the eval format (YAML spec + LLM-as-judge) need to be designed for single-run pass/fail, or for aggregate scoring across multiple runs?

### Response

**3 runs per case, aggregate scoring. Not single-run pass/fail.**

**Why not single-run pass/fail:** Non-determinism in agentic systems isn't noise — it's a feature. Single-run pass/fail conflates path variance (acceptable) with outcome variance (what you care about). Flaky evals erode trust — the team starts ignoring red results.

**Why 3 runs, not 5 or 10:** Cost/signal tradeoff. 3 cases × 3 runs = 9 total runs. At 3 runs you distinguish three states:

| Result | Interpretation | Action |
|--------|---------------|--------|
| 3/3 pass | Agent reliably handles this archetype | Green |
| 2/3 pass | Non-determinism causing outcome variance | Yellow — investigate |
| 0–1/3 pass | Genuine regression or capability gap | Red — block deployment |

**YAML spec format includes run config:**

```yaml
run_config:
  n_runs: 3
  pass_threshold: 2
  timeout_minutes: 10
```

**Judge non-determinism reduced separately:** Temperature 0, structured JSON output, rubric baked into prompt. The judge should be boring and consistent; all creative variance belongs to the agent.

**Run cadence:** Not CI/CD on every PR. Run on agent logic changes, weekly as canary, and on-demand. At 9 runs per suite, that's sustainable.

### Interviewer Feedback

Acknowledged the design was converged and moved to planning.

---

## Outcome

The five rounds produced a complete auto-eval plan with:

1. **Three-layer architecture** (SQL correctness → investigation quality MVE → full regression suite)
2. **Concrete scoring rubrics** with edge case handling (different paths, confidence calibration, novel findings)
3. **Eval set collection strategy** across historical cases, synthetic perturbations, and production feedback loops
4. **Execution mechanics** for non-determinism (3-run majority voting, LLM-as-judge at temperature 0)
5. **Implementation roadmap** from MVE (this sprint) through full suite (next quarter) to perturbation testing (Q3+)

The plan was finalized into a standalone document: `Search_Metric_Agent_AutoEval_Plan.md`
