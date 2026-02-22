# Search Metric Analyzer v1 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Claude Code skill + Python analysis toolkit that diagnoses Enterprise Search metric movements on synthetic data and generates template-based Slack messages and reports.

**Architecture:** Claude Code orchestrates a 4-step diagnostic workflow (Intake → Decompose → Validate → Synthesize) using Python analysis scripts. Domain Expert Skills provides always-on context. Dual-judge eval (LLM-as-judge + DS Analysis Review Agent) validates output quality.

**Tech Stack:** Python 3.10+ (stdlib + PyYAML for knowledge files), pytest for tests, Claude Code skills (markdown)

**Design Doc:** `docs/plans/2026-02-21-search-metric-analyzer-design.md`

**Working Directory:** `/Users/surahli/Documents/New project/Search_Metric_Analyzer/`

---

## Task Overview

| Task | Component | Depends On | Estimated Steps |
|------|-----------|-----------|----------------|
| 1 | Project scaffolding & config | — | 8 |
| 2 | Knowledge encoding (YAML) | 1 | 12 |
| 3 | decompose.py — dimensional decomposition + mix-shift | 1, 2 | 18 |
| 4 | anomaly.py — anomaly detection vs baselines | 1, 2 | 14 |
| 5 | diagnose.py — 4 validation checks + confidence | 3, 4 | 16 |
| 6 | formatter.py — Slack + report template generation | 5 | 14 |
| 7 | Extend synthetic data generator (13 Enterprise scenarios) | 2 | 20 |
| 8 | Claude Code skill file | 2, 3, 4, 5, 6 | 10 |
| 9 | Eval framework (scoring specs + MVE runner) | 6, 7 | 14 |
| 10 | End-to-end integration test | All above | 10 |

**Parallel opportunities:** Tasks 3 & 4 can run in parallel. Task 7 can start after Task 2.

---

## Task 1: Project Scaffolding & Config

**Files:**
- Create: `CLAUDE.md`
- Create: `requirements.txt`
- Create: `tools/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: directories `eval/scoring_specs/`, `eval/results/`, `templates/`

**Step 1: Create requirements.txt**

```txt
# Search Metric Analyzer v1 — minimal dependencies
pyyaml>=6.0       # Parse metric_definitions.yaml and historical_patterns.yaml
pytest>=7.0        # Test runner
pytest-cov>=4.0    # Coverage reporting
```

**Step 2: Create project-level CLAUDE.md**

```markdown
# Search Metric Analyzer

## Project Context
Enterprise Search metric diagnosis tool. Runs as a Claude Code skill + Python toolkit.
Designed for a team of 2 Senior DSs debugging metric movements for Eng Leads.

## Domain
Enterprise Search (like Glean). Key concepts:
- Tenant tiers (standard/premium/enterprise), AI enablement, connector types
- Metrics: Click Quality, Search Quality Success, AI trigger/success, zero-result rate, latency
- Search Quality Success formula: max(click_component, ai_trigger * ai_success)
- AI answers and Click Quality have INVERSE co-movement (more AI answers = fewer clicks = expected)

## Code Conventions
- Python 3.10+, stdlib + PyYAML only
- Heavy comments explaining WHY, not just WHAT
- Small functions, small files
- All tools are CLI scripts: `python tools/decompose.py --input data.csv`
- Output is always JSON to stdout (Claude Code reads it)

## Key Files
- Design doc: `docs/plans/2026-02-21-search-metric-analyzer-design.md`
- Metric definitions: `data/knowledge/metric_definitions.yaml`
- Historical patterns: `data/knowledge/historical_patterns.yaml`
- Skill file: `skills/search-metric-analyzer.md`

## Testing
Run: `pytest tests/ -v`
All tools have unit tests in `tests/test_<tool>.py`
```

**Step 3: Create tools/__init__.py**

```python
"""Search Metric Analyzer — Python Analysis Toolkit.

Tools are designed to be called as CLI scripts by Claude Code.
Each tool reads input (CSV/JSON), performs analysis, and outputs JSON to stdout.
"""
```

**Step 4: Create tests/__init__.py and tests/conftest.py**

`tests/__init__.py`: empty file

`tests/conftest.py`:
```python
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
    # 10 rows for "current" period with a Click Quality drop in JP/Standard tier
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
            "click_quality_value": 0.280,
            "search_quality_success_value": 0.378,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            "zero_result": 0,
            "latency_ms": 200,
            "ai_answer_shown": 0,
            "data_freshness_min": 10,
            "data_completeness": 0.995,
        })

    # Current period: Click Quality drops for standard tier
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
            # Standard tier Click Quality drops from 0.280 to 0.245 (-12.5%)
            "click_quality_value": 0.245 if is_standard else 0.280,
            "search_quality_success_value": 0.340 if is_standard else 0.378,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            "zero_result": 0,
            "latency_ms": 200,
            "ai_answer_shown": 0,
            "data_freshness_min": 10,
            "data_completeness": 0.995,
        })

    return baseline_rows + current_rows


@pytest.fixture
def sample_mix_shift_rows():
    """Rows where aggregate Click Quality drops due to mix-shift, not behavioral change.

    Baseline: 50% standard (Click Quality=0.245), 50% premium (Click Quality=0.295)
    Current:  70% standard, 30% premium (same per-segment Click Quality, lower aggregate)
    """
    baseline = []
    current = []

    # Baseline: 10 standard + 10 premium
    for i in range(10):
        baseline.append({
            "period": "baseline",
            "tenant_tier": "standard",
            "click_quality_value": 0.245,
            "search_quality_success_value": 0.340,
            "query_count": 100,
        })
    for i in range(10):
        baseline.append({
            "period": "baseline",
            "tenant_tier": "premium",
            "click_quality_value": 0.295,
            "search_quality_success_value": 0.390,
            "query_count": 100,
        })

    # Current: 14 standard + 6 premium (same per-segment values)
    for i in range(14):
        current.append({
            "period": "current",
            "tenant_tier": "standard",
            "click_quality_value": 0.245,
            "search_quality_success_value": 0.340,
            "query_count": 100,
        })
    for i in range(6):
        current.append({
            "period": "current",
            "tenant_tier": "premium",
            "click_quality_value": 0.295,
            "search_quality_success_value": 0.390,
            "query_count": 100,
        })

    return baseline + current
```

**Step 5: Create directory structure**

```bash
mkdir -p eval/scoring_specs eval/results templates data/knowledge
```

**Step 6: Install dependencies**

```bash
cd "/Users/surahli/Documents/New project/Search_Metric_Analyzer"
pip install -r requirements.txt
```

**Step 7: Run pytest to verify setup**

Run: `pytest tests/ -v`
Expected: 0 tests collected, no errors (clean setup)

**Step 8: Commit**

```bash
git add CLAUDE.md requirements.txt tools/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold project structure with test fixtures and config"
```

---

## Task 2: Knowledge Encoding (YAML)

**Files:**
- Create: `data/knowledge/metric_definitions.yaml`
- Create: `data/knowledge/historical_patterns.yaml`
- Test: `tests/test_knowledge.py`

**Step 1: Write test — metric definitions load and validate**

```python
# tests/test_knowledge.py
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
        assert len(table) >= 9, "Need at least 9 co-movement patterns (from design doc)"

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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_knowledge.py -v`
Expected: FAIL (YAML files don't exist yet)

**Step 3: Create metric_definitions.yaml**

```yaml
# data/knowledge/metric_definitions.yaml
# Metric definitions for Enterprise Search — formulas, dimensions, baselines, co-movements.
# This file is the "feature store" for the diagnostic workflow.

