"""KDD runner — 2-LLM-call pipeline for data analysis tasks.

Wires together:
  task_loader  -> load task metadata + discover context files
  file_reader  -> read knowledge.md + schema from data files
  sql_executor -> execute SQL planned by the LLM
  evaluator    -> compare predicted answer against gold.csv
  DataAnalysisDomain -> prompt builders for HYPOTHESIZE + SYNTHESIZE

THE PIPELINE (2 LLM calls, no orchestrator):

  1. Load task via task_loader.load_task()
  2. Build schema context from data files (file_reader)
  3. LLM call #1 (HYPOTHESIZE): plan SQL queries using domain prompts
  4. Execute the best SQL approach via sql_executor
  5. LLM call #2 (SYNTHESIZE): format raw SQL results as CSV answer
  6. Return result dict: {task_id, answer, completed, error, trace}

WHY NOT USE stage_hypothesize / stage_synthesize:
The harness stage functions are tightly coupled to SearchMetricsDomain —
they load corrections, run seam validation, emit search-specific trace spans,
and call prompt builders with search-specific signatures. The DataAnalysisDomain
has different prompt signatures (question, knowledge, schema_info instead of
understand_result, corrections, understand_context). Calling the stage functions
would crash or produce nonsensical prompts.

Instead, we call the LLM directly using DataAnalysisDomain's prompt builders.
This is the lightweight "2-LLM-call pipeline" described in the design.

CLI usage:
    # Single task
    python -m kdd.runner --task data/kdd_tasks/demo_samples/input/task_145

    # Batch (with optional gold dir for evaluation)
    python -m kdd.runner --input-dir data/kdd_tasks/demo_samples/input/ \\
                         --gold-dir data/kdd_tasks/demo_samples/output/ \\
                         --output results.json
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Lazy import: duckdb is only needed for _execute_unified (mixed SQLite+CSV).
# Guard the import so kdd.runner can be imported in environments without duckdb
# (e.g., SQLite-only tasks or unit tests with mocks).
try:
    import duckdb
    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False

from kdd.task_loader import load_task
from kdd.evaluator import evaluate
from core.file_reader import read_file
from core.sql_executor import execute_sql
from domains.data_analysis import DataAnalysisDomain
from harness.llm import extract_json
from harness.errors import LLMParseError, LLMRefusalError
from trace.collector import InvestigationTrace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_task(
    task_dir: str,
    llm_callable,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Run a single KDD task through the 2-LLM-call pipeline.

    This is the main entry point. It orchestrates the full pipeline:
    load task -> build context -> LLM plans SQL -> execute SQL -> LLM formats answer.

    Args:
        task_dir: Path to the task directory (must contain task.json + context/).
        llm_callable: Function with signature (prompt: str, system: str, max_tokens: int) -> str.
        verbose: If True, include the full trace dict in the result.
            If False, trace is None (saves memory in batch runs).

    Returns:
        Dict with keys:
          task_id   (str)       — from task.json
          answer    (str)       — the formatted CSV answer
          completed (bool)      — True if pipeline completed without errors
          error     (str|None)  — None on success, error message on failure
          trace     (dict|None) — investigation trace (only when verbose=True)
    """
    # --- Step 0: Load task metadata ---
    task = load_task(task_dir)

    # task_loader returns {"error": "..."} on failure — propagate it
    if "error" in task:
        return _error_result(
            task_id=Path(task_dir).name,
            error=f"Task load failed: {task['error']}",
        )

    task_id = task["task_id"]
    question = task["question"]

    # Create a trace to track the pipeline steps
    trace = InvestigationTrace(question=question)

    try:
        # --- Step 1: Build schema context from data files ---
        # The LLM needs to know the database schema to plan SQL queries.
        # We read each data file's schema (CREATE TABLE for SQLite, headers for CSV).
        knowledge = _read_knowledge(task)
        schema_info = _build_schema_context(task)

        # --- Step 2: Create the domain instance ---
        # DataAnalysisDomain is task-scoped — one instance per task.
        domain = DataAnalysisDomain(
            knowledge_path=task.get("knowledge_path", ""),
            context_files=task.get("context_files"),
        )

        # --- Step 3: LLM call #1 — HYPOTHESIZE (plan SQL) ---
        # Get the prompt builders from the domain, then call the LLM.
        hyp_prompts = domain.get_prompts("hypothesize")
        system_prompt = hyp_prompts["system_prompt"]()
        user_prompt = hyp_prompts["user_prompt"](
            question=question,
            knowledge=knowledge,
            schema_info=schema_info,
        )

        raw_hyp_response = llm_callable(user_prompt, system_prompt, 2000)

        # Parse the JSON plan from the LLM response
        try:
            hyp_result = extract_json(raw_hyp_response)
        except (LLMParseError, LLMRefusalError) as e:
            return _error_result(
                task_id=task_id,
                error=f"HYPOTHESIZE failed: could not parse LLM response as JSON. "
                      f"Preview: {str(raw_hyp_response)[:200]}",
                trace=trace if verbose else None,
            )

        # --- Step 4: Extract the best SQL approach ---
        sql_query = _extract_best_sql(hyp_result)
        if sql_query is None:
            return _error_result(
                task_id=task_id,
                error="HYPOTHESIZE returned no valid SQL approaches.",
                trace=trace if verbose else None,
            )

        # --- Step 5: Execute SQL via sql_executor ---
        # Determine which backend to use: SQLite (.db) or DuckDB (CSV).
        sql_result = _execute_sql_for_task(task, sql_query)

        # --- Step 5b: SQL retry on error ---
        # If the first SQL attempt fails (wrong table name, type mismatch, etc.),
        # feed the error back to the LLM and ask for a corrected query.
        # Single retry only — more retries risk burning API budget on hopeless queries.
        if sql_result["error"]:
            logger.info("SQL failed: %s — retrying with error feedback", sql_result["error"])
            retry_prompt = (
                f"Your SQL query failed with this error:\n"
                f"  {sql_result['error']}\n\n"
                f"Original SQL:\n  {sql_query}\n\n"
                f"AVAILABLE SCHEMA:\n{schema_info}\n\n"
                f"Fix the SQL query. Common issues:\n"
                f"- Wrong table name (use ONLY the tables listed above)\n"
                f"- Type mismatch (use CAST(col AS INTEGER) for comparisons)\n"
                f"- Apostrophe escaping (use '' not \\')\n\n"
                f"Return the same JSON format as before with the corrected SQL."
            )
            try:
                retry_response = llm_callable(retry_prompt, system_prompt, 2000)
                retry_result = extract_json(retry_response)
                retry_sql = _extract_best_sql(retry_result)
                if retry_sql:
                    sql_result = _execute_sql_for_task(task, retry_sql)
            except Exception:
                pass  # Retry failed — fall through to original error handling

        if sql_result["error"]:
            return _error_result(
                task_id=task_id,
                error=f"SQL execution failed: {sql_result['error']}",
                trace=trace if verbose else None,
            )

        # --- Step 6: Format answer ---
        # Codex analysis found that SYNTHESIZE LLM corrupts correct SQL results:
        # it drops rows, rounds numbers, reformats strings, and reshapes output.
        # For small/simple results, bypass SYNTHESIZE entirely and format directly.
        # Only use SYNTHESIZE for complex results that need interpretation.

        rows = sql_result.get("rows", [])
        columns = sql_result.get("columns", [])

        if len(rows) <= 20 and len(columns) <= 5:
            # Simple result — format directly as CSV, skip SYNTHESIZE LLM call.
            # WHY: avoids LLM corruption (rounding, dropping rows, reshaping).
            # The SQL result IS the answer for most KDD tasks.
            # No header row — the evaluator strips headers anyway, and omitting
            # them avoids mismatches with gold's SQL-expression headers
            # (e.g., "COUNT(DISTINCT T1.ID)" vs our "count"). Per Codex analysis.
            lines = []
            for row in rows:
                vals = [str(row.get(c, "")) for c in columns]
                lines.append(",".join(vals))
            answer = "\n".join(lines)
        else:
            # Complex result — use SYNTHESIZE LLM to interpret and format
            query_result_text = _format_sql_result(sql_result)
            syn_prompts = domain.get_prompts("synthesize")
            syn_system = syn_prompts["system_prompt"]()
            syn_user = syn_prompts["user_prompt"](
                question=question,
                query_result=query_result_text,
            )
            raw_syn_response = llm_callable(syn_user, syn_system, 1000)
            answer = _clean_csv_response(raw_syn_response)

        return {
            "task_id": task_id,
            "answer": answer,
            "completed": True,
            "error": None,
            "trace": trace.to_dict() if verbose else None,
        }

    except Exception as e:
        # Catch-all: any unexpected error should not crash the batch runner.
        # We log the full traceback for debugging but return a clean error dict.
        logger.exception("run_task(%s) failed with unexpected error", task_id)
        return _error_result(
            task_id=task_id,
            error=f"Unexpected error: {e}",
            trace=trace if verbose else None,
        )


