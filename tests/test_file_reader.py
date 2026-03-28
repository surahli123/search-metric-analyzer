"""
tests/test_file_reader.py — Tests for core/file_reader.py

Two test tiers:
  1. Fixture-based (always run) — small tracked files in tests/fixtures/
  2. KDD-data-based (skip on CI) — real demo data at data/kdd_tasks/demo_samples/

WHY both: Fixtures guarantee CI coverage. KDD data catches encoding quirks,
unusual SQLite schemas, and malformed CSVs that exist in the real dataset.
"""

import glob
import os
import tempfile

import pytest

from core.file_reader import read_file

# ---------------------------------------------------------------------------
# Tracked fixtures (always available — committed to repo)
# ---------------------------------------------------------------------------
_FIXTURE_CSV = "tests/fixtures/csv/events.csv"
_FIXTURE_DB = "tests/fixtures/db/events.db"
_FIXTURE_JSON = "tests/fixtures/json/config.json"
_FIXTURE_MD = "tests/fixtures/knowledge.md"

# ---------------------------------------------------------------------------
# KDD demo data paths (gitignored — only available locally)
# ---------------------------------------------------------------------------
_TASK_145 = "data/kdd_tasks/demo_samples/input/task_145/context"
_TASK_11  = "data/kdd_tasks/demo_samples/input/task_11/context"

_HAS_KDD_DATA = os.path.exists(f"{_TASK_145}/db/event.db")
_skip_no_kdd = pytest.mark.skipif(not _HAS_KDD_DATA, reason="KDD demo data not available")


# ===========================================================================
# Fixture-based tests (always run)
# ===========================================================================

class TestCSVFixture:
    def test_reads_csv(self):
        result = read_file(_FIXTURE_CSV)
        assert result["format"] == "csv"
        assert result["error"] is None
        assert "event_id" in result["content"]["columns"]
        assert len(result["content"]["rows"]) == 5

    def test_csv_max_rows(self):
        result = read_file(_FIXTURE_CSV, max_rows=2)
        assert result["content"]["row_count"] <= 2

    def test_csv_rows_are_dicts(self):
        result = read_file(_FIXTURE_CSV, max_rows=3)
        for row in result["content"]["rows"]:
            assert isinstance(row, dict)


class TestJSONFixture:
    def test_reads_json_object(self):
        result = read_file(_FIXTURE_JSON)
        assert result["format"] == "json"
        assert result["error"] is None
        assert result["content"]["type"] == "object"

    def test_json_has_data(self):
        result = read_file(_FIXTURE_JSON)
        assert "data" in result["content"]


class TestSQLiteFixture:
    def test_reads_sqlite_schema(self):
        result = read_file(_FIXTURE_DB)
        assert result["format"] == "sqlite"
        assert result["error"] is None
        assert len(result["content"]["tables"]) >= 1

    def test_sqlite_table_keys(self):
        result = read_file(_FIXTURE_DB)
        table = result["content"]["tables"][0]
        assert "name" in table
        assert "schema" in table
        assert "row_count" in table
        assert table["row_count"] == 5

    def test_sqlite_excludes_internal_tables(self):
        """sqlite_sequence and similar internal tables must be filtered out."""
        result = read_file(_FIXTURE_DB)
        table_names = [t["name"] for t in result["content"]["tables"]]
        for name in table_names:
            assert not name.startswith("sqlite_"), f"Internal table leaked: {name}"


class TestMarkdownFixture:
    def test_reads_markdown(self):
        result = read_file(_FIXTURE_MD)
        assert result["format"] == "markdown"
        assert result["error"] is None
        assert len(result["content"]["text"]) > 0

    def test_markdown_line_count(self):
        result = read_file(_FIXTURE_MD)
        assert result["content"]["line_count"] > 0

    def test_markdown_truncation(self):
        result = read_file(_FIXTURE_MD, max_chars=10)
        assert len(result["content"]["text"]) <= 10


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

