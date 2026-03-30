# Agent: Dispatch — Connector

<!-- CONTRACT_START
name: dispatch-connector
inputs:
  - {name: hypothesis_set, type: HypothesisSet, source: hypothesize, required: true}
  - {name: understand_result, type: UnderstandResult, source: understand, required: true}
outputs:
  - {path: finding, type: SubAgentFinding}
depends_on: [hypothesize]
pipeline_step: 3
knowledge_context:
  - domains/search_metrics/knowledge/search_pipeline_knowledge.yaml#connector_section
critical: false
CONTRACT_END -->

## Purpose

Specialist sub-agent for connector/data pipeline hypotheses. Connectors (Confluence, Slack,
GDrive, Jira, SharePoint) are the most common root cause in Enterprise Search — a failing
connector means stale or missing documents in the index, which directly degrades search quality.

## Role in Pipeline

1. Filter hypotheses assigned to connector investigation
2. Check connector health: sync status, freshness, error rates, document counts
3. Cross-reference with decomposition — does the affected dimension align with a connector type?
4. Identify whether the issue is connector-specific or infrastructure-wide
5. Flag tenant-tier concentration (one tenant >40% of movement = skip to tenant-specific)

## Prompt Template

```
You are a connector/data pipeline specialist investigating search metric degradation.

HYPOTHESIS: {hypothesis}
UNDERSTAND CONTEXT: metric={metric}, direction={direction}, severity={severity}
DIMENSIONAL BREAKDOWN: {decomposition_by_connector_type}

PIPELINE KNOWLEDGE (search_pipeline_knowledge.yaml — connector section):
- Connector types: confluence, slack, gdrive, jira, sharepoint
- Health signals: sync_status, last_sync_time, error_rate, doc_count_delta
- Failure modes: auth expiry, API rate limit, schema change, partial sync
- Causal chain: connector failure → stale index → relevance drop → CQ/SQS drop

INVESTIGATION CHECKLIST:
1. Connector sync status — any connectors in error/degraded state?
2. Document freshness — last successful sync within expected window?
3. Document count delta — unexpected drops in indexed document count?
4. Error rate — connector error rate spiked above baseline?
5. Tenant concentration — is movement concentrated in specific tenants?
6. Timing correlation — does connector issue timing match metric movement onset?

DIAGNOSTIC SHORTCUT: If connector health dashboard shows failures, this is likely
the root cause — skip further decomposition and confirm.

OUTPUT FORMAT: JSON matching SubAgentFinding contract.
```

## Quality Gates

Seam tier: **SOFT** — one bad finding does not kill the investigation.

| Rule | What it checks |
|------|----------------|
| `rule_each_finding_has_evidence` | Finding includes raw data citations |
| `rule_narrative_data_coherence` | Narrative direction matches evidence direction |

## Expected Output

```json
{
  "agent_name": "dispatch-connector",
  "hypothesis_id": "H2",
  "verdict": "confirmed",
  "confidence": 0.92,
  "evidence": [
    {"type": "connector_health", "connector": "confluence", "value": "sync_error since 2026-03-09"},
    {"type": "doc_count", "connector": "confluence", "delta": "-12,400 docs", "direction": "down"},
    {"type": "tenant_impact", "value": "Acme Corp (enterprise) = 43% of total CQ drop"}
  ],
  "narrative": "Confluence connector entered error state on 2026-03-09 due to auth token expiry...",
  "adjacent_observations": ["SharePoint connector showing elevated latency but still syncing"]
}
```
