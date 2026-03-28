"""Tests for KDD runner — the 2-LLM-call pipeline.

Tests use a mock LLM callable that returns canned responses to avoid
real API calls. The runner should:
1. Load a task (via task_loader)
2. Build schema context from data files
3. Call LLM #1 (HYPOTHESIZE) to plan SQL
4. Execute SQL via sql_executor
5. Call LLM #2 (SYNTHESIZE) to format the answer
6. Return a result dict with task_id, answer, completed, error, trace

Test cases:
- Happy path: mock LLM returns valid JSON plan + formatted answer
- Invalid SQL plan: LLM returns gibberish instead of JSON
- SQL executor error: valid plan but SQL execution fails
- Missing task directory: returns error dict without crashing
- Batch mode: runs multiple tasks, handles per-task errors
"""

import json
import os
import sqlite3
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from kdd.runner import run_task, run_batch


# ---------------------------------------------------------------------------
# Fixtures — synthetic task directories for deterministic testing
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_db_task(tmp_path):
    """Create a task directory with a SQLite database.

    The task asks "How many events are there?" and the DB has 3 rows.
    This is the simplest possible happy path test.
    """
    task_dir = tmp_path / "task_001"
    task_dir.mkdir()

    # task.json — metadata
    task_json = {
        "task_id": "task_001",
        "difficulty": "easy",
        "question": "How many events are there?",
    }
    (task_dir / "task.json").write_text(json.dumps(task_json))

    # context/ with knowledge.md + db
    context_dir = task_dir / "context"
    context_dir.mkdir()
    (context_dir / "knowledge.md").write_text(
        "# Schema\nevent table has columns: id (int), name (text), date (text)"
    )

    db_dir = context_dir / "db"
    db_dir.mkdir()
    db_path = db_dir / "event.db"

    # Create a real SQLite database with 3 rows
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE event (id INTEGER, name TEXT, date TEXT)")
    conn.execute("INSERT INTO event VALUES (1, 'Concert', '2024-01-01')")
    conn.execute("INSERT INTO event VALUES (2, 'Workshop', '2024-02-15')")
    conn.execute("INSERT INTO event VALUES (3, 'Meetup', '2024-03-20')")
    conn.commit()
    conn.close()

    return str(task_dir)


@pytest.fixture
def csv_task(tmp_path):
    """Create a task directory with CSV data files.

    Tests the DuckDB/CSV code path.
    """
    task_dir = tmp_path / "task_002"
    task_dir.mkdir()

    task_json = {
        "task_id": "task_002",
        "difficulty": "medium",
        "question": "What is the total revenue?",
    }
    (task_dir / "task.json").write_text(json.dumps(task_json))

    context_dir = task_dir / "context"
    context_dir.mkdir()
    (context_dir / "knowledge.md").write_text(
        "# Schema\nrevenue table has columns: id, amount"
    )

    csv_dir = context_dir / "csv"
    csv_dir.mkdir()
    (csv_dir / "revenue.csv").write_text("id,amount\n1,100\n2,200\n3,300")

    return str(task_dir)


# ---------------------------------------------------------------------------
# Mock LLM callables
# ---------------------------------------------------------------------------

def make_mock_llm(hypothesize_response: str, synthesize_response: str):
    """Create a mock LLM callable that returns different responses per call.

    The runner calls the LLM exactly twice:
    1. HYPOTHESIZE: plan SQL queries -> returns JSON with approaches
    2. SYNTHESIZE: format results as CSV -> returns plain text

    We track call count to return the right response at the right time.
    """
    call_count = {"n": 0}

    def mock_llm(prompt: str, system: str, max_tokens: int) -> str:
        call_count["n"] += 1
        # First call = HYPOTHESIZE, second call = SYNTHESIZE
        if call_count["n"] == 1:
            return hypothesize_response
        else:
            return synthesize_response

    return mock_llm


def make_valid_hypothesize_response(sql: str = "SELECT COUNT(*) AS total FROM event"):
    """Build a valid HYPOTHESIZE JSON response with one SQL approach."""
    return json.dumps({
        "approaches": [
            {
                "description": "Count all rows",
                "sql": sql,
                "rationale": "Direct count answers the question",
            }
        ],
        "best_approach_index": 0,
        "reasoning": "Simple count is sufficient",
    })


# ---------------------------------------------------------------------------
# Tests: Happy path
# ---------------------------------------------------------------------------

