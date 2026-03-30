# Handover: KDD v14 — 49/50 completed, 25-26/50 accurate

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`feature/kdd-v12-retries-and-tests` — 4 commits, PR #30 open against main.

## Session Summary
Continued from v10 handover. Ran v11-v14 iterations (4 full 50-task batch runs).
Completion improved from 86%→98%. Accuracy plateaued at 50-52% due to ~9 tasks
that flip nondeterministically between runs despite temperature=0.

## Commits on Branch
```
6887bfd feat: SQL retry loop (2 retries) + empty result retry + configurable temperature
644b7d1 docs: fix 30+ stale data/knowledge/ paths → domains/search_metrics/knowledge/
c8f2bf2 feat: alternative SQL approach fallback + aggregation prompt hints
f586a77 fix: JSON schema context now shows record columns instead of outer keys
```

## Results Progression

| Version | Completed | Accurate | Key Change |
|---------|-----------|----------|------------|
| v10 | 43/50 (86%) | 23/50 (46%) | Baseline |
| v11 | 41/50 (82%) | 23/50 (46%) | CSV/None/scalar fixes (already committed before this session) |
| v12 | 45/50 (90%) | 26/50 (52%) | 2 SQL retries + empty result retry |
| v13 | 48/50 (96%) | 26/50 (52%) | Alternative approach fallback + prompt hints |
| v14 | 49/50 (98%) | 25/50 (50%) | JSON schema context fix (nondeterminism masked gains) |

## Key Finding: Nondeterminism Is the Ceiling

~9 tasks flip randomly between correct and wrong on every run despite temperature=0.
This means measured accuracy oscillates between 23-27/50 depending on which tasks
get lucky. The "true" accuracy (if we could eliminate variance) is ~25-26/50.

### Nondeterministic tasks (flip between runs)
task_11, task_24, task_86, task_199, task_200, task_214, task_249, task_257, task_305

### Consistently wrong (same wrong answer every run) — 12 tasks
task_169, task_180, task_25, task_344, task_349, task_352, task_355, task_38,
task_396, task_418, task_75, task_80

### Consistently not completing — 1 task
task_194 (mixed CSV+DB, complex JOIN)

## What Each Fix Did

### SQL retry loop (1→2 retries) — v12
- Catches more syntax errors and table-not-found issues
- Helped: task_22 (now completes + correct), task_27 (now completes)
- Canary: 9/10 accurate, 0 regressions

### Empty result retry — v12
- When SQL returns 0 rows, retries with logic-error guidance
- Helped: tasks that returned empty due to wrong JOIN or filter
- Combined with retry loop: +3 accuracy, +2 completion vs v10

### Alternative SQL approach fallback — v13
- When best approach fails or returns 0 rows, tries alternatives from HYPOTHESIZE
- No extra LLM calls — just SQL execution
- Helped: task_415 (completing + correct), task_26, task_408 (now completing)
- Completion: 45→48

### JSON schema context fix — v14
- Root cause: read_file(max_chars=2000) truncated JSON before "records" key visible
- LLM saw "JSON: event (object, 1 keys) -- Keys: table" instead of column names
- Fix: json.load() directly, then extract record keys + sample values
- Helped: task_26 flipped to correct (JSON-only task)
- Completion: 48→49

### Prompt aggregation hints — v13
- Added hints for: average monthly (/12), ratio (A/B), percentage (CAST * 100), lowest (ORDER BY ASC)
- Targeted the 4 most common aggregation failure patterns
- Impact: hard to isolate, mixed with other v13 changes

### Configurable temperature — v12
- make_openai_llm() now accepts temperature parameter (default 0.0)
- KDD unchanged (0.0 for deterministic SQL)
- Search metrics callers should use 0.7 for hypothesis diversity
- Not yet tested with search metrics investigations

## Failure Analysis (12 Consistently Wrong Tasks)

