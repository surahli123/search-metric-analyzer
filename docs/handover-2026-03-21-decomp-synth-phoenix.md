# Handover — Orchestrator Decomposition + Synthetic Data + Phoenix Integration

## Project
Search Metric Analyzer — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`feature/phoenix-integration` (pushed to origin, PR #25 open → main)

## Last Session Summary
Decomposed the monolithic orchestrator.py (1,872→399 LOC) into 4 stage modules under harness/stages/. Built a synthetic investigation data generator with 5 planted-scenario CSVs. Implemented Phoenix/OpenTelemetry dual tracing across the pipeline. All work code-reviewed, fixes applied, 1,294 tests passing. PR #25 created.

## Current State
- **Tests**: 1,294 backend, all green
- **PR #25**: feature/phoenix-integration → main (7 commits, +9,597/-2,444 lines)
- **Orchestrator**: Decomposed into harness/stages/{understand,hypothesize,dispatch,synthesize}.py
- **run_v2() → run()**: Renamed, with backward-compat alias
- **v1 code deleted**: orchestrate() + 4 helpers (~447 LOC)
- **Synthetic data**: 5 scenarios in data/investigations/*.csv (ranking_regression, ai_adoption_positive, connector_failure, mix_shift, normal_variance)
- **Phoenix tracing**: Implemented and tested (30 tests), no-ops gracefully without OTel deps
- **Virtual env**: `.venv/` with anthropic, pyyaml, pytest installed
- **API investigation**: UNDERSTAND stage validated on ranking_regression data. HYPOTHESIZE/DISPATCH/SYNTHESIZE blocked on Anthropic API credits ($5 minimum at console.anthropic.com)

## Next Steps (Priority Order)
1. **Add Anthropic API credits** → run 3-5 investigations through run_v2() → validate full pipeline end-to-end
2. **Merge PR #25** after investigation validation passes
3. **Wave 6: Knowledge Retrieval Layer** — hybrid TF-IDF + API embeddings, spec approved, 8 tasks in BACKLOG
4. **Agent .md files as prompt source of truth** — replace hardcoded prompts.py (do during Wave 6)
5. **Web App Phase 2** — SSE streaming for Trace tab + real backend integration

## Key Context
- **Max vs API billing**: Claude Max subscription (for Claude Code) is separate from Anthropic API credits (for programmatic calls from Python). They don't share balance.
- **Virtual env required**: macOS PEP 668 blocks system pip. Use `source .venv/bin/activate` before running anything.
- **Worktree cleanup**: `.claude/worktrees/` directory has stale worktrees from this session — can be deleted.
- **Code review findings**: All concerns addressed. Key fixes: run_diagnosis() moved inside try/except (understand.py), LLMCallable type alias added, ai_off rows enforce exact 0.0 for AI metrics.
- **run() vs run_pipeline_only()**: `run()` = Wave 5 entry point (QUESTION_PARSE + mode selection + pipeline). `run_pipeline_only()` = direct 4-stage pipeline without parsing (legacy, used by tests).

## Relevant Files to Read First
- `harness/orchestrator.py` — Slimmed coordinator (399 LOC)
- `harness/stages/` — 4 stage modules + __init__.py
- `scripts/generate_investigation_data.py` — Data generator with 5 scenarios
- `harness/phoenix_tracer.py` — Phoenix/OTel dual tracing
- `BACKLOG.md` — Updated roadmap with completed items
- `CHANGELOG.md` — Full session changelog
