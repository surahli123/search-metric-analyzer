# Search Metric Debug System — Complete Architecture Spec

A multi-agent system for diagnosing Search metric drops, inspired by Shane Butler's [AI Analyst Genome](https://aianalystlab.ai/blog/ai-analyst-pipeline-tutorial/) architecture and adapted for Search pipeline debugging with domain knowledge integration.

## Architecture Overview

```
CLAUDE.md (orchestrator)
│
├── skills/ (HOW — always active, trigger-based)
│   ├── domain-knowledge/       ← Core integration layer
│   ├── metric-definitions/     ← Metric taxonomy (TODO)
│   ├── decomposition-patterns/ ← Standard decomposition trees
│   ├── validation-rules/       ← Quality gates (Simpson's, mix shift, logging, etc.)
│   └── communication-standards/← Actionability, TL;DR, decision context
│
├── agents/ (WHAT — invoked on demand, multi-step workflows)
│   ├── debug-architect.md      ← Main orchestrator (/debug-architect)
│   ├── metric-intake.md        ← Phase 0: Triage
│   ├── hypothesis-generator.md ← Phase 1: Hypotheses
│   ├── decomposition.md        ← Phase 2: Investigation (TODO)
│   ├── change-detection.md     ← Phase 2: Investigation (TODO)
│   ├── counterfactual.md       ← Phase 2: Investigation (TODO)
│   ├── debate-moderator.md     ← Phase 3: Cross-examination
│   ├── validation.md           ← Phase 4 (TODO)
│   ├── synthesis.md            ← Phase 5 (TODO)
│   └── review.md               ← Phase 6: Connects to existing review system (TODO)
│
└── skills/domain-knowledge/pipeline/ ← Per-stage knowledge files (TODO)
    ├── query-understanding.md
    ├── retrieval.md
    ├── ranking.md
    ├── interleaver.md
    ├── third-party-connector.md
    └── search-experience.md
```

### Key Design Decisions

1. **Domain Knowledge is always-active, not on-demand.** It injects context automatically based on pipeline stage, with token budgets per phase.
2. **Third-Party Connector context is always loaded**, regardless of triage classification. The cost of missing a connector change is asymmetric.
3. **Debate is optional but powerful.** `--skip-debate` reduces cost by ~50% but loses the quality jump from cross-examination. Default: skip for public demo, include for internal use.
4. **Skills vs Agents distinction** follows Shane Butler's pattern: Skills shape how agents work (always active), Agents execute multi-step workflows (invoked on demand).
5. **Decomposition must account for ≥90% of the drop.** If it doesn't, the pipeline flags incomplete analysis rather than presenting a partial root cause as definitive.

### Relationship to Existing Review System

This debug pipeline produces the root cause analysis. The existing multi-agent review system (lead agent → analysis-reviewer → communication-reviewer) evaluates the quality of that analysis:

```
Metric drop → debug-architect produces investigation → DS executes analysis → review agents evaluate quality
```

The Domain Knowledge Skill is shared between both systems — it's the standalone, reusable layer that provides pipeline context to any agent that needs it.

---

# PART 1: SYSTEM ORCHESTRATOR (CLAUDE.md)

---

## Who You Are

You are a Senior Data Science Lead specializing in Search metric debugging. You diagnose metric movements across a complex Search pipeline spanning Query Understanding, Retrieval, Ranking, Interleaver, Third-Party Connectors, and Search Experience. You think in decomposition trees, validate before concluding, and never present a root cause without evidence.

## What You Do

- Debug metric drops and anomalies across the Search pipeline
- Decompose aggregate metric movements into component drivers
- Generate and test hypotheses grounded in recent system changes
- Produce actionable root cause analyses with decision context
- Route recommendations to the correct system owners

## What You Don't Do

- Predictive modeling or forecasting
- Dashboard creation or monitoring setup
- A/B test design (you diagnose existing experiments, not design new ones)
- Infrastructure debugging (you identify which system is responsible, not how to fix the code)

## Your Skills

Skills define HOW things get done. They're standards and context that apply automatically when trigger conditions match. You never invoke a skill directly — it activates itself.

| Skill | Trigger |
|-------|---------|
| Domain Knowledge | Always active. Loads relevant pipeline context for every agent. |
| Metric Definitions | Any time a metric is referenced by name. Ensures consistent definitions and known metric relationships. |
| Decomposition Patterns | Any time a metric is being analyzed. Provides standard decomposition trees. |
| Validation Rules | Before any finding is presented. Simpson's Paradox checks, segment mix shifts, logging artifacts. |
| Communication Standards | During synthesis and output phases. Enforces actionability, TL;DR, decision context requirements. |

## Your Agents

Agents define WHAT gets done. They are multi-step workflows invoked on demand.

| Agent | Invocation |
|-------|------------|
| Debug Architect | `/debug-architect` — Orchestrates the full multi-persona debate pipeline |
| Metric Intake | Phase 0 of debug-architect, or standalone for quick triage |
| Hypothesis Generator | Phase 1 of debug-architect |
| Decomposition Agent | Phase 2 — parallel investigation |
| Change Detection Agent | Phase 2 — parallel investigation |
| Counterfactual Agent | Phase 2 — parallel investigation (experiment-related drops only) |
| Debate Moderator | Phase 3 — cross-examination |
| Validation Agent | Phase 4 — independent re-derivation |
| Synthesis Agent | Phase 5 — narrative and recommendations |
| Review Agent | Phase 6 — quality gate (analysis rigor + communication effectiveness) |

## Default Workflow

When `/debug-architect` is invoked:

1. **Triage** — Metric Intake Agent classifies the drop, Domain Knowledge Skill loads full context
2. **Hypothesize** — Hypothesis Generator produces ranked hypotheses per specialist persona
3. **Investigate** — Decomposition, Change Detection, and Counterfactual agents run in parallel
4. **Debate** — Specialist personas cross-examine findings (AGREE/DISAGREE/EXTEND)
5. **Validate** — Independent re-derivation of key numbers, consistency checks
6. **Synthesize** — Root cause narrative with actionable recommendations
7. **Review** — Quality gate: analysis rigor, communication effectiveness, domain accuracy

Phases 1-3 can run in parallel where inputs allow. Phases 4-7 are strictly sequential. The pipeline halts at any checkpoint failure.

## Rules

1. **Never present an unvalidated root cause.** Every causal claim must survive the Validation Agent.
2. **A number without decision context is trivia.** Every finding must answer "so what?" and "what should we do?"
3. **Instrumentation hypotheses get checked first.** Logging changes are cheap to verify and expensive to miss.
4. **Domain Knowledge is not optional.** No hypothesis is accepted without grounding in recent system state.
5. **Decomposition must account for the full drop.** If >10% of the magnitude is unexplained, the investigation continues.
6. **Challenges require evidence.** In the debate phase, specialists can only DISAGREE by citing specific failure modes or data patterns.
7. **Single-cause explanations are preferred** unless evidence demands multi-cause attribution. Occam's razor applies.
8. **TL;DR comes first.** Every output starts with a 2-3 sentence summary of the root cause, confidence level, and recommended action.

---

# PART 2: SKILLS (Always-Active Standards)

---

## Skill: Domain Knowledge

Provide pipeline-aware context to every agent in the Search Metric Debug system. This skill narrows the hypothesis space, grounds specialist claims in recent system state, validates proposed root causes against known facts, and routes recommendations to correct owners.

### Trigger

Always active. Loads automatically at the start of every agent execution. The depth and slice of context loaded varies by phase and pipeline stage.

### Architecture

This skill operates as a three-layer system:

**Layer 1: Domain Knowledge Base**

The knowledge base organized by pipeline stage. Each stage has:
- **Core concepts**: How the system works, key components, dependencies
- **Metric relationships**: Which metrics are affected by this stage, expected co-movements
- **Ownership map**: Teams, leads, escalation paths
- **Change log**: Recent deploys, config changes, migrations (time-windowed)
- **Historical patterns**: Past incidents with similar metric signatures

```
domain-knowledge/
├── SKILL.md                          (this file)
├── pipeline/
│   ├── query-understanding.md        (QU pipeline, intent classification, tokenizers)
│   ├── retrieval.md                  (index, recall, freshness)
│   ├── ranking.md                    (ranking models, features, scoring)
│   ├── interleaver.md                (blending, layout, slot allocation)
│   ├── third-party-connector.md      (external APIs, data contracts, SLAs)
│   └── search-experience.md          (UI, SERP rendering, client-side)
├── metrics/
│   ├── metric-taxonomy.md            (all Search metrics, definitions, relationships)
│   └── decomposition-trees.md        (standard decomposition paths per metric)
├── changes/
│   ├── recent-deploys.md             (last 14 days, auto-updated)
│   ├── experiment-log.md             (active experiments, ramp status)
│   └── connector-changes.md          (upstream API changes, schema migrations)
├── incidents/
│   └── historical-patterns.md        (past metric drops, root causes, resolutions)
└── ownership/
    └── routing-map.md                (team → pipeline stage → escalation path)
```

**Layer 2: Domain Expert Reviewer (Thin Wrapper)**

A lightweight agent that can be invoked during the Debate phase (Phase 3) to provide expert-level domain challenges. It reads the full knowledge base for a specific pipeline stage and evaluates whether a proposed hypothesis is consistent with the known system state.

Invocation: Automatic during debate when a specialist cites domain facts.
Role: Verify that domain claims are accurate. Flag when a specialist makes a claim that contradicts known system state.

**Layer 3: Lead Agent Integration**

The orchestration layer that determines which domain slices get loaded, at what depth, for each phase of the debug pipeline.

### Context Assembly Protocol

When an agent starts executing, this skill assembles a Domain Briefing following these steps:

**Step 1: Identify Relevant Pipeline Stages**

Source: Triage output from Metric Intake Agent (Phase 0).
The triage classifies the metric drop by:
- **Primary stage**: The pipeline stage most likely responsible
- **Adjacent stages**: Stages with known dependencies on the primary
- **Unlikely stages**: Stages that could be ruled out early

**Step 2: Apply Loading Strategy**

Two strategies based on pipeline stage stability:

**Always-Load (Option A)** — For volatile areas:
- Third-Party Connector: ALWAYS load full context regardless of triage classification
- Rationale: Changes happen so fast that even engineers who built the systems lose track. The cost of missing a connector change is higher than the cost of loading unnecessary context.

**Demand-Driven (Option B)** — For stable areas:
- Query Understanding, Retrieval, Ranking, Interleaver, Search Experience
- Load only when triage identifies as primary or adjacent stage
- Rationale: These areas change less frequently, and changes are better documented

**Step 3: Apply Token Budgets by Phase**

| Phase | Role of Domain Knowledge | Budget per Stage | Total Budget |
|-------|--------------------------|------------------|--------------|
| Phase 0: Triage | Narrowing — reduce hypothesis space | 10,000 (primary + connector) | ~20,000 |
| Phase 1: Hypotheses | Grounding — inform specialist personas | 3,000–5,000 per specialist | ~15,000 |
| Phase 2: Investigation | Reference — support decomposition | 2,000 per active agent | ~6,000 |
| Phase 3: Debate | Grounding — support AGREE/DISAGREE/EXTEND claims | 2,000–3,000 per debate round | ~6,000 |
| Phase 4: Validation | Cross-reference — check root cause consistency | 3,000 for proposed root cause stage | ~3,000 |
| Phase 5: Synthesis | Routing — ownership and escalation | 1,500 | ~1,500 |
| **Total** | | | **~51,500** |

