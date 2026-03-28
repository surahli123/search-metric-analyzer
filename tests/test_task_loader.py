"""Tests for KDD task loader.

Validates that:
1. load_task() discovers context files by extension (csv, db, json, md)
2. load_task() extracts metadata from task.json (task_id, difficulty, question)
3. Error cases return structured error dicts (missing dir, missing task.json)
4. Empty context dir still finds knowledge.md path
5. Real KDD demo data loads correctly (skipped if data unavailable)
"""

import json
import os
import tempfile
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Skip marker for tests that need real KDD demo data on disk
# ---------------------------------------------------------------------------
KDD_TASK_DIR = "data/kdd_tasks/demo_samples/input/task_145"
SKIP_NO_KDD = pytest.mark.skipif(
    not os.path.exists(KDD_TASK_DIR),
    reason="KDD demo data not available",
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic task directories for deterministic testing
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_task(tmp_path):
    """Create a minimal valid task directory with task.json + knowledge.md."""
    task_dir = tmp_path / "task_999"
    task_dir.mkdir()

    # task.json — the metadata file every task must have
    task_json = {
        "task_id": "task_999",
        "difficulty": "easy",
        "question": "How many users signed up last week?",
    }
    (task_dir / "task.json").write_text(json.dumps(task_json))

    # context/ with knowledge.md only (no data files)
    context_dir = task_dir / "context"
    context_dir.mkdir()
    (context_dir / "knowledge.md").write_text("# Schema\nusers table has id, name, created_at")

    return str(task_dir)


@pytest.fixture
def full_task(tmp_path):
    """Create a task directory with all context file types (csv, db, json, md)."""
    task_dir = tmp_path / "task_888"
    task_dir.mkdir()

    task_json = {
        "task_id": "task_888",
        "difficulty": "hard",
        "question": "What is the average revenue per customer?",
    }
    (task_dir / "task.json").write_text(json.dumps(task_json))

    context_dir = task_dir / "context"
    context_dir.mkdir()
    (context_dir / "knowledge.md").write_text("# Schema info")

    # csv subdirectory with two files
    csv_dir = context_dir / "csv"
    csv_dir.mkdir()
    (csv_dir / "revenue.csv").write_text("customer_id,amount\n1,100\n2,200")
    (csv_dir / "customers.csv").write_text("id,name\n1,Alice\n2,Bob")

    # db subdirectory
    db_dir = context_dir / "db"
    db_dir.mkdir()
    (db_dir / "sales.db").write_text("")  # empty placeholder

    # json subdirectory
    json_dir = context_dir / "json"
    json_dir.mkdir()
    (json_dir / "orders.json").write_text('[{"id": 1}]')

    return str(task_dir)


# ---------------------------------------------------------------------------
# Tests — synthetic fixtures (always run)
# ---------------------------------------------------------------------------

class TestLoadTaskSynthetic:
    """Tests using synthetic (tmp_path) task fixtures — no real KDD data needed."""

    def test_minimal_task_loads_metadata(self, minimal_task):
        """task_id, difficulty, and question come from task.json."""
        from kdd.task_loader import load_task

        result = load_task(minimal_task)

        assert result["task_id"] == "task_999"
        assert result["difficulty"] == "easy"
        assert result["question"] == "How many users signed up last week?"

    def test_minimal_task_finds_knowledge_path(self, minimal_task):
        """knowledge_path should point to context/knowledge.md even with no data files."""
        from kdd.task_loader import load_task

        result = load_task(minimal_task)

        # knowledge_path must be an absolute or relative path ending in knowledge.md
        assert result["knowledge_path"].endswith("knowledge.md")
        assert os.path.exists(result["knowledge_path"])

    def test_minimal_task_empty_data_categories(self, minimal_task):
        """With only knowledge.md, csv/db/json lists should be empty, md should have one."""
        from kdd.task_loader import load_task

        result = load_task(minimal_task)

        assert result["context_files"]["csv"] == []
        assert result["context_files"]["db"] == []
        assert result["context_files"]["json"] == []
        # knowledge.md is in the md list
        assert len(result["context_files"]["md"]) == 1

    def test_full_task_discovers_all_file_types(self, full_task):
        """All context file types should be discovered and categorized."""
        from kdd.task_loader import load_task

        result = load_task(full_task)

        assert result["task_id"] == "task_888"
        assert result["difficulty"] == "hard"

        ctx = result["context_files"]
        # Two CSV files
        assert len(ctx["csv"]) == 2
        csv_names = sorted([os.path.basename(p) for p in ctx["csv"]])
        assert csv_names == ["customers.csv", "revenue.csv"]

        # One DB file
        assert len(ctx["db"]) == 1
        assert os.path.basename(ctx["db"][0]) == "sales.db"

        # One JSON file
        assert len(ctx["json"]) == 1
        assert os.path.basename(ctx["json"][0]) == "orders.json"

        # One MD file (knowledge.md)
        assert len(ctx["md"]) == 1


class TestLoadTaskErrors:
    """Tests for error handling — missing dirs, missing files."""

    def test_missing_dir_returns_error(self):
        """Non-existent directory should return an error dict, not raise."""
        from kdd.task_loader import load_task

        result = load_task("/nonexistent/path/task_000")

        assert "error" in result
        assert "not found" in result["error"].lower() or "not exist" in result["error"].lower()

    def test_missing_task_json_returns_error(self, tmp_path):
        """Directory exists but has no task.json — should return error."""
        from kdd.task_loader import load_task

        task_dir = tmp_path / "task_no_json"
        task_dir.mkdir()

        result = load_task(str(task_dir))

        assert "error" in result
        assert "task.json" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tests — real KDD demo data (skipped if data unavailable)
# ---------------------------------------------------------------------------

class TestLoadTaskRealData:
    """Tests against real KDD demo data — skipped on CI or if data missing."""

    @SKIP_NO_KDD
    def test_load_task_145_discovers_files(self):
        """task_145 should have csv + db context files and a knowledge.md."""
        from kdd.task_loader import load_task

        result = load_task(KDD_TASK_DIR)

        assert result["task_id"] == "task_145"
        assert result["difficulty"] == "medium"
        assert "events" in result["question"].lower() or "members" in result["question"].lower()

        ctx = result["context_files"]
        # task_145 has: context/csv/attendance.csv and context/db/event.db
        assert len(ctx["csv"]) >= 1
        assert len(ctx["db"]) >= 1
        assert len(ctx["md"]) >= 1
        assert result["knowledge_path"].endswith("knowledge.md")
