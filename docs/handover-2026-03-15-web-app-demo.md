# Handover: Web App Demo — Interactive Mockup + Vercel Deployment

**Project:** Search Metric Analyzer
**Path:** `/Users/surahli/Documents/projects/Search_Metric_Analyzer/`
**Branch:** `feature/web-app-demo` (PR #11 open against main)
**Date:** 2026-03-15

## Last Session Summary

Built a demo-ready web app by enhancing the v5 HTML mockup rather than building React from scratch. A 3-role IC9 review (DS Lead, PM Lead, Principal AI Engineer) unanimously recommended the mockup-first approach — React was deferred to a separate session. Added scenario switching (Within Variance vs Ranking Regression), hypothesis evaluation checklist, data quality badges, and 10 UI fixes from a design critique. Deployed to Vercel. Also resolved branch cleanup (merged PRs #8, #9, #10 to main) and evaluated Agent SDK vs Client SDK for the backend.

## Current State

**Working:**
- Demo live at https://search-metric-analyzer-demo.vercel.app
- Presentation at https://search-metric-analyzer-demo.vercel.app/presentation
- 2-scenario switching with fade animation, pill toggle, full data sync
- Hypothesis checklist with connecting line, matched/ruled-out/not-evaluated states
- Bold verdict strip with pulse animation and left accent border
- Chart colors correct: all blue for AI adoption (positive), red for regression
- 762 tests passing, 0 failures

**Not yet done:**
- CHANGELOG.md entry keeps getting reverted by an external process — needs manual add
- Demo rehearsal (5-minute narration script is in the plan file)
- PR #11 not yet merged

## Key Decisions Made This Session

1. **Mockup-first, React later.** 3 reviewers independently concluded React is high-risk for same-day delivery. The mockup IS the demo asset.
2. **Agent SDK is NOT appropriate** for the structured 4-stage pipeline. Use the **Anthropic Client SDK** (`pip install anthropic`) for Wave 3b LLM calls.
3. **Backend deployment: Render** (not Vercel). Render's free tier sleeps on idle (good for 2-user tool), has first-class FastAPI support. Vercel is for frontend only.
4. **Critical chart fix:** All diverging bars render neutral blue when `is_positive == true` (AI adoption pattern). Red bars only for actual regressions. This prevents the #1 misdiagnosis risk.

## Next Steps (Priority Order)

1. **Demo rehearsal** — Practice the 5-minute narration (script in `~/.claude/plans/wiggly-toasting-gem.md`, Step 5)
2. **Merge PR #11** to main
3. **React + FastAPI session** (new session) — Build Phase 1 web app:
   - FastAPI backend with Pydantic schemas + mock fixtures
   - React + Vite + Tailwind frontend matching the demo HTML
   - Deploy backend to Render
4. **Wave 3b** — Wire up Anthropic Client SDK for HYPOTHESIZE/DISPATCH/SYNTHESIZE stages

## Key Context for Next Session

- **Architecture spec:** `docs/plans/2026-03-14-web-app-architecture-design.md` (667 lines, IC9-reviewed, frozen API contract)
- **Visual target:** `docs/mockups/search-metric-analyzer-demo.html` — React components must match this
- **Design system:** Light theme, Fira Sans/Code, accent #2563EB, 960px max-width (CSS variables in demo file lines 9-39)
- **API contract:** POST `/api/diagnose` response shape is fully specified in the architecture spec (lines 300-500)
- **Installed skills:** `vercel-deployment`, `vercel-api` (for future Vercel operations)
- **Unstaged changes exist** on `feature/knowledge-layer-provenance` branch: knowledge YAML provenance fields + routing tests (from a parallel session — commit separately)

## Relevant Files

| File | Purpose |
|------|---------|
| `docs/mockups/search-metric-analyzer-demo.html` | THE demo — enhanced mockup with scenario switching |
| `docs/mockups/agent-view-v5.html` | Original v5 mockup (unchanged, for reference) |
| `docs/plans/2026-03-14-web-app-architecture-design.md` | Frozen architecture spec |
| `public/` | Vercel deploy directory |
| `~/.claude/plans/wiggly-toasting-gem.md` | Session plan with demo script |
| `core/schema.py` | TypedDict schemas (mock fixtures must match) |
| `core/decompose.py`, `core/diagnose.py` | Pipeline output formats |
