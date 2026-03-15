# Session Record: Context Layer Industry Analysis → SAIN Knowledge Layer & Feedback Loop Design

**Date:** 2026-03-14  
**Source Material:** a16z article "Your Data Agents Need Context" (Mar 10, 2026) + Glean CEO response  
**Purpose:** Map industry findings to SAIN architecture; design knowledge layer refresh and feedback loop mechanisms  

---

## Part 1: Industry Context

### a16z Article Summary ("Your Data Agents Need Context")

**Authors:** Jason Cui and Jennifer Li (a16z)  
**URL:** https://www.a16z.news/p/your-data-agents-need-context  

**Core Thesis:** Data and analytics agents are essentially useless without the right context. They can't tease apart vague questions, decipher business definitions, or reason across disparate data effectively.

**Market Evolution Described:**
1. Rise of the modern data stack (decade of consolidation)
2. Agent frenzy (2024–2025, everyone deploying agents on existing data stacks)
3. Hitting the wall (agents failed due to lack of proper data context)

**The Revenue Growth Example (Crystallizing the Problem):**
- Challenge 1: How does the agent know how revenue or quarters are actually defined? Revenue is a business definition not hard-coded into a warehouse. ARR vs. run rate? Fiscal quarter timing?
- Semantic layers were supposed to solve this, but in practice they're often stale — updated by people who left, not connected to current BI tools, missing new product lines
- Challenge 2: Where are the right data sources? Which are the actual sources of truth? Raw data split across multiple tables and warehouses (fct_revenue vs. mv_revenue_monthly vs. mv_customer_mrr)

**Context Layer = Superset of Semantic Layer:**
- Traditional semantic layer: great for specific metric definitions, hand-constructed by data teams in LookML-like syntax, connected to BI tools
- Modern context layer needs: canonical entities, identity resolution, tribal knowledge instructions, governance guidance, and more

**Five-Step Architecture for Context + Agentic Data Systems:**
1. Accessing the right data (table stakes — modern data stack, lakehouse, plus tribal knowledge in GDrive/Slack/etc.)
2. Automated context construction (LLM-driven — past query history for most-referenced tables/joins, dbt/LookML definitions)
3. Human refinement (tribal knowledge that is implicit, conditional, historically contingent — e.g., "for CRM data, look at Affinity for USCAN deals from 2025 onwards but Salesforce for global leads before that")
4. Agent connection (expose context layer via API or MCP)
5. Self-updating context flows (data sources change, custom instructions evolve, agent corrections feed back into context layer)

**Key Insight:** Building a proper data agent is a blend of technical challenges (data infrastructure/engineering) with human operational challenges (tribal knowledge collection). The .cursorrules analogy: data practitioners maintain rules and guidelines like developers maintain rules files.

**Market Map Categories:**
- Data gravity platforms (Databricks, Snowflake — already have data gravity, adding lightweight semantic modeling + AI analyst products)
- Existing AI data analyst companies (evolved to encompass context layer construction)
- New dedicated context layer companies (building from ground up)

---

### Glean CEO Response

**Key Points:**

1. **Metric disambiguation requires provenance understanding:** "Historically we relied on the expertise of the data owner to know which metric to pull. Now it requires an agent understanding which metrics actually matter and selecting the right ones as they evolve over time."

2. **Canonical metric inference from usage patterns:** "At Glean, when we analyze structured data from systems like Salesforce or Databricks, we look at usage patterns, who produced the metric, and how it's already being used to infer the likely canonical metric."

3. **Metric disambiguation is fundamentally a search problem.**

4. **Data agent is usually one component of a larger workflow:** "Take a prompt like: 'Analyze my sales pipeline to understand what's at risk.' Yes, some of that analysis comes from structured data in systems like Databricks or Snowflake. But a large part of understanding 'risk' actually lives in unstructured data — team conversations, comments on documents or spreadsheets, and notes from forecasting review meetings."

5. **Context graphs are rising in importance** because agents need a new kind of data structure to understand how work actually happens and how decisions get made.

---

## Part 2: Mapping to SAIN Architecture

### The Core Shared Problem: Context Is the Bottleneck, Not Reasoning

SAIN doesn't struggle because the LLM can't write SQL or reason about metrics — it struggles because it doesn't reliably know *which* metric definition is canonical, *which* table is the source of truth, and *which* SQL pattern is correct for a given sub-domain.

### Concept Mapping: Industry → SAIN

#### 1. Knowledge Layer IS a Context Layer

The article's five-step evolution maps to SAIN's three-tier progressive knowledge loading:
- Tier 1 (base definitions) = "automated context construction"
- Tier 2 (hypothesis-tagged patterns loaded on Gate pass) = "agent connection" — context supplied just-in-time
- Phase 0 audit (tagging entries with hypothesis-level tags and pattern signatures) = the missing step that makes everything else work

**Validation:** The industry is converging on the same sequencing we arrived at empirically. Knowledge foundation first, before adding architectural complexity. Organizations that skipped this step and went straight to agent deployment hit a wall.

