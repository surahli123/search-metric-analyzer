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


# ===========================================================================
# Helpers for metric-level validation
# ===========================================================================

def _mean(values):
    """Compute arithmetic mean of a list of floats."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_float(val):
    """Convert CSV string value to float, defaulting to 0.0."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ===========================================================================
# Test Class: S9 Mix-Shift Aggregate vs Per-Segment Validation
# ===========================================================================


class TestS9MixShiftMetricBehavior:
    """S9: Verify that aggregate DLCTR drops from mix-shift while
    per-segment DLCTR stays the same.

    This is the core Simpson's Paradox test: the aggregate changes
    because the MIX of traffic shifted toward lower-performing segments,
    not because any individual segment's quality changed.

    What to expect:
    - Aggregate DLCTR in current period < aggregate DLCTR in baseline
    - Per-segment DLCTR (standard, premium, enterprise) should be similar
      between baseline and current (within sampling noise)
    """

    def test_s9_aggregate_dlctr_drops_in_current(self, metric_rows):
        """Aggregate DLCTR across all S9 rows should be lower in current vs baseline.

        The mix-shift toward standard tier (lower DLCTR baseline) should
        pull the aggregate down even though individual segments are stable.
        """
        s9_baseline = [r for r in metric_rows if r["scenario_id"] == "S9" and r["period"] == "baseline"]
        s9_current = [r for r in metric_rows if r["scenario_id"] == "S9" and r["period"] == "current"]

        baseline_agg = _mean([_safe_float(r["dlctr_value"]) for r in s9_baseline])
        current_agg = _mean([_safe_float(r["dlctr_value"]) for r in s9_current])

        # Current aggregate should be lower (mix-shift effect)
        assert current_agg < baseline_agg, (
            f"S9 aggregate DLCTR should drop in current period. "
            f"Baseline={baseline_agg:.6f}, Current={current_agg:.6f}"
        )

    def test_s9_per_segment_dlctr_stable_for_standard(self, metric_rows):
        """Standard tier DLCTR should be similar between baseline and current.

        Per-segment metrics don't change in S9 — only the mix does.
        We allow up to 10% relative difference due to sampling noise
        (the click probability uses the same tier multiplier in both periods).
        """
        s9_baseline_std = [
            r for r in metric_rows
            if r["scenario_id"] == "S9" and r["period"] == "baseline" and r["tenant_tier"] == "standard"
        ]
        s9_current_std = [
            r for r in metric_rows
            if r["scenario_id"] == "S9" and r["period"] == "current" and r["tenant_tier"] == "standard"
        ]

        if not s9_baseline_std or not s9_current_std:
            pytest.skip("Not enough standard tier rows in S9")

        baseline_mean = _mean([_safe_float(r["dlctr_value"]) for r in s9_baseline_std])
        current_mean = _mean([_safe_float(r["dlctr_value"]) for r in s9_current_std])

        # Per-segment should be stable: allow 10% relative tolerance for sampling noise
        if baseline_mean > 0:
            relative_change = abs(current_mean - baseline_mean) / baseline_mean
            assert relative_change < 0.10, (
                f"S9 standard tier DLCTR should be stable across periods. "
                f"Baseline={baseline_mean:.6f}, Current={current_mean:.6f}, "
                f"Relative change={relative_change:.2%}"
            )

    def test_s9_per_segment_dlctr_stable_for_premium(self, metric_rows):
        """Premium tier DLCTR should be similar between baseline and current."""
        s9_baseline_prem = [
            r for r in metric_rows
            if r["scenario_id"] == "S9" and r["period"] == "baseline" and r["tenant_tier"] == "premium"
        ]
        s9_current_prem = [
            r for r in metric_rows
            if r["scenario_id"] == "S9" and r["period"] == "current" and r["tenant_tier"] == "premium"
        ]

        if not s9_baseline_prem or not s9_current_prem:
            pytest.skip("Not enough premium tier rows in S9")

        baseline_mean = _mean([_safe_float(r["dlctr_value"]) for r in s9_baseline_prem])
        current_mean = _mean([_safe_float(r["dlctr_value"]) for r in s9_current_prem])

        if baseline_mean > 0:
            relative_change = abs(current_mean - baseline_mean) / baseline_mean
            assert relative_change < 0.10, (
                f"S9 premium tier DLCTR should be stable across periods. "
                f"Baseline={baseline_mean:.6f}, Current={current_mean:.6f}, "
                f"Relative change={relative_change:.2%}"
            )

    def test_s9_standard_has_lower_dlctr_than_premium(self, metric_rows):
        """Standard tier should have lower per-segment DLCTR than premium.

        This verifies the tier hierarchy that makes mix-shift meaningful:
        standard < premium < enterprise in DLCTR baseline.
        """
        s9_rows = [r for r in metric_rows if r["scenario_id"] == "S9"]
        std_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s9_rows if r["tenant_tier"] == "standard"])
        prem_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s9_rows if r["tenant_tier"] == "premium"])

        assert std_dlctr < prem_dlctr, (
            f"S9: Standard tier DLCTR ({std_dlctr:.6f}) should be lower than "
            f"premium tier ({prem_dlctr:.6f}) to make mix-shift meaningful"
        )


