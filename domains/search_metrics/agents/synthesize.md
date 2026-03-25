# Agent: Synthesize

<!-- CONTRACT_START
name: synthesize
inputs:
  - {name: finding_set, type: FindingSet, source: dispatch, required: true}
  - {name: understand_result, type: UnderstandResult, source: understand, required: true}
  - {name: hypothesis_set, type: HypothesisSet, source: hypothesize, required: true}
outputs:
  - {path: report, type: SynthesisReport}
depends_on: [dispatch-ranking, dispatch-connector, dispatch-ai-quality]
pipeline_step: 4
knowledge_context:
  - all prior stage outputs
  - narrative rules (effect-size proportionality, upgrade conditions)
critical: true
CONTRACT_END -->

## Purpose

Answers: "What's the verdict? What should we do about it?"
HIGHEST-STAKES stage — this is what eng leads read and act on. The IC9 audit found
~50% compliance on mandatory sections in v1. This contract makes that impossible.

## Role in Pipeline

1. Aggregate findings from all dispatch sub-agents
2. Resolve conflicting findings (confirmed vs rejected on same root cause)
3. Generate the 7 mandatory report sections (IC9 Phase 1 enforcement)
4. Ensure language proportionality (P0 = no minimizing words)
5. State upgrade_condition, produce actionable recommendations with owners
6. IC9 Invisible Decision #4: narrative_selection — which findings get prominence

## Prompt Template

```
You are synthesizing an investigation report for Enterprise Search metric diagnosis.

INVESTIGATION SUMMARY:
  Question: {understand_result.question}
  Metric: {understand_result.metric}
  Direction: {understand_result.direction}
  Severity: {understand_result.severity}
  Co-movement: {understand_result.co_movement_pattern.pattern_name}

FINDINGS:
{finding_set.findings}

CONTEXT TRACE: {finding_set.context_construction_trace}

MANDATORY SECTIONS (all 7 required, non-empty):
1. tldr — 1-3 sentences, conclusion-first
2. confidence_grade — High/Medium/Low
3. severity — P0/P1/P2/normal
4. root_cause — primary explanation with evidence
5. dimensional_breakdown — which segments drove the movement
6. hypothesis_and_evidence — what was tested and found
7. validation_summary — cross-checks and coherence

LANGUAGE RULES:
- P0: no minimizing words (minor/slight/small/marginal/negligible/trivial)
- No hedge words in conclusions (appears/might suggest/potentially)
- Cite specific numbers, not vague qualifiers

REQUIRED: upgrade_condition ("Would upgrade to X if Y"), recommended_actions (with owner)

OUTPUT FORMAT: JSON matching SynthesisReport contract.
```

## Quality Gates

Seam tier: **RETRY(1) then SOFT** — retry once on failure, then warn and continue.

| Rule | What it checks |
|------|----------------|
| `rule_all_mandatory_sections_present` | All 7 sections non-empty |
| `rule_effect_size_proportionality` | P0 reports use proportional language |
| `rule_upgrade_condition_stated` | upgrade_condition field populated |
| `rule_mode_compliance_simple` | Simple mode has no DISPATCH findings |
| `rule_report_quality_score` | Report scores >= 6/12 on quality rubric |

## Expected Output

```json
{
  "tldr": "CQ dropped 3.1% WoW — ranking model v2.4 regression. P1. Recommend rollback.",
  "confidence_grade": "High",
  "severity": "P1",
  "root_cause": "Ranking model v2.4 deployed 2026-03-10, 3.2% NDCG@10 regression...",
  "dimensional_breakdown": "Enterprise 68%, premium 22%, standard 10%...",
  "hypothesis_and_evidence": "H1 ranking: CONFIRMED. H2 connector: REJECTED...",
  "validation_summary": "Timing matches onset. No conflicting evidence.",
  "recommended_actions": [
    {"action": "Rollback to v2.3", "owner": "Search Ranking", "priority": "immediate",
     "rationale": "Direct cause of NDCG regression"}
  ],
  "upgrade_condition": "Already High — model deploy + NDCG evidence sufficient",
  "investigation_id": "inv-2026-03-12-001"
}
```
