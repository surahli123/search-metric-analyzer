"""Tests for schema normalization and legacy alias bridging."""

import pytest

from core.schema import (
    normalize_metric_name,
    normalize_row,
    normalize_rows,
    normalize_diagnosis_payload,
    AgentVerdict,
    OrchestrationResult,
    normalize_agent_verdict,
    VALID_VERDICTS,
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


class TestAgentVerdictSchema:
    """Contract tests for the multi-agent verdict schemas.

    These tests lock down the shape of AgentVerdict and OrchestrationResult
    so that every specialist agent returns a predictable payload.
    Think of it like an API contract test — if the schema changes,
    these tests break before downstream consumers do.
    """

    def test_valid_verdict_passes_normalization_unchanged(self):
        """A fully-formed verdict dict should come back identical.

        If all required keys are present and valid, the normalizer
        should act like a no-op — no mutations, no surprises.
        """
        complete_verdict = {
            "agent": "ranking",
            "ran": True,
            "verdict": "confirmed",
            "reason": "Click quality dropped 15% week-over-week",
            "queries": ["SELECT * FROM metrics WHERE ..."],
            "evidence": [{"metric": "click_quality_value", "delta": -0.15}],
            "cost": {"queries": 3, "seconds": 1.2},
        }
        result = normalize_agent_verdict(complete_verdict)
        # Every key/value pair should survive normalization unchanged.
        for key, value in complete_verdict.items():
            assert result[key] == value

    def test_missing_keys_get_safe_defaults(self):
        """A minimal dict with only 'agent' should get conservative defaults.

        This is the defensive programming pattern: if a specialist agent
        crashes mid-run and only reports its name, the orchestrator still
        gets a usable payload instead of KeyError explosions downstream.
        """
        minimal = {"agent": "ranking"}
        result = normalize_agent_verdict(minimal)

        assert result["agent"] == "ranking"
        assert result["ran"] is False
        assert result["verdict"] == "inconclusive"
        assert result["reason"] == "no reason provided"
        assert result["queries"] == []
        assert result["evidence"] == []
        assert result["cost"] == {"queries": 0, "seconds": 0.0}

    def test_empty_dict_gets_all_defaults(self):
        """An empty dict should not crash — agent defaults to 'unknown'.

        Even the most broken input should produce a valid, loggable payload.
        This is the 'never crash the orchestrator' guarantee.
        """
        result = normalize_agent_verdict({})

        assert result["agent"] == "unknown"
        assert result["ran"] is False
        assert result["verdict"] == "inconclusive"

    def test_invalid_verdict_value_normalizes_to_inconclusive(self):
        """An unrecognized verdict string should normalize to 'inconclusive'.

        If an agent returns verdict='maybe' or some typo, the normalizer
        clamps it to 'inconclusive' rather than letting garbage propagate.
        Think of this like input validation at an API boundary.
        """
        bad_verdict = {"agent": "ranking", "verdict": "maybe"}
        result = normalize_agent_verdict(bad_verdict)
        assert result["verdict"] == "inconclusive"

    def test_valid_verdict_values_preserved(self):
        """All four valid verdict strings should survive normalization.

        VALID_VERDICTS defines the contract: confirmed, rejected,
        inconclusive, blocked. Each must pass through unchanged.
        """
        for valid_value in VALID_VERDICTS:
            raw = {"agent": "ranking", "verdict": valid_value}
            result = normalize_agent_verdict(raw)
            assert result["verdict"] == valid_value, (
                f"Valid verdict '{valid_value}' was mutated by normalizer"
            )

    def test_preserves_extra_keys(self):
        """Extra keys beyond the schema should not be stripped.

        Specialist agents may attach extra metadata (e.g., debug info,
        timestamps). The normalizer should be additive-only — it fills
        in missing keys but never removes existing ones.
        """
        with_extras = {
            "agent": "ranking",
            "debug_info": {"stack_trace": "..."},
            "custom_field": 42,
        }
        result = normalize_agent_verdict(with_extras)
        assert result["debug_info"] == {"stack_trace": "..."}
        assert result["custom_field"] == 42