# ===========================================================================
# Test Class: S10 Confluence DLCTR Regression Validation
# ===========================================================================


class TestS10ConfluenceRegressionMetrics:
    """S10: Verify that confluence connector has lower DLCTR than other
    connectors in the current period.

    The scenario simulates confluence extraction quality degradation.
    In the current period, confluence rows should have noticeably lower
    DLCTR than non-confluence rows. In baseline, all connectors should
    be similar.
    """

    def test_s10_confluence_dlctr_lower_in_current(self, metric_rows):
        """Confluence DLCTR should be lower than non-confluence in current period.

        The 0.88x multiplier on confluence click probability in current period
        should produce a measurable DLCTR difference.
        """
        s10_current = [r for r in metric_rows if r["scenario_id"] == "S10" and r["period"] == "current"]
        confluence_current = [r for r in s10_current if r["connector_type"] == "confluence"]
        non_confluence_current = [r for r in s10_current if r["connector_type"] != "confluence"]

        if not confluence_current or not non_confluence_current:
            pytest.skip("Not enough S10 rows by connector type")

        confluence_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in confluence_current])
        non_confluence_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in non_confluence_current])

        assert confluence_dlctr < non_confluence_dlctr, (
            f"S10: Confluence DLCTR ({confluence_dlctr:.6f}) should be lower than "
            f"non-confluence ({non_confluence_dlctr:.6f}) in current period "
            f"due to extraction quality regression"
        )

    def test_s10_confluence_dlctr_drops_from_baseline(self, metric_rows):
        """Confluence DLCTR should drop between baseline and current.

        The 0.88x multiplier only applies in the current period.
        """
        s10_baseline_conf = [
            r for r in metric_rows
            if r["scenario_id"] == "S10" and r["period"] == "baseline" and r["connector_type"] == "confluence"
        ]
        s10_current_conf = [
            r for r in metric_rows
            if r["scenario_id"] == "S10" and r["period"] == "current" and r["connector_type"] == "confluence"
        ]

        if not s10_baseline_conf or not s10_current_conf:
            pytest.skip("Not enough S10 confluence rows")

        baseline_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s10_baseline_conf])
        current_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s10_current_conf])

        assert current_dlctr < baseline_dlctr, (
            f"S10: Confluence DLCTR should drop from baseline ({baseline_dlctr:.6f}) "
            f"to current ({current_dlctr:.6f})"
        )

    def test_s10_non_confluence_dlctr_stable(self, metric_rows):
        """Non-confluence connectors should have stable DLCTR across periods.

        Only confluence is affected; other connectors should be unchanged.
        """
        s10_baseline_other = [
            r for r in metric_rows
            if r["scenario_id"] == "S10" and r["period"] == "baseline" and r["connector_type"] != "confluence"
        ]
        s10_current_other = [
            r for r in metric_rows
            if r["scenario_id"] == "S10" and r["period"] == "current" and r["connector_type"] != "confluence"
        ]

        if not s10_baseline_other or not s10_current_other:
            pytest.skip("Not enough S10 non-confluence rows")

        baseline_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s10_baseline_other])
        current_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s10_current_other])

        # Non-confluence should be stable — allow 10% relative tolerance
        if baseline_dlctr > 0:
            relative_change = abs(current_dlctr - baseline_dlctr) / baseline_dlctr
            assert relative_change < 0.10, (
                f"S10: Non-confluence DLCTR should be stable. "
                f"Baseline={baseline_dlctr:.6f}, Current={current_dlctr:.6f}, "
                f"Change={relative_change:.2%}"
            )


# ===========================================================================
# Test Class: S11 Sharepoint Zero Result Rate Validation
# ===========================================================================


