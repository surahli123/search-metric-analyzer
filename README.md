# Search Metric Analyzer

A diagnostic tool for Enterprise Search metric movements. Built for Senior Data Scientists debugging why search quality metrics moved — and whether they should care.

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
python3 tools/decompose.py --input data.csv --metric dlctr_value
python3 tools/anomaly.py --input data.csv --metric dlctr_value
python3 tools/diagnose.py --input diagnosis.json
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
│   ├── generate_synthetic_data.py     # Synthetic data generator (13 scenarios)
│   └── validate_scenarios.py          # Scenario validation utilities
├── eval/
│   ├── run_stress_test.py             # Full pipeline eval (5 scenarios, scored)
│   └── scoring_specs/                 # Per-scenario scoring rubrics (YAML)
├── tests/                             # 433 unit tests
├── skills/
│   └── search-metric-analyzer.md      # Claude Code skill file
├── templates/                         # CSV templates for input data
└── docs/plans/                        # Design docs and session prompts
```

## Metrics Tracked

| Metric | What It Measures |
|--------|-----------------|
| **LCTR** |Long Click-Through Rate — (position-weighted or non position-weighted) click quality |
| **Main Search Metric** | Query Success Rate — composite of click quality + AI answer quality |
| **AI Search Trigger** | How often AI answers are shown (detection rate) |
| **AI Search Success** | How often shown AI answers satisfy users (quality rate) |

## Archetypes

The diagnostic engine recognizes these failure patterns:

| Archetype | Co-Movement Signature | What It Means |
|-----------|----------------------|---------------|
| `ranking_regression` | LCTR down, Main Metric down, AI Search Quality stable | Ranking model degraded |
| `ai_adoption` | LCTR down, Main Metric stable/up, AI Search Quality up | AI answers working (positive) |
| `broad_degradation` | All metrics down | System-wide issue |
| `query_understanding` | DLCTR/QSR/AI Search trigger down, AI Search success stable | Query interpretation layer degraded |
| `sain_regression` | AI Search Quality metrics down, LCTR stable | AI answer quality issue |
| `mix_shift` | Movement explained by traffic composition | Not a quality change |
| `false_alarm` | All metrics within noise | No action needed |

## Eval Results

5 synthetic scenarios, all GREEN (avg 91.2/100):

| Case | Scenario | Score | Grade |
|------|----------|-------|-------|
| S4 | Ranking regression | 85 | GREEN |
| S5 | AI adoption trap | 100 | GREEN |
| S7 | Multi-cause overlap | 85 | GREEN |
| S9 | Mix-shift | 96 | GREEN |
| S0 | False alarm (stable) | 90 | GREEN |

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

