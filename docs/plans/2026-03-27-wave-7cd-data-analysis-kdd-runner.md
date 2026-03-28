# Wave 7C/7D: Data Analysis Domain + KDD Runner

**Date:** 2026-03-27
**Status:** Eng-reviewed — ready for implementation
**Depends on:** Wave 7A/7B (PR #28, merged)

## 1. Goal

Validate the Domain Plugin Architecture by building a second domain (`data_analysis`) and running it against 50 KDD Cup 2026 demo tasks. Target: 40/50 completion, 15/50 accuracy.

## 2. Architecture

Reuse the existing 4-stage pipeline with reinterpreted stages:

```
QUESTION_PARSE → UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE
                 (read schema)  (plan SQL)   (run SQL)  (format answer)
```

### Stage Mapping

| Stage | Search Metrics (existing) | Data Analysis (new) |
|-------|--------------------------|---------------------|
| UNDERSTAND | Parse metric context, detect direction | Read knowledge.md + discover data schemas |
| HYPOTHESIZE | Generate root-cause hypotheses | Plan 1-3 SQL approaches to answer the question |
| DISPATCH | Investigate each hypothesis via agents | Execute best SQL plan via sql_executor/file_reader |
| SYNTHESIZE | Write diagnosis report | Format answer to match gold.csv output format |

### Key Differences from SearchMetricsDomain

| Concern | SearchMetricsDomain | DataAnalysisDomain |
|---------|--------------------|--------------------|
| Knowledge | 6 YAML routing table | Single knowledge.md per task (passed at runtime) |
| Prompts | Search diagnosis prompts | Text-to-SQL prompts |
| Quality rules | 4 search-specific rules | 2 lightweight rules (non-empty output, answer format) |
| Agents | 10 agent .md files | None — LLM path only |
| Mode selection | Simple/Medium/Complex | Always Medium (sequential pipeline) |

## 3. Wave 7C — `domains/data_analysis/`

### 3.1 DataAnalysisDomain class

```python
class DataAnalysisDomain:
    name = "data_analysis"

    def __init__(self, knowledge_path: str = "", context_files: dict = None):
        """
        Args:
            knowledge_path: Path to the task's knowledge.md file.
            context_files: Dict of discovered data files:
                {"csv": [...], "db": [...], "json": [...], "md": [...]}
        """
```

Unlike SearchMetricsDomain (which is stateless — all knowledge comes from YAML files on disk), DataAnalysisDomain is **task-scoped** — it receives the task's knowledge path and context files at construction time. A new instance is created per task.

### 3.2 DomainInterface Methods

**`parse_question(raw_question)`**
- Returns `{"question_type": "data_analysis", "raw_question": raw_question}`
- No NLP extraction needed — questions are self-contained

**`get_prompts(stage)`**
- Returns dict of prompt builder callables per stage
- Prompt builders accept the pipeline context and return formatted strings
- HYPOTHESIZE prompt: "Given this schema and question, plan SQL approaches"
- DISPATCH prompt: "Execute the SQL using sql_executor. Return the query result."
- SYNTHESIZE prompt: "Format the answer as CSV (header + values)"

**`get_quality_rules()`**
- `rule_answer_not_empty`: Synthesis must contain a non-empty answer
- `rule_answer_format_valid`: Answer must be parseable as CSV-like output

**`get_knowledge(query, stage, token_budget)`**
- Reads and returns the content of `self.knowledge_path`
- `stage` and `token_budget` are accepted but ignored (single-file domain)
- If knowledge_path is empty, returns empty string

**`get_agents()`**
- Returns `{"registry": {}, "agents_dir": ""}` — no agents for data analysis

### 3.3 Prompts (`domains/data_analysis/prompts.py`)

Three stage prompt builders:

**hypothesize_prompts:**
- system: "You are a data analyst. Given a question and database schema, plan SQL queries."
- user: Includes the question, knowledge.md content, and schema summaries from UNDERSTAND

**dispatch_prompts:**
- system: "Execute the SQL plan. Use the provided tool results."
- user: Includes the SQL plan from HYPOTHESIZE and available data file paths

**synthesize_prompts:**
- system: "Format the query result as a final answer in CSV format (header row + data rows)."
- user: Includes the raw query result from DISPATCH and the original question

### 3.4 Files

```
domains/data_analysis/
    __init__.py      — DataAnalysisDomain class (~120 lines)
    prompts.py       — Stage prompt builders (~80 lines)
tests/
    test_data_analysis_domain.py  — Protocol conformance + unit tests (~100 lines)
```

## 4. Wave 7D — `kdd/`

### 4.1 task_loader.py

```python
def load_task(task_dir: str) -> dict:
    """Load a KDD task and discover its context files.

    Args:
        task_dir: Path to task directory (e.g., data/kdd_tasks/demo_samples/input/task_145)

    Returns:
        {
            "task_id": "task_145",
            "difficulty": "medium",
            "question": "...",
            "knowledge_path": "data/.../context/knowledge.md",
            "context_files": {
                "csv": ["data/.../context/csv/attendance.csv"],
                "db": ["data/.../context/db/event.db"],
                "json": [],
                "md": ["data/.../context/knowledge.md"],
            }
        }
    """
```

- Reads `task.json` for metadata
- Walks `context/` to discover files by extension
- Returns a flat dict — no classes needed

### 4.2 runner.py

```python
def run_task(task: dict, llm_callable, verbose: bool = False) -> dict:
    """Run a single KDD task through the pipeline.

    Creates a DataAnalysisDomain scoped to this task, configures the
    orchestrator, and returns the pipeline output.

    Returns:
        {
            "task_id": str,
            "answer": str,        # The predicted answer (CSV-format string)
            "completed": bool,    # Whether the pipeline produced an answer
            "error": str | None,  # Error message if pipeline failed
            "trace": dict | None, # Investigation trace (if available)
        }
    """
```

- Creates `DataAnalysisDomain(knowledge_path=..., context_files=...)`
- Creates `SearchMetricOrchestrator(domain=domain, llm_callable=llm_callable)`
- Calls `orchestrator.run(question=task["question"], rows=schema_rows)`
- Extracts answer from synthesis report

**`run_batch(task_dirs, gold_dir, llm_callable)`** — runs all tasks, returns results + eval summary.

**CLI:**
```bash
# Single task
python -m kdd.runner --task data/kdd_tasks/demo_samples/input/task_145

# Batch (all tasks)
python -m kdd.runner --input-dir data/kdd_tasks/demo_samples/input/ \
                     --gold-dir data/kdd_tasks/demo_samples/output/ \
                     --output results.json
```

### 4.3 evaluator.py

```python
def evaluate(predicted: str, gold_path: str) -> dict:
    """Compare predicted answer against gold.csv.

    Returns:
        {
            "match": bool,
            "score": float,       # 1.0 if match, 0.0 if not
            "predicted_values": list,
            "gold_values": list,
            "details": str,       # Human-readable comparison
        }
    """
```

Comparison logic:
1. Parse gold.csv with `csv.reader` (handles SQL-expression headers)
2. Parse predicted string as CSV
3. Compare values row-by-row:
   - Try numeric comparison first (float equality within tolerance)
   - Fall back to case-insensitive string comparison
   - Handle single-value vs multi-row cases

### 4.4 Files

```
kdd/
    __init__.py        — empty
    task_loader.py     — load_task() (~50 lines)
    runner.py          — run_task(), run_batch(), CLI (~150 lines)
    evaluator.py       — evaluate() (~80 lines)
tests/
    test_task_loader.py    — discovery tests against real KDD data (~40 lines)
    test_evaluator.py      — comparison logic tests (~60 lines)
```

## 5. UNDERSTAND Stage — Skipped (Eng Review Decision #1)

`stage_understand()` is hard-wired to search metrics (calls `run_decomposition`,
`detect_step_change`, `match_co_movement_pattern`). These crash on KDD data.

**Decision:** Skip UNDERSTAND entirely. The runner builds the context dict directly:
1. Read knowledge.md via `file_reader.read_file()`
2. Read schema of each data file (SQLite schema via file_reader, CSV headers)
3. Build an `understand_result`-like dict with schema info
4. Pass directly to `stage_hypothesize()`

This means the runner is a **2-LLM-call pipeline**:
```
Runner builds context → HYPOTHESIZE (LLM plans SQL) → Runner executes SQL → SYNTHESIZE (LLM formats answer)
```

**Eng Review Decision #2:** Runner calls stage functions directly (not via orchestrator).
The orchestrator's `run()` and `_run_pipeline()` always call `stage_understand()`.

**Eng Review Decision #3:** DISPATCH is deterministic — runner executes `sql_executor`
directly on the SQL plan from HYPOTHESIZE. No LLM call for DISPATCH. Saves cost and
reduces failure modes.

## 6. LLM Integration

Uses the existing `make_openai_llm()` factory from `harness/llm.py`:
- Default: DeepSeek V3.2 via Novita API (~$0.004/task)
- 50 tasks × $0.004 = ~$0.20 total batch cost

## 7. Testing Strategy

- **Unit tests (always run):** Protocol conformance, prompt builders, evaluator logic, task loader with fixtures
- **Integration tests (skip on CI):** Run 2-3 easy tasks end-to-end against real KDD data
- **Batch eval (manual):** Run all 50 tasks, report completion + accuracy

## 8. Success Criteria

| Metric | Target | How to measure |
|--------|--------|----------------|
| Completion rate | 40/50 (80%) | Pipeline produces a non-empty answer |
| Accuracy | 15/50 (30%) | Answer matches gold.csv |
| Cost per task | < $0.01 | Track API spend |
| No regressions | 0 | Full test suite passes |

## 9. Eng Review Decisions

| # | Issue | Decision | Rationale |
|---|-------|----------|-----------|
| 1 | UNDERSTAND is search-specific | Skip UNDERSTAND, runner builds context | stage_understand calls search-only tools that crash on KDD data |
| 2 | Runner can't call orchestrator.run() | Runner calls stage functions directly | orchestrator.run() always calls stage_understand() |
| 3 | DISPATCH tool execution | Runner executes sql_executor directly | Deterministic, no LLM needed, saves cost |
| 4 | Test gaps (12 paths) | Add 8 targeted tests | Evaluator edges + runner error paths are batch-run blockers |

## 10. NOT in scope

- Code executor (deferred, can add via DomainInterface.get_tools())
- Multi-turn SQL refinement (HYPOTHESIZE gets one shot)
- Extreme task optimization (2 doc-only tasks — attempt but don't optimize)
- Auto-registration of DataAnalysisDomain in registry
- Stale data/knowledge/ path fixes (post-merge /document-release)

## 11. Parallelization Strategy

| Lane | Steps | Modules | Depends on |
|------|-------|---------|------------|
| A | Wave 7C: DataAnalysisDomain | domains/data_analysis/, tests/ | — |
| B | task_loader + evaluator | kdd/, tests/ | — |
| C | runner | kdd/runner.py, tests/ | A + B |

Launch A + B in parallel. Merge both. Then C.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 3 arch issues resolved, 8 tests added |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |

**VERDICT:** ENG CLEARED — ready to implement
