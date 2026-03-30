# Architecture Boundaries

## Layer Model (do not collapse layers)

```
Layer 1: core/          — Deterministic toolkit (decompose, anomaly, diagnose, corrections)
Layer 2: contracts/     — Stage contracts (TypedDicts) + seam_validator (17 business rules)
Layer 3: trace/         — Investigation tracing (spans, collector)
Layer 4: harness/       — Orchestrator, question parser, mode selector, DAG executor, registry
Layer 5: agents/        — Declarative agent definitions (.md with CONTRACT blocks) + registry.yaml
Web:     web/           — FastAPI backend + React frontend (presentation layer)
```

- Each layer depends only on the one below it (Layer 5 is declarative configuration loaded by Layer 4 — not a code dependency)
- Layer 1 has ZERO awareness of Layers 2-5 or the web layer
- The web layer is a PRESENTATION layer — it calls the orchestrator API, it does NOT influence backend architecture

## Pipeline Stages (5-stage, Wave 5)

```
QUESTION_PARSE → UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE
     │                                          │
     ▼                                          ▼
  Mode Select                           Parallel (Complex)
  Simple/Medium/Complex                 Sequential (Medium)
```

- QUESTION_PARSE: deterministic (no LLM), classifies question type + selects mode
- Simple mode: knowledge lookup only, skips the 4-stage pipeline
- Medium mode: sequential 4-stage pipeline (UNDERSTAND → SYNTHESIZE)
- Complex mode: parallel DISPATCH via DAGExecutor, otherwise same as Medium

## Contract Boundary

- `harness/orchestrator.py` → `OrchestrationResult` is the API contract
- `run()` = legacy 4-stage pipeline; `run_v2()` = Wave 5 pipeline with QUESTION_PARSE + mode selection
- Frontend and backend develop independently against this contract
- If backend changes, update the contract — don't let frontend drive backend decisions

## Key Directories

| Directory | Purpose | Stability |
|-----------|---------|-----------|
| `core/` | Deterministic analysis tools | Stable — rarely changes |
| `contracts/` | Business rules (17 rules, hard/soft/retry gates) | Stable |
| `trace/` | Investigation tracing (spans, collector) | Stable |
| `harness/` | Orchestrator, parser, selector, DAG executor, registry, prompts, manifest.yaml | Active development |
| `agents/` | Declarative agent .md files + registry.yaml (loaded by harness/) | Active development |
| `domains/search_metrics/knowledge/` | Domain knowledge (metric defs, patterns) | Source of truth — read before modifying |
| `eval/` | Evaluation scenarios + graders | Active development |

## Before Modifying Architecture

Read `docs/plans/2026-02-21-search-metric-analyzer-design.md` for the full v2 design and layer rationale.
