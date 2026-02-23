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
        """Click Quality, Search Quality Success, and AI Answer must all be defined."""
        metrics = self.defs["metrics"]
        for name in ["click_quality", "search_quality_success", "ai_trigger_rate", "ai_success_rate"]:
            assert name in metrics, f"Missing core metric: {name}"

    def test_click_quality_has_required_fields(self):
        click_quality = self.defs["metrics"]["click_quality"]
        required = ["full_name", "formula", "decomposition_dimensions",
                     "normal_range", "co_movements", "alert_thresholds"]
        for field in required:
            assert field in click_quality, f"Click Quality missing field: {field}"

    def test_enterprise_dimensions_present(self):
        """Enterprise Search requires tenant_tier, ai_enablement, industry, connector."""
        dims = self.defs["metrics"]["click_quality"]["decomposition_dimensions"]
        enterprise_dims = ["tenant_tier", "ai_enablement", "industry_vertical", "connector_type"]
        for dim in enterprise_dims:
            assert dim in dims, f"Missing Enterprise dimension: {dim}"

    def test_co_movement_table_exists(self):
        """The co-movement diagnostic table must exist for fast pattern matching."""
        assert "co_movement_diagnostic_table" in self.defs

    def test_co_movement_table_has_patterns(self):
        table = self.defs["co_movement_diagnostic_table"]
        # 8 patterns: 7 core (4-metric) + 1 all-stable false alarm pattern.
        # connector_outage and serving_degradation removed — need zero_result_rate/latency.
        assert len(table) >= 8, "Need at least 8 co-movement patterns"

    def test_segment_baselines_exist(self):
        """Different baselines per segment (ai_on vs ai_off, tier differences)."""
        click_quality = self.defs["metrics"]["click_quality"]
        assert "baseline_by_segment" in click_quality


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


class TestSearchPipelineKnowledge:
    """Verify search_pipeline_knowledge.yaml has correct structure.

    WHY: This file teaches the SMA about pipeline component interactions.
    Every failure mode MUST have a metric_signature (so the SMA can match
    observed patterns) and diagnostic_checks (so it can suggest next steps).
    """

    @pytest.fixture(autouse=True)
    def load_pipeline(self):
        with open(KNOWLEDGE_DIR / "search_pipeline_knowledge.yaml") as f:
            self.data = yaml.safe_load(f)

    def test_has_pipeline_components(self):
        assert "pipeline_components" in self.data

    def test_has_causal_chains(self):
        assert "causal_chains" in self.data

    def test_has_benchmarks(self):
        assert "benchmarks" in self.data

    def test_has_five_pipeline_components(self):
        """Must cover: query_understanding, query_corrections, content_classification, ranking, vector_search."""
        components = self.data["pipeline_components"]
        expected = ["query_understanding", "query_corrections", "content_classification", "ranking", "vector_search"]
        for comp in expected:
            assert comp in components, f"Missing pipeline component: {comp}"

    def test_every_failure_mode_has_metric_signature(self):
        """Every failure mode must specify which metrics move and how."""
        for comp_name, comp in self.data["pipeline_components"].items():
            for fm in comp.get("failure_modes", []):
                assert "metric_signature" in fm, (
                    f"Failure mode '{fm['name']}' in {comp_name} missing metric_signature"
                )

    def test_every_failure_mode_has_diagnostic_checks(self):
        """Every failure mode must have at least one actionable diagnostic check."""
        for comp_name, comp in self.data["pipeline_components"].items():
            for fm in comp.get("failure_modes", []):
                assert "diagnostic_checks" in fm, (
                    f"Failure mode '{fm['name']}' in {comp_name} missing diagnostic_checks"
                )
                assert len(fm["diagnostic_checks"]) >= 1, (
                    f"Failure mode '{fm['name']}' in {comp_name} needs at least 1 diagnostic check"
                )

    def test_causal_chains_have_required_fields(self):
        """Each causal chain must specify trigger, downstream effects, and metric explanation."""
        for chain in self.data["causal_chains"]:
            assert "trigger_component" in chain, "Causal chain missing trigger_component"
            assert "trigger_failure" in chain, "Causal chain missing trigger_failure"
            assert "downstream_effects" in chain, "Causal chain missing downstream_effects"
            assert "metric_explanation" in chain, "Causal chain missing metric_explanation"


class TestEvaluationMethods:
    """Verify evaluation_methods.yaml has correct structure.

    WHY: This file helps the SMA distinguish measurement artifacts from
    real quality changes. If the evaluation methodology changed, a metric
    movement might be a measurement problem, not a system problem.
    """

    @pytest.fixture(autouse=True)
    def load_evaluation(self):
        with open(KNOWLEDGE_DIR / "evaluation_methods.yaml") as f:
            self.data = yaml.safe_load(f)

    def test_has_evaluation_approaches(self):
        assert "evaluation_approaches" in self.data

    def test_has_measurement_pitfalls(self):
        assert "measurement_pitfalls" in self.data

    def test_has_diagnostic_implications(self):
        assert "diagnostic_implications" in self.data

    def test_has_pointwise_and_pairwise(self):
        """Must document both evaluation paradigms."""
        approaches = self.data["evaluation_approaches"]
        assert "pointwise" in approaches, "Missing pointwise evaluation approach"
        assert "pairwise" in approaches, "Missing pairwise evaluation approach"

    def test_pitfalls_have_required_fields(self):
        """Each pitfall must explain its metric impact and how to check for it."""
        for pitfall in self.data["measurement_pitfalls"]:
            assert "name" in pitfall, "Measurement pitfall missing name"
            assert "metric_impact" in pitfall, (
                f"Pitfall '{pitfall.get('name', '?')}' missing metric_impact"
            )
            assert "diagnostic_check" in pitfall, (
                f"Pitfall '{pitfall.get('name', '?')}' missing diagnostic_check"
            )


class TestArchitectureTradeoffs:
    """Verify architecture_tradeoffs.yaml has correct structure.

    WHY: This file helps the SMA understand cost optimization patterns.
    When a quality regression coincides with a cost reduction, this knowledge
    explains whether the tradeoff was intentional or accidental.
    """

    @pytest.fixture(autouse=True)
    def load_architecture(self):
        with open(KNOWLEDGE_DIR / "architecture_tradeoffs.yaml") as f:
            self.data = yaml.safe_load(f)

    def test_has_cost_optimization_patterns(self):
        assert "cost_optimization_patterns" in self.data

    def test_has_token_economics(self):
        assert "token_economics" in self.data

    def test_has_diagnostic_implications(self):
        assert "diagnostic_implications" in self.data

    def test_has_four_optimization_patterns(self):
        """Must cover: model_tiering, batch_processing, semantic_caching, constraint_reduction."""
        patterns = self.data["cost_optimization_patterns"]
        expected = ["model_tiering", "batch_processing", "semantic_caching", "constraint_reduction"]
        for pat in expected:
            assert pat in patterns, f"Missing cost optimization pattern: {pat}"

    def test_every_pattern_has_failure_modes(self):
        """Each optimization pattern must document what can go wrong."""
        for pat_name, pat in self.data["cost_optimization_patterns"].items():
            assert "failure_modes" in pat, f"Pattern '{pat_name}' missing failure_modes"
            assert len(pat["failure_modes"]) >= 1, (
                f"Pattern '{pat_name}' needs at least 1 failure mode"
            )