def run_batch(
    task_dirs: List[str],
    llm_callable,
    gold_dir: str = "",
    verbose: bool = False,
) -> Dict[str, Any]:
    """Run multiple KDD tasks and optionally evaluate against gold answers.

    Catches per-task errors so one failing task doesn't kill the batch.

    Args:
        task_dirs: List of task directory paths.
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
        gold_dir: Optional path to gold answer directory. When provided,
            evaluates each completed task's answer against gold.csv.
            Expected structure: gold_dir/task_XXX/gold.csv
        verbose: If True, include trace in each task result.

    Returns:
        Dict with:
          results  (list[dict]) — one result dict per task (same shape as run_task)
          summary  (dict)       — {total, completed, accuracy (if gold_dir)}
    """
    results = []
    completed_count = 0
    correct_count = 0
    evaluated_count = 0

    for task_dir in task_dirs:
        result = run_task(task_dir, llm_callable, verbose=verbose)
        results.append(result)

        if result["completed"]:
            completed_count += 1

            # Evaluate against gold if gold_dir is provided
            if gold_dir:
                eval_result = _evaluate_against_gold(result, gold_dir)
                if eval_result is not None:
                    result["evaluation"] = eval_result
                    evaluated_count += 1
                    if eval_result.get("match"):
                        correct_count += 1

    summary: Dict[str, Any] = {
        "total": len(task_dirs),
        "completed": completed_count,
    }

    # Only include accuracy when we actually evaluated tasks
    if gold_dir:
        summary["accuracy"] = correct_count / evaluated_count if evaluated_count > 0 else 0.0
        summary["evaluated"] = evaluated_count
        summary["correct"] = correct_count

    return {"results": results, "summary": summary}


