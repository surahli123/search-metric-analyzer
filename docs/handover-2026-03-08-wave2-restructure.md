# Handover: Wave 2 Directory Restructure (2026-03-08)

## Project
- **Name:** Search Metric Analyzer
- **Path:** `/Users/surahli/Documents/New project/Search_Metric_Analyzer`
- **Worktree:** `.worktrees/v2-holistic-redesign/` (branch: `feature/v2-holistic-redesign`)
- **PR:** #4 (pushed to `origin/feature/v2-holistic-redesign`)

## Last Session Summary

Completed Wave 2 of the v2.0 holistic redesign: renamed `tools/` → `core/` (5 analysis tools) + `harness/` (orchestrator + connector_investigator). Updated all imports across 31 files. Code review found and fixed 4 issues (dead fallback import, stale markdown refs, test assertion messages). 694 tests passing, eval 6/6 GREEN at 91.7 avg.

## Current State

- **Wave 1** (trace + contracts): DONE
- **Wave 2** (directory restructure): DONE, PR #4 open
- **Wave 3** (trace emission + orchestrator): NOT STARTED — scope may change based on parallel research session
- **Wave 4** (skill file + eval): NOT STARTED

Directory layout is now:
```
core/           # Analysis tools (decompose, anomaly, diagnose, formatter, schema)
harness/        # Orchestration (orchestrator, connector_investigator)
contracts/      # Stage contracts + seam validator (Wave 1)
trace/          # Trace system (Wave 1)
```

## Next Steps

**Wave 3 scope is pending** — a parallel research session is investigating changes that may affect Wave 3's deliverables. Wait for that research to complete before planning Wave 3.

Current Wave 3 backlog items (may change):
1. Add trace emission to core tools (optional `trace` parameter)
2. Build full 4-stage orchestrator in `harness/orchestrator.py` with Claude API
3. Import verdict fusion from existing orchestrator skeleton

## Key Context

- **No logic changes in Wave 2** — pure rename/restructure
- `contribution_pct` naming: deferred, confirmed no actual ambiguity (consistently 0-100 percentages)
- `constrained_by` field validation: deferred to Wave 3 when LLM spans are added
- The worktree branch has all Wave 1 + Wave 2 work; main branch does not
- PR #4 includes ALL commits from Phase 2.1 foundation through Wave 2

## Relevant Files to Read First

- `BACKLOG.md` — current task status for all waves
- `CHANGELOG.md` — full history of changes
- `docs/plans/2026-03-07-v2-holistic-redesign.md` — v2 design doc
- `MEMORY.md` (auto-memory) — project status and architecture overview
