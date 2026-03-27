"""Tests for core/sql_executor.py.

Uses real KDD demo data at data/kdd_tasks/demo_samples/input/ to verify
both the SQLite and DuckDB paths against actual files — not mocks.

Test structure mirrors the module structure:
  TestSQLiteMode     — happy path, write blocking, row limits, missing files
  TestDuckDBMode     — CSV registration, multi-table joins, missing files
  TestInputValidation — query validation and mutual-exclusion checks

All tests are relative to the project root (the pytest working directory is
set to the project root via conftest.py / pytest.ini).
"""

import pytest
from core.sql_executor import execute_sql

# ---------------------------------------------------------------------------
# Paths to real KDD demo data — these must exist for the tests to run.
# If you're getting FileNotFoundError here, check that the demo_samples
# archive has been unpacked into data/kdd_tasks/.
# ---------------------------------------------------------------------------

# task_145: event.db (SQLite, single "event" table, 42 rows)
#           attendance.csv (two columns: link_to_event, link_to_member)
TASK_145_EVENT_DB = "data/kdd_tasks/demo_samples/input/task_145/context/db/event.db"
TASK_145_ATTENDANCE_CSV = "data/kdd_tasks/demo_samples/input/task_145/context/csv/attendance.csv"

# task_64: superpower.csv + hero_power.csv (two tables for join/multi-CSV test)
TASK_64_SUPERPOWER_CSV = "data/kdd_tasks/demo_samples/input/task_64/context/csv/superpower.csv"
TASK_64_HERO_POWER_CSV = "data/kdd_tasks/demo_samples/input/task_64/context/csv/hero_power.csv"


# ===========================================================================
# SQLite mode
# ===========================================================================

class TestSQLiteMode:

    def test_query_sqlite_db(self):
        """Basic query: fetch 3 rows from the event table and check columns."""
        result = execute_sql(
            "SELECT event_id, type FROM event LIMIT 3",
            db_path=TASK_145_EVENT_DB,
        )
        assert result["error"] is None, f"Unexpected error: {result['error']}"
        assert result["row_count"] == 3
        # Columns should match the SELECT clause
        assert "event_id" in result["columns"]
        assert "type" in result["columns"]
        # Every row should be a dict with those two keys
        for row in result["rows"]:
            assert "event_id" in row
            assert "type" in row

    def test_blocks_write_query_drop(self):
        """DROP TABLE should be blocked before touching the database."""
        result = execute_sql(
            "DROP TABLE event",
            db_path=TASK_145_EVENT_DB,
        )
        assert result["error"] is not None
        # The error message should make it clear this was a write-block
        error_lower = result["error"].lower()
        assert "write" in error_lower or "blocked" in error_lower, (
            f"Expected 'write' or 'blocked' in error, got: {result['error']}"
        )

    def test_blocks_write_query_insert(self):
        """INSERT should also be blocked."""
        result = execute_sql(
            "INSERT INTO event VALUES ('x', 'y', 'z', 'a', 'b', 'c', 'd')",
            db_path=TASK_145_EVENT_DB,
        )
        assert result["error"] is not None
        error_lower = result["error"].lower()
        assert "write" in error_lower or "blocked" in error_lower

    def test_max_rows_limit(self):
        """max_rows=2 should return at most 2 rows and set truncated=True.

        The event table has 42 rows, so a SELECT * will always exceed 2.
        """
        result = execute_sql(
            "SELECT * FROM event",
            db_path=TASK_145_EVENT_DB,
            max_rows=2,
        )
        assert result["error"] is None, f"Unexpected error: {result['error']}"
        assert result["row_count"] <= 2
        assert result["truncated"] is True

    def test_no_truncation_when_under_limit(self):
        """When results fit within max_rows, truncated should be False."""
        # Fetch exactly 3 rows with LIMIT 3 — well under default max_rows=1000
        result = execute_sql(
            "SELECT * FROM event LIMIT 3",
            db_path=TASK_145_EVENT_DB,
        )
        assert result["error"] is None
        assert result["truncated"] is False
        assert result["row_count"] == 3

    def test_nonexistent_db_returns_error(self):
        """Missing .db file should return a descriptive error, not raise."""
        result = execute_sql(
            "SELECT 1",
            db_path="nonexistent/path/file.db",
        )
        assert result["error"] is not None
        assert result["row_count"] == 0
        assert result["rows"] == []

    def test_result_shape_is_always_complete(self):
        """Every success result must have all five expected keys."""
        result = execute_sql(
            "SELECT * FROM event LIMIT 1",
            db_path=TASK_145_EVENT_DB,
        )
        for key in ("columns", "rows", "row_count", "truncated", "error"):
            assert key in result, f"Missing key '{key}' in result"

    def test_all_columns_present_in_select_star(self):
        """SELECT * should return all 7 columns defined in the event table schema."""
        result = execute_sql(
            "SELECT * FROM event LIMIT 1",
            db_path=TASK_145_EVENT_DB,
        )
        assert result["error"] is None
        # Known schema: event_id, event_name, event_date, type, notes, location, status
        expected_columns = {"event_id", "event_name", "event_date", "type",
                            "notes", "location", "status"}
        assert set(result["columns"]) == expected_columns


