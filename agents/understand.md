# Agent: Understand

<!-- CONTRACT_START
name: understand
inputs:
  - {name: question_brief, type: QuestionBrief, source: question_parser, required: true}
  - {name: rows, type: "List[Dict]", source: user_data, required: true}
outputs:
  - {path: understand_result, type: UnderstandResult}
depends_on: []
pipeline_step: 1
knowledge_context:
  - data/knowledge/metric_definitions.yaml
  - data/knowledge/historical_patterns.yaml
critical: true
CONTRACT_END -->

## Purpose

Answers: "What happened? How big is it? Is the data trustworthy?"
This is the ONLY mostly-deterministic stage — it runs Python tools (decompose, anomaly)
on raw data before any LLM reasoning begins. Garbage in = garbage out, so this stage
has a HARD gate.

## Role in Pipeline

1. Validate data quality (completeness, freshness, sufficient history)
2. Run `core/decompose.py` to break metric movement into dimensional contributions
3. Run `core/anomaly.py` for step-change detection and co-movement pattern matching
4. Detect mix-shift (segment composition changes vs. behavioral changes)
5. Set `metric_direction` explicitly (IC9 Invisible Decision #1)
6. Classify severity (P0/P1/P2/normal) using alert thresholds from metric_definitions.yaml

## Prompt Template

```
You are analyzing metric data for an Enterprise Search system.

QUESTION: {question_brief.raw_question}
METRIC: {question_brief.metric_hints}
TIME RANGE: {question_brief.time_range_hints}

DATA SUMMARY (from decompose.py):
{decomposition_output}

ANOMALY DETECTION (from anomaly.py):
{anomaly_output}

KNOWLEDGE CONTEXT:
- Metric baselines by segment (metric_definitions.yaml)
- Seasonal patterns and known incidents (historical_patterns.yaml)

TASK:
1. State the metric direction (up/down/stable) and magnitude.
2. Classify severity using thresholds: P0 (>5% CQ / >4% SQS), P1 (2-5% / 1.5-4%), P2 (<2% / <1.5%).
3. Report data quality status (pass/warn/fail).
4. Identify co-movement pattern — CRITICAL: CQ down + AI up + SQS stable = POSITIVE, not regression.
5. Flag mix-shift if segment composition changed >25%.

OUTPUT FORMAT: JSON matching UnderstandResult contract.
```

## Quality Gates

Seam tier: **HARD** — failure halts the investigation.

| Rule | What it checks |
|------|----------------|
| `rule_data_quality_not_failed` | Data quality != "fail" |
| `rule_metric_direction_set` | metric_direction is one of {up, down, stable} |

## Expected Output

```json
{
  "question": "Click Quality dropped 3.1% WoW",
  "metric": "click_quality",
  "direction": "down",
  "severity": "P1",
  "data_quality_status": "pass",
  "metric_direction": "down",
  "step_change": {"detected": true, "magnitude": 0.031, "z_score": 2.8},
  "co_movement_pattern": {"pattern_name": "ranking_regression", "match_score": 0.82},
  "mix_shift_result": {"detected": false, "contribution_pct": 0.08}
}
```