metrics:
  click_quality:
    full_name: "Click Quality"
    formula: "sum(long_clicks * log2_discount(rank)) / impressions"
    description: >
      Primary click quality metric. Measures whether users find and engage
      with results. Discounted by position to weight higher-ranked clicks more.
    components:
      - click_through_rate
      - long_click_rate
      - position_discount
    decomposition_dimensions:
      # Enterprise-specific (check these first)
      - tenant_tier        # standard, premium, enterprise
      - ai_enablement      # ai_on, ai_off
      - industry_vertical  # tech, healthcare, finance, retail, other
      - connector_type     # confluence, slack, gdrive, jira, sharepoint, other
      # Standard dimensions
      - query_type         # navigational, informational, action
      - position_bucket    # 1, 2, 3-5, 6-10, 10+
    normal_range:
      mean: 0.280
      weekly_std: 0.015
    baseline_by_segment:
      ai_on:
        mean: 0.220
        notes: "Lower Click Quality expected — users get AI answers without clicking. This is GOOD."
      ai_off:
        mean: 0.310
      enterprise_tier:
        mean: 0.295
        notes: "More connectors, richer index, better results"
      premium_tier:
        mean: 0.280
      standard_tier:
        mean: 0.245
        notes: "Fewer connectors, sparser index"
    co_movements:
      - metric: search_quality_success
        expected_direction: same
        lag_days: 0
      - metric: ai_answer_rate
        expected_direction: inverse
        lag_days: 0
        notes: "More AI answers = fewer clicks = EXPECTED (not a regression)"
      - metric: zero_result_rate
        expected_direction: inverse
        lag_days: 0
      - metric: connector_coverage
        expected_direction: same
        lag_days: 0
    alert_thresholds:
      p0: 0.05    # >5% movement — critical
      p1: 0.02    # 2-5% — significant
      p2: 0.005   # 0.5-2% — minor

  search_quality_success:
    full_name: "Search Quality Success"
    formula: "max(search_quality_success_component_click, ai_trigger * ai_success)"
    description: >
      Composite metric combining click quality and AI answer quality.
      A query is "successful" if the user either clicked a good result
      OR got a satisfying AI answer.
    components:
      - search_quality_success_component_click    # equals click_quality
      - ai_trigger_rate
      - ai_success_rate
    decomposition_dimensions:
      - tenant_tier
      - ai_enablement
      - industry_vertical
      - connector_type
      - query_type
    normal_range:
      mean: 0.378
      weekly_std: 0.012
    alert_thresholds:
      p0: 0.04
      p1: 0.015
      p2: 0.005

  ai_trigger_rate:
    full_name: "AI Trigger Rate"
    formula: "queries_with_ai_answer_triggered / total_queries"
    description: >
      How often the AI answer system decides to show an answer.
      Only applicable to ai_enabled tenants. A drop means the system
      is showing fewer AI answers (detection problem).
    decomposition_dimensions:
      - tenant_tier
      - industry_vertical
      - query_type
    normal_range:
      mean: 0.220
      weekly_std: 0.010

  ai_success_rate:
    full_name: "AI Success Rate"
    formula: "ai_answers_marked_helpful / ai_answers_triggered"
    description: >
      Of AI answers shown, how many were helpful. A drop means AI answers
      are getting worse (quality problem), not that fewer are being shown.
    decomposition_dimensions:
      - tenant_tier
      - industry_vertical
      - query_type
    normal_range:
      mean: 0.620
      weekly_std: 0.015

  zero_result_rate:
    full_name: "Zero Result Rate"
    formula: "queries_with_zero_results / total_queries"
    description: >
      How often users get no results at all. Spikes indicate connector
      outages, index gaps, or permission issues.
    normal_range:
      mean: 0.03
      weekly_std: 0.005

  latency_p50:
    full_name: "Search Latency (p50)"
    formula: "percentile(query_latency_ms, 50)"
    description: >
      Median search response time. Spikes indicate serving issues,
      model timeouts, or infrastructure problems.
    normal_range:
      mean: 200
      weekly_std: 20

# ──────────────────────────────────────────────────────────────
# Co-Movement Diagnostic Table
# Checked at Step 1 (Intake). The pattern narrows hypothesis space
# BEFORE running any decomposition.
# ──────────────────────────────────────────────────────────────

co_movement_diagnostic_table:
  - pattern:
      click_quality: down
      search_quality_success: down
      ai_trigger: stable
      ai_success: stable
      zero_result_rate: stable
      latency: stable
    likely_cause: "ranking_relevance_regression"
    description: "Click quality degraded. Check ranking model, experiment ramps."
    priority_hypotheses: [algorithm_model, experiment]

  - pattern:
      click_quality: down
      search_quality_success: stable_or_up
      ai_trigger: up
      ai_success: up
      zero_result_rate: stable
      latency: stable
    likely_cause: "ai_answers_working"
    description: >
      AI answers cannibalizing clicks — this is a POSITIVE signal.
      Users get answers without needing to click. Do NOT treat as regression.
    priority_hypotheses: [ai_feature_effect]
    is_positive: true

  - pattern:
      click_quality: down
      search_quality_success: down
      ai_trigger: down
      ai_success: down
      zero_result_rate: stable
      latency: stable
    likely_cause: "broad_quality_degradation"
    description: "Both click and AI pathways affected. Check model/experiment/infra."
    priority_hypotheses: [algorithm_model, experiment, connector]

  - pattern:
      click_quality: down
      search_quality_success: down
      ai_trigger: stable
      ai_success: down
      zero_result_rate: stable
      latency: stable
    likely_cause: "ai_quality_regression"
    description: "AI answers triggering normally but failing to satisfy. Check AI model."
    priority_hypotheses: [ai_feature_effect, algorithm_model]

  - pattern:
      click_quality: down
      search_quality_success: down
      ai_trigger: stable
      ai_success: stable
      zero_result_rate: up
      latency: stable
    likely_cause: "connector_outage_or_index_gap"
    description: "Missing content leading to no results for some queries."
    priority_hypotheses: [connector, instrumentation]

  - pattern:
      click_quality: down
      search_quality_success: down
      ai_trigger: stable
      ai_success: stable
      zero_result_rate: stable
      latency: up
    likely_cause: "serving_degradation"
    description: "Latency causing model fallback or user abandonment."
    priority_hypotheses: [instrumentation, algorithm_model]

  - pattern:
      click_quality: down
      search_quality_success: stable
      ai_trigger: stable
      ai_success: stable
      zero_result_rate: stable
      latency: stable
    likely_cause: "click_behavior_change"
    description: "Only click behavior changed. Check UX changes, display changes, mix-shift."
    priority_hypotheses: [user_behavior, ai_feature_effect]

  - pattern:
      click_quality: stable
      search_quality_success: down
      ai_trigger: down
      ai_success: stable
      zero_result_rate: stable
      latency: stable
    likely_cause: "ai_trigger_regression"
    description: "AI answers not surfacing when they should. Check trigger threshold/model."
    priority_hypotheses: [ai_feature_effect]

  - pattern:
      click_quality: stable
      search_quality_success: down
      ai_trigger: stable
      ai_success: down
      zero_result_rate: stable
      latency: stable
    likely_cause: "ai_success_regression"
    description: "AI answers surfacing but wrong. Check answer quality model."
    priority_hypotheses: [ai_feature_effect, algorithm_model]

# ──────────────────────────────────────────────────────────────
# Hypothesis Priority Ordering
# Fixed priority for investigation — instrumentation first, behavior last.
# ──────────────────────────────────────────────────────────────

hypothesis_priority:
  - category: instrumentation
    name: "Instrumentation/Logging anomaly"
    rationale: "Cheap to verify, expensive to miss"
    check_always: true
  - category: connector
    name: "Connector/data pipeline change"
    rationale: "Most common root cause in Enterprise Search, under-documented"
    check_always: true
  - category: algorithm_model
    name: "Algorithm/Model change"
    rationale: "Ranking model, embedding model, retraining"
  - category: experiment
    name: "Experiment ramp/de-ramp"
    rationale: "A/B test exposure changes"
  - category: ai_feature_effect
    name: "AI feature effect"
    rationale: "AI answer adoption, threshold change, model migration"
  - category: seasonal
    name: "Seasonal/External pattern"
    rationale: "Calendar effects, industry cycles"
  - category: user_behavior
    name: "User behavior shift"
    rationale: "Null hypothesis — check LAST, accept only after ruling out engineering causes"
    check_last: true
```

**Step 4: Create historical_patterns.yaml**

```yaml
# data/knowledge/historical_patterns.yaml
# Known recurring patterns and past incidents for Enterprise Search.
# This is the "institutional memory" — the tribal knowledge encoded.

