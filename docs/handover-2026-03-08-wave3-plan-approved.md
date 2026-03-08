# Handover: Wave 3 Plan Approved (2026-03-08)

## Project
- **Name:** Search Metric Analyzer
- **Path:** `/Users/surahli/Documents/New project/Search_Metric_Analyzer`
- **Worktree:** `.worktrees/v2-holistic-redesign/` (branch: `feature/v2-holistic-redesign`)
- **PR:** #4 (pushed to `origin/feature/v2-holistic-redesign`)

## Last Session Summary

IC9-calibrated review of the Wave 3 implementation plan. Three iterations: Iteration 1 scored 6.2/10 (both reviewers), Iteration 2 scored 6.9/7.05, Iteration 3 scored 7.9/7.8 — both reviewers APPROVED with all dimensions GREEN. The plan was updated with 10 fixes across 3 iterations addressing IC9 coverage gaps, production readiness, error handling, and code quality.

## Current State

- **Wave 1** (trace + contracts): DONE
- **Wave 2** (directory restructure): DONE, PR #4 open
- **Wave 3** (trace emission + remediation + corrections + orchestrator): **PLAN APPROVED, ready to implement**
- **Wave 4** (skill file + eval): NOT STARTED
- **Tests:** 694 passing, 21 skipped, eval 6/6 GREEN at 91.7 avg

## Next Steps

1. **Implement Wave 3a** (Tasks 1-7, independent of each other):
   - Task 1: Create `trace/helpers.py` with `emit_deterministic_span()`
   - Task 2: Add trace to `core/decompose.py` (IC9 #1: metric_direction)
   - Task 3: Add trace to `core/anomaly.py` (3 functions)
   - Task 4: Add trace to `core/diagnose.py`
   - Task 5: Add remediation messages to 11 contract violations
   - Task 6: Create `core/corrections.py` + `data/knowledge/corrections.yaml`
   - Task 7: Wave 3a verification

2. **Implement Wave 3b** (Tasks 8-14, depends on 3a):
   - Task 8: OrchestratorError hierarchy + SearchMetricOrchestrator + UNDERSTAND stage
   - Task 9: HYPOTHESIZE stage (LLM + corrections + IC9 #2)
   - Task 10: DISPATCH stage (reuse orchestrate() + IC9 #3)
   - Task 11: SYNTHESIZE stage (LLM + retry gate + IC9 #4)
   - Task 12: Error handling integration tests
   - Task 13: make_anthropic_llm() factory
   - Task 14: Wave 3b verification

3. **Use subagent-driven-development** — user's preferred execution method

## Key Context

- **Plan file:** `~/.claude/plans/wobbly-discovering-newell.md` — contains full TDD test code and implementation code for ALL 14 tasks
- **Execution approach:** Use `superpowers:subagent-driven-development` skill — fresh subagent per task + two-stage review (spec then quality)
- **SOFT gates don't raise:** HYPOTHESIZE/DISPATCH seam validation calls `validate_seam()` without try/except (soft gates return violations dict, never raise SeamViolation)
- **LLM callable pattern:** `Callable[[str, str], str]` — orchestrator accepts any callable, not direct SDK
- **Corrections expiry:** Default 90 days, archetype-exact matches ranked first
- **Error classification:** Transient (429, 500, 502, 503) retried with backoff; permanent (401, 403) fail immediately
- **JSON extraction:** 3-strategy parser (direct → regex fence → outermost braces)
- **constrained_by field:** Must be set on all LLM spans (IC9 #2 and #4) — lists which rules bounded the output
- **UNDERSTAND result:** Must include `co_movement_pattern` and `mix_shift_result` for HYPOTHESIZE cross-stage rules to work
- **Non-blocking suggestions from review:** walrus operator comment, _is_transient() typed exceptions cleanup (Wave 4), _extract_json() edge case

## Relevant Files to Read First

- `~/.claude/plans/wobbly-discovering-newell.md` — **THE PLAN** (read this first)
- `BACKLOG.md` — current task status for all waves
- `CHANGELOG.md` — full history of changes
- `harness/orchestrator.py` — existing orchestrate() function (SearchMetricOrchestrator goes alongside it)
- `trace/collector.py` — InvestigationTrace class (trace emission target)
- `contracts/seam_validator.py` — 11 business rules (remediation messages target)
- `core/decompose.py`, `core/anomaly.py`, `core/diagnose.py` — trace emission targets