# ---------------------------------------------------------------------------
# Internal helpers — schema building
# ---------------------------------------------------------------------------

def _read_knowledge(task: Dict[str, Any]) -> str:
    """Read knowledge.md AND other markdown docs for a task.

    KDD tasks often include domain-specific markdown files (League.md,
    molecule.md, superhero.md, races.md) alongside knowledge.md. These
    contain entity descriptions and context the LLM needs to write
    correct SQL. Codex analysis found 4 tasks (330, 379, 396, 408)
    failing because these docs were invisible to the LLM.

    Returns concatenated text from all markdown files.
    """
    sections = []

    # Primary: knowledge.md (always first)
    knowledge_path = task.get("knowledge_path", "")
    if knowledge_path and os.path.exists(knowledge_path):
        result = read_file(knowledge_path)
        if result.get("error") is None:
            sections.append(result["content"].get("text", ""))

    # Additional: other .md files in context (League.md, molecule.md, etc.)
    # Cap each at 3000 chars to avoid blowing the prompt budget.
    for md_path in task.get("context_files", {}).get("md", []):
        if md_path == knowledge_path:
            continue  # already included above
        if os.path.exists(md_path):
            result = read_file(md_path, max_chars=3000)
            if result.get("error") is None:
                text = result["content"].get("text", "")
                if text:
                    sections.append(
                        f"\n--- {Path(md_path).name} ---\n{text}"
                    )

    return "\n".join(sections)


