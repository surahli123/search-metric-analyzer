# Agent: Investigation Sub-Agent (Generic)

<!-- CONTRACT_START
name: investigation-sub-agent
inputs:
  - {name: hypothesis, type: HypothesisBrief, source: hypothesize, required: true}
  - {name: understand_result, type: UnderstandResult, source: understand, required: true}
  - {name: investigation_context, type: str, source: hypothesize, required: true}
outputs:
  - {path: finding, type: SubAgentFinding}
depends_on: [hypothesize]
pipeline_step: 3
knowledge_context: []  # loaded per-hypothesis from knowledge routing table
critical: false
CONTRACT_END -->

## Purpose

Generic investigation sub-agent dispatched for hypotheses that don't match a specialist
(ranking, connector, AI quality). Handles: instrumentation anomalies, query understanding
regressions, experiment ramp effects, seasonal patterns, and behavior shifts.

This agent dynamically loads knowledge context based on the hypothesis archetype,
following the routing table in `.claude/rules/04-knowledge-routing.md`.

## Role in Pipeline

1. Receive a single hypothesis from the DISPATCH orchestrator
2. Load focused knowledge context (~1500 tokens) based on hypothesis archetype
3. Investigate the hypothesis using pre-registered confirms_if / rejects_if criteria
4. Produce evidence-backed finding with verdict and confidence
5. Record adjacent observations for unexpected discoveries

## Knowledge Routing (dynamic, per-hypothesis)

| Archetype | Knowledge Loaded |
|-----------|-----------------|
| `instrumentation_anomaly` | historical_patterns.yaml#diagnostic_shortcuts |
| `query_understanding_regression` | search_pipeline_knowledge.yaml#pipeline_components (QU) |
| `experiment_ramp` | metric_definitions.yaml#baselines + evaluation_methods.yaml |
| `seasonal_pattern` | historical_patterns.yaml#seasonal_patterns |
| `user_behavior_shift` | metric_definitions.yaml#co_movement_diagnostic_table |
| `mix_shift` | metric_definitions.yaml#baseline_by_segment |

## Prompt Template

```
You are investigating a specific hypothesis about an Enterprise Search metric movement.

HYPOTHESIS:
  ID: {hypothesis.hypothesis_id}
  Archetype: {hypothesis.archetype}
  Priority: {hypothesis.priority}
  Expected magnitude: {hypothesis.expected_magnitude}

PRE-REGISTERED CRITERIA:
  Confirms if: {hypothesis.confirms_if}
  Rejects if: {hypothesis.rejects_if}

INVESTIGATION CONTEXT: {investigation_context}
UNDERSTAND SUMMARY: {understand_result (severity, direction, co-movement)}

FOCUSED KNOWLEDGE: {dynamically_loaded_context}

TASK:
1. Evaluate the hypothesis against the pre-registered criteria ONLY.
2. Do not shift goalposts — confirms_if was set before investigation.
3. Cite specific data for every claim.
4. If evidence is insufficient, verdict = "inconclusive" (not "confirmed").
5. Record anything unexpected in adjacent_observations.

OUTPUT FORMAT: JSON matching SubAgentFinding contract.
```

## Quality Gates

Seam tier: **SOFT** — sub-agent failures do not block the investigation.

| Rule | What it checks |
|------|----------------|
| `rule_each_finding_has_evidence` | Finding includes raw data citations |
| `rule_narrative_data_coherence` | Narrative direction matches evidence direction |

## Expected Output

```json
{
  "agent_name": "investigation-sub-agent",
  "hypothesis_id": "H4",
  "verdict": "inconclusive",
  "confidence": 0.45,
  "evidence": [
    {"type": "logging", "value": "event volume stable, no instrumentation gaps detected"}
  ],
  "narrative": "No evidence of instrumentation anomaly found. Event volume and schema are consistent...",
  "adjacent_observations": ["Slight increase in null-field rate for mobile events (2.1%→3.4%)"]
}
```
