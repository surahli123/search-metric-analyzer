# Lead Agent: Simple Mode

## Purpose

Handle direct knowledge lookups and definitional questions that don't require
a full investigation pipeline. These are questions where the answer already
exists in the knowledge base — no hypothesis generation or data analysis needed.

## When This Mode Activates

- Question type: `adhoc`
- Examples:
  - "What's the Click Quality formula?"
  - "What tables have search_quality_success data?"
  - "Explain the AI adoption trap"
  - "What are the P0 thresholds for each metric?"

## Execution Flow

```
Question → Knowledge Lookup → Direct Answer
```

No pipeline stages run. The orchestrator routes directly to knowledge retrieval
and returns the answer.

## Token Budget

- **Target:** ~5,000 tokens total
- **Knowledge context:** Up to 2,000 tokens from relevant YAML files
- **Response:** Up to 3,000 tokens

## Guardrails

- **Must NOT** generate hypotheses or investigate findings
- **Must NOT** produce DISPATCH results (rule_mode_compliance_simple enforces this)
- **Must** reference the knowledge source (which YAML, which section)
- **Must** acknowledge if the question falls outside available knowledge

## Knowledge Sources

Routes to the most relevant knowledge file based on keywords:
- Metric definitions → `data/knowledge/metric_definitions.yaml`
- Pipeline components → `data/knowledge/search_pipeline_knowledge.yaml`
- Historical patterns → `data/knowledge/historical_patterns.yaml`
- Cost tradeoffs → `data/knowledge/architecture_tradeoffs.yaml`
- Past corrections → `data/knowledge/corrections.yaml`

## Quality Expectations

- Answers should be precise and directly sourced from knowledge files
- If a question can't be answered from knowledge, say so clearly
- Don't speculate or generate hypotheses for simple lookups
