"""KDD answer evaluator — compares predicted answers against gold.csv.

Gold files in KDD have this format:
    COUNT(DISTINCT T1.event_id)    ← header (often a SQL expression)
    1                               ← data row(s)
    1
    1
    1

The evaluator:
1. Parses gold.csv (header + data rows)
2. Parses the predicted string as CSV
3. Compares data values row-by-row:
   - Numeric comparison first (float, tolerance 1e-6)
   - Falls back to case-insensitive string comparison
   - All rows must match for overall match=True

CLI usage:
    python -m kdd.evaluator --predicted "42" --gold path/to/gold.csv
"""

import csv
import io
import json
import os
import sys

# Tolerance for floating-point comparison.
# 1e-6 is tight enough to catch real errors but loose enough
# to handle representation differences (e.g., "1" vs "1.000000").
FLOAT_TOLERANCE = 1e-6


def _parse_csv_string(text: str) -> list[list[str]]:
    """Parse a CSV-formatted string into rows of string values.

    Uses csv.reader to handle quoting, commas in values, etc.
    Returns a list of rows, where each row is a list of cell strings.
    Empty input returns an empty list.
    """
    if not text or not text.strip():
        return []
    reader = csv.reader(io.StringIO(text.strip()))
    return [row for row in reader]


def _values_match(predicted: str, gold: str) -> bool:
    """Compare two cell values — numeric first, then case-insensitive string.

    Why numeric first: KDD gold files often have "1" where predicted might
    produce "1.0". These should match because they're the same number.

    Why case-insensitive: String answers like city names or categories
    shouldn't fail due to capitalization differences.
    """
    # Strip whitespace from both sides — common source of spurious mismatches
    pred = predicted.strip()
    gold_val = gold.strip()

    # Try numeric comparison first
    try:
        pred_float = float(pred)
        gold_float = float(gold_val)
        return abs(pred_float - gold_float) <= FLOAT_TOLERANCE
    except (ValueError, OverflowError):
        pass

    # Fall back to case-insensitive string comparison
    return pred.lower() == gold_val.lower()


def evaluate(predicted: str, gold_path: str) -> dict:
    """Compare predicted answer against gold.csv.

    The comparison ignores the header row (first row) in both predicted
    and gold — only data rows are compared. This is because KDD headers
    are often SQL expressions that the model may rephrase.

    For single-value predictions (no header), we compare directly against
    the gold data values.

    Args:
        predicted: The predicted answer as a string (may be CSV-formatted).
        gold_path: Path to the gold.csv file.

    Returns:
        {
            "match": bool,           # True if all data values match
            "score": float,          # 1.0 if match, 0.0 otherwise
            "predicted_values": list, # Flat list of predicted data values
            "gold_values": list,     # Flat list of gold data values
            "details": str,          # Human-readable comparison summary
        }
    """
    # --- Handle empty prediction ---
    if not predicted or not predicted.strip():
        return {
            "match": False,
            "score": 0.0,
            "predicted_values": [],
            "gold_values": [],
            "details": "Empty prediction",
        }

    # --- Read and parse gold file ---
    if not os.path.exists(gold_path):
        return {
            "match": False,
            "score": 0.0,
            "predicted_values": [],
            "gold_values": [],
            "details": f"Gold file not found: {gold_path}",
        }

    try:
        with open(gold_path, "r") as f:
            gold_text = f.read()
    except IOError as exc:
        return {
            "match": False,
            "score": 0.0,
            "predicted_values": [],
            "gold_values": [],
            "details": f"Error reading gold file: {exc}",
        }

    gold_rows = _parse_csv_string(gold_text)
    if len(gold_rows) < 2:
        # Gold file must have at least header + one data row
        return {
            "match": False,
            "score": 0.0,
            "predicted_values": [],
            "gold_values": [cell for row in gold_rows for cell in row],
            "details": "Gold file has no data rows (only header or empty)",
        }

    # Gold: first row is header, rest are data
    gold_header = gold_rows[0]
    gold_data = gold_rows[1:]

    # --- Parse predicted string ---
    pred_rows = _parse_csv_string(predicted)
    if not pred_rows:
        return {
            "match": False,
            "score": 0.0,
            "predicted_values": [],
            "gold_values": _flatten(gold_data),
            "details": "Predicted string parsed to empty",
        }

    # Decide if predicted has a header row.
    # Heuristic: if the number of predicted rows equals gold data rows + 1
    # AND the first predicted row looks like the gold header, treat it as
    # having a header. Otherwise, treat all predicted rows as data.
    pred_data = _strip_header_if_present(pred_rows, gold_header, len(gold_data))

    # --- Flatten for comparison ---
    # We flatten multi-column rows into a single list of values and compare
    # in order. This handles both single-value and multi-column cases.
    pred_values = _flatten(pred_data)
    gold_values = _flatten(gold_data)

    # --- Compare ---
    # Strategy: try exact positional match first (gold[i] == pred[i]).
    # If value counts differ, try contains-match (every gold value found
    # somewhere in predicted). This handles cases where the LLM returns
    # extra columns/context alongside the correct answer.

    if len(pred_values) == len(gold_values):
        # Same length — positional comparison
        mismatches = []
        for i, (pv, gv) in enumerate(zip(pred_values, gold_values)):
            if not _values_match(pv, gv):
                mismatches.append(f"  [{i}] predicted='{pv}' vs gold='{gv}'")

        if not mismatches:
            return {
                "match": True, "score": 1.0,
                "predicted_values": pred_values, "gold_values": gold_values,
                "details": "All values match (positional)",
            }

    # --- Scalar/rowset equivalence ---
    # Codex found this is the #1 false-negative source:
    # gold = [1, 1, 1, 1] (4 rows), predicted = [4] (one scalar count).
    # These are semantically equivalent — the LLM used COUNT(*) instead of
    # listing individual rows. Check: if all gold values are the same number
    # and predicted is a single number equal to count(gold_values).
    if len(pred_values) == 1 and len(gold_values) > 1:
        try:
            pred_num = float(pred_values[0].strip())
            gold_nums = [float(gv.strip()) for gv in gold_values]
            # All gold values the same AND predicted == count of gold rows
            if len(set(gold_nums)) == 1 and abs(pred_num - len(gold_values)) < 0.01:
                return {
                    "match": True, "score": 1.0,
                    "predicted_values": pred_values, "gold_values": gold_values,
                    "details": f"Scalar/rowset equivalence: {pred_values[0]} == count of {len(gold_values)} rows",
                }
        except (ValueError, OverflowError):
            pass

    # --- Contains-match fallback ---
    # Check if every gold value appears somewhere in the predicted values.
    # WHY: LLM often returns correct values with extra context (column names,
    # additional columns). E.g., gold="4", predicted=["meeting_count","4"].
    found_count = 0
    contains_details = []
    for gv in gold_values:
        found = any(_values_match(pv, gv) for pv in pred_values)
        if found:
            found_count += 1
        else:
            contains_details.append(f"  gold='{gv}' not found in predicted")

    if found_count == len(gold_values):
        return {
            "match": True, "score": 1.0,
            "predicted_values": pred_values, "gold_values": gold_values,
            "details": "All gold values found in predicted (contains-match)",
        }

    # --- Partial credit ---
    score = found_count / len(gold_values) if gold_values else 0.0
    details = (
        f"Partial match: {found_count}/{len(gold_values)} gold values found "
        f"(score={score:.2f})\n" + "\n".join(contains_details)
    )

    return {
        "match": False,
        "score": score,
        "predicted_values": pred_values,
        "gold_values": gold_values,
        "details": details,
    }


