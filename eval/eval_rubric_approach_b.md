# Evaluation Protocol — Approach B: Prospective Eval

## Purpose

Evaluate the Search Metric Analysis Agent on **live, ongoing metric investigations**
by running it in parallel with a real DS/Eng investigation and comparing outputs.

While Approach A proves the agent can **match** known answers, Approach B proves
it can **accelerate** real engineering work — which is what earns long-term trust.

## Operating Modes

Approach B supports three operating modes depending on who is investigating
and whether the agent's output has been seen.

### Mode Selection

| Situation | Mode | When to Use |
|---|---|---|
| You are the only DS AND you've already seen the agent output | **Agent-First Audit** (primary) | Default for solo DS workflow |
| You can investigate first before running the agent | **Delayed Agent Run** | First 3-5 evals to establish unbiased baseline |
| Another engineer independently investigates a metric movement | **Engineer Proxy** | SEVs, experiment launches, metric reviews done by Eng |

### Mode 1: Agent-First Audit (Primary — for solo DS)

You've already run the agent and seen the output. Instead of pretending you
haven't, evaluate your ability to QA the agent's work. This mirrors how the
tool will actually be used in production — nobody will run blind parallel
investigations. Engineers will read the agent's report and decide whether
to trust it.

```
Agent produces report
  → YOU review it critically (audit the output)
    → You run verification queries where the agent looks wrong
      → You produce a corrected final report
        → Score: what did you catch, miss, and correct?
```

### Mode 2: Delayed Agent Run (for establishing baseline)

Investigate first, write your findings, THEN run the agent and compare.
This gives clean, unanchored ground truth but requires double work.

```
You investigate from scratch (don't run agent)
  → You publish your findings
    → THEN run the agent on the same question
      → Compare your report vs. agent report using Approach A rubric
```

Use this for your first 3-5 prospective evals to establish a baseline
accuracy before switching to Mode 1.

### Mode 3: Engineer Proxy (opportunistic)

When another engineer investigates a metric movement for their own reasons,
use their investigation as ground truth.

```
Engineer investigates a metric movement (SEV, experiment, metric review)
  → You run the agent on the same question
    → Compare agent output vs. engineer's findings
      → Engineer's investigation is independent (no anchoring)
```

Use this whenever you spot an Eng investigation happening — SEV postmortems,
experiment analyses, Slack debugging threads. You don't create the investigation,
you just catch ones that are already happening.

---

## Protocol

### Step 1: Trigger — Log the Investigation Start

When you or an engineer begins investigating a metric movement, immediately log:

**Mode used:** Agent-First Audit / Delayed Agent Run / Engineer Proxy

```markdown
## PROSPECTIVE-[XXX]: Investigation Started

- **Date:** YYYY-MM-DD
- **Trigger:** [what prompted the investigation — alert, SEV, ad-hoc question, metric review]
- **Metric:** [e.g., QSR on FPS]
- **Movement:** [e.g., -1.2pp WoW]
- **Investigator:** [engineer name]
- **Agent input:** [exact question given to the agent — copy verbatim]
- **Investigation complexity estimate:** Simple / Complex / SEV
```

---

### Step 2: Run the Agent

Run the agent with the same input the human engineer would start with.

Save all of the following:

| Artifact | Format | Where to Save |
|---|---|---|
| Full diagnosis JSON | `.json` | `eval/results/prospective/PROSPECTIVE-XXX/diagnosis.json` |
| Formatted report | `.md` | `eval/results/prospective/PROSPECTIVE-XXX/report.md` |
| Trace output | `.md` or `.json` | `eval/results/prospective/PROSPECTIVE-XXX/trace.md` |
| SQL queries executed | `.sql` or in trace | `eval/results/prospective/PROSPECTIVE-XXX/queries.sql` |
| Knowledge files loaded | list | Record in trace or in the scorecard |
| Wall-clock time | timestamp | Record start and end time |

**For Mode 3 (Engineer Proxy) only:** Do NOT share the agent output with the
investigating engineer until they have completed their own investigation.

---

### Step 3: Investigate / Audit (depends on mode)

**Mode 1 — Agent-First Audit:** Review the agent's output critically. For each
finding in the report, decide: trust, verify, or reject. Run your own queries
where the agent's output looks suspicious. Produce a corrected final report
that represents what you believe the true answer is.

**Mode 2 — Delayed Agent Run:** Investigate from scratch first. Publish your
findings. Then run the agent and compare.

**Mode 3 — Engineer Proxy:** Wait for the engineer to finish their independent
investigation. Capture their report.

