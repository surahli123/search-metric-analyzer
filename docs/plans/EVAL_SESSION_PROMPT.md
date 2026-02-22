# Search Metric Analyzer — Eval Stress-Test Session

> Copy everything below the line into a new Claude Code session opened in:
> `/Users/surahli/Documents/New project/Search_Metric_Analyzer/`

---

## Prompt to paste:

```
You are stress-testing the Search Metric Analyzer v1-alpha. The implementation is done (425 tests pass), but we need to verify the tool actually produces correct diagnoses — not just that the plumbing works.

## What to Read First

1. **Design doc:** `docs/plans/2026-02-21-search-metric-analyzer-design.md` — architecture and expected behavior
2. **Eval scoring specs:** `eval/scoring_specs/` — 5 YAML files defining what correct output looks like
3. **Eval runner:** `eval/run_eval.py` — deterministic scorer (load it, understand score_single_run)
4. **Synthetic data generator:** `generators/generate_synthetic_data.py` — generates test scenarios
5. **Project CLAUDE.md:** `CLAUDE.md` — conventions

## What to Do

### Phase 1: Generate Fresh Synthetic Data

Run the generator to produce fresh scenarios:
```bash
python3 generators/generate_synthetic_data.py
```

### Phase 2: Run Full Pipeline on 5 Eval Scenarios

For each scenario below, run the FULL pipeline (decompose -> diagnose -> format) and score it with the eval runner. Use Agent Teams to parallelize where possible.

| Case | Scenario | Synthetic Data Filter | Expected Root Cause |
|------|----------|----------------------|-------------------|
| 1 | S4 | `scenario_id == "S4"` | Ranking regression in Standard tier |
| 2 | S5 | `scenario_id == "S5"` | AI adoption (DLCTR drop is GOOD) |
| 3 | S7 | `scenario_id == "S7"` | Multiple causes: AI + tenant churn |
| 4 | S9 | `scenario_id == "S9"` | Mix-shift from tenant portfolio change |
| 5 | S0 | `scenario_id == "S0"` | No significant movement (false alarm) |

For each case:
1. Filter synthetic CSV to get the scenario's rows
2. Run `decompose.py` with appropriate dimensions
3. Run `anomaly.py` for step-change detection
4. Run `diagnose.py` on the decomposition output
5. Run `formatter.py` to generate Slack message + report
6. Score the output with `eval/run_eval.py`'s `score_single_run()`
7. Record: score, grade (GREEN/YELLOW/RED), and any must_not_do violations

### Phase 3: Analyze Results

After running all 5 cases:
1. How many score GREEN (>=80)?
2. How many score RED (<60)?
3. For any RED/YELLOW: what went wrong? Root cause not found? Wrong confidence?
4. Does the tool actually distinguish mix-shift from behavioral regression?
5. Does it handle the AI adoption trap correctly?

### Phase 4: Identify Gaps

Based on the results, identify:
- Which scoring criteria are too lenient (letting bad output pass)?
- Which are too strict (failing good output)?
- What failure modes does the tool have that our 425 tests didn't catch?
- Any cases where the deterministic scorer disagrees with what a human expert would say?

## Key Concern from the User

"I feel the testing results are too good to be true."

The 425 tests are mostly structural validation (does the function return the right keys? do weights sum to 100?). This session should answer: **does the tool actually diagnose metric movements correctly?**

## Domain Context

- Enterprise Search ranking: L1 (Retrieval) -> L2 (Reranking) -> L3 (Interleaver)
- "Ranking model" covers all L1-L3 components
- QSR = max(click component, sain_trigger * sain_success)
- AI adoption trap: DLCTR drops when AI answers work — this is POSITIVE
- Mix-shift threshold: >=30% composition change = INVESTIGATE
- Severity: P0 (>5%), P1 (2-5%), P2 (0.5-2%), normal (<0.5%)

## Output

Present results as a scorecard:

| Case | Scenario | Score | Grade | Root Cause Found? | Violations |
|------|----------|-------|-------|-------------------|------------|
| 1 | S4 | ?? | ?? | ?? | ?? |
| 2 | S5 | ?? | ?? | ?? | ?? |
| ... | ... | ... | ... | ... | ... |

Then provide honest assessment: is v1-alpha ready for demo, or does it need more work?
```
