# Agent: Dispatch — Ranking

<!-- CONTRACT_START
name: dispatch-ranking
inputs:
  - {name: hypothesis_set, type: HypothesisSet, source: hypothesize, required: true}
  - {name: understand_result, type: UnderstandResult, source: understand, required: true}
outputs:
  - {path: finding, type: SubAgentFinding}
depends_on: [hypothesize]
pipeline_step: 3
knowledge_context:
  - data/knowledge/search_pipeline_knowledge.yaml
critical: false
CONTRACT_END -->

## Purpose

Specialist sub-agent for ranking-related hypotheses (algorithm changes, model regressions,
reranking failures). Investigates hypotheses with archetypes: `ranking_regression`,
`algorithm_change`, `reranking_failure`, `embedding_model_regression`.

## Role in Pipeline

1. Filter hypotheses assigned to ranking investigation
2. Check ranking model deployment logs, NDCG benchmarks, A/B experiment status
3. Compare against pipeline component failure modes from search_pipeline_knowledge.yaml
4. Produce evidence-backed findings (raw data citations, not just narrative)
5. Record adjacent observations (unexpected findings outside the hypothesis scope)

## Prompt Template

```
You are a ranking specialist investigating search quality degradation.

HYPOTHESIS: {hypothesis}
UNDERSTAND CONTEXT: metric={metric}, direction={direction}, severity={severity}

PIPELINE KNOWLEDGE (search_pipeline_knowledge.yaml):
- L1 Retrieval: BM25 + vector recall, expected NDCG@10 ~0.35-0.45
- L2 Reranking: cross-encoder, expected lift +15-25% over L1
- Failure modes: stale embeddings, reranker timeout/fallback, feature drift
- Causal chains: embedding regression → recall drop → CQ drop

INVESTIGATION CHECKLIST:
1. Model version — any deployments in the affected time range?
2. NDCG benchmarks — L1 recall and L2 rerank lift within expected range?
3. Experiment ramps — any A/B tests changed exposure in this period?
4. Feature drift — input feature distributions shifted?
5. Latency — reranker p99 within budget? Fallback to BM25 triggered?

EVIDENCE REQUIREMENTS:
- Every claim must cite specific data (metric values, dates, percentages)
- State verdict: confirmed / rejected / inconclusive
- Set confidence 0.0-1.0

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
  "agent_name": "dispatch-ranking",
  "hypothesis_id": "H1",
  "verdict": "confirmed",
  "confidence": 0.85,
  "evidence": [
    {"type": "model_deploy", "value": "v2.3→v2.4 deployed 2026-03-10", "delta": "-3.2% NDCG@10"},
    {"type": "latency", "value": "reranker p99 stable at 45ms", "direction": "stable"}
  ],
  "narrative": "Ranking model v2.4 deployed on 2026-03-10 caused a 3.2% NDCG@10 regression...",
  "adjacent_observations": ["Reranker fallback rate elevated for enterprise tier only"]
}
```
