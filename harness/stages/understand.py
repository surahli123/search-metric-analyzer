"""UNDERSTAND stage — deterministic analysis using core tools.

This stage answers: "What happened?" using only code (no LLM).
It runs the full diagnostic toolkit and produces a structured
summary of the metric movement.

WHY A STANDALONE FUNCTION (not a method):
Extracted from SearchMetricOrchestrator._stage_understand() to keep
the orchestrator class small (~250 LOC) and each stage independently
testable. The function accepts explicit parameters instead of `self`.

Dependencies (all in core/ — no LLM needed):
- core.anomaly: check_data_quality, detect_step_change, match_co_movement_pattern
- core.decompose: run_decomposition
- core.diagnose: run_diagnosis
- contracts.seam_validator: validate_seam
- trace.helpers: emit_deterministic_span
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from core.anomaly import check_data_quality, detect_step_change, match_co_movement_pattern
from core.decompose import run_decomposition
from core.diagnose import run_diagnosis
from contracts.seam_validator import validate_seam, SeamViolation
from harness.errors import StageError
from trace.collector import InvestigationTrace
from trace.helpers import emit_deterministic_span


def stage_understand(
    question: str,
    rows: list,
    metric_field: str,
    dimensions: Optional[list],
    trace: InvestigationTrace,
) -> Dict[str, Any]:
    """Stage 1: UNDERSTAND — deterministic analysis using core tools.

    Steps:
    1. Check data quality (gate check — can we trust this data?)
    2. Run decomposition (where is the movement concentrated?)
    3. Extract daily values for step-change detection
    4. Detect step change (overnight jump or gradual drift?)
    5. Match co-movement pattern (which known failure mode?)
    6. Run diagnosis (validate, build hypothesis, score confidence)
    7. Build UnderstandResult dict
    8. Validate with seam_validator (HARD gate — halts on failure)
    9. Emit trace span

    Args:
        question: Investigation question text.
        rows: Metric data rows (must have 'period' field).
        metric_field: Which metric to analyze.
        dimensions: Dimensions to decompose by.
        trace: InvestigationTrace to record decisions to.

    Returns:
        UnderstandResult dict conforming to the contract schema.

    Raises:
        SeamViolation: If UNDERSTAND seam validation fails (HARD gate).
        StageError: If core tools crash on unexpected input.
    """
    # --- Core tool calls wrapped in try/except ---
    # The core/ tools assume well-formed input data. If the input has
    # unexpected structure, these tools may raise KeyError, TypeError, etc.
    # We catch these so the pipeline returns a clear StageError.
    try:
        # --- Step 1: Data quality gate ---
        dq_result = check_data_quality(rows, trace=trace)

        # --- Step 2: Run decomposition ---
        decomposition = run_decomposition(
            rows=rows,
            metric_field=metric_field,
            dimensions=dimensions,
            trace=trace,
        )

        # --- Step 3: Extract daily values for step-change detection ---
        daily_values = _extract_daily_values(rows, metric_field)

        # --- Step 4: Detect step change ---
        step_change = detect_step_change(daily_values, trace=trace)

        # --- Step 5: Match co-movement pattern ---
        observed_directions = _extract_observed_directions(rows, metric_field)
        co_movement = match_co_movement_pattern(observed_directions, trace=trace)

        # --- Step 6: Run diagnosis ---
        # Diagnosis consumes all prior analysis and produces the hypothesis.
        # MUST be inside this try/except — run_diagnosis accesses fields from
        # decomposition (e.g., "aggregate") and can raise KeyError/TypeError
        # on malformed input, same as the other core tools above.
        diagnosis = run_diagnosis(
            decomposition=decomposition,
            step_change_result=step_change,
            co_movement_result=co_movement,
            trust_gate_result=dq_result,
            trace=trace,
        )

    except (SeamViolation, StageError):
        raise
    except Exception as exc:
        raise StageError(
            message=(
                f"UNDERSTAND failed: core analysis tool raised "
                f"{type(exc).__name__}: {str(exc)[:200]}. "
                f"Check that input data has the expected columns and format."
            ),
            stage="UNDERSTAND",
            violations=[f"Core tool error: {type(exc).__name__}: {str(exc)[:200]}"],
        ) from exc

    # --- Step 7: Build UnderstandResult ---
    # Extract key fields from diagnosis and decomposition into the
    # contract-defined UnderstandResult shape.
    aggregate = decomposition.get("aggregate", {})
    direction = aggregate.get("direction", "stable")
    severity = diagnosis.get("aggregate", aggregate).get("severity", "normal")

    understand_result: Dict[str, Any] = {
        "question": question,
        "metric": metric_field,
        "direction": direction,
        "severity": severity,
        "data_quality_status": dq_result.get("status", "pass"),
        "step_change": step_change if step_change.get("detected") else None,
        "co_movement_pattern": co_movement,
        "mix_shift_result": decomposition.get("mix_shift") or None,
        # IC9 Invisible Decision #1: metric_direction must be explicitly set
        "metric_direction": direction,
        "data_quality_details": dq_result,
        # Additional context for downstream stages
        "decomposition": decomposition,
        "diagnosis": diagnosis,
    }

    # --- Step 8: Seam validation (HARD gate) ---
    # UNDERSTAND uses a HARD gate — if validation fails, the pipeline
    # halts immediately. This prevents bad data from producing misleading
    # diagnoses. The SeamViolation exception propagates to run().
    validate_seam(
        result=understand_result,
        stage="UNDERSTAND",
        trace=trace,
    )

    # --- Step 9: Emit summary trace span ---
    # Record the overall UNDERSTAND outcome for downstream stages
    emit_deterministic_span(
        trace,
        tool="harness.stages.understand.stage_understand",
        decision="understand_complete",
        value=f"{direction}_{severity}",
        human_summary=(
            f"UNDERSTAND complete: {metric_field} {direction} "
            f"(severity={severity}, dq={dq_result.get('status', 'unknown')})"
        ),
        agent_context=(
            f"metric={metric_field}, direction={direction}, severity={severity}, "
            f"dq_status={dq_result.get('status')}, "
            f"co_movement={co_movement.get('likely_cause', 'unknown')}, "
            f"step_change={step_change.get('detected', False)}"
        ),
    )

    return understand_result


# ---------------------------------------------------------------------------
# Helper functions (extracted from SearchMetricOrchestrator methods)
# ---------------------------------------------------------------------------


def _extract_daily_values(rows: list, metric_field: str) -> List[float]:
    """Extract daily metric averages from rows for step-change detection.

    Groups rows by date (from metric_ts or date field) and computes
    the daily mean for the target metric. Returns a chronologically
    sorted list of daily averages.

    If no date field is found, returns an empty list (step-change
    detection will report "not detected" for < 2 values).
    """
    daily_buckets: Dict[str, List[float]] = defaultdict(list)

    for row in rows:
        # Try common date field names
        ts = row.get("metric_ts", row.get("date", row.get("event_ts", "")))
        if not ts:
            continue
        # Extract date portion (first 10 chars of ISO timestamp)
        date_str = str(ts)[:10] if ts else "unknown"
        try:
            val = float(row.get(metric_field, 0))
        except (ValueError, TypeError):
            val = 0.0
        daily_buckets[date_str].append(val)

    if not daily_buckets:
        return []

    # Sort by date and compute daily averages
    sorted_dates = sorted(daily_buckets.keys())
    return [
        sum(daily_buckets[d]) / len(daily_buckets[d])
        for d in sorted_dates
    ]


def _extract_observed_directions(
    rows: list, primary_metric: str
) -> Dict[str, str]:
    """Extract observed metric directions for co-movement pattern matching.

    Compares baseline vs current period means for each metric and
    classifies the direction as "up", "down", or "stable".

    The co-movement table expects directions for:
    - click_quality, search_quality_success, ai_trigger, ai_success

    Uses a 1% relative threshold to distinguish "stable" from real movement.
    """
    # Metrics to check for co-movement (maps output key -> row field name)
    metric_fields = {
        "click_quality": "click_quality_value",
        "search_quality_success": "search_quality_success_value",
        "ai_trigger": "ai_trigger",
        "ai_success": "ai_success",
    }

    # Split by period
    baseline_rows = [r for r in rows if r.get("period") == "baseline"]
    current_rows = [r for r in rows if r.get("period") == "current"]

    if not baseline_rows or not current_rows:
        # Can't compute directions without both periods
        return {}

    directions: Dict[str, str] = {}
    # Threshold for "stable" — less than 1% relative change
    STABLE_THRESHOLD = 0.01

    for key, field in metric_fields.items():
        # Compute means for each period
        bl_vals = []
        cur_vals = []
        for r in baseline_rows:
            try:
                bl_vals.append(float(r.get(field, 0)))
            except (ValueError, TypeError):
                pass
        for r in current_rows:
            try:
                cur_vals.append(float(r.get(field, 0)))
            except (ValueError, TypeError):
                pass

        if not bl_vals or not cur_vals:
            directions[key] = "stable"
            continue

        bl_mean = sum(bl_vals) / len(bl_vals)
        cur_mean = sum(cur_vals) / len(cur_vals)

        if bl_mean == 0:
            directions[key] = "stable"
            continue

        relative_change = (cur_mean - bl_mean) / abs(bl_mean)

        if relative_change > STABLE_THRESHOLD:
            directions[key] = "up"
        elif relative_change < -STABLE_THRESHOLD:
            directions[key] = "down"
        else:
            directions[key] = "stable"

    return directions