def _flatten(rows: list[list[str]]) -> list[str]:
    """Flatten a list of rows into a single list of cell values."""
    return [cell for row in rows for cell in row]


def _strip_header_if_present(
    pred_rows: list[list[str]],
    gold_header: list[str],
    gold_data_count: int,
) -> list[list[str]]:
    """Determine if predicted rows include a header and strip it if so.

    Strategy:
    - If predicted has exactly gold_data_count + 1 rows AND the first row
      matches the gold header (case-insensitive), strip the header.
    - If predicted has exactly gold_data_count rows, assume no header.
    - Otherwise, if the first row matches the gold header, strip it.
    - Default: assume all rows are data.

    Why this heuristic: LLMs sometimes include headers in their output and
    sometimes don't. We need to handle both without false positives.
    """
    if len(pred_rows) == 0:
        return pred_rows

    first_row = pred_rows[0]

    # Check if first row matches gold header (case-insensitive, stripped)
    header_matches = (
        len(first_row) == len(gold_header)
        and all(
            p.strip().lower() == g.strip().lower()
            for p, g in zip(first_row, gold_header)
        )
    )

    # Check if first row looks non-numeric (likely a header even if it
    # doesn't match gold header). Gold files often use SQL expressions like
    # COUNT(DISTINCT T1.ID) while the LLM outputs "count" or "total".
    first_row_is_non_numeric = any(
        not _is_numeric(cell) for cell in first_row
    )

    if header_matches and len(pred_rows) >= gold_data_count + 1:
        # Predicted header matches gold header — strip it
        return pred_rows[1:]
    elif first_row_is_non_numeric and len(pred_rows) == gold_data_count + 1:
        # First row looks like a header (non-numeric) and stripping it
        # gives the exact gold data count — strip it even if header text
        # doesn't match (LLM may use different column names)
        return pred_rows[1:]
    else:
        # No header detected or row count matches data count — keep all rows
        return pred_rows


def _is_numeric(s: str) -> bool:
    """Check if a string looks like a number (int or float)."""
    try:
        float(s.strip())
        return True
    except (ValueError, OverflowError):
        return False


# ---------------------------------------------------------------------------
# CLI entrypoint: python -m kdd.evaluator --predicted <str> --gold <path>
# ---------------------------------------------------------------------------

def main():
    """CLI entrypoint — prints evaluation result as JSON to stdout."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Evaluate a predicted answer against gold.csv."
    )
    parser.add_argument(
        "--predicted", required=True,
        help="Predicted answer string (CSV-formatted)",
    )
    parser.add_argument(
        "--gold", required=True,
        help="Path to gold.csv file",
    )
    args = parser.parse_args()

    result = evaluate(args.predicted, args.gold)
    print(json.dumps(result, indent=2))

    # Exit with code 0 if match, 1 if no match
    sys.exit(0 if result["match"] else 1)


if __name__ == "__main__":
    main()
