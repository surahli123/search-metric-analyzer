# Architecture Boundaries

## Layer Model (do not collapse layers)

```
Layer 1: core/          — Deterministic toolkit (decompose, anomaly, diagnose, corrections)
Layer 2: harness/       — Agent orchestrator (sequential runner, fusion policy)
Layer 3: (future)       — Specialist agents
Web:     (planned)      — FastAPI + React presentation layer
```

- Each layer depends only on the one below it
- Layer 1 has ZERO awareness of Layer 2 or the web layer
- The web layer is a PRESENTATION layer — it calls the orchestrator API, it does NOT influence backend architecture

## Contract Boundary

- `harness/orchestrator.py` → `OrchestrationResult` is the API contract
- Frontend and backend develop independently against this contract
- If backend changes, update the contract — don't let frontend drive backend decisions

## Key Directories

| Directory | Purpose | Stability |
|-----------|---------|-----------|
| `core/` | Deterministic analysis tools | Stable — rarely changes |
| `contracts/` | Business rules (11 rules, hard/soft/retry gates) | Stable |
| `trace/` | Investigation tracing (spans, collector) | Stable |
| `harness/` | Orchestrator + agent adapters | Active development |
| `data/knowledge/` | Domain knowledge (metric defs, patterns) | Source of truth — read before modifying |
| `eval/` | Evaluation scenarios + graders | Active development |

## Before Modifying Architecture

Read `docs/plans/2026-02-21-search-metric-analyzer-design.md` for the full v2 design and layer rationale.
