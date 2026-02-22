"""Tests that knowledge YAML files load correctly and contain required fields."""

import yaml
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"


class TestMetricDefinitions:
    """Verify metric_definitions.yaml has correct structure."""

    @pytest.fixture(autouse=True)
    def load_definitions(self):
        with open(KNOWLEDGE_DIR / "metric_definitions.yaml") as f:
            self.defs = yaml.safe_load(f)

    def test_has_metrics_key(self):
        assert "metrics" in self.defs

    def test_core_metrics_present(self):
        """DLCTR, QSR, and SAIN must all be defined."""
        metrics = self.defs["metrics"]
        for name in ["dlctr", "qsr", "sain_trigger_rate", "sain_success_rate"]:
            assert name in metrics, f"Missing core metric: {name}"

    def test_dlctr_has_required_fields(self):
        dlctr = self.defs["metrics"]["dlctr"]
        required = ["full_name", "formula", "decomposition_dimensions",
                     "normal_range", "co_movements", "alert_thresholds"]
        for field in required:
            assert field in dlctr, f"DLCTR missing field: {field}"

    def test_enterprise_dimensions_present(self):
        """Enterprise Search requires tenant_tier, ai_enablement, industry, connector."""
        dims = self.defs["metrics"]["dlctr"]["decomposition_dimensions"]
        enterprise_dims = ["tenant_tier", "ai_enablement", "industry_vertical", "connector_type"]
        for dim in enterprise_dims:
            assert dim in dims, f"Missing Enterprise dimension: {dim}"

    def test_co_movement_table_exists(self):
        """The co-movement diagnostic table must exist for fast pattern matching."""
        assert "co_movement_diagnostic_table" in self.defs

    def test_co_movement_table_has_patterns(self):
        table = self.defs["co_movement_diagnostic_table"]
        assert len(table) >= 9, "Need at least 9 co-movement patterns (from design doc)"

    def test_segment_baselines_exist(self):
        """Different baselines per segment (ai_on vs ai_off, tier differences)."""
        dlctr = self.defs["metrics"]["dlctr"]
        assert "baseline_by_segment" in dlctr


class TestHistoricalPatterns:
    """Verify historical_patterns.yaml has correct structure."""

    @pytest.fixture(autouse=True)
    def load_patterns(self):
        with open(KNOWLEDGE_DIR / "historical_patterns.yaml") as f:
            self.patterns = yaml.safe_load(f)

    def test_has_seasonal_patterns(self):
        assert "seasonal_patterns" in self.patterns
        assert len(self.patterns["seasonal_patterns"]) >= 3

    def test_has_known_incidents(self):
        assert "known_incidents" in self.patterns

    def test_has_diagnostic_shortcuts(self):
        assert "diagnostic_shortcuts" in self.patterns

    def test_seasonal_pattern_has_required_fields(self):
        pattern = self.patterns["seasonal_patterns"][0]
        required = ["name", "typical_impact", "mechanism", "key_check"]
        for field in required:
            assert field in pattern, f"Seasonal pattern missing: {field}"

    def test_has_enterprise_patterns(self):
        """Must include Enterprise-specific patterns: onboarding, AI rollout, connector."""
        names = [p["name"] for p in self.patterns["seasonal_patterns"]]
        # At least one of each category
        assert any("onboarding" in n.lower() or "tenant" in n.lower() for n in names), \
            "Missing tenant onboarding pattern"
        assert any("ai" in n.lower() for n in names), \
            "Missing AI rollout pattern"
