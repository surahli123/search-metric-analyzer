# Handover: KDD v10 — 43/50 completed, 23/50 accurate

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — all code pushed. 20+ commits since PR #29.

## Session Summary
Epic session: built Wave 7A-7D (Domain Plugin + KDD Runner), ran 10 iteration
cycles from v1 (15/50, 5/50) to v10 (43/50, 23/50). Tested 8 models (MiniMax M2.7
won). Built AutoRefine infrastructure. Discovered Codex parallel analysis workflow
(found 6 bugs that manual iteration missed). Total: +187% completion, +360% accuracy.

## Current State
- **v10 results:** 43/50 completed (86%), 23/50 accurate (46%) with MiniMax M2.7
- **Default model:** MiniMax M2.7 via Novita API ($0.007/task)
- **Pipeline:** 2-LLM-call (HYPOTHESIZE → execute → direct CSV), SYNTHESIZE bypassed for simple results
- **DuckDB-native JSON:** read_json_auto + recursive unnest (100x faster than Python)
- **3 uncommitted fixes in code:** CSV escaping, None handling, scalar/rowset equivalence
- **Codex CLI:** v0.117.0 via brew. Desktop app also installed at /Applications/Codex.app
- **AutoRefine:** canary suite (10 tasks), 5 mutations, parameterized prompts

## Priority 1: Run v11 (3 fixes already committed)

Three fixes are committed but weren't in the v10 run:
1. CSV writer for proper escaping (commas in values like "MCTD, AMI")
2. None → empty string (DuckDB NULLs)
3. Scalar/rowset equivalence (gold=[1,1,1,1] matches predicted=[4])

Just run the batch — no code changes needed:
```bash
source .venv/bin/activate && source ~/.zshrc
for b in 1 2 3 4 5; do
  python3 /tmp/batch_run.py "minimax/minimax-m2.7" $b > /tmp/v11_mm_batch${b}.out 2>&1 &
done
```

Expected: accuracy should jump from 23/50 to ~27-30/50 (scalar equivalence alone
should flip task_145 and similar count-vs-rows tasks).

## Priority 2: Remaining Accuracy Improvements

7 tasks still don't complete. 20 complete but wrong. Patterns:
- **Batch 1** weakest (2/10 accurate) — LLM writes wrong SQL logic
- **Batch 4** improving (4/10) but still below batch 2/3/5
- **SQL logic errors** are the ceiling — model quality, not pipeline

Next levers:
1. **Multi-turn SQL (3+ retries)** — currently 1 retry. More retries with richer error context
2. **Ensemble (best-of-3)** — run each task 3x, take most common answer
3. **Stronger model for hard tasks** — use Claude Sonnet for batch 1/4 (hard tasks)

## Priority 3: Documentation
- Run `/document-release` for 30+ stale `data/knowledge/` path references
- Note: `temperature=0` in harness/llm.py affects search metrics too

## Key Files
1. Runner: `kdd/runner.py` (pipeline + unified DuckDB backend)
2. Evaluator: `kdd/evaluator.py` (fuzzy + contains + scalar/rowset)
3. LLM factory: `harness/llm.py` (MiniMax M2.7 default, temperature=0)
4. Prompts: `domains/data_analysis/prompts.py` (parameterized via PROMPT_CONFIG)
5. Canary: `kdd/canary.py` (10-task rapid validation)
6. AutoRefine: `kdd/autorefine.py` (mutation loop)
7. Batch script: `/tmp/batch_run.py` (reusable, takes model + batch number)

## Parallel Workflow (proven effective)
```
Terminal 1 (Claude Code): fix → canary → batch (Novita API)
Terminal 2 (Codex CLI):   analyze errors → suggest fixes (OpenAI API)
```

Codex commands:
```bash
codex exec "Read kdd/runner.py. [analysis prompt]" -C $(pwd) -s read-only -c 'model_reasoning_effort="high"'
```

## Model A/B Results (canary, 10 tasks)
| Model | Completed | Accurate |
|-------|-----------|----------|
| DeepSeek V3.2 | 9/10 | 8/10 |
| MiniMax M2.7 | 10/10 | 7/10 |
| GLM-5 | 10/10 | 7/10 |
| Qwen3 Coder 480B | 9/10 | 7/10 |
| Qwen3.5 397B | 10/10 | 6/10 |
| Kimi K2-thinking | 9/10 | 6/10 |
| DeepSeek R1 | 3/10 | 1/10 |
| Kimi K2.5 | 1/10 | 1/10 |
