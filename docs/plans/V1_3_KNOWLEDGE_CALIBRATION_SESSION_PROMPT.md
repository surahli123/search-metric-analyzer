# Search Metric Analyzer v1.3 — Knowledge Calibration Session Prompt

> Copy everything below the line into a new Claude Code session opened in:
> `/Users/surahli/Documents/New project/Search_Metric_Analyzer/`

---

## Prompt to paste:

```
You are calibrating the Search Metric Analyzer against real Enterprise Search knowledge docs. The tool works well on synthetic data (433 tests, 5/5 eval GREEN, avg 91.2/100), but its domain knowledge was invented, not sourced from real systems. This session corrects that.

## Context

The tool diagnoses metric movements in Enterprise Search (like Glean). It has a 4-step pipeline: Decompose → Anomaly Detection → Diagnose → Format. The "brain" lives in:
- `data/knowledge/metric_definitions.yaml` — metric formulas, noise profiles, co-movement patterns
- `data/knowledge/historical_patterns.yaml` — recurring incident patterns
- `tools/diagnose.py` — archetype recognition (ARCHETYPE_MAP), noise thresholds, false alarm detection
- `eval/run_stress_test.py` — eval pipeline with noise thresholds for co-movement classification

All of these were written from assumptions, not real data. The user will provide Enterprise Search knowledge docs for you to read and use as ground truth.

## What the User Will Provide

The user will share one or more knowledge docs (could be internal wiki pages, metric documentation, incident postmortems, or similar). Your job is to:

1. **Read the docs carefully** — extract every fact about metrics, thresholds, patterns, and diagnostic processes
2. **Compare against current assumptions** — identify every mismatch between the docs and our YAML/code
3. **Present a correction plan** — organized by impact, before making any changes
4. **Apply corrections incrementally** — with eval checkpoints after each group

## 8 Areas to Audit (ordered by impact)

### Area 1: Co-Movement Pattern Table
**Current assumption:** 7 patterns in `metric_definitions.yaml` → `co_movement_diagnostic_table`
**What to look for in docs:**
- Which metric combinations actually co-occur in real incidents
- Direction relationships (does metric A going down always mean metric B goes up?)
- Patterns we're missing entirely (connector outages? reindexing? tenant churn?)
- Whether the 4 metrics we track (Click Quality, Search Quality Success, AI trigger, AI success) are the right ones, or if we need latency, zero-result rate, or others

**File to update:** `data/knowledge/metric_definitions.yaml` → `co_movement_diagnostic_table` section
**Downstream impact:** Changes here cascade to `tools/anomaly.py` → `match_co_movement_pattern()` and all archetype recognition in `tools/diagnose.py`

### Area 2: Metric Noise Profiles
**Current assumption:** We made up weekly_std values (Click Quality 0.015, Search Quality Success 0.012, AI trigger 0.010, AI success 0.015). These drive noise thresholds.
**What to look for in docs:**
- Actual metric variability — weekly std, coefficient of variation, seasonal patterns
- Whether noise is stationary or varies by tenant tier / time
- What the operations team considers "normal fluctuation" vs. "real movement"

**Files to update:**
- `data/knowledge/metric_definitions.yaml` → `normal_range` sections
- `tools/diagnose.py` → `METRIC_NOISE_THRESHOLDS` dict
- `eval/run_stress_test.py` → `METRIC_NOISE_THRESHOLDS` dict (must stay in sync)

**v1.2 lesson:** Plan called for ai_trigger=0.05, ai_success=0.04. Broke eval because synthetic ai_success noise was 5.76%. Settled on 0.06/0.06. Real data would give us the right answer.

### Area 3: Severity Thresholds
**Current assumption:** P0 (>5%), P1 (2-5%), P2 (0.5-2%) — same for all metrics.
**What to look for in docs:**
- Per-metric severity thresholds (a 5% Click Quality drop vs. 5% ai_trigger drop are not the same urgency)
- Whether severity is based on relative % or absolute delta
- Whether it depends on affected tenant tier (enterprise tenant regression = higher severity?)
- What thresholds the actual alerting system uses

**File to update:** `tools/decompose.py` → severity classification logic (around line 200-220)

### Area 4: Real Incident Scenarios for Eval
**Current assumption:** 5 synthetic eval scenarios (S4, S5, S7, S9, S0) based on invented stories.
**What to look for in docs:**
- Real past incidents with known root causes ("In Q3, Click Quality dropped 4% because of X")
- The actual diagnostic process that was followed
- What the correct diagnosis looked like

**Files to update:**
- `eval/scoring_specs/` — adjust scoring rubrics to match real expectations
- `tools/generate_synthetic_data.py` — regenerate synthetic data with realistic parameters
- Potentially add new eval scenarios

### Area 5: Archetype Definitions
**Current assumption:** 8 archetypes in `tools/diagnose.py` → `ARCHETYPE_MAP`
Current archetypes: ranking_regression, ai_adoption, broad_degradation, ai_regression, behavior_change, ai_trigger_issue, ai_success_issue, false_alarm, mix_shift
**What to look for in docs:**
- Failure modes we're missing (connector outages, experiment contamination, reindexing, data pipeline failures)
- Whether our existing archetypes map correctly to how DS teams actually categorize incidents
- Action items — do the recommended actions match what teams actually do?

**File to update:** `tools/diagnose.py` → `ARCHETYPE_MAP`

### Area 6: Decomposition Dimensions
**Current assumption:** Primary dimensions are tenant_tier, ai_enablement, connector_type.
**What to look for in docs:**
- Which dimensions DS teams actually cut by first
- Whether query_type, industry_vertical, or other dimensions are more diagnostic
- Dimension correlations (we discovered ai_enablement ↔ tenant_tier in v1.2)

**File to update:** `eval/run_stress_test.py` → `ENTERPRISE_DIMENSIONS` list, and potentially `data/knowledge/metric_definitions.yaml` → `decomposition_dimensions`

### Area 7: Hypothesis Investigation Order
**Current assumption:** Fixed priority: instrumentation → connector → algorithm → experiment → AI feature → seasonal → user behavior
**What to look for in docs:**
- What DS teams actually check first when a metric moves
- The real frequency of each root cause type (if 60% are experiment ramps, check those first)
- What specific checks are done per hypothesis (not just generic "investigate")

**File to update:** `data/knowledge/metric_definitions.yaml` → `hypothesis_priority`, and `tools/formatter.py` → `_build_alternatives`

### Area 8: Search Quality Success Formula and Edge Cases
**Current assumption:** Search Quality Success = max(click_component, ai_trigger x ai_success)
**What to look for in docs:**
- Exact Search Quality Success formula -- any weights, floors, or conditions we're missing?
- At what AI adoption level does the AI Answer path dominate the max()?
- How zero-result queries factor in
- Sub-components of Search Quality Success we might need to decompose separately

**File to update:** `data/knowledge/metric_definitions.yaml` → `search_quality_success` section

## How to Work

### Phase 1: Read and Audit (DO NOT write code yet)
1. Read the knowledge docs the user provides
2. For each of the 8 areas above, extract the relevant facts
3. Compare against current assumptions in our files
4. Present a **correction table** to the user:

| Area | Current Assumption | Real Value (from docs) | Impact | Files to Update |
|------|--------------------|------------------------|--------|-----------------|
| ... | ... | ... | ... | ... |

Wait for user approval before proceeding.

### Phase 2: Apply Corrections (incremental, with checkpoints)
Group changes by risk level (same pattern as v1.2):
1. **YAML-only changes** (metric_definitions, historical_patterns) — lowest risk
2. **Threshold changes** (noise, severity) — medium risk
3. **Logic changes** (new archetypes, new patterns) — higher risk
4. **Eval changes** (scoring rubrics, new scenarios) — highest risk

After each group:
- Run `python3 -m pytest tests/ -v` (currently 433 passing)
- Run `python3 eval/run_stress_test.py` (currently all 5 GREEN, avg 91.2)
- If a scenario drops below GREEN, investigate before proceeding

### Phase 3: Eval Recalibration
If the real knowledge significantly changes what "correct" looks like:
1. Update scoring specs in `eval/scoring_specs/` to match real expectations
2. Consider whether synthetic scenarios need regeneration
3. Re-run eval and establish new baseline
4. It's OK if scores temporarily drop — we're making the eval MORE correct, not gaming the score

## Key Files Quick Reference

| File | What it contains | Lines |
|------|-----------------|-------|
| `data/knowledge/metric_definitions.yaml` | Metric formulas, noise profiles, co-movement table | ~200 |
| `data/knowledge/historical_patterns.yaml` | Known incident patterns | ~100 |
| `tools/diagnose.py` | ARCHETYPE_MAP, METRIC_NOISE_THRESHOLDS, false alarm logic | ~1230 |
| `tools/anomaly.py` | Co-movement pattern matching | ~300 |
| `tools/decompose.py` | Severity classification | ~400 |
| `tools/formatter.py` | Output formatting, alternatives list | ~750 |
| `eval/run_stress_test.py` | Eval pipeline, METRIC_NOISE_THRESHOLDS (synced copy) | ~415 |
| `eval/scoring_specs/` | 5 YAML scoring rubrics | ~50 each |

## Constraints
- Python 3.10+, stdlib + PyYAML only
- Don't break existing 433 tests
- METRIC_NOISE_THRESHOLDS in diagnose.py and run_stress_test.py MUST stay in sync
- Heavy comments explaining WHY, especially for values sourced from real docs (cite the source)
- Every fact from the knowledge docs should be traceable: add a comment like "# Source: [doc name], section X"

## Success Criteria
- All corrections are traceable to specific facts in the knowledge docs
- All existing 433 tests still pass (or intentionally updated)
- Eval stress test: all 5 GREEN (scores may change — that's expected if rubrics change)
- User confirms the corrections match their domain understanding
- Memory files updated with the new ground-truth values
```