def _build_schema_context(task: Dict[str, Any]) -> str:
    """Build a schema description string from the task's data files.

    Reads each data file to extract its schema:
    - SQLite .db files: CREATE TABLE statements + row counts
    - CSV files: column headers + first few rows as sample
    - JSON files: structure type + key listing

    This string is injected into the HYPOTHESIZE prompt so the LLM
    knows what tables/columns are available for SQL queries.
    """
    context_files = task.get("context_files", {})
    sections = []

    # SQLite databases — schema is the most useful context
    for db_path in context_files.get("db", []):
        result = read_file(db_path)
        if result["error"]:
            sections.append(f"-- Error reading {db_path}: {result['error']}")
            continue

        tables = result["content"].get("tables", [])
        for table in tables:
            sections.append(
                f"-- Table: {table['name']} ({table['row_count']} rows)\n"
                f"{table['schema']}"
            )

    # CSV files — column headers + a few sample rows give the LLM
    # enough context to write correct column references
    for csv_path in context_files.get("csv", []):
        # Read a small sample (5 rows) for context
        result = read_file(csv_path, max_rows=5)
        if result["error"]:
            sections.append(f"-- Error reading {csv_path}: {result['error']}")
            continue

        content = result["content"]
        table_name = Path(csv_path).stem
        columns = content.get("columns", [])
        rows = content.get("rows", [])
        total_rows = content.get("total_rows", 0)

        # Format as a pseudo-schema so the LLM understands the structure
        col_list = ", ".join(columns)
        sections.append(
            f"-- CSV Table: {table_name} ({total_rows} rows)\n"
            f"-- Columns: {col_list}"
        )

        # Add sample rows so the LLM can see data types and patterns
        if rows:
            sample_lines = []
            for row in rows[:3]:
                vals = [str(row.get(c, "")) for c in columns]
                sample_lines.append(", ".join(vals))
            sections.append(
                f"-- Sample rows:\n-- " + "\n-- ".join(sample_lines)
            )

    # JSON files — structure and keys give the LLM context for tasks
    # that use JSON as a data source (e.g., task_11: Patient.json)
    for json_path in context_files.get("json", []):
        result = read_file(json_path, max_chars=2000)
        if result["error"]:
            sections.append(f"-- Error reading {json_path}: {result['error']}")
            continue

        content = result["content"]
        json_type = content.get("type", "unknown")
        table_name = Path(json_path).stem
        data = content.get("data", {})

        # KDD JSON files have the pattern: {"table": "name", "records": [{...}]}
        # We need to show the RECORD columns, not the outer keys (table, records).
        # Codex analysis found this was causing 9 tasks to fail — the LLM never
        # saw actual column names like "state", "event_name", "publisher_name".
        if json_type == "object" and isinstance(data, dict) and "records" in data:
            # KDD format — extract the real table name and record columns
            real_name = data.get("table", table_name)
            records = data.get("records", [])
            if records and isinstance(records[0], dict):
                col_names = list(records[0].keys())[:20]
                sections.append(
                    f"-- JSON Table: {real_name} ({len(records)} rows)\n"
                    f"-- Columns: {', '.join(col_names)}"
                )
                # Add sample row so LLM can see data types
                if records:
                    sample = ", ".join(str(records[0].get(c, ""))[:30] for c in col_names[:8])
                    sections.append(f"-- Sample: {sample}")
            else:
                sections.append(f"-- JSON: {real_name} ({len(records)} records)")
        elif json_type == "object" and isinstance(data, dict):
            keys = list(data.keys())[:20]
            sections.append(
                f"-- JSON: {table_name} (object, {len(data)} keys)\n"
                f"-- Keys: {', '.join(keys)}"
            )
        elif json_type == "array" and isinstance(data, list):
            sections.append(
                f"-- JSON: {table_name} (array, {len(data)} items)"
            )
            if data and isinstance(data[0], dict):
                keys = list(data[0].keys())[:20]
                sections.append(f"-- Item keys: {', '.join(keys)}")

    if not sections:
        return "(No schema information available)"

    # Build a prominent table summary at the top so the LLM sees
    # all available table names before the detailed schemas.
    # This is the #1 fix for the "table not found" failure mode (50% of errors).
    table_names = []
    for db_path in context_files.get("db", []):
        result = read_file(db_path)
        if result.get("error") is None:
            for table in result["content"].get("tables", []):
                table_names.append(f"  - {table['name']} (from {Path(db_path).name}, {table['row_count']} rows)")
    for csv_path in context_files.get("csv", []):
        stem = Path(csv_path).stem
        table_names.append(f"  - {stem} (from {Path(csv_path).name})")
    for json_path in context_files.get("json", []):
        # Use the real table name from KDD JSON format if available
        try:
            with open(json_path, encoding="utf-8") as _jf:
                _jdata = json.load(_jf)
            real_name = _jdata.get("table", Path(json_path).stem) if isinstance(_jdata, dict) else Path(json_path).stem
        except Exception:
            real_name = Path(json_path).stem
        table_names.append(f"  - {real_name} (from {Path(json_path).name}, JSON)")

    header = "=== AVAILABLE TABLES (use ONLY these names in your SQL) ===\n"
    if table_names:
        header += "\n".join(table_names)
    else:
        header += "  (none)"

    return header + "\n\n=== DETAILED SCHEMAS ===\n\n" + "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Internal helpers — SQL extraction and execution
# ---------------------------------------------------------------------------

