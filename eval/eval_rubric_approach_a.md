# Evaluation Rubric — Approach A: Retrospective Eval

## Purpose

Score the Search Metric Analysis Agent's output against **past experiment reports**
where the root cause is already known. This rubric evaluates the full 4-stage pipeline
(UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE), not just SQL correctness.

## How to Use

1. Pick a past experiment report (Confluence page) where you know the root cause
2. Run the agent on the same metric movement (same metric, surface, time range)
3. Fill out each section below comparing agent output vs. the Eng report
4. Calculate the total score and assign a grade

## Scoring Scale

Each check uses a 3-level scale unless otherwise noted:

| Score | Meaning | When to Use |
|---|---|---|
| **PASS** (full points) | Correct, matches ground truth | Agent got it right |
| **PARTIAL** (half points) | Directionally correct but incomplete or imprecise | Agent was in the ballpark but missed details |
| **FAIL** (0 points) | Wrong, missing, or misleading | Agent got it wrong or skipped it entirely |

---

## Section A: Investigation Setup (fill before scoring)

| Field | Value |
|---|---|
| **Eval case ID** | EVAL-___ |
| **Source report** | (Confluence link) |
| **Metric investigated** | (e.g., QSR, click_quality_value, SAIN) |
| **Surface** | (e.g., FPS, Desktop, 3P) |
| **Time range** | (e.g., 2026-02-10 to 2026-02-17) |
| **Movement size** | (e.g., -1.2pp WoW) |
| **Known root cause** | (from the Eng report — 1-2 sentences) |
| **Root cause archetype** | (map to one of the 15 archetypes if possible, or "novel") |
| **Investigation complexity** | Simple / Complex / SEV |
| **Evaluator** | (your name or the engineer reviewing) |
| **Date evaluated** | YYYY-MM-DD |

---

## Section B: UNDERSTAND Stage (5 pts)

Does the agent correctly identify what it's looking at?

