# PM Lead Addendum: Findings Beyond IC9 Review

**Date:** February 22, 2026
**Role:** AI PM Lead
**Context:** After reading the IC9 critique (DS_STAR_CRITIQUE.md) and v1.4 implementation, these are findings the IC9 did NOT cover.

---

## What the IC9 Already Covered (No Overlap Needed)

- verify_diagnosis() — 5 deterministic checks → **Implemented v1.4**
- Scored archetype matching → **Implemented v1.4**
- Structured subagent specs (confirms_if/rejects_if) → **Implemented v1.4**
- Rejected: 7-agent specialization, 20-iteration loops, Router → **Decision recorded**

---

## New Findings (IC9 Did Not Address)

### 1. The Two-System Strategic Problem (RESOLVED)

Two parallel systems exist:
- **Python Toolkit (v1.4):** 4 deterministic tools, 9 archetypes, working
- **Multi-Agent Spec (Shane Butler-inspired):** 10 agents, 6 phases, not built

**Resolution:** Toolkit is Layer 1 (deterministic foundation). Multi-agent is Layer 3 (future). They're the same product at different maturity stages. The toolkit doesn't get replaced — it becomes the spine that agents call.

### 2. Runner-Up Archetype as Active Verification

v1.4 returns `runner_up` from scored matching but `verify_diagnosis()` doesn't use it. Should actively compare chosen archetype vs. runner_up using confirms_if/rejects_if fields.

**Priority:** v1.5 candidate — low effort, high impact.

### 3. Simpson's Paradox Reversal Check

Design spec (multi-agent version) lists Simpson's Paradox as mandatory Check #1. Toolkit has mix-shift detection (≥30% threshold) but not directional reversal detection (aggregate down, all segments up).

**Priority:** v1.5 candidate.

### 4. Eval Coverage: 5/10 Archetypes Tested

Only 5 of 13 defined scenarios in eval. Missing archetypes include connector pipeline cases — the most critical failure domain per IC9 judges.

**Priority:** v1.5 candidate — expand to 10 scenarios (one per archetype).

### 5. Historical Patterns YAML Is Empty

Referenced throughout design, skill, and diagnosis logic but not populated. This is the institutional memory that gives the toolkit its speed advantage over manual debugging.

**Priority:** v1.5 must-have — populate 5-10 from real SEV archive.

---

## Strategic Decision Made: Hybrid v1.5-lite + Subagent Spike

**Approved approach:**

| Track | What | Why |
|---|---|---|
| **v1.5-lite** | 5-10 historical patterns, noise calibration from 3 real incidents, eval expansion to 10 archetypes | Minimum viable foundation validation |
| **Subagent spike** | 1 Connector Investigator subagent using confirms_if → SQL via Databricks MCP → verify_diagnosis() feedback | Proves multi-agent bridge works end-to-end |

**Key design decisions:**
- Subagent only fires when confidence is Medium or Low (preserves <60s for High-confidence cases)
- Max 3 SQL queries, 1 LLM interpretation call, 2-minute timeout
- Connector Investigator first because connectors are most critical failure domain

**Next step:** Write formal v1.5 design doc (deferred to next session).
