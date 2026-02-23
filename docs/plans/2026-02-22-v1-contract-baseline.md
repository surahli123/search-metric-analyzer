# V1 Contract Baseline (2026-02-22)

This file is the single v1 source of truth for contract behavior across code, docs, CLI, and synthetic validation.

## Scope

- Keep current 4-tool pipeline: `decompose -> anomaly -> diagnose -> formatter`.
- Do not add multi-agent architecture files.
- Do not add causal engine or real-data connectors.
- Use one-release alias bridge for legacy metric names.

## Canonical Schema

### Canonical metric fields

- `click_quality_value`
- `search_quality_success_value`
- `ai_trigger`
- `ai_success`

### Legacy alias bridge (one release)

- `dlctr_value` -> `click_quality_value`
- `qsr_value` -> `search_quality_success_value`
- `sain_trigger` -> `ai_trigger`
- `sain_success` -> `ai_success`

Bridge behavior:

- Inputs accept canonical and legacy names.
- Normalization adds canonical keys.
- Compatibility output also exposes legacy keys for this release.

### Trust-gate fields

Accepted input variants:

- `data_completeness` (ratio 0-1) or `completeness_pct` (0-100)
- `data_freshness_min` or `freshness_lag_min`

Normalized output includes:

- `avg_completeness`, `avg_completeness_pct`
- `avg_freshness_min`, `avg_freshness_lag_min`

Thresholds:

- fail if completeness < `0.96`
- fail if freshness > `60` minutes
- warn if completeness < `0.98` or freshness > `30` minutes

## Tool Contracts

### `tools/decompose.py`

- Accepts canonical and legacy metric names.
- Emits canonical aggregate metric name.
- Preserves existing output shape:
  - `aggregate`
  - `dimensional_breakdown`
  - `mix_shift`
  - `dominant_dimension`
  - `drill_down_recommended`

### `tools/anomaly.py`

- `check_data_quality()` accepts both trust field variants.
- Trust-gate result always returns normalized averages and `status` in `{pass,warn,fail}`.

### `tools/diagnose.py`

New input options:

- `--co-movement-json <file>`
- `--trust-gate-json <file>`

`run_diagnosis()` input adds:

- `trust_gate_result` (optional dict)

Output adds:

- `decision_status` in `{diagnosed, blocked_by_data_quality, insufficient_evidence}`
- `trust_gate_result` (normalized)

Decision-status rules:

- `blocked_by_data_quality` when trust gate `status=fail`.
- `insufficient_evidence` when overlapping multi-cause attribution is unresolved.
- Otherwise `diagnosed`.

Contract guardrails:

- Trust-gate fail blocks definitive RCA.
- S7-style unresolved overlap cannot remain single-cause high confidence.
- Confidence is downgraded on unresolved overlap.

### `tools/formatter.py`

- Normalizes diagnosis payload before rendering.
- Uses canonical metric naming in outputs.
- Handles decision statuses in TL;DR:
  - blocked by data quality
  - insufficient evidence
  - diagnosed

## Synthetic Pipeline Contract

Canonical implementation:

- `generators/generate_synthetic_data.py`
- `generators/validate_scenarios.py`

`tools/*` wrappers:

- `tools/generate_synthetic_data.py` delegates to `generators/generate_synthetic_data.py`
- `tools/validate_scenarios.py` delegates to `generators/validate_scenarios.py`

## Eval Contract

`eval/run_eval.py` and `eval/run_stress_test.py` must execute and report 3-run majority logic:

- run scoring 3 times per case
- aggregate with per-case `pass_threshold` (`3/3 GREEN` or `2/3 GREEN`)
- report run-level scores/grades plus majority verdict

## Required Scenario Behavior

- S7: must not produce single-cause high-confidence conclusion when overlap is unresolved.
- S8: must return `blocked_by_data_quality`.

## Validation Commands

```bash
python3 generators/generate_synthetic_data.py --rows-per-scenario 20000 --output-dir data/synthetic
python3 generators/validate_scenarios.py --input-dir data/synthetic --output-dir data/synthetic
python3 eval/run_stress_test.py
pytest -q
```
