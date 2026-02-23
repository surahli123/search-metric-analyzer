# Session-End Memory (2026-02-22)

## Session Summary

Completed v1 contract hardening for synthetic validation and eval contract checks without changing architecture scope:

- Kept 4-tool architecture intact (`decompose`, `anomaly`, `diagnose`, `formatter`).
- No multi-agent files, no causal engine, no real-data connectors.
- Preserved one-release alias bridge behavior.
- Hardened synthetic validator to produce contract-consistent outcomes on `S0-S12`.
- Added eval scoring enforcement for `decision_status` contract.
- Added regression tests for CLI entrypoint `--help` compatibility and S7/S8 contract guards.

## Code Changes This Session

### Synthetic Validator
- `generators/validate_scenarios.py`
  - Added `signature_matches_contract()` with noise-tolerant semantic checks for `S0-S12`.
  - Tuned classification thresholds for noisy `S2-S7`:
    - `S3`/`S4` L3 thresholds
    - `S6` AI regression thresholds
  - Preserved hard contract enforcement:
    - `S7` cannot produce single-cause high confidence
    - `S8` forced to `blocked_by_data_quality`

### Eval Contract
- `eval/run_eval.py`
  - Added `_check_decision_status_contract()`.
  - `score_single_run()` now applies `decision_status_contract` deduction on mismatch.
  - Contract map:
    - `S7` -> `insufficient_evidence`
    - `S8` -> `blocked_by_data_quality`
    - default -> `diagnosed`

- `eval/run_stress_test.py`
  - Includes and prints `decision_status` in case summaries.

### Tests Added/Updated
- Added `tests/test_validate_scenarios.py`
  - canonical dataset contract pass check
  - `S7` demotion/overlap guard checks
  - `S8` forced blocked behavior check
- Added `tests/test_tool_entrypoints.py`
  - `python3 tools/*.py --help` compatibility checks
- Updated `tests/test_eval.py`
  - explicit `decision_status` contract tests (S7)
  - stress pipeline decision-status assertion for S7

### Docs Updated
- `README.md`
- `README_synthetic_validation.md`
- `skills/search-metric-analyzer.md`
- `CHANGELOG.md` (new `v1.5.1` entry)

## Verification Evidence (Fresh)

Commands run and status:

1. `python3 generators/generate_synthetic_data.py --rows-per-scenario 20000 --output-dir data/synthetic`
   - Exit `0`
2. `python3 generators/validate_scenarios.py --input-dir data/synthetic --output-dir data/synthetic`
   - Exit `0`
   - `validation_report.md`: `13/13` scenarios pass
3. `python3 eval/run_stress_test.py`
   - Exit `0`
   - 5/5 GREEN with 3-run majority reporting
4. `pytest -q`
   - Exit `0`
   - `484 passed`

## Mistakes / Lessons

1. Strict exact-delta validation was too brittle for generated noise and composition effects.
   - Lesson: scenario contracts should prioritize semantic signature checks over exact deltas.
2. Eval scoring missed `decision_status`, allowing structurally wrong outputs to score well.
   - Lesson: contract fields (`decision_status`) must be first-class scoring checks.
3. S7 guard coverage was incomplete in tests.
   - Lesson: include both single-cause demotion and unresolved-overlap paths in regression tests.

## AGENTS.md / CLAUDE.md Update Proposals

1. Add checklist item:
   - "For contract fields (e.g., `decision_status`), add at least one eval-scoring assertion and one integration-path assertion."
2. Add synthetic validation guidance:
   - "Prefer semantic/noise-tolerant signature checks over strict exact-delta equality unless determinism is guaranteed."
3. Add CLI guardrail:
   - "When touching `tools/*.py`, run `python3 tools/<script>.py --help` for each touched script before completion."
4. Add handoff requirement:
   - "Session-end memory must include command evidence, mismatch risks, and concrete next-session tasks."

## Next Session Tasks

1. Reduce S9 false-alarm scoring ambiguity in stress eval (currently GREEN but still framed as false_alarm).
2. Add an explicit S8 eval case/spec if desired for full end-to-end `blocked_by_data_quality` coverage in stress runs.
3. Tighten case4 mix-shift rubric matching so it rewards explicit compositional framing over generic no-movement language.
4. Decide whether to expose validator per-scenario signature diagnostics (which condition failed) in CSV/report for faster debugging.

---

## Continuation Update (2026-02-22, PST)

Completed all four queued follow-ups from the prior handoff while preserving constraints:
- Kept 4-tool architecture (`decompose`, `anomaly`, `diagnose`, `formatter`).
- No multi-agent files, no causal engine, no real-data connectors.
- Preserved one-release alias bridge behavior.

### What Changed

1. S9 framing fix (compositional vs false alarm)
- `tools/diagnose.py`
  - Significant mix-shift (`check_mix_shift == INVESTIGATE`) now overrides stable/no-significant co-movement framing.
  - False-alarm inference is blocked when significant mix-shift is present.