class TestS11SharepointZeroResultRate:
    """S11: Verify that sharepoint connector has elevated zero-result behavior
    in the current period.

    The scenario simulates sharepoint auth credential expiry: documents
    stop syncing, so many queries return zero results (no click).
    The metric-level signal is a higher rate of zero-click rows for
    sharepoint in the current period compared to baseline.
    """

    def test_s11_sharepoint_click_rate_drops_in_current(self, metric_rows):
        """Sharepoint should have lower click rate in current period.

        With auth expiry, 40% of sharepoint queries force zero results,
        and the remaining have a 0.70x click probability multiplier.
        This should produce a measurable drop in click rate.
        """
        s11_baseline_sp = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "baseline" and r["connector_type"] == "sharepoint"
        ]
        s11_current_sp = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "current" and r["connector_type"] == "sharepoint"
        ]

        if not s11_baseline_sp or not s11_current_sp:
            pytest.skip("Not enough S11 sharepoint rows")

        # clicked_flag == 1 means a click happened
        baseline_click_rate = _mean([_safe_float(r["clicked_flag"]) for r in s11_baseline_sp])
        current_click_rate = _mean([_safe_float(r["clicked_flag"]) for r in s11_current_sp])

        assert current_click_rate < baseline_click_rate, (
            f"S11: Sharepoint click rate should drop in current period. "
            f"Baseline={baseline_click_rate:.4f}, Current={current_click_rate:.4f}"
        )

    def test_s11_sharepoint_dlctr_lower_in_current(self, metric_rows):
        """Sharepoint DLCTR should be lower in current vs baseline.

        Both the zero-result forcing (40% no-click) and the 0.70x multiplier
        should pull sharepoint DLCTR down.
        """
        s11_baseline_sp = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "baseline" and r["connector_type"] == "sharepoint"
        ]
        s11_current_sp = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "current" and r["connector_type"] == "sharepoint"
        ]

        if not s11_baseline_sp or not s11_current_sp:
            pytest.skip("Not enough S11 sharepoint rows")

        baseline_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s11_baseline_sp])
        current_dlctr = _mean([_safe_float(r["dlctr_value"]) for r in s11_current_sp])

        assert current_dlctr < baseline_dlctr, (
            f"S11: Sharepoint DLCTR should drop from baseline ({baseline_dlctr:.6f}) "
            f"to current ({current_dlctr:.6f}) due to auth expiry"
        )

    def test_s11_non_sharepoint_click_rate_stable(self, metric_rows):
        """Non-sharepoint connectors should have stable click rate.

        Only sharepoint is affected by the auth expiry.
        """
        s11_baseline_other = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "baseline" and r["connector_type"] != "sharepoint"
        ]
        s11_current_other = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "current" and r["connector_type"] != "sharepoint"
        ]

        if not s11_baseline_other or not s11_current_other:
            pytest.skip("Not enough S11 non-sharepoint rows")

        baseline_click_rate = _mean([_safe_float(r["clicked_flag"]) for r in s11_baseline_other])
        current_click_rate = _mean([_safe_float(r["clicked_flag"]) for r in s11_current_other])

        # Non-sharepoint should be stable — allow 10% relative tolerance
        if baseline_click_rate > 0:
            relative_change = abs(current_click_rate - baseline_click_rate) / baseline_click_rate
            assert relative_change < 0.10, (
                f"S11: Non-sharepoint click rate should be stable. "
                f"Baseline={baseline_click_rate:.4f}, Current={current_click_rate:.4f}, "
                f"Change={relative_change:.2%}"
            )

    def test_s11_sharepoint_zero_result_rate_elevated_in_current(self, metric_rows):
        """Sharepoint should have more zero-result (no-click) rows in current.

        We measure zero-result rate as 1 - click_rate. In the current period,
        sharepoint's zero-result rate should be higher than baseline.
        """
        s11_baseline_sp = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "baseline" and r["connector_type"] == "sharepoint"
        ]
        s11_current_sp = [
            r for r in metric_rows
            if r["scenario_id"] == "S11" and r["period"] == "current" and r["connector_type"] == "sharepoint"
        ]

        if not s11_baseline_sp or not s11_current_sp:
            pytest.skip("Not enough S11 sharepoint rows")

        baseline_zero_rate = 1.0 - _mean([_safe_float(r["clicked_flag"]) for r in s11_baseline_sp])
        current_zero_rate = 1.0 - _mean([_safe_float(r["clicked_flag"]) for r in s11_current_sp])

        assert current_zero_rate > baseline_zero_rate, (
            f"S11: Sharepoint zero-result rate should increase in current period. "
            f"Baseline zero-result={baseline_zero_rate:.4f}, "
            f"Current zero-result={current_zero_rate:.4f}"
        )


# ===========================================================================
# Test Class: S12 LLM Migration SAIN Success Validation
# ===========================================================================