#### 2. The Canonical Metric Problem Is Universal

Glean CEO's insight: metric disambiguation requires understanding provenance and usage, not just definitions. "Who produced the metric and how it's already being used to infer the likely canonical metric."

**SAIN mapping:** Confluence hygiene problem. Knowledge index entries may be stale, authored by people who've left, or superseded by newer definitions. Phase 0 audit needs to capture not just *what* a metric is defined as, but *who* maintains it and *whether it's actively used in dashboards/reports*. Provenance metadata separates a context layer from a glorified glossary.

#### 3. "Data Agent Is Usually One Component of a Larger Workflow"

**SAIN mapping:** ~60-70% of DS work is reactive (measuring/validating decisions already made). SAIN isn't replacing the full investigation workflow — it's accelerating the triage phase within a larger human decision-making process. Failure cases in the article are organizations that tried to make the data agent the *entire* workflow rather than an accelerant within one.

Reinforces SME Review Rubric approach — SAIN produces a hypothesis-backed triage, humans validate and decide. The credibility gap is exactly what happens when organizations present agent output as a finished answer rather than as input to a human workflow.

#### 4. Structured + Unstructured Context

Glean CEO's "risk" example: signal lives in team conversations, document comments, meeting notes, not just CRM data.

**SAIN parallel:** When investigating a metric movement, the *numbers* come from structured data (tables, metrics). But the *why* often lives in unstructured context: experiment launch notes, team Slack discussions about a rollout, Confluence pages about a ranking change. Sub-domain knowledge (Query Understanding, Retrieval, Ranking, etc.) is essentially encoding this unstructured tribal knowledge into structured context that the agent can use.

#### 5. Human Refinement Is Non-Negotiable

Article: automated context construction can't create the full picture — some context is "implicit, conditional, and historically contingent."

**SAIN mapping:** Human curation before automation. Converting Lead Principal Engineer into calibration co-owner rather than presenting finished evaluations. Gate rubrics and knowledge index tags are the data-science equivalent of .cursorrules files.

#### 6. Self-Updating Context = Feedback Loop Gap

Article's step 5 (self-updating context flows where agent corrections feed back into context layer) is the piece SAIN architecture hasn't formalized yet. When SAIN gets something wrong in a review session, that correction lives in the session record but doesn't systematically flow back into the knowledge index.

**Natural Phase 2 capability:** When a Gate catches a bad hypothesis or a reviewer flags an incorrect table reference, that signal should update the knowledge layer's provenance tags and pattern signatures.

### Meta-Insight

Glean CEO: metric disambiguation is "fundamentally a search problem." We're building a search metric agent inside a search organization. The same principles that make search good (relevance ranking, authority signals, freshness, context-dependent retrieval) are exactly what a knowledge/context layer needs. Search domain expertise is a competitive advantage in building this agent.

**Biggest takeaway:** Phase 0 knowledge audit is even more important than previously assessed. The industry is confirming context is the make-or-break layer. The article provides external validation and vocabulary (context layer, context graph, provenance-based metric resolution) that may resonate with stakeholders in industry terms rather than internal architecture terms.

---

## Part 3: Knowledge Layer Refresh & Feedback Loop Design

### Framing: Two Problems at Different Maturity Levels

- **Knowledge layer refresh** (keeping entries current) = Phase 0/1 problem. Needed before the agent is credible at scale.
- **Feedback loops** (corrections flowing back) = Phase 2 problem. Needs enough usage volume for signal to be meaningful.

Mixing them up is a complexity migration risk: building a sophisticated self-updating system before validating what the knowledge entries should look like.

---

### Knowledge Layer Refresh (Phase 0–1)

**Core problem:** Staleness detection. Knowledge index has entries but no way to know if they're still accurate. The a16z article's example of semantic layers "updated by a data team member that left last year, no longer used by BI tools" is literally the Confluence situation.

#### Provenance Fields Required Per Entry (Post Phase 0 Audit)

Beyond the already-planned hypothesis-level tags and pattern signatures, each entry needs three provenance fields:

**1. Ownership Signal**
- Not "who wrote the Confluence page" but "who would you Slack right now if this metric looked wrong"
- That's the actual domain owner
- If you can't name that person, the entry is already suspect
- Maps to Glean CEO's point about inferring canonical metrics from who produces them

**2. Usage Signal**
- Is this metric/table/pattern actively referenced in dashboards, alerts, or recent investigations?
- An entry describing `mv_customer_mrr` that nobody has queried in 6 months is a dead entry
- Can be determined from query logs without building anything — one-time check during audit

**3. Freshness Marker**
- When was this entry last validated by a human (not when the Confluence page was last edited, which could be a formatting change)
- Starts as the date audited in Phase 0
- Becomes the mechanism for refresh later

#### Refresh Mechanism (Keep It Simple)

**Do NOT build an automated staleness detector.**

