// Scenario data for the Search Metric Analyzer demo.
//
// WHY this file exists: the frontend is currently in "mock mode" — it renders
// pre-baked investigation results from this file rather than calling the FastAPI
// backend. This lets us demo the full UI without a live backend.
//
// HOW to add a new scenario: add a new key to SCENARIOS, following the same
// shape as the existing two. The key is used for URL routing and tab switching.
//
// DATA INTEGRITY NOTES (from 3-role IC9 review, 2026-03-15):
// - "Within Variance" SQS delta is +0.3pp (not +0.7pp which would be P1 severity)
// - Hypothesis status is "matched" or "not_evaluated" ONLY — no fabricated "ruled_out"
// - All numeric values are observed raw values; no CIs or significance badges

export const SCENARIOS = {
  within_variance: {
    investigation_id: "mock-within-variance-001",
    diagnosis: {
      verdict: "within_variance",
      verdict_label: "Within Variance",
      is_positive: false,
      confidence: { level: "Low", explained_pct: 65.0, evidence_count: 1, reason: "Movement within normal fluctuation range" },
      co_movement: {
        pattern_matched: "ai_adoption",
        is_positive: true,
        metric_directions: {
          click_quality: { direction: "down", delta_pct: -1.1 },
          search_quality_success: { direction: "up", delta_pct: 0.4 },
          ai_trigger: { direction: "up", delta_pct: 6.7 },
          ai_success: { direction: "up", delta_pct: 1.5 },
        },
        pattern_description: "CQ down, AI Trigger up, SQS stable/up — AI adoption pattern (positive)",
      },
      hypotheses_evaluated: [
        { category: "instrumentation", status: "not_evaluated" },
        { category: "connector", status: "not_evaluated" },
        { category: "query_understanding", status: "not_evaluated" },
        { category: "algorithm_model", status: "not_evaluated" },
        { category: "experiment", status: "not_evaluated" },
        { category: "ai_feature", status: "matched", reason: "Co-movement matches AI adoption pattern" },
        { category: "seasonal", status: "not_evaluated" },
        { category: "user_behavior", status: "not_evaluated" },
      ],
      hypothesis: { archetype: "ai_adoption", dimension: "tenant_tier", segment: "enterprise", contribution_pct: 68.0, confirms_if: ["AI trigger rate increase correlates with CQ decrease"], rejects_if: ["AI metrics stable while CQ drops"] },
      aggregate: { metric: "search_quality_success_value", severity: "P2", delta_pct: 0.3 },
      dimensional_breakdown: {
        dimension: "tenant_tier",
        segments: [
          { segment: "enterprise", current_count: 89, baseline_count: 95, current_value: 73.8, baseline_value: 71.7, delta_pp: 2.1, traffic_share_pct: 25.6, weighted_delta: 0.537, contribution_pct: 68.0 },
          { segment: "premium", current_count: 124, baseline_count: 118, current_value: 71.0, baseline_value: 70.6, delta_pp: 0.4, traffic_share_pct: 35.6, weighted_delta: 0.142, contribution_pct: 22.0 },
          { segment: "standard", current_count: 135, baseline_count: 134, current_value: 69.5, baseline_value: 69.4, delta_pp: 0.1, traffic_share_pct: 38.8, weighted_delta: 0.039, contribution_pct: 10.0 },
        ],
      },
      mix_shift: { detected: false, mix_shift_contribution_pct: 8.2, behavioral_contribution_pct: 91.8, flag: null },
      validation_checks: [
        { label: "Logging artifact", status: "pass" },
        { label: "Decomposition completeness", status: "pass" },
        { label: "Trust gate", status: "pass" },
      ],
    },
    narrative: {
      text: "<strong>Search Quality Success for all tenants</strong> measured at <strong>70.8%</strong> this week vs 70.5% last week (<strong>+0.3pp</strong>). The movement is driven by a <strong>+2.4pp increase in AI Trigger Rate</strong> (35.8% → 38.2%), offset by a small Click Quality dip (-0.7pp) — consistent with the expected inverse co-movement pattern when AI answers increase. Sample size is modest (n=348); consider monitoring for another week before drawing firm conclusions.",
      source: "template",
      hedging: "Sample size is modest (n=348)",
    },
    data_context: {
      data_source: "search_query_relevance_metrics_enriched",
      data_freshness: { raw_data: "2026-02-24T18:00:00Z", enrichment: "2026-02-24T14:00:00Z", status: "fresh", status_note: "fresh (<6h), stale (6-24h), critical (>24h)" },
      queries_analyzed: 348,
      metric_formula: "max(click_component, ai_trigger * ai_success)",
      metric_formula_note: "Formula resolved from metric_definitions.yaml for search_quality_success",
      filters_applied: ["searchExperience = 'fullPageSearch'", "is_hello = 0"],
    },
    sql_queries: [
      { description: "Data quality gate — check logging completeness and freshness", sql: "SELECT\n  DATE(query_timestamp) AS query_date,\n  COUNT(*) AS total_queries,\n  COUNT(DISTINCT user_id) AS unique_users,\n  AVG(CASE WHEN click_quality_value IS NOT NULL THEN 1 ELSE 0 END) AS completeness\nFROM search_query_relevance_metrics_enriched\nWHERE query_date BETWEEN '2026-02-17' AND '2026-02-24'\n  AND search_experience = 'fullPageSearch'\nGROUP BY 1\nORDER BY 1", duration_s: 3.2, rows: 7 },
      { description: "Week-over-week metric comparison by tenant tier", sql: "SELECT\n  tenant_tier,\n  week_label,\n  COUNT(*) AS n,\n  AVG(search_quality_success_value) AS sqs,\n  AVG(click_quality_value) AS cq,\n  AVG(ai_trigger) AS ai_trig,\n  AVG(ai_success) AS ai_succ\nFROM search_query_relevance_metrics_enriched\nWHERE query_date BETWEEN '2026-02-10' AND '2026-02-24'\n  AND search_experience = 'fullPageSearch'\nGROUP BY 1, 2\nORDER BY 1, 2", duration_s: 5.8, rows: 6 },
    ],
    orchestration: { orchestrated: false, agents_run: [], fused_verdict: null, fused_reason: null, updated_decision_status: "diagnosed", run_log: [] },
    display: {
      question: "How is Search Quality Success (SQS) performing this week vs. last?",
      verdict_human: "Normal fluctuation — no action needed",
      severity_human: "Minor",
      results_title: "SQS Week-over-Week",
      results_date_range: "2026-02-10 → 2026-02-24",
      results_headers: ["Period", "Queries", "SQS", "Click", "AI Trigger", "AI Success", "Δ SQS"],
      results_rows: [
        { period: "This week", queries: "348", col3: "70.8%", col4: "65.4%", col5: "38.2%", col6: "82.1%", delta: "+0.3pp" },
        { period: "Last week", queries: "347", col3: "70.5%", col4: "66.1%", col5: "35.8%", col6: "80.9%", delta: "—" },
      ],
      chart_bars: [
        { label: "SQS (net)", value: "+0.3", width_pct: 6, direction: "right", color: "accent", opacity: 1, bold: true },
        { label: "AI Trigger Rate", value: "+2.4", width_pct: 48, direction: "right", color: "accent", opacity: 1, bold: false },
        { label: "AI Success Rate", value: "+1.2", width_pct: 24, direction: "right", color: "accent", opacity: 0.6, bold: false },
        { label: "Click Quality", value: "-0.7", width_pct: 14, direction: "left", color: "accent", opacity: 0.75, bold: false },
        { label: "Zero Result Rate", value: "0.0", width_pct: 0, direction: "dot", color: "muted", opacity: 0.5, bold: false },
      ],
      trend_data: {
        title: "SQS Daily Trend — This Week vs Last Week",
        current: [{ day: "Mon", value: 69.5 }, { day: "Tue", value: 70.2 }, { day: "Wed", value: 69.8 }, { day: "Thu", value: 71.5 }, { day: "Fri", value: 70.8 }, { day: "Sat", value: 71.2 }, { day: "Sun", value: 71.8 }],
        previous: [{ day: "Mon", value: 70.0 }, { day: "Tue", value: 70.5 }, { day: "Wed", value: 69.2 }, { day: "Thu", value: 70.8 }, { day: "Fri", value: 70.3 }, { day: "Sat", value: 70.5 }, { day: "Sun", value: 71.0 }],
        legend_current: "This week (70.8% avg, n=348)",
        legend_previous: "Last week (70.5% avg, n=347)",
      },
      segment_title: "SQS by Tenant Tier — Decomposition",
      segment_metric_label: "SQS",
      segment_insight: "Enterprise tier (n=89) drives 68% of the blended SQS movement at +2.1pp. Premium and Standard show small changes.",
      footer: { verdict_text: "Within Variance", summary: "SQS trending positive (+0.3pp WoW, +1.4pp over 3 weeks)", total_queries: "695 total", date_range: "2026-02-03 → 2026-02-24" },
      chart_insight_html: '<span class="insight-badge expected">Expected co-movement</span> <strong>Pattern:</strong> AI Trigger ↑ and Click Quality ↓ is the expected inverse co-movement — more AI answers means fewer clicks. Net SQS is positive.',
    },
  },
  ranking_regression: {
    investigation_id: "mock-ranking-regression-001",
    diagnosis: {
      verdict: "ranking_regression",
      verdict_label: "Ranking Regression",
      is_positive: false,
      confidence: { level: "Medium", explained_pct: 82.3, evidence_count: 2, reason: "Explained percentage below 90% threshold for High" },
      co_movement: {
        pattern_matched: "ranking_regression",
        is_positive: false,
        metric_directions: {
          click_quality: { direction: "down", delta_pct: -15.2 },
          search_quality_success: { direction: "down", delta_pct: -4.5 },
          ai_trigger: { direction: "stable", delta_pct: 0.3 },
          ai_success: { direction: "stable", delta_pct: -0.1 },
        },
        pattern_description: "CQ and SQS both down, AI stable — likely ranking regression",
      },
      hypotheses_evaluated: [
        { category: "instrumentation", status: "not_evaluated" },
        { category: "connector", status: "not_evaluated" },
        { category: "query_understanding", status: "not_evaluated" },
        { category: "algorithm_model", status: "matched", reason: "Co-movement matches ranking regression pattern" },
        { category: "experiment", status: "not_evaluated" },
        { category: "ai_feature", status: "not_evaluated" },
        { category: "seasonal", status: "not_evaluated" },
        { category: "user_behavior", status: "not_evaluated" },
      ],
      hypothesis: { archetype: "ranking_regression", dimension: "tenant_tier", segment: "enterprise", contribution_pct: 85.0, confirms_if: ["ranking model version changed"], rejects_if: ["movement uniform across segments"] },
      aggregate: { metric: "click_quality_value", severity: "P1", delta_pct: -15.2 },
      dimensional_breakdown: {
        dimension: "tenant_tier",
        segments: [
          { segment: "enterprise", current_count: 130, baseline_count: 150, current_value: 25.0, baseline_value: 29.5, delta_pp: -4.5, traffic_share_pct: 32.2, weighted_delta: -1.449, contribution_pct: 85.0 },
          { segment: "premium", current_count: 124, baseline_count: 118, current_value: 28.1, baseline_value: 28.4, delta_pp: -0.3, traffic_share_pct: 30.7, weighted_delta: -0.092, contribution_pct: 10.0 },
          { segment: "standard", current_count: 150, baseline_count: 142, current_value: 24.8, baseline_value: 24.9, delta_pp: -0.1, traffic_share_pct: 37.1, weighted_delta: -0.037, contribution_pct: 5.0 },
        ],
      },
      mix_shift: { detected: false, mix_shift_contribution_pct: 5.1, behavioral_contribution_pct: 94.9, flag: null },
      validation_checks: [
        { label: "Logging artifact", status: "pass" },
        { label: "Decomposition completeness", status: "warn" },
        { label: "Trust gate", status: "pass" },
      ],
    },
    narrative: {
      text: "<strong>Click Quality for Enterprise tenants</strong> dropped from <strong>29.5%</strong> to <strong>25.0%</strong> week-over-week (<strong>-4.5pp, -15.2%</strong>). This is a <strong>P1 severity</strong> movement. Co-movement analysis shows SQS also declined (-4.5%) with AI metrics stable — consistent with a <strong>ranking model regression</strong>, not an AI feature effect. Enterprise tier drives 85% of the blended movement. Standard and Premium tiers show minimal change, suggesting the issue is isolated to enterprise-scale indices.",
      source: "template",
      hedging: null,
    },
    data_context: {
      data_source: "search_query_relevance_metrics_enriched",
      data_freshness: { raw_data: "2026-03-07T18:00:00Z", enrichment: "2026-03-07T16:00:00Z", status: "fresh", status_note: "fresh (<6h), stale (6-24h), critical (>24h)" },
      queries_analyzed: 2450,
      metric_formula: "sum(long_clicks * log2_discount(rank)) / impressions",
      metric_formula_note: "Formula resolved from metric_definitions.yaml for click_quality",
      filters_applied: ["searchExperience = 'fullPageSearch'", "is_hello = 0"],
    },
    sql_queries: [
      { description: "Data quality gate — check logging completeness and freshness", sql: "SELECT\n  DATE(query_timestamp) AS query_date,\n  COUNT(*) AS total_queries,\n  COUNT(DISTINCT user_id) AS unique_users,\n  AVG(CASE WHEN click_quality_value IS NOT NULL THEN 1 ELSE 0 END) AS completeness\nFROM search_query_relevance_metrics_enriched\nWHERE query_date BETWEEN '2026-02-24' AND '2026-03-07'\n  AND search_experience = 'fullPageSearch'\nGROUP BY 1\nORDER BY 1", duration_s: 4.1, rows: 7 },
      { description: "Week-over-week metric comparison by tenant tier", sql: "SELECT\n  tenant_tier,\n  week_label,\n  COUNT(*) AS n,\n  AVG(click_quality_value) AS cq,\n  AVG(search_quality_success_value) AS sqs,\n  AVG(ai_trigger) AS ai_trig,\n  AVG(ai_success) AS ai_succ\nFROM search_query_relevance_metrics_enriched\nWHERE query_date BETWEEN '2026-02-24' AND '2026-03-07'\n  AND search_experience = 'fullPageSearch'\nGROUP BY 1, 2\nORDER BY 1, 2", duration_s: 6.3, rows: 6 },
    ],
    orchestration: { orchestrated: false, agents_run: [], fused_verdict: null, fused_reason: null, updated_decision_status: "diagnosed", run_log: [] },
    display: {
      question: "Why did Click Quality drop for enterprise-tier tenants last week?",
      verdict_human: "Ranking quality dropped — needs investigation",
      severity_human: "Urgent",
      results_title: "Click Quality Week-over-Week — Enterprise Tenants",
      results_date_range: "2026-02-24 → 2026-03-07",
      results_headers: ["Period", "Queries", "CQ", "SQS", "AI Trigger", "AI Success", "Δ CQ"],
      results_rows: [
        { period: "This week", queries: "1,206", col3: "25.0%", col4: "64.2%", col5: "36.1%", col6: "81.8%", delta: "-4.5pp" },
        { period: "Last week", queries: "1,244", col3: "29.5%", col4: "68.7%", col5: "35.9%", col6: "82.0%", delta: "—" },
      ],
      chart_bars: [
        { label: "Click Quality", value: "-4.5", width_pct: 90, direction: "left", color: "red", opacity: 1, bold: true },
        { label: "SQS", value: "-1.7", width_pct: 34, direction: "left", color: "red", opacity: 0.7, bold: false },
        { label: "AI Trigger Rate", value: "+0.2", width_pct: 4, direction: "right", color: "muted", opacity: 0.4, bold: false },
        { label: "AI Success Rate", value: "-0.2", width_pct: 4, direction: "left", color: "muted", opacity: 0.4, bold: false },
        { label: "Zero Result Rate", value: "0.0", width_pct: 0, direction: "dot", color: "muted", opacity: 0.5, bold: false },
      ],
      trend_data: {
        title: "Click Quality Daily Trend — This Week vs Last Week",
        current: [{ day: "Mon", value: 27.0 }, { day: "Tue", value: 26.2 }, { day: "Wed", value: 25.5 }, { day: "Thu", value: 24.8 }, { day: "Fri", value: 24.0 }, { day: "Sat", value: 23.5 }, { day: "Sun", value: 24.0 }],
        previous: [{ day: "Mon", value: 29.8 }, { day: "Tue", value: 30.0 }, { day: "Wed", value: 29.2 }, { day: "Thu", value: 29.5 }, { day: "Fri", value: 30.0 }, { day: "Sat", value: 29.5 }, { day: "Sun", value: 29.2 }],
        legend_current: "This week (25.0% avg, n=1,206)",
        legend_previous: "Last week (29.5% avg, n=1,244)",
      },
      segment_title: "Click Quality by Tenant Tier — Decomposition",
      segment_metric_label: "CQ",
      segment_insight: "Enterprise tier (n=130) drives 85% of the Click Quality decline at -4.5pp. Premium and Standard are within normal fluctuation.",
      footer: { verdict_text: "Ranking Regression", summary: "Click Quality regression detected — enterprise tier driving 85% of movement", total_queries: "2,450 total", date_range: "2026-02-24 → 2026-03-07" },
      chart_insight_html: '<span class="insight-badge regression">Regression detected</span> <strong>Pattern:</strong> Click Quality ↓ and SQS ↓ with AI metrics stable — consistent with a ranking model regression. AI is not the cause.',
    },
  },
}