class TestS12LLMMigrationSainSuccess:
    """S12: Verify that sain_success is lower for ai_on tenants in current period.

    The scenario simulates a model migration that degrades AI answer quality.
    The effect should be localized to ai_on tenants; ai_off tenants should
    be completely unaffected.

    Adjustments: trigger_rate * 1.05, success_rate * 0.92 for ai_on in current.
    """

    def test_s12_ai_on_sain_success_drops_in_current(self, metric_rows):
        """ai_on tenants should have lower sain_success rate in current period.

        The 0.92x multiplier on success probability should produce a measurable
        drop in the sain_success rate for ai_on rows.
        """
        s12_baseline_ai_on = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "baseline" and r["ai_enablement"] == "ai_on"
        ]
        s12_current_ai_on = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "current" and r["ai_enablement"] == "ai_on"
        ]

        if not s12_baseline_ai_on or not s12_current_ai_on:
            pytest.skip("Not enough S12 ai_on rows")

        # sain_success is a binary column (0 or 1); mean gives the rate
        baseline_success_rate = _mean([_safe_float(r["sain_success"]) for r in s12_baseline_ai_on])
        current_success_rate = _mean([_safe_float(r["sain_success"]) for r in s12_current_ai_on])

        assert current_success_rate < baseline_success_rate, (
            f"S12: ai_on sain_success should drop in current period. "
            f"Baseline={baseline_success_rate:.4f}, Current={current_success_rate:.4f}"
        )

    def test_s12_ai_off_sain_success_stable(self, metric_rows):
        """ai_off tenants should have stable sain_success rate across periods.

        The LLM migration only affects ai_on; ai_off is the control group.
        """
        s12_baseline_ai_off = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "baseline" and r["ai_enablement"] == "ai_off"
        ]
        s12_current_ai_off = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "current" and r["ai_enablement"] == "ai_off"
        ]

        if not s12_baseline_ai_off or not s12_current_ai_off:
            pytest.skip("Not enough S12 ai_off rows")

        baseline_success_rate = _mean([_safe_float(r["sain_success"]) for r in s12_baseline_ai_off])
        current_success_rate = _mean([_safe_float(r["sain_success"]) for r in s12_current_ai_off])

        # ai_off should be stable — allow 15% relative tolerance (SAIN has
        # high variance since trigger rate ~22% and success rate ~62% means
        # only ~14% of rows have sain_success=1)
        if baseline_success_rate > 0:
            relative_change = abs(current_success_rate - baseline_success_rate) / baseline_success_rate
            assert relative_change < 0.15, (
                f"S12: ai_off sain_success should be stable. "
                f"Baseline={baseline_success_rate:.4f}, Current={current_success_rate:.4f}, "
                f"Change={relative_change:.2%}"
            )

    def test_s12_ai_on_current_success_lower_than_ai_off_current(self, metric_rows):
        """In the current period, ai_on sain_success should be lower than ai_off.

        After the LLM migration, ai_on tenants have degraded AI answer quality
        while ai_off tenants are completely unaffected. Since ai_off has the
        same baseline success rate and is not degraded, ai_on's rate should be
        lower in the current period.

        Note: This comparison might be affected by the fact that ai_on tenants
        inherently have different SAIN interaction patterns. We check that the
        DROP for ai_on is larger than for ai_off (a difference-in-differences approach).
        """
        s12_baseline_on = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "baseline" and r["ai_enablement"] == "ai_on"
        ]
        s12_current_on = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "current" and r["ai_enablement"] == "ai_on"
        ]
        s12_baseline_off = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "baseline" and r["ai_enablement"] == "ai_off"
        ]
        s12_current_off = [
            r for r in metric_rows
            if r["scenario_id"] == "S12" and r["period"] == "current" and r["ai_enablement"] == "ai_off"
        ]

        if not all([s12_baseline_on, s12_current_on, s12_baseline_off, s12_current_off]):
            pytest.skip("Not enough S12 rows for diff-in-diff")

        # Compute the change for each group
        ai_on_baseline = _mean([_safe_float(r["sain_success"]) for r in s12_baseline_on])
        ai_on_current = _mean([_safe_float(r["sain_success"]) for r in s12_current_on])
        ai_on_delta = ai_on_current - ai_on_baseline

        ai_off_baseline = _mean([_safe_float(r["sain_success"]) for r in s12_baseline_off])
        ai_off_current = _mean([_safe_float(r["sain_success"]) for r in s12_current_off])
        ai_off_delta = ai_off_current - ai_off_baseline

        # ai_on should have a LARGER drop (more negative delta) than ai_off
        assert ai_on_delta < ai_off_delta, (
            f"S12: ai_on success drop ({ai_on_delta:.4f}) should be larger (more negative) "
            f"than ai_off change ({ai_off_delta:.4f}), showing localized LLM impact"
        )
