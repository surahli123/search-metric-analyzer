# Session Log: Search Metric Debug System — Architecture Design

**Date:** February 21, 2026
**Topic:** Designing a multi-agent Search metric debug system inspired by Shane Butler's AI Analyst Genome

---

## Context

Sarah saw a LinkedIn post by Shane Butler about his AI Analyst system and wanted to understand how he built it, then adapt the architecture for her own use case: debugging Search metric drops across a complex pipeline (Query Understanding, Retrieval, Ranking, Interleaver, Third-Party Connectors, Search Experience).

---

## Turn 1: User Shares Screenshots

Sarah shared two screenshots:

**Screenshot 1 (LinkedIn Post — Shane Butler):**
Shane describes how the key to unlocking Claude Code for analysis was making agents argue with each other first. His "AI Analyst Genome" has three architect agents (Product Architect, Quality Systems Designer, DevEx Designer) that produce proposals independently, then annotate each other's work with AGREE, DISAGREE, or EXTEND. A fourth agent resolves conflicts using predetermined priority rules. Original architects can only challenge by citing specific failure modes. His tagline: "Not consensus. Debate."

**Screenshot 2 (VS Code — Skill: /architect):**
Shows his `/architect` skill in detail:
- Parameters: brief (required), --personas (default 5), --skip-debate, --output-dir
- Methodology phases:
  - Phase 0: Scope & Persona Selection → define brief, pick 3-5 expert personas
  - Phase 1: Independent Plans (Round 1) → all personas plan in parallel
  - Phase 2: Debate & Critique → single moderator resolves conflicts
  - Phase 3: Revised Plans (Round 2) → personas revise in parallel
  - Phase 4: Alignment & Synthesis → single architect produces master plan
  - Phase 5: Build Status Tracker → CREATE BUILD_STATUS.yaml
- Running Claude Code v2.1.44, Opus 4.6, in the ai-analyst project

**User's request:** "Please read the screenshot, understand how he built, then tie to my case where I also want to build something similar but focus more on search metric analysis (debug metric drop). How can I do architect design."

---

## Turn 2: Claude's Initial Analysis

### What Shane Built

His `/architect` skill implements a multi-persona planning methodology with structured debate:
- Phase 0 — Scope & Persona Selection
- Phase 1 — Independent Plans (parallel)
- Phase 2 — Debate & Critique (AGREE/DISAGREE/EXTEND + moderator)
- Phase 3 — Revised Plans
- Phase 4 — Alignment & Synthesis
- Phase 5 — Build Status Tracker

Key insight: "Not consensus. Debate." Quality comes from agents designing around edge cases through forced challenges citing specific failure modes.

### Mapping to Search Metric Debug

**Proposed Persona Selection for Search:**
1. Query Understanding Specialist
2. Retrieval & Ranking Engineer
3. Third-Party Connector Analyst (most critical, fastest-changing area)
4. Search Experience / Interleaver Analyst
5. Metrics & Experimentation Lead

**Adapted Phase Design:**
- Phase 0: Intake & Triage (classify metric, auto-select relevant personas)
- Phase 1: Independent Hypotheses (each persona generates ranked hypotheses with expected data signatures)
- Phase 2: Cross-Examination (AGREE/DISAGREE/EXTEND with domain evidence requirements)
- Phase 3: Investigation Plan (prioritized debug checklist)
- Phase 4: Analysis Template (queries, comparisons, segments to decompose)

**Connection to existing work:**
- Multi-agent review system sits downstream (debug → analysis → review)
- Domain Knowledge Skill becomes shared context layer for all architect personas
- `--skip-debate` parameter as cost control for public Streamlit demo

**Prioritization suggestion:**
- Start with 3 personas instead of 5
- Single debate round initially
- `--skip-debate` for cost management

---

## Turn 3: User Shares Blog Post

**User:** "This is his blog for reference: https://aianalystlab.ai/blog/ai-analyst-pipeline-tutorial/"

---

## Turn 4: Claude Fetches and Analyzes Full Blog

Fetched the full blog post: "Will Claude Code + Opus 4.6 Replace Your Data Team?"

### Key Insights from the Full Blog

**Skills vs Agents separation:**
- Skills define HOW (standards, patterns, always-active triggers)
- Agents define WHAT (multi-step workflows, invoked on demand)
- Skills tell agents what "good" looks like — change one skill file, every agent that uses it produces different output

