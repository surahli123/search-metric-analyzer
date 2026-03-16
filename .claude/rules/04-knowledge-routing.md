# Knowledge Routing Table

This is a routing table — it maps diagnostic questions to the right knowledge file.
Read rules 01–03 first. Only load files via this table when rules don't fully answer the question.

## Single-Intent Routes

### Metric Definitions & Baselines

| Intent | File | Section Key | ~Line |
|---|---|---|---|
| Metric formula, definition, components | metric_definitions.yaml | `metrics:` | ~12 |
| Baselines by segment (detail beyond rules) | metric_definitions.yaml | `baseline_by_segment:` | ~44 |
| Co-movement patterns (full 9-row table) | metric_definitions.yaml | `co_movement_diagnostic_table:` | ~168 |
| Hypothesis priority (full with rationale) | metric_definitions.yaml | `hypothesis_priority:` | ~279 |

### Search Pipeline & Architecture

| Intent | File | Section Key | ~Line |
|---|---|---|---|
| Pipeline component (QU, ranking, vector) | search_pipeline_knowledge.yaml | `pipeline_components:` | ~8 |
| Failure mode per component + metric signature | search_pipeline_knowledge.yaml | `failure_modes:` (within each component) | — |
| Causal chain (cross-component cascade) | search_pipeline_knowledge.yaml | `causal_chains:` | ~170 |
| NDCG benchmarks (BM25 through hybrid) | search_pipeline_knowledge.yaml | `benchmarks:` | ~196 |

### Cost & Architecture Tradeoffs

| Intent | File | Section Key | ~Line |
|---|---|---|---|
| Cost optimization pattern or model tiering | architecture_tradeoffs.yaml | `cost_optimization_patterns:` | ~8 |
| Token economics or cost comparison | architecture_tradeoffs.yaml | `token_economics:` | ~173 |
| Cost-quality tradeoff diagnostic | architecture_tradeoffs.yaml | `diagnostic_implications:` | ~204 |

### Evaluation Methods

| Intent | File | Section Key | ~Line |
|---|---|---|---|
| LLM-as-judge methodology | evaluation_methods.yaml | `evaluation_approaches:` | ~9 |
| Measurement pitfall or judge bias | evaluation_methods.yaml | `measurement_pitfalls:` | ~97 |
| Is this metric move real or artifact? | evaluation_methods.yaml | `diagnostic_implications:` | ~164 |

### Historical Context

| Intent | File | Section Key | ~Line |
|---|---|---|---|
| Seasonal pattern or recurring event | historical_patterns.yaml | `seasonal_patterns:` | ~5 |
| Past incident or data signature | historical_patterns.yaml | `known_incidents:` | ~68 |
| Diagnostic shortcut (skip decomposition) | historical_patterns.yaml | `diagnostic_shortcuts:` | ~103 |

### Corrections & Design

| Intent | File | Section Key | ~Line |
|---|---|---|---|
| Past diagnostic mistake or correction | corrections.yaml | `corrections:` | full file |
| System architecture or layer boundaries | docs/plans/2026-02-21-search-metric-analyzer-design.md | `## 4. Architecture` | ~67 |
| 4-stage diagnostic workflow design | docs/plans/2026-02-21-search-metric-analyzer-design.md | `## 5. Diagnostic Workflow` | ~99 |
| Evaluation scenarios (13 test cases) | docs/plans/2026-02-21-search-metric-analyzer-design.md | `## 8. Scenarios (13 Total)` | ~243 |
| Architectural gaps or enforcement issues | docs/research/IC9_review_FULL_PIPELINE_assessment.md | `## What the System Gets Wrong` | ~40 |
| System-level failure modes (SYS-1 to SYS-5) | docs/research/IC9_review_FULL_PIPELINE_assessment.md | `## System-Level Failure Modes` | ~197 |
| Eval rubric for retrospective scoring | eval/eval_rubric_approach_a.md | — | full file |
| Eval rubric for prospective/live scoring | eval/eval_rubric_approach_b.md | — | full file |
| Context layer industry analysis | docs/research/session-record-context-layer*.md | — | full file |

## Composite Intents (multi-file routing — stop when resolved)

| Question Pattern | Load First | Then If Needed |
|---|---|---|
| "Why did [metric] drop/change?" | rules 01+03 (already loaded) | metric_definitions `co_movement_diagnostic_table:` → historical_patterns |
| "Is this a real regression or noise?" | rules 01+03 (already loaded) | evaluation_methods `measurement_pitfalls:` → historical_patterns |
| "What could cause [component] to fail?" | search_pipeline_knowledge `failure_modes:` | architecture_tradeoffs (if cost-related) |
| "How do I evaluate agent quality?" | eval/eval_rubric_approach_a.md | eval/eval_rubric_approach_b.md (if live investigation) |
| "What's my next step?" | rules 03 decision points (already loaded) | docs/plans/2026-02-21-search-metric-analyzer-design.md `## 5. Diagnostic Workflow` |

## Stop Rule

If rules 01–03 fully and specifically answer the question with no ambiguity → don't load any file.
But if the question involves a specific segment, time period, or magnitude threshold → load the relevant YAML for detail.

## Fallback Behavior

- If no intent matches → load the most relevant YAML based on question topic
- If topic is unclear → ask the user to clarify rather than loading everything
- Never load all knowledge files at once — that defeats the purpose of this routing table

## Provenance & Corrections

- If a knowledge entry seems stale or contradicts observed data → flag it, don't silently use it
- Always check `corrections.yaml` for known overrides before relying on any entry
- When a knowledge entry contributes to a wrong diagnosis → note it for the user to update

## Scalability Ceiling

This routing table is valid while: <15 knowledge files, <60 intents, and correction volume <30/month.
At 100+ users, expect to hit these limits within 2–3 months — plan for semantic retrieval migration.
Track routing misses and unmatched intents to inform the migration timeline.
