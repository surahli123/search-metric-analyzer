# In-House Search Metric Agent — Architecture Analysis

**Date:** 2026-03-18
**Source:** 6 screenshots of the production in-house search metric agent
**Purpose:** Reference for SMA open-source implementation

---

## 1. System Overview (Screenshot 6)

**Title:** "Search Metric Agent — How a metric question becomes a verified answer"

The in-house system has 6 color-coded layers:

### Orchestration Layer (Blue)
- **Lead Agent** — Orchestrates investigation
  - Classifies: Simple / Medium / Complex
  - 3 phases: Understand → Hypothesize → Dispatch → Synthesize
  - Enforces 14 quality gates
- **Mode Selector** — Routes by complexity
  - Simple: 1-2 queries (~5K tokens)
  - Medium: trend / triage / experiment
  - Complex: full pipeline + sub-agents
- **Knowledge Router** — Loads only what's needed
  - 8 manifest routes (5K-55K tokens)
  - Metric registry: QSR, SAIN, Chat MAU...
  - Schema catalog + playbooks + SEV archive

### Investigation Engine (Green)
- **Investigation Sub-Agent** — Tests hypotheses in parallel
  - Dispatched per hypothesis
  - Detects Simpson's Paradox & schema drift
  - Emits structured trace events
- **SQL Executor** — Runs queries against Databricks
  - query_helper.py via REST API
  - 4-level token fallback (CLI + .env)
  - Auto-logs every query to trace
- **Session Manager** — Tracks work across sessions
  - Multi-session chain linking
  - PAUSE / RESUME without losing context
  - Git branch per session
- **Analysis Tools** — Diagnoses harness health
  - 7 health signals (harness_diagnosis)
  - Mode classifier (dispatch_adapter)
  - Metric vs SQL cross-validation

### Quality & Output (Red)
- **Quality Gates (C1-C14)** — Validates every phase transition
  - C1: Question brief schema
  - C9: Hypothesis set (9 checks)
  - Mode compliance: CP1-CP5
  - Post-synthesis: 12-point report score
  - SRM: experiment arm ratio check
- **Report Generator** — Turns findings into shareable artifacts
  - HTML report (Atlassian-style)
  - Interactive trace viewer
  - Cross-validates metrics vs dashboard queries
- **Session Skills** — Lifecycle protocols
  - start-session: branch + handover
  - continue-session: pause / resume
  - close-session: record + memory + chain
  - generate-report: HTML + Confluence

### Knowledge Base (Purple)
- **Metric Registry** — Canonical metric definitions (QSR, Weighted QSR, SAIN Success, Chat MAU, Connector, Experiment)
- **Schema Catalog** — SQL patterns & table references (QSR, connector, chat, experiment) with drift checks + annotated examples
- **Playbooks** — Investigation recipes (QSR, experiments, dimensions) + SEV archive (past incident patterns) + Memory (learnings + investigation index)

### External Systems (Dark)
- **Databricks** — SQL warehouse (REST API), production analytics tables
- **Confluence** — Investigation reports, knowledge page ingestion
- **Bitbucket** — Session branch management (jlili/sma-session-NNN), PR workflow

---

## 2. Full Pipeline Flow (Screenshot 5)

### Phase 1: UNDERSTAND
- User Question → Question Routing (simple vs complex) → Question Type (SEV / Experiment / Trend / Ad-hoc)
- Structured Question: metric, surface, time range, how big, which users, what decision
- Outputs: Report + Transparency Log (feeds Phase 4)

### Phase 2: HYPOTHESIZE
- Is This Drop Real? (normal variance vs real change)
- Numerator vs Denominator Shift
- Experiment Confidence Check
- Drop Pattern Analysis
- Hypothesis Generation (playbook + first-principles)
- Output: Hypothesis Card

### Phase 3: DISPATCH
- Hypothesis Card → Route Decision (what rig for each sub-agent)
- Sub-Agent H1, H2, H3 (parallel execution)
- Finding per H: verdict, confidence, evidence
- Coverage Check

### Phase 4: SYNTHESIZE
- Completeness Check → Compare AI Findings → Confidence Scoring → Quality Rules
- TL;DR Summary / Analysis / Next Steps
- Narrative Voice: ≤5 bullets + global md (user-edited)
- Feeds future investigations

---

## 3. UNDERSTAND Stage Dependency Graph (Screenshots 3 & 4)