@_skip_no_kdd
class TestCSVReader:
    def test_reads_csv(self):
        result = read_file(f"{_TASK_145}/csv/attendance.csv")
        assert result["format"] == "csv"
        assert result["error"] is None
        # attendance.csv has these two columns per manual inspection
        assert "link_to_event" in result["content"]["columns"]
        assert "link_to_member" in result["content"]["columns"]
        assert len(result["content"]["rows"]) > 0

    def test_csv_max_rows_respected(self):
        result = read_file(f"{_TASK_145}/csv/attendance.csv", max_rows=3)
        assert result["content"]["row_count"] <= 3
        assert len(result["content"]["rows"]) <= 3

    def test_csv_reports_total_rows(self):
        """total_rows must be >= row_count (it counts the whole file)."""
        result = read_file(f"{_TASK_145}/csv/attendance.csv", max_rows=3)
        assert result["content"]["total_rows"] >= result["content"]["row_count"]

    def test_csv_row_count_matches_rows_list(self):
        """row_count in content must equal len(rows) — no off-by-one."""
        result = read_file(f"{_TASK_145}/csv/attendance.csv")
        assert result["content"]["row_count"] == len(result["content"]["rows"])

    def test_csv_truncated_flag_when_max_rows_hit(self):
        """If total_rows > max_rows the truncated flag must be True."""
        # Use max_rows=1 — almost certainly fewer rows than the file has
        result = read_file(f"{_TASK_145}/csv/attendance.csv", max_rows=1)
        if result["content"]["total_rows"] > 1:
            assert result["truncated"] is True

    def test_csv_truncated_false_when_all_rows_returned(self):
        """When max_rows is large enough to hold the whole file, truncated = False."""
        result = read_file(f"{_TASK_145}/csv/attendance.csv", max_rows=100_000)
        assert result["truncated"] is False

    def test_csv_rows_are_dicts(self):
        """Each row should be a plain dict, not an OrderedDict or list."""
        result = read_file(f"{_TASK_145}/csv/attendance.csv", max_rows=5)
        for row in result["content"]["rows"]:
            assert isinstance(row, dict)

    def test_csv_reports_size_bytes(self):
        result = read_file(f"{_TASK_145}/csv/attendance.csv")
        assert result["size_bytes"] > 0


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

@_skip_no_kdd
class TestJSONReader:
    def test_reads_json_object(self):
        """Patient.json is a top-level dict (object)."""
        result = read_file(f"{_TASK_11}/json/Patient.json")
        assert result["format"] == "json"
        assert result["error"] is None
        assert result["content"]["type"] == "object"

    def test_reads_json_via_glob(self):
        """Glob-based discovery — at least one JSON file must be readable."""
        json_files = glob.glob("data/kdd_tasks/demo_samples/input/*/context/json/*.json")
        assert len(json_files) > 0, "No JSON files found in demo_samples — check path"
        result = read_file(json_files[0])
        assert result["format"] == "json"
        assert result["error"] is None

    def test_json_content_has_data_key(self):
        result = read_file(f"{_TASK_11}/json/Patient.json")
        assert "data" in result["content"]

    def test_json_reports_size_bytes(self):
        result = read_file(f"{_TASK_11}/json/Patient.json")
        assert result["size_bytes"] > 0

    def test_json_truncation_on_small_max_chars(self):
        """With a tiny max_chars budget, a large JSON should be truncated."""
        result = read_file(f"{_TASK_11}/json/Patient.json", max_chars=10)
        # The file is almost certainly > 10 chars
        if result["size_bytes"] > 10:
            assert result["truncated"] is True

    def test_json_no_truncation_when_budget_large(self):
        result = read_file(f"{_TASK_11}/json/Patient.json", max_chars=10_000_000)
        assert result["truncated"] is False


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

@_skip_no_kdd
class TestSQLiteReader:
    def test_reads_sqlite_schema(self):
        result = read_file(f"{_TASK_145}/db/event.db")
        assert result["format"] == "sqlite"
        assert result["error"] is None
        assert len(result["content"]["tables"]) >= 1

    def test_sqlite_table_has_required_keys(self):
        result = read_file(f"{_TASK_145}/db/event.db")
        table = result["content"]["tables"][0]
        assert "name" in table
        assert "schema" in table
        assert "row_count" in table

    def test_sqlite_row_counts_positive(self):
        """event.db has data — row counts must be > 0."""
        result = read_file(f"{_TASK_145}/db/event.db")
        table = result["content"]["tables"][0]
        assert table["row_count"] > 0

    def test_sqlite_schema_contains_create_table(self):
        """Schema field should contain the DDL string."""
        result = read_file(f"{_TASK_145}/db/event.db")
        table = result["content"]["tables"][0]
        # SQLite stores the original CREATE TABLE statement
        assert "CREATE TABLE" in table["schema"].upper()

    def test_sqlite_truncated_always_false(self):
        """Schema + counts are never truncated — we always return the complete metadata."""
        result = read_file(f"{_TASK_145}/db/event.db")
        assert result["truncated"] is False

    def test_sqlite_reports_size_bytes(self):
        result = read_file(f"{_TASK_145}/db/event.db")
        assert result["size_bytes"] > 0


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

