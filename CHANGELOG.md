# Changelog — Search Metric Analyzer

All notable changes to this project are documented here.
Format: version, date, summary, then categorized changes.

---

## v1.4 — DS-STAR Learnings (2026-02-21)

Adapted two patterns from Google's DS-STAR multi-agent paper: a deterministic
post-diagnosis Verifier and scored (rank-all) archetype matching. Also fixed a
silent rendering bug in the v1.3 archetype and added structured subagent specs.

### Bug Fixes
- **`query_understanding_regression` archetype**: Used `summary_template` + `action`
  (plain strings) instead of `description_template` + `action_items` (list of dicts).
  The rendering code in `_build_primary_hypothesis()` and `_build_action_items()`
  silently returned None/empty for this archetype. Now consistent with all 8 others.

### New Features
- **Scored co-movement matching** (`anomaly.py`): `match_co_movement_pattern()` now
  scores ALL 9 patterns (0-4 matching fields) and returns the best match with
  `match_score` (0.0-1.0) + `runner_up`. Threshold: >= 0.75 (3/4 fields).
  Special rule: `no_significant_movement` requires exact 4/4 match.
- **`verify_diagnosis()`** (`diagnose.py`): 5 deterministic coherence checks run
  after diagnosis is complete. Catches archetype-segment, severity-action,
  confidence-check, false-alarm, and multi-cause contradictions. Advisory mode —
  warnings surface in output but don't block the diagnosis.
- **Structured subagent specs**: All 9 archetypes now have `confirms_if` and
  `rejects_if` fields — conditions that confirm or reject each hypothesis.
  Designed for production subagent SQL query generation.
- **Formatter integration**: Verification warnings surfaced in Slack messages
  (error-level only) and short reports (all levels).

### Tests
- 28 new tests: 8 scored matching, 5 archetype validation, 15 verify_diagnosis
- 2 existing tests updated for scored matching behavior
- Total: 461 tests (441 run + 20 skipped), 0 failures

### Eval
- All 5 scenarios remain GREEN, average 91.2/100 (unchanged from v1.3)
- Zero verification warnings on all existing eval scenarios

---

## v1.3 — Knowledge Calibration (2026-02-21)

Calibrated knowledge base against real Atlassian Rovo Search architecture
(3 public blog posts). Validated pipeline assumptions, corrected gaps.

### Knowledge Corrections
- Added `query_understanding_regression` archetype (Rovo L0 pipeline stage)
- Added `product_source` decomposition dimension (Rovo L3 Interleaver)
- Added `query_understanding` hypothesis priority
- Enriched `ai_success_rate` definition with engagement + dwell time
- Added Rovo source citations throughout metric_definitions.yaml

### Eval
- All 5 scenarios GREEN, average 91.2/100 (unchanged)

---

## v1.2 — Diagnostic Engine: Archetypes + False Alarm Detection (2026-02-21)

Major diagnostic engine upgrade: archetype recognition, false alarm detection,
mix-shift handling, and formatter polish.

### New Features
- mix_shift archetype + activation logic
- False alarm delta guard (path b respects per-metric noise thresholds)
- HALT guard on confidence override
- Smart multi-cause suppression (dimension-correlation check)
- Formatter polish: direction-derived words, em dashes, monitoring text

### Bug Fixes
- `effective_co_movement` passed to hypothesis/action builders

### Eval
- All 5 scenarios GREEN, average 91.2/100

---

## v1.1 — Eval Fixes (2026-02-21)

First round of fixes driven by eval stress-test results.

### Eval
- S5 (AI adoption trap): 50 → 100
- S0 (False alarm): 47 → 90
- Average: 72.4 → 91.2

---

## v1-alpha — Initial Release (2026-02-21)

4-step diagnostic pipeline: Intake → Decompose → Validate → Synthesize.
5 eval scenarios, deterministic stress-test runner.

### Eval
- 5/5 passing, average 72.4/100
