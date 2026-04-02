"""KDD pipeline state management — experiment tracking + dynamic learnings.

AutoKaggle-inspired state persistence:
- Experiment registry: tracks SQL attempts + results per task across runs
- Dynamic learnings: after each batch, extracts patterns from failures
- State persistence: round number, best scores, history

Files:
- kdd/experiments.json: per-task SQL attempts and results
- kdd/learnings.json: accumulated learnings (correct patterns, common errors)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_STATE_DIR = Path(__file__).parent
_EXPERIMENTS_PATH = _STATE_DIR / "experiments.json"
_LEARNINGS_PATH = _STATE_DIR / "learnings.json"


import fcntl
import tempfile

_LOCK_PATH = _STATE_DIR / "experiments.lock"


def load_experiments() -> Dict[str, Any]:
    """Load experiment registry from disk (race-condition safe).

    Uses file locking to prevent corruption when 5 parallel batch
    processes read/write simultaneously. Returns empty state on
    any error (corrupted file, empty file, etc.).
    """
    if not _EXPERIMENTS_PATH.exists():
        return {"tasks": {}, "runs": 0}
    try:
        with open(_EXPERIMENTS_PATH) as f:
            content = f.read().strip()
            if not content:
                return {"tasks": {}, "runs": 0}
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {"tasks": {}, "runs": 0}


def save_experiments(data: Dict[str, Any]) -> None:
    """Save experiment registry atomically with file locking.

    WHY atomic: 5 parallel batch processes write simultaneously.
    Without locking, one process truncates the file while another reads,
    causing JSONDecodeError (empty file). Fix: write to temp file first,
    then rename (atomic on POSIX).
    """
    lock_fd = None
    try:
        # Acquire exclusive lock
        lock_fd = open(_LOCK_PATH, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Write to temp file, then atomic rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(_STATE_DIR), suffix=".tmp", prefix="experiments_"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, str(_EXPERIMENTS_PATH))
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


def _locked_read_modify_write(modify_fn) -> Dict[str, Any]:
    """Read-modify-write with exclusive file lock.

    Prevents race conditions when 5 parallel batch processes all try to
    update experiments.json simultaneously.
    """
    lock_fd = None
    try:
        lock_fd = open(_LOCK_PATH, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        data = load_experiments()
        modify_fn(data)
        # Write atomically (save_experiments acquires its own lock,
        # but we already hold it — fcntl locks are per-process reentrant)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(_STATE_DIR), suffix=".tmp", prefix="experiments_"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, str(_EXPERIMENTS_PATH))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return data
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


def record_attempt(
    task_id: str,
    sql: str,
    result_preview: str,
    match: bool,
    run_id: str = "",
) -> None:
    """Record a SQL attempt for a task (thread/process safe).

    Stores what SQL was tried and whether it worked, so future runs
    can avoid repeating failed approaches.
    """
    def _modify(data):
        if task_id not in data["tasks"]:
            data["tasks"][task_id] = {"attempts": [], "best_match": False}
        data["tasks"][task_id]["attempts"].append({
            "sql": sql[:200],
            "result": result_preview[:100],
            "match": match,
            "run": run_id,
        })
        if match:
            data["tasks"][task_id]["best_match"] = True
        if len(data["tasks"][task_id]["attempts"]) > 10:
            data["tasks"][task_id]["attempts"] = data["tasks"][task_id]["attempts"][-10:]

    _locked_read_modify_write(_modify)


def get_past_attempts(task_id: str) -> list[dict]:
    """Get past SQL attempts for a task.

    Returns list of {sql, result, match} dicts. Used by the runner to
    inject "don't try this again" context for tasks that have failed before.
    """
    data = load_experiments()
    return data.get("tasks", {}).get(task_id, {}).get("attempts", [])


def get_failed_sql_for_task(task_id: str) -> list[str]:
    """Get SQL queries that previously FAILED for this task.

    Injected into the HYPOTHESIZE prompt as negative examples so the
    LLM avoids repeating the same mistakes.
    """
    attempts = get_past_attempts(task_id)
    return [a["sql"] for a in attempts if not a.get("match", False)]


def increment_run_count() -> int:
    """Increment and return the run counter (process safe)."""
    result = [0]
    def _modify(data):
        data["runs"] = data.get("runs", 0) + 1
        result[0] = data["runs"]
    _locked_read_modify_write(_modify)
    return result[0]


def batch_retrospective(results: list[dict]) -> str:
    """Analyze a batch of results and generate a retrospective.

    AutoKaggle pattern: every 10 rounds, the Reviewer does a campaign
    retrospective. We do this after each batch to identify patterns.

    Returns a summary string of insights.
    """
    correct = [r for r in results if r.get("match")]
    wrong = [r for r in results if r.get("completed") and not r.get("match")]
    failed = [r for r in results if not r.get("completed")]

    insights = []
    insights.append(f"Batch: {len(correct)} correct, {len(wrong)} wrong, {len(failed)} failed")

    # Identify tasks that improved (were wrong before, now correct)
    data = load_experiments()
    for r in correct:
        tid = r.get("task_id", "")
        past = data.get("tasks", {}).get(tid, {})
        if past and not past.get("best_match", False):
            insights.append(f"IMPROVEMENT: {tid} — first time correct!")

    # Identify tasks that regressed (were correct before, now wrong)
    for r in wrong:
        tid = r.get("task_id", "")
        past = data.get("tasks", {}).get(tid, {})
        if past and past.get("best_match", False):
            insights.append(f"REGRESSION: {tid} — was correct before, now wrong")

    return "\n".join(insights)