@_skip_no_kdd
class TestMarkdownReader:
    def test_reads_markdown(self):
        result = read_file(f"{_TASK_145}/context/knowledge.md")
        # Note: knowledge.md is directly in context/, not a subdir
        # Try both paths
        if result["error"] is not None:
            result = read_file(f"{_TASK_145}/../context/knowledge.md")
        # Fallback: use the direct path we know exists
        result = read_file("data/kdd_tasks/demo_samples/input/task_145/context/knowledge.md")
        assert result["format"] == "markdown"
        assert result["error"] is None
        assert len(result["content"]["text"]) > 0

    def test_markdown_has_line_count(self):
        result = read_file("data/kdd_tasks/demo_samples/input/task_145/context/knowledge.md")
        assert result["content"]["line_count"] > 0

    def test_markdown_truncation(self):
        result = read_file(
            "data/kdd_tasks/demo_samples/input/task_145/context/knowledge.md",
            max_chars=100,
        )
        assert len(result["content"]["text"]) <= 100
        # Either the file was truncated, or the file was already smaller than 100 chars
        if result["size_bytes"] > 100:
            assert result["truncated"] is True

    def test_markdown_no_truncation_with_large_budget(self):
        result = read_file(
            "data/kdd_tasks/demo_samples/input/task_145/context/knowledge.md",
            max_chars=10_000_000,
        )
        assert result["truncated"] is False

    def test_markdown_reports_size_bytes(self):
        result = read_file(_FIXTURE_MD)
        assert result["size_bytes"] > 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_nonexistent_file_returns_error(self):
        result = read_file("nonexistent_file.csv")
        assert result["error"] is not None
        assert result["format"] == "csv"  # format is inferred from extension even on error

    def test_nonexistent_file_content_is_empty(self):
        result = read_file("nonexistent_file.csv")
        assert result["content"] == {}

    def test_unknown_extension_falls_back_to_text(self):
        """An unrecognised extension should be treated as text, not crash."""
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False, mode="w") as f:
            f.write("hello world\n")
            path = f.name
        try:
            result = read_file(path)
            assert result["format"] == "text"
            assert result["error"] is None
            assert "hello world" in result["content"]["text"]
        finally:
            os.unlink(path)

    def test_unknown_extension_content_readable(self):
        """Content is accessible even for unknown extensions."""
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False, mode="w") as f:
            f.write("line1\nline2\nline3")
            path = f.name
        try:
            result = read_file(path)
            assert result["content"]["line_count"] == 3
        finally:
            os.unlink(path)

    def test_reports_file_size(self):
        """size_bytes is populated for files that exist."""
        result = read_file(_FIXTURE_MD)
        assert result["size_bytes"] > 0

    def test_size_bytes_zero_for_missing_file(self):
        """size_bytes should be 0 (not crash) when file doesn't exist."""
        result = read_file("completely_missing_file.txt")
        assert result["size_bytes"] == 0

    def test_result_always_has_all_keys(self):
        """Every result — success or failure — must have all six top-level keys."""
        required_keys = {"format", "path", "content", "size_bytes", "truncated", "error"}
        for path in [
            _FIXTURE_MD,
            "nonexistent_file.csv",
        ]:
            result = read_file(path)
            assert required_keys.issubset(result.keys()), (
                f"Missing keys in result for {path}: {required_keys - result.keys()}"
            )

    def test_path_echoed_in_result(self):
        """The path field must echo back the exact string passed in."""
        p = _FIXTURE_MD
        result = read_file(p)
        assert result["path"] == p