def _extract_best_sql(hyp_result) -> Optional[str]:
    """Extract the best SQL query from the HYPOTHESIZE result.

    The hypothesize response has this shape:
    {
        "approaches": [{"description": ..., "sql": ..., "rationale": ...}],
        "best_approach_index": 0,
        "reasoning": "..."
    }

    WHY defensive type handling: LLMs sometimes return a list of approaches
    directly instead of wrapping them in {"approaches": [...]}. We normalize
    both shapes to avoid AttributeError crashes. (Found in v2 batch run.)

    We use best_approach_index if valid, otherwise fall back to the first approach.
    Returns None if no approaches exist or no SQL is found.
    """
    # Normalize: if LLM returned a list directly, wrap it
    if isinstance(hyp_result, list):
        hyp_result = {"approaches": hyp_result, "best_approach_index": 0}
    if not isinstance(hyp_result, dict):
        return None

    approaches = hyp_result.get("approaches", [])
    if not approaches:
        return None

    # Use the LLM's preferred approach
    best_idx = hyp_result.get("best_approach_index", 0)
    if not isinstance(best_idx, int) or best_idx < 0 or best_idx >= len(approaches):
        best_idx = 0  # fallback to first approach

    sql = approaches[best_idx].get("sql", "")
    return sql.strip() if sql and sql.strip() else None


def _execute_sql_for_task(task: Dict[str, Any], sql_query: str, max_rows: int = 1000) -> dict:
    """Execute a SQL query using the appropriate backend for this task.

    Decision logic:
    - ONLY .csv files -> use execute_sql with csv_paths (DuckDB)
    - ONLY .db files -> use execute_sql with db_path (SQLite)
    - BOTH .csv AND .db -> unified DuckDB connection that loads both
      WHY: KDD tasks often require JOINs across CSV and SQLite tables
      (e.g., task_145: event.db + attendance.csv). Neither backend alone
      has all tables. We load everything into one DuckDB connection.

    Returns the sql_executor result dict shape: columns, rows, row_count, truncated, error.
    """
    context_files = task.get("context_files", {})
    db_files = context_files.get("db", [])
    csv_files = context_files.get("csv", [])
    json_files = context_files.get("json", [])

    # Count how many data source types we have
    source_types = sum(1 for s in [db_files, csv_files, json_files] if s)

    if source_types >= 2 or json_files:
        # Unified mode — load ALL sources into one DuckDB connection.
        # WHY json_files always triggers unified: JSON files contain
        # {"table": "name", "records": [...]} that must be loaded as
        # DuckDB tables for SQL queries. The basic execute_sql can't do this.
        return _execute_unified(sql_query, db_files, csv_files, max_rows, json_files)
    elif db_files:
        return execute_sql(query=sql_query, db_path=db_files[0])
    elif csv_files:
        return execute_sql(query=sql_query, csv_paths=csv_files)
    else:
        # Markdown-only tasks (extreme difficulty) — no structured data
        return {
            "columns": ["note"],
            "rows": [{"note": "No structured data files. Answer must come from knowledge.md context."}],
            "row_count": 1,
            "truncated": False,
            "error": None,
        }


def _sqlite_to_duckdb_type(sqlite_type: str) -> str:
    """Map SQLite column type to DuckDB type.

    SQLite types are flexible (any string is valid), but DuckDB needs
    concrete types. We map the common ones and default to VARCHAR for
    anything unknown. This preserves numeric operations on INTEGER/REAL
    columns and date operations on DATE/DATETIME columns.
    """
    t = sqlite_type.upper().strip()
    if t in ("INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT"):
        return "BIGINT"
    elif t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"):
        return "DOUBLE"
    elif t in ("DATE",):
        return "DATE"
    elif t in ("DATETIME", "TIMESTAMP"):
        return "TIMESTAMP"
    elif t in ("BOOLEAN", "BOOL"):
        return "BOOLEAN"
    elif t in ("BLOB",):
        return "BLOB"
    else:
        # TEXT, VARCHAR, CHAR, CLOB, and anything else → VARCHAR
        return "VARCHAR"


def _apply_limit_if_missing(query: str, max_rows: int) -> str:
    """Append LIMIT to a query if it doesn't already have one.

    Inlined from core.sql_executor._apply_limit to avoid importing a private
    function across module boundaries. Same logic: check for "limit" keyword
    (case-insensitive), append max_rows+1 for truncation detection.
    """
    if "limit" not in query.lower():
        return f"{query.rstrip(';')} LIMIT {max_rows + 1}"
    return query


