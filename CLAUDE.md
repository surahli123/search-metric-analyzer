# Search Metric Analyzer

## Project Context
Enterprise Search metric diagnosis tool + KDD Cup 2026 data analysis pipeline.
Two modes: search metric diagnosis (SearchMetricsDomain) + general data analysis (DataAnalysisDomain).
Designed for a team of 2 Senior DSs debugging metric movements for Eng Leads.

## Domain
Enterprise Search (like Glean). Key concepts:
- Tenant tiers (standard/premium/enterprise), AI enablement, connector types
- Metrics: Click Quality, Search Quality Success, AI trigger/success, zero-result rate, latency
- Search Quality Success formula: max(click_component, ai_trigger * ai_success)
- AI answers and Click Quality have INVERSE co-movement (more AI answers = fewer clicks = expected)

## Code Conventions
- Python 3.10+, stdlib + PyYAML + DuckDB
- Heavy comments explaining WHY, not just WHAT
- Small functions, small files
- All tools are CLI scripts: `python core/decompose.py --input data.csv`
- Output is always JSON to stdout (Claude Code reads it)

## Key Files
- Domain interface: `contracts/domain_interface.py`
- Search domain: `domains/search_metrics/__init__.py`
- Data analysis domain: `domains/data_analysis/__init__.py`
- KDD runner: `kdd/runner.py` (2-LLM-call pipeline)
- KDD evaluator: `kdd/evaluator.py` (fuzzy + contains + scalar/rowset matching)
- KDD canary: `kdd/canary.py` (10-task rapid validation suite)
- LLM factory: `harness/llm.py` (MiniMax M2.7 default via Novita API)
- Knowledge: `domains/search_metrics/knowledge/*.yaml`
- Skill file: `skills/search-metric-analyzer.md`

## Testing
Run: `pytest tests/ -v`
All tools have unit tests in `tests/test_<tool>.py`
Canary suite: `python -m kdd.canary` (10 tasks, ~7 min)

## KDD Pipeline Architecture
- 2-LLM-call: HYPOTHESIZE (plan SQL) → execute SQL → direct CSV output (SYNTHESIZE bypassed for simple results)
- Unified DuckDB backend loads SQLite + CSV + JSON into one connection
- JSON loaded via DuckDB-native `read_json_auto` + `unnest(records, recursive := true)`
- Security: allowlist write-block (SELECT/WITH only), external access disabled after data load
- SQL retry: on error, feeds error + schema back to LLM for correction (1 retry)

## KDD Iteration Strategies (Proven)
- Code fixes >> prompt tuning (AutoRefine found 0/5 mutations beat baseline)
- Canary suite (10 tasks) validates fixes in ~7 min before full 50-task batch
- Codex parallel analysis finds bugs that batch iteration misses (6 bugs found)
- Model matters: MiniMax M2.7 > DeepSeek V3.2 for completion+accuracy
- temperature=0 stabilizes accuracy (12% reliability without → ~80% with)

## Verification Checklist (KDD)
- After any change to `_execute_unified`: test SQLite-only, CSV-only, JSON-only, AND mixed paths
- After any evaluator change: run canary to check for regressions
- After any prompt change: run AutoRefine (`python -m kdd.autorefine`) to verify no regression
- Before full batch: smoke-test 1 task live (`python -m kdd.runner --task <dir>`)

## Known Issues
- `temperature=0` in `harness/llm.py` affects search metrics too — verify before using for investigations
- Knowledge YAML paths updated to `domains/search_metrics/knowledge/` (was `data/knowledge/`)
- `_execute_unified` has 4 loading paths but limited test coverage for JSON-native path
- 100K row cap may produce wrong answers for tasks needing full-table aggregates
