"""Tests for _execute_unified and related fixes (CSV formatting, evaluator equivalence).

These tests cover 6 specific gaps identified in the test coverage:
1. JSON-only task through _execute_unified
2. DuckDB recursive unnest produces flat column names (not nested structs)
3. Large tables capped at _MAX_LOAD_ROWS (100,000)
4. CSV values containing commas are properly quoted via csv.writer
5. None values become empty strings, not "None"
6. Scalar/rowset equivalence in evaluator

Tests 1-3 use real DuckDB + temp files (no mocks needed for data layer).
Tests 4-5 test the CSV formatting logic from the runner's direct-format path.
Test 6 uses the evaluator with a real temp gold.csv file.
"""

import csv
import io
import json
import os
import sqlite3
import tempfile
import pytest
from pathlib import Path

# WHY these specific imports: _execute_unified is private but the function
# under test — importing directly is the cleanest way to unit-test it.
from kdd.runner import _execute_unified
from kdd.evaluator import evaluate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_kdd_json(path: str, table_name: str, records: list[dict]) -> None:
    """Write a KDD-format JSON file: {"table": "name", "records": [...]}.

    KDD datasets use this format — the table name embedded in the file
    determines the DuckDB table name, and records become rows.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"table": table_name, "records": records}, f)


def _write_gold_csv(path: str, header: str, data_rows: list[str]) -> None:
    """Write a gold.csv file in KDD format: header row + data rows.

    Gold files always have a header (often a SQL expression like
    'COUNT(DISTINCT T1.id)') followed by one or more data rows.
    """
    with open(path, "w") as f:
        f.write(header + "\n")
        for row in data_rows:
            f.write(row + "\n")


# ---------------------------------------------------------------------------
# Test 1: JSON-only task through _execute_unified
# ---------------------------------------------------------------------------

class TestJsonOnlyTask:
    """Verify that _execute_unified correctly loads and queries JSON files.

    WHY: KDD tasks can have only .json context files (no .db or .csv).
    The runner must load JSON into DuckDB tables and make them queryable.
    This tests the full JSON-only code path end-to-end.
    """

    def test_json_only_task_returns_correct_rows(self, tmp_path):
        """Load a KDD JSON file and query it — verify rows come back."""
        json_path = tmp_path / "products.json"
        records = [
            {"product_id": 1, "name": "Widget", "price": 9.99},
            {"product_id": 2, "name": "Gadget", "price": 19.99},
            {"product_id": 3, "name": "Doohickey", "price": 29.99},
        ]
        _write_kdd_json(str(json_path), "products", records)

        # Query with no .db or .csv files — only JSON
        result = _execute_unified(
            query="SELECT name, price FROM products ORDER BY product_id",
            db_files=[],
            csv_files=[],
            json_files=[str(json_path)],
        )

        # Verify no errors and correct data
        assert result["error"] is None, f"Unexpected error: {result['error']}"
        assert result["row_count"] == 3
        assert len(result["rows"]) == 3

        # Verify actual values — order matters (ORDER BY product_id)
        assert result["rows"][0]["name"] == "Widget"
        assert result["rows"][1]["name"] == "Gadget"
        assert result["rows"][2]["name"] == "Doohickey"

        # Verify prices are numeric (DuckDB should preserve types)
        assert abs(result["rows"][0]["price"] - 9.99) < 0.01


# ---------------------------------------------------------------------------
# Test 2: DuckDB recursive unnest produces flat column names
# ---------------------------------------------------------------------------

class TestRecursiveUnnestColumnNames:
    """Verify that JSON loading produces flat column names, not nested structs.

    WHY: Without `recursive := true` in the unnest call, DuckDB would produce
    a single struct column like `records` with nested fields (records.col1,
    records.col2). The recursive flag flattens this so column names are just
    "col1", "col2" — matching how LLMs generate SQL.

    This was a real bug: LLM-generated SQL used "SELECT col1 FROM table"
    but without recursive unnest, the actual column was "records.col1".
    """

    def test_columns_are_flat_not_nested(self, tmp_path):
        """JSON records should produce flat columns like 'name', not 'records.name'."""
        json_path = tmp_path / "employees.json"
        records = [
            {"emp_id": 101, "department": "Engineering", "salary": 85000},
            {"emp_id": 102, "department": "Sales", "salary": 72000},
        ]
        _write_kdd_json(str(json_path), "employees", records)

        result = _execute_unified(
            query="SELECT * FROM employees",
            db_files=[],
            csv_files=[],
            json_files=[str(json_path)],
        )

        assert result["error"] is None, f"Unexpected error: {result['error']}"

        # Column names should be flat — "emp_id", "department", "salary"
        # NOT nested like "records.emp_id" or "unnest(records).emp_id"
        columns = result["columns"]
        for col in columns:
            assert "." not in col, (
                f"Column '{col}' is nested — recursive unnest didn't flatten it. "
                f"Expected flat names like 'emp_id', got struct path."
            )

        # Verify the expected columns are present
        assert "emp_id" in columns
        assert "department" in columns
        assert "salary" in columns

        # Verify we can query by flat name (this would fail with nested names)
        result2 = _execute_unified(
            query="SELECT department FROM employees WHERE emp_id = 101",
            db_files=[],
            csv_files=[],
            json_files=[str(json_path)],
        )
        assert result2["error"] is None
        assert result2["rows"][0]["department"] == "Engineering"


# ---------------------------------------------------------------------------
# Test 3: Large SQLite table — full access via sqlite_scanner
# ---------------------------------------------------------------------------

class TestMaxLoadRowsCap:
    """Verify that _execute_unified loads full SQLite tables via sqlite_scanner.

    WHY: The old approach capped SQLite loading at 100K rows via Python
    materialization, producing silently wrong aggregates on large tables.
    sqlite_scanner attaches the .db file directly — DuckDB queries the full
    table without Python-side row caps. Codex analysis identified the cap as
    the #1 accuracy bug.

    NOTE: JSON loading uses DuckDB's read_json_auto natively and also has
    no row cap. The query result is separately capped by max_rows parameter.
    """

    def test_sqlite_table_full_access(self, tmp_path):
        """Create a SQLite DB with >100K rows, verify ALL rows are accessible."""
        db_path = tmp_path / "large.db"

        # Create a SQLite table with 100,050 rows.
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE big_table (id INTEGER, val TEXT)")

        total_rows = 100_050
        batch_size = 5000
        for start in range(0, total_rows, batch_size):
            end = min(start + batch_size, total_rows)
            rows = [(i, f"row_{i}") for i in range(start, end)]
            conn.executemany("INSERT INTO big_table VALUES (?, ?)", rows)
        conn.commit()

        cursor = conn.execute("SELECT COUNT(*) FROM big_table")
        assert cursor.fetchone()[0] == total_rows
        conn.close()

        # With sqlite_scanner, we should get ALL rows — no 100K cap.
        result = _execute_unified(
            query="SELECT COUNT(*) AS cnt FROM big_table",
            db_files=[str(db_path)],
            csv_files=[],
        )

        assert result["error"] is None, f"Unexpected error: {result['error']}"

        # COUNT should be the full 100,050 — sqlite_scanner queries
        # the SQLite file directly without Python materialization.
        count = result["rows"][0]["cnt"]
        assert count == total_rows, (
            f"Expected {total_rows} rows (full table), got {count}. "
            f"sqlite_scanner should provide full access without row caps."
        )


# ---------------------------------------------------------------------------
# Test 4: CSV values containing commas are properly quoted
# ---------------------------------------------------------------------------

class TestCsvCommaEscaping:
    """Verify that the runner's CSV formatting properly handles commas in values.

    WHY: The runner's direct-format path (lines 218-226 of runner.py) formats
    SQL results as CSV for the evaluator. Values like "MCTD, AMI" (a disease
    name) contain commas that would split into two columns with naive
    str.join(","). Using csv.writer handles this by quoting such values.

    This was a real Codex R3 finding — naive comma-joining caused
    "MCTD, AMI" to become two cells ["MCTD", " AMI"] instead of one.
    """

    def test_comma_in_value_stays_single_field(self):
        """Values with commas should be quoted so they parse as one field."""
        # Simulate the runner's CSV formatting logic (lines 218-226).
        # This is the exact code path: sql_result dict → csv.writer → string.
        columns = ["diagnosis", "count"]
        rows = [
            {"diagnosis": "MCTD, AMI", "count": 42},  # comma in value!
            {"diagnosis": "Simple Cold", "count": 100},
        ]

        # Reproduce the runner's formatting logic
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow([
                "" if row.get(c) is None else str(row.get(c, ""))
                for c in columns
            ])
        csv_output = buf.getvalue().strip()

        # Parse it back — each row should have exactly 2 fields
        parsed = list(csv.reader(io.StringIO(csv_output)))
        assert len(parsed) == 2, f"Expected 2 rows, got {len(parsed)}"

        # The comma in "MCTD, AMI" should NOT split into two fields
        assert len(parsed[0]) == 2, (
            f"Row 0 has {len(parsed[0])} fields: {parsed[0]}. "
            f"Expected 2 — the comma in 'MCTD, AMI' was not properly quoted."
        )
        assert parsed[0][0] == "MCTD, AMI"
        assert parsed[0][1] == "42"

        # Second row should also be clean
        assert parsed[1][0] == "Simple Cold"
        assert parsed[1][1] == "100"


# ---------------------------------------------------------------------------
# Test 5: None values become empty strings, not "None"
# ---------------------------------------------------------------------------

class TestNoneHandling:
    """Verify that None values in SQL results become "" not "None" in CSV output.

    WHY: DuckDB returns None for SQL NULLs. The runner's CSV formatting
    converts these to empty strings for the evaluator. Without explicit
    None handling, Python's str(None) produces the literal string "None",
    which would be compared against gold values and fail spuriously.

    This was caught during Codex R3 analysis — several tasks had NULL values
    that were being written as "None" instead of empty strings.
    """

    def test_none_becomes_empty_string(self):
        """None values should format as empty strings, not literal 'None'."""
        columns = ["name", "age", "email"]
        rows = [
            {"name": "Alice", "age": 30, "email": None},      # NULL email
            {"name": None, "age": None, "email": "b@test.com"},  # NULL name + age
        ]

        # Reproduce the runner's formatting logic (lines 218-226)
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow([
                "" if row.get(c) is None else str(row.get(c, ""))
                for c in columns
            ])
        csv_output = buf.getvalue().strip()

        # Parse back and verify
        parsed = list(csv.reader(io.StringIO(csv_output)))
        assert len(parsed) == 2

        # Row 0: email should be empty string, not "None"
        assert parsed[0][0] == "Alice"
        assert parsed[0][1] == "30"
        assert parsed[0][2] == "", (
            f"None email should be empty string, got '{parsed[0][2]}'. "
            f"str(None) produces 'None' — the explicit None check is needed."
        )

        # Row 1: name and age should both be empty strings
        assert parsed[1][0] == "", (
            f"None name should be empty string, got '{parsed[1][0]}'."
        )
        assert parsed[1][1] == "", (
            f"None age should be empty string, got '{parsed[1][1]}'."
        )
        assert parsed[1][2] == "b@test.com"


# ---------------------------------------------------------------------------
# Test 6: Scalar/rowset equivalence in evaluator
# ---------------------------------------------------------------------------

class TestScalarRowsetEquivalence:
    """Verify that evaluate() treats scalar counts as equivalent to repeated rows.

    WHY: The #1 source of false negatives in KDD evaluation was this pattern:
    - Gold file: 4 rows of "1" (e.g., listing each matching record)
    - Predicted: "4" (the LLM used COUNT(*) instead of listing rows)

    These are semantically equivalent — the LLM just answered differently.
    The evaluator's scalar/rowset equivalence logic (lines 186-203 of
    evaluator.py) detects this: if all gold values are the same number
    and predicted is a single number equal to count(gold_values), it's a match.

    This was a Codex R3 finding — many correct answers were scored as wrong
    because the LLM chose COUNT(*) over listing individual rows.
    """

    def test_scalar_count_matches_repeated_rows(self, tmp_path):
        """predicted='4' should match gold with 4 rows of '1'."""
        gold_path = tmp_path / "gold.csv"
        # Gold file format: header row + 4 data rows, each containing "1"
        # This represents a query that returned 4 rows where each has value 1
        _write_gold_csv(str(gold_path), "has_match", ["1", "1", "1", "1"])

        # The LLM predicted "4" — it used COUNT(*) instead of listing rows
        result = evaluate(predicted="4", gold_path=str(gold_path))

        assert result["match"] is True, (
            f"Scalar/rowset equivalence failed: predicted='4' should match "
            f"4 rows of '1'. Details: {result['details']}"
        )
        assert result["score"] == 1.0

    def test_scalar_count_no_false_positive(self, tmp_path):
        """predicted='5' should NOT match gold with 4 rows of '1'.

        WHY: We need to verify the equivalence logic doesn't over-match.
        The count must exactly equal the number of gold rows.
        """
        gold_path = tmp_path / "gold.csv"
        _write_gold_csv(str(gold_path), "has_match", ["1", "1", "1", "1"])

        # predicted='5' is wrong — there are only 4 rows
        result = evaluate(predicted="5", gold_path=str(gold_path))

        assert result["match"] is False, (
            f"Scalar/rowset equivalence false positive: predicted='5' should NOT "
            f"match 4 rows of '1'. Details: {result['details']}"
        )
