# Handover: KDD v22 — Pipeline Maximized for Open-Source Models

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — all code shipped. No open PRs.

## Last Session Summary
Epic iteration session: ran v10→v22 (22 batch runs), tested 6 models, implemented
15+ pipeline improvements, analyzed Meta's Analytics Agent architecture, and ran
Codex in parallel for code analysis. Completion went from 86%→98%, accuracy from
46%→54% (single-run best), with a best-of-3 ceiling of 62%.

## Current State
- **Pipeline**: Fully optimized for MiniMax M2.7 via Novita API
- **Accuracy band**: 25-27/50 (50-54%) per single run, oscillates due to 9 nondeterministic tasks
- **Best-of-3 ceiling**: 31/50 (62%) — theoretical max with current model
- **Completion**: 48-49/50 (96-98%)
- **Tests**: 38 passing (runner + evaluator + unified), 0 regressions
- **All code on main**, changelog updated

## What's Shipped (Complete Feature List)
1. SQL retry loop (2 retries) + empty result retry
2. Alternative SQL approach fallback + all-approaches chooser
3. Iterative reasoning loop (Meta Analytics Agent)
4. SQL pattern memory (6 patterns based on failure analysis)
5. sqlite_scanner (eliminated 100K row cap — Codex's #1 finding)
6. JSON schema context fix (json.load instead of truncated read_file)
7. SQLite sample rows in schema context
8. JOIN hints from shared column names
9. JOIN-first prompt strategy (replaced "prefer simple queries")
10. Configurable temperature on make_openai_llm()
11. Evaluator: cell normalization, header detection, relative tolerance (0.1%)
12. 7 new tests, 30+ doc path fixes
13. Data exploration function (preserved but disabled — needs stronger model)

## What Didn't Work (Tried and Reverted/Abandoned)
- **Prompt tuning**: AutoRefine 0/5 mutations beat baseline. Aggregation hints ignored by model.
- **LLM sanity check**: Model detects wrong answers but can't write correct replacement SQL.
- **Data exploration**: JSON parse failures (markdown fences), prompt truncation.
- **Ensemble (best-of-3)**: +1-2 accuracy at 3x cost — marginal.
- **6 different models**: All fail on same 12 tasks (model ceiling, not model-specific).

## The 12 Unsolvable Tasks (need frontier model or new approach)
task_25, task_75, task_80, task_169, task_196, task_344, task_349, task_352,
task_355, task_38, task_396, task_418

Common patterns: complex aggregations, multi-table JOINs with wrong column selection,
domain-specific filter conditions not defined in knowledge.md.

## Next Steps (Priority Order)
1. **Try frontier model** (Claude Sonnet/Opus, GPT-4o) on the 12 hard tasks — need API access
2. **Question decomposition with stronger model** — _explore_data() is ready, just needs a model
   that follows JSON instructions reliably
3. **Submit to KDD competition** with current 52% accuracy as baseline
4. **Run /document-release** if any more stale paths found

## Key Files
- Runner: `kdd/runner.py` (pipeline + all retry/chooser/exploration logic)
- Evaluator: `kdd/evaluator.py` (fuzzy + contains + scalar/rowset + normalization)
- Prompts: `domains/data_analysis/prompts.py` (parameterized + pattern memory)
- LLM: `harness/llm.py` (MiniMax M2.7 default, configurable temperature)
- Canary: `kdd/canary.py` (10-task rapid validation)
- Research: `docs/research/2026-03-30-meta-analytics-agent-learnings.md`
- Handover: `docs/handover-2026-03-29-kdd-v14-iteration.md` (detailed v10→v22 results)

## Key Context
- **Novita API**: MiniMax M2.7 via `NOVITA_API_KEY` in ~/.zshrc (~$0.007/task)
- **Virtual env**: `.venv/` with anthropic, pyyaml, pytest, openai, fastapi, duckdb
- **Batch script**: `/tmp/batch_run.py` (single-run), `/tmp/batch_ensemble.py` (best-of-N)
- **temperature=0** globally — affects search metrics too (see configurable param)
- **sqlite_scanner** extension auto-installs on first use
