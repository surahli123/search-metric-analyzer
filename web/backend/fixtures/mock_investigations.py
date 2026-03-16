"""
Mock investigation fixtures for Phase 1 backend demo.

These are hardcoded response dicts that replicate what the real orchestrator
would return from a live investigation. They let the frontend/API layer be
tested and demoed without running the full Python analysis pipeline.

DS Lead review fixes applied:
  Fix 1: Within Variance SQS delta_pct = +0.3 (not +0.7 — that would be P1)
  Fix 2: Hypotheses show only 'matched' and 'not_evaluated' (no fabricated 'ruled_out')
  Fix 3: Ranking Regression enterprise counts = 130 vs 150 (not 89 vs 150)
"""

# ---------------------------------------------------------------------------
# Fixture 1: Within Variance
# Scenario: SQS looks fine, CQ dipped slightly due to AI adoption (positive).
# ---------------------------------------------------------------------------
WITHIN_VARIANCE = {
    "investigation_id": "mock-within-variance-001",
    "diagnosis": {
        "verdict": "within_variance",
        "verdict_label": "Within Variance",
        "is_positive": False,
        "confidence": {
            "level": "Low",
            "explained_pct": 65.0,
            "evidence_count": 1,
            "reason": "Movement within normal fluctuation range",
        },
        "co_movement": {
            "pattern_matched": "ai_adoption",
            "is_positive": True,
            "metric_directions": {
                "click_quality": {"direction": "down", "delta_pct": -1.1},
                "search_quality_success": {"direction": "up", "delta_pct": 0.4},
                "ai_trigger": {"direction": "up", "delta_pct": 6.7},
                "ai_success": {"direction": "up", "delta_pct": 1.5},
            },
            # AI Trigger ↑ + CQ ↓ + SQS stable/up = expected inverse co-movement.
            # This is a positive signal, not a regression.
            "pattern_description": "CQ down, AI Trigger up, SQS stable/up — AI adoption pattern (positive)",
        },
        # Fix 2: only 'matched' and 'not_evaluated' statuses — no 'ruled_out'
        "hypotheses_evaluated": [
            {"category": "instrumentation", "status": "not_evaluated"},
            {"category": "connector", "status": "not_evaluated"},
            {"category": "query_understanding", "status": "not_evaluated"},
            {"category": "algorithm_model", "status": "not_evaluated"},
            {"category": "experiment", "status": "not_evaluated"},
            {
                "category": "ai_feature",
                "status": "matched",
                "reason": "Co-movement matches AI adoption pattern",
            },
            {"category": "seasonal", "status": "not_evaluated"},
            {"category": "user_behavior", "status": "not_evaluated"},
        ],
        "hypothesis": {
            "archetype": "ai_adoption",
            "dimension": "tenant_tier",
            "segment": "enterprise",
            "contribution_pct": 68.0,
            "confirms_if": ["AI trigger rate increase correlates with CQ decrease"],
            "rejects_if": ["AI metrics stable while CQ drops"],
        },
        # Fix 1: delta_pct = 0.3 — within P2 range (< 1.5), not P1
        "aggregate": {
            "metric": "search_quality_success_value",
            "severity": "P2",
            "delta_pct": 0.3,
        },
        "dimensional_breakdown": {
            "dimension": "tenant_tier",
            "segments": [
                {
                    "segment": "enterprise",
                    "current_count": 89,
                    "baseline_count": 95,
                    "current_value": 73.8,
                    "baseline_value": 71.7,
                    "delta_pp": 2.1,
                    "traffic_share_pct": 25.6,
                    "weighted_delta": 0.537,
                    "contribution_pct": 68.0,
                },
                {
                    "segment": "premium",
                    "current_count": 124,
                    "baseline_count": 118,
                    "current_value": 71.0,
                    "baseline_value": 70.6,
                    "delta_pp": 0.4,
                    "traffic_share_pct": 35.6,
                    "weighted_delta": 0.142,
                    "contribution_pct": 22.0,
                },
                {
                    "segment": "standard",
                    "current_count": 135,
                    "baseline_count": 134,
                    "current_value": 69.5,
                    "baseline_value": 69.4,
                    "delta_pp": 0.1,
                    "traffic_share_pct": 38.8,
                    "weighted_delta": 0.039,
                    "contribution_pct": 10.0,
                },
            ],
        },
        "mix_shift": {
            "detected": False,
            "mix_shift_contribution_pct": 8.2,
            "behavioral_contribution_pct": 91.8,
            "flag": None,
        },
        "validation_checks": [
            {"label": "Logging artifact", "status": "pass"},
            {"label": "Decomposition completeness", "status": "pass"},
            {"label": "Trust gate", "status": "pass"},
        ],
    },
    "narrative": {
        "text": (
            "<strong>Search Quality Success for Customer Cohort FPS</strong> measured at "
            "<strong>70.8%</strong> this week vs 70.5% last week (<strong>+0.3pp</strong>). "
            "The movement is driven by a <strong>+2.4pp increase in AI Trigger Rate</strong> "
            "(35.8% → 38.2%), offset by a small Click Quality dip (-0.7pp) — consistent with "
            "the expected inverse co-movement pattern when AI answers increase. Sample size is "
            "modest (n=348); consider monitoring for another week before drawing firm conclusions."
        ),
        "source": "template",
        "hedging": "Sample size is modest (n=348)",
    },
    "data_context": {
        "data_source": "search_query_relevance_metrics_enriched",
        "data_freshness": {
            "raw_data": "2026-02-24T18:00:00Z",
            "enrichment": "2026-02-24T14:00:00Z",
            "status": "fresh",
            "status_note": "fresh (<6h), stale (6-24h), critical (>24h)",
        },
        "queries_analyzed": 348,
        "metric_formula": "max(click_component, ai_trigger * ai_success)",
        "metric_formula_note": "Formula resolved from metric_definitions.yaml for search_quality_success",
        "filters_applied": [
            "searchExperience = 'fullPageSearch'",
            "is_hello = 0",
        ],
    },
    "sql_queries": [
        {
            "description": "Data quality gate — check logging completeness and freshness",
            "sql": (
                "SELECT\n"
                "  DATE(query_timestamp) AS query_date,\n"
                "  COUNT(*) AS total_queries,\n"
                "  COUNT(DISTINCT user_id) AS unique_users,\n"
                "  AVG(CASE WHEN click_quality_value IS NOT NULL THEN 1 ELSE 0 END) AS completeness\n"
                "FROM search_query_relevance_metrics_enriched\n"
                "WHERE query_date BETWEEN '2026-02-17' AND '2026-02-24'\n"
                "  AND search_experience = 'fullPageSearch'\n"
                "GROUP BY 1\n"
                "ORDER BY 1"
            ),
            "duration_s": 3.2,
            "rows": 7,
        },
        {
            "description": "Week-over-week metric comparison by tenant tier",
            "sql": (
                "SELECT\n"
                "  tenant_tier,\n"
                "  week_label,\n"
                "  COUNT(*) AS n,\n"
                "  AVG(search_quality_success_value) AS sqs,\n"
                "  AVG(click_quality_value) AS cq,\n"
                "  AVG(ai_trigger) AS ai_trig,\n"
                "  AVG(ai_success) AS ai_succ\n"
                "FROM search_query_relevance_metrics_enriched\n"
                "WHERE query_date BETWEEN '2026-02-10' AND '2026-02-24'\n"
                "  AND search_experience = 'fullPageSearch'\n"
                "GROUP BY 1, 2\n"
                "ORDER BY 1, 2"
            ),
            "duration_s": 5.8,
            "rows": 6,
        },
    ],
    "orchestration": {
        "orchestrated": False,
        "agents_run": [],
        "fused_verdict": None,
        "fused_reason": None,
        "updated_decision_status": "diagnosed",
        "run_log": [],
    },
    "display": {
        "question": "What does SQS look like this week vs last week for Customer Cohort FPS?",
        "results_title": "SQS Week-over-Week — Customer Cohort FPS",
        "results_date_range": "2026-02-10 → 2026-02-24",
        "results_headers": ["Period", "Queries", "SQS", "Click", "AI Trigger", "AI Success", "Δ SQS"],
        "results_rows": [
            {
                "period": "This week",
                "queries": "348",
                "col3": "70.8%",
                "col4": "65.4%",
                "col5": "38.2%",
                "col6": "82.1%",
                "delta": "+0.3pp",
            },
            {
                "period": "Last week",
                "queries": "347",
                "col3": "70.5%",
                "col4": "66.1%",
                "col5": "35.8%",
                "col6": "80.9%",
                "delta": "—",
            },
        ],
        # Diverging bar chart data — each bar has direction (left/right) and width_pct
        # so the frontend can render without computing layout math.
        "chart_bars": [
            {"label": "SQS (net)", "value": "+0.3", "width_pct": 6, "direction": "right", "color": "accent", "opacity": 1, "bold": True},
            {"label": "AI Trigger Rate", "value": "+2.4", "width_pct": 48, "direction": "right", "color": "accent", "opacity": 1, "bold": False},
            {"label": "AI Success Rate", "value": "+1.2", "width_pct": 24, "direction": "right", "color": "accent", "opacity": 0.6, "bold": False},
            {"label": "Click Quality", "value": "-0.7", "width_pct": 14, "direction": "left", "color": "accent", "opacity": 0.75, "bold": False},
            {"label": "Zero Result Rate", "value": "0.0", "width_pct": 0, "direction": "dot", "color": "muted", "opacity": 0.5, "bold": False},
        ],
        "trend_data": {
            "title": "SQS Daily Trend — This Week vs Last Week",
            "current": [
                {"day": "Mon", "value": 69.5},
                {"day": "Tue", "value": 70.2},
                {"day": "Wed", "value": 69.8},
                {"day": "Thu", "value": 71.5},
                {"day": "Fri", "value": 70.8},
                {"day": "Sat", "value": 71.2},
                {"day": "Sun", "value": 71.8},
            ],
            "previous": [
                {"day": "Mon", "value": 70.0},
                {"day": "Tue", "value": 70.5},
                {"day": "Wed", "value": 69.2},
                {"day": "Thu", "value": 70.8},
                {"day": "Fri", "value": 70.3},
                {"day": "Sat", "value": 70.5},
                {"day": "Sun", "value": 71.0},
            ],
            "legend_current": "This week (70.8% avg, n=348)",
            "legend_previous": "Last week (70.5% avg, n=347)",
        },
        "segment_title": "SQS by Tenant Tier — Decomposition",
        "segment_metric_label": "SQS",
        "segment_insight": "Enterprise tier (n=89) drives 68% of the blended SQS movement at +2.1pp. Premium and Standard show small changes.",
        "footer": {
            "verdict_text": "Within Variance",
            "summary": "SQS trending positive (+0.3pp WoW, +1.4pp over 3 weeks)",
            "total_queries": "695 total",
            "date_range": "2026-02-03 → 2026-02-24",
        },
        "chart_insight_html": (
            "<span class=\"insight-badge expected\">Expected co-movement</span> "
            "<strong>Pattern:</strong> AI Trigger ↑ and Click Quality ↓ is the expected "
            "inverse co-movement — more AI answers means fewer clicks. Net SQS is positive."
        ),
    },
}


