# core/corrections.py
"""Corrections knowledge layer — institutional memory of diagnostic mistakes.

WHY THIS EXISTS:
  When the system misdiagnoses a metric movement (e.g., calls a mix-shift
  a "ranking regression"), the DS corrects it. Without recording that
  correction, the system will make the same mistake next time it sees a
  similar pattern. This module prevents that by storing corrections as
  YAML and surfacing them at HYPOTHESIZE time.

  Think of it like a "lessons learned" database for an A/B test review —
  except it's for metric diagnosis, and it auto-expires stale entries
  so the knowledge base doesn't rot (Memory Time Bomb prevention).

Three capture methods:
  1. CLI: python3 core/corrections.py --add --metric X --original Y --corrected-to Z ...
  2. Auto: orchestrator calls append_correction() when connector SQL queries fail
  3. Skill: post-diagnosis feedback in Mode A calls CLI to save DS corrections

At HYPOTHESIZE, the orchestrator loads relevant corrections as context
to avoid repeating the same mistakes.
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default path: corrections.yaml lives alongside metric_definitions.yaml
_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "knowledge" / "corrections.yaml"
)

# Valid correction sources — tracks HOW the correction was captured.
# This matters for downstream filtering (e.g., sql_error corrections
# may be auto-captured and less reliable than user_correction).
VALID_SOURCES = {"user_correction", "sql_error", "skill_feedback"}


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def load_corrections(yaml_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load corrections from YAML file.

    Returns empty list if file doesn't exist — this is intentional so
    new installs work without needing to create the file first.
    The orchestrator can call this safely even before any corrections
    have been recorded.

    Args:
        yaml_path: Override path to corrections YAML. If None, uses the
            default path (data/knowledge/corrections.yaml).

    Returns:
        List of correction dicts. Each has at minimum:
        metric, original_archetype, corrected_to, context, date, source.
    """
    path = Path(yaml_path) if yaml_path else _DEFAULT_PATH

    if not path.exists():
        return []

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    # Handle empty file or file without corrections key
    if not data or "corrections" not in data:
        return []

    return data["corrections"]


