# Search Metric Analyzer: Web App Architecture Design

**Date:** 2026-03-14
**Status:** Approved (design direction locked, spec updated after 3-role IC9 review)
**Scope:** Architecture for web app presentation layer over existing diagnostic pipeline
**Mockups:** `.superpowers/brainstorm/44661-1773549752/agent-view-v5.html` (approved v5)
**Reviews:** DS Lead (APPROVE WITH FIXES), PM Lead (REJECT → addressed), Principal AI Eng (APPROVE WITH FIXES)

---

## 1. Product Context

### Audience
1. **Phase 1 (demo):** Employer — prove the concept, secure permission to use work time
2. **Phase 2 (daily use):** Team of 2 Senior DSs debugging metric movements for Eng Leads

### Demo Plan (Phase 1)

| Element | Detail |
|---------|--------|
| **Audience** | Direct manager + skip-level (Eng Lead) |
| **Format** | 5-minute screen share, live in browser |
| **Script** | (1) Open Dashboard — "here's our metric health at a glance." (2) Click the degraded metric card — "Click Quality dropped, let me investigate." (3) Agent view opens with pre-filled question — show the Overview tab rendering. (4) Switch to Execution Trace — "here's every step the agent took, with the SQL it ran." (5) Ask: "Can I dedicate 20% time to making this a daily tool for the team?" |
| **"Yes" looks like** | Permission to spend work time on this project, present to the 2 Senior DSs |
| **"No" looks like** | "Interesting, but not now" — still a portfolio piece for interviews |
| **Minimum viable demo** | v5 mockup HTML shown in a browser with narration. If that gets buy-in, skip React for Phase 1. |

### User Research (before Phase 2-3)

Before building the daily-use features, schedule a 15-minute session with each of the 2 Senior DSs:
1. "What's the most painful part of debugging a metric movement today?"
2. "If this existed, when in your workflow would you use it?"
3. "What would make you NOT use this?"

Document responses in this spec. Their answers may reshape Dashboard vs Agent priority.

### Core Principle
The web layer is a **presentation layer** over the existing diagnostic pipeline.
It does NOT influence backend architecture decisions.
The orchestrator API is the contract boundary — treat it like an internal microservice.

---

## 2. Two-View Architecture

### View 1: Agent (primary experience — build first)

The main experience. A unified view combining what was originally three separate views
(Query Playground, Trace Viewer, Overview) into one cohesive interface, inspired by
OpenAI's data agent pattern.

**Structure:**
```
┌─────────────────────────────────────────────────┐
│  Header:  Logo  |  [Dashboard] [Agent]  |  meta │
├─────────────────────────────────────────────────┤
│  Question: user's natural language query         │
│  Data through 2026-02-24 · Freshness: 4h · n=X  │
├─────────────────────────────────────────────────┤
│  Tabs:  [Overview]  [Execution Trace (14)]       │
├─────────────────────────────────────────────────┤
│                                                   │
│  Tab content area (scrollable)                    │
│                                                   │
├─────────────────────────────────────────────────┤
│  Footer: verdict badge | summary | date range    │
├─────────────────────────────────────────────────┤
│  Input: [Ask about a metric movement...]  [Go]   │
└─────────────────────────────────────────────────┘
```

**Overview tab (answer → evidence → detail):**
1. **Verdict strip** — 1-line TL;DR with raw `n` badge (e.g., "Within Variance — QSR +0.7pp WoW", `n=348 queries`)
2. **Data quality checks** — pass/warn/halt badges for validation checks (logging artifact, decomposition completeness, trust gate). Visually prominent (amber/red) when any check is HALT. This is the "before I trust any of this, did the data checks pass?" section.
3. **Co-movement indicator** — compact 4-metric direction arrows (Click Quality ↓, SQS stable, AI Trigger ↑, AI Success ↑) with the matched pattern name and `is_positive` badge. This is the "why should I believe you?" evidence.
4. **Narrative** — 2-3 sentence plain-language summary with qualitative hedging on sample size
5. **Hypothesis checklist** — ordered list of hypothesis categories evaluated, showing which were matched, ruled out, or not evaluated. Renders as a visual elimination trail.
6. **Results table** — WoW comparison with raw query counts, metric values, deltas (no fake significance)
7. **Diverging bar chart** — component-level WoW changes showing magnitude + direction. When `is_positive == true` (AI adoption), all bars render in neutral blue with "Expected co-movement" annotation instead of red/green.
8. **Trend chart** — daily line comparison (this week solid, last week dashed) with raw `n` in legend
9. **Segment decomposition table** — per-tenant-tier breakdown with contribution bars. When `mix_shift_contribution_pct >= 30%`, show amber annotation: "35% of this movement is traffic composition change (mix-shift)."
10. **Methodology** — collapsible, collapsed by default. Data source, date range, filters, formula
11. **SQL queries** — dark code blocks with syntax highlighting, permalink