### What to Capture After Your Audit/Investigation

| Artifact | How to Get It |
|---|---|
| **Ground truth report** | Your corrected report (Mode 1), your independent report (Mode 2), or the engineer's report (Mode 3) |
| **Investigation / audit duration** | How long you spent reviewing + verifying the agent output |
| **Root cause conclusion** | Your final determination of the actual root cause |
| **Corrections made** | List of specific things you changed from the agent's output (Mode 1) |
| **Verification queries run** | SQL you ran to check the agent's claims (Mode 1) |

---

### Step 4: Score Using the Standard Rubric (Sections A-G)

Use the exact same rubric from `eval_rubric_approach_a.md`. Your corrected
report / independent report / engineer's report is the ground truth.
Score the agent's original output against it.

Fill out Sections A through G as documented in the Approach A rubric.

---

### Step 5: Prospective-Only Scoring (Section P)

Score these dimensions that only apply to live investigations. Section P has
two variants — use the one matching your mode.

#### Section P — Mode 1: Agent-First Audit (primary)

This measures whether you can effectively QA the agent's output — which is
how this tool will actually be used in production.

| # | Check | Score (1-5) | Notes |
|---|---|---|---|
| P1a | **First-draft accuracy** — Before you dug deeper, how much of the agent's report was correct? | ___ | 5 = >90% correct, 4 = 70-90%, 3 = 50-70%, 2 = 30-50%, 1 = <30%. Score based on what you later discovered. |
| P2a | **Error detectability** — Were the agent's mistakes obvious on first read, or did you need to run queries to find them? | ___ | 5 = errors jumped out immediately, 3 = needed to spot-check 1-2 things, 1 = errors were hidden behind convincing reasoning |
| P3a | **Time to verify** — How long did it take to verify/correct the agent's output vs. your estimate of doing it from scratch? | ___ | 5 = much faster than from-scratch, 3 = about the same, 1 = took longer (agent output was misleading) |
| P4a | **Anchoring risk** — Did the agent's framing cause you to miss something you would have caught investigating independently? | ___ | 5 = no anchoring (you checked beyond what the agent suggested), 3 = you mostly followed the agent's framing, 1 = you suspect you missed things because of anchoring |
| P5a | **Final output quality** — Is your final report (agent draft + your corrections) better, worse, or same as what you'd produce alone? | ___ | 5 = noticeably better (agent found things you might have missed), 3 = same quality, 1 = worse (agent's framing degraded your output) |
| P6a | **Coverage gap identified?** — Did this investigation reveal a missing playbook, archetype, or knowledge gap? | ___ | Record specifically what's missing below |

**P subtotal (Mode 1): ___ / 30**

**Self-audit for anchoring (fill after every Mode 1 eval):**
- Things I verified independently (ran my own queries): ___
- Things I accepted from the agent without verifying: ___
- Things I would have investigated differently if starting fresh: ___

#### Section P — Mode 2/3: Blind Comparison

Use this when you investigated first (Mode 2) or an engineer investigated
independently (Mode 3).

| # | Check | Score (1-5) | Notes |
|---|---|---|---|
| P1 | **Speed** — How much faster was the agent than the human? | ___ | 5 = agent < 10% of human time, 4 = 10-25%, 3 = 25-50%, 2 = 50-100%, 1 = agent slower |
| P2 | **Novelty handling** — Was this a pattern the agent hasn't seen before? How did it handle it? | ___ | 5 = handled novel pattern well, 3 = partially, 1 = failed on novelty. N/A if known pattern. |
| P3 | **Triage utility** — If the agent report had been available at the START of the investigation, would it have helped triage faster? | ___ | 5 = major acceleration, 4 = noticeable help, 3 = some help, 2 = marginal, 1 = misleading |
| P4 | **Trust signal** — Would the investigating engineer trust this report enough to use it as a starting point? | ___ | Ask the engineer directly after showing them (Mode 3), or self-assess (Mode 2) |
| P5 | **Coverage gap identified?** — Did this investigation reveal a missing playbook, archetype, or knowledge gap? | ___ | Record specifically what's missing below |

**P subtotal (Mode 2/3): ___ / 25**

### Coverage Gaps Discovered (all modes)

If gaps were identified, record them here for backlog:

- [ ] Missing playbook entry: ___
- [ ] Missing archetype: ___
- [ ] Missing/stale knowledge file: ___
- [ ] Missing SQL template: ___
- [ ] Domain knowledge never documented: ___

---

### Step 6: Post-Investigation Debrief

#### Mode 1 — Self-Debrief

