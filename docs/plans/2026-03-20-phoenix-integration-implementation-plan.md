# Phoenix Integration — Implementation Plan

**Branch:** feature/phoenix-integration
**Design doc:** docs/plans/2026-03-20-arize-phoenix-integration-design.md
**Eng review round 1:** 7 decisions locked (see below)
**Eng review round 2:** 5 additional fixes (see below)
**Approach:** TDD — tests first, implementation second, per step

## Locked Decisions (from eng review)

| # | Decision | Choice |
|---|---|---|
| 1 | Layer boundary | Dual-emit in `harness/phoenix_tracer.py`, trace/ untouched |
| 2 | Thread context | Explicit OTel context propagation in DAGExecutor workers |
| 3 | Trace ID | Correlate directly — OTel trace_id set from InvestigationTrace.trace_id |
| 4 | Exporter mode | Batch + explicit flush at pipeline end |
| 5 | Import guard | Single guard + PHOENIX_AVAILABLE flag in phoenix_tracer.py |
| 6 | Dual emit | Single dual_emit() replaces existing emit calls |
| 7 | Test strategy | Full suite (13 scenarios) with InMemorySpanExporter |

## Critical Gaps to Fix

1. `stage_span()` internal errors → log warning, don't crash
2. `flush()` timeout → log warning, don't block indefinitely

## Round 2 Fixes (from implementation review)

| # | Fix | Impact |
|---|---|---|
| R1 | `register_phoenix()` must be idempotent — lazy init with `_tracer_provider` guard | Prevents double-instrumentation on repeated calls |
| R2 | `dual_emit()` needs `swimlane` param to handle both deterministic AND llm_generated spans | Without this, 3/4 stages (HYPOTHESIZE/DISPATCH/SYNTHESIZE) get no OTel spans |
| R3 | Step 5 split into 5a (structural wrapping) + 5b (behavioral emit replacement) | Bisectable commits, easier debugging |
| R4 | `register_phoenix()` must explicitly call `AnthropicInstrumentor().instrument()` | Auto-instrumentation won't work without this |
| R5 | Step 8 "uninstall test" replaced with mock-based `PHOENIX_AVAILABLE=False` test | Can't uninstall packages inside a running test process |

## Implementation Steps

### Step 1: Scaffold + dependencies
**Files:** `harness/phoenix_tracer.py`, `requirements-dev.txt`
**TDD:** Write skeleton with PHOENIX_AVAILABLE=False, verify import doesn't crash
**What:**
- Create `requirements-dev.txt` with:
  - arize-phoenix-otel
  - openinference-instrumentation-anthropic
  - opentelemetry-sdk (explicit for InMemorySpanExporter in tests)
- Create `harness/phoenix_tracer.py` with:
  - try/except import guard → PHOENIX_AVAILABLE flag
  - Module-level `_tracer_provider = None` for idempotency (R1)
  - `register_phoenix(endpoint, project_name)` → returns tracer_provider or None
  - Idempotency: if `_tracer_provider` already set, return it immediately (R1)
  - Call `AnthropicInstrumentor().instrument(tracer_provider=provider)` inside register (R4)
  - No-op fallbacks when PHOENIX_AVAILABLE=False
**Tests first:**
- test_phoenix_available_flag_false_without_deps (mock ImportError)
- test_phoenix_available_flag_true_with_deps (mock successful import)
- test_register_phoenix_returns_provider
- test_register_phoenix_noop_when_unavailable
- test_register_phoenix_idempotent (call twice, same provider returned) (R1)
- test_register_phoenix_calls_anthropic_instrumentor (R4)
**Commit:** "feat: scaffold phoenix_tracer with import guard and registration"