seasonal_patterns:
  - name: "Enterprise Onboarding Wave"
    trigger: "Large tenant batch onboarding"
    typical_impact:
      click_quality: [-0.02, -0.04]
      search_quality_success: [-0.01, -0.02]
    mechanism: >
      New tenants have sparse indexes (few connectors configured),
      dragging down aggregate metrics via mix-shift.
    duration_days: [14, 28]
    key_check: >
      Segment by tenant_age — if drop is concentrated in tenants < 30 days
      old, this is expected onboarding noise.
    recovery: "Metrics recover as new tenants configure more connectors (30-90 days)."

  - name: "AI Feature Batch Rollout"
    trigger: "Batch AI enablement for tenant cohort"
    typical_impact:
      click_quality: [-0.02, -0.04]
      ai_answer_rate: [+0.10, +0.20]
      search_quality_success: [+0.005, +0.015]
    mechanism: >
      Users get direct AI answers instead of clicking through to documents.
      Click Quality drops but Search Quality Success may improve. This is SUCCESS, not failure.
    key_check: >
      Always segment by ai_enablement. If drop is entirely in ai_on cohort
      AND ai_answer_rate increased, this is a positive signal.
    is_positive: true

  - name: "Connector Outage Pattern"
    trigger: "Third-party connector service degradation"
    typical_impact:
      click_quality: [-0.02, -0.08]
      zero_result_rate: [+0.02, +0.10]
    mechanism: >
      If a connector goes down, queries needing that source return
      degraded or zero results.
    duration_days: [0.5, 3]
    key_check: >
      Segment by connector_type. Check connector health/sync status.
    diagnostic_shortcut: "Check connector health dashboard first — if status shows failure, skip decomposition."

  - name: "End of Quarter Surge"
    trigger: "Enterprise end-of-quarter (finance, compliance searches)"
    typical_impact:
      query_volume: [+0.15, +0.30]
      click_quality: [-0.005, -0.015]
    mechanism: >
      Quarter-end drives finance/compliance/strategy searches.
      These tend to be more exploratory, lower click-through.
      Mix-shift from query type composition change.
    key_check: "Check calendar alignment. Compare to same period last year."

  - name: "Weekend/Weekday Cycle"
    trigger: "Normal weekly usage pattern"
    typical_impact:
      query_volume: [-0.30, -0.50]
      click_quality: [+0.01, +0.02]
    mechanism: >
      Weekend has fewer queries, skewed toward power users who click more.
      Apparent Click Quality increase is mix-shift, not quality improvement.
    key_check: "Always compare same day-of-week (WoW), not consecutive days."

known_incidents:
  - date: "2025-11-15"
    type: "logging_anomaly"
    affected_metrics: [click_quality, search_quality_success]
    impact: -0.04
    root_cause: "Click tracking pipeline migration dropped 8% of events"
    resolution: "Pipeline rollback + backfill"
    data_signature:
      overnight_step_change: true
      all_segments_affected_equally: true
      data_completeness_drop: true
    lessons: "Always check tracking completeness before investigating quality."

  - date: "2025-09-22"
    type: "connector_outage"
    affected_metrics: [click_quality, zero_result_rate]
    impact: -0.03
    root_cause: "Confluence API rate limiting during large customer migration"
    resolution: "Rate limit increase + backfill"
    data_signature:
      concentrated_in_connector: "confluence"
      zero_result_spike: true
      gradual_onset: true

  - date: "2025-08-10"
    type: "model_regression"
    affected_metrics: [click_quality, search_quality_success]
    impact: -0.025
    root_cause: "L3 ranker retraining introduced position bias for tail queries"
    resolution: "Model rollback to previous version"
    data_signature:
      concentrated_in_tier: "standard"
      concentrated_in_position: "3-5"
      experiment_temporal_match: true

diagnostic_shortcuts:
  - name: "Connector health check"
    condition: "Connector health dashboard shows failures"
    action: "Jump directly to connector root cause — skip full decomposition"
    saves: "30-60 minutes of dimensional analysis"

  - name: "Model fallback rate"
    condition: "model_fallback_rate metric spiked"
    action: "Jump to serving/latency investigation"
    saves: "Skip hypothesis generation for non-infra causes"

  - name: "Single tenant dominance"
    condition: "One tenant accounts for >40% of the metric movement"
    action: "Jump to tenant-specific analysis"
    saves: "Avoid analyzing dimensions that are all driven by one tenant"

  - name: "Overnight step-change"
    condition: "Metric changed >2% between consecutive days with no gradual trend"
    action: "Check instrumentation/logging first (highest prior probability)"
    saves: "Logging bugs cause step-changes; quality regressions are usually gradual"
```

**Step 5: Run tests to verify knowledge files**

Run: `pytest tests/test_knowledge.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add data/knowledge/ tests/test_knowledge.py
git commit -m "feat: add metric definitions and historical patterns knowledge files"
```

---

## Task 3: decompose.py — Dimensional Decomposition + Mix-Shift

**Files:**
- Create: `tools/decompose.py`
- Test: `tests/test_decompose.py`

This is the most important analysis tool. It breaks a metric movement into dimensional contributions and separates behavioral changes from mix-shift.

**Step 1: Write test — basic dimensional decomposition**

```python
# tests/test_decompose.py
"""Tests for the dimensional decomposition and mix-shift analysis tool."""

import json
import pytest
from tools.decompose import (
    compute_aggregate_delta,
    decompose_by_dimension,
    compute_mix_shift,
    run_decomposition,
)


class TestAggregateDelta:
    """Test headline metric movement calculation."""

    def test_computes_wow_delta(self, sample_metric_rows):
        baseline = [r for r in sample_metric_rows if r["period"] == "baseline"]
        current = [r for r in sample_metric_rows if r["period"] == "current"]
        result = compute_aggregate_delta(baseline, current, "click_quality_value")
        # Baseline: all 0.280, Current: half at 0.245 + half at 0.280 = avg 0.2625
        assert result["baseline_mean"] == pytest.approx(0.280, abs=0.001)
        assert result["current_mean"] == pytest.approx(0.2625, abs=0.001)
        assert result["absolute_delta"] < 0  # it dropped
        assert result["relative_delta_pct"] == pytest.approx(-6.25, abs=0.5)

    def test_classifies_severity_p1(self, sample_metric_rows):
        baseline = [r for r in sample_metric_rows if r["period"] == "baseline"]
        current = [r for r in sample_metric_rows if r["period"] == "current"]
        result = compute_aggregate_delta(baseline, current, "click_quality_value")
        # 6.25% drop → P0 (>5%)
        assert result["severity"] == "P0"

    def test_empty_input_returns_error(self):
        result = compute_aggregate_delta([], [], "click_quality_value")
        assert result["error"] is not None


class TestDimensionalDecomposition:
    """Test breaking metric by dimensions."""

    def test_decompose_by_tenant_tier(self, sample_metric_rows):
        baseline = [r for r in sample_metric_rows if r["period"] == "baseline"]
        current = [r for r in sample_metric_rows if r["period"] == "current"]
        result = decompose_by_dimension(baseline, current, "click_quality_value", "tenant_tier")

        # Should have two segments: standard and premium
        assert len(result["segments"]) == 2

        # Standard tier should show the drop
        standard = next(s for s in result["segments"] if s["segment_value"] == "standard")
        assert standard["delta"] < 0

        # Premium tier should be stable
        premium = next(s for s in result["segments"] if s["segment_value"] == "premium")
        assert premium["delta"] == pytest.approx(0.0, abs=0.001)

    def test_contribution_percentages_sum_to_near_100(self, sample_metric_rows):
        baseline = [r for r in sample_metric_rows if r["period"] == "baseline"]
        current = [r for r in sample_metric_rows if r["period"] == "current"]
        result = decompose_by_dimension(baseline, current, "click_quality_value", "tenant_tier")
        total_contribution = sum(s["contribution_pct"] for s in result["segments"])
        assert total_contribution == pytest.approx(100.0, abs=5.0)


class TestMixShift:
    """Test mix-shift analysis — separating composition change from behavioral change."""

    def test_detects_mix_shift(self, sample_mix_shift_rows):
        baseline = [r for r in sample_mix_shift_rows if r["period"] == "baseline"]
        current = [r for r in sample_mix_shift_rows if r["period"] == "current"]
        result = compute_mix_shift(baseline, current, "click_quality_value", "tenant_tier")

        # Per-segment Click Quality is unchanged, but aggregate drops due to more standard tier
        assert result["mix_shift_contribution_pct"] > 50  # majority is mix-shift
        assert result["behavioral_contribution_pct"] < 50

    def test_no_mix_shift_when_composition_stable(self, sample_metric_rows):
        baseline = [r for r in sample_metric_rows if r["period"] == "baseline"]
        current = [r for r in sample_metric_rows if r["period"] == "current"]
        result = compute_mix_shift(baseline, current, "click_quality_value", "tenant_tier")

        # Composition is 50/50 in both periods → no mix shift
        assert result["mix_shift_contribution_pct"] < 10