Answer these questions honestly after each Agent-First Audit:

1. "If I hadn't seen the agent's output, would I have reached a different conclusion?"
2. "Did I verify enough of the agent's claims, or did I get lazy and trust it?"
3. "What would I tell another DS to watch out for when reviewing this agent's output?"

```markdown
### Self-Debrief — PROSPECTIVE-[XXX]

**Date:** YYYY-MM-DD

**Corrections I made to agent output:**
(list each change and why)

**Things I trusted without verifying:**
(be honest — this is how you calibrate your review process)

**Anchoring concerns:**
(did the agent's framing limit your thinking?)

**Would I have found the root cause faster without the agent?** Yes / No / Same

**Net assessment:** The agent made my investigation [faster / slower / same]
and [more accurate / less accurate / same accuracy]
```

#### Mode 3 — Engineer Debrief (show agent output after they finish)

Ask the investigating engineer:

1. "Does this match your findings?"
2. "What did it get wrong?"
3. "Would this have saved you time if you'd seen it at the start?"
4. "What's missing from the agent's analysis that you had to figure out yourself?"
5. "Is there anything the agent caught that surprised you?"

```markdown
### Engineer Debrief — PROSPECTIVE-[XXX]

**Engineer:** [name]
**Date:** YYYY-MM-DD

**Reaction to agent output:**
(verbatim or close paraphrase)

**What it got right:**

**What it got wrong:**

**Would it have saved time?** Yes / No / Partially — because:

**Missing from agent analysis:**

**Surprising findings from agent:**

**Trust level (1-5):** ___

**Would you use this as a starting point next time?** Yes / No / Maybe
```

---

## When to Run Approach B

Not every investigation is a good eval candidate.

### Include

- Metrics the agent knows about (in metric_definitions.yaml)
- Investigations that take at least 30 minutes of human work
- Investigations that reach a clear conclusion
- Current data that's queryable with current table schemas
- All complexity tiers (Simple, Complex, SEV)

### Exclude

- Metrics outside the agent's registry
- Quick 5-minute "it's nothing" checks (not enough substance to evaluate)
- Investigations that end inconclusive (no ground truth to compare against)
- Investigations requiring data sources the agent can't access

### Target Cadence

**2-3 prospective evals per month.**

This gives a steady stream of real-world data without creating overhead. After
6 months, you'll have 12-18 data points — enough for meaningful aggregate stats.

---

## Scoring Summary Template

```markdown
## PROSPECTIVE-[XXX]: [Brief description]

### Setup
- **Date:** YYYY-MM-DD
- **Metric:** [metric on surface]
- **Movement:** [size and direction]
- **Complexity:** Simple / Complex / SEV
- **Human investigation time:** [hours/minutes]
- **Agent investigation time:** [minutes]

### Standard Rubric Score (from Approach A)
| Section | Max | Score |
|---|---|---|
| B: UNDERSTAND | 5 | ___ |
| C: HYPOTHESIZE | 20 | ___ |
| D: DISPATCH | 20 | ___ |
| E: SYNTHESIZE | 25 | ___ |
| F: Cross-Stage | 15 | ___ |
| G: Comparative | 15 | ___ |
| **Rubric Total** | **100** | **___** |

### Prospective-Only Score
| Check | Score |
|---|---|
| P1: Speed | ___/5 |
| P2: Novelty handling | ___/5 |
| P3: Triage utility | ___/5 |
| P4: Trust signal | ___/5 |
| P5: Coverage gap | ___/5 |
| **P Total** | **___/25** |

### Grade: ___ (GREEN / YELLOW / RED)
### Critical Flags: ___

### Key Takeaways
- **What the agent got right:**
- **What the agent got wrong:**
- **Root cause of failure (if any):**
- **Improvement action items:**
```

---

## Aggregate Tracking

After accumulating 5+ prospective evals, maintain a tracking table:

```markdown
| Case | Date | Metric | Rubric Score | Grade | C1 Hit? | E1 Match? | P3 Triage | P4 Trust | Human Time | Agent Time | Time Ratio |
|------|------|--------|-------------|-------|---------|-----------|-----------|----------|------------|------------|------------|
| P-001 | ... | QSR | 72 | YELLOW | PASS | PARTIAL | 3 | 3 | 4h | 8min | 30x |
| P-002 | ... | SAIN | 85 | GREEN | PASS | PASS | 4 | 4 | 2h | 5min | 24x |
| ... | | | | | | | | | | | |
```

### Key Metrics to Report to Eng Leads

#### From all modes

