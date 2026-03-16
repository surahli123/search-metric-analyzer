"""
Tests for the FastAPI backend (Phase 1 mock fixtures layer).

Coverage:
  - GET /api/health — liveness check
  - POST /api/diagnose — fixture routing by metric name
  - Response shape validation (required top-level keys)
  - DS Lead review fix enforcement:
      Fix 1: Within Variance SQS delta below P1 threshold (< 1.5pp)
      Fix 2: No 'ruled_out' hypothesis statuses
      Fix 3: Ranking Regression enterprise counts plausible (current/baseline > 0.7)

Run:
  pytest tests/test_web_backend.py -v
"""

import pytest
from fastapi.testclient import TestClient

from web.backend.main import app

# ---------------------------------------------------------------------------
# Shared client — reused across all tests (stateless app, safe to share)
# ---------------------------------------------------------------------------
client = TestClient(app)


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------
class TestHealthCheck:
    def test_health_returns_200(self):
        """GET /api/health must return HTTP 200."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_body(self):
        """Health response must include status='ok' and a service name."""
        response = client.get("/api/health")
        body = response.json()
        assert body.get("status") == "ok"
        assert "service" in body


# ---------------------------------------------------------------------------
# Diagnose endpoint tests
# ---------------------------------------------------------------------------
class TestDiagnoseEndpoint:
    def test_click_quality_returns_ranking_regression(self):
        """Posting metric='click_quality' must return the ranking regression fixture."""
        response = client.post("/api/diagnose", json={"metric": "click_quality"})
        assert response.status_code == 200
        body = response.json()
        assert body["diagnosis"]["verdict"] == "ranking_regression"

    def test_sqs_returns_within_variance(self):
        """Posting metric='search_quality_success' must return the within variance fixture."""
        response = client.post("/api/diagnose", json={"metric": "search_quality_success"})
        assert response.status_code == 200
        body = response.json()
        assert body["diagnosis"]["verdict"] == "within_variance"

    def test_unknown_metric_returns_default(self):
        """An unknown metric name should fall back to the within_variance fixture (not 404/500)."""
        response = client.post("/api/diagnose", json={"metric": "some_unknown_metric"})
        assert response.status_code == 200
        body = response.json()
        # Default is within_variance — defined in the route
        assert body["diagnosis"]["verdict"] == "within_variance"

    def test_response_has_required_top_level_keys(self):
        """
        Every diagnose response must include the 6 top-level keys the frontend expects.
        Missing any of these would cause a silent undefined in the React component.
        """
        response = client.post("/api/diagnose", json={"metric": "click_quality"})
        body = response.json()
        required_keys = [
            "investigation_id",
            "diagnosis",
            "narrative",
            "data_context",
            "sql_queries",
            "orchestration",
        ]
        for key in required_keys:
            assert key in body, f"Missing required key: {key}"

    def test_no_ruled_out_hypotheses(self):
        """
        DS Lead Fix 2: no hypothesis should have status='ruled_out'.
        Only 'matched' and 'not_evaluated' are valid — 'ruled_out' is fabricated precision.
        Checks both fixtures.
        """
        for metric in ["click_quality", "search_quality_success"]:
            response = client.post("/api/diagnose", json={"metric": metric})
            hypotheses = response.json()["diagnosis"]["hypotheses_evaluated"]
            statuses = [h["status"] for h in hypotheses]
            assert "ruled_out" not in statuses, (
                f"Fixture for '{metric}' contains 'ruled_out' hypothesis status — "
                "this is fabricated precision. Use 'not_evaluated' instead."
            )

    def test_within_variance_sqs_delta_below_p1(self):
        """
        DS Lead Fix 1: Within Variance SQS delta_pct must be < 1.5 (below P1 threshold).
        If delta_pct >= 1.5, the fixture claims P2 severity for a P1 magnitude — contradiction.
        """
        response = client.post("/api/diagnose", json={"metric": "search_quality_success"})
        body = response.json()
        delta = body["diagnosis"]["aggregate"]["delta_pct"]
        assert abs(delta) < 1.5, (
            f"Within Variance SQS delta_pct={delta} is >= 1.5pp (P1 threshold). "
            "This fixture should show P2 magnitude. Check Fix 1."
        )

    def test_ranking_regression_enterprise_count_plausible(self):
        """
        DS Lead Fix 3: Ranking Regression enterprise current_count / baseline_count must be > 0.7.
        The original 89 vs 150 ratio (~0.59) implied implausible churn for a 1-week window.
        130 vs 150 ratio (~0.87) is realistic.
        """
        response = client.post("/api/diagnose", json={"metric": "click_quality"})
        segments = response.json()["diagnosis"]["dimensional_breakdown"]["segments"]
        enterprise = next(s for s in segments if s["segment"] == "enterprise")
        ratio = enterprise["current_count"] / enterprise["baseline_count"]
        assert ratio > 0.7, (
            f"Enterprise current/baseline ratio={ratio:.2f} is implausibly low (<0.7). "
            "Fix 3 requires counts of 130 vs 150 (ratio ~0.87). Check the fixture."
        )