| # | Check | Score | Points | Notes |
|---|---|---|---|---|
| B1 | **Metric identification** — Did it identify the correct metric? (e.g., `click_quality_value` not confused with `search_quality_success_value`) | ___ | /1 | |
| B2 | **Direction classification** — Did it correctly determine which direction is "bad"? (IC9 Invisible Decision #1) | ___ | /1 | If wrong here, everything downstream is wrong |
| B3 | **Surface/segment scoping** — Did it correctly identify the affected surface and time range? | ___ | /1 | |
| B4 | **Severity classification** — Is the P0/P1/P2 severity appropriate for the movement size? | ___ | /1 | Thresholds: P0 > 5%, P1 2-5%, P2 0.5-2% |
| B5 | **Data quality gate** — Did the quality checks (completeness >= 96%, freshness <= 60min, step-change) fire correctly? | ___ | /1 | Logging artifact should HALT; clean data should PASS |

**B subtotal: ___ / 5**

---

## Section C: HYPOTHESIZE Stage (20 pts)

The highest-leverage stage. The one-shot constraint means if the right hypothesis
isn't generated here, the investigation fails permanently.

| # | Check | Score | Points | Notes |
|---|---|---|---|---|
| C1 | **Root cause in hypothesis set** — Was the actual root cause (from the Eng report) included in the generated hypotheses? | ___ | /5 | **MOST CRITICAL.** FAIL = agent cannot succeed downstream. |
| C2 | **Significance check** — Did the agent correctly determine whether the movement is statistically real vs. normal variance? | ___ | /3 | Check against metric's weekly_std/mean noise profile |
| C3 | **Num/denom decomposition** — Did the agent correctly split numerator vs. denominator to identify which drove the change? | ___ | /3 | Essential for composite metrics like QSR |
| C4 | **Experiment coincidence** — Did the agent check whether an experiment launched in the same window? Did it find the right one? | ___ | /3 | Compare: what experiments does the Eng report mention? |
| C5 | **Archetype match** — Does the selected archetype match the actual root cause pattern? | ___ | /3 | Map Eng report root cause to one of 15 archetypes |
| C6 | **Hypothesis quality** — Are there extraneous/misleading hypotheses that would waste investigation time? | ___ | /3 | PASS = clean set, PARTIAL = 1-2 noise, FAIL = majority noise |

**C subtotal: ___ / 20**

### C1 Failure Analysis (fill only if C1 = FAIL)

- What was the actual root cause: ___
- What hypotheses did the agent generate: ___
- Why the miss happened (playbook gap / novel pattern / wrong decomposition / other): ___
- Recommendation (new playbook entry / new archetype / prompt fix / other): ___

---

## Section D: DISPATCH Stage (20 pts)

Did the sub-agents investigate correctly?

| # | Check | Score | Points | Notes |
|---|---|---|---|---|
| D1 | **SQL correctness** — Do the queries execute successfully and return valid data? | ___ | /4 | No syntax errors, correct table names, appropriate WHERE clauses |
| D2 | **SQL relevance** — Do the queries test the right thing for the hypothesis? | ___ | /4 | A correct query that answers the wrong question is worse than a failed query |
| D3 | **Data interpretation** — Does the sub-agent correctly read the query results? | ___ | /4 | Watch for: correct numbers, wrong interpretation (evidence bottleneck) |
| D4 | **Verdict accuracy** — Is SUPPORTED/REJECTED/INCONCLUSIVE correct given the evidence? | ___ | /4 | Compare to Eng report: same evidence available? Same conclusion? |
| D5 | **Context quality** — Did the sub-agent receive appropriate context from HYPOTHESIZE? (IC9 Invisible Decision #3) | ___ | /4 | Was enough info provided, or was critical context filtered out? |

**D subtotal: ___ / 20**

### D3 Failure Patterns (check all that apply)

- [ ] Confuses correlation with causation
- [ ] Misreads the direction of a metric movement
- [ ] Reports numbers that don't match the raw query output (hallucinated evidence)
- [ ] Ignores important rows/segments in the data
- [ ] Other: ___

---

## Section E: SYNTHESIZE Stage (25 pts)

The highest-consequence stage. This is what the engineer reads and acts on.

| # | Check | Score | Points | Notes |
|---|---|---|---|---|
| E1 | **Root cause match** — Does the agent's final conclusion match the Eng report? | ___ | /7 | The ultimate accuracy check |
| E2 | **Evidence faithfulness** — Do the numbers in the report match actual query results? | ___ | /5 | Checks the "interpretation of interpretation" problem |
| E3 | **Reasoning chain** — Is the logical path from evidence to conclusion sound? | ___ | /4 | Even if conclusion is right, broken reasoning is a reliability risk |
| E4 | **Confidence calibration** — Does the confidence grade (High/Medium/Low) match actual certainty? | ___ | /3 | Overconfident on weak evidence? Underconfident on strong evidence? |
| E5 | **Actionability** — Are the recommended next steps specific, correct, and useful? | ___ | /3 | Compare to what the Eng report recommended |
| E6 | **Completeness** — Does the report cover all elements the Eng report covers? | ___ | /3 | Missing secondary finding = PARTIAL. Missing primary = FAIL. |

**E subtotal: ___ / 25**

---

## Section F: Cross-Stage Checks (15 pts)

Tests for the systemic failure modes identified in the IC9 audit.

| # | Check | Score | Points | Notes |
|---|---|---|---|---|
| F1 | **Error propagation** — If any upstream stage made an error, did it cascade into a wrong final conclusion? | ___ | /5 | The "convincing wrong answer" check |
| F2 | **Knowledge utilization** — Did the agent use the right knowledge files? Did stale/wrong knowledge hurt? | ___ | /3 | Which playbooks/digests were loaded? Relevant? |
| F3 | **Memory influence** — If global.md learnings were applied, did they help or hurt? | ___ | /3 | PASS = improved hypotheses. FAIL = biased toward wrong conclusion. N/A if unused. |
| F4 | **Transparency** — Could an engineer reading the trace understand WHY the agent reached its conclusion? | ___ | /4 | Can you follow UNDERSTAND -> SYNTHESIZE decision chain? |

**F subtotal: ___ / 15**

---

## Section G: Comparative Assessment (15 pts)

Directly addresses the question: "Is the agent useful compared to human investigation?"

| # | Check | Score (1-5) | Points | Notes |
|---|---|---|---|---|
| G1 | **Overlap with Eng report** — What % of the Eng report's key findings does the agent also surface? | ___ | /5 | 5 = >80%, 4 = 60-80%, 3 = 40-60%, 2 = 20-40%, 1 = <20% |
| G2 | **Novel insights** — Did the agent surface anything correct that the Eng report missed? | ___ | /5 | 5 = major new insight, 3 = minor additions, 1 = nothing new |
| G3 | **First-draft utility** — If an engineer received this before investigating, would it save time? | ___ | /5 | 5 = significant, 3 = some, 1 = would mislead |

**G subtotal: ___ / 15**

---

## Scoring Summary

| Section | Max | Score |
|---|---|---|
| B: UNDERSTAND | 5 | ___ |
| C: HYPOTHESIZE | 20 | ___ |
| D: DISPATCH | 20 | ___ |
| E: SYNTHESIZE | 25 | ___ |
| F: Cross-Stage | 15 | ___ |
| G: Comparative | 15 | ___ |
| **TOTAL** | **100** | **___** |

## Grade

| Grade | Score | Interpretation |
|---|---|---|
| **GREEN** | 80-100 | Reliable first draft. Engineer reviews and refines rather than starting from scratch. |
| **YELLOW** | 55-79 | Significant gaps or errors. Useful starting point with heavy review. |
| **RED** | 0-54 | Unreliable or misleading. Would not save engineer time. |

**This investigation's grade: ___**

---

## Critical Failure Flags

Regardless of total score, flag the investigation as **RED** if ANY of these are true:

| Flag | Triggered? | Why Critical |
|---|---|---|
| C1 = FAIL (root cause not in hypothesis set) | [ ] | One-shot constraint — agent can never find it |
| E1 = FAIL AND E3 = PASS (wrong conclusion, convincing reasoning) | [ ] | "Convincing wrong answer" — the most dangerous failure |
| E2 = FAIL (evidence doesn't match raw data) | [ ] | Hallucinated/misreported evidence destroys trust |
| F1 = FAIL (error propagation to wrong conclusion) | [ ] | Systemic pipeline integrity failure |

**Critical flags triggered: ___**

---

## Investigation Notes

### What the agent got right
(1-2 sentences)


### What the agent got wrong
(1-2 sentences)


### Root cause of failure
(which stage, which decision)


### Would this improve with...
- [ ] Better playbooks / new archetype
- [ ] Better SQL templates
- [ ] Better knowledge files / domain digests
- [ ] Better prompts (which stage?)
- [ ] Structural change (what?)
- [ ] Other: ___

### Lessons for the agent
(anything that should feed back into improvements)


---

## Selection Criteria for Test Cases

When choosing past experiment reports to evaluate, filter for:

1. **Root cause clearly documented** in the Confluence page
2. **Data still queryable** — tables and schemas haven't changed since the investigation
3. **Metric/surface in agent's coverage area** — metric is in metric_definitions.yaml
4. **Mix of complexities** — target ~5 Simple, ~5 Complex, ~3 SEV-level
5. **Mix of archetypes** — try to cover at least 5-7 of the 15 archetypes

### Recommended Eval Set Size

- **Minimum viable:** 10 scored investigations
- **Target:** 15 scored investigations
- **Stretch:** 20 scored investigations (your full set)

### Aggregate Reporting

After scoring 10+ cases, compute:

| Aggregate Metric | Formula | Target |
|---|---|---|
| **Hypothesis hit rate** | % of cases where C1 = PASS | > 70% |
| **Root cause accuracy** | % of cases where E1 = PASS or PARTIAL | > 60% |
| **Mean triage utility** | Average G3 score | > 3.5 / 5 |
| **Critical failure rate** | % of cases with any critical flag | < 20% |
| **Mean total score** | Average total score across all cases | > 65 |
