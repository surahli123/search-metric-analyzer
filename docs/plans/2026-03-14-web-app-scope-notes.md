# Search Metric Analyzer: Web App Scope Notes

**Date:** 2026-03-14
**Status:** Scoping — parallel with Phase 2.2 backend refactoring

## Metric Focus

### v1 Scope: Online User Engagement Metrics (5 dashboard metrics)
- Click Quality (click-through behavior, click positions)
- Search Quality Success = max(click_component, ai_trigger * ai_success)
- AI trigger rate, AI success rate
- Zero-result rate
- The inverse co-movement pattern: more AI answers = fewer clicks (expected, not alarming)

### v2 Scope: Additional Online Metrics (deferred from v1 dashboard)
- Latency (p50, p95, p99) — requires separate data source
- Session depth, dwell time, bounce rate — requires session-level aggregation

### Future Scope: Offline Metrics (deferred)
- NDCG, MRR, precision@k on labeled datasets
- Requires ground-truth labels + evaluation pipelines
- Different workflow (batch evaluation vs real-time monitoring)

## Web App Vision: Two Views (consolidated from original 3)

**Design evolution (2026-03-14):** Query Playground + Trace Viewer merged into a single
"Agent" view with two tabs (Overview + Execution Trace), inspired by OpenAI's data agent
pattern. See architecture design doc for details.

### 1. Dashboard
- Metric cards with trend indicators (up/down/stable)
- Time-series charts for key metrics (CTR, Search Quality Success, AI rates)
- Tenant-level drill-down (standard/premium/enterprise)
- Alert indicators for anomalous movements
- **Clickable metric cards → opens Agent with pre-filled investigation**
- Think: "search team standup screen"

### 2. Agent (merged Query Playground + Trace Viewer)
- **Overview tab:** Answer-first flow — verdict, narrative, results table, charts, segment decomposition, methodology (collapsed), SQL queries
- **Execution Trace tab:** Phase-based accordion with step-type badges (SQL, Knowledge, Reasoning), live streaming progression, filter tabs
- Think: "OpenAI data agent for search diagnostics"
- Think: "Chrome DevTools Network tab, but for search diagnostics"

## Technical Stack (IC9 Recommendation)

### Backend: FastAPI (Python)
- Same language as existing toolkit
- Async-native for real-time streaming
- Pydantic models align with existing schemas (AgentVerdict, OrchestrationResult)
- Easy path to Databricks/Snowflake connectors later

### Frontend: React + Tailwind CSS
- Component-based = right for chat interface + trace tree + dashboard
- Professional appearance (not Streamlit hackathon look)
- Claude Code writes React fluently via document-skills:frontend-design

### API Contract Boundary
- Define API contract FIRST (endpoints, request/response shapes)
- Freeze contract, build frontend against frozen spec
- Backend refactoring (Phase 2.2) and web layer develop independently
- If backend changes, update contract — don't let frontend drive backend decisions

## Audience

1. **Phase 1:** Demo for employer (prove the concept, get buy-in)
2. **Phase 2:** Team of 2 Senior DSs (daily diagnostic tool)

## Available Skills for Web Development

| Skill | Purpose |
|-------|---------|
| `backend-patterns` | FastAPI API design, middleware, error handling |
| `deployment-patterns` | Docker, CI/CD, health checks |
| `e2e-testing` | Playwright browser testing |
| `verification-loop` | Pre-PR quality gate (6 phases) |
| `document-skills:frontend-design` | React component generation |
| `document-skills:webapp-testing` | Playwright integration |
| `ui-ux-pro-max` | Design system generation |
| `security-review` | OWASP checklist for API endpoints |
| `security-reviewer` agent | Vulnerability scanning |

## gstack Evaluation

**Status:** Revisit when browser QA is needed
- `/browse` + `/qa` become valuable once the web app exists and needs testing
- `/plan-ceo-review` + `/review` are useful now but overlap with existing CLAUDE.md personas
- Requires Bun runtime (additional dependency)
- **Decision:** Install when the web app has a running UI to test against

## Key Constraint

The web layer is a PRESENTATION layer over the existing diagnostic pipeline.
It should NOT influence backend architecture decisions.
The orchestrator API is the contract boundary — treat it like an internal microservice.
