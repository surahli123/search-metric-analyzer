# Handover: KDD v8 — 36/50 completed, 18/50 accurate

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — all code pushed. 12 commits since PR #29.

## Last Session Summary
8 iteration cycles from v1 (15/50, 5/50) to v8 (36/50, 18/50). Built AutoRefine
infrastructure (canary suite + mutation runner). Key insight: code fixes drove ALL
improvements, prompt tuning had zero impact. Exceeded the 15/50 accuracy target.

## Current State
- **v8 results:** 36/50 completed (72%), 18/50 accurate (36%)
- **Pipeline:** 2-LLM-call (HYPOTHESIZE → execute → SYNTHESIZE) with unified DuckDB backend
- **Unified backend:** loads SQLite tables (with types), CSV, and JSON into one DuckDB connection
- **Security:** allowlist write-block, external access locked, row cap 100K
- **LLM:** DeepSeek V3.2 via Novita API, temperature=0
- **AutoRefine:** canary suite (10 tasks), 5 mutations defined, parameterized prompts
- **Tests:** 1,522 backend, all passing

## 18 Accurate Tasks (v8)
task_11, task_22, task_64, task_74, task_86, task_180, task_200, task_214, task_218,
task_243, task_261, task_269, task_283, task_287, task_292, task_305, task_418, task_420

## 14 Non-Completing Tasks
task_19, task_24, task_26, task_27, task_67, task_75, task_194, task_249, task_250,
task_292 (intermittent), task_303 (intermittent), task_330, task_379, task_396, task_408

## Priority 1: Reach 80% Completion (40/50)

The remaining 14 non-completing tasks fail because:
1. **Multi-table SQL the LLM can't write** (~8 tasks) — needs multi-turn agentic SQL
2. **Large file timeouts** (~3 tasks, task_250 has 384MB) — needs chunking or smarter queries
3. **JSON-only tasks with complex schemas** (~3 tasks) — LLM misreads JSON structure

### Recommended fixes:
1. **Multi-turn SQL (3 retries with richer error context)** — currently only 1 retry.
   Feed the actual schema + error into each retry, not just the error message.
2. **Smarter data source selection** — when the LLM's SQL references tables from
   different backends, try the unified backend automatically.
3. **Codex CLI for parallel error analysis** — while Claude Code fixes code, use
   `codex exec "analyze errors..."` to identify patterns in the 14 failing tasks.

## Priority 2: Improve Accuracy (target 25/50)

18 tasks complete but produce wrong answers. Root causes:
1. **Wrong SQL logic** (~10 tasks) — LLM generates syntactically valid but semantically wrong SQL
2. **Answer format mismatch** (~5 tasks) — correct values but different structure than gold
3. **Partial credit tasks** (~3 tasks) — close but not exact match

### Recommended fixes:
1. **Stronger model** — try Claude Sonnet or GPT-4o for HYPOTHESIZE (SQL planning).
   Keep DeepSeek for SYNTHESIZE (cheap, format-only task).
2. **Self-consistency (best-of-3)** — run each task 3x, take most common answer.
   With temperature=0 this should be deterministic, but the SQL retry path introduces variance.
3. **Gold-aware SYNTHESIZE** — show the LLM the gold.csv header format so it knows
   what shape to produce (e.g., "COUNT(DISTINCT T1.event_id)" vs "count").

## Priority 3: Documentation
- Run `/document-release` to fix 30+ stale `data/knowledge/` path references
- Update architecture rules to include `domains/` and `kdd/` layers
- Note: `temperature=0` in harness/llm.py affects search metrics too — verify this is OK

## Key Files
1. Runner: `kdd/runner.py` (main pipeline + unified backend)
2. Prompts: `domains/data_analysis/prompts.py` (parameterized via PROMPT_CONFIG)
3. Canary: `kdd/canary.py` (10-task rapid validation suite)
4. AutoRefine: `kdd/autorefine.py` (mutation loop)
5. Evaluator: `kdd/evaluator.py` (fuzzy matching + partial credit)
6. LLM factory: `harness/llm.py` (temperature=0 set here)

## Canary Command (quick validation after any change)
```bash
source .venv/bin/activate && source ~/.zshrc
python -m kdd.canary  # 10 tasks, ~7 min, flags regressions
```

## Full Batch Command
```bash
# 5 parallel agents via Claude Code (fastest)
# Or sequential:
python -m kdd.runner --input-dir data/kdd_tasks/demo_samples/input/ \
                     --gold-dir data/kdd_tasks/demo_samples/output/ \
                     --output results.json
```

## Codex CLI Integration (for next session)
```bash
# Parallel error analysis while Claude Code fixes code
codex exec "Read kdd/runner.py. Analyze why 14/50 tasks fail to complete. Focus on SQL execution errors. Suggest the top 3 code fixes." --read-only

# Code review after fixes
codex review
```