# ===========================================================================
# DuckDB mode
# ===========================================================================

class TestDuckDBMode:

    def test_query_single_csv(self):
        """Query attendance.csv registered as the 'attendance' table."""
        result = execute_sql(
            "SELECT * FROM attendance LIMIT 5",
            csv_paths=[TASK_145_ATTENDANCE_CSV],
        )
        assert result["error"] is None, f"Unexpected error: {result['error']}"
        assert result["row_count"] == 5
        # attendance.csv has columns: link_to_event, link_to_member
        assert "link_to_event" in result["columns"]
        assert "link_to_member" in result["columns"]

    def test_table_name_is_csv_stem(self):
        """The table name must match the CSV filename stem (no extension)."""
        # Querying "attendance" should work; querying "attendance.csv" should fail
        result_correct = execute_sql(
            "SELECT * FROM attendance LIMIT 1",
            csv_paths=[TASK_145_ATTENDANCE_CSV],
        )
        assert result_correct["error"] is None

        result_wrong = execute_sql(
            'SELECT * FROM "attendance.csv" LIMIT 1',
            csv_paths=[TASK_145_ATTENDANCE_CSV],
        )
        # This should fail — the table is named "attendance", not "attendance.csv"
        assert result_wrong["error"] is not None

    def test_multiple_csv_files(self):
        """Register two CSVs and query one of them."""
        result = execute_sql(
            "SELECT COUNT(*) AS cnt FROM superpower",
            csv_paths=[TASK_64_SUPERPOWER_CSV, TASK_64_HERO_POWER_CSV],
        )
        assert result["error"] is None, f"Unexpected error: {result['error']}"
        assert result["row_count"] == 1
        assert result["rows"][0]["cnt"] > 0  # superpower.csv has 167 rows

    def test_aggregate_across_csv(self):
        """COUNT(*) on the hero_power table should return a single-row result."""
        result = execute_sql(
            "SELECT COUNT(*) AS total FROM hero_power",
            csv_paths=[TASK_64_HERO_POWER_CSV],
        )
        assert result["error"] is None
        assert result["row_count"] == 1
        assert result["rows"][0]["total"] > 0

    def test_nonexistent_csv_returns_error(self):
        """Missing CSV file should return a descriptive error, not raise."""
        result = execute_sql(
            "SELECT * FROM foo",
            csv_paths=["nonexistent/file.csv"],
        )
        assert result["error"] is not None
        assert result["row_count"] == 0

    def test_max_rows_duckdb(self):
        """max_rows should work the same way in DuckDB mode."""
        # attendance.csv has 326 data rows — SELECT * will exceed max_rows=3
        result = execute_sql(
            "SELECT * FROM attendance",
            csv_paths=[TASK_145_ATTENDANCE_CSV],
            max_rows=3,
        )
        assert result["error"] is None
        assert result["row_count"] <= 3
        assert result["truncated"] is True


# ===========================================================================
# Input validation
# ===========================================================================

class TestInputValidation:

    def test_no_data_source_returns_error(self):
        """Calling execute_sql with neither db_path nor csv_paths should fail."""
        result = execute_sql("SELECT 1")
        assert result["error"] is not None
        # The error should hint at what's missing
        assert "db_path" in result["error"] or "csv_paths" in result["error"] or \
               "data source" in result["error"].lower()

    def test_both_db_and_csv_returns_error(self):
        """Passing both db_path and csv_paths is ambiguous — should fail."""
        result = execute_sql(
            "SELECT 1",
            db_path="some.db",
            csv_paths=["some.csv"],
        )
        assert result["error"] is not None

    def test_empty_query_returns_error(self):
        """An empty or whitespace-only query should fail before touching any data."""
        result = execute_sql("   ", db_path=TASK_145_EVENT_DB)
        assert result["error"] is not None

    def test_blocked_keywords_comprehensive(self):
        """All write keywords should be blocked regardless of casing."""
        write_keywords = [
            "INSERT", "UPDATE", "DELETE", "DROP",
            "CREATE", "ALTER", "TRUNCATE",
            # Check mixed case too
            "Insert", "update", "Delete",
        ]
        for keyword in write_keywords:
            result = execute_sql(
                f"{keyword} INTO something VALUES (1)",
                db_path=TASK_145_EVENT_DB,
            )
            assert result["error"] is not None, (
                f"Expected {keyword} to be blocked, but got no error"
            )
            error_lower = result["error"].lower()
            assert "write" in error_lower or "blocked" in error_lower, (
                f"Expected 'write' or 'blocked' in error for {keyword}, "
                f"got: {result['error']}"
            )

    def test_error_result_has_correct_shape(self):
        """Every error path must return the same five-key shape (not raise)."""
        result = execute_sql("SELECT 1")  # No data source — triggers validation error
        for key in ("columns", "rows", "row_count", "truncated", "error"):
            assert key in result, f"Missing key '{key}' in error result"
        # Safe defaults on error
        assert result["columns"] == []
        assert result["rows"] == []
        assert result["row_count"] == 0
        assert result["truncated"] is False
        assert result["error"] is not None
