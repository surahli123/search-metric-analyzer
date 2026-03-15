# Search Metric Analyzer: Web App Scope Notes

**Date:** 2026-03-14
**Status:** Scoping — parallel with Phase 2.2 backend refactoring

## Metric Focus

### v1 Scope: Online User Engagement Metrics
- Click Quality (click-through behavior, click positions)
- Search Quality Success = max(click_component, ai_trigger * ai_success)
- AI trigger rate, AI success rate
- Zero-result rate
- Latency (p50, p95, p99)
- Session depth, dwell time, bounce rate
- The inverse co-movement pattern: more AI answers = fewer clicks (expected, not alarming)

### Future Scope: Offline Metrics (deferred)
- NDCG, MRR, precision@k on labeled datasets
- Requires ground-truth labels + evaluation pipelines
- Different workflow (batch evaluation vs real-time monitoring)

## Web App Vision: Three Views

### 1. Dashboard
- Metric cards with trend indicators (up/down/stable)
- Time-series charts for key metrics (CTR, Search Quality Success, AI rates)
- Tenant-level drill-down (standard/premium/enterprise)
- Alert indicators for anomalous movements
- Think: "search team standup screen"

### 2. Query Playground (ChatGPT-like)
- User inputs a question: "Why did Click Quality drop 15% for enterprise tenants last week?"
- System runs the diagnostic pipeline (existing orchestrator)
- Streams results in real-time
- Shows agent reasoning + evidence
- Think: "search team diagnostic console"

### 3. Trace Viewer
- Expandable tree view of diagnostic trace
- Each node: which agent ran, what it found, confidence, raw evidence
- Links back to underlying data (connector metrics, tenant breakdown)
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
