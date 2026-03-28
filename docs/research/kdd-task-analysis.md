# KDD Demo Task Analysis

**Date:** 2026-03-23
**Purpose:** Validate design assumptions for Domain Plugin Architecture before code.

## Dataset Overview

- **Source:** `~/Downloads/demo_samples.zip` (439 MB)
- **Tasks:** 50 total — 15 easy, 23 medium, 10 hard, 2 extreme
- **Extracted to:** `data/kdd_tasks/demo_samples/` (gitignored)

## Task Schema

Every task has identical structure:

```json
{
  "task_id": "task_<id>",
  "difficulty": "easy|medium|hard|extreme",
  "question": "<natural language question>"
}
```

Schema is **consistent across all 50 tasks** — no extra fields, no difficulty-specific variation.

## Data Source Distribution

| Source Type | Count | Notes |
|------------|-------|-------|
| CSV files | 40 | Up to 279MB (Match.csv) |
| JSON files | 37 | Up to 167MB (posts.json) |
| SQLite DBs | 27 | Up to 267MB (postHistory.db) |
| Markdown docs | 15 | Data-as-prose (hard/extreme tasks) |
| knowledge.md | 50 | Universal — every task has one |

**10 files exceed 50MB.** Largest: Match.csv (279MB), postHistory.db (267MB), postHistory.csv (224MB).
These cannot be loaded into LLM context — DuckDB is essential.

**1 task is doc-only** (task_418, extreme). All other 49 tasks have structured data.

## knowledge.md Pattern

Every task includes a `knowledge.md` that acts as a **semantic layer / data dictionary**:
- Entity definitions with field descriptions
- Metric formulas (KPIs)
- Filtering conventions (date formats, admission codes, etc.)
- Example SQL queries (5 per knowledge.md)
- Ambiguity resolution rules

This is analogous to our `metric_definitions.yaml` — domain knowledge that guides interpretation.

## gold.csv Format

**Format varies by task:**

| Task | Gold Format | Rows |
|------|-----------|------|
| task_11 (easy) | Multi-column: `ID,SEX,Diagnosis` | 3 rows |
| task_145 (medium) | SQL expression header: `COUNT(DISTINCT T1.event_id)` | 4 rows of `1` |
| task_250 (medium) | Column name: `PostId` | 1 row: `351` |
| task_330 (hard) | Column names: `home_team_goal,away_team_goal` | 1 row: `1,1` |
| task_418 (extreme) | SQL expression: `COUNT(DISTINCT T1.ID)` | 1 row: `1` |

**Key observation:** Headers can be either column names or SQL expressions.
The evaluator likely uses `pd.read_csv()` and compares values, not exact string match.

## Difficulty Level Patterns

### Easy (15 tasks)
- **Data:** JSON + CSV, small files (<300K)
- **Challenge:** Data lookup + filtering (not complex joins)
- **Example:** "List patients with severe thrombosis" → filter JSON by field value
- **Tool needed:** DuckDB (JSON/CSV querying) or simple file reading

### Medium (23 tasks)
- **Data:** CSV + SQLite + JSON, mixed sources, some large files
- **Challenge:** Text-to-SQL, multi-source joins, aggregation
- **Example:** "How many meetings had >10 attendees?" → JOIN attendance + event tables
- **Tool needed:** DuckDB (CSV + SQLite), file reader for knowledge.md

### Hard (10 tasks)
- **Data:** Large CSVs (up to 279MB) + markdown docs (~10K-128K tokens)
- **Challenge:** Reasoning over unstructured docs + structured data
- **Example:** "Final score for match on Sep 24, 2008?" → query 279MB CSV + read League.md
- **Tool needed:** DuckDB (large CSV), file reader (markdown), LLM reasoning

### Extreme (2 tasks)
- **Data:** Long markdown documents only (no structured data)
- **Challenge:** Extract structured info from narrative prose with distractors
- **Example:** "Patients with abnormal creatinine under 70?" → parse 280K of prose where
  lab values are embedded in paragraphs with deliberate corrections and irrelevant details
  (chess club membership, cafeteria preferences, campus schedules)
- **Tool needed:** File reader (large markdown), LLM long-context reasoning

## Code Executor Decision

### Finding: **DEFER CONFIRMED — no code execution needed**

Evidence:
1. **Zero Python files** exist in any task's context directory
2. The README says easy tasks require "Python execution" — but this describes what
   *competing agents* do, not a task requirement. Our pipeline handles it differently:
   - Easy/Medium: DuckDB queries CSV/JSON/SQLite directly
   - Hard: DuckDB + LLM reads markdown docs
   - Extreme: LLM reads long markdown docs (pure comprehension)
3. All data formats (CSV, JSON, SQLite, markdown) are handled by planned tools:
   - `core/sql_executor.py` (DuckDB) — CSVs, JSONs, SQLite
   - `core/file_reader.py` — markdown docs, JSON files, CSV headers

### Risk: "Competition agents that execute Python achieve higher accuracy"
If our non-code approach plateaus below target accuracy, code_executor can be added in
Wave 7D without architectural changes (just add another tool to DomainInterface.get_tools()).

## Implications for Domain Plugin Architecture

### Validated assumptions:
- DuckDB is the right SQL engine (queries CSV-as-table, handles large files)
- File reader is needed for markdown docs (15 docs across tasks)
- knowledge.md maps cleanly to DomainInterface.get_knowledge()
- No code execution needed for completeness (may help accuracy later)

### New insights:
- **knowledge.md is always present** — the data_analysis domain's get_knowledge()
  should return the task's knowledge.md content (simple file read, not routing table)
- **gold.csv format varies** — evaluator must handle both column-name and SQL-expression headers
- **Extreme tasks are doc-only** — need a strategy for long-document reasoning
  (chunking? or rely on model's 128K+ context window?)
- **Distractors in extreme tasks** — prose contains irrelevant details and deliberate
  corrections ("initially X, corrected to Y"). Agent must track corrections carefully.

## 5 Sampled Tasks Summary

| Task | Difficulty | Data Sources | File Sizes | Question | Gold |
|------|-----------|-------------|-----------|----------|------|
| task_11 | easy | 2 JSON + knowledge.md | ~500K | "Patients with severe thrombosis" | 3 rows (ID, SEX, Diagnosis) |
| task_145 | medium | 1 CSV + 1 SQLite + knowledge.md | ~40K | "Meetings with >10 attendees" | 4 rows (count=1 each) |
| task_250 | medium | 1 JSON + 1 CSV + 1 SQLite + knowledge.md | ~400MB | "Post by slashnick with most answers" | 1 row (PostId=351) |
| task_330 | hard | 1 CSV + 1 doc + knowledge.md | ~279MB | "Score for Sep 24, 2008 match" | 1 row (1,1) |
| task_418 | extreme | 2 docs + knowledge.md | ~365K | "Patients with abnormal creatinine under 70" | 1 row (count=1) |
