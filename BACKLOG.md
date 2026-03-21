# Backlog — Search Metric Analyzer v2.0 Holistic Redesign

Last updated: 2026-03-20

---

## Upcoming

### Wave 3a: Trace Emission + Remediation + Corrections (DONE — 2026-03-08)
- [x] Task 1: Create `trace/helpers.py` with `emit_deterministic_span()` convenience helper
- [x] Task 2: Add trace emission to `core/decompose.py` (IC9 #1: metric_direction)
- [x] Task 3: Add trace emission to `core/anomaly.py` (data quality, step change, co-movement)
- [x] Task 4: Add trace emission to `core/diagnose.py` (archetype, confidence)
- [x] Task 5: Add remediation messages to all 11 contract violation rules
- [x] Task 6: Create `core/corrections.py` + `data/knowledge/corrections.yaml` (read/write/CLI, 90-day expiry)
- [x] Task 7: Wave 3a verification (full test suite + eval)

### Web App Phase 0: Demo Mockup (DONE — 2026-03-15)
- [x] Enhanced v5 mockup with scenario switching (Within Variance + Ranking Regression)
- [x] Fixed Critical chart color issue (all bars blue for AI adoption pattern)
- [x] Added data quality badges, hypothesis evaluation checklist
- [x] 3-role IC9 review + design critique → 10 UI fixes applied
- [x] Deployed to Vercel: https://search-metric-analyzer-demo.vercel.app
- [x] PR #11 created
- Demo file: `docs/mockups/search-metric-analyzer-demo.html`

### Web App Phase 1: React Frontend + FastAPI Backend (DONE — 2026-03-16)
- [x] Scaffold `web/backend/` — FastAPI app, mock fixtures, diagnose route, health check
- [x] Scaffold `web/frontend/` — React + Vite + Tailwind, design tokens from demo CSS
- [x] Build 14 Overview tab components (match demo HTML visual target)
- [x] Wire 2 hardcoded mock investigation fixtures with scenario switching
- [x] 9 backend tests + 23 frontend tests (32 total)
- [x] Fix DivergingBarChart overflow, text clipping, insight badges, TrendChart Y-axis
- [x] Apply 3 DS Lead review fixes (SQS delta, hypothesis honesty, enterprise counts)
- [x] Build Execution Trace tab components (TraceTab, TracePhaseCard, TraceStep, filter pills) — done in UI Redesign PR #15
- [ ] Deploy backend to Render (free tier) — deferred, running locally for demo
- PR #13 merged
- Plan: `docs/superpowers/plans/2026-03-15-web-app-react-phase1.md`

### UI Redesign: 3-Tab Architecture (DONE — 2026-03-19)
- [x] Design critique (Impeccable + gstack Design Review) — 8 issues found
- [x] 3-tab navigation: Investigate (query at top), Trace, Knowledge Base
- [x] Progressive disclosure: Answer → Evidence (collapsible) → Technical (collapsed)
- [x] Plain English labels, section headers, conclusion-first patterns
- [x] Naming cleanup: removed "Customer Cohort FPS", expanded SQS
- [x] Chart polish: titles, axis labels, units, SQL collapsed
- [x] 194 frontend tests (up from 23), code review + TDD audit
- [x] Deployed to Vercel: https://search-metric-analyzer.vercel.app
- PR #15 merged

### Web App Phase 2: SSE Streaming + Live Trace (after Phase 1)
- [ ] Implement SSE streaming endpoint with in-memory buffer
- [ ] Wire real pipeline calls (decompose → diagnose → orchestrate)
- [ ] Build loading/error/empty states

### Web App Phase 3: Dashboard View (after Phase 2)
- [ ] Build 6 metric cards (including Connector Health)
- [ ] Clickable cards → pre-filled Agent investigation
- [ ] Tenant tier filter tabs

### Wave 3b: Full 4-Stage Orchestrator (DONE — 2026-03-17)
- [x] Task 8: OrchestratorError hierarchy + SearchMetricOrchestrator skeleton + UNDERSTAND stage
- [x] Task 9: HYPOTHESIZE stage (LLM + corrections context + IC9 #2: hypothesis_inclusion trace)
- [x] Task 10: DISPATCH stage (reuse orchestrate() + IC9 #3: context_construction trace)
- [x] Task 11: SYNTHESIZE stage (LLM + retry gate + IC9 #4: narrative_selection trace)
- [x] Task 12: Error handling integration tests
- [x] Task 13: make_anthropic_llm() factory with timeout + optional SDK
- [x] Task 14: Wave 3b verification (all 4 IC9 decisions traced end-to-end)
- 949 tests GREEN, PR #14 merged

### Wave 4: Skill File + Eval (DONE — 2026-03-20, PR #23)
- [x] Update `skills/search-metric-analyzer.md` — add seam validator subprocess calls after each stage
- [x] Add trace context reads at SYNTHESIZE stage in skill file
- [x] Add `investigation_context` to sub-agent context at DISPATCH stage
- [x] Extend `eval/run_eval.py` — add trace coverage checks (4 IC9 Invisible Decisions)
- [x] Extend eval — add seam check coverage (4 seam validations ran and passed)
- [x] Add eval scenario S8b (SYNTHESIZE compliance — catches missing mandatory sections)
- [x] Run eval stress test — all 7 scenarios GREEN (avg 91.7/100)

---

## Open Code Review Items (from Wave 1 review)

Priority: fix during the wave where they naturally fit.

- [ ] `contribution_pct` naming — ratio (0.0-1.0) vs percentage (0-100). Deferred to Wave 3 (confirmed no actual ambiguity — consistently 0-100). (Suggestion)
- [ ] `constrained_by` field validation — add warning in `InvestigationTrace.emit()` when `swimlane == "llm_generated"` and `constrained_by` missing. Fix during Wave 3 when adding LLM spans. (Important)
- [ ] Business rules return single violation — document as known limitation or change return type to `List[str]`. (Suggestion)
- [ ] `narrative_data_coherence` false-negative bias — add docstring noting that mixed-direction text passes. (Suggestion)
- [ ] `CoMovementResult.runner_up` double-optional — `Optional[str]` + `total=False` is redundant. (Suggestion)
- [ ] `InvestigationTrace.emit()` mutates span dict in-place — add docstring note. (Suggestion)

### Knowledge Layer: Context Optimization (2026-03-14)
- [x] Create knowledge routing table (`.claude/rules/04-knowledge-routing.md`)
- [x] Enrich rule 01 with alert thresholds, baselines, blind spots
- [x] Enrich rule 03 with decision points
- [x] Create context layer architecture spec (`docs/plans/2026-03-14-context-layer-architecture.md`)
- [x] Copy session record to `docs/research/`
- [x] Code review — blocking issues fixed
- [x] Push + open PR for `feature/knowledge-routing-context-layer` (merged PR #10)
- [ ] Add per-segment SQS baselines to rule 01 (when pipeline data available)
- [x] Add provenance fields to YAML entries — tiered by decay rate (2026-03-15)
- [x] Build `test_knowledge_routing.py` integrity checker — 7 tests + 6 provenance tests (2026-03-15)
- [x] Minor: add one-line note in spec Section 3 (2026-03-15)
- [x] Minor: add 4th scalability trigger (>500 entries) to rule 04 (2026-03-15)
- [ ] Add process note to spec: after corrections, update `last_validated` on referenced entry

---

## SMA v2 Improvement Plan (approved 2026-03-18)

4-wave roadmap to mirror in-house architecture, borrowing from ai-analyst.
Full plan: `docs/plans/2026-03-18-sma-v2-improvement-plan.md`

### Wave 5: Agent Architecture (DONE — 2026-03-20, PRs #16-#20)
- [x] 5A: Mode Selection (Simple/Medium/Complex) — 3 lead agent variants + mode_selector.py
- [x] 5B: Declarative agents with CONTRACT blocks + registry.yaml (7 agents + registry parser)
- [x] 5C: DAG orchestration with parallel dispatch (DAGExecutor + ThreadPoolExecutor)
- [x] 5D: Quality gates expansion (13 → 17, exceeds in-house 14)
- [x] 5E: Domain-scoped question framing (question_parser.py + QuestionBrief contract)
- [x] Code review: all 10 findings addressed (PR #20)

### Wave 6: Knowledge & Learning Loop
- [ ] Manifest-based knowledge routing (8 routes, token budgets)
- [ ] 3-tier knowledge architecture (Infrastructure/Investigative/Domain)
- [ ] Investigation archive + playbook distillation
- [ ] SEV archive (past incident case files)

### Wave 7: Data Connectivity
- [ ] SQL executor (DuckDB + CSV/Parquet)
- [ ] Schema profiler + data quality validation
- [ ] Query auto-logging to trace

### Wave 8: Richer Output Layer
- [ ] Trace viewer redesign (narrative timeline, not accordion)
- [ ] Narrative quality gate (no hedging, evidence-linked findings, 12-point report score)
- [ ] HTML diagnostic reports (Atlassian-style)
- [ ] Session lifecycle skills (start/continue/close/generate-report)

---

## Deferred to v2.1+

- [ ] Cross-mode conformance test — run same scenarios through Mode A and Mode B, compare trace outputs
- [ ] Hypothesis re-generation loop (breaks One-Shot Constraint)
- [ ] Memory quality system (Memory Time Bomb)
- [ ] Inter-batch context flow
- [ ] Calibrate severity thresholds (one-size-fits-all → metric-specific)
- [ ] Simpson's Paradox reversal check in decompose.py
- [ ] Archetype-specific actions for `unknown_pattern` fallback
- [ ] `click_behavior_change` lumps UX + mix-shift without prioritization

---

## Done

### Wave 2: Directory Restructure (2026-03-08)
- [x] Rename `tools/` → `core/` (git mv, preserve history)
- [x] Move `tools/agent_orchestrator.py` → `harness/orchestrator.py`
- [x] Move `tools/connector_investigator.py` → `harness/connector_investigator.py`
- [x] Create `core/__init__.py` and `harness/__init__.py`
- [x] Update all imports in `tests/*.py` (11 files)
- [x] Update all imports in `eval/*.py` (2 files)
- [x] Update CLI paths in `skills/search-metric-analyzer.md`
- [x] Update `CLAUDE.md`, `README.md`, operational markdown docs
- [x] Delete thin wrappers (`generate_synthetic_data.py`, `validate_scenarios.py`)
- [x] Fix dead fallback import in `harness/orchestrator.py`
- [x] Run full test suite — 694 passed, 21 skipped
- [x] Run eval stress test — 6/6 GREEN, avg 91.7
- [x] Code review — all findings addressed
- [x] PR #4 opened

### Wave 1: Trace + Contracts (2026-03-07)
- [x] Create `trace/` module (span.py, collector.py, schema.py)
- [x] Create `contracts/` module (understand.py, hypothesize.py, dispatch.py, synthesize.py, seam_validator.py)
- [x] Implement 11 business rules with tiered gates (hard/soft/retry)
- [x] Implement Amendment 2: `rule_hypotheses_consistent_with_co_movement`
- [x] Implement Amendment 3: `MixShiftResult` in UnderstandResult
- [x] Implement Amendment 4: `agent_context_for()` with token budget
- [x] Write 144 tests (57 trace + 87 contracts)
- [x] Move IC9 review + tech talk docs into repo
- [x] Create OpenAI harness engineering reference stub
- [x] Save v2 design doc
- [x] Run IC9-calibrated review (DS Lead, PM Lead, Principal AI Eng)
- [x] Fix Critical #1: word-boundary regex in `rule_effect_size_proportionality`
- [x] Fix Critical #2: update `validate_seam` signature in design doc
- [x] Set up `.worktrees/` with gitignore
