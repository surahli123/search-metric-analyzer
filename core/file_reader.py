"""
core/file_reader.py — Universal file reader for KDD task context data.

WHY this exists:
KDD Cup 2026 tasks come with context data in many formats — CSV tables, JSON records,
SQLite databases, markdown knowledge docs, and plain text. The domain agent needs a
single tool that can hand it any file and get back structured, consistently-shaped
content without format-specific glue code scattered across the codebase.

Design principles:
- Auto-detect format from file extension (no caller guessing)
- Always return the same dict shape — format, path, content, size_bytes, truncated, error
- Large-file safe: CSV is streamed line-by-line, text is truncated before returning
- Stdlib only (csv, json, sqlite3, pathlib) — no external dependencies

Supported formats:
  .csv           → columns + first max_rows rows (streaming, never loads full file)
  .json          → parsed JSON, optionally truncated repr if huge
  .db / .sqlite  → table schema (CREATE TABLE) + row counts, read-only connection
  .md            → markdown text, truncated to max_chars
  .txt           → plain text, truncated to max_chars
  (anything else) → treated as text (best-effort read, falls back to "unknown" on decode error)
"""

import csv
import json
import os
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_file(path: str, max_rows: int = 500, max_chars: int = 50000) -> dict:
    """Read any supported file and return structured content.

    Auto-detects format from file extension:
    - .csv:         Parse as CSV, return column names + first max_rows rows
    - .json:        Parse as JSON, return structure (truncated if large)
    - .db/.sqlite:  Return schema (CREATE TABLE statements) + row counts per table
    - .md/.txt:     Return text content (truncated to max_chars)

    Args:
        path:      Path to the file to read.
        max_rows:  Max rows to return for tabular data (CSV). Default 500.
        max_chars: Max characters to return for text/JSON files. Default 50 000.

    Returns:
        dict with keys:
          format     — "csv" | "json" | "sqlite" | "markdown" | "text" | "unknown"
          path       — the input path as given
          content    — format-specific payload (see module docstring)
          size_bytes — file size in bytes, or 0 if the file couldn't be stat-ed
          truncated  — True if content was cut short due to max_rows / max_chars
          error      — None on success; human-readable string on failure

    Content shapes by format:
        csv:      {"columns": [...], "rows": [{...}, ...], "row_count": int, "total_rows": int}
        json:     {"data": <parsed>, "type": "object" | "array" | "other"}
        sqlite:   {"tables": [{"name": str, "schema": str, "row_count": int}, ...]}
        markdown: {"text": str, "line_count": int}
        text:     {"text": str, "line_count": int}
        unknown:  {"text": str, "line_count": int}
    """
    # --- resolve size before we attempt to open ---
    # We do this outside the format dispatchers so every error path can still
    # return size_bytes without duplicating the os.stat() call.
    size_bytes = _safe_stat(path)

    # --- route to the right reader based on extension ---
    suffix = Path(path).suffix.lower()

    if suffix == ".csv":
        return _read_csv(path, max_rows, size_bytes)
    elif suffix == ".json":
        return _read_json(path, max_chars, size_bytes)
    elif suffix in (".db", ".sqlite"):
        return _read_sqlite(path, size_bytes)
    elif suffix == ".md":
        return _read_text(path, max_chars, size_bytes, fmt="markdown")
    elif suffix == ".txt":
        return _read_text(path, max_chars, size_bytes, fmt="text")
    else:
        # Unknown extension — try reading as text (most permissive fallback).
        # This handles .tsv, .log, config files, etc. that appear in some tasks.
        return _read_text(path, max_chars, size_bytes, fmt="text")


# ---------------------------------------------------------------------------
# Format-specific readers
# ---------------------------------------------------------------------------

def _read_csv(path: str, max_rows: int, size_bytes: int) -> dict:
    """Stream a CSV file, returning the first max_rows rows.

    WHY streaming: KDD task CSVs can be large. Loading everything into memory
    just to return 500 rows is wasteful. We iterate once to capture rows, then
    continue iterating (discarding data) to count totals — one pass, O(1) memory.
    """
    try:
        rows = []
        columns = None
        total_rows = 0

        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            columns = reader.fieldnames or []

            for row in reader:
                total_rows += 1
                if total_rows <= max_rows:
                    # Convert OrderedDict → plain dict for cleaner JSON serialisation
                    rows.append(dict(row))

        row_count = len(rows)
        truncated = total_rows > max_rows

        return _ok(
            fmt="csv",
            path=path,
            content={
                "columns": list(columns),
                "rows": rows,
                "row_count": row_count,
                "total_rows": total_rows,
            },
            size_bytes=size_bytes,
            truncated=truncated,
        )

    except FileNotFoundError:
        return _err(path, "csv", size_bytes, f"File not found: {path}")
    except UnicodeDecodeError as exc:
        return _err(path, "csv", size_bytes, f"Encoding error reading CSV: {exc}")
    except csv.Error as exc:
        return _err(path, "csv", size_bytes, f"CSV parse error: {exc}")