### Step 2: stage_span() context manager
**Files:** `harness/phoenix_tracer.py`
**What:**
- Context manager that creates a CHAIN span for a pipeline stage
- Sets attributes: stage name, mode (simple/medium/complex)
- Logs warning on internal OTel errors (critical gap #1)
- Returns no-op context manager when PHOENIX_AVAILABLE=False
**Tests first:**
- test_stage_span_creates_chain_span (InMemorySpanExporter)
- test_stage_span_sets_stage_attribute
- test_stage_span_noop_when_unavailable
- test_stage_span_logs_warning_on_internal_error
**Commit:** "feat: stage_span() context manager with error logging"

### Step 3: dual_emit() function
**Files:** `harness/phoenix_tracer.py`
**What:**
- Accepts same args as emit_deterministic_span() + trace object
- Adds `swimlane` param (default="deterministic") and `code_enforced` param (default=True) (R2)
- When swimlane="llm_generated": sets code_enforced=False on the TraceSpan (R2)
- Writes to InvestigationTrace via trace.emit()
- Writes to OTel as span attributes on current span (if active)
- No-op on OTel side when PHOENIX_AVAILABLE=False
- Handles trace=None (existing pattern from trace/helpers.py)
**Tests first:**
- test_dual_emit_writes_to_investigation_trace
- test_dual_emit_writes_otel_attributes
- test_dual_emit_noop_otel_when_unavailable
- test_dual_emit_noop_when_trace_is_none
- test_dual_emit_deterministic_swimlane (default: swimlane="deterministic", code_enforced=True) (R2)
- test_dual_emit_llm_swimlane (swimlane="llm_generated", code_enforced=False) (R2)
**Commit:** "feat: dual_emit() for synchronized trace emission"

### Step 4: emit_guardrail() + flush()
**Files:** `harness/phoenix_tracer.py`
**What:**
- `emit_guardrail(stage, passed, tier, violations)` → GUARDRAIL span
- `flush(tracer_provider, timeout_ms=5000)` → force_flush with timeout + warning log (critical gap #2)
**Tests first:**
- test_emit_guardrail_creates_guardrail_span
- test_emit_guardrail_sets_tier_and_violations
- test_flush_calls_force_flush
- test_flush_logs_warning_on_timeout
**Commit:** "feat: emit_guardrail() and flush() with timeout safety"

### Step 5a: Structural wrapping — stage spans + flush (R3)
**Files:** `harness/orchestrator.py`
**What:**
- Import from phoenix_tracer (register_phoenix, stage_span, flush)
- Call register_phoenix() at start of _run_pipeline() (idempotent — safe to call repeatedly)
- Wrap _run_pipeline() in root CHAIN span
- Wrap each _stage_*() call in stage_span()
- Call flush() before returning from _run_pipeline()
- Set OTel trace_id from InvestigationTrace.trace_id (decision #3)
- Handle run_v2() QUESTION_PARSE stage span
**Tests first:**
- test_pipeline_creates_stage_spans (InMemorySpanExporter + mock LLM)
- test_pipeline_trace_id_matches_investigation_trace
- test_pipeline_flushes_at_end
- test_pipeline_works_without_phoenix (graceful degradation)
**Commit:** "feat: wrap orchestrator stages in Phoenix CHAIN spans"

### Step 5b: Behavioral change — replace emit calls with dual_emit() (R3)
**Files:** `harness/orchestrator.py`
**What:**
- Import dual_emit from phoenix_tracer
- Replace emit_deterministic_span() calls (UNDERSTAND) with dual_emit(swimlane="deterministic")
- Replace trace.emit(TraceSpan(...)) calls (HYPOTHESIZE, DISPATCH, SYNTHESIZE) with dual_emit(swimlane="llm_generated")
- Verify existing InvestigationTrace output is unchanged
**Tests first:**
- test_dual_emit_replaces_deterministic_emits
- test_dual_emit_replaces_llm_emits
- test_investigation_trace_output_unchanged_after_migration
**Commit:** "feat: replace emit calls with dual_emit() in orchestrator"

### Step 6: Wire into seam_validator
**Files:** `contracts/seam_validator.py`
**What:**
- Import emit_guardrail from phoenix_tracer
- After existing trace.emit_seam() call in validate_seam(), call emit_guardrail()
**Tests first:**
- test_validate_seam_emits_guardrail_span
- test_validate_seam_guardrail_noop_without_phoenix
**Commit:** "feat: emit GUARDRAIL spans from seam validator"

### Step 7: Wire into DAGExecutor
**Files:** `harness/dag_executor.py`
**What:**
- Import context propagation from phoenix_tracer
- Capture OTel context before ThreadPoolExecutor submit
- Attach context in each worker callable
- Wrap execute() in AGENT span
**Tests first:**
- test_dag_executor_propagates_otel_context
- test_dag_executor_child_spans_parent_correctly
- test_dag_executor_works_without_phoenix
**Commit:** "feat: OTel context propagation in DAGExecutor parallel dispatch"

### Step 8: Full integration test + graceful degradation (R5)
**What:**
- End-to-end test: mock LLM + InMemorySpanExporter, run full pipeline, assert trace tree structure
- Mock-based degradation: mock PHOENIX_AVAILABLE=False, run pipeline, verify no crashes (R5)
- Manual verification: run `pytest tests/` in a clean venv WITHOUT Phoenix deps before PR merge (R5)
**Tests:**
- test_full_pipeline_produces_complete_trace_tree
- test_full_pipeline_with_phoenix_disabled (mock PHOENIX_AVAILABLE=False) (R5)
**Commit:** "test: full integration test + graceful degradation verification"

## Revised Step Count

9 steps (was 8), ~31 tests (was 27), 9 atomic commits (was 8).

## File Change Summary

| File | Type | Lines est. |
|---|---|---|
| `harness/phoenix_tracer.py` | NEW | ~220 |
| `requirements-dev.txt` | NEW | ~5 |
| `tests/test_phoenix_tracer.py` | NEW | ~400 |
| `harness/orchestrator.py` | MODIFY | ~50 lines changed (split across 5a + 5b) |
| `contracts/seam_validator.py` | MODIFY | ~10 lines added |
| `harness/dag_executor.py` | MODIFY | ~20 lines added |

## Architecture Diagram (post-implementation)

```
┌─────────────────────────────────────────────────────────────┐
│  harness/orchestrator.py                                     │
│  _run_pipeline()                                             │
│    ├── register_phoenix()          ← from phoenix_tracer     │
│    ├── with stage_span("UNDERSTAND"):                        │
│    │     ├── _stage_understand()                             │
│    │     ├── dual_emit(trace, ...)  ← replaces old emit     │
│    │     └── validate_seam() → emit_guardrail()             │
│    ├── with stage_span("HYPOTHESIZE"):                       │
│    │     ├── _stage_hypothesize()                            │
│    │     ├── dual_emit(trace, ...)                           │
│    │     └── validate_seam() → emit_guardrail()             │
│    ├── with stage_span("DISPATCH"):                          │
│    │     ├── DAGExecutor.execute()  ← context propagation   │
│    │     │   └── ThreadPoolExecutor workers                  │
│    │     │       └── context.attach() + LLM calls           │
│    │     └── validate_seam() → emit_guardrail()             │
│    ├── with stage_span("SYNTHESIZE"):                        │
│    │     ├── _stage_synthesize()                             │
│    │     ├── dual_emit(trace, ...)                           │
│    │     └── validate_seam() → emit_guardrail()             │
│    └── flush()                      ← batch export + log    │
│                                                              │
│  Auto-instrumented by AnthropicInstrumentor:                 │
│    client.messages.create() → LLM spans nested inside       │
│    stage_span CHAIN spans automatically                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ OTLP (batch)
                           ▼
                   Phoenix Server (sidecar)
                   localhost:6006
```

## Risk Register

| Risk | Mitigation |
|---|---|
| OTel trace_id format mismatch (inv_hex vs 128-bit hex) | Validate during Step 5, pad or convert as needed |
| AnthropicInstrumentor patches fail silently | Test with real Anthropic import in integration test |
| Batch flush timeout blocks CLI exit | 5s timeout + warning log (Step 4) |
| Existing tests break from new imports | Import guard ensures zero side effects (Step 1) |
