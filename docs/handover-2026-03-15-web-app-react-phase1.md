# Handover: React + FastAPI Web App — Phase 1 (Review-Refined)

**Project:** Search Metric Analyzer
**Path:** `/Users/surahli/Documents/projects/Search_Metric_Analyzer/`
**Branch:** Create `feature/web-app-react` from `main`
**Date:** 2026-03-15

## Goal

Build Phase 1 of the React + FastAPI web app. The visual target already exists as a working HTML demo. This session was reviewed by 3 personas (PM Lead, Principal AI Engineer, DS Lead) — their findings are incorporated below.

## Execution Mode

**Use Agent Teams / subagent-driven-development** to parallelize independent tasks (backend scaffold + frontend scaffold can run in parallel).

**Invoke these superpowers skills during implementation:**
- `superpowers:test-driven-development` — write tests before implementation code
- `superpowers:requesting-code-review` — review after each major milestone (backend done, frontend done, integration)
- `superpowers:verification-before-completion` — run verification commands before claiming done

## Stack Decisions (Review-Refined)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend framework | React + Vite | User decision — learning investment |
| Language | **JavaScript (.jsx)** NOT TypeScript | Principal reviewer: TS doubles debugging surface for a learner. Migrate to TS later. |
| Styling | Tailwind CSS | Matches spec design system |
| Charts — trend line | Recharts | Library adds value for SVG path interpolation |
| Charts — diverging bar | **CSS/HTML divs** NOT Recharts | Principal reviewer: Recharts can't do center-zero horizontal bars natively. Demo uses positioned divs — keep it. |
| Charts — segment bars | CSS/HTML divs | Simple progress bar styling |
| Backend | FastAPI (Python) | Minimal — serves mock fixtures |
| Schemas | **Plain Python dicts** NOT full Pydantic | Principal reviewer: premature for mock data. Build Pydantic when wiring real pipeline. |
| Deployment | **Run locally** for demo | Principal reviewer: Render free tier has 30-60s cold starts. `uvicorn` + Vite dev server on your machine. |

## Mock Data Fixes (From DS Lead Review — BLOCKERS)

### Fix 1: "Within Variance" mock values
**Problem:** SQS +0.7pp on mean 0.378 = 1.85% relative change, exceeding P1 threshold (1.5%). Pipeline would classify this as P1, not "Within Variance."
**Fix:** Use +0.3pp instead (~0.8% relative, safely in P2/normal range). Or use Click Quality with a smaller delta.

