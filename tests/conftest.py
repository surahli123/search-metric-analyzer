"""Shared test fixtures for Search Metric Analyzer tests."""

import json
import pytest
from pathlib import Path

# Project root
ROOT = Path(__file__).parent.parent

# Path to knowledge files
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"


@pytest.fixture
def knowledge_dir():
    """Path to the data/knowledge directory."""
    return KNOWLEDGE_DIR


@pytest.fixture
def synthetic_dir():
    """Path to the data/synthetic directory."""
    return SYNTHETIC_DIR


@pytest.fixture
def sample_metric_rows():
    """Minimal synthetic metric rows for testing decompose/diagnose tools.

    Returns a list of dicts simulating rows from the metric aggregate CSV,
    with Enterprise Search dimensions added.
    """
    # Baseline: 20 rows representing a "normal" period
    # 10 rows for "current" period with a DLCTR drop in JP/Standard tier
    baseline_rows = []
    current_rows = []

    for i in range(20):
        baseline_rows.append({
            "scenario_id": "test",
            "period": "baseline",
            "tenant_tier": "standard" if i % 2 == 0 else "premium",
            "ai_enablement": "ai_off",
            "industry_vertical": "tech",
            "connector_type": "confluence",
            "query_type": "informational",
            "position_bucket": "1" if i % 3 == 0 else "3-5",
            "dlctr_value": 0.280,
            "qsr_value": 0.378,
            "sain_trigger": 0.220,
            "sain_success": 0.620,
            "zero_result": 0,
            "latency_ms": 200,
            "ai_answer_shown": 0,
            "data_freshness_min": 10,
            "data_completeness": 0.995,
        })

    # Current period: DLCTR drops for standard tier
    for i in range(20):
        is_standard = i % 2 == 0
        current_rows.append({
            "scenario_id": "test",
            "period": "current",
            "tenant_tier": "standard" if is_standard else "premium",
            "ai_enablement": "ai_off",
            "industry_vertical": "tech",
            "connector_type": "confluence",
            "query_type": "informational",
            "position_bucket": "1" if i % 3 == 0 else "3-5",
            # Standard tier DLCTR drops from 0.280 to 0.245 (-12.5%)
            "dlctr_value": 0.245 if is_standard else 0.280,
            "qsr_value": 0.340 if is_standard else 0.378,
            "sain_trigger": 0.220,
            "sain_success": 0.620,
            "zero_result": 0,
            "latency_ms": 200,
            "ai_answer_shown": 0,
            "data_freshness_min": 10,
            "data_completeness": 0.995,
        })

    return baseline_rows + current_rows


@pytest.fixture
def sample_mix_shift_rows():
    """Rows where aggregate DLCTR drops due to mix-shift, not behavioral change.

    Baseline: 50% standard (DLCTR=0.245), 50% premium (DLCTR=0.295)
    Current:  70% standard, 30% premium (same per-segment DLCTR, lower aggregate)
    """
    baseline = []
    current = []

    # Baseline: 10 standard + 10 premium
    for i in range(10):
        baseline.append({
            "period": "baseline",
            "tenant_tier": "standard",
            "dlctr_value": 0.245,
            "qsr_value": 0.340,
            "query_count": 100,
        })
    for i in range(10):
        baseline.append({
            "period": "baseline",
            "tenant_tier": "premium",
            "dlctr_value": 0.295,
            "qsr_value": 0.390,
            "query_count": 100,
        })

    # Current: 14 standard + 6 premium (same per-segment values)
    for i in range(14):
        current.append({
            "period": "current",
            "tenant_tier": "standard",
            "dlctr_value": 0.245,
            "qsr_value": 0.340,
            "query_count": 100,
        })
    for i in range(6):
        current.append({
            "period": "current",
            "tenant_tier": "premium",
            "dlctr_value": 0.295,
            "qsr_value": 0.390,
            "query_count": 100,
        })

    return baseline + current