# ---------------------------------------------------------------------------
# Fixture 2: Ranking Regression
# Scenario: CQ dropped -15.2% for enterprise tenants — real regression.
# Fix 3: enterprise current_count=130, baseline_count=150 (not 89 vs 150)
# ---------------------------------------------------------------------------
RANKING_REGRESSION = {
    "investigation_id": "mock-ranking-regression-001",
    "diagnosis": {
        "verdict": "ranking_regression",
        "verdict_label": "Ranking Regression",
        "is_positive": False,
        "confidence": {
            "level": "Medium",
            "explained_pct": 82.3,
            "evidence_count": 2,
            # Just below 90% threshold for High confidence
            "reason": "Explained percentage below 90% threshold for High",
        },
        "co_movement": {
            "pattern_matched": "ranking_regression",
            "is_positive": False,
            "metric_directions": {
                "click_quality": {"direction": "down", "delta_pct": -15.2},
                "search_quality_success": {"direction": "down", "delta_pct": -4.5},
                # AI metrics are stable — ruling out AI adoption trap
                "ai_trigger": {"direction": "stable", "delta_pct": 0.3},
                "ai_success": {"direction": "stable", "delta_pct": -0.1},
            },
            "pattern_description": "CQ down significantly, SQS down, AI metrics stable — ranking regression pattern",
        },
        # Fix 2: only 'matched' and 'not_evaluated' — no 'ruled_out'
        "hypotheses_evaluated": [
            {"category": "instrumentation", "status": "not_evaluated"},
            {"category": "connector", "status": "not_evaluated"},
            {"category": "query_understanding", "status": "not_evaluated"},
            {
                "category": "algorithm_model",
                "status": "matched",
                "reason": "Co-movement matches ranking regression pattern",
            },
            {"category": "experiment", "status": "not_evaluated"},
            {"category": "ai_feature", "status": "not_evaluated"},
            {"category": "seasonal", "status": "not_evaluated"},
            {"category": "user_behavior", "status": "not_evaluated"},
        ],
        "hypothesis": {
            "archetype": "ranking_regression",
            "dimension": "tenant_tier",
            "segment": "enterprise",
            "contribution_pct": 85.0,
            "confirms_if": [
                "Ranking model change or experiment de-ramp in enterprise cohort",
                "NDCG offline eval shows degradation in same time window",
            ],
            "rejects_if": [
                "No ranking model changes deployed in the window",
                "Regression appears in standard/premium but not enterprise",
            ],
        },
        "aggregate": {
            "metric": "click_quality_value",
            "severity": "P1",
            "delta_pct": -15.2,
        },
        "dimensional_breakdown": {
            "dimension": "tenant_tier",
            "segments": [
                {
                    # Fix 3: 130 vs 150 (plausible churn/count change for a real regression)
                    "segment": "enterprise",
                    "current_count": 130,
                    "baseline_count": 150,
                    "current_value": 25.0,
                    "baseline_value": 29.5,
                    "delta_pp": -4.5,
                    "traffic_share_pct": 32.2,
                    "weighted_delta": -1.449,
                    "contribution_pct": 85.0,
                },
                {
                    "segment": "premium",
                    "current_count": 124,
                    "baseline_count": 118,
                    "current_value": 28.1,
                    "baseline_value": 28.4,
                    "delta_pp": -0.3,
                    "traffic_share_pct": 30.7,
                    "weighted_delta": -0.092,
                    "contribution_pct": 10.0,
                },
                {
                    "segment": "standard",
                    "current_count": 150,
                    "baseline_count": 142,
                    "current_value": 24.8,
                    "baseline_value": 24.9,
                    "delta_pp": -0.1,
                    "traffic_share_pct": 37.1,
                    "weighted_delta": -0.037,
                    "contribution_pct": 5.0,
                },
            ],
        },
        "mix_shift": {
            "detected": False,
            "mix_shift_contribution_pct": 5.1,
            "behavioral_contribution_pct": 94.9,
            "flag": None,
        },
        "validation_checks": [
            {"label": "Logging artifact", "status": "pass"},
            # Warn because decomposition only explains 82% — some movement unexplained
            {"label": "Decomposition completeness", "status": "warn"},
            {"label": "Trust gate", "status": "pass"},
        ],
    },
    "narrative": {
        "text": (
            "<strong>Click Quality for Enterprise tenants</strong> dropped from "
            "<strong>29.5% to 25.0%</strong> (-4.5pp, <strong>-15.2%</strong>) week-over-week. "
            "This is a <strong>P1 severity</strong> regression. The co-movement pattern — "
            "CQ down sharply, SQS down, AI metrics stable — is consistent with a "
            "<strong>ranking regression</strong>, not an AI adoption effect. "
            "Enterprise drives 85% of the blended movement (n=130 vs 150 baseline). "
            "Recommended next step: check ranking model deployments and experiment ramps "
            "in the 2026-02-24 to 2026-03-07 window."
        ),
        "source": "template",
        "hedging": None,
    },
    "data_context": {
        "data_source": "search_query_relevance_metrics_enriched",
        "data_freshness": {
            "raw_data": "2026-03-07T18:00:00Z",
            "enrichment": "2026-03-07T14:00:00Z",
            "status": "fresh",
            "status_note": "fresh (<6h), stale (6-24h), critical (>24h)",
        },
        "queries_analyzed": 2450,
        "metric_formula": "sum(long_clicks * log2_discount(rank)) / impressions",
        "metric_formula_note": "Formula resolved from metric_definitions.yaml for click_quality",
        "filters_applied": [
            "searchExperience = 'fullPageSearch'",
            "is_hello = 0",
            "tenant_tier = 'enterprise'",
        ],
    },
    "sql_queries": [
        {
            "description": "Data quality gate — check logging completeness and freshness",
            "sql": (
                "SELECT\n"
                "  DATE(query_timestamp) AS query_date,\n"
                "  COUNT(*) AS total_queries,\n"
                "  COUNT(DISTINCT user_id) AS unique_users,\n"
                "  AVG(CASE WHEN click_quality_value IS NOT NULL THEN 1 ELSE 0 END) AS completeness\n"
                "FROM search_query_relevance_metrics_enriched\n"
                "WHERE query_date BETWEEN '2026-02-24' AND '2026-03-07'\n"
                "  AND search_experience = 'fullPageSearch'\n"
                "GROUP BY 1\n"
                "ORDER BY 1"
            ),
            "duration_s": 4.1,
            "rows": 7,
        },
        {
            "description": "Week-over-week Click Quality comparison by tenant tier",
            "sql": (
                "SELECT\n"
                "  tenant_tier,\n"
                "  week_label,\n"
                "  COUNT(*) AS n,\n"
                "  AVG(click_quality_value) AS cq,\n"
                "  AVG(search_quality_success_value) AS sqs,\n"
                "  AVG(ai_trigger) AS ai_trig,\n"
                "  AVG(ai_success) AS ai_succ\n"
                "FROM search_query_relevance_metrics_enriched\n"
                "WHERE query_date BETWEEN '2026-02-17' AND '2026-03-07'\n"
                "  AND search_experience = 'fullPageSearch'\n"
                "GROUP BY 1, 2\n"
                "ORDER BY 1, 2"
            ),
            "duration_s": 6.3,
            "rows": 6,
        },
    ],
    "orchestration": {
        "orchestrated": False,
        "agents_run": [],
        "fused_verdict": None,
        "fused_reason": None,
        "updated_decision_status": "diagnosed",
        "run_log": [],
    },
    "display": {
        "question": "Why did Click Quality drop for enterprise tenants last week?",
        "results_title": "Click Quality Week-over-Week — Enterprise Tenants",
        "results_date_range": "2026-02-24 → 2026-03-07",
        "results_headers": ["Period", "Queries", "CQ", "SQS", "AI Trigger", "AI Success", "Δ CQ"],
        "results_rows": [
            {
                "period": "This week",
                "queries": "1,287",
                "col3": "25.0%",
                "col4": "68.2%",
                "col5": "38.5%",
                "col6": "82.0%",
                "delta": "-4.5pp",
            },
            {
                "period": "Last week",
                "queries": "1,163",
                "col3": "29.5%",
                "col4": "72.7%",
                "col5": "38.2%",
                "col6": "82.1%",
                "delta": "—",
            },
        ],
        # Red bars for regressions — direction "left" = negative movement
        "chart_bars": [
            {"label": "Click Quality", "value": "-4.5", "width_pct": 90, "direction": "left", "color": "red", "opacity": 1, "bold": True},
            {"label": "SQS", "value": "-1.7", "width_pct": 34, "direction": "left", "color": "red", "opacity": 0.75, "bold": False},
            {"label": "AI Trigger Rate", "value": "+0.2", "width_pct": 4, "direction": "right", "color": "muted", "opacity": 0.5, "bold": False},
            {"label": "AI Success Rate", "value": "-0.2", "width_pct": 4, "direction": "left", "color": "muted", "opacity": 0.5, "bold": False},
            {"label": "Zero Result Rate", "value": "0.0", "width_pct": 0, "direction": "dot", "color": "muted", "opacity": 0.5, "bold": False},
        ],
        "trend_data": {
            "title": "Click Quality Daily Trend — This Week vs Last Week",
            "current": [
                {"day": "Mon", "value": 27.2},
                {"day": "Tue", "value": 26.5},
                {"day": "Wed", "value": 25.8},
                {"day": "Thu", "value": 24.9},
                {"day": "Fri", "value": 25.0},
                {"day": "Sat", "value": 24.5},
                {"day": "Sun", "value": 24.2},
            ],
            "previous": [
                {"day": "Mon", "value": 29.8},
                {"day": "Tue", "value": 29.6},
                {"day": "Wed", "value": 29.4},
                {"day": "Thu", "value": 29.5},
                {"day": "Fri", "value": 29.3},
                {"day": "Sat", "value": 29.6},
                {"day": "Sun", "value": 29.5},
            ],
            "legend_current": "This week (25.0% avg, n=1,287)",
            "legend_previous": "Last week (29.5% avg, n=1,163)",
        },
        "segment_title": "Click Quality by Tenant Tier — Decomposition",
        "segment_metric_label": "CQ",
        "segment_insight": "Enterprise tier (n=130 vs 150 baseline) drives 85% of the blended CQ movement at -4.5pp. Premium and Standard are stable.",
        "footer": {
            "verdict_text": "Ranking Regression",
            "summary": "Click Quality down -4.5pp WoW for Enterprise (P1 severity)",
            "total_queries": "2,450 total",
            "date_range": "2026-02-17 → 2026-03-07",
        },
        "chart_insight_html": (
            "<span class=\"insight-badge regression\">Regression detected</span> "
            "<strong>Pattern:</strong> Click Quality ↓ with AI metrics stable — "
            "this is a ranking regression, not an AI adoption effect. "
            "Investigate ranking model deployments in the affected window."
        ),
    },
}


# ---------------------------------------------------------------------------
# FIXTURE_MAP — maps metric name → fixture.
# The diagnose route uses this to select the right scenario.
# Both canonical (e.g. "click_quality") and value-suffixed names are supported.
# ---------------------------------------------------------------------------
FIXTURE_MAP = {
    "search_quality_success_value": WITHIN_VARIANCE,
    "search_quality_success": WITHIN_VARIANCE,
    "click_quality_value": RANKING_REGRESSION,
    "click_quality": RANKING_REGRESSION,
}
