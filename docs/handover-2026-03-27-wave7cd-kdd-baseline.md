# Handover: Wave 7C/7D Complete + KDD Baseline + v2 Prompt Tuning Results

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — PRs #28 and #29 merged. All code is on main.

## Last Session Summary
Implemented Wave 7A-7D in a single session: Domain Plugin Architecture (PR #28),
Data Analysis Domain + KDD Runner (PR #29), ran 50-task baseline. 4 review rounds
with gstack + Codex found 20 issues, all fixed. Baseline: 15/50 completed, 5/50 accurate.

## Current State
- **Domain Plugin**: 2 domains — SearchMetricsDomain (search diagnosis) + DataAnalysisDomain (KDD tasks)
- **KDD Runner**: 2-LLM-call pipeline (HYPOTHESIZE → execute SQL → SYNTHESIZE)
- **Unified Backend**: DuckDB handles mixed SQLite+CSV tasks (both loaded into one connection)
- **Baseline saved**: `data/kdd_tasks/baseline_results_v1.json`
- **Tests**: 1,522 backend, all passing
- **Virtual env**: `.venv/` with anthropic, pyyaml, pytest, openai, fastapi, duckdb
- **Novita API**: NOVITA_API_KEY in ~/.zshrc, DeepSeek V3.2, ~$0.004/task

## v2 Prompt Tuning Results (same session)

Committed as `acfacd1` on main. Changes: schema summary header, DuckDB hints, values-only output.

| Metric | v1 | v2 | Delta |
|--------|----|----|-------|
| Completed | 15/50 (30%) | 19/50 (38%) | +4 |
| Accurate | 5/50 (10%) | 4/50 (8%) | -1 |

Completion improved (+4 tasks, schema summary helped). Accuracy slightly regressed —
"no headers" SYNTHESIZE prompt hurt the evaluator's header-stripping heuristic.

### v2 accurate tasks: task_214, task_305, task_420 (+ 1 from batch 3 unclear)
### v1 accurate tasks that regressed: task_26, task_200, task_67

## Priority 1: Three Quick Fixes (highest ROI)

The #1 failure mode is **table not found** (50% of failures). The LLM guesses table
names because `_build_schema_context()` doesn't surface all available tables clearly.

### Three quick fixes (do these first):

0. **CRASH BUG: `_extract_best_sql` breaks on list response** (`kdd/runner.py:~423`)
   - LLM sometimes returns a list instead of `{"approaches": [...]}` dict
   - `hyp_result.get("approaches")` throws `AttributeError: 'list' object has no attribute 'get'`
   - Fix: if isinstance(hyp_result, list), wrap as `{"approaches": hyp_result, "best_approach_index": 0}`
   - Could flip ~5 tasks from failed to completed

1. **Revert SYNTHESIZE to include headers** (`domains/data_analysis/prompts.py`)
   - "No headers" instruction caused accuracy regression (task_26, task_200, task_67 lost)
   - The evaluator's header-stripping heuristic works better than LLM header omission
   - Revert to: "Format as CSV with header row + data rows"

2. **Add SQL retry on error** (`kdd/runner.py:run_task`)
   - When sql_executor returns an error, feed the error message back to the LLM
   - Ask: "Your SQL failed with this error: {error}. Fix the SQL."
   - Single retry could fix type mismatches, wrong table names, escaping issues

### Additional improvements (if time):

3. **Schema context quality** (`kdd/runner.py:_build_schema_context`)
   - Ensure ALL table names from SQLite DBs are listed prominently
   - Include table names from CSVs with explicit "Available tables:" header
   - Add JSON file keys/structure for JSON-only tasks
   - Show table-to-file mapping so LLM knows which table came from where

2. **HYPOTHESIZE prompt** (`domains/data_analysis/prompts.py:build_hypothesize_system_prompt`)
   - Add instruction: "ONLY use table names from the schema above. Do not guess."
   - Add DuckDB-specific hints: use CAST() for type comparisons, use '' not \' for escaping
   - Tell LLM to prefer simple queries (single table) before JOINs

3. **SYNTHESIZE prompt** (`domains/data_analysis/prompts.py:build_synthesize_system_prompt`)
   - Be explicit: "Return ONLY the data values, no column headers, no markdown"
   - Match gold.csv format: one row per line, comma-separated

4. **Answer extraction** (`kdd/runner.py:_clean_csv_response`)
   - Strip markdown fences more aggressively
   - Handle LLM returning column names as first row

### Expected impact:
- Schema fix alone could flip ~25 tasks from "not completed" to "completed"
- Prompt fixes could push accuracy from 5/50 to 15-20/50
- Total cost for re-run: ~$0.20

## Priority 2: Stale Documentation Paths

30+ references to `data/knowledge/` in agent .md files, CLAUDE.md, and .claude/rules/*.md
need updating to `domains/search_metrics/knowledge/`. Run `/document-release` to fix.

## Priority 3: Advanced KDD Improvements (if time)

- VARCHAR typing in unified backend (all columns loaded as VARCHAR)
- Multi-turn SQL refinement (retry on SQL error with error message)
- Code executor for tasks that need Python computation
- AutoRefine for systematic prompt optimization with eval loop

## Key Files to Read First
1. Baseline results: `data/kdd_tasks/baseline_results_v1.json`
2. Runner: `kdd/runner.py` (focus on `_build_schema_context` and `_execute_sql_for_task`)
3. Prompts: `domains/data_analysis/prompts.py`
4. Evaluator: `kdd/evaluator.py`
5. Design doc: `docs/plans/2026-03-27-wave-7cd-data-analysis-kdd-runner.md`

## Batch Run Command
```bash
# Run all 50 tasks (sequential)
source .venv/bin/activate && source ~/.zshrc
python -m kdd.runner --input-dir data/kdd_tasks/demo_samples/input/ \
                     --gold-dir data/kdd_tasks/demo_samples/output/ \
                     --output data/kdd_tasks/results_v2.json
```

## Session Stats
- 2 PRs merged (#28, #29)
- 69 files changed, +6,769 lines
- 1,522 tests (79 new)
- 6 review rounds, 20 issues fixed
- $0.20 batch run cost
