# Handover: Domain Plugin Architecture Design — Ready for Implementation

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — create `feature/wave-7a-domain-extraction` before implementing.

## Last Session Summary
Implemented OpenAI-compatible LLM factory (PR #27, merged). Ran 6 real investigations
(3 scenarios × 2 models, 100% pass). Then brainstormed next phase via `/office-hours`:
designed Domain Plugin Architecture for KDD Cup 2026 generalization. Eng-reviewed the
design doc — 5 issues found, all resolved. Design is APPROVED and implementation-ready.

## Current State
- **OpenAI factory:** Merged, 1,324 tests passing, 6/6 investigations PASS
- **Design doc:** APPROVED at `~/.gstack/projects/surahli123-search-metric-analyzer/surahli-main-design-20260322-194713.md`
- **Reviews:** Office-hours spec review (15 issues, 10 fixed) + Eng review (5 issues, all resolved) + Codex adversarial (11 findings, all addressed)
- **Novita API:** $50 budget, NOVITA_API_KEY in ~/.zshrc
- **Virtual env:** `.venv/` with anthropic, pyyaml, pytest, openai, fastapi, duckdb (not yet installed)

## Next Steps (in order)

### 0. Extract and examine 5 KDD demo tasks (FIRST — before any code)
```bash
mkdir -p data/kdd_tasks
cd data/kdd_tasks && unzip /Users/surahli/Downloads/demo_samples.zip
```
Read 5 sample tasks (1 easy, 1 medium, 1 hard, 1 extreme, 1 random). Understand:
- Exact structure of task.json
- What data sources each task provides (CSV, SQLite, JSON, markdown)
- What the gold.csv ground truth looks like
- Whether any tasks require Python code execution (validates code_executor deferral)

### 1. Wave 7A.1: Create DomainInterface Protocol (1 session)
- Create `contracts/domain_interface.py` with Protocol class
- Signature: `get_knowledge(query, stage, token_budget)` (enriched per eng review)
- Define generic vs domain-specific TypedDict fields
- Create `domains/search_metrics/__init__.py` implementing DomainInterface
- Move prompts.py → domains/search_metrics/prompts.py
- Move knowledge YAMLs → domains/search_metrics/knowledge/
- All 1,324 backend tests must pass

### 2. Wave 7A.2: Extract stage logic + quality rules (1-2 sessions)
- Split seam_validator: generic framework + 11 search-specific rules → domains/search_metrics/rules.py
- Make stage functions accept DomainInterface parameter
- Make question_parser + mode_selector delegate to domain
- Move 7 agent .md files → domains/search_metrics/agents/

### 3. Wave 7B: Core tools — SQL executor + file reader (1 session)
- `core/sql_executor.py` — DuckDB primary, sqlite3 fallback (eng review decision 6A)
- `core/file_reader.py` — CSV, JSON, markdown, SQLite schema
- code_executor.py DEFERRED until KDD task analysis confirms need
- Install: `.venv/bin/pip install duckdb`

### 4. Wave 7C: data_analysis domain module (1 session)
### 5. Wave 7D: KDD runner + validation (1 session)

## Key Decisions Made This Session

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture approach | Domain Plugin (Approach A) | Dual-use: SMA + KDD. Clean conference story. |
| Contracts structure | Generic plumbing + domain data (2A) | Beck's rule: make the change easy first |
| Knowledge API | `get_knowledge(query, stage, token_budget)` (4A) | Explicit > clever. search_metrics needs routing context |
| SQL engine | DuckDB primary + sqlite3 fallback (6A) | DuckDB queries CSV-as-SQL-table. Best for KDD. |
| Code executor | DEFERRED | Examine KDD tasks first. May not be needed. |
| Test specs | Required per wave (5A) | TDD discipline. Tests are cheapest lake to boil. |
| Competitive strategy | Reliability > accuracy | 40/50 complete beats 15/50 brilliant (DABstep: best = 14.55% on hard) |

## Key Files to Read First
1. **Design doc:** `~/.gstack/projects/surahli123-search-metric-analyzer/surahli-main-design-20260322-194713.md`
2. **Architecture rules:** `.claude/rules/02-architecture-boundaries.md`
3. **Orchestrator:** `harness/orchestrator.py` (417 LOC — the main refactor target)
4. **Seam validator:** `contracts/seam_validator.py` (776 LOC — 17 rules to split)
5. **Stage contracts:** `contracts/understand.py`, `contracts/hypothesize.py`, etc. (5 files with domain-specific TypedDicts)

## Gotchas
- **Contracts are 5 separate files**, not one `stage_contracts.py` — the design doc was corrected
- **`srm_check` in seam_validator is A/B-test-specific** — verify against KDD tasks before classifying as "generic"
- **Wave 7B code_executor is still mentioned in the design doc** but was deferred — ignore it
- **DuckDB CSV auto-detection can fail on messy data** — test against actual KDD CSVs, add error handling
- **Budget is ~2,000-3,000 full investigations** (not 12,500 — each investigation makes 4-6 LLM calls)

## Working Models (verified 2026-03-22)
| Model | ID | Pipeline Status |
|-------|----|-----------------|
| DeepSeek V3.2 | `deepseek/deepseek-v3.2` | 6/6 PASS |
| Qwen3 235B | `qwen/qwen3-235b-a22b-instruct-2507` | 6/6 PASS |
| GPT-OSS 120B | `openai/gpt-oss-120b` | Untested in pipeline |
| Kimi K2 | `moonshotai/kimi-k2-instruct` | Untested in pipeline |