### Fix 2: "hypotheses_evaluated" is fabricated
**Problem:** The pipeline matches ONE co-movement pattern. It does NOT evaluate all 8 hypothesis categories with reasons. Showing "ruled_out" with reasons misrepresents capability.
**Fix:** Show only two statuses:
- `matched` — the archetype category from the co-movement match
- `not_evaluated` — everything else (honest about what the pipeline doesn't do)
- Do NOT show `ruled_out` — nothing in the pipeline performs that evaluation

### Fix 3: Ranking Regression count imbalance
**Problem:** Enterprise segment has current_count=89 vs baseline_count=150 (41% volume drop) — suspicious signal that would undermine the diagnosis.
**Fix:** Use more plausible counts (e.g., 130 vs 150) or flag the volume drop in data quality checks.

## What to Build

### Backend (FastAPI) — `web/backend/`
```
web/backend/
├── main.py                    # FastAPI app, CORS, health check
├── routes/
│   └── diagnose.py            # POST /api/diagnose → return mock fixture
└── fixtures/
    └── mock_investigations.py # 2 hardcoded response dicts
```

- `POST /api/diagnose` — ignores request body, returns fixture based on `metric` field (click_quality → Ranking Regression, search_quality_success → Within Variance)
- Response shape matches the API contract in the architecture spec (Section 3)
- Install: `pip install fastapi uvicorn`

### Frontend (React + Vite + Tailwind) — `web/frontend/`
```
web/frontend/
├── src/
│   ├── App.jsx
│   ├── styles/
│   │   └── tokens.css              # CSS variables from demo HTML
│   ├── components/
│   │   ├── Header.jsx
│   │   ├── QuestionInput.jsx
│   │   ├── VerdictStrip.jsx        # 1-line TL;DR + n badge
│   │   ├── DataQualityChecks.jsx   # pass/warn badges
│   │   ├── CoMovementIndicator.jsx # 4-metric arrows + pattern
│   │   ├── NarrativeBlock.jsx      # 2-3 sentence summary
│   │   ├── HypothesisChecklist.jsx # matched/not_evaluated only
│   │   ├── ResultsTable.jsx        # WoW comparison
│   │   ├── DivergingBarChart.jsx   # CSS divs, NOT Recharts
│   │   ├── TrendChart.jsx          # Recharts line chart
│   │   ├── SegmentTable.jsx        # Per-tier breakdown
│   │   ├── MethodologyBlock.jsx    # Collapsible
│   │   ├── SqlBlock.jsx            # Dark code block
│   │   └── Footer.jsx
│   └── data/
│       └── scenarios.js            # 2 fixture objects for client-side switching
├── index.html
├── package.json
└── vite.config.js                  # proxy /api → localhost:8000
```

- Scaffold: `npm create vite@latest frontend -- --template react`
- Install: `npm install tailwindcss @tailwindcss/vite recharts`
- CSS variables: copy from demo HTML lines 9-39
- Vite proxy: `/api` → `localhost:8000`

## Component Build Order (answer → evidence → detail)

Build in this order — each component is independently testable:

1. **Header** — static, logo + nav tabs
2. **VerdictStrip** — verdict text + n badge + colored left bar
3. **DataQualityChecks** — row of pass/warn badges
4. **CoMovementIndicator** — 4-metric arrows + pattern name
5. **NarrativeBlock** — text with hedging
6. **HypothesisChecklist** — ordered list with matched/not_evaluated icons
7. **ResultsTable** — WoW comparison table
8. **DivergingBarChart** — CSS positioned divs (NOT Recharts)
9. **TrendChart** — Recharts `<LineChart>` with solid/dashed series
10. **SegmentTable** — per-tier breakdown with progress bars
11. **MethodologyBlock** — collapsible details
12. **SqlBlock** — dark code block with syntax highlighting
13. **Footer** — verdict badge + summary
14. **QuestionInput** — input bar + scenario switching
15. **App.jsx** — compose all components, wire scenario state

## Key Files to Read First

1. `docs/plans/2026-03-14-web-app-architecture-design.md` — frozen API contract, design system, component specs
2. `docs/mockups/search-metric-analyzer-demo.html` — visual target (lines 9-39 for CSS vars, lines 870-1200 for scenario data)
3. `core/schema.py` — existing TypedDict schemas
4. `data/knowledge/metric_definitions.yaml` — baselines for validating mock data plausibility

## Critical Rendering Rules

- **Per-metric `n` everywhere** (ai_success has different denominator)
- **`is_positive == true`** → neutral blue bars + "Expected" badge (NOT green/red)
- **`n < 30` segments** → muted text + "insufficient data" (no contribution bars)
- **`n < 500` total** → narrative includes hedging language
- **Data freshness** → fresh (<6h normal), stale (6-24h amber), critical (>24h red)
- **No CIs, no p-values, no significance badges** — raw counts and deltas only

## Parallel Session Note

A parallel session is executing Wave 3b (SearchMetricOrchestrator + LLM factory) on `harness/`. No conflicts — Wave 3b touches `harness/`, this work touches `web/`.

## What "Done" Looks Like

- `uvicorn web.backend.main:app` serves mock fixtures on localhost:8000
- `npm run dev` in `web/frontend/` renders the Agent View matching the demo HTML
- Selecting a scenario switches all 11 sections with correct data
- All statistical honesty rules are followed (no fake significance)
- Mock data values are internally consistent with metric_definitions.yaml baselines
- Tests exist for backend routes and key frontend rendering logic