def _execute_unified(
    query: str, db_files: list, csv_files: list, max_rows: int = 1000,
    json_files: list = None,
) -> dict:
    """Load SQLite tables, CSVs, and JSON files into a single DuckDB connection.

    WHY this exists: KDD tasks have mixed data sources (e.g., event.db + attendance.csv
    + gasstations.json) and the LLM generates SQL that JOINs across them. This function
    creates a unified namespace where all sources are queryable as tables.

    Steps:
    1. Create in-memory DuckDB connection
    2. For each .db file: read all tables via sqlite3, create DuckDB tables from data
    3. For each .csv file: register via read_csv_auto
    4. Lock down external access
    5. Execute the query
    """
    _error = lambda msg: {"columns": [], "rows": [], "row_count": 0, "truncated": False, "error": msg}

    if not _HAS_DUCKDB:
        return _error("duckdb is not installed — cannot run unified queries. pip install duckdb")

    # Allowlist: only SELECT/WITH queries
    first_word = query.strip().split()[0].lower() if query.strip() else ""
    if first_word not in ("select", "with"):
        return _error(f"Write operation blocked: '{first_word.upper()}' not allowed.")

    # Max rows to load per table — prevents OOM/hangs on large datasets.
    # Defined here (not inside loops) so both SQLite and JSON loading share it.
    _MAX_LOAD_ROWS = 100_000

    conn = None
    try:
        conn = duckdb.connect()

        # --- Load SQLite tables into DuckDB ---
        for db_path in db_files:
            resolved = Path(db_path).resolve()
            if not resolved.exists():
                continue
            sqlite_conn = None
            try:
                sqlite_conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
                cursor = sqlite_conn.cursor()
                # Get all user tables
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                for (table_name,) in cursor.fetchall():
                    # Get column types via PRAGMA — preserves INTEGER, REAL, DATE, etc.
                    cursor.execute(f"PRAGMA table_info([{table_name}])")
                    col_info = cursor.fetchall()  # (cid, name, type, notnull, dflt, pk)
                    col_names = [c[1] for c in col_info]
                    col_types = [_sqlite_to_duckdb_type(c[2]) for c in col_info]

                    # Check row count first — cap to prevent OOM/hangs on
                    # large tables (task_250: 1.5M rows, task_257: 2M rows).
                    cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
                    row_count = cursor.fetchone()[0]

                    if row_count > _MAX_LOAD_ROWS:
                        logging.info(
                            f"Table {table_name} has {row_count} rows — "
                            f"loading first {_MAX_LOAD_ROWS} only"
                        )
                        cursor.execute(
                            f"SELECT * FROM [{table_name}] LIMIT {_MAX_LOAD_ROWS}"
                        )
                    else:
                        cursor.execute(f"SELECT * FROM [{table_name}]")
                    rows = cursor.fetchall()

                    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', table_name)
                    col_defs = ", ".join(
                        f'"{name}" {dtype}' for name, dtype in zip(col_names, col_types)
                    )
                    conn.execute(f'CREATE TABLE "{safe_name}" ({col_defs})')
                    if rows:
                        placeholders = ", ".join(["?"] * len(col_names))
                        conn.executemany(
                            f'INSERT INTO "{safe_name}" VALUES ({placeholders})', rows
                        )
            except Exception as e:
                logging.warning(f"Failed to load SQLite {db_path}: {e}")
            finally:
                # Always close SQLite connection to prevent resource leak
                if sqlite_conn is not None:
                    sqlite_conn.close()

        # --- Register CSVs as DuckDB tables ---
        for csv_path in csv_files:
            resolved = Path(csv_path).resolve()
            if not resolved.exists():
                continue
            table_name = re.sub(r'[^a-zA-Z0-9_]', '_', Path(csv_path).stem)
            safe_path = str(resolved).replace("'", "''")
            conn.execute(
                f'CREATE TABLE "{table_name}" AS '
                f"SELECT * FROM read_csv_auto('{safe_path}')"
            )

        # --- Load JSON files as DuckDB tables ---
        # KDD JSON files follow the pattern: {"table": "name", "records": [{...}, ...]}
        # We extract the records array and create a table from it.
        for json_path in (json_files or []):
            resolved = Path(json_path).resolve()
            if not resolved.exists():
                continue
            try:
                with open(resolved, encoding="utf-8") as fh:
                    data = json.load(fh)

                # Extract table name and records from the KDD JSON format
                if isinstance(data, dict) and "records" in data:
                    table_name = re.sub(r'[^a-zA-Z0-9_]', '_',
                                        data.get("table", Path(json_path).stem))
                    records = data["records"]
                elif isinstance(data, dict) and "table" not in data:
                    # Plain dict — use filename as table, wrap as single record
                    table_name = re.sub(r'[^a-zA-Z0-9_]', '_', Path(json_path).stem)
                    records = [data]
                elif isinstance(data, list):
                    table_name = re.sub(r'[^a-zA-Z0-9_]', '_', Path(json_path).stem)
                    records = data
                else:
                    continue

                if records and isinstance(records[0], dict):
                    # Cap JSON records at 100K to prevent OOM on large files
                    if len(records) > _MAX_LOAD_ROWS:
                        logging.info(
                            f"JSON {table_name} has {len(records)} records — "
                            f"loading first {_MAX_LOAD_ROWS} only"
                        )
                        records = records[:_MAX_LOAD_ROWS]
                    col_names = list(records[0].keys())
                    col_defs = ", ".join(f'"{c}" VARCHAR' for c in col_names)
                    conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')
                    placeholders = ", ".join(["?"] * len(col_names))
                    batch = [tuple(str(r.get(c, "")) for c in col_names) for r in records]
                    conn.executemany(
                        f'INSERT INTO "{table_name}" VALUES ({placeholders})', batch
                    )
            except Exception as e:
                logging.warning(f"Failed to load JSON {json_path}: {e}")

        # Lock down external access after loading all data
        conn.execute("SET enable_external_access = false")

        # Apply LIMIT to prevent unbounded scans (matches sql_executor pattern)
        bounded_query = _apply_limit_if_missing(query, max_rows)
        rel = conn.execute(bounded_query)
        raw_rows = rel.fetchmany(max_rows + 1)
        truncated = len(raw_rows) > max_rows
        if truncated:
            raw_rows = raw_rows[:max_rows]

        columns = [desc[0] for desc in rel.description] if rel.description else []
        rows = [dict(zip(columns, row)) for row in raw_rows]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "error": None,
        }
    except Exception as e:
        return _error(f"Unified query error: {e}")
    finally:
        # Always close DuckDB connection to prevent resource leak
        if conn is not None:
            conn.close()


