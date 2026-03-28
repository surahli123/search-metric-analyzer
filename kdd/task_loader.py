"""KDD task loader — reads task metadata and discovers context files.

Each KDD task lives in a directory with this structure:

    task_145/
        task.json              ← metadata: task_id, difficulty, question
        context/
            knowledge.md       ← always present, schema + domain hints
            csv/               ← optional: CSV data files
            db/                ← optional: SQLite database files
            json/              ← optional: JSON data files

load_task() reads task.json and walks context/ to build a flat dict
that downstream consumers (runner, evaluator) can use without knowing
the directory structure.

CLI usage:
    python -m kdd.task_loader --task data/kdd_tasks/demo_samples/input/task_145
"""

import json
import os
import sys
from pathlib import Path


# File extensions we care about, grouped by category.
# The context/ dir may have subdirectories (csv/, db/, json/) or files
# at the top level — we walk everything and classify by extension.
EXTENSION_MAP = {
    ".csv": "csv",
    ".db": "db",
    ".sqlite": "db",       # some tasks use .sqlite instead of .db
    ".json": "json",
    ".md": "md",
}


def load_task(task_dir: str) -> dict:
    """Load a KDD task and discover its context files.

    Reads task.json for metadata (task_id, difficulty, question), then walks
    the context/ subdirectory to find all data files grouped by extension.

    Args:
        task_dir: Path to the task directory (e.g., "data/.../input/task_145").

    Returns:
        On success:
        {
            "task_id": "task_145",
            "difficulty": "medium",
            "question": "...",
            "knowledge_path": "/abs/path/to/context/knowledge.md",
            "context_files": {
                "csv": ["/abs/path/to/context/csv/attendance.csv"],
                "db":  ["/abs/path/to/context/db/event.db"],
                "json": [],
                "md":  ["/abs/path/to/context/knowledge.md"],
            }
        }

        On error:
        {"error": "description of what went wrong"}
    """
    task_path = Path(task_dir)

    # --- Validate directory exists ---
    if not task_path.exists():
        return {"error": f"Task directory not found: {task_dir}"}

    # --- Read task.json for metadata ---
    task_json_path = task_path / "task.json"
    if not task_json_path.exists():
        return {"error": f"task.json not found in {task_dir}"}

    try:
        with open(task_json_path, "r") as f:
            metadata = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        return {"error": f"Failed to read task.json: {exc}"}

    # --- Discover context files by walking context/ ---
    context_dir = task_path / "context"
    context_files = {"csv": [], "db": [], "json": [], "md": []}

    if context_dir.exists():
        # os.walk gives us every file in every subdirectory
        for dirpath, _dirnames, filenames in os.walk(str(context_dir)):
            for filename in filenames:
                ext = Path(filename).suffix.lower()
                category = EXTENSION_MAP.get(ext)
                if category:
                    full_path = os.path.join(dirpath, filename)
                    context_files[category].append(full_path)

    # Sort each category for deterministic output (helps testing + debugging)
    for category in context_files:
        context_files[category].sort()

    # --- Locate knowledge.md ---
    # knowledge.md lives at context/knowledge.md in every task.
    # We use the absolute path so consumers don't need to know task_dir.
    knowledge_path = str(context_dir / "knowledge.md") if context_dir.exists() else ""
    if knowledge_path and not os.path.exists(knowledge_path):
        knowledge_path = ""  # safety: don't claim it exists if it doesn't

    return {
        "task_id": metadata.get("task_id", ""),
        "difficulty": metadata.get("difficulty", ""),
        "question": metadata.get("question", ""),
        "knowledge_path": knowledge_path,
        "context_files": context_files,
    }


# ---------------------------------------------------------------------------
# CLI entrypoint: python -m kdd.task_loader --task <dir>
# ---------------------------------------------------------------------------

def main():
    """CLI entrypoint — prints task dict as JSON to stdout."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Load a KDD task and discover context files."
    )
    parser.add_argument(
        "--task", required=True,
        help="Path to task directory (e.g., data/kdd_tasks/demo_samples/input/task_145)",
    )
    args = parser.parse_args()

    result = load_task(args.task)
    # Always output JSON to stdout (project convention)
    print(json.dumps(result, indent=2))

    # Exit with error code if load_task returned an error
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
