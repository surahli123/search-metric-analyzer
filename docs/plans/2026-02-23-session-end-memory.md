# Session-End Memory (2026-02-23)

## Session Summary

Implemented all four requested continuation goals on `codex/v1-contract-baseline` while preserving constraints:

- Kept 4-tool architecture (`decompose`, `anomaly`, `diagnose`, `formatter`).
- No multi-agent architecture files.
- No causal engine or real-data connectors.
- Preserved one-release alias bridge behavior.

Primary outcomes:
- Finalized `blocked_by_data_quality` severity semantics (`severity=blocked` with preserved `original_severity`).
- Tightened S9 confidence calibration contract without over-rewarding underconfident compositional diagnoses.
- Reduced S9-S12 fallback reliance further using one lightweight S12 signal.
- Added optional machine-readable stress artifact output for CI regression diffing.

## What Changed

### 1) Final severity semantics for blocked-by-data-quality

- `tools/diagnose.py`
  - On trust-gate fail, diagnosis now sets:
    - `decision_status = blocked_by_data_quality`
    - `aggregate.severity = blocked`
    - `aggregate.original_severity` preserved from pre-block value
    - `aggregate.severity_override_reason` set explicitly
- `tools/formatter.py`
  - Added `blocked` severity emoji mapping.
  - Business impact section now states diagnosis is blocked pending data quality recovery (instead of normal monitoring language).

### 2) S9 confidence calibration tightening in eval scoring/spec

- `eval/scoring_specs/case4_mix_shift.yaml`
  - Added anti-pattern rule: `underconfident_mix_shift`.
- `eval/run_eval.py`
  - Added explicit rule evaluation for `underconfident_mix_shift`.
  - Deduction is `15` points when a diagnosed, clear compositional case (`mix_shift >= 30%`) is labeled `Low` confidence.
- `tools/diagnose.py`
  - Added compositional confidence floor:
    - diagnosed `mix_shift_composition` with strong compositional signal is calibrated to at least `Medium`.

Result: S9 is now calibrated and remains GREEN in stress runs (confidence Medium, not Low).

### 3) Reduced scenario-id fallback for S9-S12 with one lightweight signal

- `generators/validate_scenarios.py`
  - Added `ai_on_ai_trigger_delta` as lightweight S12 signal in both signature checks and prediction heuristic.
  - S12 can now be inferred from strong AI-on trigger-shift evidence even when AI-on success delta is noisy.

### 4) Optional machine-readable stress output artifact

- `eval/run_stress_test.py`
  - Added `--artifact-json <path>` flag.
  - Added `build_stress_artifact()` payload with:
    - summary counts/scores
    - per-case score/grade/run metrics
    - decision_status/confidence/severity
    - violation rules

Example verified path in-session: `/tmp/stress_eval_results.json`.

## Tests Added/Updated

- `tests/test_diagnose.py`
  - trust-gate fail now asserts blocked severity contract fields
  - mix-shift compositional confidence floor regression
- `tests/test_formatter.py`
  - blocked-by-data-quality report/severity language assertion
- `tests/test_eval.py`
  - S9 underconfident mix-shift penalty assertion
  - S8 blocked severity assertion in stress path
  - machine-readable artifact helper shape assertion
- `tests/test_validate_scenarios.py`
  - AI-on trigger-shift migration inference regression

## Verification Evidence (Fresh)

Required command sequence executed in order:

1. `python3 generators/generate_synthetic_data.py --rows-per-scenario 20000 --output-dir data/synthetic`
   - Exit `0`
2. `python3 generators/validate_scenarios.py --input-dir data/synthetic --output-dir data/synthetic`
   - Exit `0`
   - `validation_report.md`: `13/13` scenarios pass
3. `python3 eval/run_stress_test.py`
   - Exit `0`
   - `6/6` GREEN (`S4`, `S5`, `S7`, `S8`, `S9`, `S0`)
   - S8 severity now `blocked`
   - S9 confidence now `Medium`
4. `pytest -q`
   - Exit `0`
   - `513 passed`

Additional optional artifact verification:
- `python3 eval/run_stress_test.py --artifact-json /tmp/stress_eval_results.json`
  - Exit `0`
  - Artifact written with expected summary/case schema

## Mistakes / Lessons

1. Initial S9 underconfidence penalty made stress RED before confidence semantics were adjusted.
   - Lesson: eval strictness and diagnosis confidence calibration must be tuned together to avoid false regressions.
2. A formatter patch accidentally short-circuited Slack generation for blocked cases.
   - Lesson: when patching shared helpers, re-run focused formatter tests immediately and inspect full function outputs.
3. Blocked severity semantics were clearer in diagnosis payload than in report impact language initially.
   - Lesson: contract-level state changes need payload + formatter coherence checks in the same PR.

## AGENTS.md / CLAUDE.md Proposals (Concrete)

1. Add calibration coupling checklist:
   - "When adding eval penalties for confidence miscalibration, add/verify matching diagnosis confidence policy to avoid synthetic stress false RED regressions."
2. Add blocked-state consistency checklist:
   - "If `decision_status=blocked_by_data_quality`, assert payload severity semantics and formatter business-impact wording in tests."
3. Add stress artifact contract reminder:
   - "When adding machine-readable artifacts, include one schema-shape regression test plus one CLI-path smoke check."
4. Add patch-safety guideline:
   - "For formatter helper edits, run targeted tests on both Slack and short report outputs before full suite."

## Next Session Tasks

1. Decide whether blocked severity should remain `blocked` for one release or be normalized to a dedicated enum in schema docs.
2. Add a small docs section for `--artifact-json` usage and recommended CI path conventions.
3. Consider tightening S4 confidence expectation separately (currently Medium still scores GREEN due existing rubric weighting).
4. Optional: emit stress artifact to a repo-local deterministic path during CI jobs and diff against previous baseline.
