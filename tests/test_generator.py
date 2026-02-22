"""Tests that the synthetic data generator produces valid Enterprise Search data.

Tests cover:
1. Enterprise dimension columns exist in both session log and metric aggregate
2. All 13 scenarios (S0-S12) present
3. Period column with baseline/current for every scenario
4. Scenario-specific behaviors (S9 mix-shift, S10 connector regression, etc.)
5. Enterprise dimension value validity
6. Data distribution sanity checks
"""

import csv
import json
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants for validation
# ---------------------------------------------------------------------------

ENTERPRISE_COLS = ["tenant_tier", "ai_enablement", "industry_vertical", "connector_type"]
VALID_TENANT_TIERS = {"standard", "premium", "enterprise"}
VALID_AI_ENABLEMENT = {"ai_on", "ai_off"}
VALID_INDUSTRY = {"tech", "healthcare", "finance", "retail", "other"}
VALID_CONNECTOR = {"confluence", "slack", "gdrive", "jira", "sharepoint", "other"}
VALID_PERIODS = {"baseline", "current"}
ALL_SCENARIO_IDS = {f"S{i}" for i in range(13)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_csv(path: Path):
    """Read a CSV file and return list of dicts."""
    with open(path) as f:
        return list(csv.DictReader(f))


def _read_csv_by_scenario(path: Path, scenario_id: str):
    """Read rows for a specific scenario from a CSV."""
    rows = _read_csv(path)
    return [r for r in rows if r["scenario_id"] == scenario_id]


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_dir():
    """Path to synthetic data directory in the worktree."""
    # Use the project root from the test file's location
    root = Path(__file__).parent.parent
    return root / "data" / "synthetic"


@pytest.fixture(scope="module")
def session_log_path(synthetic_dir):
    path = synthetic_dir / "synthetic_search_session_log.csv"
    if not path.exists():
        pytest.skip("Run generator first: python generators/generate_synthetic_data.py --output-dir data/synthetic")
    return path


@pytest.fixture(scope="module")
def metric_agg_path(synthetic_dir):
    path = synthetic_dir / "synthetic_metric_aggregate.csv"
    if not path.exists():
        pytest.skip("Run generator first: python generators/generate_synthetic_data.py --output-dir data/synthetic")
    return path


@pytest.fixture(scope="module")
def session_rows(session_log_path):
    return _read_csv(session_log_path)


@pytest.fixture(scope="module")
def metric_rows(metric_agg_path):
    return _read_csv(metric_agg_path)


# ===========================================================================
# Test Class: Enterprise Dimensions
# ===========================================================================

class TestEnterpriseDimensions:
    """Verify enterprise dimension columns exist with valid values."""

    def test_session_log_has_enterprise_columns(self, session_rows):
        """Session log must have all 4 enterprise dimension columns."""
        first_row = session_rows[0]
        for col in ENTERPRISE_COLS:
            assert col in first_row, f"Missing Enterprise dimension in session log: {col}"

    def test_metric_agg_has_enterprise_columns(self, metric_rows):
        """Metric aggregate must have all 4 enterprise dimension columns."""
        first_row = metric_rows[0]
        for col in ENTERPRISE_COLS:
            assert col in first_row, f"Missing Enterprise dimension in metric aggregate: {col}"

    def test_tenant_tier_values_valid(self, session_rows):
        """tenant_tier must be one of: standard, premium, enterprise."""
        tiers = {r["tenant_tier"] for r in session_rows}
        assert tiers.issubset(VALID_TENANT_TIERS), f"Invalid tenant_tier values: {tiers - VALID_TENANT_TIERS}"
        # All three tiers should appear across the full dataset
        assert tiers == VALID_TENANT_TIERS, f"Missing tenant tiers: {VALID_TENANT_TIERS - tiers}"

    def test_ai_enablement_values_valid(self, session_rows):
        """ai_enablement must be one of: ai_on, ai_off."""
        values = {r["ai_enablement"] for r in session_rows}
        assert values.issubset(VALID_AI_ENABLEMENT), f"Invalid ai_enablement: {values - VALID_AI_ENABLEMENT}"
        assert values == VALID_AI_ENABLEMENT, f"Missing ai_enablement values: {VALID_AI_ENABLEMENT - values}"

    def test_industry_vertical_values_valid(self, session_rows):
        """industry_vertical must be one of the valid set."""
        values = {r["industry_vertical"] for r in session_rows}
        assert values.issubset(VALID_INDUSTRY), f"Invalid industry: {values - VALID_INDUSTRY}"

    def test_connector_type_values_valid(self, session_rows):
        """connector_type must be one of the valid set."""
        values = {r["connector_type"] for r in session_rows}
        assert values.issubset(VALID_CONNECTOR), f"Invalid connector: {values - VALID_CONNECTOR}"


# ===========================================================================
# Test Class: All 13 Scenarios
# ===========================================================================

class TestScenarioCoverage:
    """Verify all 13 scenarios (S0-S12) are present."""

    def test_session_log_has_all_13_scenarios(self, session_rows):
        """Session log must have scenarios S0 through S12."""
        scenarios = {r["scenario_id"] for r in session_rows}
        for i in range(13):
            assert f"S{i}" in scenarios, f"Missing scenario S{i} in session log"

    def test_metric_agg_has_all_13_scenarios(self, metric_rows):
        """Metric aggregate must have scenarios S0 through S12."""
        scenarios = {r["scenario_id"] for r in metric_rows}
        for i in range(13):
            assert f"S{i}" in scenarios, f"Missing scenario S{i} in metric aggregate"


# ===========================================================================
# Test Class: Period Column
# ===========================================================================

class TestPeriodColumn:
    """Verify period column exists with baseline and current for every scenario."""

    def test_session_log_has_period_column(self, session_rows):
        """Session log must have a 'period' column."""
        assert "period" in session_rows[0], "Session log missing 'period' column"

    def test_metric_agg_has_period_column(self, metric_rows):
        """Metric aggregate must have a 'period' column."""
        assert "period" in metric_rows[0], "Metric aggregate missing 'period' column"

    def test_every_scenario_has_both_periods_in_session_log(self, session_rows):
        """Each scenario (S0-S12) must have both baseline and current rows."""
        for sid in ALL_SCENARIO_IDS:
            scenario_rows = [r for r in session_rows if r["scenario_id"] == sid]
            periods = {r["period"] for r in scenario_rows}
            assert "baseline" in periods, f"{sid} missing 'baseline' period in session log"
            assert "current" in periods, f"{sid} missing 'current' period in session log"

    def test_every_scenario_has_both_periods_in_metric_agg(self, metric_rows):
        """Each scenario (S0-S12) must have both baseline and current in metric aggregate."""
        for sid in ALL_SCENARIO_IDS:
            scenario_rows = [r for r in metric_rows if r["scenario_id"] == sid]
            periods = {r["period"] for r in scenario_rows}
            assert "baseline" in periods, f"{sid} missing 'baseline' period in metric aggregate"
            assert "current" in periods, f"{sid} missing 'current' period in metric aggregate"

    def test_period_values_are_valid(self, session_rows):
        """Period must be exactly 'baseline' or 'current'."""
        periods = {r["period"] for r in session_rows}
        assert periods.issubset(VALID_PERIODS), f"Invalid period values: {periods - VALID_PERIODS}"


# ===========================================================================
# Test Class: Scenario S9 — Tenant Portfolio Mix-Shift
# ===========================================================================

class TestScenarioS9MixShift:
    """S9: Aggregate DLCTR drops from mix-shift, per-segment metrics stay the same."""

    def test_s9_has_tenant_tier_variation(self, session_rows):
        """S9 must have multiple tenant tiers (the mix-shift source)."""
        s9_rows = [r for r in session_rows if r["scenario_id"] == "S9"]
        tiers = {r["tenant_tier"] for r in s9_rows}
        assert len(tiers) >= 2, f"S9 should have multiple tenant tiers, got: {tiers}"

    def test_s9_current_has_more_standard_share(self, session_rows):
        """In S9 current period, standard tier should have higher share than baseline."""
        s9_baseline = [r for r in session_rows if r["scenario_id"] == "S9" and r["period"] == "baseline"]
        s9_current = [r for r in session_rows if r["scenario_id"] == "S9" and r["period"] == "current"]

        baseline_standard_share = sum(1 for r in s9_baseline if r["tenant_tier"] == "standard") / max(len(s9_baseline), 1)
        current_standard_share = sum(1 for r in s9_current if r["tenant_tier"] == "standard") / max(len(s9_current), 1)

        # Current should have higher standard share (65% vs 50%)
        assert current_standard_share > baseline_standard_share, (
            f"S9 current standard share ({current_standard_share:.2%}) "
            f"should exceed baseline ({baseline_standard_share:.2%})"
        )


# ===========================================================================
# Test Class: Scenario S10 — Connector Extraction Quality Regression
# ===========================================================================

class TestScenarioS10ConnectorRegression:
    """S10: Confluence connector quality degrades, others stable."""

    def test_s10_has_confluence_rows(self, session_rows):
        """S10 must include confluence connector_type rows."""
        s10_rows = [r for r in session_rows if r["scenario_id"] == "S10"]
        connectors = {r["connector_type"] for r in s10_rows}
        assert "confluence" in connectors, "S10 missing confluence connector rows"

    def test_s10_has_non_confluence_rows(self, session_rows):
        """S10 should also have non-confluence rows (for comparison)."""
        s10_rows = [r for r in session_rows if r["scenario_id"] == "S10"]
        non_confluence = [r for r in s10_rows if r["connector_type"] != "confluence"]
        assert len(non_confluence) > 0, "S10 should have non-confluence rows for stable comparison"


# ===========================================================================
# Test Class: Scenario S11 — Auth Credential Expiry
# ===========================================================================

class TestScenarioS11AuthExpiry:
    """S11: Sharepoint auth expires, documents stop syncing."""

    def test_s11_has_sharepoint_rows(self, session_rows):
        """S11 must include sharepoint connector_type rows."""
        s11_rows = [r for r in session_rows if r["scenario_id"] == "S11"]
        connectors = {r["connector_type"] for r in s11_rows}
        assert "sharepoint" in connectors, "S11 missing sharepoint connector rows"

    def test_s11_has_non_sharepoint_rows(self, session_rows):
        """S11 should also have non-sharepoint rows (stable comparisons)."""
        s11_rows = [r for r in session_rows if r["scenario_id"] == "S11"]
        non_sp = [r for r in s11_rows if r["connector_type"] != "sharepoint"]
        assert len(non_sp) > 0, "S11 should have non-sharepoint rows"


# ===========================================================================
# Test Class: Scenario S12 — LLM Provider/Model Migration
# ===========================================================================

class TestScenarioS12LLMMigration:
    """S12: AI answer quality changes, affects ai_on tenants only."""

    def test_s12_has_ai_on_rows(self, session_rows):
        """S12 must include ai_on rows (the affected segment)."""
        s12_rows = [r for r in session_rows if r["scenario_id"] == "S12"]
        ai_values = {r["ai_enablement"] for r in s12_rows}
        assert "ai_on" in ai_values, "S12 missing ai_on rows"

    def test_s12_has_ai_off_rows(self, session_rows):
        """S12 should have ai_off rows (unaffected control group)."""
        s12_rows = [r for r in session_rows if r["scenario_id"] == "S12"]
        ai_values = {r["ai_enablement"] for r in s12_rows}
        assert "ai_off" in ai_values, "S12 missing ai_off rows"


# ===========================================================================
# Test Class: Data Quality
# ===========================================================================

class TestDataQuality:
    """General data quality checks on the generated data."""

    def test_session_log_not_empty(self, session_rows):
        """Generated session log must have rows."""
        assert len(session_rows) > 0, "Session log is empty"

    def test_metric_agg_not_empty(self, metric_rows):
        """Generated metric aggregate must have rows."""
        assert len(metric_rows) > 0, "Metric aggregate is empty"

    def test_session_and_metric_row_counts_match(self, session_rows, metric_rows):
        """Session log and metric aggregate should have same number of rows."""
        assert len(session_rows) == len(metric_rows), (
            f"Row count mismatch: session={len(session_rows)}, metric={len(metric_rows)}"
        )

    def test_generation_summary_exists(self, synthetic_dir):
        """generation_summary.json should exist after generation."""
        summary_path = synthetic_dir / "generation_summary.json"
        if not summary_path.exists():
            pytest.skip("Run generator first")
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["scenario_count"] == 13, f"Expected 13 scenarios, got {summary['scenario_count']}"

    def test_enterprise_dimensions_in_metric_agg_match_session_log(self, session_rows, metric_rows):
        """Enterprise dimensions in metric aggregate should match session log for same query_id."""
        # Spot-check first 100 rows
        session_by_qid = {r["query_id"]: r for r in session_rows[:500]}
        for mr in metric_rows[:500]:
            qid = mr["query_id"]
            if qid in session_by_qid:
                sr = session_by_qid[qid]
                for col in ENTERPRISE_COLS:
                    assert mr[col] == sr[col], (
                        f"Mismatch for {qid}: metric_agg.{col}={mr[col]} vs session.{col}={sr[col]}"
                    )
