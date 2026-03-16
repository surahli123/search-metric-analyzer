"""
POST /api/diagnose — returns a mock investigation fixture based on the requested metric.

Phase 1 behavior: purely fixture-based (no real analysis).
  - Looks up `request.get("metric")` in FIXTURE_MAP
  - Falls back to WITHIN_VARIANCE if the metric is unknown
  - Always returns HTTP 200 with the fixture dict

Phase 2 (future): replace the fixture lookup with a real orchestrator call.
The contract (response shape) stays identical, so the frontend won't need changes.
"""

from fastapi import APIRouter
from typing import Any

from web.backend.fixtures.mock_investigations import FIXTURE_MAP, WITHIN_VARIANCE

router = APIRouter()


@router.post("/diagnose")
async def diagnose(request: dict[str, Any]) -> dict[str, Any]:
    """
    Accept a JSON body with at least {"metric": "<metric_name>"} and return
    the matching investigation fixture.

    Unknown metric names fall back to WITHIN_VARIANCE (the safer default —
    it shows a non-alarming result rather than a false regression).
    """
    metric = request.get("metric", "")
    # FIXTURE_MAP supports both canonical names ("click_quality") and
    # value-suffixed names ("click_quality_value") — see mock_investigations.py
    fixture = FIXTURE_MAP.get(metric, WITHIN_VARIANCE)
    return fixture