class TestRunDecomposition:
    """Test the full decomposition pipeline."""

    def test_returns_json_serializable(self, sample_metric_rows):
        result = run_decomposition(sample_metric_rows, "click_quality_value",
                                   dimensions=["tenant_tier"])
        # Should be JSON-serializable (Claude Code reads JSON output)
        json_str = json.dumps(result)
        assert json_str is not None

    def test_includes_aggregate_and_dimensions(self, sample_metric_rows):
        result = run_decomposition(sample_metric_rows, "click_quality_value",
                                   dimensions=["tenant_tier"])
        assert "aggregate" in result
        assert "dimensional_breakdown" in result
        assert "mix_shift" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_decompose.py -v`
Expected: FAIL (decompose.py doesn't exist)

**Step 3: Implement decompose.py**

```python
#!/usr/bin/env python3
"""Dimensional decomposition and mix-shift analysis for Search metrics.

This tool breaks a metric movement into dimensional contributions and
separates behavioral changes (actual quality change) from mix-shift
(population composition change).

Usage (CLI):
    python tools/decompose.py --input data.csv --metric click_quality_value --dimensions tenant_tier,ai_enablement

Usage (from Python):
    from tools.decompose import run_decomposition
    result = run_decomposition(rows, "click_quality_value", dimensions=["tenant_tier"])

Output: JSON to stdout (Claude Code reads this).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────
# Severity classification thresholds
# Matches design doc Section 5: P0 (>5%), P1 (2-5%), P2 (<2%)
# ──────────────────────────────────────────────────

SEVERITY_THRESHOLDS = {
    "P0": 0.05,   # >5% relative movement
    "P1": 0.02,   # 2-5%
    "P2": 0.005,  # 0.5-2%
}


def _mean(values: List[float]) -> float:
    """Compute mean. Returns 0.0 for empty lists."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_float(value) -> float:
    """Convert a value to float, handling strings and edge cases."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _classify_severity(relative_delta_pct: float) -> str:
    """Classify metric movement severity based on magnitude.

    Uses absolute value because both drops AND spikes can be concerning.
    """
    magnitude = abs(relative_delta_pct) / 100.0  # convert pct to fraction
    if magnitude >= SEVERITY_THRESHOLDS["P0"]:
        return "P0"
    elif magnitude >= SEVERITY_THRESHOLDS["P1"]:
        return "P1"
    elif magnitude >= SEVERITY_THRESHOLDS["P2"]:
        return "P2"
    return "normal"


def compute_aggregate_delta(
    baseline_rows: List[Dict],
    current_rows: List[Dict],
    metric_field: str,
) -> Dict[str, Any]:
    """Compute the headline metric movement between two periods.

    This is the first thing we check: "Click Quality dropped X% WoW."

    Args:
        baseline_rows: Rows from the comparison period (e.g., last week)
        current_rows: Rows from the current period
        metric_field: Which field to analyze (e.g., "click_quality_value")

    Returns:
        Dict with baseline_mean, current_mean, absolute_delta,
        relative_delta_pct, severity, direction, error.
    """
    if not baseline_rows or not current_rows:
        return {"error": "Empty input: need both baseline and current rows"}

    baseline_values = [_safe_float(r.get(metric_field, 0)) for r in baseline_rows]
    current_values = [_safe_float(r.get(metric_field, 0)) for r in current_rows]

    baseline_mean = _mean(baseline_values)
    current_mean = _mean(current_values)

    if baseline_mean == 0:
        return {"error": f"Baseline mean is zero for {metric_field}"}

    absolute_delta = current_mean - baseline_mean
    relative_delta_pct = (absolute_delta / baseline_mean) * 100.0

    direction = "up" if absolute_delta > 0 else "down" if absolute_delta < 0 else "stable"
    severity = _classify_severity(relative_delta_pct)

    return {
        "metric": metric_field,
        "baseline_mean": round(baseline_mean, 6),
        "current_mean": round(current_mean, 6),
        "absolute_delta": round(absolute_delta, 6),
        "relative_delta_pct": round(relative_delta_pct, 2),
        "direction": direction,
        "severity": severity,
        "baseline_count": len(baseline_values),
        "current_count": len(current_values),
        "error": None,
    }


def decompose_by_dimension(
    baseline_rows: List[Dict],
    current_rows: List[Dict],
    metric_field: str,
    dimension: str,
) -> Dict[str, Any]:
    """Break a metric movement into contributions by a single dimension.

    For each segment value (e.g., tenant_tier="standard"), compute:
    - How much the metric changed in that segment
    - What % of the total change this segment contributed

    This tells you WHERE the drop is concentrated.

    Args:
        baseline_rows: Rows from baseline period
        current_rows: Rows from current period
        metric_field: Metric to analyze
        dimension: Which dimension to segment by (e.g., "tenant_tier")

    Returns:
        Dict with segments list, each containing segment_value, baseline_mean,
        current_mean, delta, contribution_pct.
    """
    # Group rows by segment value
    def _group_by(rows, dim):
        groups = defaultdict(list)
        for r in rows:
            groups[r.get(dim, "unknown")].append(r)
        return groups

    baseline_groups = _group_by(baseline_rows, dimension)
    current_groups = _group_by(current_rows, dimension)

    # Overall delta for computing contribution percentages
    overall = compute_aggregate_delta(baseline_rows, current_rows, metric_field)
    overall_delta = overall["absolute_delta"] if overall["error"] is None else 0.0

    all_segments = set(list(baseline_groups.keys()) + list(current_groups.keys()))
    segments = []

    for seg_value in sorted(all_segments):
        bl_values = [_safe_float(r.get(metric_field, 0)) for r in baseline_groups.get(seg_value, [])]
        cur_values = [_safe_float(r.get(metric_field, 0)) for r in current_groups.get(seg_value, [])]

        bl_mean = _mean(bl_values)
        cur_mean = _mean(cur_values)
        delta = cur_mean - bl_mean

        # Weight by segment size (proportion of current traffic)
        cur_weight = len(cur_values) / max(len(current_rows), 1)

        # Contribution: how much of the overall delta comes from this segment
        # Weighted delta contribution = segment_delta * segment_traffic_share
        weighted_delta = delta * cur_weight
        contribution_pct = (weighted_delta / overall_delta * 100.0) if overall_delta != 0 else 0.0

        segments.append({
            "segment_value": seg_value,
            "baseline_mean": round(bl_mean, 6),
            "current_mean": round(cur_mean, 6),
            "delta": round(delta, 6),
            "baseline_count": len(bl_values),
            "current_count": len(cur_values),
            "traffic_share_pct": round(cur_weight * 100, 1),
            "contribution_pct": round(contribution_pct, 1),
        })

    # Sort by contribution magnitude (highest contributor first)
    segments.sort(key=lambda s: abs(s["contribution_pct"]), reverse=True)

    return {
        "dimension": dimension,
        "overall_delta": overall_delta,
        "segments": segments,
        "dominant_segment": segments[0]["segment_value"] if segments else None,
        "dominant_contribution_pct": segments[0]["contribution_pct"] if segments else 0,
    }


def compute_mix_shift(
    baseline_rows: List[Dict],
    current_rows: List[Dict],
    metric_field: str,
    dimension: str,
) -> Dict[str, Any]:
    """Separate mix-shift from behavioral change for a metric movement.

    Mix-shift = the metric moved because the COMPOSITION of traffic changed
    (e.g., more standard-tier tenants), not because behavior changed within
    any segment.

    Uses the Kitagawa-Oaxaca decomposition:
      Total change = Behavioral effect + Composition effect (mix-shift)

    Behavioral: hold composition constant, measure metric change per segment
    Composition: hold segment metrics constant, measure traffic share change

    This is critical for Enterprise Search where tenant portfolio changes
    (new tenants, churns, tier migrations) constantly shift the mix.
    """
    def _group_by(rows, dim):
        groups = defaultdict(list)
        for r in rows:
            groups[r.get(dim, "unknown")].append(r)
        return groups

    baseline_groups = _group_by(baseline_rows, dimension)
    current_groups = _group_by(current_rows, dimension)

    all_segments = set(list(baseline_groups.keys()) + list(current_groups.keys()))
    total_baseline = max(len(baseline_rows), 1)
    total_current = max(len(current_rows), 1)

    behavioral_effect = 0.0
    composition_effect = 0.0

    for seg in all_segments:
        bl_values = [_safe_float(r.get(metric_field, 0)) for r in baseline_groups.get(seg, [])]
        cur_values = [_safe_float(r.get(metric_field, 0)) for r in current_groups.get(seg, [])]

        bl_mean = _mean(bl_values) if bl_values else 0.0
        cur_mean = _mean(cur_values) if cur_values else 0.0

        bl_share = len(bl_values) / total_baseline
        cur_share = len(cur_values) / total_current

        # Behavioral: metric changed within this segment, weighted by avg share
        avg_share = (bl_share + cur_share) / 2
        behavioral_effect += (cur_mean - bl_mean) * avg_share

        # Composition: traffic share changed, weighted by avg metric
        avg_metric = (bl_mean + cur_mean) / 2
        composition_effect += (cur_share - bl_share) * avg_metric

    total_effect = behavioral_effect + composition_effect
    if abs(total_effect) < 1e-10:
        return {
            "mix_shift_contribution_pct": 0.0,
            "behavioral_contribution_pct": 0.0,
            "total_effect": 0.0,
            "behavioral_effect": 0.0,
            "composition_effect": 0.0,
            "flag": None,
        }

    mix_pct = abs(composition_effect) / (abs(behavioral_effect) + abs(composition_effect)) * 100
    behavioral_pct = 100.0 - mix_pct

    # Flag if mix-shift exceeds 30% threshold (from design doc validation check #4)
    flag = "mix_shift_dominant" if mix_pct >= 30 else None

    return {
        "mix_shift_contribution_pct": round(mix_pct, 1),
        "behavioral_contribution_pct": round(behavioral_pct, 1),
        "total_effect": round(total_effect, 6),
        "behavioral_effect": round(behavioral_effect, 6),
        "composition_effect": round(composition_effect, 6),
        "flag": flag,
    }


def run_decomposition(
    rows: List[Dict],
    metric_field: str,
    dimensions: Optional[List[str]] = None,
    baseline_period: str = "baseline",
    current_period: str = "current",
    period_field: str = "period",
) -> Dict[str, Any]:
    """Run the full decomposition pipeline on a dataset.

    This is the main entry point called by Claude Code.

    Args:
        rows: All rows (both periods)
        metric_field: Which metric to analyze
        dimensions: List of dimensions to decompose by (default: all Enterprise dims)
        baseline_period: Value of period_field for baseline rows
        current_period: Value of period_field for current rows
        period_field: Column name containing period labels

    Returns:
        Dict with aggregate, dimensional_breakdown, mix_shift results.
        JSON-serializable for Claude Code to read.
    """
    if dimensions is None:
        dimensions = [
            "tenant_tier", "ai_enablement", "industry_vertical",
            "connector_type", "query_type", "position_bucket",
        ]

    # Split into baseline and current periods
    baseline = [r for r in rows if r.get(period_field) == baseline_period]
    current = [r for r in rows if r.get(period_field) == current_period]

    # Step 1: Headline delta
    aggregate = compute_aggregate_delta(baseline, current, metric_field)

    # Step 2: Decompose by each dimension
    dimensional = {}
    for dim in dimensions:
        # Only decompose if the dimension exists in the data
        if any(dim in r for r in rows):
            dimensional[dim] = decompose_by_dimension(baseline, current, metric_field, dim)

    # Step 3: Mix-shift analysis for the primary dimension (tenant_tier if available)
    primary_dim = dimensions[0] if dimensions else None
    mix_shift = {}
    if primary_dim and any(primary_dim in r for r in rows):
        mix_shift = compute_mix_shift(baseline, current, metric_field, primary_dim)

    # Identify dominant dimension (which one explains most of the drop?)
    max_contribution = 0
    dominant_dimension = None
    for dim_name, dim_result in dimensional.items():
        if dim_result["segments"]:
            top_contribution = abs(dim_result["segments"][0]["contribution_pct"])
            if top_contribution > max_contribution:
                max_contribution = top_contribution
                dominant_dimension = dim_name

    return {
        "aggregate": aggregate,
        "dimensional_breakdown": dimensional,
        "mix_shift": mix_shift,
        "dominant_dimension": dominant_dimension,
        "drill_down_recommended": max_contribution > 50,
    }


# ──────────────────────────────────────────────────
# CLI interface — for Claude Code to call via Bash tool
# ──────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Decompose a metric movement by dimensions and detect mix-shift"
    )
    parser.add_argument("--input", required=True, help="Path to CSV file with metric data")
    parser.add_argument("--metric", required=True, help="Metric column to analyze (e.g., click_quality_value)")
    parser.add_argument("--dimensions", default="tenant_tier,ai_enablement,query_type",
                        help="Comma-separated dimensions to decompose by")
    parser.add_argument("--baseline-period", default="baseline",
                        help="Value of period column for baseline rows")
    parser.add_argument("--current-period", default="current",
                        help="Value of period column for current rows")
    parser.add_argument("--period-field", default="period",
                        help="Column name containing period labels")
    return parser.parse_args()


def main():
    args = parse_args()

    # Load CSV
    input_path = Path(args.input)
    if not input_path.exists():
        print(json.dumps({"error": f"File not found: {args.input}"}))
        sys.exit(1)

    with open(input_path) as f:
        rows = list(csv.DictReader(f))

    dimensions = [d.strip() for d in args.dimensions.split(",")]

    result = run_decomposition(
        rows=rows,
        metric_field=args.metric,
        dimensions=dimensions,
        baseline_period=args.baseline_period,
        current_period=args.current_period,
        period_field=args.period_field,
    )

    # Output JSON to stdout for Claude Code to read
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_decompose.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add tools/decompose.py tests/test_decompose.py
git commit -m "feat: add dimensional decomposition tool with mix-shift analysis"
```

---

## Task 4: anomaly.py — Anomaly Detection vs Baselines

**Files:**
- Create: `tools/anomaly.py`
- Test: `tests/test_anomaly.py`

This tool compares metric values against known baselines and historical patterns to detect anomalies. It also checks co-movement patterns from the diagnostic table.

**Step 1: Write test**

```python
# tests/test_anomaly.py
"""Tests for anomaly detection tool."""

import pytest
from tools.anomaly import (
    check_data_quality,
    detect_step_change,
    match_co_movement_pattern,
    check_against_baseline,
)


class TestDataQuality:
    """Test data quality gate — Step 1 of the diagnostic workflow."""

    def test_passes_clean_data(self):
        rows = [{"data_completeness": 0.995, "data_freshness_min": 10} for _ in range(100)]
        result = check_data_quality(rows)
        assert result["status"] == "pass"

    def test_fails_low_completeness(self):
        rows = [{"data_completeness": 0.90, "data_freshness_min": 10} for _ in range(100)]
        result = check_data_quality(rows)
        assert result["status"] == "fail"
        assert "completeness" in result["reason"].lower()

    def test_fails_stale_data(self):
        rows = [{"data_completeness": 0.995, "data_freshness_min": 300} for _ in range(100)]
        result = check_data_quality(rows)
        assert result["status"] == "fail"
        assert "freshness" in result["reason"].lower()

    def test_warns_borderline(self):
        rows = [{"data_completeness": 0.965, "data_freshness_min": 50} for _ in range(100)]
        result = check_data_quality(rows)
        assert result["status"] in ["warn", "pass"]


class TestStepChange:
    """Test overnight step-change detection (validation check #1)."""

    def test_detects_overnight_step_change(self):
        # Values stable around 0.280, then drop to 0.245 overnight
        daily_values = [0.280, 0.281, 0.279, 0.280, 0.245, 0.244, 0.246]
        result = detect_step_change(daily_values, threshold_pct=2.0)
        assert result["detected"] is True
        assert result["change_day_index"] == 4

    def test_no_step_change_gradual(self):
        # Gradual decline — no single overnight jump
        daily_values = [0.280, 0.276, 0.272, 0.268, 0.264, 0.260]
        result = detect_step_change(daily_values, threshold_pct=2.0)
        assert result["detected"] is False


class TestCoMovementPattern:
    """Test co-movement pattern matching against the diagnostic table."""

    def test_matches_ranking_regression(self):
        observed = {
            "click_quality": "down", "search_quality_success": "down",
            "ai_trigger": "stable", "ai_success": "stable",
            "zero_result_rate": "stable", "latency": "stable",
        }
        result = match_co_movement_pattern(observed)
        assert result["likely_cause"] == "ranking_relevance_regression"

    def test_matches_ai_answers_working(self):
        observed = {
            "click_quality": "down", "search_quality_success": "stable_or_up",
            "ai_trigger": "up", "ai_success": "up",
            "zero_result_rate": "stable", "latency": "stable",
        }
        result = match_co_movement_pattern(observed)
        assert result["likely_cause"] == "ai_answers_working"
        assert result.get("is_positive") is True

    def test_no_match_returns_unknown(self):
        observed = {
            "click_quality": "up", "search_quality_success": "up",
            "ai_trigger": "up", "ai_success": "up",
            "zero_result_rate": "up", "latency": "up",
        }
        result = match_co_movement_pattern(observed)
        assert result["likely_cause"] == "unknown_pattern"


class TestBaselineComparison:
    """Test comparing current metric value against expected baselines."""

    def test_within_normal_range(self):
        result = check_against_baseline(
            current_value=0.278, metric_name="click_quality",
            segment=None, baselines={"mean": 0.280, "weekly_std": 0.015}
        )
        assert result["status"] == "normal"

    def test_outside_normal_range(self):
        result = check_against_baseline(
            current_value=0.220, metric_name="click_quality",
            segment=None, baselines={"mean": 0.280, "weekly_std": 0.015}
        )
        assert result["status"] == "anomalous"
        assert result["z_score"] < -2.0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_anomaly.py -v`
Expected: FAIL

**Step 3: Implement anomaly.py**

Create `tools/anomaly.py` implementing the four functions tested above:
- `check_data_quality()` — data quality gate with completeness (>=96%) and freshness (<=60 min) thresholds
- `detect_step_change()` — find overnight step-changes >threshold in a daily time series
- `match_co_movement_pattern()` — match observed metric directions against the co-movement diagnostic table (loaded from YAML)
- `check_against_baseline()` — z-score comparison against known segment baselines

Include CLI interface: `python tools/anomaly.py --input data.csv --metric click_quality_value`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_anomaly.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add tools/anomaly.py tests/test_anomaly.py
git commit -m "feat: add anomaly detection tool with co-movement pattern matching"
```

---

## Task 5: diagnose.py — 4 Validation Checks + Confidence Scoring

**Files:**
- Create: `tools/diagnose.py`
- Test: `tests/test_diagnose.py`

This tool runs the 4 mandatory validation checks and assigns confidence levels. It takes the output of decompose.py and anomaly.py as input.

**Step 1: Write test**

```python
# tests/test_diagnose.py
"""Tests for validation checks and confidence scoring."""

import pytest
from tools.diagnose import (
    check_logging_artifact,
    check_decomposition_completeness,
    check_temporal_consistency,
    check_mix_shift_threshold,
    compute_confidence,
    run_diagnosis,
)


class TestLoggingArtifact:
    """Validation Check #1: Overnight step-change detection."""

    def test_flags_overnight_step_change(self):
        step_change_result = {"detected": True, "change_day_index": 4, "magnitude_pct": 3.5}
        result = check_logging_artifact(step_change_result)
        assert result["status"] == "HALT"
        assert result["check"] == "logging_artifact"

    def test_passes_no_step_change(self):
        step_change_result = {"detected": False}
        result = check_logging_artifact(step_change_result)
        assert result["status"] == "PASS"


class TestDecompositionCompleteness:
    """Validation Check #2: Segments must explain >=90% of total drop."""

    def test_passes_when_complete(self):
        result = check_decomposition_completeness(explained_pct=94.0)
        assert result["status"] == "PASS"

    def test_warns_when_incomplete(self):
        result = check_decomposition_completeness(explained_pct=85.0)
        assert result["status"] == "WARN"

    def test_halts_when_very_incomplete(self):
        result = check_decomposition_completeness(explained_pct=65.0)
        assert result["status"] == "HALT"


class TestTemporalConsistency:
    """Validation Check #3: Metric must change AFTER proposed cause."""

    def test_passes_when_consistent(self):
        # Cause on day 3, metric changed on day 4
        result = check_temporal_consistency(
            cause_date_index=3, metric_change_date_index=4
        )
        assert result["status"] == "PASS"

    def test_halts_when_metric_before_cause(self):
        # Metric changed on day 2, but proposed cause on day 5
        result = check_temporal_consistency(
            cause_date_index=5, metric_change_date_index=2
        )
        assert result["status"] == "HALT"


class TestMixShiftThreshold:
    """Validation Check #4: Flag when mix-shift >= 30%."""

    def test_flags_high_mix_shift(self):
        result = check_mix_shift_threshold(mix_shift_pct=45.0)
        assert result["status"] == "INVESTIGATE"

    def test_passes_low_mix_shift(self):
        result = check_mix_shift_threshold(mix_shift_pct=12.0)
        assert result["status"] == "PASS"


class TestConfidence:
    """Test confidence level assignment."""

    def test_high_confidence(self):
        # All checks pass, high explained pct, temporal match
        checks = [
            {"status": "PASS"}, {"status": "PASS"},
            {"status": "PASS"}, {"status": "PASS"},
        ]
        result = compute_confidence(
            checks=checks, explained_pct=94.0,
            evidence_lines=3, has_historical_precedent=True,
        )
        assert result["level"] == "High"

    def test_medium_confidence(self):
        # One check warns, still decent explained pct
        checks = [
            {"status": "PASS"}, {"status": "WARN"},
            {"status": "PASS"}, {"status": "PASS"},
        ]
        result = compute_confidence(
            checks=checks, explained_pct=87.0,
            evidence_lines=2, has_historical_precedent=False,
        )
        assert result["level"] == "Medium"

    def test_low_confidence(self):
        # Single evidence line, no precedent
        checks = [
            {"status": "PASS"}, {"status": "PASS"},
            {"status": "PASS"}, {"status": "INVESTIGATE"},
        ]
        result = compute_confidence(
            checks=checks, explained_pct=75.0,
            evidence_lines=1, has_historical_precedent=False,
        )
        assert result["level"] == "Low"

    def test_includes_upgrade_condition(self):
        result = compute_confidence(
            checks=[{"status": "PASS"}] * 4,
            explained_pct=87.0,
            evidence_lines=2,
            has_historical_precedent=False,
        )
        assert "would_upgrade_if" in result
        assert result["would_upgrade_if"] is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_diagnose.py -v`
Expected: FAIL

**Step 3: Implement diagnose.py**

Create `tools/diagnose.py` implementing:
- 4 validation check functions (each returns `{"check": ..., "status": "PASS"|"WARN"|"HALT"|"INVESTIGATE", "detail": ...}`)
- `compute_confidence()` — assigns High/Medium/Low with explicit criteria and upgrade/downgrade conditions
- `run_diagnosis()` — orchestrates all checks on decomposition + anomaly results, returns full diagnosis JSON

Confidence criteria (from design doc Section 10):
- **High**: >=90% explained + >=3 evidence lines + historical precedent + all checks pass
- **Medium**: >=80% explained + >=2 evidence lines, OR missing one check
- **Low**: Single evidence line, OR multiple alternatives unresolved, OR <80% explained

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_diagnose.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add tools/diagnose.py tests/test_diagnose.py
git commit -m "feat: add diagnosis tool with 4 validation checks and confidence scoring"
```

---

## Task 6: formatter.py — Slack + Report Template Generation

**Files:**
- Create: `tools/formatter.py`
- Create: `templates/slack_message.md`
- Create: `templates/short_report.md`
- Test: `tests/test_formatter.py`

**Step 1: Write test**

```python
# tests/test_formatter.py
"""Tests for Slack message and report template generation."""

import pytest
from tools.formatter import (
    generate_slack_message,
    generate_short_report,
    format_diagnosis_output,
)


# Sample diagnosis result (as would come from diagnose.py)
SAMPLE_DIAGNOSIS = {
    "aggregate": {
        "metric": "click_quality_value",
        "baseline_mean": 0.280,
        "current_mean": 0.2625,
        "relative_delta_pct": -6.25,
        "direction": "down",
        "severity": "P0",
    },
    "primary_hypothesis": {
        "category": "algorithm_model",
        "description": "Ranking model regression for Standard tier",
    },
    "confidence": {
        "level": "High",
        "reasoning": "Decomposition explains 94%, temporal match confirmed, no contradicting co-movements.",
        "would_upgrade_if": None,
        "would_downgrade_if": "Experiment team reports no model change in this period.",
    },
    "validation_checks": [
        {"check": "logging_artifact", "status": "PASS", "detail": "No overnight step-change detected"},
        {"check": "decomposition_completeness", "status": "PASS", "detail": "94% of drop explained"},
        {"check": "temporal_consistency", "status": "PASS", "detail": "Drop onset matches model deploy"},
        {"check": "mix_shift", "status": "PASS", "detail": "12% mix-shift (below 30% threshold)"},
    ],
    "dimensional_breakdown": {
        "tenant_tier": {
            "segments": [
                {"segment_value": "standard", "contribution_pct": 78.0, "delta": -0.035},
                {"segment_value": "premium", "contribution_pct": 22.0, "delta": -0.005},
            ]
        }
    },
    "mix_shift": {"mix_shift_contribution_pct": 12.0},
    "action_items": [
        {"action": "Check ranking model version deployed this week", "owner": "Ranking team"},
        {"action": "Review Standard tier query performance", "owner": "Search DS"},
    ],
}


class TestSlackMessage:
    """Test Slack message generation."""

    def test_has_severity_and_confidence_in_header(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        assert "P0" in msg
        assert "High" in msg

    def test_has_tldr(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        assert "TL;DR" in msg or "tl;dr" in msg.lower()

    def test_has_key_findings(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        assert "finding" in msg.lower() or "%" in msg

    def test_length_is_reasonable(self):
        """Slack message should be 5-8 lines, not a wall of text."""
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        lines = [l for l in msg.strip().split("\n") if l.strip()]
        assert 4 <= len(lines) <= 15  # some slack for headers/spacing

    def test_no_anti_patterns(self):
        """Output must not contain hedge language or passive voice."""
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        hedge_phrases = ["it could be", "it might be", "possibly", "perhaps",
                         "further investigation needed", "was impacted by"]
        for phrase in hedge_phrases:
            assert phrase not in msg.lower(), f"Anti-pattern found: '{phrase}'"


class TestShortReport:
    """Test short report generation."""

    def test_has_all_required_sections(self):
        report = generate_short_report(SAMPLE_DIAGNOSIS)
        required_sections = ["Summary", "Decomposition", "Diagnosis",
                            "Validation", "Business Impact", "Recommended Actions"]
        for section in required_sections:
            assert section.lower() in report.lower(), f"Missing section: {section}"

    def test_has_confidence_upgrade_conditions(self):
        report = generate_short_report(SAMPLE_DIAGNOSIS)
        assert "would" in report.lower()  # "Would upgrade/downgrade if..."

    def test_has_validation_check_table(self):
        report = generate_short_report(SAMPLE_DIAGNOSIS)
        assert "PASS" in report


class TestFormatDiagnosisOutput:
    """Test the combined formatter that produces both outputs."""

    def test_returns_both_formats(self):
        result = format_diagnosis_output(SAMPLE_DIAGNOSIS)
        assert "slack_message" in result
        assert "short_report" in result

    def test_output_is_string(self):
        result = format_diagnosis_output(SAMPLE_DIAGNOSIS)
        assert isinstance(result["slack_message"], str)
        assert isinstance(result["short_report"], str)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter.py -v`
Expected: FAIL

**Step 3: Create Slack message template**

```markdown
<!-- templates/slack_message.md -->
{emoji} {metric_name} Movement Alert — [Severity: {severity}] [Confidence: {confidence}]

TL;DR: {tldr}

Key findings:
{findings}

Confidence: {confidence_level} — {confidence_reasoning}
{confidence_change}

{action_items}
```

**Step 4: Create short report template**

```markdown
<!-- templates/short_report.md -->
# Metric Movement Report: {metric_name} {delta_pct}% {period}
**Date:** {date} | **Severity:** {severity} | **Confidence:** {confidence}

## Summary
{tldr}

## Decomposition
{decomposition_table}

## Diagnosis
**Primary hypothesis:** {primary_hypothesis}
**Evidence:** {evidence_bullets}
**Alternatives considered:** {alternatives}

## Validation Checks
{validation_table}

## Business Impact
{business_impact}

## Recommended Actions
{action_items}

## What Would Change This Assessment
{confidence_change}
```

**Step 5: Implement formatter.py**

Create `tools/formatter.py` with:
- `generate_slack_message(diagnosis)` — fills Slack template from diagnosis dict
- `generate_short_report(diagnosis)` — fills report template
- `format_diagnosis_output(diagnosis)` — returns both formats
- CLI: `python tools/formatter.py --input diagnosis.json`

**Step 6: Run tests**

Run: `pytest tests/test_formatter.py -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add tools/formatter.py templates/ tests/test_formatter.py
git commit -m "feat: add template-based Slack message and report formatter"
```

---

## Task 7: Extend Synthetic Data Generator (13 Enterprise Scenarios)

**Files:**
- Modify: `generators/generate_synthetic_data.py` (heavy modification)
- Test: `tests/test_generator.py`

The existing generator creates S0-S8 with generic dimensions. We need to:
1. Add Enterprise dimensions (tenant_tier, ai_enablement, industry_vertical, connector_type)
2. Add 4 new scenarios (S9-S12)
3. Ensure generated data works with our decompose.py tool

This is the largest task. The existing ~600-line generator needs significant restructuring.

**Step 1: Write test for new Enterprise dimensions**

```python
# tests/test_generator.py
"""Tests that the synthetic data generator produces valid Enterprise Search data."""

import csv
import json
import pytest
from pathlib import Path

# This test runs the generator and checks output
# We test the generated CSV structure, not the generation logic


class TestGeneratedData:
    """Test structure of generated synthetic data."""

    def test_has_enterprise_dimensions(self, synthetic_dir):
        """Generated data must include Enterprise Search dimensions."""
        session_log = synthetic_dir / "synthetic_search_session_log.csv"
        if not session_log.exists():
            pytest.skip("Run generator first: python generators/generate_synthetic_data.py")

        with open(session_log) as f:
            reader = csv.DictReader(f)
            row = next(reader)

        enterprise_cols = ["tenant_tier", "ai_enablement", "industry_vertical", "connector_type"]
        for col in enterprise_cols:
            assert col in row, f"Missing Enterprise dimension: {col}"

    def test_has_all_13_scenarios(self, synthetic_dir):
        """Must have scenarios S0 through S12."""
        session_log = synthetic_dir / "synthetic_search_session_log.csv"
        if not session_log.exists():
            pytest.skip("Run generator first")

        scenarios = set()
        with open(session_log) as f:
            for row in csv.DictReader(f):
                scenarios.add(row["scenario_id"])

        for i in range(13):
            assert f"S{i}" in scenarios, f"Missing scenario S{i}"

    def test_has_period_column(self, synthetic_dir):
        """Each scenario should have baseline and current periods."""
        metric_agg = synthetic_dir / "synthetic_metric_aggregate.csv"
        if not metric_agg.exists():
            pytest.skip("Run generator first")

        periods = set()
        with open(metric_agg) as f:
            for row in csv.DictReader(f):
                if row["scenario_id"] == "S0":
                    periods.add(row.get("period", ""))

        assert "baseline" in periods
        assert "current" in periods
```

**Step 2: Implement extended generator**

This requires significant modification to the existing `generate_synthetic_data.py`. Key changes:
- Add `tenant_tier`, `ai_enablement`, `industry_vertical`, `connector_type` columns
- Add `period` column (baseline vs current) to enable WoW comparison
- Add scenarios S9 (tenant portfolio mix-shift), S10 (connector extraction regression), S11 (auth credential expiry), S12 (model migration)
- Ensure each scenario has realistic Enterprise Search dimension distributions
- Keep existing S0-S8 logic but add Enterprise dimensions

**Step 3: Run generator and verify**

```bash
cd "/Users/surahli/Documents/New project/Search_Metric_Analyzer"
python generators/generate_synthetic_data.py --output-dir data/synthetic
```

**Step 4: Run tests**

Run: `pytest tests/test_generator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add generators/generate_synthetic_data.py tests/test_generator.py
git commit -m "feat: extend synthetic data generator with 13 Enterprise Search scenarios"
```

---

## Task 8: Claude Code Skill File

**Files:**
- Create: `skills/search-metric-analyzer.md`

**Step 1: Write the skill file**

The skill file encodes the 4-step diagnostic methodology that Claude Code follows. It tells Claude Code when and how to call each Python tool, how to interpret results, and how to format output.

```markdown
# skills/search-metric-analyzer.md

---
name: search-metric-analyzer
description: >
  Diagnose Enterprise Search metric movements using a 4-step workflow.
  Use when an Eng Lead or DS reports a metric drop/spike (Click Quality, Search Quality Success, AI Answer, etc.).
trigger: >
  User mentions metric drop, metric spike, Click Quality, Search Quality Success, AI Answer, search quality,
  metric investigation, metric debugging, or search regression.
---

# Search Metric Analyzer

You are a senior Search DS with 20 years of experience debugging Enterprise Search
metrics. Follow this 4-step diagnostic workflow EXACTLY.

## Prerequisites
- Search Domain Expert Skills must be loaded (provides domain knowledge)
- Python tools are at: `tools/decompose.py`, `tools/anomaly.py`, `tools/diagnose.py`, `tools/formatter.py`
- Knowledge files at: `data/knowledge/metric_definitions.yaml`, `data/knowledge/historical_patterns.yaml`

## Step 1: INTAKE & TRIAGE

1. Identify the metric and time period from the user's description
2. Load the data file provided by the user
3. Run data quality check:
   ```bash
   python tools/anomaly.py --mode quality --input {data_file}
   ```
4. If quality FAILS → stop and report "Blocked by data quality: {reason}"
5. Compute headline delta:
   ```bash
   python tools/decompose.py --input {data_file} --metric {metric} --mode aggregate
   ```
6. Check co-movement pattern: compare directions of Click Quality, Search Quality Success, AI trigger, AI success, zero-result rate, latency
7. Report severity (P0/P1/P2) and co-movement pattern match
8. Draw on Domain Expert Skills: what recent system changes could be relevant?

## Step 2: DECOMPOSE & INVESTIGATE

1. Run full dimensional decomposition:
   ```bash
   python tools/decompose.py --input {data_file} --metric {metric} --dimensions tenant_tier,ai_enablement,industry_vertical,connector_type,query_type,position_bucket
   ```
2. Run mix-shift analysis on the dominant dimension
3. If any dimension contributes >50%: offer to drill down further
4. Generate hypotheses in priority order:
   - Instrumentation/Logging (always check)
   - Connector/Data pipeline (always check)
   - Algorithm/Model change
   - Experiment ramp/de-ramp
   - AI feature effect
   - Seasonal/External
   - User behavior (check LAST)
5. For **Quick mode**: stop after top 2 hypotheses, skip to Step 4
6. For **Standard mode**: investigate all hypotheses

## Step 3: VALIDATE

Run all 4 validation checks:
```bash
python tools/diagnose.py --input {decomposition_result} --checks all
```

Checks:
1. **Logging Artifact**: overnight step-change >=2%? → HALT if yes
2. **Decomposition Completeness**: segments explain >=90%? → HALT if <70%, WARN if <90%
3. **Temporal Consistency**: cause precedes effect? → HALT if violated
4. **Mix Shift**: >=30% from composition change? → INVESTIGATE (flag)

Assign confidence (High/Medium/Low) with explicit criteria.

## Step 4: SYNTHESIZE & FORMAT

Generate output:
```bash
python tools/formatter.py --input {diagnosis_result} --format slack,report
```

### Output Rules (NON-NEGOTIABLE):
- TL;DR first, always, max 3 sentences: what happened, why, what to do
- Numbers always have context ("78% of drop in JP market", not just "JP dropped")
- Confidence stated explicitly with criteria
- Every action has an owner
- State what would change confidence level

### Anti-Patterns (NEVER produce these):
- Data dump: many numbers without narrative
- Hedge parade: "it could be X, or maybe Y, or possibly Z"
- Orphaned recommendation: "further investigation needed" with no owner
- Passive voice: "the metric was impacted by changes"

### Special Case: AI Answer Adoption
If Click Quality dropped but ai_answer_rate increased in ai_on cohort:
- Label as "AI_ADOPTION_EFFECT" (POSITIVE signal)
- Slack tone: "Click Quality decline reflects successful AI answer adoption"
- Do NOT treat as regression
```

**Step 2: Verify skill file is valid markdown**

Read it back and check structure.

**Step 3: Commit**

```bash
git add skills/search-metric-analyzer.md
git commit -m "feat: add Claude Code diagnostic skill with 4-step methodology"
```

---

## Task 9: Eval Framework (Scoring Specs + MVE Runner)

**Files:**
- Create: `eval/scoring_specs/case1_single_cause.yaml`
- Create: `eval/scoring_specs/case2_multi_cause.yaml`
- Create: `eval/scoring_specs/case3_false_alarm.yaml`
- Create: `eval/run_eval.py`
- Test: `tests/test_eval.py`

**Step 1: Create scoring spec for Case 1 (single cause)**

```yaml
# eval/scoring_specs/case1_single_cause.yaml
# MVE Case 1: S4 — Ranking model regression for Standard tier
# Archetype: single-cause, clean signal

case:
  name: "Single-cause ranking regression"
  scenario: "S4"
  archetype: "single_cause_clean_signal"
  purpose: "Can the tool find an obvious problem and attribute it correctly?"

must_find:
  root_cause: "Ranking model change degraded Standard tier queries"
  semantic_match: true  # LLM-as-judge checks semantic similarity

must_check_dimensions:
  - tenant_tier
  - query_type
  - position_bucket

must_not_do:
  - attribute_to_ai_feature: "Should not blame AI answers"
  - claim_data_quality_issue: "Data is clean in this scenario"
  - hedge_excessively: "Should state root cause with High confidence"

output_quality:
  has_tldr: true
  confidence_stated: true
  confidence_level: "High"
  actionable_recommendation: true
  no_anti_patterns: true
```

**Step 2: Create scoring specs for Cases 2 and 3**

Similar YAML files for:
- Case 2 (S7): Must find BOTH causes, must NOT over-attribute, confidence should be Medium
- Case 3 (S0/S1): Must conclude "no action needed", must NOT flag as incident

**Step 3: Write eval runner test**

```python
# tests/test_eval.py
"""Tests for the MVE eval runner."""

import yaml
import pytest
from pathlib import Path

EVAL_DIR = Path(__file__).parent.parent / "eval"


class TestScoringSpecs:
    """Verify scoring spec files exist and have correct structure."""

    @pytest.mark.parametrize("case_file", [
        "case1_single_cause.yaml",
        "case2_multi_cause.yaml",
        "case3_false_alarm.yaml",
    ])
    def test_scoring_spec_exists(self, case_file):
        spec_path = EVAL_DIR / "scoring_specs" / case_file
        assert spec_path.exists(), f"Missing scoring spec: {case_file}"

    @pytest.mark.parametrize("case_file", [
        "case1_single_cause.yaml",
        "case2_multi_cause.yaml",
        "case3_false_alarm.yaml",
    ])
    def test_scoring_spec_has_required_fields(self, case_file):
        spec_path = EVAL_DIR / "scoring_specs" / case_file
        with open(spec_path) as f:
            spec = yaml.safe_load(f)

        assert "case" in spec
        assert "must_find" in spec
        assert "must_check_dimensions" in spec
        assert "must_not_do" in spec
        assert "output_quality" in spec
```

**Step 4: Implement eval runner skeleton**

Create `eval/run_eval.py` with:
- Load scoring specs
- For each case: run diagnosis 3 times, evaluate with LLM-as-judge
- Aggregate results: GREEN/YELLOW/RED per case
- Output summary report

**Step 5: Run tests**

Run: `pytest tests/test_eval.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add eval/ tests/test_eval.py
git commit -m "feat: add MVE eval framework with 3-case scoring specs"
```

---

## Task 10: End-to-End Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

```python
# tests/test_integration.py
"""End-to-end integration test: synthetic data → decompose → diagnose → format."""

import json
import pytest
from tools.decompose import run_decomposition
from tools.diagnose import run_diagnosis
from tools.formatter import format_diagnosis_output


class TestEndToEnd:
    """Run the full pipeline on sample data and verify output quality."""

    def test_full_pipeline_produces_slack_and_report(self, sample_metric_rows):
        # Step 1-2: Decompose
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        assert decomp["aggregate"]["error"] is None

        # Step 3: Diagnose
        diagnosis = run_diagnosis(decomposition=decomp)
        assert diagnosis["confidence"]["level"] in ["High", "Medium", "Low"]

        # Step 4: Format
        output = format_diagnosis_output(diagnosis)
        assert "slack_message" in output
        assert "short_report" in output
        assert len(output["slack_message"]) > 50  # not empty
        assert "TL;DR" in output["short_report"] or "Summary" in output["short_report"]

    def test_output_is_json_serializable(self, sample_metric_rows):
        decomp = run_decomposition(sample_metric_rows, "click_quality_value",
                                   dimensions=["tenant_tier"])
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)
        # Everything must be JSON-serializable for Claude Code
        json_str = json.dumps(output)
        assert json_str is not None
```

**Step 2: Run integration test**

Run: `pytest tests/test_integration.py -v`
Expected: All tests PASS

**Step 3: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS across all test files

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: add end-to-end integration test for full diagnostic pipeline"
```

**Step 5: Final commit — tag as v1-alpha**

```bash
git tag -a v1-alpha -m "Search Metric Analyzer v1 alpha: skill + toolkit + eval framework"
```

---

## Implementation Notes for the Developer

### Parallel Execution Opportunities

- **Tasks 3 & 4** (decompose.py & anomaly.py) have no dependencies on each other — implement in parallel
- **Task 7** (generator extension) can start as soon as Task 2 (knowledge encoding) is done
- **Tasks 5 & 6** depend on Tasks 3 & 4 but not on each other if interfaces are defined

### Key Invariants to Maintain

1. **All tool output is JSON to stdout.** Claude Code reads JSON. Never print debug info to stdout.
2. **All tools work as both importable modules AND CLI scripts.** Tests import functions; Claude Code calls CLI.
3. **Knowledge YAML files are the single source of truth** for metric definitions, baselines, thresholds, and co-movement patterns. Don't hardcode these in Python.
4. **Tests use fixtures from conftest.py** for sample data. Don't duplicate test data.

### Definition of Done

Per design doc success criteria:
- [ ] 3+ scenario types work end-to-end (single-cause, multi-cause, false alarm)
- [ ] Slack message passes anti-pattern checks (no hedging, no data dumps)
- [ ] All validation checks produce correct status for test scenarios
- [ ] `pytest tests/ -v` passes with 0 failures
- [ ] Code is committed with descriptive messages
- [ ] Skill file can be loaded in Claude Code