def _format_sql_result(sql_result: dict) -> str:
    """Format sql_executor result as a human-readable string for the LLM.

    The SYNTHESIZE prompt needs the raw query results as text.
    We format as a simple table: column headers + tab-separated values.
    """
    columns = sql_result.get("columns", [])
    rows = sql_result.get("rows", [])

    if not columns or not rows:
        return "(No results returned)"

    # Header row
    lines = ["\t".join(columns)]

    # Data rows — convert each row dict to tab-separated values
    for row in rows:
        vals = [str(row.get(c, "")) for c in columns]
        lines.append("\t".join(vals))

    # Add summary
    lines.append(f"\n({sql_result.get('row_count', 0)} rows returned)")
    if sql_result.get("truncated"):
        lines.append("(Results truncated — more rows available)")

    return "\n".join(lines)


def _clean_csv_response(raw_response: str) -> str:
    """Strip markdown fences and whitespace from the LLM's CSV response.

    LLMs often wrap CSV in ```csv ... ``` fences even when told not to.
    We remove those fences to get the raw CSV content.
    """
    text = raw_response.strip()

    # Remove markdown code fences: ```csv\n...\n``` or ```\n...\n```
    if text.startswith("```"):
        # Find the end of the opening fence line
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        # Remove closing fence
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    return text.strip()


# ---------------------------------------------------------------------------
# Internal helpers — evaluation
# ---------------------------------------------------------------------------

def _evaluate_against_gold(result: Dict[str, Any], gold_dir: str) -> Optional[dict]:
    """Evaluate a completed task result against gold.csv.

    Looks for gold_dir/task_XXX/gold.csv and compares with evaluator.evaluate().
    Returns None if gold file not found (task can't be evaluated).
    """
    task_id = result["task_id"]
    gold_path = os.path.join(gold_dir, task_id, "gold.csv")

    if not os.path.exists(gold_path):
        return None

    return evaluate(predicted=result["answer"], gold_path=gold_path)


# ---------------------------------------------------------------------------
# Internal helpers — result construction
# ---------------------------------------------------------------------------

