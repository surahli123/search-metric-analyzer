"""Tests for schema normalization and legacy alias bridging."""

import pytest

from tools.schema import (
    normalize_metric_name,
    normalize_row,
    normalize_rows,
    normalize_diagnosis_payload,
)


class TestNormalizeMetricName:
    """Metric aliases should map to canonical v1 names."""

    def test_maps_legacy_metric_names(self):
        assert normalize_metric_name("dlctr_value") == "click_quality_value"
        assert normalize_metric_name("qsr_value") == "search_quality_success_value"
        assert normalize_metric_name("sain_trigger") == "ai_trigger"
        assert normalize_metric_name("sain_success") == "ai_success"

    def test_keeps_canonical_metric_names(self):
        assert normalize_metric_name("click_quality_value") == "click_quality_value"
        assert (
            normalize_metric_name("search_quality_success_value")
            == "search_quality_success_value"
        )


class TestNormalizeRow:
    """Row-level normalization should expose canonical and compatibility fields."""

    def test_adds_canonical_metrics_from_legacy_aliases(self):
        row = {
            "dlctr_value": "0.280",
            "qsr_value": "0.378",
            "sain_trigger": "1",
            "sain_success": "0",
        }
        norm = normalize_row(row)

        assert norm["click_quality_value"] == "0.280"
        assert norm["search_quality_success_value"] == "0.378"
        assert norm["ai_trigger"] == "1"
        assert norm["ai_success"] == "0"

    def test_adds_legacy_aliases_from_canonical_fields(self):
        row = {
            "click_quality_value": "0.245",
            "search_quality_success_value": "0.340",
            "ai_trigger": "0",
            "ai_success": "1",
        }
        norm = normalize_row(row)

        assert norm["dlctr_value"] == "0.245"
        assert norm["qsr_value"] == "0.340"
        assert norm["sain_trigger"] == "0"
        assert norm["sain_success"] == "1"

    def test_normalizes_trust_gate_variants(self):
        row = {"completeness_pct": "99.7", "freshness_lag_min": "30"}
        norm = normalize_row(row)

        assert norm["completeness_pct"] == "99.7"
        assert norm["freshness_lag_min"] == "30"
        assert float(norm["data_completeness"]) == pytest.approx(0.997, abs=1e-6)
        assert float(norm["data_freshness_min"]) == pytest.approx(30.0, abs=1e-6)

    def test_normalize_rows_applies_to_all_rows(self):
        rows = [
            {"dlctr_value": "0.280", "completeness_pct": "99.5"},
            {"dlctr_value": "0.260", "completeness_pct": "99.0"},
        ]
        normalized = normalize_rows(rows)
        assert len(normalized) == 2
        assert normalized[0]["click_quality_value"] == "0.280"
        assert normalized[1]["click_quality_value"] == "0.260"


class TestNormalizeDiagnosisPayload:
    """Formatter/consumers should be able to canonicalize diagnosis payloads."""

    def test_normalizes_aggregate_metric_and_sets_default_decision_status(self):
        diagnosis = {"aggregate": {"metric": "dlctr_value"}}
        normalized = normalize_diagnosis_payload(diagnosis)
        assert normalized["aggregate"]["metric"] == "click_quality_value"
        assert normalized["decision_status"] == "diagnosed"

