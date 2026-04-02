# Handover: KDD v28 — AutoKaggle Patterns + 60% Accuracy Record

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — all code shipped. No open PRs.

## Last Session Summary
28 iterations (v10→v28). Implemented Meta Analytics Agent + AutoKaggle design
patterns. Accuracy went from 46%→60% (best single run v27: 30/50). Tested 6
models on Novita, all fail on the same hard tasks. Experiment registry with
negative example injection was the biggest breakthrough (v26→v27: 27→30).

## Current State
- **Best accuracy**: 30/50 (60%) — v27
- **Accuracy band**: 26-30/50 (52-60%), mean ~27-28
- **Completion**: 48-49/50 (96-98%)
- **Best-of-3 ceiling**: 31/50 (62%) — nearly reached
- **Experiment registry**: seeded with 50+ task attempts across 2 runs
- **Tests**: 38 passing, 0 regressions
- **Scheduled runs**: v24-v26 scheduled via `at` (check /tmp/v24_mm_batch*.out)

## Next Session Priorities

### Priority 1: Stabilize at 28+ accuracy
The accuracy oscillates 26-30 due to nondeterminism. Run 5 more batches and
take the mean to establish a stable baseline. If mean is 28+, the AutoKaggle
improvements are confirmed. If <27, the negative examples may need capping.

### Priority 2: Cap negative examples to avoid confusion
v28 dropped to 26 (from v27's 30). Too many negative examples may confuse the
LLM. Try capping at 1-2 most recent failures instead of 3. Also consider only
injecting failures that had specific error patterns (not nondeterministic flips).

### Priority 3: Multi-round retry (last AutoKaggle gap)
For the ~10 consistently wrong tasks, implement a second round:
- Round 1: standard pipeline (current)
- Round 2: if Round 1 failed, use learnings from Round 1 failure to retry
  with a specifically adjusted prompt ("your last attempt gave X, which is
  wrong because Y — try a different approach")
This is different from the iterative loop (which happens within a single run).

### Priority 4: Dynamic learnings update
After each batch, automatically extract patterns from new correct/wrong tasks
and update kdd/learnings.json. Currently the learnings file is static (hand-written).
AutoKaggle updates LEARNINGS.md after each campaign automatically.

### Priority 5: KDD competition submission
With 60% accuracy, we have a solid baseline. Consider:
- Running best-of-3 on all 50 tasks for submission (ceiling: 62%)
- Analyzing the competition leaderboard for context on where 60% ranks
- Identifying if the remaining 20 wrong tasks share patterns addressable
  by a different model or approach

## Key Files
- Runner: `kdd/runner.py` (full pipeline with all improvements)
- State: `kdd/state.py` (experiment registry, file locking, retrospective)
- Learnings: `kdd/learnings.json` (6 SQL patterns, injected per question)
- Prompts: `domains/data_analysis/prompts.py` (few-shot + pattern memory + learnings)
- Evaluator: `kdd/evaluator.py` (normalization + relative tolerance)
- LLM: `harness/llm.py` (MiniMax M2.7 default, configurable temperature)
- Research: `docs/research/2026-04-01-autokaggle-learnings.md`
- Research: `docs/research/2026-03-30-meta-analytics-agent-learnings.md`
- Research: `docs/research/2026-04-01-token-efficient-agent-teams.md`

## What Worked (ranked by impact)
1. **Experiment registry + negative examples** (AutoKaggle) — v26→v27: +3
2. **Few-shot SQL examples** — v22→v23: +2
3. **Structured 6-point reviewer** (AutoKaggle) — v24→v25: +3
4. **sqlite_scanner** (Codex finding) — eliminated 100K row cap
5. **JSON schema context fix** — showed record columns instead of outer keys
6. **SQL retries + empty retry** — v10→v12: +3

## What Didn't Work
- Prompt tuning (AutoRefine 0/5, aggregation hints ignored by model)
- LLM sanity check (detects problems, can't fix them)
- Data exploration/question decomposition (JSON parse failures, prompt truncation)
- Ensemble best-of-3 (marginal: +1-2 at 3x cost)
- 6 different open-source models (all fail on same 10 hard tasks)

## API & Environment
- **Novita API**: MiniMax M2.7, ~$0.007/task, NOVITA_API_KEY in ~/.zshrc
- **Virtual env**: `.venv/` with anthropic, pyyaml, pytest, openai, fastapi, duckdb
- **Batch scripts**: `/tmp/batch_run.py`, `/tmp/batch_ensemble.py`, `/tmp/batch_best_of_n_split.py`
- **Experiments**: `kdd/experiments.json` (auto-updated per run, file-locked)
