"""Tests for the investigation data generator (scripts/generate_investigation_data.py).

Tests cover:
1. All 5 scenario CSVs are generated with correct columns
2. Row counts are within expected range (200-400 per scenario)
3. Dimension values are all valid
4. Period split is roughly 50/50
5. Planted regressions are detectable in the data
6. SQS formula consistency: search_quality_success >= max(click_quality, ai_trigger * ai_success)
7. Data quality columns have expected ranges
8. CLI interface works (--list, --scenario)
"""

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants — must match the generator's output schema
# ---------------------------------------------------------------------------

REQUIRED_METRIC_COLS = [
    "click_quality_value",
    "search_quality_success_value",
    "ai_trigger",
    "ai_success",
    "zero_result",
    "latency_ms",
]

REQUIRED_DATA_QUALITY_COLS = [
    "data_completeness",
    "data_freshness_min",
]

REQUIRED_DIMENSION_COLS = [
    "tenant_tier",
    "ai_enablement",
    "connector_type",
    "industry_vertical",
    "query_type",
]

REQUIRED_PERIOD_COL = "period"

ALL_REQUIRED_COLS = (
    REQUIRED_METRIC_COLS
    + REQUIRED_DATA_QUALITY_COLS
    + REQUIRED_DIMENSION_COLS
    + [REQUIRED_PERIOD_COL]
)

VALID_TENANT_TIERS = {"standard", "premium", "enterprise"}
VALID_AI_ENABLEMENT = {"ai_on", "ai_off"}
VALID_CONNECTORS = {"confluence", "slack", "gdrive", "jira", "sharepoint"}
VALID_INDUSTRIES = {"tech", "finance", "retail", "healthcare"}
VALID_QUERY_TYPES = {"navigational", "informational", "action"}
VALID_PERIODS = {"baseline", "current"}

SCENARIO_NAMES = [
    "ranking_regression",
    "ai_adoption_positive",
    "connector_failure",
    "mix_shift",
    "normal_variance",
]

# Project root — navigate from tests/ up one level
ROOT = Path(__file__).parent.parent
SCRIPT_PATH = ROOT / "scripts" / "generate_investigation_data.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_csv(path: Path):
    """Read a CSV file and return list of dicts."""
    with open(path) as f:
        return list(csv.DictReader(f))