def find_relevant_corrections(
    metric: str,
    archetype: str,
    corrections: List[Dict[str, Any]],
    max_age_days: Optional[int] = 90,
) -> List[Dict[str, Any]]:
    """Find corrections relevant to a given metric investigation.

    WHY METRIC-LEVEL MATCHING (not metric + archetype):
      A past mistake on the same metric is always worth surfacing, even
      if the archetype is different. For example, if click_quality was
      once misdiagnosed as "ranking_regression" when it was really
      "mix_shift", that lesson is relevant even when the current
      hypothesis is "behavioral_change" — because mix-shift is a
      common confounder for ALL click_quality movements.

    MEMORY TIME BOMB PREVENTION:
      Corrections older than max_age_days are filtered out by default.
      Old corrections may no longer be relevant — the system, data
      patterns, or team knowledge may have changed. Like how an A/B
      test result from 2 years ago shouldn't drive today's decisions
      without re-validation. Default is 90 days. Set max_age_days=None
      to disable expiration entirely.

    SORTING:
      Exact archetype matches rank first (most actionable), then by
      date (newest first) within each group. This ensures the most
      relevant correction is always at the top.

    Args:
        metric: The metric being investigated (e.g., "click_quality").
        archetype: The current archetype hypothesis (e.g., "ranking_regression").
        corrections: Full list of correction entries (from load_corrections).
        max_age_days: Exclude corrections older than this many days.
            Default 90. Set to None to include all regardless of age.

    Returns:
        List of matching corrections, sorted by relevance then recency.
    """
    # Step 1: Filter to same metric only
    matches = [c for c in corrections if c.get("metric") == metric]

    # Step 2: Filter expired corrections (Memory Time Bomb prevention)
    # String comparison works for ISO date format (YYYY-MM-DD)
    if max_age_days is not None:
        cutoff = str(date.today() - timedelta(days=max_age_days))
        matches = [c for c in matches if c.get("date", "") >= cutoff]

    # Step 3: Sort by relevance then recency
    # Python's sort is stable, so two stable sorts compose correctly:
    #   1. Sort by date descending (establishes date order)
    #   2. Sort by exact-match priority (preserves date order within each group)
    # Result: exact archetype matches first (date-descending),
    #         then metric-only matches (date-descending).
    matches.sort(key=lambda c: c.get("date", ""), reverse=True)
    matches.sort(key=lambda c: 0 if c.get("original_archetype") == archetype else 1)

    return matches


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def append_correction(
    metric: str,
    original_archetype: str,
    corrected_to: str,
    context: str,
    source: str,
    corrected_by: Optional[str] = None,
    lesson: Optional[str] = None,
    yaml_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a correction to the YAML file.

    Called by:
      - CLI (--add flag) for user corrections and skill feedback
      - Orchestrator DISPATCH stage for auto-captured SQL errors

    The source field tracks HOW the correction was captured, which
    matters for downstream filtering and trust calibration:
      - "user_correction": DS manually corrected a diagnosis (highest trust)
      - "skill_feedback": DS responded to post-diagnosis prompt (high trust)
      - "sql_error": connector query failed, auto-recorded (lower trust)

    Args:
        metric: Which metric was misdiagnosed (e.g., "click_quality").
        original_archetype: What the system originally said (e.g., "ranking_regression").
        corrected_to: What it actually was (e.g., "mix_shift").
        context: What happened and why the original was wrong.
        source: How the correction was captured. Must be one of VALID_SOURCES.
        corrected_by: Who made the correction (optional, e.g., "DS Lead").
        lesson: Lesson learned for future investigations (optional).
        yaml_path: Override path. If None, uses default.

    Returns:
        The correction entry dict that was appended.

    Raises:
        ValueError: If source is not one of VALID_SOURCES.
    """
    # Validate source before doing any file I/O
    if source not in VALID_SOURCES:
        raise ValueError(
            f"source must be one of {VALID_SOURCES}, got '{source}'"
        )

    path = Path(yaml_path) if yaml_path else _DEFAULT_PATH

    # Build the correction entry — date is always "today"
    entry: Dict[str, Any] = {
        "date": str(date.today()),
        "metric": metric,
        "original_archetype": original_archetype,
        "corrected_to": corrected_to,
        "context": context,
        "source": source,
    }
    if corrected_by:
        entry["corrected_by"] = corrected_by
    if lesson:
        entry["lesson"] = lesson

    # Load existing file or start fresh
    if path.exists():
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
    else:
        # Create parent directories if they don't exist
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    # Initialize corrections list if missing
    if "corrections" not in data:
        data["corrections"] = []

    data["corrections"].append(entry)

    # Write back — sort_keys=False preserves insertion order for readability
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return entry


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """CLI entry point for appending corrections.

    Usage:
        python3 core/corrections.py --add \\
            --metric click_quality \\
            --original ranking_regression \\
            --corrected-to mix_shift \\
            --context "Was actually a mix-shift, not ranking regression" \\
            --source user_correction \\
            --corrected-by "DS Lead"

    Outputs JSON to stdout (for Claude Code to parse):
        {"status": "appended", "entry": {...}}
    """
    parser = argparse.ArgumentParser(
        description="Corrections knowledge layer — append diagnostic corrections"
    )
    parser.add_argument(
        "--add", action="store_true", required=True,
        help="Append a new correction",
    )
    parser.add_argument(
        "--metric", required=True,
        help="Metric name (e.g., click_quality)",
    )
    parser.add_argument(
        "--original", required=True,
        help="Original archetype that was wrong",
    )
    parser.add_argument(
        "--corrected-to", required=True,
        help="Correct archetype / root cause",
    )
    parser.add_argument(
        "--context", required=True,
        help="What happened and why the original was wrong",
    )
    parser.add_argument(
        "--source", required=True,
        choices=sorted(VALID_SOURCES),
        help="How the correction was captured",
    )
    parser.add_argument(
        "--corrected-by", default=None,
        help="Who made the correction (optional)",
    )
    parser.add_argument(
        "--lesson", default=None,
        help="Lesson learned for future investigations (optional)",
    )
    parser.add_argument(
        "--yaml-path", default=None,
        help="Custom YAML path (default: data/knowledge/corrections.yaml)",
    )

    args = parser.parse_args()

    entry = append_correction(
        metric=args.metric,
        original_archetype=args.original,
        corrected_to=args.corrected_to,
        context=args.context,
        source=args.source,
        corrected_by=args.corrected_by,
        lesson=args.lesson,
        yaml_path=args.yaml_path,
    )

    # Output JSON to stdout for Claude Code to parse
    print(json.dumps({"status": "appended", "entry": entry}, indent=2))


if __name__ == "__main__":
    main()
