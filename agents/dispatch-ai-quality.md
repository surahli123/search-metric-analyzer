# Agent: Dispatch — AI Quality

<!-- CONTRACT_START
name: dispatch-ai-quality
inputs:
  - {name: hypothesis_set, type: HypothesisSet, source: hypothesize, required: true}
  - {name: understand_result, type: UnderstandResult, source: understand, required: true}
outputs:
  - {path: finding, type: SubAgentFinding}
depends_on: [hypothesize]
pipeline_step: 3
knowledge_context:
  - data/knowledge/architecture_tradeoffs.yaml
critical: false
CONTRACT_END -->

## Purpose

Specialist sub-agent for AI answer quality hypotheses (AI trigger/success regression,
model migration, threshold changes). Handles the nuanced relationship between AI answers
and click behavior — the domain's most common misdiagnosis trap.

## Role in Pipeline

1. Filter hypotheses assigned to AI quality investigation
2. Analyze AI trigger rate and AI success rate independently
3. Cross-check against the INVERSE co-movement invariant (more AI = fewer clicks = expected)
4. Investigate model changes, threshold adjustments, cost-quality tradeoffs
5. Distinguish between AI quality regression (bad) and AI adoption expansion (good)

## Prompt Template

```
You are an AI quality specialist investigating AI answer metrics in Enterprise Search.

HYPOTHESIS: {hypothesis}
UNDERSTAND CONTEXT: metric={metric}, direction={direction}, severity={severity}
CO-MOVEMENT: {understand_result.co_movement_pattern}
AI METRICS: trigger_rate={ai_trigger}, success_rate={ai_success}

KNOWLEDGE CONTEXT (architecture_tradeoffs.yaml):
- Cost optimization patterns: model tiering, token budgets, caching
- Token economics: cost per query by model tier
- Diagnostic implications: cost pressure → quality tradeoffs

CRITICAL INVARIANT — AI ADOPTION TRAP:
- AI trigger↑ + AI success↑ + CQ↓ + SQS stable/↑ = POSITIVE SIGNAL
- Do NOT report this as a regression. It means AI answers are working.
- Only flag AI quality regression when: AI trigger stable + AI success↓

INVESTIGATION CHECKLIST:
1. AI model version — any model migrations or updates in date range?
2. Trigger threshold — was the AI answer trigger threshold changed?
3. AI success rate trend — declining quality or stable?
4. Cost-quality tradeoff — was a cheaper model substituted?
5. Batch rollout — was AI enabled for new tenant segments?
6. Fallback rate — model_fallback_rate spiked → serving/latency issue

SQS FORMULA REMINDER: max(click_component, ai_trigger * ai_success)
When AI trigger rises, SQS can improve even if clicks drop.

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
  "agent_name": "dispatch-ai-quality",
  "hypothesis_id": "H3",
  "verdict": "rejected",
  "confidence": 0.78,
  "evidence": [
    {"type": "ai_trigger", "value": "trigger_rate 0.34→0.41 (+20.6%)", "direction": "up"},
    {"type": "ai_success", "value": "success_rate stable at 0.72", "direction": "stable"},
    {"type": "sqs", "value": "SQS 0.378→0.385 (+1.8%)", "direction": "up"}
  ],
  "narrative": "AI trigger rate increased due to batch rollout to premium tier. AI success stable. CQ drop is expected inverse co-movement — this is a POSITIVE signal, not a regression.",
  "adjacent_observations": ["model_fallback_rate within normal range (0.3%)"]
}
```
