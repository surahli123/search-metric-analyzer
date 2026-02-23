# Synthetic Validation Quickstart

## Purpose
This quickstart runs synthetic scenario validation for Search Quality diagnosis on scenarios `S0-S12`.

## Prerequisites
- `python3`
- `pip3` (not required for this stdlib-only workflow)

## Run
From `/Users/surahli/Documents/New project/Search_Metric_Analyzer`:

1. Write starter templates:
```bash
python3 generators/generate_synthetic_data.py --write-templates-only
```

2. Generate synthetic datasets:
```bash
python3 generators/generate_synthetic_data.py --rows-per-scenario 20000 --output-dir data/synthetic
```

3. Validate generated scenarios:
```bash
python3 generators/validate_scenarios.py --input-dir data/synthetic --output-dir data/synthetic
```

## Artifacts
- `templates/scenario_knobs_template.csv`
- `templates/session_log_template.csv`
- `templates/metric_aggregate_template.csv`
- `data/synthetic/synthetic_search_session_log.csv`
- `data/synthetic/synthetic_metric_aggregate.csv`
- `data/synthetic/validation_results.csv`
- `data/synthetic/validation_report.md`
- `data/synthetic/generation_summary.json`

## Notes
- Canonical formula invariants are enforced in validation:
  - `search_quality_success_component_click == click_quality_value`
  - `search_quality_success_value == max(click_quality_value, search_quality_success_component_ai)`
- Scenario signature checks are semantic/noise-tolerant (markers + directionality) for `S0-S12`, not strict exact-delta equality.
- Contract hard guards:
  - `S7` cannot produce a single-cause high-confidence outcome.
  - `S8` is always forced to `blocked_by_data_quality`.
- Long-click is computed from next query in the same session using the 40-second rule.
- `tools/generate_synthetic_data.py` and `tools/validate_scenarios.py` are wrapper entrypoints that delegate to `generators/*`.

## Troubleshooting
- If script execution fails, rerun with explicit paths from repo root.
- If validation fails, inspect `data/synthetic/validation_report.md` for failing scenarios and predicted labels.
