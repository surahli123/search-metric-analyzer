# Supplementary Handover: Technical Debt + Verification Gaps

Read `docs/handover-2026-03-28-kdd-v10-final.md` first for full context.
This document covers what the reflexion:reflect evaluation (3.40/5.0) identified
as gaps in the main session's work.

## Critical: Test the Untested

`_execute_unified` in `kdd/runner.py` has 4 loading paths (~150 lines) but only 4 tests.
The DuckDB-native JSON path (`read_json_auto` + recursive unnest, added this session)
has ZERO test coverage. Write tests for:

1. JSON-only task through `_execute_unified` (e.g., task with only .json files)
2. DuckDB recursive unnest produces correct column names (not struct)
3. Large JSON file with `max_object_size` (>16MB)
4. CSV values containing commas go through `csv.writer` correctly
5. `None` values become empty strings, not `"None"`
6. Scalar/rowset equivalence: evaluator matches `predicted=[4]` vs `gold=[1,1,1,1]`

## Critical: Verify Shared Module Side Effect

`harness/llm.py` has `temperature=0` set globally. This affects BOTH:
- KDD pipeline (correct — we want deterministic SQL)
- Search metrics investigations (UNKNOWN — may reduce hypothesis diversity in HYPOTHESIZE)

**Action:** grep for all callers of `make_openai_llm()`, run one search metric
investigation, check if hypothesis quality is acceptable.

## Debt: 30+ Stale Documentation Paths

Agent `.md` files, CLAUDE.md rules, and `.claude/rules/*.md` still reference
`data/knowledge/` instead of `domains/search_metrics/knowledge/`. This causes
LLM agents to look for files in the wrong location during search metric
investigations. Run `/document-release` to fix.

Files affected:
- `domains/search_metrics/agents/*.md` (10 files)
- `.claude/rules/01-metric-invariants.md`
- `.claude/rules/02-architecture-boundaries.md`
- `.claude/rules/03-diagnostic-patterns.md`
- `.claude/rules/04-knowledge-routing.md`

## Debt: 100K Row Cap Correctness

`_execute_unified` caps SQLite tables and JSON at 100K rows (`_MAX_LOAD_ROWS`).
Codex code review flagged this: `COUNT(*)`, `SUM()`, and JOINs on truncated
tables produce wrong answers silently. No task has proven wrong yet, but it's
unverified.

**Action:** check if any of the 7 non-completing tasks or 20 wrong-answer tasks
have tables >100K rows where the cap matters. If so, consider using DuckDB's
`sqlite_scanner` extension to attach SQLite DBs natively (avoids Python
materialization entirely).

## Debt: Batch 3 Silent Failures

Across v9 and v10, batch 3 output files were 0 bytes on first dispatch
(both models). Re-dispatch always worked. Never root-caused. Likely a race
condition when 10 parallel Python processes all import `kdd.runner` simultaneously,
or Novita API rate limiting on burst.

## Session Metrics (from reflexion:reflect)

| Criterion | Score |
|-----------|-------|
| Instruction Following | 4/5 |
| Output Completeness | 3/5 |
| Solution Quality | 3/5 |
| Reasoning Quality | 4/5 |
| Response Coherence | 3/5 |
| **Weighted Total** | **3.40/5.0** |

Key gap: impressive results (+360% accuracy) but accumulated debt in tests,
docs, and unverified assumptions. Next session should prioritize verification
before adding features.