Instead, leverage the Phase A/B user engagement already planned:
- When Jira Search EM and team review SAIN outputs in 20-minute sessions, any knowledge entry that contributed to a wrong or questionable result gets flagged for re-validation
- That's the refresh trigger for Phase 1: usage-driven, human-validated, zero infrastructure

**Practical cadence:** After each Phase B review session (weeks 3–6), reviewer spends 5 minutes tagging:
- Which knowledge entries were hit
- Whether they held up vs. didn't

This quickly reveals which sub-domains have the most knowledge decay.

**Expected decay pattern (hypothesis):**
- Fastest decay: Third-Party Connectors, Search Experience (change frequently)
- Most stable: Query Understanding, Retrieval (more foundational)

---

### Feedback Loop Design (Phase 2)

**Current state:** When a Gate catches a bad hypothesis or a reviewer flags an incorrect table reference, the correction lives in the session record. The gap: correction doesn't update the knowledge layer, so SAIN can repeat the same mistake.

#### Three Categories of Corrections (Different Feedback Paths)

**Category 1: Factual Corrections (wrong table, wrong metric definition, wrong join pattern)**
- Easiest category — correction is deterministic
- Example: `fct_search_clicks` was replaced by `fct_search_events_v2` three months ago
- Should update the knowledge entry directly
- Phase 2 mechanism: structured annotation format in session records, batch-processed weekly into knowledge index updates
- No automation needed — literally find-and-replace on the knowledge entry

**Category 2: Judgment Corrections (wrong hypothesis prioritization, missed a more likely root cause)**
- Harder — not "fix the entry" but "add a new pattern"
- Example: SAIN consistently under-prioritizes interleaver-related hypotheses when a metric drops → need new pattern signature: "when metric X drops and feature Y recently launched, check interleaver allocation first"
- Mechanism: accumulate in a staging area (can be a markdown file), review during regular architecture sessions, promote into knowledge index after review
- Do NOT auto-promote — judgment corrections need human validation before becoming canonical

**Category 3: Context Corrections (metric was technically right but business context changed)**
- Hardest to systematize — maps to Glean CEO's unstructured data point
- Example: "Revenue dropped 10% but that's because we intentionally deprecated a product line last quarter"
- SAIN can't know this from structured data
- Should stay human-mediated for a long time
- Mechanism: SAIN's SYNTHESIZE output should have an explicit "assumptions this analysis rests on" section → reviewers validate assumptions → when assumption is wrong due to missing business context → add time-bounded context note to knowledge layer
- Example note: "Q1 2026: Product X deprecated, expect ~10% drop in affected metrics"

#### Feedback Loop Architecture

```
Session Record
    → Structured Correction Annotation (low-friction capture during review)
    → Categorize: Factual / Judgment / Context
    → Route:
        Factual    → Direct knowledge entry update (weekly batch)
        Judgment   → Staging file → Batch review in architecture sessions → Promote or discard
        Context    → Time-bounded notes added to knowledge layer
```

#### Key Design Principle

**Write-heavy, read-light.**
- Very easy to capture a correction during a review session (low friction write)
- Relatively infrequent to process corrections into the knowledge layer (batched read)
- If the capture step is hard, people won't do it
- If the processing step is real-time, all time goes to knowledge maintenance instead of agent improvement

---

### Roadmap Impact

**Phase 0 (now):**
- Add provenance fields (ownership, usage, freshness) to each knowledge entry during the audit
- No new infrastructure required

**Phase A/B (weeks 1–6):**
- Use review sessions as the refresh trigger
- Track which entries were hit and held up vs. didn't
- Capture corrections in a simple structured format in session records

**Post-Phase B:**
- Batch-process accumulated corrections
- Factual fixes → go directly into knowledge index
- Judgment patterns → reviewed and promoted
- Context notes → added with time bounds
- Assess whether correction volume justifies any automation
- Hypothesis: won't justify automation for at least another quarter

**What to resist:** Building a "self-updating context flow" (article's step 5) before having data on what actually goes stale and how fast. Phase A/B sessions will provide that data empirically. Then decide whether automated staleness detection is worth building or whether a monthly human review pass is sufficient given actual decay rate. Practical constraints first.

---

## Key Vocabulary for Stakeholder Communication

These terms from the article may resonate with stakeholders who need to hear the argument in industry terms:

| Industry Term | SAIN Equivalent |
|---|---|
| Context layer / Context OS | Knowledge layer (three-tier progressive loading) |
| Context graph | Sub-domain knowledge structure with cross-references |
| Provenance-based metric resolution | Ownership + usage signals on knowledge entries |
| Semantic layer (traditional) | Static metric definitions (what we're upgrading from) |
| Self-updating context flows | Feedback loop (Phase 2) |
| Tribal knowledge capture | Human refinement of knowledge entries, Confluence curation |
| Canonical metric inference | Pattern signatures + hypothesis-level tags |

---

*End of session record. Ready for Claude Code handoff.*
