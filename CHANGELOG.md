# Changelog — Search Metric Analyzer

All notable changes to this project are documented here.
Format: version, date, summary, then categorized changes.

---

## v1.5.4 — Minimal Multi-Agent Bridge Spike (2026-02-23)

Forward-port + completion pass for the v1.5 minimal connector bridge.

### Connector Investigator Spike
- `tools/connector_investigator.py`
  - adds bounded connector investigation helper (`max_queries=3`, `timeout_seconds=120`)
  - returns deterministic `confirmed|rejected` verdict payloads with query/evidence traces
- `tools/diagnose.py`
  - adds optional `connector_investigator` hook in `run_diagnosis()`
  - executes only when `decision_status=diagnosed` and confidence is `Medium|Low`
  - connector rejection downgrades to `decision_status=insufficient_evidence` and `confidence=Low`
  - preserves trust-gate and overlap contracts:
    - trust-gate fail -> `blocked_by_data_quality`
    - `aggregate.severity=blocked` with `aggregate.original_severity` preserved
    - unresolved overlap -> `insufficient_evidence`

### Stress-Path Spike Switch
- `eval/run_stress_test.py`
  - adds `--enable-connector-spike` CLI flag
  - wires a bounded local connector runner into diagnosis calls when enabled

### Tests + Docs
- `tests/test_connector_investigator.py`
  - contract coverage for max-query bounds and timeout rejection behavior
- `tests/test_diagnose.py`
  - connector gating + rejection downgrade coverage
- `tests/test_eval.py` and `tests/test_tool_entrypoints.py`
  - connector spike CLI flag parsing/help coverage
- `README.md`
  - records connector investigator spike contract and stress CLI usage

## v1.5.3 — Blocked Severity Semantics + Calibration Tightening (2026-02-23)

Focused continuation to finalize blocked-by-data-quality semantics, tighten
S9 confidence calibration behavior, reduce enterprise fallback usage, and add
an optional machine-readable stress artifact for CI diffing.

### Diagnosis + Formatting
- `tools/diagnose.py`
  - trust-gate failures now set `aggregate.severity` to `blocked`
  - preserves pre-blocked severity in `aggregate.original_severity`
  - adds explicit `severity_override_reason` for blocked contract state
  - introduces a mix-shift confidence floor:
    - diagnosed `mix_shift_composition` with `mix_shift >= 30%` no longer drops to `Low`
    - confidence is calibrated to `Medium` unless stronger blockers apply
- `tools/formatter.py`
  - adds `blocked` severity emoji mapping
  - business impact now states: diagnosis is blocked pending data quality recovery

### Eval Calibration + Spec Contract
- `eval/scoring_specs/case4_mix_shift.yaml`
  - added `underconfident_mix_shift` anti-pattern rule
- `eval/run_eval.py`
  - added explicit detection for `underconfident_mix_shift`
  - applies a 15-point deduction when a diagnosed clear mix-shift case is marked `Low` confidence

### Synthetic Validator Attribution
- `generators/validate_scenarios.py`
  - added one lightweight S12 signal (`ai_on_ai_trigger_delta` magnitude) to signature checks
  - S12 prediction heuristic now accepts strong AI-on trigger-shift evidence when AI-on success delta is noisy
  - further reduces scenario-id fallback dependence for S9-S12 without adding complexity

### Stress Eval Artifact Output
- `eval/run_stress_test.py`
  - added optional `--artifact-json <path>` CLI flag
  - added `build_stress_artifact()` machine-readable summary/case payload
  - artifact includes case scores, verdicts, decision status, confidence, severity, and violation rules

### Tests
- `tests/test_diagnose.py`
  - blocked severity contract assertion for trust-gate failures
  - mix-shift confidence floor regression test
- `tests/test_formatter.py`
  - blocked severity/report language assertion
- `tests/test_eval.py`
  - S9 underconfident mix-shift penalty assertion
  - S8 blocked severity assertion in stress pipeline
  - stress artifact schema helper test
- `tests/test_validate_scenarios.py`
  - AI-on trigger-shift migration classification regression test
- Suite status: `513 passed`.

## v1.5.2 — Stress Framing + Diagnostics Expansion (2026-02-22)

Focused follow-up to tighten compositional framing, extend stress eval coverage,
and improve validator debuggability while keeping the 4-tool architecture intact.

### Diagnosis + Formatting
- `tools/diagnose.py`
  - mix-shift activation now overrides `no_significant_movement` framing when
    mix-shift check is `INVESTIGATE` (prevents S9 false-alarm-style narratives)
  - false-alarm inference no longer triggers when significant mix-shift is present
- `tools/formatter.py`
  - key findings now state:
    - `compositional change dominates` when mix-shift >= 30%
    - `behavioral change dominates` otherwise

### Stress Eval Coverage
- Added `eval/scoring_specs/case6_data_quality_gate.yaml` for explicit S8 contract scoring.
- `eval/run_stress_test.py`
  - added S8 stress case (`Data quality gate block`)
  - updated configured stress matrix from 5 to 6 scenarios
  - summary counts now use dynamic case totals instead of hardcoded `/5`

### Synthetic Validator Diagnostics + Attribution
- `generators/validate_scenarios.py`
  - added signature sub-check diagnostics via `signature_sub_checks()`
  - `validation_results.csv` now includes `signature_failed_checks`
  - `validation_report.md` now includes per-scenario signature failure details
  - reduced S9-S12 scenario-id routing reliance with heuristic-first attribution:
    - mix-shift composition detection (share-shift + per-tier stability)
    - connector regression/auth-expiry detection via dominant connector drop
    - ai-model migration detection via AI deltas + ai_on success degradation
  - kept scenario-id fallback only for ambiguous enterprise cases

