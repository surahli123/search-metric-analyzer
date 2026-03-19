# Agent: Hypothesize

<!-- CONTRACT_START
name: hypothesize
inputs:
  - {name: understand_result, type: UnderstandResult, source: understand, required: true}
outputs:
  - {path: hypothesis_set, type: HypothesisSet}
depends_on: [understand]
pipeline_step: 2
knowledge_context:
  - data/knowledge/metric_definitions.yaml#co_movement_diagnostic_table
  - data/knowledge/corrections.yaml
critical: true
CONTRACT_END -->

## Purpose

Answers: "What could explain this movement? What should we investigate?"
LLM-driven but heavily constrained by UNDERSTAND output. Generates 3+ hypotheses
with pre-registered confirmation/rejection criteria to prevent post-hoc rationalization.

## Role in Pipeline

1. Read co-movement pattern from UNDERSTAND to narrow hypothesis space
2. Generate hypotheses following the fixed priority order:
   instrumentation > connector > query understanding > algorithm > experiment > AI feature > seasonal > behavior
3. Include at least one contrarian hypothesis that challenges the obvious explanation
4. Set expected_magnitude on each hypothesis (prevents false alarms)
5. Record excluded hypotheses with reasons (IC9 Invisible Decision #2)
6. Check corrections.yaml for past diagnostic mistakes on similar patterns

## Prompt Template

```
You are generating diagnostic hypotheses for an Enterprise Search metric movement.

UNDERSTAND OUTPUT:
{understand_result}

CO-MOVEMENT PATTERN: {understand_result.co_movement_pattern.pattern_name}
SEVERITY: {understand_result.severity}
MIX-SHIFT: {understand_result.mix_shift_result}

KNOWLEDGE CONTEXT:
- Co-movement diagnostic table (metric_definitions.yaml lines ~168-278)
- Past corrections for similar patterns (corrections.yaml)

HYPOTHESIS PRIORITY ORDER (FIXED — instrumentation first, behavior last):
1. Instrumentation/logging anomaly
2. Connector/data pipeline change
3. Query understanding regression
4. Algorithm/model change
5. Experiment ramp/de-ramp
6. AI feature effect
7. Seasonal/external
8. User behavior shift

CRITICAL RULE — AI ADOPTION TRAP:
If co-movement = "ai_adoption_expected" (CQ↓ + AI↑ + SQS stable/↑),
do NOT generate a "click_quality_degradation" hypothesis unless marked contrarian.

TASK:
1. Generate >= 3 hypotheses with confirms_if, rejects_if, expected_magnitude.
2. Mark at least one as is_contrarian: true.
3. If mix-shift >25%, include a mix_shift hypothesis.
4. List excluded hypotheses with reasons.

OUTPUT FORMAT: JSON matching HypothesisSet contract.
```

## Quality Gates

Seam tier: **SOFT** — violations emit warnings but investigation continues.

| Rule | What it checks |
|------|----------------|
| `rule_min_three_hypotheses` | >= 3 hypotheses |
| `rule_all_have_confirms_if` | Every hypothesis has confirmation criteria |
| `rule_has_contrarian_hypothesis` | At least one contrarian |
| `rule_expected_magnitude_present` | Every hypothesis has expected_magnitude |
| `rule_hypotheses_consistent_with_co_movement` | No CQ degradation hyp when AI adoption expected |
| `rule_mix_shift_considered_when_detected` | Mix-shift hyp when mix-shift >25% |

## Expected Output

```json
{
  "hypotheses": [
    {"hypothesis_id": "H1", "archetype": "ranking_regression", "priority": 4,
     "confirms_if": ["model version changed", "NDCG delta >2%"],
     "rejects_if": ["no model changes"], "expected_magnitude": "CQ drop 2-5%",
     "source": "data_driven", "is_contrarian": false}
  ],
  "exclusions": [{"archetype": "seasonal", "reason": "no pattern match"}],
  "investigation_context": "CQ dropped 3.1% WoW, P1, ranking_regression pattern"
}
```
