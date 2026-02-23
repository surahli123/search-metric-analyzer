"""Contract tests for synthetic scenario validation."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from generators.validate_scenarios import compute_score, predict_label, run_validation


ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_DIR = ROOT / "data" / "synthetic"


def _load_results(path: Path) -> dict[str, dict[str, str]]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    return {r["scenario_id"]: r for r in rows}


def test_s7_single_cause_high_confidence_is_demoted():
    """Guardrail: even if single-cause evidence looks strong, S7 cannot stay High."""
    obs = {
        "gate_fail": False,
        "gate_warn": False,
        "has_shock": False,
        "has_l3_marker": True,
        "periodicity_index": 0.02,
    }
    deltas = {
        "click_quality": -0.04,
        "search_quality_success": -0.02,
        "p3": 0.15,
        "rank": 0.8,
        "ai_trigger": 0.02,
        "ai_success": 0.0,
    }

    score, confidence, flags = compute_score(
        sid="S7",
        predicted_label="l3_interleaver_regression",
        obs=obs,
        deltas=deltas,
        signature_pass=True,
    )

    assert score >= 80
    assert confidence == "medium"
    assert "s7_high_confidence_demoted" in flags


def test_s7_unresolved_overlap_applies_confidence_downgrade():
    """Overlap path should never emit High confidence."""
    obs = {
        "gate_fail": False,
        "gate_warn": False,
        "has_shock": True,
        "has_l3_marker": True,
        "periodicity_index": 0.02,
    }
    deltas = {
        "click_quality": -0.03,
        "search_quality_success": -0.02,
        "p3": 0.10,
        "rank": 0.5,
        "ai_trigger": 0.0,
        "ai_success": 0.0,
    }

    _score, confidence, flags = compute_score(
        sid="S7",
        predicted_label="multi_candidate_unresolved_overlap",
        obs=obs,
        deltas=deltas,
        signature_pass=True,
    )

    assert confidence in {"medium", "low", "insufficient_evidence"}
    assert confidence != "high"
    assert "unresolved_overlap" in flags


def test_validation_contract_passes_on_canonical_dataset(tmp_path: Path):
    """Canonical synthetic dataset should satisfy S0-S12 scenario contracts."""
    if not SYNTHETIC_DIR.exists():
        pytest.skip("Synthetic directory missing; run generators first.")

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name in ("synthetic_search_session_log.csv", "synthetic_metric_aggregate.csv"):
        src = SYNTHETIC_DIR / name
        if not src.exists():
            pytest.skip(f"Missing required synthetic file: {src}")
        shutil.copy2(src, input_dir / name)

    run_validation(input_dir=input_dir, output_dir=output_dir)
    results = _load_results(output_dir / "validation_results.csv")

    failed = [
        sid
        for sid, row in sorted(results.items())
        if row.get("overall_pass", "false") != "true"
    ]
    assert failed == []

    # Contract hard gates: S8 is always blocked; S7 is unresolved overlap.
    assert results["S8"]["predicted_label"] == "blocked_by_data_quality"
    assert results["S8"]["confidence_label"] == "none"
    assert results["S7"]["predicted_label"] == "multi_candidate_unresolved_overlap"
    assert results["S7"]["confidence_label"] in {"medium", "low", "insufficient_evidence"}

    for sid, row in results.items():
        assert "signature_failed_checks" in row, f"Missing signature diagnostics column for {sid}"
        failed_checks = json.loads(row["signature_failed_checks"])
        assert isinstance(failed_checks, list)
        if row.get("signature_pass") == "true":
            assert failed_checks == []


def test_predict_label_infers_mix_shift_without_scenario_routing():
    obs = {
        "gate_fail": False,
        "has_shock": False,
        "has_l3_marker": False,
        "periodicity_index": 0.0,
        "tenant_tier_mix_shift_abs": 0.14,
        "max_tier_click_delta_abs": 0.004,
        "dominant_connector": "gdrive",
        "dominant_connector_click_delta": -0.002,
        "ai_on_ai_success_delta": 0.0,
        "ai_on_ai_trigger_delta": 0.0,
    }
    deltas = {
        "click_quality": -0.011,
        "search_quality_success": -0.008,
        "p3": 0.0,
        "rank": 0.0,
        "ai_trigger": 0.0,
        "ai_success": 0.0,
    }
    assert predict_label("S_UNKNOWN", obs, deltas) == "mix_shift_composition"


def test_predict_label_infers_connector_regression_without_scenario_routing():
    obs = {
        "gate_fail": False,
        "has_shock": False,
        "has_l3_marker": False,
        "periodicity_index": 0.0,
        "tenant_tier_mix_shift_abs": 0.01,
        "max_tier_click_delta_abs": 0.02,
        "dominant_connector": "confluence",
        "dominant_connector_click_delta": -0.024,
        "ai_on_ai_success_delta": 0.0,
        "ai_on_ai_trigger_delta": 0.0,
    }
    deltas = {
        "click_quality": -0.010,
        "search_quality_success": -0.007,
        "p3": 0.0,
        "rank": 0.0,
        "ai_trigger": 0.0,
        "ai_success": 0.0,
    }
    assert predict_label("S_UNKNOWN", obs, deltas) == "connector_regression"


def test_predict_label_infers_connector_auth_expiry_without_scenario_routing():
    obs = {
        "gate_fail": False,
        "has_shock": False,
        "has_l3_marker": False,
        "periodicity_index": 0.0,
        "tenant_tier_mix_shift_abs": 0.01,
        "max_tier_click_delta_abs": 0.02,
        "dominant_connector": "sharepoint",
        "dominant_connector_click_delta": -0.028,
        "ai_on_ai_success_delta": 0.0,
        "ai_on_ai_trigger_delta": 0.0,
    }
    deltas = {
        "click_quality": -0.006,
        "search_quality_success": -0.004,
        "p3": 0.0,
        "rank": 0.0,
        "ai_trigger": 0.0,
        "ai_success": 0.0,
    }
    assert predict_label("S_UNKNOWN", obs, deltas) == "connector_auth_expiry"


def test_predict_label_infers_ai_model_migration_without_scenario_routing():
    obs = {
        "gate_fail": False,
        "has_shock": False,
        "has_l3_marker": False,
        "periodicity_index": 0.0,
        "tenant_tier_mix_shift_abs": 0.01,
        "max_tier_click_delta_abs": 0.003,
        "dominant_connector": "jira",
        "dominant_connector_click_delta": -0.003,
        "ai_on_ai_success_delta": -0.022,
        "ai_on_ai_trigger_delta": 0.009,
    }
    deltas = {
        "click_quality": -0.001,
        "search_quality_success": -0.012,
        "p3": 0.0,
        "rank": 0.0,
        "ai_trigger": 0.008,
        "ai_success": -0.012,
    }
    assert predict_label("S_UNKNOWN", obs, deltas) == "ai_model_migration"


def test_predict_label_infers_ai_model_migration_from_ai_on_trigger_shift():
    """S12 should still classify without scenario fallback when ai_on success is noisy."""
    obs = {
        "gate_fail": False,
        "has_shock": False,
        "has_l3_marker": False,
        "periodicity_index": 0.0,
        "tenant_tier_mix_shift_abs": 0.01,
        "max_tier_click_delta_abs": 0.003,
        "dominant_connector": "jira",
        "dominant_connector_click_delta": -0.003,
        # Weaken success delta below old hard threshold; trigger-shift should carry it.
        "ai_on_ai_success_delta": -0.010,
        "ai_on_ai_trigger_delta": 0.012,
    }
    deltas = {
        "click_quality": -0.001,
        "search_quality_success": -0.010,
        "p3": 0.0,
        "rank": 0.0,
        "ai_trigger": 0.009,
        "ai_success": -0.009,
    }
    assert predict_label("S_UNKNOWN", obs, deltas) == "ai_model_migration"