### Tests
- `tests/test_diagnose.py`
  - added regression coverage: high mix-shift must not be framed as false alarm
- `tests/test_formatter.py`
  - added compositional wording assertion for high mix-shift Slack output
- `tests/test_eval.py`
  - added case6 scoring spec coverage and S8 decision_status contract assertions
  - added stress-path S8 decision_status assertion
- `tests/test_validate_scenarios.py`
  - added signature diagnostics column checks
  - added heuristic attribution tests for S9-S12 without scenario-id routing
- Suite status: `507 passed`.

## v1.5.1 — Contract Hardening (2026-02-22)

Focused hardening pass for synthetic/eval contract alignment with no architecture expansion.

### Synthetic Validation
- `generators/validate_scenarios.py`
  - replaced strict exact-delta signature checks with noise-tolerant scenario signatures for `S0-S12`
  - tuned noisy classification thresholds for `S2-S7` (notably `S3`, `S4`, `S6`)
  - kept hard guards:
    - `S7` cannot emit single-cause high confidence
    - `S8` is forced to `blocked_by_data_quality`
- Canonical synthetic dataset validation now reports `13/13` pass.

### Eval Contract
- `eval/run_eval.py`
  - added explicit `decision_status` contract violations in scoring (`decision_status_contract`)
  - default expectation: `diagnosed`
  - scenario overrides:
    - `S7` -> `insufficient_evidence`
    - `S8` -> `blocked_by_data_quality`
- `eval/run_stress_test.py`
  - now records and prints `decision_status` in case breakdown output.

### Tests
- Added `tests/test_tool_entrypoints.py` for `python3 tools/*.py --help` compatibility checks.
- Added `tests/test_validate_scenarios.py` for synthetic contract behavior (`S7`/`S8` guards + canonical dataset pass).
- Added eval contract tests and stress-path decision-status assertions in `tests/test_eval.py`.
- Suite status: `484 passed`.

## v1.5 — Contract Baseline Alignment (2026-02-22)

Lean v1 contract-alignment release to remove doc/code/schema drift without adding architecture complexity.

### Contract + Schema
- Added `tools/schema.py` as canonical normalization layer:
  - metric alias bridge: `dlctr_value/qsr_value/sain_trigger/sain_success` -> canonical names
  - trust-gate field normalization: `data_completeness|completeness_pct`, `data_freshness_min|freshness_lag_min`
  - diagnosis payload normalization with default `decision_status`

### Tool Updates
- `tools/anomaly.py`
  - `check_data_quality()` now accepts both trust-field variants
  - emits normalized trust-gate averages:
    - `avg_completeness`, `avg_completeness_pct`
    - `avg_freshness_min`, `avg_freshness_lag_min`
- `tools/decompose.py`
  - normalizes metric names and row fields via schema bridge
- `tools/diagnose.py`
  - new CLI args: `--co-movement-json`, `--trust-gate-json`
  - `run_diagnosis()` accepts `trust_gate_result`
  - emits `decision_status`: `diagnosed|blocked_by_data_quality|insufficient_evidence`
  - enforces trust-gate blocking: no definitive RCA on trust-gate fail
  - enforces unresolved-overlap downgrade path
- `tools/formatter.py`
  - consumes normalized diagnosis payload
  - renders TL;DR with decision-status-aware language

### Synthetic Pipeline Consolidation
- `generators/*` is now the canonical implementation.
- `tools/generate_synthetic_data.py` and `tools/validate_scenarios.py` are thin wrappers to `generators/*`.

### Eval
- `eval/run_eval.py`
  - added executable 3-run majority helper (`run_three_run_majority`)
  - CLI diagnosis scoring now reports 3-run majority bundles
- `eval/run_stress_test.py`
  - executes 3 scoring runs per case
  - reports run scores/grades plus majority verdict
  - passes trust-gate result into diagnosis

### Docs
- Added single v1 source-of-truth:
  - `docs/plans/2026-02-22-v1-contract-baseline.md`
- Updated for canonical schema/CLI behavior:
  - `README.md`
  - `README_synthetic_validation.md`
  - `skills/search-metric-analyzer.md`

---

## v1.4 — DS-STAR Learnings + Metric Rename (2026-02-22)

Adapted two patterns from Google's DS-STAR multi-agent paper: a deterministic
post-diagnosis Verifier and scored (rank-all) archetype matching. Also fixed a
silent rendering bug in the v1.3 archetype, added structured subagent specs,
and renamed all internal metric names for public repo safety.

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

### Refactoring
- **Internal metric rename** (31 files, 1480+ lines changed): Renamed all internal
  metric names across the entire codebase for public repo safety.
  - `dlctr` / `dlctr_value` → `click_quality` / `click_quality_value`
  - `qsr` / `qsr_value` → `search_quality_success` / `search_quality_success_value`
  - `sain_trigger` → `ai_trigger`
  - `sain_success` → `ai_success`
  - Affected: tools, tests, eval specs, generators, YAML knowledge, skill file, docs

### Tests
- 28 new tests: 8 scored matching, 5 archetype validation, 15 verify_diagnosis
- 2 existing tests updated for scored matching behavior
- Total: 461 tests (441 run + 20 skipped), 0 failures

### Eval
- All 5 scenarios remain GREEN, average 91.2/100 (unchanged from v1.3)
- Zero verification warnings on all existing eval scenarios

### Documentation
- **DS-STAR Critique** (`docs/plans/DS_STAR_CRITIQUE.md`): IC9-level multi-judge
  review of Google's DS-STAR paper. 3 judges (Search Systems Architect, Metric
  Diagnosis Domain Expert, Production Engineering Pragmatist). Includes full raw
  reviews in appendix.

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
