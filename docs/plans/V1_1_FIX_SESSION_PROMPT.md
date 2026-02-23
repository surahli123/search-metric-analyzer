# Search Metric Analyzer v1.1 — Fix Session Prompt

> Copy everything below the line into a new Claude Code session opened in:
> `/Users/surahli/Documents/New project/Search_Metric_Analyzer/`

---

## Prompt to paste:

```
You are fixing the Search Metric Analyzer v1-alpha based on eval stress-test findings. The tool runs (425 tests pass) but fails to produce correct diagnoses on 3/5 eval scenarios.

## What Happened

We ran the full diagnostic pipeline on 5 eval scenarios. Results:

| Case | Scenario | Score | Grade | Problem |
|------|----------|-------|-------|---------|
| S4 | Ranking regression | 81 | GREEN | OK — but hypothesis says "ai_enablement=ai_off" instead of "ranking model change" |
| S5 | AI adoption trap | 50 | RED | Missed AI adoption mechanism, assigned P0 severity, no tradeoff mentioned |
| S7 | Multi-cause overlap | 61 | YELLOW | Only found 1 of 2 causes, no multi-cause support |
| S9 | Mix-shift | 90 | GREEN | OK — best score, mix-shift detection works |
| S0 | False alarm (stable) | 47 | RED | Manufactured root cause from noise, no false alarm restraint |

## Root Causes (from eval-findings.md in memory)

5 critical gaps, in priority order:
1. **Co-movement matching broken** — `match_co_movement_pattern()` returns "unknown_pattern" for ALL scenarios. The most valuable diagnostic signal is completely unused.
2. **No archetype recognition** — `diagnose.py` always picks "biggest segment" but never maps to known failure modes (AI adoption, mix-shift regression, false alarm).
3. **No false alarm detection** — Pipeline always manufactures a root cause, even when movement is noise.
4. **Severity ignores context** — P0 assigned based on magnitude alone, not adjusted for positive movements.
5. **Single-cause bias** — Can't express multi-cause hypotheses.

## What to Read First

1. **Eval findings (memory):** Check your memory directory for `eval-findings.md` — has per-scenario scoring details and exactly where points were lost
2. **Co-movement diagnostic table:** `data/knowledge/metric_definitions.yaml` → `co_movement_diagnostic_table` — understand the YAML pattern format
3. **anomaly.py:** `tools/anomaly.py` → `match_co_movement_pattern()` — debug why it returns "unknown_pattern"
4. **diagnose.py:** `tools/diagnose.py` → `run_diagnosis()` — this is where most fixes go
5. **Stress test runner:** `eval/run_stress_test.py` — run this after fixes to validate (targets: all 5 GREEN)

## How to Work

Use Claude's Agent Teams (the Task tool) to parallelize independent work:

### Phase 1: Debug & Fix (use Agent Teams for parallel investigation)
- **Agent 1**: Debug co-movement matching (Fix 1) — read YAML table format, compare with observed dict format in `run_stress_test.py`, find the mismatch
- **Agent 2**: Read `diagnose.py` end-to-end and map all places that need archetype awareness

Then implement fixes sequentially (they're dependent):
1. Fix co-movement matching first (unblocks everything)
2. Add archetype recognition using co-movement output
3. Add false alarm detection (archetype: false_alarm_restraint)
4. Add context-aware severity (reduce P0 for positive movements)
5. Add multi-cause hypothesis support
6. Add action owners to formatter

### Phase 2: Validate
After each fix, run: `python3 eval/run_stress_test.py`
Target: all 5 scenarios GREEN (>=80/100)

### Phase 3: Review
After all fixes pass eval, request reviews from two perspectives:
- **DS Lead review**: Does the diagnostic logic match how a Senior DS would actually diagnose metric movements? Are the archetypes correct?
- **PM Lead review**: Are the outputs actionable? Would an Eng Lead know exactly what to do from the Slack message?

Use Agent Teams to dispatch both reviews in parallel.

## Files to Modify
- `tools/anomaly.py` — Fix co-movement matching
- `tools/diagnose.py` — Archetype recognition, false alarm, multi-cause, context-aware severity
- `tools/formatter.py` — Action owners
- `data/knowledge/metric_definitions.yaml` — Possibly fix pattern format

## Constraints
- Python 3.10+, stdlib + PyYAML only
- Don't break existing 425 tests
- Heavy comments explaining WHY
- All output is JSON to stdout
- Run `pytest tests/ -v` after each fix to confirm no regressions

## Success Criteria
- All 5 eval scenarios score GREEN (>=80)
- No `must_not_do` violations on any scenario
- S5 correctly identifies AI adoption as positive signal
- S0 correctly says "no action needed"
- S7 identifies both causes
- All existing 425 tests still pass
```