**Execution Trace tab:**
1. **Filter tabs** — All Steps / SQL / Knowledge / Reasoning
2. **Phase accordion** — collapsible cards, each phase shows step count + timing
3. **Step types** — SQL QUERY (purple), KNOWLEDGE (teal), REASONING (coral), PHASE OUTPUT (green)
4. **Live progression** — amber pulsing dot for in-progress phase, gray for pending
5. **Inline SQL** — dark code blocks inside expanded steps with timing + row count

### View 2: Dashboard (status check — build second)

The "standup screen" — glance for 10 seconds, then go to Agent if something looks off.

**Structure:**
- 6 metric cards: Click Quality, Search Quality Success, AI Trigger, AI Success, Zero Result Rate, **Connector Health**
- Each metric card shows: current value, WoW delta, raw per-metric `n`
- Connector Health card shows: `{healthy, degraded, failing}` counts as a traffic light indicator. This is diagnostic shortcut #1 from `diagnostic-patterns.md` — check before running decomposition.
- One time-series chart (7d trend)
- Tenant tier filter tabs (All / Standard / Premium / Enterprise)
- **Clickable metric cards** → opens Agent with pre-filled question (e.g., "Why did Click Quality drop 15% for enterprise?")

### History (not a separate view)

Past investigations shown as a sidebar or dropdown on the Agent view.
A list of past questions with verdict badges and timestamps. Reference material, not a primary workflow.

---

## 3. Design System

| Element | Choice | Rationale |
|---------|--------|-----------|
| **Theme** | Light default (`#F4F4F5` page, `#FFFFFF` cards) | Matches workplace context (Databricks, Confluence, Slack). Matches OpenAI reference. |
| **Dark toggle** | v2 feature | Design light-first, adapt dark later |
| **Body font** | Fira Sans (300-700) | ui-ux-pro-max recommendation for analytics dashboards |
| **Code font** | Fira Code (400-600) | Monospace for SQL, metrics, timestamps |
| **Text primary** | `#18181B` | WCAG AAA on white background |
| **Text secondary** | `#52525B` | Sufficient contrast for body text |
| **Text muted** | `#A1A1AA` | Labels, timestamps, secondary metadata |
| **Accent** | `#2563EB` (blue) | Single accent color, used with intent |
| **Green** | `#16A34A` | Positive deltas (used sparingly — only when agent confirms significance) |
| **Red** | `#DC2626` | Negative deltas (same caveat) |
| **Amber** | `#D97706` | In-progress states, warnings |
| **Purple** | `#7C3AED` | SQL step type badge |
| **Teal** | `#0D9488` | Knowledge step type badge |
| **Coral** | `#E11D48` | Reasoning step type badge |
| **Code blocks** | Dark bg `#1E1E2E` inside light page | High contrast, matches OpenAI reference |
| **Step icons** | Letter-based SVG circles with colored borders (S, K, R, O) | No emoji icons. Matches OpenAI reference. |
| **Borders** | `#E4E4E7` | Subtle, non-distracting |
| **Card shadow** | `0 1px 2px rgba(0,0,0,0.04)` | Minimal elevation |
| **Border radius** | 10px cards, 8px inputs, 6px buttons, 4px badges | Consistent rounding scale |

### Statistical Honesty Rules (v1)

