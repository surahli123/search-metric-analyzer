# Handover: Wave 3a Implemented (2026-03-08)

## Project
- **Name:** Search Metric Analyzer
- **Path:** `/Users/surahli/Documents/New project/Search_Metric_Analyzer`
- **Worktree:** `.worktrees/v2-holistic-redesign/` (branch: `feature/v2-holistic-redesign`)
- **PR:** #4 (origin is 8 commits behind local — push needed before next PR update)

## Last Session Summary

Implemented all 7 Wave 3a tasks using subagent-driven-development. Each task followed TDD with two-stage review (spec compliance + code quality). Added trace emission to all 3 core tools, remediation messages to all 11 contract violations, and a corrections knowledge layer with CLI. 45 new tests, 739 total passing, eval unchanged at 6/6 GREEN (91.7 avg).

## Current State

- **Wave 1** (trace + contracts): DONE
- **Wave 2** (directory restructure): DONE, PR #4 open
- **Wave 3a** (trace emission + remediation + corrections): **DONE** (this session)
- **Wave 3b** (SearchMetricOrchestrator): **READY TO IMPLEMENT**
- **Wave 4** (skill file + eval): NOT STARTED
- **Tests:** 739 passing, 21 skipped, eval 6/6 GREEN at 91.7 avg

## What Was Built (Wave 3a)

| Task | File(s) | What |
|------|---------|------|
| 1 | `trace/helpers.py` | `emit_deterministic_span()` — no-ops when trace is None, sets swimlane/code_enforced |
| 2 | `core/decompose.py` | 3 trace spans: metric_direction (IC9 #1), dominant_dimension, mix_shift_significance |
| 3 | `core/anomaly.py` | 11 emit calls across all return paths of 3 functions (data quality, step change, co-movement) |
| 4 | `core/diagnose.py` | 2 trace spans: archetype, confidence_level |
| 5 | `contracts/seam_validator.py` | Remediation suffixes on all 11 violation messages (imperative verb format) |
| 6 | `core/corrections.py` + `data/knowledge/corrections.yaml` | load/find/append corrections, 90-day expiry, CLI with --add flag |
| 7 | Verification | 739 tests pass, eval 6/6 GREEN, E2E trace integration confirmed |

## Next Steps

1. **Push to origin** — 8 commits ahead, need `git push` to update PR #4
2. **Implement Wave 3b** (Tasks 8-14, from same plan file):
   - Task 8: OrchestratorError hierarchy + SearchMetricOrchestrator + UNDERSTAND stage
   - Task 9: HYPOTHESIZE stage (LLM + corrections + IC9 #2)
   - Task 10: DISPATCH stage (reuse orchestrate() + IC9 #3)
   - Task 11: SYNTHESIZE stage (LLM + retry gate + IC9 #4)
   - Task 12: Error handling integration tests
   - Task 13: make_anthropic_llm() factory
   - Task 14: Wave 3b verification
3. **Use subagent-driven-development** — same approach as Wave 3a

## Key Context

- **Plan file:** `~/.claude/plans/wobbly-discovering-newell.md` — contains full TDD test code and implementation code for ALL 14 tasks (Tasks 1-7 done, 8-14 remain)
- **CLI import shadowing pattern:** Core tools use try/except to handle Python's built-in `trace` module shadowing during standalone CLI execution:
  ```python
  try:
      from trace.helpers import emit_deterministic_span
  except (ModuleNotFoundError, ImportError):
      def emit_deterministic_span(*args, **kwargs):
          pass
  ```
- **SOFT gates don't raise:** HYPOTHESIZE/DISPATCH seam validation calls `validate_seam()` without try/except
- **LLM callable pattern:** `Callable[[str, str], str]` — orchestrator accepts any callable, not direct SDK
- **Corrections expiry:** Default 90 days, archetype-exact matches ranked first
- **Error classification:** Transient (429, 500, 502, 503) retried with backoff; permanent (401, 403) fail immediately
- **JSON extraction:** 3-strategy parser (direct → regex fence → outermost braces)
- **constrained_by field:** Must be set on all LLM spans (IC9 #2 and #4)
- **UNDERSTAND result:** Must include `co_movement_pattern` and `mix_shift_result` for HYPOTHESIZE cross-stage rules
- **Python version:** Use `pytest` directly or `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` (not `python3` which may default to 3.14)

## Relevant Files to Read First

- `~/.claude/plans/wobbly-discovering-newell.md` — **THE PLAN** (read Tasks 8-14)
- `BACKLOG.md` — current task status for all waves
- `CHANGELOG.md` — full history of changes
- `trace/helpers.py` — the trace emission helper (used by Wave 3b orchestrator)
- `core/corrections.py` — corrections layer (consumed by Wave 3b HYPOTHESIZE stage)
- `contracts/seam_validator.py` — 11 business rules with remediation (called at stage boundaries)
- `harness/orchestrator.py` — existing orchestrate() function (SearchMetricOrchestrator goes alongside it)
- `trace/collector.py` — InvestigationTrace class (trace emission target)