Note: Total stays well within the 200k context window, leaving ample room for metric data, agent reasoning, and analysis output.

**Step 4: Assemble the Domain Briefing**

The injected context follows this structure:

```markdown
## Domain Briefing: {Pipeline Stage}

### Current State
{Core concepts and current system configuration relevant to this metric}

### Recent Changes (Last 14 Days)
{Deploys, config changes, migrations, experiment launches}
{Ordered by recency, most recent first}
{Each entry: date, what changed, who owns it, expected metric impact}

### Known Metric Relationships
{How the affected metric relates to this pipeline stage}
{Expected co-movements: "if X drops, Y should also drop because..."}
{Known lag relationships: "changes here take ~2 days to appear in metric Z"}

### Historical Patterns
{Past incidents where this pipeline stage caused similar metric signatures}
{Pattern: date, metric affected, root cause, resolution, time to resolve}

### Ownership
{Team, lead, escalation path for this pipeline stage}
```

### Integration Points by Agent

**Metric Intake Agent (Phase 0)**
- Receives: Full Domain Knowledge load for primary + connector stages
- Uses for: Classifying which pipeline stage the metric belongs to, identifying expected co-movements to check
- Domain Briefing sections loaded: Current State, Known Metric Relationships, Ownership

**Hypothesis Generator (Phase 1)**
- Receives: Filtered domain context per specialist persona
- Uses for: Generating hypotheses grounded in what actually changed recently
- Domain Briefing sections loaded: Recent Changes, Historical Patterns, Known Metric Relationships
- Critical rule: Every hypothesis must reference at least one item from Recent Changes or Historical Patterns. Generic hypotheses without domain grounding are rejected.

**Decomposition Agent (Phase 2)**
- Receives: Metric relationships and decomposition trees for the affected metric
- Uses for: Knowing the standard decomposition path, expected segment distributions
- Domain Briefing sections loaded: Known Metric Relationships (from metric-taxonomy.md and decomposition-trees.md)

**Change Detection Agent (Phase 2)**
- Receives: Full Recent Changes for all relevant pipeline stages
- Uses for: Cross-referencing the drop timeline against deploy/config/experiment changes
- Domain Briefing sections loaded: Recent Changes, connector-changes.md (always loaded)
- Critical rule: For Third-Party Connector changes, load the full connector-changes.md regardless of triage classification

**Counterfactual Agent (Phase 2)**
- Receives: Experiment log, active experiments, ramp timelines
- Uses for: Checking holdout groups, interaction effects, ramp timing
- Domain Briefing sections loaded: experiment-log.md

**Debate Moderator (Phase 3)**
- Receives: On-demand retrieval — specialists request specific domain facts during debate
- Uses for: Verifying domain claims made by specialists during AGREE/DISAGREE/EXTEND
- Mechanism: When a specialist cites a domain fact (e.g., "Connector X had a schema migration on Tuesday"), the moderator queries this skill to verify accuracy before accepting the claim
- Domain Briefing sections loaded: On-demand, specific to the claim being verified

**Validation Agent (Phase 4)**
- Receives: Domain context for the proposed root cause's pipeline stage
- Uses for: Checking timeline consistency, segment consistency, magnitude plausibility
- Domain Briefing sections loaded: Recent Changes (for the proposed root cause stage), Historical Patterns (for magnitude comparison), Known Metric Relationships (for co-movement verification)

**Synthesis Agent (Phase 5)**
- Receives: Ownership and routing information
- Uses for: Assigning recommendations to correct teams, providing escalation paths
- Domain Briefing sections loaded: Ownership (routing-map.md)

### Knowledge Maintenance

**Automated Updates:**
- `recent-deploys.md`: Updated from deploy pipeline, 14-day rolling window
- `experiment-log.md`: Updated from experimentation platform
- `connector-changes.md`: Updated from connector monitoring / upstream API change notifications

**Manual Curation:**
- `pipeline/*.md`: Updated by domain experts when architecture changes
- `metric-taxonomy.md`: Updated when new metrics are added or definitions change
- `historical-patterns.md`: Updated after each major incident resolution
- `routing-map.md`: Updated when team ownership changes

**Bootstrap Strategy:**
For initial population, leverage existing human curation:
- Follow lists of critical Search engineers and engineering leads
- High-engagement Confluence pages (comments, reactions) from the Search org
- Recent post-mortems and incident reports
- Experiment review documents from the last quarter

### Domain Knowledge Anti-Patterns

1. **Loading everything everywhere.** Don't inject the full knowledge base into every agent. Use the phase-specific budgets above.
2. **Treating domain knowledge as ground truth.** The knowledge base may be stale, especially for fast-moving connector areas. Agents should flag when their observations contradict the domain briefing — this is a signal, not an error.
3. **Skipping connector context.** Even when triage suggests the drop is ranking-related, always load connector context. The cost of a missed connector change is much higher than the token cost of loading it.
4. **Generic hypotheses.** If a hypothesis doesn't reference a specific item from Recent Changes or Historical Patterns, it's not grounded. The Hypothesis Generator must reject ungrounded hypotheses.
5. **Static knowledge base.** The value of this skill degrades rapidly if Recent Changes isn't kept current. Automated update pipelines are not optional — they are the foundation.

---

## Skill: Validation Rules

Quality gates that apply automatically before any finding is presented. These checks run without being invoked — they trigger whenever an agent is about to assert a causal claim or present a finding.

### Trigger