class TestRunTaskHappyPath:
    """Test that run_task completes successfully with valid inputs."""

    def test_run_task_completes_with_mock_llm(self, simple_db_task):
        """Happy path: mock LLM returns valid plan + answer, result is completed=True."""
        mock_llm = make_mock_llm(
            hypothesize_response=make_valid_hypothesize_response(
                "SELECT COUNT(*) AS total FROM event"
            ),
            synthesize_response="COUNT(*)\n3",
        )

        result = run_task(simple_db_task, mock_llm)

        # Must return a well-shaped result dict
        assert result["task_id"] == "task_001"
        assert result["completed"] is True
        assert result["error"] is None
        # The answer should contain the synthesize output
        assert "3" in result["answer"]

    def test_run_task_with_csv_data(self, csv_task):
        """Happy path with CSV data files — uses DuckDB backend."""
        mock_llm = make_mock_llm(
            hypothesize_response=make_valid_hypothesize_response(
                "SELECT SUM(amount) AS total FROM revenue"
            ),
            synthesize_response="SUM(amount)\n600",
        )

        result = run_task(csv_task, mock_llm)

        assert result["task_id"] == "task_002"
        assert result["completed"] is True
        assert result["error"] is None
        assert "600" in result["answer"]

    def test_run_task_result_shape(self, simple_db_task):
        """Verify all expected keys are present in the result dict."""
        mock_llm = make_mock_llm(
            hypothesize_response=make_valid_hypothesize_response(),
            synthesize_response="COUNT(*)\n3",
        )

        result = run_task(simple_db_task, mock_llm)

        # Required keys per spec
        assert "task_id" in result
        assert "answer" in result
        assert "completed" in result
        assert "error" in result
        assert "trace" in result

    def test_run_task_trace_is_populated(self, simple_db_task):
        """The trace dict should be non-None on successful completion."""
        mock_llm = make_mock_llm(
            hypothesize_response=make_valid_hypothesize_response(),
            synthesize_response="COUNT(*)\n3",
        )

        result = run_task(simple_db_task, mock_llm, verbose=True)

        # Trace should be a dict with at least a trace_id
        assert result["trace"] is not None
        assert "trace_id" in result["trace"]


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------

class TestRunTaskErrors:
    """Test that run_task handles errors gracefully without crashing."""

    def test_run_task_invalid_sql_plan(self, simple_db_task):
        """LLM returns gibberish instead of valid JSON for HYPOTHESIZE."""
        mock_llm = make_mock_llm(
            hypothesize_response="I don't know how to write SQL for this.",
            synthesize_response="",
        )

        result = run_task(simple_db_task, mock_llm)

        # Should not crash — returns error dict
        assert result["task_id"] == "task_001"
        assert result["completed"] is False
        assert result["error"] is not None
        assert len(result["error"]) > 0

    def test_run_task_sql_executor_error(self, simple_db_task):
        """LLM returns valid JSON with SQL, but the SQL references a nonexistent table."""
        mock_llm = make_mock_llm(
            hypothesize_response=make_valid_hypothesize_response(
                "SELECT COUNT(*) FROM nonexistent_table"
            ),
            synthesize_response="",
        )

        result = run_task(simple_db_task, mock_llm)

        # SQL execution error should be captured, not crash
        assert result["task_id"] == "task_001"
        assert result["completed"] is False
        assert result["error"] is not None
        # Error message should mention the SQL failure
        assert "error" in result["error"].lower() or "nonexistent" in result["error"].lower()

    def test_run_task_missing_task_dir(self):
        """Nonexistent task directory returns error dict."""
        mock_llm = make_mock_llm("", "")

        result = run_task("/nonexistent/path/task_999", mock_llm)

        assert result["completed"] is False
        assert result["error"] is not None
        assert "task_id" in result

    def test_run_task_llm_exception(self, simple_db_task):
        """LLM callable raises an exception — should be caught gracefully."""
        def exploding_llm(prompt, system, max_tokens):
            raise RuntimeError("API connection failed")

        result = run_task(simple_db_task, exploding_llm)

        assert result["completed"] is False
        assert result["error"] is not None
        assert "API connection failed" in result["error"]

    def test_run_task_empty_approaches(self, simple_db_task):
        """LLM returns valid JSON but with empty approaches list."""
        mock_llm = make_mock_llm(
            hypothesize_response=json.dumps({
                "approaches": [],
                "best_approach_index": 0,
                "reasoning": "No ideas",
            }),
            synthesize_response="",
        )

        result = run_task(simple_db_task, mock_llm)

        assert result["completed"] is False
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# Tests: Batch mode
# ---------------------------------------------------------------------------

