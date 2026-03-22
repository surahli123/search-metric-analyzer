# Handover: Phoenix Integration — Design + Plan Complete

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`feature/phoenix-integration` — created from `main`, no commits yet (design artifacts are untracked).

## Last Session Summary
Researched Arize Phoenix (open-source LLM observability), ran `/office-hours` brainstorming to evaluate adoption, produced a design doc, ran 2 rounds of `/plan-eng-review`, and wrote a 9-step TDD implementation plan. All architectural decisions are locked. Ready for implementation.

## Current State
- **Design doc:** `docs/plans/2026-03-20-arize-phoenix-integration-design.md` (APPROVED)
- **Implementation plan:** `docs/plans/2026-03-20-phoenix-integration-implementation-plan.md` (reviewed, 2 rounds CLEARED)
- **TODOS.md:** Created with eval integration follow-up
- **BACKLOG.md:** Updated with Phoenix integration section
- **CHANGELOG.md:** Updated with session summary
- **No code written yet** — design and planning only

## What Phoenix Integration Does
Adds Arize Phoenix as a dev-time observability layer alongside the existing `trace/` enforcement system. Auto-instruments Anthropic SDK calls, wraps pipeline stages in OTel CHAIN spans, maps domain concepts (seam validations → GUARDRAIL spans, IC9 decisions → span attributes). Runs as a sidecar (`phoenix serve` on localhost:6006).

## 12 Key Decisions (locked)
1. Dual-emit in `harness/phoenix_tracer.py`, trace/ (Layer 3) untouched
2. Explicit OTel context propagation in DAGExecutor ThreadPoolExecutor workers
3. Correlate trace IDs directly — OTel trace_id from InvestigationTrace.trace_id
4. Batch exporter + explicit `flush()` at pipeline end
5. Single import guard + `PHOENIX_AVAILABLE` flag in phoenix_tracer.py
6. Single `dual_emit()` replaces existing emit calls
7. Full test suite (31 tests) with InMemorySpanExporter
8. Idempotent `register_phoenix()` with `_tracer_provider` lazy init guard
9. `dual_emit()` handles both swimlanes via `swimlane` parameter
10. Step 5 split into 5a (structural wrapping) + 5b (behavioral change)
11. Explicit `AnthropicInstrumentor().instrument()` call in `register_phoenix()`
12. Graceful degradation tested via mock `PHOENIX_AVAILABLE=False`, not package uninstall

## Next Steps (in order)
1. **Install dev dependencies:** `pip install arize-phoenix-otel openinference-instrumentation-anthropic`
2. **Execute Step 1:** Scaffold `harness/phoenix_tracer.py` + `requirements-dev.txt` (TDD — 6 tests first)
3. **Steps 2-4:** Build out phoenix_tracer.py functions (stage_span, dual_emit, emit_guardrail, flush)
4. **Steps 5a-5b:** Wire into orchestrator (structural wrapping, then emit replacement)
5. **Steps 6-7:** Wire into seam_validator and DAGExecutor
6. **Step 8:** Full integration test + graceful degradation
7. **Code review** before merging
8. **Manual verification:** Run `pytest tests/` in clean venv WITHOUT Phoenix deps to confirm all existing tests pass

## Key Files to Read First
- `docs/plans/2026-03-20-phoenix-integration-implementation-plan.md` — The implementation plan (read this FIRST)
- `docs/plans/2026-03-20-arize-phoenix-integration-design.md` — Design doc with architecture diagram and span mapping
- `harness/orchestrator.py` — Main file being modified (1,872 lines, `_run_pipeline()` is the target)
- `trace/collector.py` — Existing trace system (InvestigationTrace, emit/emit_seam)
- `trace/helpers.py` — Existing `emit_deterministic_span()` pattern (dual_emit follows this)
- `harness/dag_executor.py` — ThreadPoolExecutor parallel dispatch (needs context propagation)
- `contracts/seam_validator.py` — `validate_seam()` (needs GUARDRAIL span emission)

## Gotchas
- **OTel trace_id format:** InvestigationTrace uses `inv_<hex>` (short), OTel requires 128-bit hex. Need to pad/convert during Step 5a.
- **Don't modify `trace/`** — Layer 3 boundary. All Phoenix code lives in `harness/`.
- **Orchestrator has 2 emit patterns:** deterministic (`emit_deterministic_span()`) and LLM-generated (`trace.emit(TraceSpan(...))`). `dual_emit()` must handle both via `swimlane` param.
- **ThreadPoolExecutor breaks OTel context** — worker threads need explicit `context.attach()`.
- **AnthropicInstrumentor monkey-patches the SDK** — must be called ONCE (idempotency guard in `register_phoenix()`).