def _error_result(
    task_id: str,
    error: str,
    trace: Optional[InvestigationTrace] = None,
) -> Dict[str, Any]:
    """Construct a standardized error result dict.

    Using a helper ensures every error path returns the same shape,
    which makes batch processing and downstream consumers predictable.
    """
    return {
        "task_id": task_id,
        "answer": "",
        "completed": False,
        "error": error,
        "trace": trace.to_dict() if trace else None,
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    """CLI entrypoint — supports single task and batch modes.

    Single task:
        python -m kdd.runner --task data/kdd_tasks/demo_samples/input/task_145

    Batch:
        python -m kdd.runner --input-dir data/kdd_tasks/demo_samples/input/ \\
                             --gold-dir data/kdd_tasks/demo_samples/output/ \\
                             --output results.json
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Run KDD data analysis tasks through the 2-LLM-call pipeline.",
        epilog=(
            "Examples:\n"
            "  python -m kdd.runner --task data/kdd_tasks/demo_samples/input/task_145\n"
            "  python -m kdd.runner --input-dir data/kdd_tasks/demo_samples/input/ "
            "--gold-dir data/kdd_tasks/demo_samples/output/ --output results.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Single task mode
    parser.add_argument(
        "--task",
        help="Path to a single task directory.",
    )
    # Batch mode
    parser.add_argument(
        "--input-dir",
        help="Path to directory containing multiple task directories.",
    )
    parser.add_argument(
        "--gold-dir",
        help="Path to gold answer directory (for evaluation).",
    )
    parser.add_argument(
        "--output",
        help="Output file path for batch results JSON.",
    )
    # Shared options
    parser.add_argument(
        "--verbose", action="store_true",
        help="Include investigation traces in output.",
    )
    parser.add_argument(
        "--model", default="",
        help="LLM model name (for make_llm factory). Default reads from env.",
    )

    args = parser.parse_args()

    # Validate: must provide either --task or --input-dir
    if not args.task and not args.input_dir:
        parser.error("Provide either --task (single task) or --input-dir (batch).")

    # Create LLM callable. The CLI always uses a real LLM.
    # Import here so tests don't need API keys installed.
    llm = _make_cli_llm(args.model)

    if args.task:
        # --- Single task mode ---
        result = run_task(args.task, llm, verbose=args.verbose)
        print(json.dumps(result, indent=2, default=str))
        sys.exit(0 if result["completed"] else 1)

    else:
        # --- Batch mode ---
        # Discover all task directories in input-dir
        input_dir = Path(args.input_dir)
        if not input_dir.exists():
            print(json.dumps({"error": f"Input dir not found: {args.input_dir}"}))
            sys.exit(1)

        task_dirs = sorted([
            str(d) for d in input_dir.iterdir()
            if d.is_dir() and (d / "task.json").exists()
        ])

        if not task_dirs:
            print(json.dumps({"error": f"No task directories found in {args.input_dir}"}))
            sys.exit(1)

        result = run_batch(
            task_dirs=task_dirs,
            llm_callable=llm,
            gold_dir=args.gold_dir or "",
            verbose=args.verbose,
        )

        # Output results
        output_text = json.dumps(result, indent=2, default=str)
        if args.output:
            Path(args.output).write_text(output_text)
            print(f"Results written to {args.output}")
            # Print summary to stdout
            print(json.dumps(result["summary"], indent=2))
        else:
            print(output_text)

        sys.exit(0)


def _make_cli_llm(model: str = ""):
    """Create a real LLM callable for CLI usage.

    Uses Novita API (DeepSeek) if NOVITA_API_KEY is set,
    otherwise falls back to Anthropic.

    This is only called from the CLI — tests pass mock LLMs directly.
    """
    # Try Novita (DeepSeek) first — cheaper for batch runs
    novita_key = os.environ.get("NOVITA_API_KEY", "")
    if novita_key:
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=novita_key,
                base_url="https://api.novita.ai/v3/openai",
            )
            model_name = model or "deepseek/deepseek-v3-0324"

            def novita_llm(prompt: str, system: str, max_tokens: int) -> str:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""

            return novita_llm
        except ImportError:
            logger.warning("openai package not installed, falling back to Anthropic")

    # Fallback to Anthropic
    try:
        from harness.llm import make_anthropic_llm
        return make_anthropic_llm(model=model or "claude-sonnet-4-20250514")
    except Exception as e:
        print(f"Error: Could not create LLM callable: {e}", file=sys.stderr)
        print("Set NOVITA_API_KEY or ANTHROPIC_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
