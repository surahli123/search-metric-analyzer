# Diagnostic Patterns — Quick Reference

## Co-Movement Pattern Table

Use this to narrow hypotheses BEFORE running decomposition.

| Click Quality | SQS | AI Trigger | AI Success | Likely Cause | Action |
|---|---|---|---|---|---|
| ↓ | ↓ | stable | stable | Ranking regression | Check ranking model, experiment ramps |
| ↓ | stable/↑ | ↑ | ↑ | AI answers working | **POSITIVE — do NOT treat as regression** |
| ↓ | ↓ | ↓ | ↓ | Broad degradation | Check model/experiment/infra |
| ↓ | ↓ | stable | ↓ | AI quality regression | Check AI answer model |
| ↓ | stable | stable | stable | Click behavior change | Check UX changes, display changes, mix-shift |
| stable | ↓ | ↓ | stable | AI trigger regression | Check trigger threshold/model |
| stable | ↓ | stable | ↓ | AI success regression | Check answer quality model |
| ↓ | ↓ | ↓ | stable/↓ | Query understanding regression | Check L0 layer (intent, spell, reformulation) |
| stable | stable | stable | stable | No significant movement | Normal fluctuation — no action |

## Diagnostic Shortcuts (skip decomposition when these are true)

1. **Connector health dashboard shows failures** → jump to connector root cause
2. **model_fallback_rate spiked** → jump to serving/latency investigation
3. **One tenant >40% of movement** → jump to tenant-specific analysis
4. **Overnight step-change >2%** → check instrumentation/logging first

## Known Seasonal Patterns

- **Enterprise onboarding wave** — new tenants drag metrics down via mix-shift (recovers in 30-90 days)
- **AI batch rollout** — Click Quality drops but SQS improves (positive signal)
- **End of quarter surge** — exploratory queries lower click-through
- **Weekend/weekday cycle** — always compare same day-of-week, not consecutive days

## Decision Points (what to do next)

- **Drop confirmed, isolated to one segment** → segment-specific deep dive, check connector health for that segment
- **Co-movement matches a known pattern** → follow the pattern's priority_hypotheses, skip unrelated dimensions
- **Co-movement doesn't match ANY pattern** → escalate; read full co-movement table + check historical_patterns for similar novel cases
- **Magnitude is small (<P2 threshold)** → likely normal fluctuation, document and monitor, no action needed
- **Root cause unclear after initial triage** → check instrumentation/logging first (cheapest to verify), then escalate to eng lead with evidence summary

## Before Diagnosing an Incident

Read `domains/search_metrics/knowledge/historical_patterns.yaml` for full known incidents, data signatures, and seasonal baselines.
