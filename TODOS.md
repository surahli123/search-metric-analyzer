# TODOS

## Phoenix Integration Follow-ups

### Wire Phoenix into eval stress test pipeline
**Priority:** High | **Effort:** S (CC: ~10 min)
**What:** Call `register_phoenix()` at the start of `eval/run_stress_test.py` so all 7 scenarios produce visual traces in Phoenix.
**Why:** Currently eval outputs pass/fail scores but you can't visually debug WHY a scenario failed. With Phoenix traces per scenario, you click into the failing run and see exactly which LLM call produced bad output.
**Depends on:** Base Phoenix integration (`harness/phoenix_tracer.py`) must be complete and tested.
**Context:** Design doc Open Question #3. The coupling is acceptable because eval is already a dev-time tool. Implementation: ~10 lines — import register_phoenix, call at start, flush at end.