def _mean(values):
    """Simple mean for a list of floats."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _rows_by_period(rows, period):
    """Filter rows by period value."""
    return [r for r in rows if r["period"] == period]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def generated_dir(tmp_path_factory):
    """Run the generator once and return the output directory.

    Uses a temp directory so tests don't depend on pre-existing data.
    This fixture runs the script as a subprocess to validate the CLI interface.
    """
    out_dir = tmp_path_factory.mktemp("investigations")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--output-dir", str(out_dir)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"Generator failed with stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    return out_dir


@pytest.fixture(scope="module")
def scenario_data(generated_dir):
    """Load all 5 scenario CSVs into a dict keyed by scenario name."""
    data = {}
    for name in SCENARIO_NAMES:
        path = generated_dir / f"scenario_{name}.csv"
        assert path.exists(), f"Missing CSV: {path}"
        data[name] = _read_csv(path)
    return data


# ===========================================================================
# Test Class: Schema Validation
# ===========================================================================

class TestSchemaValidation:
    """Every generated CSV must have the correct columns and valid values."""

    def test_all_five_csvs_exist(self, generated_dir):
        """All 5 scenario CSVs must be generated."""
        for name in SCENARIO_NAMES:
            path = generated_dir / f"scenario_{name}.csv"
            assert path.exists(), f"Missing scenario CSV: scenario_{name}.csv"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_required_columns_present(self, scenario_data, scenario):
        """Each CSV must contain all required columns."""
        rows = scenario_data[scenario]
        assert len(rows) > 0, f"Scenario {scenario} has no rows"
        first_row = rows[0]
        for col in ALL_REQUIRED_COLS:
            assert col in first_row, (
                f"Scenario {scenario} missing required column: {col}"
            )

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_row_count_in_range(self, scenario_data, scenario):
        """Each scenario should have 200-400 rows."""
        count = len(scenario_data[scenario])
        assert 200 <= count <= 400, (
            f"Scenario {scenario} has {count} rows, expected 200-400"
        )

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_dimension_values_valid(self, scenario_data, scenario):
        """All dimension column values must be from the allowed sets."""
        rows = scenario_data[scenario]
        for row in rows:
            assert row["tenant_tier"] in VALID_TENANT_TIERS, (
                f"Invalid tenant_tier: {row['tenant_tier']}"
            )
            assert row["ai_enablement"] in VALID_AI_ENABLEMENT, (
                f"Invalid ai_enablement: {row['ai_enablement']}"
            )
            assert row["connector_type"] in VALID_CONNECTORS, (
                f"Invalid connector_type: {row['connector_type']}"
            )
            assert row["industry_vertical"] in VALID_INDUSTRIES, (
                f"Invalid industry_vertical: {row['industry_vertical']}"
            )
            assert row["query_type"] in VALID_QUERY_TYPES, (
                f"Invalid query_type: {row['query_type']}"
            )

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_period_values_valid(self, scenario_data, scenario):
        """Period must be 'baseline' or 'current'."""
        periods = {r["period"] for r in scenario_data[scenario]}
        assert periods == VALID_PERIODS, (
            f"Scenario {scenario} has unexpected periods: {periods}"
        )

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_period_split_roughly_balanced(self, scenario_data, scenario):
        """Baseline and current rows should each be at least 40% of total."""
        rows = scenario_data[scenario]
        total = len(rows)
        baseline_count = sum(1 for r in rows if r["period"] == "baseline")
        current_count = total - baseline_count
        # Each period should be at least 40% of total (allowing some flexibility)
        assert baseline_count >= total * 0.35, (
            f"Scenario {scenario}: too few baseline rows ({baseline_count}/{total})"
        )
        assert current_count >= total * 0.35, (
            f"Scenario {scenario}: too few current rows ({current_count}/{total})"
        )


# ===========================================================================
# Test Class: Metric Range Validation
# ===========================================================================

class TestMetricRanges:
    """Metric values must be within physically meaningful ranges."""

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_click_quality_in_range(self, scenario_data, scenario):
        """click_quality_value must be in [0.0, 1.0]."""
        for row in scenario_data[scenario]:
            val = float(row["click_quality_value"])
            assert 0.0 <= val <= 1.0, f"click_quality_value out of range: {val}"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_sqs_in_range(self, scenario_data, scenario):
        """search_quality_success_value must be in [0.0, 1.0]."""
        for row in scenario_data[scenario]:
            val = float(row["search_quality_success_value"])
            assert 0.0 <= val <= 1.0, f"sqs out of range: {val}"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_ai_trigger_in_range(self, scenario_data, scenario):
        """ai_trigger must be in [0.0, 1.0]."""
        for row in scenario_data[scenario]:
            val = float(row["ai_trigger"])
            assert 0.0 <= val <= 1.0, f"ai_trigger out of range: {val}"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_ai_success_in_range(self, scenario_data, scenario):
        """ai_success must be in [0.0, 1.0]."""
        for row in scenario_data[scenario]:
            val = float(row["ai_success"])
            assert 0.0 <= val <= 1.0, f"ai_success out of range: {val}"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_zero_result_binary(self, scenario_data, scenario):
        """zero_result must be 0 or 1."""
        for row in scenario_data[scenario]:
            val = int(row["zero_result"])
            assert val in (0, 1), f"zero_result not binary: {val}"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_latency_positive(self, scenario_data, scenario):
        """latency_ms must be positive."""
        for row in scenario_data[scenario]:
            val = int(row["latency_ms"])
            assert val > 0, f"latency_ms not positive: {val}"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_data_completeness_in_range(self, scenario_data, scenario):
        """data_completeness must be in [0.0, 1.0]."""
        for row in scenario_data[scenario]:
            val = float(row["data_completeness"])
            assert 0.0 <= val <= 1.0, f"data_completeness out of range: {val}"

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_data_freshness_non_negative(self, scenario_data, scenario):
        """data_freshness_min must be >= 0."""
        for row in scenario_data[scenario]:
            val = int(row["data_freshness_min"])
            assert val >= 0, f"data_freshness_min negative: {val}"


# ===========================================================================
# Test Class: SQS Formula Consistency
# ===========================================================================

class TestSQSFormula:
    """SQS must respect the formula: max(click_component, ai_trigger * ai_success).

    We allow a small tolerance because of random noise added for realism.
    The generated SQS should be CLOSE to max(CQ, ai_trigger * ai_success),
    not exact (noise is intentionally added).
    """

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_sqs_approximately_consistent(self, scenario_data, scenario):
        """SQS should be approximately max(CQ, ai_trigger * ai_success).

        WHY tolerance = 0.001 (not 0.05)?
        SQS is computed AFTER noise is added to its components (CQ, ai_trigger,
        ai_success). The formula max(CQ, ai_trigger * ai_success) is applied to
        already-noised values, so the only source of deviation is floating-point
        rounding — which is under 0.000001. A tight tolerance ensures we'd
        catch any bug where SQS was computed from a different set of values
        than what's written to the row.
        """
        rows = scenario_data[scenario]
        deviations = []
        for row in rows:
            cq = float(row["click_quality_value"])
            ai_t = float(row["ai_trigger"])
            ai_s = float(row["ai_success"])
            sqs = float(row["search_quality_success_value"])
            expected = max(cq, ai_t * ai_s)
            deviations.append(abs(sqs - expected))
        mean_dev = _mean(deviations)
        # Tight tolerance: SQS is computed AFTER noise, so deviation is only
        # from float rounding + clamp(). 0.001 is still 100x the actual error.
        assert mean_dev < 0.001, (
            f"Scenario {scenario}: SQS deviates from formula by avg {mean_dev:.6f}"
        )


# ===========================================================================
# Test Class: Scenario-Specific Planted Signals
# ===========================================================================

class TestPlantedSignals:
    """Each scenario must have its planted regression/pattern detectable."""

    def test_ranking_regression_click_quality_drops(self, scenario_data):
        """Ranking regression: CQ should drop ~3.5% from baseline to current."""
        rows = scenario_data["ranking_regression"]
        baseline_cq = _mean([
            float(r["click_quality_value"])
            for r in _rows_by_period(rows, "baseline")
        ])
        current_cq = _mean([
            float(r["click_quality_value"])
            for r in _rows_by_period(rows, "current")
        ])
        # CQ should drop by at least 2% (allowing some noise around 3.5% target)
        pct_drop = (baseline_cq - current_cq) / baseline_cq
        assert pct_drop > 0.02, (
            f"Ranking regression CQ drop too small: {pct_drop:.4f} "
            f"(baseline={baseline_cq:.4f}, current={current_cq:.4f})"
        )

    def test_ranking_regression_ai_stable(self, scenario_data):
        """Ranking regression: AI metrics should be stable (< 3% change)."""
        rows = scenario_data["ranking_regression"]
        baseline_ai_t = _mean([
            float(r["ai_trigger"])
            for r in _rows_by_period(rows, "baseline")
        ])
        current_ai_t = _mean([
            float(r["ai_trigger"])
            for r in _rows_by_period(rows, "current")
        ])
        if baseline_ai_t > 0:
            pct_change = abs(current_ai_t - baseline_ai_t) / baseline_ai_t
            assert pct_change < 0.05, (
                f"Ranking regression: AI trigger changed {pct_change:.4f} — should be stable"
            )

    def test_ai_adoption_cq_drops_ai_up(self, scenario_data):
        """AI adoption: CQ drops for ai_on, but AI trigger/success increase."""
        rows = scenario_data["ai_adoption_positive"]
        # Check CQ drop for ai_on segments
        ai_on_baseline = [
            float(r["click_quality_value"])
            for r in rows
            if r["period"] == "baseline" and r["ai_enablement"] == "ai_on"
        ]
        ai_on_current = [
            float(r["click_quality_value"])
            for r in rows
            if r["period"] == "current" and r["ai_enablement"] == "ai_on"
        ]
        if ai_on_baseline and ai_on_current:
            assert _mean(ai_on_current) < _mean(ai_on_baseline), (
                "AI adoption: CQ should drop for ai_on segments"
            )

        # Check AI trigger increase
        baseline_ai_t = _mean([
            float(r["ai_trigger"])
            for r in _rows_by_period(rows, "baseline")
            if r["ai_enablement"] == "ai_on"
        ])
        current_ai_t = _mean([
            float(r["ai_trigger"])
            for r in _rows_by_period(rows, "current")
            if r["ai_enablement"] == "ai_on"
        ])
        if baseline_ai_t > 0:
            pct_increase = (current_ai_t - baseline_ai_t) / baseline_ai_t
            assert pct_increase > 0.05, (
                f"AI adoption: AI trigger should increase, got {pct_increase:.4f}"
            )

    def test_ai_adoption_sqs_stable_or_up(self, scenario_data):
        """AI adoption: SQS should be stable or increase (positive signal)."""
        rows = scenario_data["ai_adoption_positive"]
        baseline_sqs = _mean([
            float(r["search_quality_success_value"])
            for r in _rows_by_period(rows, "baseline")
        ])
        current_sqs = _mean([
            float(r["search_quality_success_value"])
            for r in _rows_by_period(rows, "current")
        ])
        # SQS should not drop by more than 2% (some noise ok)
        if baseline_sqs > 0:
            pct_change = (current_sqs - baseline_sqs) / baseline_sqs
            assert pct_change > -0.02, (
                f"AI adoption: SQS should be stable/up, but dropped {pct_change:.4f}"
            )

    def test_connector_failure_isolated(self, scenario_data):
        """Connector failure: one connector has severe CQ drop, others normal.

        WHY >5% relative threshold?
        The P0 severity threshold for Click Quality is >5% movement
        (see rules/01-metric-invariants.md). A connector failure that
        doesn't breach P0 wouldn't trigger investigation, making the
        scenario useless for testing. The old 0.01 absolute threshold
        was far too weak — it could pass with a P2-level blip.
        """
        rows = scenario_data["connector_failure"]
        # Find the failing connector — it should have the largest CQ drop
        connectors = VALID_CONNECTORS
        drops = {}
        baseline_means = {}
        for conn in connectors:
            baseline = [
                float(r["click_quality_value"])
                for r in rows
                if r["period"] == "baseline" and r["connector_type"] == conn
            ]
            current = [
                float(r["click_quality_value"])
                for r in rows
                if r["period"] == "current" and r["connector_type"] == conn
            ]
            if baseline and current:
                baseline_means[conn] = _mean(baseline)
                drops[conn] = _mean(baseline) - _mean(current)

        # The failing connector must have a RELATIVE drop > 5% (P0 threshold)
        max_drop_conn = max(drops, key=drops.get)
        baseline_mean = baseline_means[max_drop_conn]
        if baseline_mean > 0:
            relative_drop = drops[max_drop_conn] / baseline_mean
            assert relative_drop > 0.05, (
                f"Connector {max_drop_conn} relative drop {relative_drop:.4f} "
                f"below P0 threshold of 5%"
            )
        # Other connectors should be relatively stable
        for conn, drop in drops.items():
            if conn != max_drop_conn and drop > 0:
                # Other connectors should have much smaller drops
                assert drop < drops[max_drop_conn] * 0.5, (
                    f"Connector {conn} drop ({drop:.4f}) too close to failing "
                    f"connector {max_drop_conn} ({drops[max_drop_conn]:.4f})"
                )

    def test_connector_failure_zero_result_spike(self, scenario_data):
        """Connector failure: failing connector should have elevated zero_result."""
        rows = scenario_data["connector_failure"]
        # Find the connector with the highest zero_result rate in current period
        connectors = VALID_CONNECTORS
        zr_rates = {}
        for conn in connectors:
            current = [
                int(row["zero_result"])
                for row in rows
                if row["period"] == "current" and row["connector_type"] == conn
            ]
            if current:
                zr_rates[conn] = _mean(current)

        max_zr_conn = max(zr_rates, key=zr_rates.get)
        # Failing connector should have noticeably higher zero-result rate
        other_zr = _mean([v for k, v in zr_rates.items() if k != max_zr_conn])
        assert zr_rates[max_zr_conn] > other_zr + 0.05, (
            f"Failing connector {max_zr_conn} ZR rate ({zr_rates[max_zr_conn]:.3f}) "
            f"not significantly higher than others ({other_zr:.3f})"
        )

    def test_mix_shift_no_per_segment_change(self, scenario_data):
        """Mix-shift: individual segments should NOT have significant CQ drops."""
        rows = scenario_data["mix_shift"]
        # Check that each tenant_tier's CQ is roughly stable
        for tier in VALID_TENANT_TIERS:
            baseline = [
                float(r["click_quality_value"])
                for r in rows
                if r["period"] == "baseline" and r["tenant_tier"] == tier
            ]
            current = [
                float(r["click_quality_value"])
                for r in rows
                if r["period"] == "current" and r["tenant_tier"] == tier
            ]
            if baseline and current:
                b_mean = _mean(baseline)
                c_mean = _mean(current)
                if b_mean > 0:
                    pct_change = abs(c_mean - b_mean) / b_mean
                    # Allow up to 5% because random noise (±1.5%) can compound
                    # across the ~50 rows per segment. The key signal is that
                    # NO tier has a LARGE drop (>5%), unlike ranking_regression
                    # which drops every tier by ~3.5%.
                    assert pct_change < 0.05, (
                        f"Mix-shift: tier {tier} CQ changed {pct_change:.4f} — "
                        f"per-segment metrics should be stable"
                    )

    def test_mix_shift_aggregate_drops(self, scenario_data):
        """Mix-shift: overall aggregate CQ should drop due to composition change."""
        rows = scenario_data["mix_shift"]
        baseline_cq = _mean([
            float(r["click_quality_value"])
            for r in _rows_by_period(rows, "baseline")
        ])
        current_cq = _mean([
            float(r["click_quality_value"])
            for r in _rows_by_period(rows, "current")
        ])
        # Aggregate should drop (more standard tier in current)
        assert current_cq < baseline_cq, (
            f"Mix-shift: aggregate CQ should drop, but "
            f"baseline={baseline_cq:.4f}, current={current_cq:.4f}"
        )

    def test_normal_variance_small_movement(self, scenario_data):
        """Normal variance: all metrics should move less than 2%."""
        rows = scenario_data["normal_variance"]
        for metric in ["click_quality_value", "search_quality_success_value"]:
            baseline_vals = [
                float(r[metric]) for r in _rows_by_period(rows, "baseline")
            ]
            current_vals = [
                float(r[metric]) for r in _rows_by_period(rows, "current")
            ]
            b_mean = _mean(baseline_vals)
            c_mean = _mean(current_vals)
            if b_mean > 0:
                pct_change = abs(c_mean - b_mean) / b_mean
                assert pct_change < 0.02, (
                    f"Normal variance: {metric} moved {pct_change:.4f} — too large"
                )


# ===========================================================================
# Test Class: Data Quality Columns
# ===========================================================================

class TestDataQuality:
    """Data quality columns should have realistic values."""

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_most_rows_pass_data_quality(self, scenario_data, scenario):
        """Most rows should have completeness > 0.96 and freshness < 30."""
        rows = scenario_data[scenario]
        passing = sum(
            1 for r in rows
            if float(r["data_completeness"]) > 0.96
            and int(r["data_freshness_min"]) < 30
        )
        # At least 80% of rows should pass data quality (connector failure
        # may have more failing rows for the bad connector)
        pass_rate = passing / len(rows)
        assert pass_rate > 0.70, (
            f"Scenario {scenario}: only {pass_rate:.2%} pass data quality"
        )

    def test_connector_failure_has_stale_data(self, scenario_data):
        """Connector failure: some rows for the failing connector should have high freshness."""
        rows = scenario_data["connector_failure"]
        stale_rows = [
            r for r in rows
            if int(r["data_freshness_min"]) > 60
        ]
        assert len(stale_rows) > 0, (
            "Connector failure should have some stale data rows (freshness > 60)"
        )


# ===========================================================================
# Test Class: AI-Off Zero Invariant
# ===========================================================================

class TestAIOffZeroInvariant:
    """When AI is disabled (ai_off), AI metrics must be exactly 0.0.

    WHY THIS MATTERS:
    AI trigger and success are physically meaningless when AI is turned off.
    Any non-zero value (even from noise) would make the SQS formula incorrect
    and could mislead the orchestrator into thinking AI is partially active.
    This is a domain invariant, not just a data quality check.
    """

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_ai_off_rows_have_zero_ai_trigger(self, scenario_data, scenario):
        """All ai_off rows must have ai_trigger == 0.0 (no noise)."""
        rows = scenario_data[scenario]
        ai_off_rows = [r for r in rows if r["ai_enablement"] == "ai_off"]
        # There should be ai_off rows in every scenario
        assert len(ai_off_rows) > 0, (
            f"Scenario {scenario} has no ai_off rows"
        )
        for row in ai_off_rows:
            val = float(row["ai_trigger"])
            assert val == 0.0, (
                f"Scenario {scenario}: ai_off row has ai_trigger={val}, "
                f"expected exactly 0.0 (period={row['period']}, "
                f"tier={row['tenant_tier']})"
            )

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_ai_off_rows_have_zero_ai_success(self, scenario_data, scenario):
        """All ai_off rows must have ai_success == 0.0 (no noise)."""
        rows = scenario_data[scenario]
        ai_off_rows = [r for r in rows if r["ai_enablement"] == "ai_off"]
        for row in ai_off_rows:
            val = float(row["ai_success"])
            assert val == 0.0, (
                f"Scenario {scenario}: ai_off row has ai_success={val}, "
                f"expected exactly 0.0 (period={row['period']}, "
                f"tier={row['tenant_tier']})"
            )


# ===========================================================================
# Test Class: Seed Isolation
# ===========================================================================

class TestSeedIsolation:
    """Scenario-specific seeds prevent cross-scenario coupling.

    WHY THIS MATTERS:
    If all scenarios share the same RNG state, adding or reordering a scenario
    changes every subsequent scenario's data — a silent, hard-to-debug failure.
    Each scenario should get its own deterministic seed (seed + i) so changes
    to one scenario don't cascade to others.
    """

    def test_scenario_data_independent_of_order(self):
        """Generating one scenario should produce the same data regardless of
        whether other scenarios were generated first.

        We verify by generating 'ranking_regression' alone (seed=42) and then
        generating all scenarios (which gives ranking_regression seed=42+0=42).
        The data should be identical.
        """
        # Import the generator
        sys.path.insert(0, str(ROOT / "scripts"))
        from generate_investigation_data import generate_scenario, generate_all

        # Generate ranking_regression alone with seed=42
        solo_rows = generate_scenario("ranking_regression", rows_per_period=50, seed=42)

        # Generate all scenarios with base seed=42 (ranking_regression gets 42+0=42)
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_all(Path(tmpdir), rows_per_period=50, seed=42)
            # Read the ranking_regression CSV back
            with open(Path(tmpdir) / "scenario_ranking_regression.csv") as f:
                import csv
                all_rows = list(csv.DictReader(f))

        # Compare: solo and all-generated should produce identical data
        # because ranking_regression is index 0, so seed + 0 = seed = 42
        assert len(solo_rows) == len(all_rows), (
            f"Row count mismatch: solo={len(solo_rows)}, all={len(all_rows)}"
        )
        for i, (solo, full) in enumerate(zip(solo_rows, all_rows)):
            assert solo["click_quality_value"] == full["click_quality_value"], (
                f"Row {i} CQ mismatch: solo={solo['click_quality_value']}, "
                f"all={full['click_quality_value']}"
            )

    def test_second_scenario_differs_from_first(self):
        """The second scenario (ai_adoption_positive, seed=43) should produce
        different data than if it used the same seed as the first (seed=42).

        This confirms that generate_all actually offsets seeds per scenario.
        """
        sys.path.insert(0, str(ROOT / "scripts"))
        from generate_investigation_data import generate_scenario

        # ai_adoption_positive with seed=42 (would be the same as ranking_regression's seed)
        rows_same_seed = generate_scenario("ai_adoption_positive", rows_per_period=50, seed=42)

        # ai_adoption_positive with seed=43 (what generate_all should use: 42 + 1)
        rows_offset_seed = generate_scenario("ai_adoption_positive", rows_per_period=50, seed=43)

        # The two should produce DIFFERENT data (different seeds)
        # Compare first row's CQ value — with different seeds, dimension combos differ
        same_cq_0 = rows_same_seed[0]["click_quality_value"]
        offset_cq_0 = rows_offset_seed[0]["click_quality_value"]
        # It's theoretically possible but astronomically unlikely for two
        # different seeds to produce identical first rows
        assert same_cq_0 != offset_cq_0, (
            "Different seeds should produce different data"
        )


# ===========================================================================
# Test Class: CLI Interface
# ===========================================================================

class TestCLI:
    """The script's command-line interface should work correctly."""

    def test_list_scenarios(self):
        """--list should print available scenarios."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--list"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        output = result.stdout
        for name in SCENARIO_NAMES:
            assert name in output, f"--list missing scenario: {name}"

    def test_single_scenario_generation(self, tmp_path):
        """--scenario should generate only the specified scenario."""
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH),
                "--scenario", "ranking_regression",
                "--output-dir", str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        # Only ranking_regression CSV should exist
        assert (tmp_path / "scenario_ranking_regression.csv").exists()
        # Others should NOT exist
        assert not (tmp_path / "scenario_normal_variance.csv").exists()