| Show | Don't show (defer to v2) |
|------|--------------------------|
| Raw query count `n` everywhere | Confidence intervals |
| **Per-metric `n`** (each metric's actual denominator, not total queries) | Significance badges |
| Raw deltas (e.g., +0.7pp) | p-values |
| Neutral coloring for ambiguous deltas | Green/red coloring without proven significance |
| Qualitative hedging in narrative when n is small | "Not statistically significant" (requires actual test) |

**Minimum-n display rule:** When a segment has `n < 30`, show the delta in muted styling
with an "insufficient data" label. Do not render contribution bars for segments below this threshold.

**Hedging rule:** Narrative includes hedging language when total `n < 500`:
"Sample size is modest (n=X); consider monitoring for another week before drawing firm conclusions."
This threshold is documented so narrative generation is reproducible across runs.

**Per-metric `n` rule:** `ai_success` has a different denominator than other metrics.
Its `n` = `ai_answers_triggered`, not `total_queries`. The API must return each metric's
actual denominator. Example: if `total_queries = 2450` and `ai_trigger_rate = 34.7%`,
then `ai_success.n = ~850`, not `2450`.

**Contribution % formula:** Uses the same computation as `core/decompose.py`:
`weighted_delta = delta * cur_weight` then `contribution_pct = weighted_delta / overall_delta * 100`.
In decompose.py, `cur_weight = len(cur_values) / max(len(current_rows), 1)` (current-period
traffic share). `presenter.py` computes `weighted_delta` (not exported by decompose.py) and
renames `cur_weight` → `traffic_share_pct` (×100) for the API response. The API includes raw
ingredients (`traffic_share_pct`, `delta_pp`, `weighted_delta`) so a DS can verify the math.

**AI inverse co-movement rendering rule:** When `diagnosis.is_positive == true` (e.g., AI
adoption pattern: Click Quality ↓ + AI Trigger ↑ + SQS stable), the DivergingBarChart
renders ALL bars in neutral blue (not red/green) with an "Expected co-movement" annotation.
The VerdictStrip uses a blue "Expected" badge, not a green "Improvement" badge — because
Click Quality dropping is not an improvement, it's an expected tradeoff. This prevents the
#1 misdiagnosis risk: an Eng Lead seeing red bars and concluding something is broken.

**Data freshness degradation rule:** The StatusBar renders freshness with color coding:
- `fresh` (<6h): normal text, no highlight
- `stale` (6-24h): amber text + tooltip: "Data may not reflect recent changes"
- `critical` (>24h): red text + tooltip: "Data is >24h old. Pipeline may have failed."
When enrichment freshness differs from raw data freshness (common in enterprise pipelines),
show the WORSE of the two as the primary indicator.

**v2 addition:** A `STATISTICAL TEST` step type in the trace, where the agent explicitly runs
bootstrap/permutation tests and shows methodology. Only then do CI and significance badges appear.

---

## 4. Technical Architecture

### Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Backend** | FastAPI (Python) | Same language as existing pipeline. Async-native for SSE streaming. Pydantic models align with existing TypedDict schemas. |
| **Frontend** | React + Tailwind CSS | Component-based (right for chat + trace + dashboard). Professional appearance. Deliberate learning investment. |
| **Charts** | Recharts or ApexCharts | React-native charting. Supports line, bar, diverging bar. |
| **State** | React Context or Zustand | Lightweight. No Redux overhead for 2 views. |
| **Streaming** | Server-Sent Events (SSE) | One-directional (server → client). Simpler than WebSocket. Phase 2 only. |

### Alternatives Considered

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **Static HTML mockup** | Already done (v5). Zero build effort. | Not interactive, can't show live data. | Use as fallback demo if React isn't ready in time. |
| **Streamlit** | Pure Python, fastest to demo, supports streaming. | Limited visual control, "hackathon look" even with custom CSS. Can't match v5 mockup quality. | Rejected — design ambitions exceed Streamlit's ceiling. |
| **FastAPI + HTMX** | Server-rendered, no JS build step, v5 CSS reusable as-is. | Less ecosystem support for complex client-side interactions (tab switching, accordion state). | Strong alternative. Revisit if React complexity blocks progress after 1 week. |
| **FastAPI + React (chosen)** | Full control over UI, rich ecosystem, professional result. | Steep learning curve (JSX, hooks, TypeScript, build toolchain). Two processes in dev. | Chosen — deliberate investment in learning React. Scope Phase 1 to minimum viable components. |

**Escape hatch:** If React blocks progress for >1 week, fall back to HTMX. The v5 mockup's HTML/CSS can be used directly as HTMX templates with minimal changes.

### Directory Structure

```
web/
├── backend/
│   ├── main.py              # FastAPI app, CORS, lifespan
│   ├── routes/
│   │   ├── diagnose.py       # POST /api/diagnose — run diagnosis
│   │   ├── stream.py         # GET /api/diagnose/stream — SSE trace
│   │   └── dashboard.py      # GET /api/metrics — dashboard data
│   ├── services/
│   │   ├── pipeline.py       # Calls decompose → diagnose → orchestrate
│   │   └── presenter.py      # Transforms pipeline output → API response shape
│   ├── fixtures/
│   │   └── mock_investigations.py  # Phase 1: hardcoded mock results
│   └── schemas/
│       └── api.py            # Pydantic request/response models
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── AgentView/
│   │   │   │   ├── QuestionInput.tsx
│   │   │   │   ├── OverviewTab.tsx
│   │   │   │   ├── TraceTab.tsx
│   │   │   │   ├── VerdictStrip.tsx
│   │   │   │   ├── ResultsTable.tsx
│   │   │   │   ├── DivergingBarChart.tsx
│   │   │   │   ├── TrendChart.tsx
│   │   │   │   ├── SegmentTable.tsx
│   │   │   │   ├── SqlBlock.tsx
│   │   │   │   ├── PhaseAccordion.tsx
│   │   │   │   └── StepRow.tsx
│   │   │   ├── Dashboard/
│   │   │   │   ├── MetricCard.tsx
│   │   │   │   └── TenantFilter.tsx
│   │   │   └── shared/
│   │   │       ├── Header.tsx
│   │   │       ├── Footer.tsx
│   │   │       └── StatusBar.tsx
│   │   ├── hooks/
│   │   │   ├── useDiagnosis.ts   # POST + SSE consumption
│   │   │   └── useMetrics.ts     # Dashboard data fetching
│   │   └── styles/
│   │       └── tokens.css        # CSS variables from design system
│   └── package.json
└── README.md
```

### API Contract

**Define contract FIRST, freeze it, build independently on both sides.**
**Design principle:** Response keys are domain concepts, not UI component names. The frontend
decides how to render `dimensional_breakdown` — as a table, chart, or both.

#### `POST /api/diagnose`

**Phase 1:** Returns hardcoded mock results (ignores question, returns pre-built response).
**Phase 2+:** Structured form input (metric dropdown, date picker, filter selects). NLP
free-text parsing deferred to v2.

Request:
```json
{
  "metric": "click_quality_value",
  "date_range": {"start": "2026-02-10", "end": "2026-02-24"},
  "filters": {"tenant_tier": "enterprise", "search_experience": "fullPageSearch"},
  "question": "optional free-text for display only in Phase 1"
}
```

Response (domain-concept structured):
```json
{
  "investigation_id": "uuid-v4-generated-per-request",
  "diagnosis": {
    "verdict": "ranking_regression",
    "verdict_label": "Ranking Regression",
    "is_positive": false,
    "confidence": {
      "level": "Medium",
      "explained_pct": 82.3,
      "evidence_count": 2,
      "reason": "Explained percentage below 90% threshold for High"
    },
    "co_movement": {
      "pattern_matched": "ranking_regression",
      "is_positive": false,
      "metric_directions": {
        "click_quality": {"direction": "down", "delta_pct": -15.2},
        "search_quality_success": {"direction": "down", "delta_pct": -4.5},
        "ai_trigger": {"direction": "stable", "delta_pct": 0.3},
        "ai_success": {"direction": "stable", "delta_pct": -0.1}
      },
      "pattern_description": "CQ and SQS both down, AI stable — likely ranking regression"
    },
    "hypotheses_evaluated": [
      {"category": "instrumentation", "status": "ruled_out", "reason": "No step-change in logging volume"},
      {"category": "connector", "status": "not_evaluated", "reason": "Connector health data not available"},
      {"category": "query_understanding", "status": "ruled_out", "reason": "No query reformulation anomaly"},
      {"category": "algorithm_model", "status": "matched", "reason": "Co-movement matches ranking regression pattern"},
      {"category": "experiment", "status": "not_evaluated", "reason": "No experiment ramp data available"},
      {"category": "ai_feature", "status": "ruled_out", "reason": "AI metrics stable"},
      {"category": "seasonal", "status": "ruled_out", "reason": "No calendar effect detected"},
      {"category": "user_behavior", "status": "ruled_out", "reason": "Null hypothesis — checked last"}
    ],
    "hypothesis": {
      "archetype": "ranking_regression",
      "dimension": "tenant_tier",
      "segment": "enterprise",
      "contribution_pct": 85.0,
      "confirms_if": ["ranking model version changed"],
      "rejects_if": ["movement uniform across segments"]
    },
    "aggregate": { "metric": "click_quality_value", "severity": "P1", "delta_pct": -15.2 },
    "dimensional_breakdown": {
      "dimension": "tenant_tier",
      "segments": [
        {
          "segment": "enterprise", "current_count": 89, "baseline_count": 150,
          "current_value": 73.8, "baseline_value": 71.7, "delta_pp": 2.1,
          "traffic_share_pct": 25.6, "weighted_delta": 0.537, "contribution_pct": 74.7
        },
        {
          "segment": "premium", "current_count": 124, "baseline_count": 118,
          "current_value": 71.0, "baseline_value": 70.6, "delta_pp": 0.4,
          "traffic_share_pct": 35.6, "weighted_delta": 0.142, "contribution_pct": 19.8
        }
      ]
    },
    "mix_shift": {
      "detected": false,
      "mix_shift_contribution_pct": 12.3,
      "behavioral_contribution_pct": 87.7,
      "flag": null
    },
    "validation_checks": [...]
  },
  "narrative": {
    "text": "Click Quality dropped -15.2% for enterprise tenants...",
    "source": "template",
    "hedging": "Sample size is modest (n=348)"
  },
  "data_context": {
    "data_source": "search_query_relevance_metrics_enriched",
    "data_freshness": {
      "raw_data": "2026-02-24T18:00:00Z",
      "enrichment": "2026-02-24T06:00:00Z",
      "status": "fresh",
      "status_note": "fresh (<6h), stale (6-24h), critical (>24h)"
    },
    "queries_analyzed": 348,
    "metric_formula": "sum(long_clicks * log2_discount(rank)) / impressions",
    "metric_formula_note": "Formula is resolved per-metric from metric_definitions.yaml",
    "filters_applied": ["searchExperience = 'fullPageSearch'", "is_hello = 0"]
  },
  "sql_queries": [
    {"description": "Data quality gate", "sql": "SELECT ...", "duration_s": 11.9, "rows": 3}
  ],
  "orchestration": {
    "orchestrated": true,
    "agents_run": ["...AgentVerdict dicts..."],
    "fused_verdict": "confirmed",
    "fused_reason": "Confirmed by: ranking_agent. Diagnosis hypothesis verified.",
    "updated_decision_status": "diagnosed",
    "run_log": ["...per-agent timing entries..."]
  }
}
```

**Key changes from v1 draft:**
- `confidence` is an object with `level`, `explained_pct`, `evidence_count`, `reason` — sourced from `core/diagnose.py` confidence scoring logic (DS Lead)
- `dimensional_breakdown` is a nested object with `dimension` + `segments` list, matching `decompose.py` output shape (Spec Review blocker)
- `mix_shift` exposes the full decomposition: `mix_shift_contribution_pct`, `behavioral_contribution_pct`, `flag` — matching `decompose.py::compute_mix_shift()` output (Spec Review)
- `metric_formula` is resolved per-metric from `metric_definitions.yaml` — example shows Click Quality's actual formula, not SQS (DS Lead + Spec Review)
- `orchestration` includes `fused_reason` and `updated_decision_status` matching `OrchestrationResult` in `core/schema.py` (Spec Review)
- `narrative.source` discloses `"template"` or `"llm_generated"` (DS Lead)
- Response structured around domain concepts, not UI layout (Principal Eng)

#### `GET /api/diagnose/{id}/stream` (Phase 2 only — skip in Phase 1)

**Streaming architecture:**
- `POST /api/diagnose` starts a background task via `asyncio.create_task` and returns
  `{investigation_id}` immediately
- Backend stores streaming events in an **in-memory buffer** keyed by `investigation_id`
  (acceptable for 2-3 concurrent users)
- Each SSE event includes an `id` field for `Last-Event-ID` reconnection support
- Buffer has 30-minute TTL; completed investigations are garbage collected
- `event: error` defined for pipeline failures

```
id: 1
event: phase_start
data: {"phase": "Phase 1: Data Quality", "step_count": 3}

id: 2
event: step
data: {"type": "SQL_QUERY", "description": "Data quality gate", "sql": "SELECT ...", "duration_s": 11.9, "rows": 3}

id: 5
event: phase_complete
data: {"phase": "Phase 1: Data Quality", "duration_s": 11.9}

id: 10
event: error
data: {"phase": "Phase 3: Decomposition", "error": "TimeoutError", "message": "Agent exceeded 300s timeout"}

id: 11
event: complete
data: {"investigation_id": "uuid-v4", "partial": false}
```

**Error handling:** If the pipeline crashes mid-stream, emit `event: error` with the phase
and error message. The frontend shows partial results (completed phases) with a banner:
"Investigation incomplete — Phase 3 failed. Showing partial results."

**Cancellation:** If the user submits a new question while one is running, the frontend
discards the old SSE stream (client-side). The old backend task runs to completion but
its result is never consumed.

#### `GET /api/metrics`

Dashboard endpoint (per-metric `n`):
```json
{
  "date_range": {"start": "2026-03-08", "end": "2026-03-14"},
  "metrics": {
    "click_quality": {"value": 72.3, "delta_pp": 2.1, "n": 2450},
    "search_quality_success": {"value": 68.1, "delta_pp": -4.5, "n": 2450},
    "ai_trigger": {"value": 34.7, "delta_pp": 8.2, "n": 2450},
    "ai_success": {"value": 81.4, "delta_pp": 0.0, "n": 850},
    "zero_result_rate": {"value": 3.2, "delta_pp": 0.0, "n": 2450}
  },
  "trend": [{"date": "2026-03-08", "click_quality": 71.1, ...}, ...],
  "data_freshness": "2026-03-14T18:00:00Z"
}
```

Note: `ai_success.n = 850` (not 2450) because its denominator is `ai_answers_triggered`,
not `total_queries`. Each metric carries its own actual denominator.

---

## 5. How It Connects to the Existing Pipeline

### Data Flow Gap (acknowledged)

Today the pipeline is CLI-driven: a human runs `python core/decompose.py --input data.csv`
and feeds the output to `diagnose.py`. The web app needs to automate what the human does
manually. This requires work that does NOT exist yet:

1. **Data fetching** — querying the actual data warehouse (Databricks/Snowflake). Not in scope for Phase 1.
2. **Question parsing** — extracting metric, date range, and filters from user input. Phase 1 uses structured form fields (dropdowns + date picker), not free-text NLP.
3. **Pipeline orchestration** — calling decompose → diagnose → orchestrate in sequence. This is the `web/backend/services/pipeline.py` module.

**Phase 1 approach:** The `POST /api/diagnose` endpoint returns **hardcoded mock results** —
2-3 pre-built investigation responses that match the mockup data. The input form is
non-functional (display only). This is sufficient for the employer demo.

**Phase 2+ approach:** Wire up the real pipeline. Data fetching is a separate workstream
that should be scoped independently.

### Pipeline Flow (Phase 2+)

```
Structured form input (metric, date_range, filters)
     │
     ▼
FastAPI backend (web/backend/)
     │
     ├── services/pipeline.py
     │   ├── Fetches data (v2+ — data warehouse connector)
     │   ├── Calls core/decompose.py::run_decomposition()
     │   ├── Calls core/diagnose.py::run_diagnosis()
     │   └── Calls harness/orchestrator.py::orchestrate()
     │
     ├── services/presenter.py
     │   ├── Transforms pipeline output → API response shape
     │   ├── Generates narrative from structured data (template-based)
     │   ├── Computes display labels from archetype codes
     │   └── Reads trace spans for SQL query surfacing
     │
     └── Streams trace events via SSE (Phase 2)
```

### Presenter Transformation Mapping (presenter.py)

`presenter.py` transforms raw pipeline output into the API response shape. Key mappings:

**`dimensional_breakdown`** — decompose.py → API:
```
decompose.py output:                          API response:
─────────────────────                         ────────────
dimensional_breakdown:                        dimensional_breakdown:
  tenant_tier:                                  dimension: "tenant_tier"
    segments:                                   segments: [
      - segment_value: "enterprise"               { segment: "enterprise",     # renamed from segment_value
        current_count: 89                           current_count: 89,
        baseline_count: 150                         baseline_count: 150,
        current_mean: 73.8                          current_value: 73.8,       # renamed from current_mean
        baseline_mean: 71.7                         baseline_value: 71.7,      # renamed from baseline_mean
        delta: 2.1                                  delta_pp: 2.1,             # same value, clarified as pp
        cur_weight: 0.256                           traffic_share_pct: 25.6,   # cur_weight * 100
                                                    weighted_delta: 0.537,     # COMPUTED: delta * cur_weight
                                                    contribution_pct: 74.7     # COMPUTED: weighted_delta / overall_delta * 100
                                                  }
    dominant_segment: "enterprise"              ]
```

**`confidence`** — diagnose.py → API:
```
diagnose.py::compute_confidence() produces:   API response:
  level: "Medium"                               level: "Medium"                   # pass-through
  explained_pct: 82.3                           explained_pct: 82.3               # pass-through
  reasoning: "Explained pct below 90%..."       reason: "Explained pct below..."  # RENAMED (reasoning → reason)
  (validation_checks length)                    evidence_count: 2                  # COMPUTED from len(validation_checks)

NOTE: reason is a PASS-THROUGH rename of diagnose.py's `reasoning` field,
NOT a recomputation. This preserves the separation of concerns —
diagnostic judgments stay in diagnose.py.
```

**`co_movement`** — diagnose.py → API:
```
diagnose.py already computes co_movement_result via anomaly.py.
presenter.py passes through the matched pattern, metric directions,
and is_positive flag. The pattern_description is a pass-through of
the archetype's description_template from ARCHETYPE_MAP.
```

**`hypotheses_evaluated`** — diagnose.py → API:
```
diagnose.py's ARCHETYPE_MAP produces priority_hypotheses per archetype.
presenter.py surfaces which categories were matched, ruled_out, or
not_evaluated based on the co-movement scoring and archetype selection.
```

**`mix_shift`** — decompose.py → API:
```
decompose.py::compute_mix_shift() returns:    API response:
  mix_shift_contribution_pct: 12.3              mix_shift_contribution_pct: 12.3  # pass-through
  behavioral_contribution_pct: 87.7             behavioral_contribution_pct: 87.7 # pass-through
  flag: null  (when mix_pct < 30%)              flag: null                         # pass-through (NOT renamed)
  flag: "mix_shift_dominant" (>= 30%)           detected: true/false               # COMPUTED: flag == "mix_shift_dominant"

IMPORTANT: decompose.py returns flag=null (not "behavioral_dominant")
when mix_shift_pct < 30%. presenter.py must handle null correctly.
The frontend treats null and "behavioral_dominant" the same way
for display purposes, but the API preserves the null to avoid
asserting something the code did not determine.
```

**`metric_formula`** — looked up from `data/knowledge/metric_definitions.yaml` based on
the requested metric name. Each metric has its own formula; this is NOT hardcoded.

### Separation of Concerns (redefined)

| Allowed in web layer | NOT allowed in web layer |
|---------------------|--------------------------|
| **Presentation transformation** — reshaping dicts into table rows, computing display labels, generating narrative text from structured data | **Diagnosis decisions** — no thresholds, no archetype recognition, no confidence scoring |
| **`presenter.py`** — dedicated module for transforming pipeline output into API response | **Reimplementing logic** that exists in `core/` or `harness/` |

### Development Workflow

```bash
# Dev (two terminals, or use Vite proxy)
make dev-backend    # uvicorn web.backend.main:app --reload --port 8000
make dev-frontend   # cd web/frontend && npm run dev (Vite, port 5173)

# Vite proxy config forwards /api/* → localhost:8000 (no CORS issues in dev)

# Production (single process)
npm run build       # outputs to web/backend/static/
uvicorn web.backend.main:app  # FastAPI serves React as static files

# Single Dockerfile (optional)
docker build -t sma-web .
docker run -p 8000:8000 sma-web
```

### Investigation History (v1 persistence)

Store completed investigations as JSON files in `web/data/investigations/`.
Simple, inspectable, survives restarts, no database dependency.
`investigation_id` is a UUID v4 generated per POST request. Same question submitted
twice generates two separate investigations.

---

## 6. Sequencing Decision: Phase 2.2 vs Web App

### Recommendation: Sequential — web app first, then Phase 2.2

Parallel tracks are technically sound (API contract as boundary) but unrealistic for a
solo developer. Context-switching between React/TypeScript (frontend), FastAPI async
(backend), and orchestrator internals (ML pipeline) kills velocity on everything.

| Order | Phase | Deliverable | Estimated Effort |
|-------|-------|-------------|-----------------|
| 1 | **Web App Phase 1** | Agent view, Overview tab, hardcoded mock data | 1-2 sessions |
| 2 | **Web App Phase 2** | Execution Trace tab, SSE streaming | 1-2 sessions |
| 3 | **Web App Phase 3** | Dashboard view, clickable metric cards | 1 session |
| 4 | **Phase 2.2** | Real agent adapters, data pipeline wiring | 2-3 sessions |

**Why sequential:** You stay in one mental model at a time. Phases 1-3 are frontend-heavy
(React learning). Phase 2.2 is pure Python in your comfort zone. Finishing the web app
first means you have a working UI to test against when Phase 2.2 lands real data.

**Merge point:** When Phase 2.2 lands, swap mock data fixtures for real pipeline calls.
The web app's components don't change — only the data source behind `POST /api/diagnose`.

### Phase 1 Scope (employer demo)

Phase 1 is intentionally minimal:
- **Build:** FastAPI serving React app with 2-3 hardcoded investigation responses
- **Input:** Structured form (metric dropdown, date picker, filter selects) — NOT free-text NLP
- **Output:** Overview tab rendering verdict, narrative, table, charts, SQL, segment decomposition
- **Mock data:** 2-3 pre-built JSON fixtures matching the v5 mockup content
- **Escape hatch:** If React blocks progress for >1 week, demo with the v5 static HTML mockup instead

---

## 7. Success Criteria

### Employer Demo (Phase 1)

| Criterion | Measurable Test |
|-----------|----------------|
| Investigation report renders | All 8 sections visible in Overview tab within 2s of page load |
| Matches approved mockup | 3 colleagues independently describe it as "professional-looking" |
| Data context visible | Data freshness timestamp, query count, and metric formula shown |
| WCAG AA contrast | All text passes 4.5:1 contrast ratio check |
| No layout shifts | Zero visible CLS on page load |

### Daily Use (Phase 2-3)

| Criterion | Measurable Test |
|-----------|----------------|
| Live trace streaming | Phases appear incrementally within 1s of each completion |
| Phase accordion is interactive | Click expand/collapse works; filter tabs filter steps |
| Dashboard shows metrics | 5 metric cards with per-metric `n` and WoW delta |
| Clickable investigation launch | Clicking a degraded metric opens Agent with pre-filled structured form |
| Investigation history | Past 10 investigations listed, clickable to re-view |

### Technical Quality

| Criterion | Measurable Test |
|-----------|----------------|
| API contract frozen | OpenAPI spec generated and committed before frontend work begins |
| Presentation-only web layer | Zero diagnosis decisions in `web/` — only `presenter.py` transformations |
| Component isolation | Each React component renders independently with mock props |
| SSE reconnection | Dropping and reconnecting the EventSource resumes from `Last-Event-ID` |
| Error states | Pipeline crash shows partial results + error banner (not blank screen) |

### UI States (must be designed)

| State | What the user sees |
|-------|-------------------|
| **Loading** | Skeleton screens for each Overview section; pulsing phase dots in Trace |
| **Error** | Partial results rendered + red banner: "Phase X failed: [reason]. Showing partial results." |
| **Empty** | First visit: "Ask a question to start an investigation" with example prompts |
| **Timeout** | After 60s: "Investigation is taking longer than expected. Partial results shown below." |
