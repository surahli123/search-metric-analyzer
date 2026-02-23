# Synthetic Validation Scenarios for Search Metric Diagnosis

## 1) Purpose
This document defines a deterministic synthetic scenario pack to validate diagnosis logic for seasonality, L3/interleaver shifts (3P vs 1P), SAIN behavior, overlap handling, and data-quality blocking.

Canonical metric definitions:
- `qsr_component_click = dlctr_value`
- `qsr_component_sain = sain_success * sain_trigger`
- `qsr_value = greatest(qsr_component_click, qsr_component_sain)`

## 2) Baseline Calibration
Baseline defaults (synthetic):
- `dlctr_mean = 0.280`
- `sain_trigger_rate = 0.220`
- `sain_success_rate = 0.620`
- `qsr_mean`: derived from row-level formula (generator computes and snapshots baseline value)
- `p3_click_share = 0.270` (`1p_click_share = 0.730`)
- `mean_clicked_rank = 2.6`

Metric-note invariants:
- `qsr_component_click = dlctr_value`
- `qsr_component_sain = sain_success * sain_trigger`
- `qsr_value = greatest(qsr_component_click, qsr_component_sain)`

## 3) Step-by-Step Scenario Design
1. Build a stable baseline with realistic connector mix and rank-click decay.
2. Add single-factor scenarios (seasonality-only, L3-only, SAIN-only) to validate identifiability.
3. Add overlap scenarios (seasonality + L3, L3 + SAIN) to validate confidence downgrade and abstain behavior.
4. Add a non-product anomaly scenario (logging drift) to validate trust-gate blocking.
5. Define pass/fail assertions for metric signature and diagnosis outputs.

## 4) Revised Scenario Pack (9)
| ID | Scenario | What changes | Expected metric signature | Expected diagnosis outcome |
|---|---|---|---|---|
| S0 | Baseline stable | No release/experiment change | QSR and DLCTR stable | `no_incident` |
| S1 | Normal seasonality (weekly pattern) | Day-of-week demand/query-mix shifts only | Predictable cyclical DLCTR/QSR movement; no structural break | `seasonality_only` with high confidence |
| S2 | Seasonality shock | Holiday/event query-mix spike; no product change markers | Sudden movement, concentrated in time/query classes, connectors unchanged | `seasonality_shock` with medium-high confidence |
| S3 | L3 3P boost (benign) | Interleaver promotes 3P moderately for exploratory queries | Connector mix shifts to 3P, DLCTR near-flat/slight down, QSR near-flat/up | `l3_interleaver_change` with medium confidence |
| S4 | L3 3P overboost (harmful to 1P intent) | Strong 3P promotion on navigational/1P-heavy intents | DLCTR down, deeper clicks, 1P click share down, QSR down/flat | `l3_interleaver_regression` with high confidence |
| S5 | SAIN uplift with click cannibalization | Higher SAIN trigger+success, ranking unchanged | DLCTR down, SAIN component up, QSR flat/up | `sain_behavior_shift` (not ranking regression) |
| S6 | SAIN regression | SAIN trigger high but success drops | QSR down in SAIN-triggered cohort, DLCTR mixed | `sain_regression` with high confidence |
| S7 | Overlap: seasonality + L3 | S2 and S4 concurrently active | Mixed signatures: query-mix shift + 3P share shift + depth changes | `multi_candidate_unresolved_overlap` (confidence downgrade) |
| S8 | Logging/metric anomaly | Event completeness/join coverage degraded | Abrupt QSR/DLCTR jump inconsistent with behavior/connectors | `blocked_by_data_quality` |

## 5) Scenario Knobs (Numeric)
All relative deltas are measured against baseline means from Section 2.

| scenario_id | volume_delta_rel | exploratory_query_share_delta_abs | p3_click_share_delta_abs | mean_clicked_rank_delta_abs | sain_trigger_rate_delta_abs | sain_success_rate_delta_abs | expected_dlctr_delta_abs | expected_dlctr_delta_rel | expected_qsr_delta_abs | expected_qsr_delta_rel |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S0 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.000 | +0.0% | +0.000 | +0.0% |
| S1 | +/-0.06 (sinusoidal) | +0.04 weekday cycle | +0.00 | +/-0.10 | +0.00 | +0.00 | +/-0.010 | +/-3.6% | +/-0.008 | +/-2.4% |
| S2 | +0.18 (shock window) | +0.12 | +0.00 | +0.20 | +0.00 | +0.00 | -0.015 | -5.4% | -0.010 | -2.9% |
| S3 | +0.02 | +0.08 | +0.08 | +0.20 | +0.00 | +0.00 | -0.006 | -2.1% | +0.004 | +1.2% |
| S4 | +0.01 | -0.05 | +0.18 | +0.80 | +0.00 | +0.00 | -0.035 | -12.5% | -0.022 | -6.5% |
| S5 | +0.00 | +0.00 | +0.00 | +0.50 | +0.12 | +0.10 | -0.020 | -7.1% | +0.006 | +1.8% |
| S6 | +0.00 | +0.00 | +0.00 | +0.10 | +0.10 | -0.25 | +/-0.005 | +/-1.8% | -0.030 | -8.8% |
| S7 | +0.19 (combined) | +0.07 (combined) | +0.18 | +1.00 | +0.00 | +0.00 | -0.045 | -16.1% | -0.030 | -8.8% |
| S8 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.000 | +0.0% | +0.000 | +0.0% |