def _read_json(path: str, max_chars: int, size_bytes: int) -> dict:
    """Parse a JSON file.

    WHY truncation check: Some KDD tasks ship JSON files with tens of thousands
    of records. We truncate the repr before returning so callers don't
    accidentally embed a 10 MB dict into a prompt.

    WHY size guard: json.load() materializes the entire file in memory twice
    (raw string + Python objects). For files much larger than max_chars, we
    skip full parsing and return a raw-text preview instead. This bounds
    memory to ~max_chars rather than the full file size.
    """
    # Size guard: if the file is much larger than max_chars, don't bother
    # parsing — just return a raw text preview. The 4x multiplier accounts
    # for JSON's overhead (quotes, braces, whitespace) vs. data content.
    _MAX_PARSE_BYTES = max(max_chars * 4, 1_000_000)  # at least 1 MB

    try:
        if size_bytes > _MAX_PARSE_BYTES:
            # File too large to parse safely — return raw text preview
            with open(path, encoding="utf-8") as fh:
                preview = fh.read(max_chars)
            return _ok(
                fmt="json",
                path=path,
                content={
                    "data": preview,
                    "type": "large_file_preview",
                    "note": f"File is {size_bytes:,} bytes — showing first {max_chars:,} chars as text",
                },
                size_bytes=size_bytes,
                truncated=True,
            )

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        # Classify top-level type so callers can decide how to iterate
        if isinstance(data, dict):
            json_type = "object"
        elif isinstance(data, list):
            json_type = "array"
        else:
            json_type = "other"

        # Check if the full repr would exceed max_chars
        # We use repr() here as a cheap size proxy — callers will re-serialise anyway
        full_repr = json.dumps(data, ensure_ascii=False)
        truncated = len(full_repr) > max_chars

        if truncated:
            # Truncate arrays to keep the first N items; truncate objects to first N keys.
            # This preserves structure rather than doing a raw string slice.
            if isinstance(data, list):
                # Binary search would be clever but overkill — just slice and check
                data = _truncate_json_list(data, max_chars)
            elif isinstance(data, dict):
                data = _truncate_json_dict(data, max_chars)
            # For "other" (scalar, bool, etc.) truncation doesn't apply meaningfully

        return _ok(
            fmt="json",
            path=path,
            content={"data": data, "type": json_type},
            size_bytes=size_bytes,
            truncated=truncated,
        )

    except FileNotFoundError:
        return _err(path, "json", size_bytes, f"File not found: {path}")
    except json.JSONDecodeError as exc:
        return _err(path, "json", size_bytes, f"JSON parse error: {exc}")
    except UnicodeDecodeError as exc:
        return _err(path, "json", size_bytes, f"Encoding error reading JSON: {exc}")


def _read_sqlite(path: str, size_bytes: int) -> dict:
    """Return schema and row counts for every table in a SQLite database.

    WHY read-only URI: We never want the file_reader to accidentally create a
    WAL file or modify a database that belongs to a KDD task fixture. The
    `?mode=ro` URI flag ensures sqlite3 opens in read-only mode.

    WHY schema + row count (not data): The domain agent uses this to understand
    *structure* before deciding which SQL query to run via sql_executor.py. Dumping
    rows here would duplicate what sql_executor does and blow the context budget.
    """
    try:
        # Use URI mode for read-only access.
        # file: prefix + ?mode=ro → raises OperationalError if file doesn't exist.
        uri = f"file:{path}?mode=ro"
        con = sqlite3.connect(uri, uri=True)

        try:
            cur = con.cursor()

            # Fetch all user-defined tables (exclude sqlite internal tables
            # like sqlite_sequence, sqlite_stat1, etc.)
            cur.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            rows = cur.fetchall()

            tables = []
            for table_name, create_sql in rows:
                # Row count — cheap full-table scan but necessary for context
                cur.execute(f"SELECT COUNT(*) FROM [{table_name}]")  # brackets handle reserved-word names
                (row_count,) = cur.fetchone()

                tables.append({
                    "name": table_name,
                    "schema": create_sql or "",  # sql can be None for auto-created tables
                    "row_count": row_count,
                })

        finally:
            con.close()

        return _ok(
            fmt="sqlite",
            path=path,
            content={"tables": tables},
            size_bytes=size_bytes,
            truncated=False,  # Schema + counts are always complete — nothing is omitted
        )

    except FileNotFoundError:
        return _err(path, "sqlite", size_bytes, f"File not found: {path}")
    except sqlite3.OperationalError as exc:
        # Covers: file not found via URI, locked db, corrupt db
        return _err(path, "sqlite", size_bytes, f"SQLite error: {exc}")
    except sqlite3.Error as exc:
        return _err(path, "sqlite", size_bytes, f"SQLite error: {exc}")


