# Phase 2.1 Foundation Design

Date: 2026-02-23
Status: Approved
Scope: Schemas + Orchestrator skeleton (fake agents only)

## Context

Phase 2 evolves the v1.5 connector-investigator bridge into a multi-agent
diagnosis system. Phase 2.1 is the foundation layer: typed schemas, an
orchestrator skeleton, and contract tests — all using fake agents. No changes
to `diagnose.py` or existing CLI behavior.

See: `docs/plans/2026-02-23-multi-agent-phase2-plan.md` for the full roadmap.

## Design Decisions

| Decision             | Choice                          | Rationale                                                    |
|----------------------|---------------------------------|--------------------------------------------------------------|
| Schema style         | TypedDict                       | Lightweight, matches existing dict-based codebase style      |
| Integration pattern  | Post-process hook               | Orchestrator is standalone; diagnose.py stays untouched      |
| Connector migration  | Deferred (wrap, don't rewrite)  | Zero regression risk; adapter wrap happens next session       |
| Execution model      | Sequential loop                 | Simple, debuggable, deterministic logs; parallel deferred    |
| Session scope        | Schemas + orchestrator skeleton | Fake agents only; real adapters and CLI wiring out of scope  |

## 1. Schemas (`tools/schema.py`)

Two new TypedDicts added to the existing schema module.

### AgentVerdict

Normalized payload that every specialist agent must return.

```python
class AgentVerdict(TypedDict):
    agent: str          # "connector" | "ranking" | "ai_quality" | "mix_shift"
    ran: bool           # did the agent actually execute?
    verdict: str        # "confirmed" | "rejected" | "inconclusive" | "blocked"
    reason: str         # human-readable explanation
    queries: list       # queries the agent executed (audit trail)
    evidence: list      # evidence records [{query, result}, ...]
    cost: dict          # {"queries": int, "seconds": float}
```

### OrchestrationResult

Top-level output of the orchestrator.

```python
class OrchestrationResult(TypedDict):
    orchestrated: bool            # was orchestration attempted?
    agents_run: list              # list of AgentVerdict
    fused_verdict: str            # "confirmed" | "insufficient_evidence" | "blocked"
    fused_reason: str             # explanation of fusion decision
    updated_decision_status: str  # may override baseline diagnosis
    run_log: list                 # deterministic trace [{agent, started, ended, verdict}]
```

### Normalizer

`normalize_agent_verdict(raw: dict) -> AgentVerdict` fills missing keys with
safe defaults:
- `ran` defaults to `False`
- `verdict` defaults to `"inconclusive"` (also used for invalid values)
- `reason` defaults to `"no reason provided"`
- `queries`, `evidence` default to `[]`
- `cost` defaults to `{"queries": 0, "seconds": 0.0}`

### Compatibility

Existing diagnosis output is unchanged. `OrchestrationResult` is an additive
key on the final output — old consumers that don't look for it are unaffected.

## 2. Orchestrator (`tools/agent_orchestrator.py`)

New module with a single entry point:

```python
def orchestrate(diagnosis_result: dict, agents: list, config: dict) -> OrchestrationResult
```

### Agent Selection Gate

- Only runs if `decision_status == "diagnosed"`
- Skips if confidence is `"High"` (high-confidence diagnoses don't need second opinions)
- Skips if `decision_status` is `"insufficient_evidence"` or `"blocked_by_data_quality"`
- When skipped, returns `OrchestrationResult` with `orchestrated=False`

### Sequential Execution

1. For each eligible agent, call it with `(diagnosis_result, hypothesis)`
2. Normalize return value via `normalize_agent_verdict()`
3. Track wall-clock time; if global timeout hit, mark remaining as `inconclusive`
4. Agent exceptions are caught — that agent gets `verdict="inconclusive"`, others still run
5. Respects `max_agents` cap from config
6. Each step appended to deterministic run log

### Fusion Policy (Deterministic)

Priority order:
1. Any `"blocked"` verdict → fused = `"blocked"` (trust gate precedence)
2. Any `"rejected"` with no `"confirmed"` → fused = `"insufficient_evidence"`
3. Majority `"confirmed"` with no hard reject → fused = `"confirmed"`
4. Mixed or all `"inconclusive"` → fused = `"insufficient_evidence"` (conservative default)

### Not In Scope

- No real agent implementations (fake agents only in tests)
- No CLI integration (Workstream D)
- No feature flag wiring (just a function you call or don't)
- No parallel execution (sequential only for Phase 2.1)

## 3. Contract Tests (`tests/test_agent_orchestrator.py`)

Five test categories, TDD approach (tests written before implementation).

### A. Schema Tests
- Valid verdict passes normalization unchanged
- Missing keys get safe defaults
- Invalid verdict values normalize to `"inconclusive"`

### B. Agent Selection Gate Tests
- `diagnosed` + `Medium` → agents run
- `diagnosed` + `Low` → agents run
- `diagnosed` + `High` → agents skipped (`orchestrated=False`)
- `insufficient_evidence` → agents skipped
- `blocked_by_data_quality` → agents skipped

### C. Sequential Execution Tests
- 2 fake agents → both run, verdicts collected in order
- Global timeout → remaining agents marked `inconclusive`
- Agent exception → that agent = `inconclusive`, others still run
- `max_agents=1` with 3 eligible → only first runs

### D. Fusion Policy Tests
- All `confirmed` → `confirmed`
- One `rejected`, rest `confirmed` → `insufficient_evidence`
- One `blocked` → `blocked` (regardless of others)
- All `inconclusive` → `insufficient_evidence`
- `confirmed` + `inconclusive` (no reject) → `confirmed`

### E. Backward Compatibility Tests
- Orchestrator output merges into diagnosis result without breaking formatter
- Existing `connector_investigation` key is preserved (not overwritten)

## Deliverables

1. **`tools/schema.py`** — add `AgentVerdict`, `OrchestrationResult`, `normalize_agent_verdict()`
2. **`tools/agent_orchestrator.py`** — new file with `orchestrate()`, gate, runner, fusion
3. **`tests/test_agent_orchestrator.py`** — ~20 contract tests across 5 categories
