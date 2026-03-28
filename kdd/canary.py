"""KDD canary task suite — 10 hand-picked tasks for rapid prompt iteration testing.

WHY CANARY TASKS:
Running all 50 KDD tasks takes ~10 minutes and costs ~$0.20 per iteration.
When iterating on prompts, you want a fast signal: "did this change help or hurt?"
The canary suite answers that in ~2 minutes with 10 strategically chosen tasks.

SELECTION CRITERIA (based on 5 iteration cycles):
- 3 Regression canaries: consistently accurate — if a prompt breaks these, it's bad
- 3 Accuracy targets: complete but wrong — prompt changes should try to fix these
- 2 JSON validation: recently unlocked by JSON loading fix — verify it keeps working
- 2 Stretch targets: currently never complete — stretch goals for big improvements

CLI usage:
    # Full canary run (requires LLM API key)
    python -m kdd.canary

    # Dry run — just print the task list, no LLM calls
    python -m kdd.canary --dry-run

    # Verbose — include traces in output
    python -m kdd.canary --verbose
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from kdd.runner import run_task
from kdd.evaluator import evaluate


# ---------------------------------------------------------------------------
# Canary task definitions
# ---------------------------------------------------------------------------

# Each entry describes a task and what we expect from it today.
# "role" explains WHY it's in the canary set.
# "expected" is what a healthy prompt should produce:
#   - "match"          = answer matches gold (regression canary — must stay green)
#   - "completed"      = pipeline finishes but answer is wrong (accuracy target)
#   - "not_completed"  = pipeline fails/errors (stretch target)
CANARY_TASKS = [
    # --- Regression canaries (must stay accurate) ---
    # These tasks consistently match gold across all 5 iteration cycles.
    # If a prompt change breaks any of these, the change is harmful.
    {"task_id": "task_200", "role": "regression", "expected": "match"},
    {"task_id": "task_420", "role": "regression", "expected": "match"},
    {"task_id": "task_305", "role": "regression", "expected": "match"},

    # --- Accuracy targets (complete but wrong — try to fix) ---
    # These tasks run to completion but produce wrong answers.
    # A good prompt iteration should flip one or more of these to "match".
    {"task_id": "task_145", "role": "accuracy_target", "expected": "completed"},
    {"task_id": "task_214", "role": "accuracy_target", "expected": "completed"},
    {"task_id": "task_350", "role": "accuracy_target", "expected": "completed"},

    # --- JSON validation (recently unlocked in v5) ---
    # These tasks started matching after the JSON file loading fix.
    # They verify the JSON ingestion path keeps working.
    {"task_id": "task_261", "role": "json_validation", "expected": "match"},
    {"task_id": "task_283", "role": "json_validation", "expected": "match"},

    # --- Stretch targets (currently failing) ---
    # These tasks have never completed successfully.
    # If a prompt change fixes one, that's a significant breakthrough.
    {"task_id": "task_22", "role": "stretch", "expected": "not_completed"},
    {"task_id": "task_75", "role": "stretch", "expected": "not_completed"},
]

# Base paths for task input and gold output directories.
# These follow the KDD demo_samples directory structure.
DEFAULT_INPUT_DIR = "data/kdd_tasks/demo_samples/input"
DEFAULT_GOLD_DIR = "data/kdd_tasks/demo_samples/output"


# ---------------------------------------------------------------------------
# Core canary runner
# ---------------------------------------------------------------------------

def run_canary(
    llm_callable,
    verbose: bool = False,
    input_dir: str = DEFAULT_INPUT_DIR,
    gold_dir: str = DEFAULT_GOLD_DIR,
) -> Dict[str, Any]:
    """Run the 10 canary tasks and return a structured report.

    Each task is run through the full pipeline (runner.run_task), then
    evaluated against gold (evaluator.evaluate). Results are compared
    against expectations to detect regressions and improvements.

    Args:
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
        verbose: If True, include full traces in results (for debugging).
        input_dir: Path to KDD input task directories.
        gold_dir: Path to KDD gold output directories.

    Returns:
        {
            "total": 10,
            "completed": N,         # tasks where pipeline finished without error
            "accurate": N,          # tasks where answer matches gold
            "regressions": [...],   # expected=match but didn't match
            "improvements": [...],  # NOT expected to match but did match
            "results": {            # per-task details
                "task_200": {
                    "completed": bool,
                    "match": bool,
                    "score": float,
                    "role": str,
                    "expected": str,
                    "status": "regression" | "improvement" | "as_expected",
                    "elapsed_s": float,
                    "error": str | None,
                },
                ...
            },
            "elapsed_s": float,     # total wall-clock time
        }
    """
    results: Dict[str, Dict[str, Any]] = {}
    regressions: List[str] = []
    improvements: List[str] = []
    completed_count = 0
    accurate_count = 0
    start_time = time.time()

    for canary in CANARY_TASKS:
        task_id = canary["task_id"]
        role = canary["role"]
        expected = canary["expected"]

        task_result = _run_single_canary(
            task_id=task_id,
            llm_callable=llm_callable,
            verbose=verbose,
            input_dir=input_dir,
            gold_dir=gold_dir,
        )

        # Track aggregate counts
        if task_result["completed"]:
            completed_count += 1
        if task_result["match"]:
            accurate_count += 1

        # Compare against expectation to detect regressions and improvements
        status = _classify_outcome(
            expected=expected,
            completed=task_result["completed"],
            match=task_result["match"],
        )
        if status == "regression":
            regressions.append(task_id)
        elif status == "improvement":
            improvements.append(task_id)

        results[task_id] = {
            "completed": task_result["completed"],
            "match": task_result["match"],
            "score": task_result["score"],
            "role": role,
            "expected": expected,
            "status": status,
            "elapsed_s": task_result["elapsed_s"],
            "error": task_result["error"],
        }

    total_elapsed = time.time() - start_time

    return {
        "total": len(CANARY_TASKS),
        "completed": completed_count,
        "accurate": accurate_count,
        "regressions": regressions,
        "improvements": improvements,
        "results": results,
        "elapsed_s": round(total_elapsed, 1),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_single_canary(
    task_id: str,
    llm_callable,
    verbose: bool,
    input_dir: str,
    gold_dir: str,
) -> Dict[str, Any]:
    """Run one canary task and evaluate it against gold.

    Returns a flat dict with: completed, match, score, elapsed_s, error.
    Catches all exceptions so one failing task never kills the suite.
    """
    task_dir = os.path.join(input_dir, task_id)
    gold_path = os.path.join(gold_dir, task_id, "gold.csv")

    start = time.time()

    try:
        # Step 1: Run the task through the pipeline
        result = run_task(task_dir, llm_callable, verbose=verbose)
        elapsed = round(time.time() - start, 1)

        if not result["completed"]:
            return {
                "completed": False,
                "match": False,
                "score": 0.0,
                "elapsed_s": elapsed,
                "error": result.get("error"),
            }

        # Step 2: Evaluate against gold
        eval_result = evaluate(predicted=result["answer"], gold_path=gold_path)

        return {
            "completed": True,
            "match": eval_result["match"],
            "score": eval_result["score"],
            "elapsed_s": elapsed,
            "error": None,
        }

    except Exception as e:
        elapsed = round(time.time() - start, 1)
        return {
            "completed": False,
            "match": False,
            "score": 0.0,
            "elapsed_s": elapsed,
            "error": f"Unexpected error: {e}",
        }


def _classify_outcome(expected: str, completed: bool, match: bool) -> str:
    """Compare actual outcome against expectation.

    Returns one of:
      "regression"   — expected success but got failure (BAD)
      "improvement"  — expected failure but got success (GOOD)
      "as_expected"  — outcome matches expectation (NEUTRAL)

    Classification logic:
      expected="match"         → regression if not match
      expected="completed"     → improvement if match (accuracy target fixed!)
      expected="not_completed" → improvement if completed (stretch target unlocked!)
    """
    if expected == "match":
        # Regression canary: must match gold
        if not match:
            return "regression"
    elif expected == "completed":
        # Accuracy target: completing is expected, matching is an improvement
        if match:
            return "improvement"
    elif expected == "not_completed":
        # Stretch target: even completing is an improvement
        if completed:
            return "improvement"

    return "as_expected"


# ---------------------------------------------------------------------------
# Summary printer — compact terminal output
# ---------------------------------------------------------------------------

# ANSI colors for terminal output.
# Why not a library: project convention is stdlib-only dependencies.
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def print_summary(report: Dict[str, Any]) -> None:
    """Print a compact summary table to stderr.

    Output goes to stderr so JSON output to stdout stays machine-readable.
    The table shows each task's role, expected outcome, actual outcome,
    and whether it's a regression/improvement/as-expected.
    """
    results = report["results"]

    # Header
    _eprint(f"\n{_BOLD}{'='*65}")
    _eprint(f"  CANARY SUITE RESULTS  ({report['total']} tasks, {report['elapsed_s']}s)")
    _eprint(f"{'='*65}{_RESET}\n")

    # Column headers
    _eprint(f"  {'Task':<12} {'Role':<18} {'Expected':<15} {'Actual':<12} {'Status'}")
    _eprint(f"  {'-'*12} {'-'*18} {'-'*15} {'-'*12} {'-'*12}")

    # One row per task
    for canary in CANARY_TASKS:
        task_id = canary["task_id"]
        r = results[task_id]

        # Determine actual outcome string
        if r["match"]:
            actual = "match"
        elif r["completed"]:
            actual = "completed"
        else:
            actual = "failed"

        # Color the status column
        status = r["status"]
        if status == "regression":
            status_str = f"{_RED}REGRESSION{_RESET}"
        elif status == "improvement":
            status_str = f"{_GREEN}IMPROVEMENT{_RESET}"
        else:
            status_str = f"{_CYAN}as_expected{_RESET}"

        _eprint(f"  {task_id:<12} {r['role']:<18} {r['expected']:<15} {actual:<12} {status_str}")

    # Aggregate summary
    _eprint(f"\n  {_BOLD}Summary:{_RESET}")
    _eprint(f"    Completed: {report['completed']}/{report['total']}")
    _eprint(f"    Accurate:  {report['accurate']}/{report['total']}")

    if report["regressions"]:
        _eprint(f"    {_RED}Regressions: {', '.join(report['regressions'])}{_RESET}")
    else:
        _eprint(f"    {_GREEN}Regressions: none{_RESET}")

    if report["improvements"]:
        _eprint(f"    {_GREEN}Improvements: {', '.join(report['improvements'])}{_RESET}")

    _eprint("")


def print_dry_run() -> None:
    """Print the canary task list without running anything.

    Useful for verifying the task selection before spending API credits.
    """
    _eprint(f"\n{_BOLD}Canary Task Suite (dry run — no LLM calls){_RESET}\n")
    _eprint(f"  {'Task':<12} {'Role':<18} {'Expected'}")
    _eprint(f"  {'-'*12} {'-'*18} {'-'*15}")

    for canary in CANARY_TASKS:
        _eprint(f"  {canary['task_id']:<12} {canary['role']:<18} {canary['expected']}")

    _eprint(f"\n  Total: {len(CANARY_TASKS)} tasks")
    _eprint(f"  Input dir: {DEFAULT_INPUT_DIR}")
    _eprint(f"  Gold dir:  {DEFAULT_GOLD_DIR}")

    # Also verify all task dirs exist
    missing = []
    for canary in CANARY_TASKS:
        task_dir = os.path.join(DEFAULT_INPUT_DIR, canary["task_id"])
        if not os.path.isdir(task_dir):
            missing.append(canary["task_id"])

    if missing:
        _eprint(f"\n  {_RED}WARNING: Missing task directories: {', '.join(missing)}{_RESET}")
    else:
        _eprint(f"\n  {_GREEN}All task directories found.{_RESET}")
    _eprint("")


def _eprint(*args, **kwargs):
    """Print to stderr (keeps stdout clean for JSON output)."""
    print(*args, file=sys.stderr, **kwargs)


# ---------------------------------------------------------------------------
# CLI entrypoint: python -m kdd.canary
# ---------------------------------------------------------------------------

def main():
    """CLI entrypoint — run canary suite or dry-run.

    Usage:
        python -m kdd.canary              # full run (needs API key)
        python -m kdd.canary --dry-run    # just print task list
        python -m kdd.canary --verbose    # include traces in JSON output
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the KDD canary task suite for rapid prompt iteration testing.",
        epilog=(
            "Examples:\n"
            "  python -m kdd.canary --dry-run     # preview task list\n"
            "  python -m kdd.canary               # full run\n"
            "  python -m kdd.canary --verbose      # with traces\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the canary task list without running. No LLM calls.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Include investigation traces in JSON output.",
    )
    parser.add_argument(
        "--model", default="",
        help="LLM model name (default reads from NOVITA_API_KEY env).",
    )
    parser.add_argument(
        "--input-dir", default=DEFAULT_INPUT_DIR,
        help=f"Path to input task directories (default: {DEFAULT_INPUT_DIR}).",
    )
    parser.add_argument(
        "--gold-dir", default=DEFAULT_GOLD_DIR,
        help=f"Path to gold output directories (default: {DEFAULT_GOLD_DIR}).",
    )

    args = parser.parse_args()

    if args.dry_run:
        print_dry_run()
        # Also output JSON to stdout for machine consumption
        print(json.dumps({
            "mode": "dry_run",
            "tasks": CANARY_TASKS,
            "total": len(CANARY_TASKS),
        }, indent=2))
        sys.exit(0)

    # --- Full run: create LLM and execute ---
    # Reuse the same LLM factory as runner.py's CLI
    from kdd.runner import _make_cli_llm
    llm = _make_cli_llm(args.model)

    # Print progress to stderr, JSON results to stdout
    _eprint(f"Running {len(CANARY_TASKS)} canary tasks...")

    report = run_canary(
        llm_callable=llm,
        verbose=args.verbose,
        input_dir=args.input_dir,
        gold_dir=args.gold_dir,
    )

    # Print human-readable summary to stderr
    print_summary(report)

    # Print machine-readable JSON to stdout
    print(json.dumps(report, indent=2, default=str))

    # Exit code: 0 if no regressions, 1 if any regressions
    # WHY exit(1) on regression: so CI/scripts can detect failures automatically.
    # Improvements and as-expected results are not failures.
    sys.exit(1 if report["regressions"] else 0)


if __name__ == "__main__":
    main()