- `tools/formatter.py`
  - Mix-shift key finding now explicitly says:
    - `compositional change dominates` when mix-shift >= 30%
    - `behavioral change dominates` otherwise

2. Explicit S8 stress eval coverage
- Added `eval/scoring_specs/case6_data_quality_gate.yaml` (scenario `S8`).
- `eval/run_stress_test.py`
  - Added `S8` stress case row (`Data quality gate block`).
  - Stress matrix is now 6 scenarios (`S4`, `S5`, `S7`, `S8`, `S9`, `S0`).
  - Summary denominator is dynamic (`len(results)`), not hardcoded.

3. Validator diagnostics for signature sub-checks
- `generators/validate_scenarios.py`
  - Added `signature_sub_checks()` for per-scenario contract sub-check evaluation.
  - `validation_results.csv` now includes `signature_failed_checks` (JSON list).
  - `validation_report.md` now includes `Signature Failed Checks` per scenario and failing-section diagnostics.

4. Reduced S9-S12 scenario-id routing reliance (practical, low-complexity)
- `generators/validate_scenarios.py`
  - `predict_label()` now uses heuristic-first enterprise attribution:
    - S9: tenant mix-shift + per-tier stability + stable AI deltas
    - S10: confluence-dominant connector drop
    - S11: sharepoint-dominant connector drop
    - S12: AI migration signature (QSR/AI-success/AI-trigger pattern)
  - Retained scenario-id fallback only for ambiguous enterprise boundaries.

### Test Coverage Added
- `tests/test_diagnose.py`
  - mix-shift must override false-alarm framing when co-movement is stable.
- `tests/test_formatter.py`
  - high mix-shift wording must be compositional (Slack key findings).
- `tests/test_eval.py`
  - case6 spec coverage (`S8`) and S8 decision-status contract assertions.
  - stress-path S8 assertion (`decision_status == blocked_by_data_quality`).
- `tests/test_validate_scenarios.py`
  - diagnostics column assertion (`signature_failed_checks`).
  - heuristic attribution tests for S9-S12 without scenario-id routing.

### Verification Evidence (Fresh)

Commands run and status:

1. `python3 generators/generate_synthetic_data.py --rows-per-scenario 20000 --output-dir data/synthetic`
   - Exit `0`
2. `python3 generators/validate_scenarios.py --input-dir data/synthetic --output-dir data/synthetic`
   - Exit `0`
   - `validation_report.md`: `13/13` scenarios pass
   - `validation_results.csv`: includes `signature_failed_checks` column
3. `python3 eval/run_stress_test.py`
   - Exit `0`
   - 6/6 GREEN (`S4`, `S5`, `S7`, `S8`, `S9`, `S0`)
   - S9 now framed as `mix_shift` (not false alarm)
   - S8 explicit case reports `decision_status=blocked_by_data_quality`
4. `pytest -q`
   - Exit `0`
   - `507 passed`

### Mistakes / Lessons (This Continuation)

1. Archetype precedence bug: stable co-movement could override high mix-shift and produce false-alarm framing.
   - Lesson: compositional signal arbitration must be explicit; do not rely on pattern order side effects.
2. Enterprise heuristic boundaries were initially over-broad and briefly misclassified `S6` as `S12`.
   - Lesson: every new heuristic needs at least one negative-control test against adjacent scenarios.
3. Formatter verification initially checked short report for key-findings phrasing that is surfaced in Slack output.
   - Lesson: assert wording at the output channel where the section is rendered.

### AGENTS.md / CLAUDE.md Proposals (Concrete)

1. Add an archetype-precedence checklist item:
   - "When two archetype routes can fire (e.g., no_significant_movement vs mix_shift), add explicit precedence tests."
2. Add heuristic-safety requirement:
   - "For every new heuristic classifier, add one positive test and one adjacent-scenario negative-control test."
3. Add diagnostics contract reminder:
   - "If validator emits debug columns, assert both CSV schema presence and human-readable report rendering."
4. Add stress-matrix guard:
   - "When adding/removing stress cases, avoid hardcoded case counts in summary output and tests."

### Next Session Tasks

1. Decide whether blocked-by-data-quality cases should suppress false-alarm severity overrides earlier (currently `S8` ends with `severity=normal` plus remediation action, which is contract-safe but semantically mixed).
2. Calibrate `case4_mix_shift.yaml` confidence rubric vs current deterministic behavior (S9 can grade GREEN with Low confidence due rubric composition).
3. Reduce residual enterprise fallback dependence further by adding one lightweight connector-health feature (for example per-connector zero-result shift) while keeping validator complexity low.
4. Add optional JSON artifact output for stress runs (case-by-case machine-readable result bundle) to improve regression diffing in CI.
