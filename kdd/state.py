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


def load_experiments() -> Dict[str, Any]:
    """Load experiment registry from disk."""
    if _EXPERIMENTS_PATH.exists():
        with open(_EXPERIMENTS_PATH) as f:
            return json.load(f)
    return {"tasks": {}, "runs": 0}


def save_experiments(data: Dict[str, Any]) -> None:
    """Save experiment registry to disk."""
    with open(_EXPERIMENTS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def record_attempt(
    task_id: str,
    sql: str,
    result_preview: str,
    match: bool,
    run_id: str = "",
) -> None:
    """Record a SQL attempt for a task.

    Stores what SQL was tried and whether it worked, so future runs
    can avoid repeating failed approaches.
    """
    data = load_experiments()
    if task_id not in data["tasks"]:
        data["tasks"][task_id] = {"attempts": [], "best_match": False}

    data["tasks"][task_id]["attempts"].append({
        "sql": sql[:200],  # Truncate to save space
        "result": result_preview[:100],
        "match": match,
        "run": run_id,
    })

    # Track if we ever got this task right
    if match:
        data["tasks"][task_id]["best_match"] = True

    # Cap attempts per task to prevent file bloat
    if len(data["tasks"][task_id]["attempts"]) > 10:
        data["tasks"][task_id]["attempts"] = data["tasks"][task_id]["attempts"][-10:]

    save_experiments(data)


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
    """Increment and return the run counter."""
    data = load_experiments()
    data["runs"] = data.get("runs", 0) + 1
    save_experiments(data)
    return data["runs"]


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