class TestRunBatch:
    """Test batch execution across multiple tasks."""

    def test_run_batch_all_succeed(self, simple_db_task, csv_task):
        """Batch run with all tasks succeeding."""
        mock_llm = make_mock_llm(
            # These get reset per call inside run_batch, so we need a smarter mock
            hypothesize_response=make_valid_hypothesize_response(
                "SELECT COUNT(*) AS total FROM event"
            ),
            synthesize_response="COUNT(*)\n3",
        )

        # For batch, we need a mock that works for multiple tasks.
        # Each task gets its own run_task call, so the mock needs to
        # handle multiple rounds of hypothesize+synthesize calls.
        call_count = {"n": 0}

        def batch_mock_llm(prompt: str, system: str, max_tokens: int) -> str:
            call_count["n"] += 1
            # Odd calls = HYPOTHESIZE, even calls = SYNTHESIZE
            if call_count["n"] % 2 == 1:
                # Return SQL appropriate for whichever task is running
                if "revenue" in prompt.lower() or "amount" in prompt.lower():
                    return make_valid_hypothesize_response(
                        "SELECT SUM(amount) AS total FROM revenue"
                    )
                return make_valid_hypothesize_response(
                    "SELECT COUNT(*) AS total FROM event"
                )
            else:
                return "total\n3"

        # No gold_dir for this test — just check completion
        result = run_batch(
            task_dirs=[simple_db_task, csv_task],
            llm_callable=batch_mock_llm,
        )

        assert "results" in result
        assert "summary" in result
        assert result["summary"]["total"] == 2
        assert result["summary"]["completed"] == 2

    def test_run_batch_partial_failure(self, simple_db_task):
        """Batch run where one task fails (missing dir) and one succeeds."""
        call_count = {"n": 0}

        def batch_mock_llm(prompt: str, system: str, max_tokens: int) -> str:
            call_count["n"] += 1
            if call_count["n"] % 2 == 1:
                return make_valid_hypothesize_response(
                    "SELECT COUNT(*) AS total FROM event"
                )
            else:
                return "total\n3"

        result = run_batch(
            task_dirs=[simple_db_task, "/nonexistent/task_000"],
            llm_callable=batch_mock_llm,
        )

        assert result["summary"]["total"] == 2
        assert result["summary"]["completed"] == 1
        # The failed task should still be in results
        assert len(result["results"]) == 2

    def test_run_batch_with_gold_dir(self, simple_db_task, tmp_path):
        """Batch run with gold_dir populates accuracy in summary."""
        # Create a gold directory with a matching gold.csv
        gold_dir = tmp_path / "output"
        gold_dir.mkdir()
        task_gold_dir = gold_dir / "task_001"
        task_gold_dir.mkdir()
        (task_gold_dir / "gold.csv").write_text("COUNT(*)\n3")

        call_count = {"n": 0}

        def batch_mock_llm(prompt: str, system: str, max_tokens: int) -> str:
            call_count["n"] += 1
            if call_count["n"] % 2 == 1:
                return make_valid_hypothesize_response(
                    "SELECT COUNT(*) AS total FROM event"
                )
            else:
                return "COUNT(*)\n3"

        result = run_batch(
            task_dirs=[simple_db_task],
            llm_callable=batch_mock_llm,
            gold_dir=str(gold_dir),
        )

        assert result["summary"]["total"] == 1
        assert result["summary"]["completed"] == 1
        # accuracy should be populated when gold_dir is provided
        assert "accuracy" in result["summary"]


# ---------------------------------------------------------------------------
# Tests: Verbose / trace mode
# ---------------------------------------------------------------------------

class TestRunTaskVerbose:
    """Test verbose mode produces trace output."""

    def test_verbose_false_returns_none_trace(self, simple_db_task):
        """When verbose=False, trace should be None to save memory."""
        mock_llm = make_mock_llm(
            hypothesize_response=make_valid_hypothesize_response(),
            synthesize_response="COUNT(*)\n3",
        )

        result = run_task(simple_db_task, mock_llm, verbose=False)

        assert result["trace"] is None

    def test_verbose_true_returns_trace_dict(self, simple_db_task):
        """When verbose=True, trace should be a populated dict."""
        mock_llm = make_mock_llm(
            hypothesize_response=make_valid_hypothesize_response(),
            synthesize_response="COUNT(*)\n3",
        )

        result = run_task(simple_db_task, mock_llm, verbose=True)

        assert result["trace"] is not None
        assert isinstance(result["trace"], dict)