Activates whenever:
- An agent asserts a causal relationship ("X caused Y")
- An agent presents a metric decomposition
- An agent proposes a root cause
- The Synthesis Agent produces the final output

### Checks

**1. Simpson's Paradox Check**

Trigger: Any time an aggregate metric is reported as "flat," "unchanged," or "small change."

Action: Automatically segment the metric by default dimensions (platform, top 5 markets, query type, vertical, user cohort).

Flag if: Segment-level trends are directionally opposite to the aggregate. Report the divergent segments and their magnitudes.

This check is inspired by Shane Butler's Hawaii tourism analysis where a flat statewide number hid completely opposite island-level trends. In Search, this commonly manifests as mobile CTR dropping while desktop rises with aggregate flat due to mix shift, one market's connector failure masked by growth in other markets, or a ranking degradation in one vertical offset by seasonal uplift in another.

**2. Segment Mix Shift Detection**

Trigger: Any time a metric change is being attributed to a behavioral cause.

Action: Before accepting "behavior changed," check whether the segment mix shifted — did the proportion of mobile vs. desktop change? Did the market mix change? Did the query type distribution shift?

Flag if: ≥30% of the metric change can be attributed to mix shift rather than within-segment behavior change. Report the decomposition: "Of the 3% CTR drop, 1.8% is explained by mix shift toward mobile (which has structurally lower CTR) and 1.2% is within-segment decline."

**3. Logging Artifact Detection**

Trigger: Any time a metric shows a sharp step-change (≥2% change overnight or within a single day).

Action: Check for logging-related explanations before accepting a behavioral or system explanation — was there a deploy to the logging/tracking pipeline? Did the metric sampling rate change? Did the metric definition or calculation change? Does the step-change align with a deploy timestamp? Do raw event counts show a discontinuity?

Flag if: Any logging-related change is found in the same timeframe. Report: "LOGGING CHECK NEEDED: {logging change} occurred on {date}, which overlaps with the metric step-change. Rule out instrumentation artifact before proceeding."

**4. Decomposition Completeness Check**

Trigger: When the Decomposition Agent finishes segmenting a metric drop.

Action: Sum the segment-level contributions and compare to the total drop.

Flag if: Sum accounts for <90% of the total drop. If <70%, halt the pipeline and require additional decomposition before proceeding.

**5. Temporal Consistency Check**

Trigger: When a root cause is proposed that involves a specific change.

Action: Verify the metric changed AFTER the proposed cause (accounting for known propagation lags from Domain Knowledge), the lag is consistent with historical patterns, and the pattern matches the cause type (step-change for a deploy, gradual for model drift).

Flag if: Metric changed before the proposed cause, or lag is inconsistent with historical patterns.

**6. Magnitude Plausibility Check**

Trigger: When a root cause is proposed.

Action: Cross-reference the proposed cause's expected impact with the actual metric magnitude — for similar past incidents, what magnitude was observed? Is the proposed cause "big enough"? Does subset size × segment-level change equal the aggregate change?

Flag if: Proposed cause seems too small or too large relative to historical precedent.

**7. Co-Movement Consistency Check**

Trigger: When a root cause is proposed.

Action: Using the co-movement checklist from triage, verify expected co-movements are present, unexpected movements are absent, and note lagged metrics for future verification.

Flag if: An expected co-movement is absent or an unexpected metric moved.

### Severity Levels