## 6) Pass Bands (Absolute + Relative)
Signature passes only if both conditions hold:
- `abs(observed_abs_delta - expected_abs_delta) <= abs_tolerance`
- `abs(observed_rel_delta - expected_rel_delta) <= rel_tolerance`

Default tolerances:
- DLCTR: abs `+/-0.006`, rel `+/-2.0%`
- QSR: abs `+/-0.008`, rel `+/-2.5%`
- Connector-share: abs `+/-0.02`
- Mean clicked rank: abs `+/-0.25`

## 7) Rule-Based Confidence Rubric
Score range: `0..100`

Components:
- Signature match: `0..40`
- Cohort specificity match (query_class/connector/SAIN cohort): `0..20`
- Marker alignment (release/experiment timing): `0..20`
- Disconfirming-check success: `0..20`

Penalties:
- Unresolved overlap: `-25`
- Any trust-gate warn: `-15`
- Any trust-gate fail: force `blocked_by_data_quality` (no confidence label)

Label mapping:
- `>=80`: `high`
- `60..79`: `medium`
- `40..59`: `low`
- `<40`: `insufficient_evidence`

Mandatory rule:
- S7 cannot end as a single-cause `high` confidence diagnosis.

Validator output interface fields:
- `diagnosis_score` (int)
- `confidence_label` (`high|medium|low|insufficient_evidence|none`)
- `penalty_flags` (array of penalty codes)

## 8) Long-Click Edge Rules
- If `clicked_rank is null`: `is_long_click = 0`
- If click exists and next query is missing in same session: `is_long_click = 1`
- If `next_event_ts <= click_ts`: mark row as data-quality anomaly, exclude from metric computation, and include in S8 gate checks
- Primary criterion remains the 40-second rule from `click_ts` to next query timestamp

## 9) Trust-Gate Thresholds for S8
Fail thresholds:
- Freshness lag fail: `>180 min`
- Completeness fail: `<98.0%`
- Join coverage fail: `<97.0%`

Warn thresholds:
- Freshness lag warn: `>90 and <=180 min`
- Completeness warn: `>=98.0% and <99.5%`
- Join coverage warn: `>=97.0% and <99.0%`

Expected behavior:
- If any fail threshold is hit, expected diagnosis is `blocked_by_data_quality`

## 10) Minimal Interface Additions
Keep existing single base table + metric aggregate table design. Required fields:
1. `event_ts` for seasonality patterns.
2. `clicked_connector` and `ranked_results.connector` for 1P/3P attribution.
3. `experiment_id` and `release_id` for L3 treatment markers.
4. `query_class` (synthetic control field).
5. `seasonality_tag` (synthetic control field).

No new raw data tables are required.

## 11) Pass/Fail Assertions
1. Signature check: observed metric patterns match expected absolute and relative bands.
2. Attribution check: top diagnosis label matches expected root cause.
3. Confidence check: overlap scenarios must downgrade confidence or abstain.
4. Component check: `qsr_component_click == dlctr_value` always.
5. Formula check: `qsr_value == greatest(dlctr_value, sain_success * sain_trigger)` always.
6. Data-quality check: S8 must produce `blocked_by_data_quality`.

## 12) Assumptions and Defaults
1. Connector taxonomy reliably maps 1P vs 3P.
2. L3 change is represented by `experiment_id` or `release_id`.
3. Seasonality effects are simulated by time/query-mix distributions, not hidden product changes.
4. Scenario knobs are synthetic controls, not inferred from production logs.
5. Numeric defaults are v1 calibration values and may be tuned after first dry run.
6. Confidence rubric is deterministic and auditable; no learned calibration in this phase.

## 13) Execution
Run from `/Users/surahli/Documents/New project/Search_Metric_Analyzer`:

1. Generate starter CSV templates:
`python3 tools/generate_synthetic_data.py --write-templates-only`

2. Generate synthetic data (default 20,000 rows per scenario):
`python3 tools/generate_synthetic_data.py --rows-per-scenario 20000 --output-dir data/synthetic`

3. Validate scenarios and emit reports:
`python3 tools/validate_scenarios.py --input-dir data/synthetic --output-dir data/synthetic`

Expected artifacts:
- `data/synthetic/synthetic_search_session_log.csv`
- `data/synthetic/synthetic_metric_aggregate.csv`
- `data/synthetic/validation_results.csv`
- `data/synthetic/validation_report.md`

## 14) Validation Findings Snapshot
Run snapshot (2026-02-07):
- Total scenarios: `9`
- Passed scenarios: `9`
- Failed scenarios: `0`
- Formula invariant violations: `0`

Observed key outcomes:
- `S7` correctly produced overlap-aware downgrade (`multi_candidate_unresolved_overlap`, low confidence), not a forced single-cause high-confidence diagnosis.
- `S8` correctly produced `blocked_by_data_quality` when trust-gate fail conditions were present.
- Formula invariants held across all rows:
  - `qsr_component_click == dlctr_value`
  - `qsr_value == greatest(qsr_component_click, qsr_component_sain)`

Evidence artifacts:
- `/Users/surahli/Documents/New project/Search_Metric_Analyzer/data/synthetic/validation_results.csv`
- `/Users/surahli/Documents/New project/Search_Metric_Analyzer/data/synthetic/validation_report.md`