```
Raw Input (human text)
  ├→ Agent File Selection
  ├→ Manifest Routing (keyword match) → manifest.yaml (harness)
  │     └→ Knowledge Module Loading
  │           ├→ Model Classification (C1) ←── Metric Registry (static)
  │           │                              ←── Corrections Index (manual)
  │           └→ Metric Identification
  ├→ Table Pre-Selection ←── Socrates MCP (external)
  │                       ←── _shared.yaml (semi-static)
  ├→ Personal Memory (per-session)
  ├→ Pipeline Freshness (SQL — live check)
  └→ C4 Pre-SQL Readiness → HYPOTHESIZE
```

Knowledge sources at different freshness levels:
- **Static:** Metric Registry
- **Semi-static:** _shared.yaml
- **Per-session:** Personal Memory, Global Memory
- **Manual:** Corrections Index
- **Live (SQL):** Pipeline Freshness
- **External:** Socrates MCP

---

## 4. Repository Structure (Screenshot 2 — AGENTS.md)

```
search-metric-agent/
├── AGENTS.md              → Agent startup instructions
├── README.md              → Human-facing setup & overview
├── mcp.json               → Socrates Schema MCP config
├── agents/
│   ├── lead-agent.md            → Full monolithic file (legacy)
│   ├── lead-agent-simple.md     → Simple questions (definitions, lookups)
│   ├── lead-agent-medium.md     → Medium questions (trends, experiments, triage)
│   ├── lead-agent-complex.md    → Complex investigations (5-phase workflow)
│   └── investigation-sub-agent.md → Sub-agent: hypothesis evidence gathering
├── reference/
│   ├── gate-consolidation.md    → 14 composite checkpoints (v1.5.1)
│   ├── trace-instrumentation.md → Tiered trace setup
│   └── failure-policy.md        → Per-phase failure tolerance
├── tools/
│   ├── query_helper.py          → Primary SQL executor (Python REST API, auto-token-refresh)
│   ├── run_query.sh             → Backward-compatible wrapper
│   ├── refresh_token.sh         → Token refresh (legacy)
│   └── check_environment.sh     → Pre-flight validation
├── knowledge/
│   ├── playbook/                → Investigation Playbook (decision trees)
│   ├── sev-archive/             → Past incident case files
│   ├── metric-registry/         → YAML metric definitions
│   ├── schema-catalog/          → Search-specific SQL patterns
│   ├── corrections/             → Known data quirks and SQL fixes
│   ├── config/
│   │   ├── spaces.yaml          → Confluence space config (5 spaces)
│   │   └── roster.yaml          → Personnel roster
│   └── digests/                 → Domain Knowledge Store output (auto-refreshed)
```

---

## 5. Trace Viewer Gap Analysis (Screenshot 1)

**Current state:**
- Phase Accordion (collapsible sections)
- SQL Cards Primary (SQL is the hero content)
- Reasoning Collapsed (hidden by default)
- Thinking Auto-Expanded (rarely emitted)
- No gates visible

**Target state (Narrative Timeline):**
- Continuous Scroll (single scrollable stream — no tabs, no accordions)
- Reasoning Primary (reasoning is the hero content)
- Validation Blocks Visible (always shown)
- SQL Expandable (evidence, not hero — click to expand)
- Gates Inline (quality gates shown in the flow)

**Design principle:** "Single scrollable stream — no tabs, no accordions hiding content by default"

---

## 6. Implications for SMA

### What SMA should mirror
1. Mode Selection (Simple/Medium/Complex) with different agent files
2. 14 quality gates (C1-C14) with structured checkpoints
3. Investigation sub-agents dispatched per hypothesis (parallel)
4. Manifest-based knowledge routing (8 routes, token budgets)
5. Session lifecycle (start/continue/close/generate-report)
6. Narrative timeline trace viewer
7. HTML diagnostic reports (Atlassian-style)

### What SMA should adapt (not copy directly)
- Use DuckDB instead of Databricks
- Use GitHub instead of Bitbucket
- Skip Confluence publishing (open-source project)
- Domain-aware Simpson's Paradox detection (AI adoption ≠ paradox)

### What SMA already has that's aligned
- 4-stage pipeline (UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE) — same flow
- 11 business rule validators — extensible to 14
- IC9 invisible decision tracing — unique to SMA, not in in-house
- Deterministic fusion policy — clear and debuggable
- Co-movement pattern enforcement — domain-specific intelligence