| Metric | Formula | Target | What It Proves |
|---|---|---|---|
| **Hypothesis hit rate** | % of cases where C1 = PASS | > 70% | "The system knows what to look for" |
| **Root cause accuracy** | % of cases where E1 = PASS or PARTIAL | > 60% | "The system gets the right answer" |
| **Critical failure rate** | % of cases with any critical flag | < 20% | "The system is reliable" |

#### From Mode 1 (Agent-First Audit) specifically

| Metric | Formula | Target | What It Proves |
|---|---|---|---|
| **First-draft accuracy** | Average P1a score | > 3.5 / 5 | "Agent output is mostly correct out of the box" |
| **Error detectability** | Average P2a score | > 3.0 / 5 | "Mistakes are catchable during review" |
| **Verification speedup** | Average P3a score | > 3.5 / 5 | "Reviewing agent output is faster than investigating from scratch" |
| **Anchoring safety** | Average P4a score | > 3.5 / 5 | "Reviewing doesn't blind you to the agent's mistakes" |

#### From Mode 2/3 (Blind Comparison)

| Metric | Formula | Target | What It Proves |
|---|---|---|---|
| **Mean triage utility** | Average P3 score | > 3.5 / 5 | "Engineers actually find this useful" |
| **Mean trust signal** | Average P4 score | > 3.0 / 5 | "Engineers would use this" |
| **Median time ratio** | Median (human time / agent time) | > 10x | "This is worth the token cost" |

### The Story for Eng Leads

Combine metrics from all modes to tell the story:

1. **Hypothesis hit rate > 70%** → "The system includes the actual root cause in its hypothesis set 7 out of 10 times"
2. **Root cause accuracy > 60%** → "The system identifies the correct root cause more often than not"
3. **First-draft accuracy > 3.5** → "The agent's output is mostly correct out of the box — the DS reviews and corrects rather than starting from scratch"
4. **Verification speedup > 3.5** → "Reviewing the agent's output is significantly faster than doing the full investigation manually"
5. **Anchoring safety > 3.5** → "The review process catches the agent's mistakes reliably — we're not rubber-stamping bad output"

---

## Comparison: Approach A vs Approach B

| Dimension | Approach A (Retrospective) | Approach B (Prospective) |
|---|---|---|
| **Ground truth** | Already exists (Eng report) | Created in real-time by human |
| **Speed to accumulate data** | Fast (batch through past reports) | Slow (2-3/month) |
| **Bias risk** | Agent may be tuned to known patterns | True out-of-sample |
| **What it proves** | "Agent can reproduce known answers" | "Agent accelerates real work" |
| **When to use** | First — build baseline confidence | Ongoing — prove real-world value |
| **Sample size needed** | 10-15 cases for baseline | 5+ for initial trends, 15+ for confidence |

### Recommended Sequence

1. **Weeks 1-2:** Run Approach A on 10-15 past reports (batch) — establishes baseline accuracy
2. **Weeks 2-3:** Run 3-5 Approach B evals in Mode 2 (Delayed Agent Run) — establishes unbiased prospective baseline
3. **Week 4+:** Switch to Mode 1 (Agent-First Audit) as your default — this is your real workflow
4. **Ongoing:** Grab Mode 3 (Engineer Proxy) evals opportunistically whenever Eng investigates something
5. **Month 3:** Combine A + B results for first comprehensive report to Eng leads
6. **Ongoing:** Continue B (mostly Mode 1) to track improvement as you fix issues found in A

**Why start with Mode 2 before switching to Mode 1:** You need 3-5 unbiased
data points to know the agent's baseline accuracy. Once you know it misses
root causes ~30% of the time (or whatever the real number is), you can
calibrate your Mode 1 reviews accordingly — you know what to watch for.

---

## File Organization

```
eval/
  eval_rubric_approach_a.md     # This rubric (retrospective)
  eval_rubric_approach_b.md     # This protocol (prospective)
  run_eval.py                    # Existing deterministic eval (synthetic cases)
  run_stress_test.py             # Existing stress testing
  scoring_specs/                 # Existing 6 synthetic eval cases
  results/
    retrospective/               # Approach A scored investigations
      EVAL-001/
        diagnosis.json
        report.md
        scorecard.md             # Filled-out rubric
      EVAL-002/
        ...
    prospective/                 # Approach B scored investigations
      PROSPECTIVE-001/
        diagnosis.json
        report.md
        trace.md
        queries.sql
        scorecard.md             # Filled-out rubric + P section + debrief
      PROSPECTIVE-002/
        ...
    tracking.md                  # Aggregate tracking table (both approaches)
```