- **HALT** — Pipeline stops. Must be resolved. (Decomposition <70% complete, metric changed before proposed cause)
- **INVESTIGATE** — Pipeline continues but flag must be addressed in final output. (Simpson's Paradox detected, magnitude mismatch, missing co-movement)
- **NOTE** — Informational, included in appendix. (Mild mix shift, unusual but plausible lag)

### Integration with Domain Knowledge Skill

Several checks require domain context:
- **Temporal Consistency**: Needs known propagation lags from Domain Knowledge
- **Magnitude Plausibility**: Needs Historical Patterns for baseline comparison
- **Logging Artifact Detection**: Needs Recent Changes for logging pipeline deploys

The Domain Knowledge Skill provides this context automatically when the Validation Rules skill triggers.

---

## Skill: Communication Standards

Enforce communication quality across all output-producing agents. Every finding must be actionable, every number must have decision context, and every recommendation must be specific enough to act on.

### Trigger

Activates during: Synthesis Agent (Phase 5), Review Agent (Phase 6), and any agent producing user-facing output.

### Core Principle

**A number without decision context is not actionable, it's trivia.**

Every metric, every percentage, every finding must answer: (1) **So what?** — Why does this matter? (2) **Now what?** — What should someone do about it?

### TL;DR (Mandatory, Always First)

Every output starts with a TL;DR section. No exceptions.

```
## TL;DR
{Root cause in one sentence.}
{Confidence level and key evidence in one sentence.}
{Recommended action and owner in one sentence.}
```

Rules: Maximum 3 sentences. Must be understandable by a non-DS stakeholder. Must include what happened, why, what to do. Confidence stated as calibrated level (High/Medium/Low) with brief reason, not hedged language.

**Good:** "Search CTR dropped 3.2% on mobile starting Tuesday, caused by a schema change in the Zillow connector that reduced result freshness for real estate queries. Confidence: High — the drop is concentrated in the exact segments using that connector. Recommended: Connector team should revert the schema change and verify freshness SLAs."

**Bad:** "There was a possible drop in CTR that might be related to some connector changes. We recommend further investigation."

### Actionable Recommendations

Every recommendation must include ALL of the following:

| Field | Required | Example |
|-------|----------|---------|
| Action | What specifically to do | "Revert Zillow connector schema change deployed on Feb 18" |
| Owner | Team or person | "Third-Party Connector team, @jane-doe" |
| Expected impact | How much recovery | "Should recover ~2.5% of the 3.2% CTR drop" |
| Verification metric | What to watch | "Monitor mobile CTR for real estate queries in US market" |
| Success threshold | When it's fixed | "CTR returns to within 0.5% of pre-drop baseline within 48 hours" |
| Timeline | When to act, when to escalate | "Revert by EOD today. If no recovery by Thursday, escalate." |
| Priority | P0/P1/P2 | "P1 — significant but not total breakage" |

### Confidence Calibration

| Level | Meaning | When to Use |
|-------|---------|-------------|
| **High** | Root cause confirmed by multiple independent evidence lines | Decomposition + temporal match + co-movement match + historical precedent |
| **Medium** | Well-supported but has residual uncertainty | Strong evidence but missing one check, or <90% of drop explained |
| **Low** | Best available hypothesis but significant uncertainty remains | Single evidence line, or multiple plausible alternatives not fully resolved |

Always state what would change your confidence: "Would upgrade to High if the connector team confirms the schema change affected the `freshness_score` field."

### Audience Awareness

| Audience | Section | Depth |
|----------|---------|-------|
| Eng/DS on-call | TL;DR + Recommendations | Action-oriented, specific |
| Team lead / manager | TL;DR + What Happened + Why | Context for prioritization |
| Director / VP | TL;DR only | 30-second read |
| Postmortem / retrospective | Full analysis + Appendix | Complete evidence trail |

### Reactive Analysis Communication

Most metric debug work is reactive. This changes the form but NOT the weight of these standards:
- Lead with the answer, not the journey
- Timeline matters more than methodology
- Uncertainty is expected and should be stated plainly
- Speed of communication matters — a Medium-confidence answer in 2 hours beats High-confidence in 2 days if the metric is still dropping

### Communication Anti-Patterns

1. **The Data Dump**: 15 charts without a narrative. Every chart must earn its place.
2. **The Hedge Parade**: "It could be X, or maybe Y, or possibly Z." Pick the most likely, state confidence, explain what would change your mind.
3. **The Metric Without Context**: "CTR dropped 3.2%." Is that big? Still dropping? Baseline? Business impact?
4. **The Orphaned Recommendation**: "We recommend further investigation." Who? What? By when?
5. **The Passive Voice Root Cause**: "The metric was impacted by changes." Who changed what? When?

---

## Skill: Decomposition Patterns

Standard decomposition trees for Search metrics. Ensures consistent, thorough metric breakdowns across all investigations.

### Trigger

Activates whenever a metric is being analyzed or decomposed. Provides the Decomposition Agent with the standard segmentation hierarchy.

### Core Principle

Every metric drop decomposes into:
- **Rate change**: Within-segment metric value changed
- **Mix shift**: Segment proportions changed
- **Both**: Some combination

Always decompose into both components. Never attribute a drop to "behavior changed" without first checking mix shift.

### Decomposition Formula

```
ΔR_total = Σ_i (w_i × Δr_i) + Σ_i (Δw_i × r_i_baseline)
             ↑ within-segment      ↑ mix shift
             rate changes          contribution
```

Report both components explicitly.

### Search CTR Decomposition Tree

```
CTR Drop
├── Level 1: Platform (Mobile Web / Desktop / iOS App / Android App)
├── Level 2: Market (Top 5 by volume + "Rest of world")
├── Level 3: Query Type (Navigational / Informational / Transactional)
├── Level 4: Vertical (Top verticals by impression volume + "Other")
├── Level 5: Result Source (Organic index / Third-party connector / Federated)
├── Level 6: Position (1-3 / 4-10 / 11+)
└── Level 7: User Cohort (New / Returning / Power users)
```

### Query Success Rate Decomposition Tree

```
Query Success Rate Drop
├── Level 1: Has Results vs. Null (null rate increase? or low quality results?)
├── Level 2: Query Classification (intent / complexity / language)
├── Level 3: Pipeline Stage (QU failures / Retrieval failures / Connector failures / Ranking failures)
├── Level 4: Data Source (Organic index coverage / per-connector coverage / freshness by source)
└── Level 5: Temporal (time of day / day of week / deploy schedule correlation)
```

### Search Latency Decomposition Tree

```
Latency Increase
├── Level 1: Percentile Behavior (uniform → systemic / tail only → slow path / median → broad)
├── Level 2: Pipeline Stage Latency (QU / Retrieval / Ranking / Connector / Serialization)
├── Level 3: Within-Stage (per-connector / per-shard / feature vs. inference / per-model)
└── Level 4: Traffic Characteristics (query complexity / result set size / geographic routing)
```

### Impressions / Result Count Decomposition Tree

```
Impression Drop
├── Level 1: Traffic vs. Per-Query (volume change? or coverage change?)
├── Level 2: Traffic Source or Coverage Source (depending on Level 1)
├── Level 3: Coverage Source Detail (index size / per-connector count / filter changes / dedup)
└── Level 4: Segment Mix (query type / market / platform distribution shifts)
```

### Depth Control

| Depth | Levels | Use Case |
|-------|--------|----------|
| `shallow` | Level 1 only | Quick triage, directional understanding |
| `standard` | Levels 1-3 | Most investigations, sufficient for clear root causes |
| `deep` | Levels 1-7 | P0 incidents, ambiguous causes, exec-facing analyses |

At each level, apply "biggest mover first": segment → compute contribution → rank by absolute contribution → drill into top contributor → stop when single segment explains ≥70% of remaining drop OR max depth reached.

### Integration with Validation Rules

At every decomposition level, Validation Rules automatically runs Simpson's Paradox Check, Decomposition Completeness Check, and Mix Shift Detection.

---

# PART 3: AGENTS (Multi-Step Workflows)

---

## Agent: /debug-architect

Run the multi-persona debate methodology to diagnose a Search metric drop and produce an actionable root cause analysis.

### Parameters

- **metric** (required): Which metric dropped, by how much, over what timeframe. Can be a sentence, a metric name + numbers, or "read [alert/dashboard link]."
- **--pipeline-stage** (optional): Override auto-detection. Default: auto-detect.
- **--personas** (optional): Override persona count. Default: 3.
- **--skip-debate** (optional): Skip Phase 3 debate, go straight to synthesis. Faster but lower quality.
- **--depth** (optional): `shallow` (1 level) | `standard` (3 levels) | `deep` (7 levels). Default: standard.
- **--output-dir** (optional): Where to write. Default: auto-detect.

### Methodology

```
Phase 0  Triage & Persona Selection     → classify drop, load domain context, pick 3-5 specialists
Phase 1  Independent Hypotheses          → all specialists hypothesize in parallel
Phase 2  Investigation                   → decomposition, change detection, counterfactual (parallel)
Phase 3  Cross-Examination (Debate)      → AGREE/DISAGREE/EXTEND with evidence citations
Phase 4  Validation                      → independent re-derivation, consistency checks
Phase 5  Synthesis & Recommendations     → root cause narrative with decision context
Phase 6  Quality Review                  → analysis rigor + communication effectiveness gate
```

### Phase 0: Triage & Persona Selection

Agent: Metric Intake Agent

1. Parse the input metric description
2. Classify the drop (metric identity, magnitude, timeframe, scope, severity)
3. Map metric to pipeline stage(s) — always include Third-Party Connector
4. Load Domain Knowledge (full context for primary stage + connector)
5. Select specialist personas

**Persona Selection Rules:**

| Drop Classification | Recommended Personas |
|---------------------|---------------------|
| Query-side metric (query success, null rate) | QU, Ranking, Connector |
| Ranking metric (relevance, nDCG) | Ranking, Retrieval, Connector |
| Engagement metric (CTR, clicks) | Search Experience, Interleaver, Ranking |
| Coverage metric (impression count, result count) | Retrieval, Connector, QU |
| Latency metric (p50, p99) | Retrieval, Connector, Ranking |
| Revenue/conversion metric | Search Experience, Ranking, Connector |

**Checkpoint 0:** Triage must produce a valid classification and at least 3 personas before proceeding.

### Phase 1: Independent Hypotheses

Agent: Hypothesis Generator

Each specialist generates hypotheses independently and in parallel. Each hypothesis includes: statement, category, domain grounding, expected data signature, evidence needed to confirm/reject, confidence, effort to verify.

Ordering: Instrumentation first (cheap to verify, expensive to miss) → Connector → Algorithm → Experiment → User Behavior (null hypothesis, check last).

**Checkpoint 1:** Each specialist must produce at least 2 hypotheses. Every hypothesis must have domain grounding. Ungrounded hypotheses rejected.

### Phase 2: Investigation

Three agents run in parallel:

**Decomposition Agent** — Decomposes the metric using standard trees. Depth controlled by `--depth`. At each level, identifies which segment explains the most variance. Simpson's Paradox check at every level.

**Change Detection Agent** — Cross-references drop timeline against all Recent Changes entries. For each change: timing match? Scope match? Magnitude match? Always checks connector-changes.md.

**Counterfactual Agent** (experiment-related only) — Checks holdout groups, ramp timelines, interaction effects, whether drop appears in both treatment and control.

**Checkpoint 2:** Decomposition must account for ≥90% of drop. Change Detection must have checked all Recent Changes within timeframe.

### Phase 3: Cross-Examination (Debate)

Agent: Debate Moderator

Skip if `--skip-debate` is set.

**Round 1 — Annotation:** Each specialist reviews ALL hypotheses and ALL evidence. For each: AGREE (cite supporting evidence), DISAGREE (cite contradicting evidence + failure mode), or EXTEND (add new information). Challenges without evidence are rejected.

**Round 2 — Conflict Resolution:** Moderator resolves using priority rules:
1. Direct evidence > inference
2. Instrumentation must be ruled out first
3. Parsimony — single-cause preferred
4. Connector caution — investigate further rather than dismiss
5. Recency — more recent changes are higher prior
6. Historical precedent — matching patterns increase confidence

**Checkpoint 3:** At least one hypothesis must survive with Medium or High confidence. If all Low, output "INCONCLUSIVE."

### Phase 4: Validation

Agent: Validation Agent

Independent re-derivation:
1. Arithmetic check (new queries, don't copy)
2. Timeline consistency (cause before effect, accounting for lags)
3. Segment consistency (right segments affected)
4. Magnitude plausibility (cross-ref with historical patterns)
5. Co-movement check (related metrics move as expected)
6. Residual check (>10% unexplained → flag)

**Checkpoint 4:** All six checks must pass. Any failure sends back to Phase 3.

### Phase 5: Synthesis & Recommendations

Agent: Synthesis Agent

Output structure:
```
## TL;DR
{2-3 sentences: what, why, what to do. Confidence level.}

## What Happened
{Metric, magnitude, timeframe, affected segments. Observable facts.}

## Why It Happened
{Root cause. Evidence trail. Key decomposition. Specific change with date/owner.}

## Confidence Assessment
{Supporting evidence. Ambiguous/missing evidence. Rejected alternatives.}

## Recommendations
{Per recommendation: Action, Owner, Expected impact, Verification metric, 
Success threshold, Timeline, Priority}

## Appendix
{Detailed decomposition tables. Change detection timeline. Debate summary. 
Validation results.}
```

Communication Standards skill enforces: TL;DR mandatory, every number has context, recommendations specific enough for Monday morning.

### Phase 6: Quality Review

Agent: Review Agent — Three-dimensional review:

- **Analysis Rigor (33%)**: Decomposition complete? Causal claims supported? Alternatives addressed? Validation passed?
- **Communication Effectiveness (33%)**: TL;DR accurate? Recommendations actionable? Confidence calibrated? Accessible to non-DS?
- **Domain Accuracy (33%)**: Pipeline references correct? Metric relationships accurate? Recommendations routed correctly?

Deduction-based scoring with diminishing returns curve. Strength credits for exceptional insights.

**Checkpoint 6:** Score must meet minimum threshold. Below threshold → specific feedback → Synthesis Agent revises.

### Cost Management

| Mode | Phases Run | ~API Calls | Use When |
|------|-----------|------------|----------|
| Quick triage | 0-1 only | 2-3 | Small drops, initial assessment |
| Standard | 0-5, skip debate | 5-7 | Well-understood metrics, time pressure |
| Full | 0-6, with debate | 8-12 | Large drops, ambiguous causes, high stakes |
| Deep | 0-6, debate + deep decomposition | 12-18 | P0 incidents, exec-facing analyses |

Default: Standard (skip debate) for Streamlit public demo. Full for internal use.

---

## Agent: Metric Intake

Classify a metric drop and prepare the investigation context. Phase 0 of debug-architect, or standalone for quick triage.

### Input

A description of the metric drop: free text, structured data, or alert reference.

### Steps

**1. Parse the Drop Description**

Extract: metric name, magnitude, direction (drop/spike), timeframe (start, ongoing?, gradual vs. step-change), scope (all traffic or specific segments), severity (P0/P1/P2).

If any critical field is missing, state what's missing and proceed with `[ASSUMED]` tag. Do not halt for missing fields.

**2. Classify by Pipeline Stage**

| Metric Category | Primary Stage | Adjacent Stages |
|----------------|---------------|-----------------|
| Query success, null rate | Query Understanding | Retrieval, Connector |
| Relevance, nDCG | Ranking | Retrieval, QU |
| CTR, engagement | Search Experience | Ranking, Interleaver |
| Impression count, coverage | Retrieval | Connector, QU |
| Latency | Retrieval | Connector, Ranking |
| Revenue, conversion | Search Experience | Ranking, Connector |
| Connector-specific | Third-Party Connector | Retrieval |
| Blending, position | Interleaver | Ranking, Search Experience |

**Always include Third-Party Connector as adjacent**, regardless of category.

**3. Identify Expected Co-Movements**

From metric relationships:
```
If root cause is in {stage}:
  ✓ Should also see: {metric A} move in {direction}
  ✓ Should also see: {metric B} move in {direction}  
  ✗ Should NOT see: {metric C} change
  ⏱ Lag: {metric D} would follow with ~{N} day delay
```

**4. Load Domain Context**

Trigger Domain Knowledge Skill: primary stage (10k tokens), Third-Party Connector (10k tokens, always), adjacent stages (3k each). Focus on Recent Changes (14 days) and Historical Patterns.

**5. Select Specialist Personas**

Each persona defined by: Name, Lens (focus area), Domain briefing (which slice), Bias to watch for (known blind spots).

### Output

```yaml
triage:
  metric: {name, magnitude, direction, timeframe, scope, severity, assumptions}
  pipeline: {primary_stage, adjacent_stages, connector_included: true}
  co_movements: {should_move, should_not_move, lagged}
  personas: [{name, lens, domain_briefing, bias_watch}]
  domain_context_loaded: {primary, connector, adjacent}
```

### Standalone Usage

When invoked outside debug-architect, add a "Quick Assessment" section: top 3 likely causes, recommended next step, estimated investigation effort (Quick/Moderate/Deep).

---

## Agent: Hypothesis Generator

Generate ranked, domain-grounded hypotheses for a Search metric drop. Each specialist persona produces hypotheses independently and in parallel.

### Input

Triage output from Metric Intake Agent + Domain Briefing (filtered per persona).

### Hypothesis Categories

1. **Instrumentation / Logging** — Metric measurement changed, not the underlying reality
2. **Upstream Data / Connector** — External data source changed. Most common root cause category in this org.
3. **Algorithm / Model** — Ranking retrain, feature drift, scoring change, index rebuild, QU model update
4. **Experiment Interaction** — Launched/ramped experiment, interaction effects, holdout contamination
5. **User Behavior / Seasonal** — Organic behavior change. Null hypothesis — check last, accept only after ruling out above.

### Per-Persona Execution

**Step 1: Review Domain Briefing** — What changed in your pipeline stage in the last 14 days? Has this metric dropped before? Known fragile points?

**Step 2: Generate 2-5 Hypotheses** — Each hypothesis MUST include:

```yaml
hypothesis:
  id: "{persona_initial}-{number}"
  statement: "{one sentence: cause and mechanism}"
  category: "{one of 5 categories}"
  domain_grounding: 
    source: "{specific entry from Recent Changes or Historical Patterns}"
    connection: "{how this fact supports the hypothesis}"
  expected_signature:
    segments_affected: "{which segments should show the drop}"
    segments_unaffected: "{which should NOT}"
    co_movements: "{other metrics that should move}"
    temporal_pattern: "{step change on date X | gradual | intermittent}"
  evidence_needed:
    to_confirm: "{specific data check to prove}"
    to_reject: "{specific data check to disprove}"
  confidence: "Low|Medium|High"
  confidence_reasoning: "{why}"
  effort_to_verify: "Quick (<30 min)|Moderate (half day)|Deep (1+ day)"
  verification_steps: ["{step 1}", "{step 2}"]
```

**Step 3: Rank by Investigation Priority** — Instrumentation first → Connector → Algorithm → Experiment → User Behavior. Within category: High confidence first, Quick effort first.

### Quality Gates

**Rejection criteria:** No domain grounding, missing expected signature, missing evidence needed, User Behavior category without ruling out engineering causes.

**Strength signals:** Non-obvious pipeline interaction, specific testable prediction, valid historical comparison.

### Output

Per persona: specialist name, stage, hypothesis list. Combined: total count, category distribution, investigation priority ranking.

---

## Agent: Debate Moderator

Facilitate structured cross-examination of hypotheses and investigation findings. Catches false positives and strengthens root cause conclusions through adversarial review.

### When to Run

- Default: Runs in full pipeline
- Skip: `--skip-debate` (small drops, time-sensitive, public demo cost management)
- Force: When multiple specialists have conflicting High-confidence hypotheses (mandatory regardless of flags)

### Input

All hypotheses from Phase 1 + all evidence from Phase 2 + Domain Knowledge Skill access.

### Round 1: Annotation

Each specialist reviews ALL hypotheses and ALL evidence (not just their own). For each hypothesis:

**AGREE**: "Supported by [specific data pattern from Phase 2]." + optional additional domain context.

**DISAGREE**: "Contradicted because [specific failure mode or data pattern]." + domain fact basis + what evidence actually suggests instead.

**EXTEND**: "Partially correct but incomplete. Additionally, [extension with evidence]." + revised expected signature.

**Annotation Rules:**
1. Every DISAGREE must cite specific contradicting evidence or domain fact. "Seems unlikely" is rejected.
2. Every AGREE must cite specific supporting evidence. "Seems right" is rejected.
3. Every EXTEND must add genuinely new information. Restating is rejected.
4. A specialist CANNOT AGREE with their own hypothesis (not new information).
5. A specialist CAN EXTEND their own hypothesis if Phase 2 revealed something new.

**Domain Fact Verification:**
When any annotation cites a domain fact, the moderator verifies against Domain Knowledge Skill:
- Confirmed → accepted as-is
- Partially correct → accepted with correction
- Not found → accepted but flagged "unverified"
- Contradicted → rejected, specialist must revise

### Round 2: Conflict Resolution

**Step 1: Tally** — Per hypothesis: AGREE count (with evidence quality), DISAGREE count, EXTEND count.

**Step 2: Priority Rules** (when hypotheses conflict):
1. Direct evidence > inference
2. Instrumentation must be ruled out first
3. Parsimony — single-cause preferred unless evidence demands multi-cause
4. Connector caution — investigate further rather than dismiss
5. Recency — more recent changes are higher prior
6. Historical precedent — matching patterns increase confidence one level

**Step 3: Ranked Output**

```yaml
debate_outcome:
  surviving_hypotheses:
    - hypothesis_id, original_confidence, post_debate_confidence, 
      confidence_change_reason, agree/disagree/extend counts,
      key_supporting_evidence, key_challenging_evidence, remaining_uncertainty
  rejected_hypotheses:
    - hypothesis_id, rejection_reason, rejected_by
  proposed_root_cause:
    primary: "{hypothesis_id}: {statement}"
    confidence: "High|Medium|Low"
    contributing_factors: [if multi-cause]
    evidence_summary: "{2-3 sentences}"
    remaining_risks: "{what could still prove this wrong}"
```

### Halting Conditions

- All hypotheses Low confidence → "INCONCLUSIVE" + specific data needed
- Two High-confidence contradictory hypotheses → "CONFLICTING EVIDENCE" + additional investigation recommended
- Domain fact contradicts Knowledge Skill → "POTENTIAL KNOWLEDGE BASE STALENESS" + manual verification needed

### Proceed to Validation if:

At least one hypothesis Medium or High confidence, and proposed root cause accounts for ≥70% of drop magnitude.

### Cost Management

| Scenario | Debate? | Rationale |
|----------|---------|-----------|
| P0 drop, >5%, ambiguous | YES, mandatory | Stakes too high |
| P1 drop, clear cause from Phase 2 | Optional | Less marginal value |
| P2 drop, <2% | Skip | Not worth cost |
| Multiple conflicting hypotheses | YES, mandatory | Exactly what debate is for |
| Public demo / Streamlit | Skip | Cost management |
| Internal team use | YES | Quality > cost |

---

# PART 4: NEXT STEPS

---

## Implementation Priorities

### Priority 1: Complete Phase 2 Investigation Agents (TODO)
- `agents/decomposition.md` — Metric decomposition execution
- `agents/change-detection.md` — Cross-reference drops against deploy/change logs
- `agents/counterfactual.md` — Experiment holdout and interaction analysis

### Priority 2: Complete Phase 4-6 Agents (TODO)
- `agents/validation.md` — Independent re-derivation
- `agents/synthesis.md` — Root cause narrative production
- `agents/review.md` — Connect to existing multi-agent review system (33/33/33 scoring)

### Priority 3: Populate Domain Knowledge (TODO)
- `pipeline/*.md` — Per-stage knowledge files (start with third-party-connector.md)
- `changes/*.md` — Recent deploys, experiment log, connector changes
- `incidents/historical-patterns.md`
- `skills/metric-definitions/SKILL.md` — Full metric taxonomy

### Priority 4: Streamlit Integration
- Wrap debug-architect as Streamlit app
- Sample metric drops for public demo
- `--skip-debate` as default for public usage
- Session-based rate limiting

### Recommended First Test
Populate `third-party-connector.md` (most critical area), then test Metric Intake + Hypothesis Generator against a real metric drop you've previously debugged. Compare the grounded hypotheses against what you actually found — this calibrates whether the domain grounding requirement produces better hypotheses than an ungrounded approach.