def _read_text(path: str, max_chars: int, size_bytes: int, fmt: str) -> dict:
    """Read a text file (markdown, plain text, or unknown extension).

    WHY we count lines before truncating: line_count tells the caller how large
    the original document is, so it can decide if the truncated view is representative.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()

        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        truncated = len(text) > max_chars

        if truncated:
            text = text[:max_chars]

        return _ok(
            fmt=fmt,
            path=path,
            content={"text": text, "line_count": line_count},
            size_bytes=size_bytes,
            truncated=truncated,
        )

    except FileNotFoundError:
        return _err(path, fmt, size_bytes, f"File not found: {path}")
    except UnicodeDecodeError:
        # Binary file masquerading as text (e.g. a .dat with unknown extension).
        # Return a minimal error result — don't crash.
        return _err(path, "unknown", size_bytes, f"Cannot read file as text (binary or unknown encoding): {path}")


# ---------------------------------------------------------------------------
# JSON truncation helpers
# ---------------------------------------------------------------------------

def _truncate_json_list(data: list, max_chars: int) -> list:
    """Return a prefix of a JSON list that fits within max_chars when serialised.

    WHY iterative approach: binary search would be O(log n * n) with json.dumps
    inside the loop. For lists up to ~10k items a simple forward walk is fast enough
    and much easier to reason about.
    """
    acc = []
    running = 2  # account for "[]"
    for item in data:
        item_json = json.dumps(item, ensure_ascii=False)
        # +2 for ", " separator
        if running + len(item_json) + 2 > max_chars:
            break
        acc.append(item)
        running += len(item_json) + 2
    return acc


def _truncate_json_dict(data: dict, max_chars: int) -> dict:
    """Return a prefix of a JSON dict (first N keys) that fits within max_chars."""
    acc = {}
    running = 2  # account for "{}"
    for key, value in data.items():
        pair_json = json.dumps({key: value}, ensure_ascii=False)[1:-1]  # strip outer {}
        if running + len(pair_json) + 2 > max_chars:
            break
        acc[key] = value
        running += len(pair_json) + 2
    return acc


# ---------------------------------------------------------------------------
# Result helpers — ensure consistent shape
# ---------------------------------------------------------------------------

def _ok(fmt: str, path: str, content: dict, size_bytes: int, truncated: bool) -> dict:
    """Build a successful result dict."""
    return {
        "format": fmt,
        "path": path,
        "content": content,
        "size_bytes": size_bytes,
        "truncated": truncated,
        "error": None,
    }


def _err(path: str, fmt: str, size_bytes: int, message: str) -> dict:
    """Build an error result dict.

    WHY we still return format + size_bytes on error: callers may want to log
    what format was *attempted* and how large the file was, even when reading fails.
    """
    return {
        "format": fmt,
        "path": path,
        "content": {},
        "size_bytes": size_bytes,
        "truncated": False,
        "error": message,
    }


def _safe_stat(path: str) -> int:
    """Return file size in bytes, or 0 if the file can't be stat-ed."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Usage: python core/file_reader.py path/to/file.csv [max_rows] [max_chars]
    # Output: JSON to stdout — designed to be piped into jq or read by the agent
    if len(sys.argv) < 2:
        print("Usage: python core/file_reader.py <path> [max_rows] [max_chars]", file=sys.stderr)
        sys.exit(1)

    _path = sys.argv[1]
    _max_rows = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    _max_chars = int(sys.argv[3]) if len(sys.argv) > 3 else 50000

    result = read_file(_path, max_rows=_max_rows, max_chars=_max_chars)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
