#!/usr/bin/env python3
"""SQL execution tool for KDD Cup 2026 data analysis tasks.

This module provides a single entry point — execute_sql() — that can query:
  1. SQLite databases (.db files) in read-only mode
  2. CSV files registered as DuckDB in-memory tables

Design philosophy (same as the rest of core/):
- Pure function: takes query + data sources in, returns a dict out.
- Safety first: write operations are blocked unconditionally.
- Bounded output: max_rows prevents OOM on large SELECT * queries.
- Fail gracefully: errors go into the result dict, never raise to the caller.

Think of this like a query adapter layer in a data pipeline:
- The caller (agent or orchestrator) doesn't need to know if data is SQLite or CSV.
- The adapter normalizes the result into a single consistent format.
- Row-level output is always a list of dicts for easy downstream processing.

Usage (import):
    from core.sql_executor import execute_sql
    result = execute_sql("SELECT * FROM event LIMIT 5",
                         db_path="data/kdd_tasks/.../event.db")

Usage (CLI):
    python core/sql_executor.py --query "SELECT * FROM event LIMIT 5" \\
                                 --db data/kdd_tasks/.../event.db
    python core/sql_executor.py --query "SELECT * FROM attendance LIMIT 5" \\
                                 --csv data/kdd_tasks/.../attendance.csv
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# DuckDB is optional at import time so that the module can still be imported
# in environments where DuckDB isn't installed (e.g., unit tests that only
# exercise the SQLite path). We'll raise a clear error at call time if the
# caller tries to use DuckDB mode without having it installed.
try:
    import duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    _DUCKDB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Write-blocking: allowlist approach
# ---------------------------------------------------------------------------

# Only SELECT and WITH (for CTEs) are allowed as the first keyword.
# An allowlist is safer than a denylist — new DuckDB commands (EXPORT,
# CALL, LOAD, INSTALL, etc.) are blocked by default without us having to
# enumerate every possible write/side-effect keyword.
_ALLOWED_FIRST_KEYWORDS = frozenset({"select", "with"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_sql(
    query: str,
    db_path: str = "",
    csv_paths: list | None = None,
    max_rows: int = 1000,
) -> dict:
    """Execute a SQL query against a SQLite DB or DuckDB-registered CSVs.

    Two modes — exactly one must be provided:
      - SQLite mode: pass db_path pointing to a .db file
      - DuckDB mode: pass csv_paths with one or more CSV file paths

    Args:
        query:     SQL query string. Must start with SELECT (case-insensitive).
        db_path:   Path to a SQLite .db file (mutually exclusive with csv_paths).
        csv_paths: List of CSV paths to register as DuckDB tables. The table
                   name is the filename stem: "attendance.csv" → table "attendance".
        max_rows:  Maximum number of rows to return. Results beyond this limit
                   are silently dropped (truncated=True in the result).

    Returns:
        A dict with keys:
          columns   (list[str])  — column names in order
          rows      (list[dict]) — each row as {column: value, ...}
          row_count (int)        — number of rows actually returned
          truncated (bool)       — True if max_rows was hit and results were cut
          error     (str|None)   — None on success, message string on failure
    """
    # --- Normalise defaults so callers can pass None explicitly ---
    if csv_paths is None:
        csv_paths = []

    # --- Input validation: exactly one data source must be provided ---
    validation_error = _validate_inputs(query, db_path, csv_paths)
    if validation_error:
        return _error_result(validation_error)

    # --- Write-block check ---
    block_error = _check_write_block(query)
    if block_error:
        return _error_result(block_error)

    # --- Dispatch to the right backend ---
    if db_path:
        return _run_sqlite(query, db_path, max_rows)
    else:
        return _run_duckdb(query, csv_paths, max_rows)


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _validate_inputs(query: str, db_path: str, csv_paths: list) -> str | None:
    """Return an error message string if inputs are invalid, else None.

    We want to be explicit about the mode conflict to prevent silent
    failures where the caller passes both and only one is used.
    """
    if not query or not query.strip():
        return "Query must not be empty."

    has_db = bool(db_path and db_path.strip())
    has_csv = bool(csv_paths)

    if has_db and has_csv:
        # Mutual exclusion: passing both is ambiguous — which backend wins?
        return (
            "Provide either db_path (SQLite mode) or csv_paths (DuckDB mode), "
            "not both."
        )

    if not has_db and not has_csv:
        return (
            "No data source provided. Pass db_path for SQLite mode "
            "or csv_paths for DuckDB mode."
        )

    return None


def _check_write_block(query: str) -> str | None:
    """Return an error message if the query doesn't start with an allowed keyword.

    Allowlist approach: only SELECT and WITH (CTEs) are permitted.
    Everything else — INSERT, DROP, EXPORT, CALL, LOAD, etc. — is rejected
    without needing to maintain a denylist of every possible write command.

    Still intentionally simple (first-token check). A determined adversary
    could bypass it, but for a diagnostic tool used by trusted agents this
    is the right balance of safety vs complexity.
    """
    first_word = query.strip().split()[0].lower()
    if first_word not in _ALLOWED_FIRST_KEYWORDS:
        return (
            f"Write operation blocked: '{first_word.upper()}' queries are not "
            f"allowed. Only SELECT queries are permitted in read-only mode."
        )
    return None


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

def _run_sqlite(query: str, db_path: str, max_rows: int) -> dict:
    """Execute query against a SQLite file in read-only mode.

    We use the SQLite URI filename format with ?mode=ro to enforce read-only
    at the file-system level — even if the write-block check above were
    somehow bypassed, SQLite itself will reject writes.

    We also append LIMIT to the query if one isn't already present. This is
    a belt-and-suspenders approach: the write-block prevents most dangerous
    operations, but an unbounded SELECT on a large DB could still OOM.
    """
    # Resolve to absolute path so the URI format works correctly
    resolved = Path(db_path).resolve()

    if not resolved.exists():
        return _error_result(f"Database file not found: {db_path}")

    # SQLite read-only URI: file:path?mode=ro
    # The ?mode=ro parameter tells SQLite to open the file in read-only mode.
    # uri=True tells the Python sqlite3 module to interpret the path as a URI.
    uri = f"file:{resolved}?mode=ro"

    try:
        conn = sqlite3.connect(uri, uri=True)
        # Row factory: sqlite3.Row gives us column-indexed access so we can
        # build {column: value} dicts without a separate description lookup.
        conn.row_factory = sqlite3.Row

        try:
            # Append LIMIT only if the query doesn't already have one.
            # We check case-insensitively so "limit" and "LIMIT" both match.
            bounded_query = _apply_limit(query, max_rows)
            cursor = conn.execute(bounded_query)

            # Fetch max_rows + 1 so we can detect truncation without a second
            # COUNT query. If we get max_rows+1 rows back, the results were cut.
            raw_rows = cursor.fetchmany(max_rows + 1)
            truncated = len(raw_rows) > max_rows
            if truncated:
                raw_rows = raw_rows[:max_rows]

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = [dict(row) for row in raw_rows]

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
                "error": None,
            }
        finally:
            conn.close()

    except sqlite3.OperationalError as e:
        return _error_result(f"SQLite error: {e}")
    except sqlite3.Error as e:
        return _error_result(f"SQLite error: {e}")
    except Exception as e:
        return _error_result(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# DuckDB backend
# ---------------------------------------------------------------------------

def _run_duckdb(query: str, csv_paths: list, max_rows: int) -> dict:
    """Execute query against CSV files registered as DuckDB in-memory tables.

    Each CSV is registered with read_csv_auto(), which infers column types
    automatically — no schema pre-declaration needed. This is the "convention
    over configuration" approach suited to KDD tasks where schema is unknown
    in advance.

    Table naming convention: the stem of the file path becomes the table name.
    E.g., /path/to/attendance.csv → table name "attendance".
    Duplicate stems would collide, but that's an unlikely edge case for the
    KDD demo dataset structure.
    """
    if not _DUCKDB_AVAILABLE:
        return _error_result(
            "DuckDB is not installed. Install it with: pip install duckdb"
        )

    # Validate all CSV files exist before opening the DuckDB connection.
    # This gives a cleaner error than a DuckDB CatalogException.
    for path in csv_paths:
        if not Path(path).exists():
            return _error_result(f"CSV file not found: {path}")

    try:
        # in-memory DuckDB connection — nothing is persisted to disk
        conn = duckdb.connect()

        try:
            # Register each CSV as a named view using read_csv_auto().
            # A VIEW (not a table) keeps data on disk and avoids loading
            # everything into memory — DuckDB will push predicates down to
            # the CSV scan layer.
            for csv_path in csv_paths:
                # Sanitize filename stem → valid SQL identifier.
                # E.g., "my-data (2).csv" → "my_data__2_"
                table_name = re.sub(r'[^a-zA-Z0-9_]', '_', Path(csv_path).stem)
                resolved = Path(csv_path).resolve()
                # We use single quotes around the path and escape any
                # embedded single quotes for safety.
                safe_path = str(resolved).replace("'", "''")
                # Double-quote the table name so reserved words (e.g.,
                # "select.csv" → table "select") don't cause syntax errors.
                conn.execute(
                    f'CREATE VIEW "{table_name}" AS '
                    f"SELECT * FROM read_csv_auto('{safe_path}')"
                )

            bounded_query = _apply_limit(query, max_rows)
            rel = conn.execute(bounded_query)

            raw_rows = rel.fetchmany(max_rows + 1)
            truncated = len(raw_rows) > max_rows
            if truncated:
                raw_rows = raw_rows[:max_rows]

            columns = [desc[0] for desc in rel.description] if rel.description else []
            # DuckDB rows are plain tuples, not sqlite3.Row objects
            rows = [dict(zip(columns, row)) for row in raw_rows]

            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
                "error": None,
            }
        finally:
            conn.close()

    except duckdb.Error as e:
        return _error_result(f"DuckDB error: {e}")
    except Exception as e:
        return _error_result(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _apply_limit(query: str, max_rows: int) -> str:
    """Append LIMIT to a query if it doesn't already have one.

    This is a simple heuristic: check whether the word "limit" appears
    anywhere in the query (case-insensitive). It's not SQL-aware — a query
    with LIMIT inside a subquery would still pass — but for the straightforward
    KDD task queries this is sufficient and avoids a full SQL parser dependency.

    We add max_rows + 1 here so that the fetch layer can detect truncation
    (fetching one extra row tells us whether results were cut without
    a separate COUNT(*) round-trip).
    """
    if "limit" not in query.lower():
        return f"{query.rstrip(';')} LIMIT {max_rows + 1}"
    # If the query already has LIMIT, trust it and don't double-limit.
    # The fetchmany(max_rows+1) call in the caller will still enforce max_rows.
    return query


def _error_result(message: str) -> dict:
    """Construct a standard error result dict.

    Using a helper ensures every error path returns the exact same shape,
    which makes error handling in callers (agents, tests) predictable.
    """
    return {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "error": message,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Execute a read-only SQL query against a SQLite DB or CSV files.",
        epilog=(
            "Examples:\n"
            "  python core/sql_executor.py --query 'SELECT * FROM event LIMIT 5' "
            "--db data/kdd_tasks/.../event.db\n"
            "  python core/sql_executor.py --query 'SELECT * FROM attendance LIMIT 5' "
            "--csv data/kdd_tasks/.../attendance.csv\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", required=True, help="SQL SELECT query to execute.")
    parser.add_argument("--db", default="", help="Path to a SQLite .db file.")
    parser.add_argument(
        "--csv",
        action="append",
        default=[],
        dest="csv_paths",
        help="Path to a CSV file (can be repeated for multiple tables).",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=1000,
        help="Maximum number of rows to return (default: 1000).",
    )

    args = parser.parse_args()

    result = execute_sql(
        query=args.query,
        db_path=args.db,
        csv_paths=args.csv_paths,
        max_rows=args.max_rows,
    )

    # All output goes to stdout as JSON — same pattern as every other core/ tool.
    # Errors also go to stdout (not stderr) so the caller can parse them uniformly.
    print(json.dumps(result, indent=2, default=str))

    # Exit with non-zero status when there's an error so shell scripts can
    # detect failures without having to parse the JSON.
    if result["error"] is not None:
        sys.exit(1)
