# SMA Improvement Plan: Learning from ai-analyst + In-House Architecture

## Context

**Problem:** Search Metric Analyzer (SMA) is a 3-layer diagnostic tool with a sequential 4-stage pipeline (UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE). While architecturally sound (seam contracts, tiered gates, IC9 tracing), it has significant gaps compared to the **in-house production system** and the **ai-analyst reference implementation**.

**In-house system (from screenshots) already has:**
- 6-layer architecture: Orchestration → Investigation Engine → Quality & Output → Knowledge Base → Session Skills → External Systems
- Mode Selection (Simple/Medium/Complex) routing to 3 different lead agent files
- 14 quality gates (C1-C14) including SRM checks, 12-point report score
- Investigation sub-agents dispatched per hypothesis (parallel, with Simpson's Paradox detection)
- SQL Executor (Databricks REST API, 4-level token fallback)
- Session Manager (multi-session chaining, PAUSE/RESUME, git branch per session)
- Knowledge Router (8 manifest routes, 5K-55K token budgets)
- Report Generator (HTML Atlassian-style, interactive trace viewer, Confluence publishing)
- UNDERSTAND stage dependency graph: Raw Input → Manifest Routing → Knowledge Module Loading → Model Classification (C1) → Metric Identification → Table Pre-Selection → C4 Pre-SQL Readiness → HYPOTHESIZE

**SMA gaps vs in-house:**
1. No mode selection (one pipeline for all complexity levels)
2. 11 business rules vs 14 quality gates (missing SRM, mode compliance, report score)
3. No investigation sub-agents (DISPATCH is single-agent)
4. No SQL executor (synthetic data only)
5. No session management (no PAUSE/RESUME, no chain linking)
6. Static knowledge routing (YAML files vs manifest-based routing with token budgets)
7. No report generation (Slack messages + markdown only)
8. Trace viewer gap: accordion-based vs target narrative timeline

**Goal:** Evolve SMA to mirror the in-house 6-layer architecture, borrowing infrastructure patterns from ai-analyst (DAG orchestration, CONTRACT blocks, knowledge system) while preserving SMA's domain intelligence.

**Dual purpose:** SMA improvements double as interview preparation for OpenAI/Perplexity DS roles.

**Principle:** Copy ai-analyst's pipes, not its water. Mirror in-house architecture, not its proprietary data.

---

## Wave 1: Agent Architecture (Foundation)

**Goal:** Replace sequential Python callables with declarative agents, mode selection, and DAG orchestration — mirroring the in-house Lead Agent + Mode Selector + Knowledge Router pattern.

### 1A. Mode Selection (Simple/Medium/Complex)

Mirror the in-house pattern of 3 lead agent variants:

| Mode | In-House | SMA Equivalent |
|------|----------|---------------|
| **Simple** | 1-2 queries (~5K tokens), definitions/lookups | Single-tool diagnosis (e.g., "what's the Click Quality formula?") |
| **Medium** | Trends, experiments, triage | Standard 4-stage pipeline (current SMA behavior) |
| **Complex** | Full pipeline + sub-agents, 5-phase workflow | Full pipeline + investigation sub-agents (new) |

**Files to create:**
- `agents/lead-agent-simple.md` — Direct knowledge lookup, no pipeline
- `agents/lead-agent-medium.md` — Standard 4-stage pipeline
- `agents/lead-agent-complex.md` — Full pipeline with sub-agent dispatch
- `harness/mode_selector.py` — Classifies question complexity, routes to agent

**Interview angle:** "We route by complexity — simple questions get 1-2 queries, complex investigations get a full multi-agent pipeline with parallel sub-agents. This mirrors how a senior DS triages: quick lookup vs full investigation."

### 1B. Declarative Agent Definitions (CONTRACT blocks)

Each agent declares typed inputs, outputs, dependencies, and **required knowledge** via CONTRACT blocks. The orchestrator enforces knowledge loading before the agent runs.

Mirror the in-house UNDERSTAND dependency graph:
```
Raw Input → Manifest Routing (keyword match) → manifest.yaml
  → Knowledge Module Loading
  → Model Classification (C1) ← Metric Registry (static), Corrections Index
  → Metric Identification
  → Table Pre-Selection ← Socrates MCP, _shared.yaml
  → C4 Pre-SQL Readiness ← Personal Memory, Pipeline Freshness
  → HYPOTHESIZE
```

**Files to create:**
- `agents/understand.md` — CONTRACT: requires metric_definitions.yaml, historical_patterns.yaml
- `agents/hypothesize.md` — CONTRACT: requires co-movement table, corrections, hypothesis priority
- `agents/dispatch-ranking.md` — CONTRACT: requires search_pipeline_knowledge.yaml ranking section
- `agents/dispatch-connector.md` — CONTRACT: requires connector failure modes
- `agents/dispatch-ai-quality.md` — CONTRACT: requires AI feature knowledge
- `agents/investigation-sub-agent.md` — CONTRACT: per-hypothesis evidence gathering (mirrors in-house)
- `agents/synthesize.md` — CONTRACT: requires all prior agent outputs + narrative rules
- `agents/registry.yaml` — Machine-readable dependency graph
- `harness/manifest.yaml` — Knowledge routing manifest (8 routes, token budgets per route)

**Files to modify:**
- `harness/orchestrator.py` — Refactor to read registry.yaml, load knowledge per CONTRACT, dispatch agents
- `harness/llm.py` — Support agent-as-markdown invocation

**What to reuse from SMA:**
- `contracts/seam_validator.py` — 11 business rules stay, extended toward 14 gates
- `trace/` — IC9 tracing stays, now emits per-agent spans
- `core/` — All deterministic tools stay untouched (Layer 1 independence preserved)

**What to borrow from ai-analyst:**
- CONTRACT block format — `ai-analyst/agents/CONTRACT_TEMPLATE.md`
- Registry schema — `ai-analyst/agents/registry.yaml`
- DAG validation — `ai-analyst/.claude/skills/run-pipeline/skill.md`

### 1E. Domain-Scoped Question Framing (UNDERSTAND enhancement)

Unlike ai-analyst's fully open question framing, SMA's question framing is **domain-constrained** — like query understanding in search. The agent:
1. **Parses** the user's question (metric drop? system understanding? experiment eval? trend?)
2. **Enriches** with domain knowledge (which components, metrics, tables are relevant)
3. **Structures** into investigation plan (what to check, in what order, what evidence to gather)
4. **Routes** to mode (Simple/Medium/Complex)

Expanded question types beyond SEV/Experiment/Trend:
- **SEV** — "QSR dropped 3pts overnight" (diagnostic)
- **Experiment** — "Is this experiment significant?" (evaluation)
- **Trend** — "How has connector health changed over Q1?" (longitudinal)
- **Deep Dive** — "How does connector health affect query quality?" (exploratory → diagnostic)
- **System Understanding** — "What's the relationship between AI adoption and user satisfaction?" (analytical)
- **Ad-hoc** — "What tables have QSR data?" (simple lookup)

**Why not fully open:** The domain knowledge (co-movement patterns, hypothesis priority, archetypes) IS the value. Open-ended questions are gateways to diagnostic investigations — the framing layer helps users arrive at the right diagnostic question faster.

**What NOT to borrow:**
- Data-agnostic connection manager (defer to Wave 3)
- Marp deck generation (wrong audience)

### 1C. DAG Orchestration with Parallel Dispatch

- Topological sort from registry.yaml
- DISPATCH stage runs investigation sub-agents in parallel (H1, H2, H3 — mirrors in-house)
- Per-hypothesis error isolation (one failure → "inconclusive")
- Circuit breaker: 3 agent failures in same tier → pipeline halts
- Coverage check after dispatch (mirrors in-house: ensures all hypotheses covered)

**Latency improvement:** 4 sequential LLM calls (~120s) → 3 tiers with parallel DISPATCH (~60s)
**Token efficiency:** Each sub-agent gets focused context (its CONTRACT knowledge only)

### 1D. Quality Gates Expansion (11 → 14)

Extend current 11 business rules toward in-house 14 gates:

| Gate | In-House | SMA Status |
|------|----------|-----------|
| C1: Question brief schema | ✅ | Add — validate structured question output |
| C4: Pre-SQL readiness | ✅ | Add — validate table selection + metric ID before SQL |
| C9: Hypothesis set (9 checks) | ✅ | Partially exists — extend |
| CP1-CP5: Mode compliance | ✅ | Add — validate agent followed mode-appropriate path |
| Post-synthesis: 12-point report score | ✅ | Add — quality rubric for final output |
| SRM: experiment arm ratio check | ✅ | Add — critical for experiment investigations |

---

## Wave 2: Knowledge & Learning Loop

**Goal:** Evolve from static YAML files to manifest-based routing with the 3-tier knowledge architecture.

### Knowledge Router (mirrors in-house)

The in-house system has 8 manifest routes with 5K-55K token budgets. SMA currently loads knowledge via a prompt-based routing table in markdown.

**Upgrade path:**
- `harness/manifest.yaml` — Machine-readable routing (replaces markdown routing table)
- Each route specifies: intent pattern, knowledge files, token budget, freshness requirement
- The orchestrator reads the manifest and loads knowledge BEFORE agent invocation
- **This is the core fix for the knowledge grounding problem**

### Knowledge Tiers (mapped from in-house)

| Tier | In-House Directories | SMA Implementation |
|------|---------------------|-------------------|
| **Infrastructure** | metric-registry/, schema-catalog/ | `data/knowledge/metric_definitions.yaml` + new `data/knowledge/schema_catalog/` |
| **Investigative** | playbook/, sev-archive/, corrections/ | New `data/investigations/` with record/index/playbook pipeline |
| **Domain** | digests/ (auto-refreshed), config/ | New `data/knowledge/digests/` with domain knowledge store |

### Learning Loop
- **Correction logging:** Extend corrections to capture investigation-level overrides
- **Investigation archive:** Each investigation → structured record → index → playbook
- **Playbook distillation:** After N similar archetypes, auto-generate playbook entries
- **SEV archive:** Past incident case files with data signatures (mirrors in-house sev-archive/)

### What to borrow from ai-analyst
- `.knowledge/` directory structure — `ai-analyst/.knowledge/README.md`
- Correction logging format — `ai-analyst/.knowledge/corrections/log.yaml`
- Query archaeology pattern — `ai-analyst/.knowledge/query-archaeology/`
- Miss rate logger — `ai-analyst/helpers/miss_rate_logger.py`

### Interview Angle
- "3 tiers by team function (DE/DS/Eng), each with different time horizons"
- "Manifest-based routing with token budgets replaces prompt-based routing — like moving from regex URL routing to a proper API gateway"

---

## Wave 3: Data Connectivity

**Goal:** Move from synthetic-only to real data source support, mirroring in-house SQL executor.

### SQL Executor (mirrors in-house query_helper.py)
- Python-based SQL executor with REST API pattern
- DuckDB for local analysis (open-source alternative to Databricks)
- CSV/Parquet ingestion for exported search metrics
- Auto-logging every query to trace (mirrors in-house)
- Schema profiler: auto-detect columns, distributions, quality issues

### What to borrow from ai-analyst
- Connection manager pattern (simplified) — `ai-analyst/helpers/connection_manager.py`
- Schema profiler — `ai-analyst/helpers/schema_profiler.py`
- Source tie-out validation — `ai-analyst/helpers/tieout_helpers.py`

### What to keep from SMA
- Synthetic scenarios remain as **regression tests**
- Baselines by segment remain the source of truth

### Interview Angle
- "Synthetic scenarios are regression tests. Real validation comes from 15+ production investigations."
- "SQL executor auto-logs every query to the investigation trace — full data lineage from question to answer."

---

## Wave 4: Richer Output Layer

**Goal:** Upgrade to narrative timeline trace viewer + HTML diagnostic reports, mirroring in-house targets.

### Trace Viewer Redesign (from Screenshot 1 gap analysis)

| Current | Target |
|---------|--------|
| Phase Accordion | Continuous Scroll (narrative timeline) |
| SQL Cards Primary | SQL Expandable (evidence, not hero) |
| Reasoning Collapsed | Reasoning Primary |
| Thinking Auto-Expanded (rarely) | Validation Blocks Visible |
| No gates visible | Gates Inline |

**Key design principle:** Single scrollable stream — no tabs, no accordions hiding content by default.

### Narrative Quality Architecture (SYNTHESIZE enhancement)

Three problems to solve: verbose hedging, no story structure, evidence disconnected from conclusions.

**4B-i. Narrative Quality Gate** — Enforced rules (not suggestions) at SYNTHESIZE:
- No hedge words ("it appears," "might suggest," "potentially") — state conclusions directly
- No passive voice — "Confluence connector degraded" not "degradation was observed"
- Max sentence length enforcement
- Every finding must reference its evidence source (inline SQL/table reference)
- ≤5 bullet TL;DR + structured evidence blocks

**4B-ii. Finding → Evidence → Confidence → Recommendation structure:**
Each finding in the report follows this template:
```
**Finding:** Click Quality dropped 3.2% WoW
**Evidence:** Confluence connector contribution = -2.1pp (SQL: see Table 2)
**Confidence:** High (matches 'connector_health' archetype, 3/3 validation checks pass)
**Recommendation:** Check Confluence connector pipeline freshness → escalate to connector team
```
This replaces flat lists of observations with connected narrative.

**4B-iii. 12-Point Report Score** (mirrors in-house quality gate):
Quality rubric for final output — every report must score above threshold before delivery.
Criteria include: evidence linkage, conclusion directness, actionability, confidence calibration.

**What to borrow from ai-analyst:**
- Narrative coherence review pattern — `ai-analyst/agents/narrative-coherence-reviewer.md`
- Chart design critic checklist — `ai-analyst/agents/visual-design-critic.md` (adapted for report quality)

### Report Generator (mirrors in-house)
- HTML diagnostic report (Atlassian-style, like in-house)
- Interactive trace viewer embedded in report (narrative timeline, not accordion)
- Evidence inline with findings (not buried in appendix)
- Confidence scoring display with evidence links
- ≤5 bullet TL;DR summary + narrative voice (mirrors in-house SYNTHESIZE output)

### Session Skills (mirrors in-house lifecycle)
- `start-session` — branch + handover context
- `continue-session` — PAUSE/RESUME without losing context
- `close-session` — record + memory + chain linking
- `generate-report` — HTML output

### What NOT to build
- Slide decks / Marp (wrong audience)
- Confluence publishing (SMA is open-source, no Confluence)
- Branded themes (engineers want clarity, not branding)

---

## What NOT to Adopt

| Pattern | Source | Decision |
|---------|--------|----------|
| Open-ended question framing | ai-analyst | **ADOPT (adapted)** — Domain-scoped, not fully open. Acts as query understanding layer. Added as Wave 1E. |
| Story architecture + narrative coherence | ai-analyst | **ADOPT (adapted)** — Not full storyboarding. Narrative quality gate + Finding→Evidence→Confidence→Recommendation structure. Added as Wave 4B. |
| Universal data connector (5 warehouses) | ai-analyst | Skip — DuckDB + CSV is sufficient for open-source |
| Marp slide decks + branded themes | ai-analyst | Skip — Wrong audience |
| Generic Simpson's Paradox detector | ai-analyst | Skip — SMA needs domain-aware detection (AI adoption ≠ paradox) |
| Bitbucket integration | in-house | Skip — SMA uses GitHub |
| Confluence publishing | in-house | Skip — SMA is open-source |
| Databricks-specific SQL | in-house | Skip — SMA uses DuckDB for portability |

---

## Sequencing & Dependencies

```
Wave 1: Agent Architecture ──────────────────────────> (Foundation)
  ├── 1A: Mode Selection (Simple/Medium/Complex)
  ├── 1B: Declarative agents + CONTRACT blocks
  ├── 1C: DAG orchestration + parallel dispatch
  └── 1D: Quality gates expansion (11 → 14)
              │
Wave 2: Knowledge & Learning Loop ──────────────────> (Intelligence)
  ├── Manifest-based knowledge routing
  ├── 3-tier knowledge architecture
  └── Investigation archive + playbook distillation
              │
Wave 3: Data Connectivity ──────────────────────────> (Production-readiness)
  ├── SQL executor (DuckDB + CSV/Parquet)
  ├── Schema profiler + data quality
  └── Query auto-logging to trace
              │
Wave 4: Richer Output Layer ────────────────────────> (Presentation)
  ├── Trace viewer redesign (narrative timeline)
  ├── HTML diagnostic reports
  └── Session lifecycle skills
```

Each wave is independently shippable. Wave 1 is the prerequisite.

---

## Interview Prep Angles (Summary)

| Topic | Key Talking Point |
|---|---|
| **Contracts & Gates** | "Applied experimentation guardrail thinking — 14 quality gates with C1-C14 checkpoints including SRM checks and a 12-point report score" |
| **IC9 Invisible Decisions** | "Trace 4 points where the system silently commits — like debugging query understanding vs ranking in search" |
| **Knowledge Grounding** | "Manifest-based routing with token budgets replaced prompt-based routing — like moving from regex to an API gateway" |
| **Pipeline → Multi-Agent** | "Latency (parallel sub-agents), token efficiency (focused context per agent), resilience (cross-check instead of cascade)" |
| **Mode Selection** | "Route by complexity: simple gets 1-2 queries, complex gets full pipeline + parallel sub-agents. Like triaging P0 vs P2 alerts." |
| **3-Tier Knowledge System** | "Infrastructure (what data means), Investigative (what we learned), Domain (current system state). Each tier has different time horizons." |
| **Domain vs General** | "Borrowed infrastructure patterns from general-purpose analytics (DAG, contracts). Kept domain intelligence (co-movement, hypothesis ordering, archetypes)." |
| **Session Management** | "Multi-session chain linking with PAUSE/RESUME — investigations span days, context must persist across sessions." |

---

## Verification

### Per Wave
- **Wave 1:** All 949 existing tests pass + new tests for mode selector, registry parsing, CONTRACT validation, DAG execution, parallel dispatch, new quality gates
- **Wave 2:** Manifest routing loads correct knowledge per route. Investigation records round-trip (write, index, retrieve). Playbook generation produces valid entries.
- **Wave 3:** Can load real CSV/Parquet data, profile schema, run decomposition on non-synthetic data. All queries auto-logged to trace.
- **Wave 4:** Trace viewer renders as narrative timeline. HTML report generates with confidence scoring. Session lifecycle works (start/pause/resume/close).

### End-to-End
- Run full pipeline (all 3 modes) on synthetic scenarios → verify same diagnostic output
- Run full pipeline on real (anonymized) search metric dataset → verify reasonable diagnosis
- Stress test: all 6 scenarios must remain GREEN after each wave

---

## Pre-requisites Before Starting

1. Merge PR #14 (Wave 3b) into main
2. Verify `feature/wave-3b-clean` branch is clean
3. Create new branch: `feature/wave-4-agent-architecture` (or similar)
4. Read ai-analyst's CONTRACT_TEMPLATE.md and registry.yaml in detail
5. Review in-house AGENTS.md and gate-consolidation.md for reference patterns