| Task | Gold | Predicted | Failure Type |
|------|------|-----------|-------------|
| task_169 | 459.96 | 82,027,220 | Wrong aggregation (total vs avg/12) |
| task_180 | 1903.2 | [] empty | Complex multi-table, SQL returns nothing |
| task_25 | November Speaker | February Speaker | Wrong row selected (sort/filter) |
| task_344 | 4 | 0 | Filter too restrictive |
| task_349 | Business | Angela, Sanders | Wrong columns (person not major) |
| task_352 | 2.727 | FAILED | LLM can't plan complex ratio query |
| task_355 | Elijah, Allen, 28.15 | IDs, 199.39 | Wrong columns + wrong values |
| task_38 | 816173... | trans_id, account_id... | Headers as data |
| task_396 | 54.84% | 100.0% | Wrong denominator |
| task_418 | 1 | "No structured data" | Markdown-only task (no SQL possible) |
| task_75 | Fisichella | Räikkönen | Wrong driver (sort/filter logic) |
| task_80 | 3 | [] empty | SQL returned nothing |

### Categories
- **Wrong SQL logic** (6 tasks): LLM writes plausible but incorrect SQL
- **Wrong columns** (3 tasks): LLM selects wrong columns or IDs instead of names
- **Empty result** (2 tasks): SQL matches nothing due to filter/JOIN errors
- **No structured data** (1 task): Markdown-only, can't be answered via SQL

## Ensemble Experiment (Partial)

Ran best-of-3 ensemble on batches 1 and 2 (20 tasks × 3 = 60 LLM calls).

### Findings
- Ensemble stabilizes nondeterministic tasks (task_200: 3/3 unanimous)
- But can also lock in wrong answers (task_11: 2/3 majority wrong)
- task_173: 3 different answers, 1 happened to be correct — not reliable
- **Verdict:** Ensemble helps ~3-4 tasks but harms ~2-3 others. Net gain ~1-2 accuracy.
  Not worth 3x cost for marginal improvement.

## Tests
- 127 backend tests pass (120 existing + 7 new in test_runner_unified.py)
- Canary suite: consistently 8-9/10 accurate, regressions are always nondeterminism
- No real regressions from any code change

## What Would Move the Needle

### High confidence (would definitely help)
1. **Stronger model for hard tasks** — Use Claude Sonnet or GPT-4o for the 12 consistently
   wrong tasks. MiniMax M2.7 can't write complex SQL (ratios, multi-table JOINs with
   aggregation). Cost: ~$0.10/task vs $0.007/task.
2. **Task-specific SQL templates** — For known hard patterns (percentage, ratio, GROUP BY
   month), provide SQL templates in the prompt. The LLM fills in table/column names.

### Medium confidence (might help)
3. **Multi-turn SQL with result verification** — After SQL returns, ask the LLM "does this
   answer make sense for the question?" and retry if not. Catches task_169 (82M for an
   "average monthly consumption" question).
4. **Better header stripping in evaluator** — task_38 returns headers as data. The evaluator's
   header detection heuristic may not catch all cases.

### Low confidence (unlikely to help much)
5. **More retries** (3+) — diminishing returns, same errors repeat
6. **Ensemble** — 3x cost for ~1-2 accuracy gain
7. **Prompt tuning** — AutoRefine already showed 0/5 mutations beat baseline

## Key Files
1. Runner: `kdd/runner.py` (pipeline + unified DuckDB backend + retry logic)
2. Evaluator: `kdd/evaluator.py` (fuzzy + contains + scalar/rowset matching)
3. LLM factory: `harness/llm.py` (MiniMax M2.7 default, configurable temperature)
4. Prompts: `domains/data_analysis/prompts.py` (parameterized + aggregation hints)
5. Canary: `kdd/canary.py` (10-task rapid validation)
6. Batch script: `/tmp/batch_run.py` (single-run) `/tmp/batch_ensemble.py` (best-of-N)

## API Cost
- Estimated ~$3-4 total this session (v11-v14 batches + canary runs + debug tests)
- MiniMax M2.7 via Novita API: ~$0.007/task single-run, ~$0.021/task ensemble

## PR
https://github.com/surahli123/search-metric-analyzer/pull/30