**15 agents across 6 phases:**
- Phase 1: Frame (Question Framing, Hypothesis)
- Phase 2: Explore (Data Explorer, Descriptive Analytics, Overtime/Trend, Root Cause Investigator, Opportunity Sizer, Experiment Designer) — parallel where possible
- Phase 3: Validate (re-derives key numbers independently, Simpson's Paradox check)
- Phase 4: Story (Story Architect, Narrative Coherence Reviewer, Storytelling) — sequential
- Phase 5: Charts (Chart Maker, Visual Design Critic)
- Phase 6: Deliver (Deck Creator)

**12 skills throughout:** data quality check, question framing, analysis design spec, triangulation, metric spec, tracking gaps, guardrails, visualization patterns, presentation themes, stakeholder communication, close-the-loop, run-pipeline

**Self-improving loop:** Feedback updates agent/skill files permanently, not just the current output. Compound improvement over time.

**Analytical judgment highlights:**
- Simpson's Paradox check is mandatory and built into the workflow
- Root cause investigator does "peel the onion" up to 7 iterations deep
- Validation agent re-derives numbers using new queries (not copies)
- Storytelling follows Context/Tension/Resolution arc

### Adapted Architecture for Search Metric Debug

Provided complete architecture with:

**5 Skills:** Domain Knowledge (always-active), Metric Definitions, Decomposition Patterns, Validation Rules, Communication Standards

**10 Agents across 6 Phases:**
- Phase 0: Triage (Metric Intake)
- Phase 1: Hypothesize (Hypothesis Generator)
- Phase 2: Investigate (Decomposition, Change Detection, Counterfactual — parallel)
- Phase 3: Debate (Debate Moderator with AGREE/DISAGREE/EXTEND)
- Phase 4: Validate (independent re-derivation)
- Phase 5: Synthesize (root cause narrative + recommendations)
- Phase 6: Review (connects to existing multi-agent review system)

**Key differences from Shane's system:**
1. Hypothesis space is constrained (known taxonomy of failure modes per pipeline stage)
2. Debate phase matters more (misattributing root cause → wrong fix → metric stays broken)
3. Review system is load-bearing quality gate, not cosmetic

**Practical sequencing:**
- Phase 1: Triage + Hypothesis Generator (2 API calls, immediately useful)
- Phase 2: Add Debate phase (triples calls but quality jump)
- Phase 3: Full pipeline with review system

---

## Turn 5: Domain Knowledge Integration Question

**User:** "Assuming if I built domain knowledge skill, how to integrate into this framework?"

---

## Turn 6: Claude's Domain Knowledge Integration Design

### Integration Architecture

Domain Knowledge plays four distinct roles across the pipeline:
1. **Narrowing** (Phase 0) — reduces hypothesis space
2. **Grounding** (Phase 1-2) — forces claims based on actual system state
3. **Validating** (Phase 3) — confirms/rejects root cause against known facts
4. **Routing** (Phase 4) — ensures recommendations reach right people

### Context Assembly at Each Phase

**Phase 0: Triage** (heaviest usage, ~20k tokens)
- Full domain load for primary stage + Third-Party Connector (always)
- Narrows from "anything could have happened" to "here's what actually changed"

**Phase 1: Independent Hypotheses** (filtered, ~15k tokens)
- Each specialist gets only their relevant domain slice
- Domain Knowledge Skill acts as router

**Phase 2: Investigation** (reference, ~6k tokens)
- Supports decomposition with metric relationships

**Phase 3: Cross-Examination** (on-demand, ~6k tokens)
- Specialists request specific domain facts to support challenges
- Moderator verifies claims against Domain Knowledge Skill

**Phase 4: Validation** (cross-reference, ~3k tokens)
- Checks timeline, segment, and magnitude consistency

**Phase 5: Synthesis** (light touch, ~1.5k tokens)
- Ownership routing for recommendations

### Loading Strategy Decision

**Option A (Always-Load):** For Third-Party Connector — too volatile to skip, cost of missing a change is asymmetric.

**Option B (Demand-Driven):** For stable areas (QU, Retrieval, Ranking, Interleaver, Search Experience) — load only when triage identifies as relevant.

### Total Token Budget: ~51,500 tokens

Well within 200k context window, leaving room for metric data, agent reasoning, and analysis output.

### Injection Mechanism

Each agent's execution starts with:
1. Pipeline stage identified (from Phase 0 triage)
2. Domain Knowledge Skill triggers
3. Assembles relevant context slice (layer + time window + budget)
4. Context injected as "Domain Briefing" section
5. Agent executes with domain-aware context

---

## Turn 7: User Approves and Requests Spec Files

**User:** "I agree with your judgement, you can continue writing the Md file"

---

## Turn 8: Claude Creates Full Spec Files

Created 10 markdown files in a project structure:

### Files Created

**CLAUDE.md** — System orchestrator
- Who You Are, What You Do, What You Don't Do
- Skills table (5 skills with triggers)
- Agents table (10 agents with invocations)
- Default Workflow (7-step pipeline)
- Rules (8 non-negotiable rules)

**skills/domain-knowledge/SKILL.md** — Core integration layer
- Three-layer architecture (Knowledge Base, Domain Expert Reviewer, Lead Agent Integration)
- Context Assembly Protocol (4 steps: identify stages, apply loading strategy, apply token budgets, assemble briefing)
- Integration points for each of 8 agents with specific sections loaded and token budgets
- Knowledge Maintenance (automated updates, manual curation, bootstrap strategy)
- Anti-patterns (5 things to avoid)

**skills/validation-rules/SKILL.md** — Quality gates
- 7 checks: Simpson's Paradox, Segment Mix Shift, Logging Artifact, Decomposition Completeness, Temporal Consistency, Magnitude Plausibility, Co-Movement Consistency
- Severity levels: HALT, INVESTIGATE, NOTE
- Integration with Domain Knowledge Skill

**skills/communication-standards/SKILL.md** — Output quality
- TL;DR mandatory and first
- Actionable recommendations (7 required fields per recommendation)
- Confidence calibration (High/Medium/Low with explicit criteria)
- Audience awareness (4 audience levels)
- Reactive analysis communication guidance
- 5 anti-patterns

**skills/decomposition-patterns/SKILL.md** — Metric decomposition trees
- Core decomposition formula (rate change vs. mix shift)
- 4 decomposition trees: Search CTR (7 levels), Query Success Rate (5 levels), Latency (4 levels), Impressions (4 levels)
- Depth control: shallow/standard/deep
- "Biggest mover first" heuristic

**agents/debug-architect.md** — Main orchestrator
- Parameters: metric, --pipeline-stage, --personas, --skip-debate, --depth, --output-dir
- Full 6-phase execution spec with checkpoints at each phase
- Persona selection rules (6 metric categories → recommended personas)
- Phase 5 output structure (TL;DR, What Happened, Why, Confidence, Recommendations, Appendix)
- Phase 6 three-dimensional review (33/33/33 scoring)
- Cost management table (Quick/Standard/Full/Deep modes)

**agents/metric-intake.md** — Phase 0 triage
- 5-step process: parse, classify by pipeline stage, identify co-movements, load domain context, select personas
- Pipeline stage mapping table (8 metric categories)
- Co-movement checklist format
- Standalone usage mode with Quick Assessment

**agents/hypothesis-generator.md** — Phase 1 hypotheses
- 5 hypothesis categories with investigation priority order
- Full hypothesis schema (id, statement, category, domain grounding, expected signature, evidence needed, confidence, effort)
- Quality gates (rejection criteria + strength signals)
- Per-persona execution steps

**agents/debate-moderator.md** — Phase 3 debate
- Round 1: Annotation protocol (AGREE/DISAGREE/EXTEND with evidence requirements)
- 5 annotation rules
- Domain fact verification mechanism (confirmed/partially correct/not found/contradicted)
- Round 2: Conflict resolution with 6 priority rules
- Halting conditions (INCONCLUSIVE, CONFLICTING EVIDENCE, KNOWLEDGE BASE STALENESS)
- Cost management guidance by scenario

**README.md** — Project overview
- Architecture diagram
- What's built vs. TODO
- Key design decisions
- Implementation priorities
- Relationship to existing review system

---

## Turn 9: User Requests Single File

**User:** "can you make as 1 Md file?"

---

## Turn 10: Claude Creates Consolidated File

Created `search-metric-debug-system.md` — single file with 4 parts:
- Part 1: System Orchestrator
- Part 2: Skills (all 4 complete skills)
- Part 3: Agents (all 4 complete agents)
- Part 4: Next Steps and implementation priorities

---

## Turn 11: User Requests Session Log

**User:** "can you also save this session's full chat record into a .md file?"

---

## Key Decisions Made in This Session

1. **Adopted Shane Butler's Skills vs Agents pattern** — Skills are always-active standards, Agents are invoked workflows
2. **Domain Knowledge uses hybrid loading** — Always-load for Third-Party Connector, demand-driven for stable areas
3. **Debate phase is optional but powerful** — `--skip-debate` for cost management, mandatory for P0 drops or conflicting hypotheses
4. **Hypothesis ordering follows an instrumentation-first principle** — Logging bugs are cheap to verify and expensive to miss
5. **Communication standards encode existing principles** — "A number without decision context is trivia"
6. **Token budget of ~51.5k** for domain knowledge across the full pipeline, fitting within 200k context window
7. **Three-dimensional review scoring (33/33/33)** connects to existing multi-agent review system
8. **Recommended starting with Third-Party Connector knowledge** as first domain file to populate, then testing against a real historical metric drop

## References

- Shane Butler's LinkedIn post (screenshot, Feb 21 2026)
- Shane Butler's `/architect` skill screenshot (VS Code)
- [Shane Butler's blog: "Will Claude Code + Opus 4.6 Replace Your Data Team?"](https://aianalystlab.ai/blog/ai-analyst-pipeline-tutorial/)
- Sarah's existing DS Analysis Review Agent (MVP 1.0)
- Sarah's Domain Knowledge Skill system (in development)
- Sarah's multi-agent Search debugging spec (inspired by Shane Butler's debate methodology)