// Mock trace data shared by both scenarios — shows the 4-stage diagnostic pipeline.
// Each phase has steps with type-coded badges (sql, knowledge, reasoning, output).
// Phase 1 (demo): static data. Phase 2: live SSE streaming from backend.
export const TRACE_DATA = {
  within_variance: {
    phases: [
      {
        name: 'UNDERSTAND', status: 'done', duration_s: 3.2, steps: [
          { type: 'sql', label: 'Data quality gate', detail: 'Logging completeness check', duration_s: 3.2, rows: 7 },
          { type: 'knowledge', label: 'Load metric definitions', detail: 'metric_definitions.yaml → SQS formula', file: 'metric_definitions.yaml' },
          { type: 'knowledge', label: 'Load baselines', detail: 'Segment baselines for ai_on, enterprise', file: 'metric_definitions.yaml' },
          { type: 'reasoning', label: 'Classify severity', detail: '+0.3pp → P2 (Minor), within normal fluctuation' },
          { type: 'reasoning', label: 'Detect co-movement', detail: 'CQ↓ + AI Trigger↑ + SQS↑ → ai_adoption pattern' },
          { type: 'output', label: 'UnderstandResult', detail: 'metric=SQS, severity=P2, co_movement=ai_adoption' },
        ]
      },
      {
        name: 'HYPOTHESIZE', status: 'done', duration_s: 1.8, steps: [
          { type: 'knowledge', label: 'Load co-movement table', detail: '9-row diagnostic table → pattern match', file: 'metric_definitions.yaml' },
          { type: 'knowledge', label: 'Load corrections', detail: 'Check for past diagnostic mistakes', file: 'corrections.yaml' },
          { type: 'reasoning', label: 'Generate hypotheses', detail: 'Co-movement matches ai_feature archetype' },
          { type: 'output', label: 'HypothesisSet', detail: '1 matched (ai_feature), 7 not indicated' },
        ]
      },
      {
        name: 'DISPATCH', status: 'done', duration_s: 4.1, steps: [
          { type: 'sql', label: 'WoW comparison by segment', detail: 'Tenant tier decomposition query', duration_s: 5.8, rows: 6 },
          { type: 'reasoning', label: 'Decompose by tenant_tier', detail: 'Enterprise +2.1pp (68%), Premium +0.4pp (22%), Standard +0.1pp (10%)' },
          { type: 'reasoning', label: 'Mix-shift analysis', detail: 'mix_shift=8.2% (below 30% threshold), behavioral=91.8%' },
          { type: 'output', label: 'FindingSet', detail: 'Enterprise drives 68% of movement, no mix-shift' },
        ]
      },
      {
        name: 'SYNTHESIZE', status: 'done', duration_s: 2.4, steps: [
          { type: 'reasoning', label: 'Narrative generation', detail: 'Template-based synthesis with hedging for n=348' },
          { type: 'reasoning', label: 'Validate coherence', detail: 'Verdict consistent with evidence, no contradictions' },
          { type: 'output', label: 'SynthesisReport', detail: 'Verdict: within_variance, Confidence: Low (n=348)' },
        ]
      },
    ]
  },
  ranking_regression: {
    phases: [
      {
        name: 'UNDERSTAND', status: 'done', duration_s: 4.1, steps: [
          { type: 'sql', label: 'Data quality gate', detail: 'Logging completeness check', duration_s: 4.1, rows: 7 },
          { type: 'knowledge', label: 'Load metric definitions', detail: 'metric_definitions.yaml → CQ formula', file: 'metric_definitions.yaml' },
          { type: 'reasoning', label: 'Classify severity', detail: '-15.2% → P1 (Urgent), exceeds 5% threshold' },
          { type: 'reasoning', label: 'Detect co-movement', detail: 'CQ↓ + SQS↓ + AI stable → ranking_regression pattern' },
          { type: 'output', label: 'UnderstandResult', detail: 'metric=CQ, severity=P1, co_movement=ranking_regression' },
        ]
      },
      {
        name: 'HYPOTHESIZE', status: 'done', duration_s: 1.5, steps: [
          { type: 'knowledge', label: 'Load co-movement table', detail: '9-row diagnostic table → pattern match', file: 'metric_definitions.yaml' },
          { type: 'reasoning', label: 'Generate hypotheses', detail: 'Co-movement matches algorithm_model archetype' },
          { type: 'output', label: 'HypothesisSet', detail: '1 matched (algorithm_model), 7 not indicated' },
        ]
      },
      {
        name: 'DISPATCH', status: 'done', duration_s: 6.3, steps: [
          { type: 'sql', label: 'WoW comparison by segment', detail: 'Tenant tier decomposition query', duration_s: 6.3, rows: 6 },
          { type: 'reasoning', label: 'Decompose by tenant_tier', detail: 'Enterprise -4.5pp (85%), Premium -0.3pp (10%), Standard -0.1pp (5%)' },
          { type: 'reasoning', label: 'Mix-shift analysis', detail: 'mix_shift=5.1% (below 30%), behavioral=94.9%' },
          { type: 'output', label: 'FindingSet', detail: 'Enterprise drives 85%, isolated regression' },
        ]
      },
      {
        name: 'SYNTHESIZE', status: 'done', duration_s: 2.1, steps: [
          { type: 'reasoning', label: 'Narrative generation', detail: 'Template synthesis — P1 ranking regression, enterprise-isolated' },
          { type: 'reasoning', label: 'Validate coherence', detail: 'Decomposition completeness: 82.3% (WARN — below 90%)' },
          { type: 'output', label: 'SynthesisReport', detail: 'Verdict: ranking_regression, Confidence: Medium (82.3% explained)' },
        ]
      },
    ]
  },
}

// Keys for scenario switching (used by tabs/routing)
export const SCENARIO_KEYS = Object.keys(SCENARIOS)

// Default scenario shown on first load
export const DEFAULT_SCENARIO = 'ranking_regression'
