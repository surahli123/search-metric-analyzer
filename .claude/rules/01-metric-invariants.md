# Metric Invariants — Always True

## Core Formulas (never modify without approval)

- **Click Quality** = sum(long_clicks * log2_discount(rank)) / impressions
- **Search Quality Success** = max(click_component, ai_trigger * ai_success)
- **AI Trigger Rate** = queries_with_ai_answer_triggered / total_queries
- **AI Success Rate** = ai_answers_satisfying / ai_answers_triggered
- **Zero Result Rate** = queries_with_zero_results / total_queries

## Inverse Co-Movement (critical — do NOT misdiagnose)

AI answers and clicks have INVERSE co-movement by design:
- More AI answers → fewer clicks → Click Quality drops → **this is EXPECTED, not a regression**
- If Click Quality↓ + AI Trigger↑ + AI Success↑ + SQS stable/up → **positive signal**
- NEVER flag this pattern as a bug or regression

## Decomposition Dimensions (check enterprise-specific first)

1. tenant_tier (standard/premium/enterprise)
2. ai_enablement (ai_on/ai_off)
3. industry_vertical
4. connector_type (confluence, slack, gdrive, jira, sharepoint)
5. query_type (navigational, informational, action)

## Hypothesis Priority (fixed order — instrumentation first, behavior last)

1. Instrumentation/logging anomaly — cheap to verify, expensive to miss
2. Connector/data pipeline change — most common root cause in Enterprise Search
3. Query understanding regression — L0 layer affects all downstream
4. Algorithm/model change — ranking model, embedding model, retraining
5. Experiment ramp/de-ramp — A/B test exposure changes
6. AI feature effect — threshold change, model migration
7. Seasonal/external — calendar effects, industry cycles
8. User behavior shift — null hypothesis, check LAST

## Alert Thresholds

| Metric | P0 (critical) | P1 (significant) | P2 (minor) |
|---|---|---|---|
| Click Quality | >5% movement | 2–5% | 0.5–2% |
| SQS | >4% | 1.5–4% | 0.5–1.5% |

Use these to classify severity BEFORE deep-diving. P2 movements are usually normal fluctuation — document and monitor, don't investigate.

## Baselines by Segment

**Click Quality baselines:**

| Segment | Click Quality | Notes |
|---|---|---|
| ai_on | 0.220 | Lower expected — users get AI answers without clicking (GOOD) |
| ai_off | 0.310 | Traditional search baseline |
| enterprise_tier | 0.295 | More connectors, richer index |
| premium_tier | 0.280 | Mid-tier |
| standard_tier | 0.245 | Fewer connectors, sparser index |

**SQS baseline (global only — no per-segment breakdown available yet):**

| Metric | Mean | Weekly Std Dev | Notes |
|---|---|---|---|
| SQS | 0.378 | 0.012 | Composite metric — values shift with AI rollouts and model changes |

⚠ SQS baselines change dynamically with AI feature rollouts. Always validate against recent data before using as a reference point. Per-segment SQS breakdowns are a gap — when added to the pipeline, update this table.

Always compare to segment-specific baseline, not global average. A 0.220 Click Quality for ai_on is healthy; the same value for ai_off is a P0.

## Known Blind Spots (metrics CAN'T tell you this)

- **Demand suppression:** queries never issued because users learned the system won't help (invisible to all metrics)
- **Zero-click success:** snippet/preview answered the question — looks like failure in Click Quality but is actually success
- **Multi-session attribution:** success happens in a later session (attribution gap across sessions)
- **Over-trust these metrics at your peril** — always consider what they can't measure before concluding

## Before Modifying Metric Logic

Read `data/knowledge/metric_definitions.yaml` for full formulas, baselines, alert thresholds, and co-movement table before changing any metric calculation.
