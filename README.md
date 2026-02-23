# Search Metric Analyzer

A diagnostic tool for Enterprise Search metric movements. Built for Senior Data Scientists debugging why search quality metrics moved — and whether they should care.

## v1 Contract Highlights

- Canonical metric schema: `click_quality_value`, `search_quality_success_value`, `ai_trigger`, `ai_success`.
- One-release legacy alias bridge: `dlctr_value`, `qsr_value`, `sain_trigger`, `sain_success`.
- Trust gate is contract-enforced: trust-gate fail blocks definitive diagnosis.
- Diagnosis output includes `decision_status`:
  - `diagnosed`
  - `blocked_by_data_quality`
  - `insufficient_evidence`
- Synthetic validator uses noise-tolerant scenario signatures (S0-S12) instead of strict exact-delta matching.
- Hard scenario contracts:
  - S7 cannot resolve to single-cause high confidence.
  - S8 is always `blocked_by_data_quality`.
- Eval scoring enforces `decision_status` contract checks (notably S7/S8 behavior).
- Synthetic pipeline is canonical in `generators/*`; `tools/*` generator scripts are wrappers only.

## What It Does

When a search metric moves, this tool runs a 4-step diagnostic pipeline:

1. **Decompose** — Kitagawa-Oaxaca decomposition to isolate which segments drove the movement (tenant tier, AI enablement, connector type, product source). Separates real quality changes from mix-shift.

2. **Anomaly Detection** — Step-change detection, co-movement pattern matching across metrics, and data quality gates. Identifies whether the movement is a real signal or noise.

3. **Diagnose** — Archetype recognition (ranking regression, AI adoption effect, broad degradation, query understanding regression, etc.), confidence scoring, and false alarm detection.

4. **Format** — Slack-ready summary and short report with TL;DR, root cause hypothesis, confidence level, evidence, and recommended next steps with owners.

## Key Design Decisions

- **AI adoption is not a regression.** When AI answers work well, Long Click CTR related metrics drops because users get answers without clicking. The tool detects this co-movement pattern and correctly labels it as a positive signal.
- **Mix-shift is the most common false alarm.** ~30-40% of Search metric movements are caused by changes in traffic composition, not quality. The tool quantifies mix-shift contribution before diagnosing.
- **False alarms get high confidence.** If all metrics are within normal variation and no single segment dominates, the tool says "no action needed" with high confidence — rather than hedging.

## Quick Start

```bash
# Install dependencies (just PyYAML)
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Run eval stress test (5 scenarios)
python3 eval/run_stress_test.py

# Run individual tools
python3 tools/decompose.py --input data.csv --metric click_quality_value
python3 tools/anomaly.py --input data.csv --metric click_quality_value --check data_quality
python3 tools/diagnose.py --input decomposition.json --co-movement-json co_movement.json --trust-gate-json trust_gate.json
python3 tools/formatter.py --input diagnosis.json
```

## Project Structure

```
Search_Metric_Analyzer/
├── data/
│   ├── knowledge/
│   │   ├── metric_definitions.yaml    # Metric formulas, noise profiles, co-movement patterns
│   │   └── historical_patterns.yaml   # Known incident patterns, seasonal effects
│   └── synthetic/                     # Generated test data (gitignored, regenerable)
├── tools/
│   ├── decompose.py                   # Kitagawa-Oaxaca decomposition + mix-shift
│   ├── anomaly.py                     # Step-change detection, co-movement matching
│   ├── diagnose.py                    # Archetype recognition, confidence scoring
│   ├── formatter.py                   # Slack message + short report generation
│   ├── schema.py                      # Canonical schema normalization + alias bridge
│   ├── generate_synthetic_data.py     # Wrapper -> generators/generate_synthetic_data.py
│   └── validate_scenarios.py          # Wrapper -> generators/validate_scenarios.py
├── generators/
│   ├── generate_synthetic_data.py     # Canonical synthetic data generator (S0-S12)
│   └── validate_scenarios.py          # Canonical synthetic validator
├── eval/
│   ├── run_stress_test.py             # Full pipeline eval (5 scenarios, scored)
│   └── scoring_specs/                 # Per-scenario scoring rubrics (YAML)
├── tests/                             # 484 unit tests
├── skills/
│   └── search-metric-analyzer.md      # Claude Code skill file
├── templates/                         # CSV templates for input data
└── docs/plans/                        # Design docs and session prompts
```

## Metrics Tracked

| Metric | What It Measures |
|--------|-----------------|
| **`click_quality_value`** | Click quality / long-click effectiveness |
| **`search_quality_success_value`** | Composite quality signal across click and AI-answer success |
| **`ai_trigger`** | How often AI answers are shown |
| **`ai_success`** | How often shown AI answers satisfy users |

## Archetypes

The diagnostic engine recognizes these failure patterns:

| Archetype | Co-Movement Signature | What It Means |
|-----------|----------------------|---------------|
| `ranking_regression` | Click Quality down, Search Quality Success down, AI metrics stable | Ranking model degraded |
| `ai_adoption` | Click Quality down, Search Quality Success stable/up, AI metrics up | AI answers working (positive) |
| `broad_degradation` | All metrics down | System-wide issue |
| `query_understanding` | Click Quality/Search Quality Success/AI trigger down, AI success stable | Query interpretation layer degraded |
| `sain_regression` | AI metrics down, Click Quality stable | AI answer quality issue |
| `mix_shift` | Movement explained by traffic composition | Not a quality change |
| `false_alarm` | All metrics within noise | No action needed |

## Eval Results

Use `python3 eval/run_stress_test.py` to run the 5-case stress eval with 3-run majority reporting and explicit per-case `decision_status`.

## Tech Stack

- Python 3.10+
- Dependencies: PyYAML (stdlib otherwise)
- All tools are CLI scripts that output JSON to stdout
- Designed to be called by Claude Code as a skill

## Knowledge Calibration

The tool's domain knowledge (metric definitions, noise profiles, co-movement patterns) was initially built from assumptions, then calibrated against real Enterprise Search system architecture. Items validated against real systems are tagged with source citations in the YAML files. Items without source tags remain synthetic estimates pending calibration with production data.

Areas still pending real-world calibration:
- Metric noise profiles (weekly standard deviations)
- Per-metric severity thresholds
- Real incident scenarios for eval
- QSR formula exact weights/floors

