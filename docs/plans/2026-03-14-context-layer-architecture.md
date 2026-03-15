# Context Layer Architecture — Design Spec for 100+ Scale

**Date:** 2026-03-14
**Status:** Design complete, ready for implementation
**Audience:** Internal reference + stakeholder communication (employer demo, eng leads)

---

## Why This Is a Full Spec, Not a 1-Pager

Scaling from 5 DSs to 100+ search engineers within 1 month means tribal knowledge can't scale through implicit sharing. At 5 users, someone can Slack the answer. At 100, that person becomes a bottleneck. Provenance, correction workflows, and refresh mechanisms become operational necessities, not nice-to-haves.

---

## 1. Problem & Industry Validation

### Context Is the Bottleneck, Not Reasoning

SAIN doesn't struggle because the LLM can't reason about metrics — it struggles because it doesn't reliably know *which* metric definition is canonical, *which* table is the source of truth, and *which* diagnostic pattern applies to a given situation.

This is not unique to us. The a16z article "Your Data Agents Need Context" (Mar 2026) identifies this as the universal failure mode: organizations deploy data agents on existing data stacks, agents fail because they lack proper context, not because they lack reasoning capability.

### a16z Five-Step Architecture → SAIN Three-Tier Mapping

| a16z Step | Description | SAIN Equivalent |
|---|---|---|
| 1. Accessing the right data | Table stakes — modern data stack + tribal knowledge | All routable knowledge files (10 files, ~2,871 lines total: 6 YAMLs + design doc + IC9 review + 2 eval rubrics) |
| 2. Automated context construction | LLM-driven — past query history, dbt/LookML definitions | Compressed rules (01–03) — key facts always in context |
| 3. Human refinement | Tribal knowledge that is implicit, conditional, historically contingent | Provenance fields + correction workflow (this spec) |
| 4. Agent connection | Expose context layer via API or MCP | Knowledge routing table (rule 04) — just-in-time loading |
| 5. Self-updating context flows | Agent corrections feed back into context layer | Feedback loop architecture (Section 5 below) |

### Competitive Advantage

Glean CEO's insight: metric disambiguation is "fundamentally a search problem." We're building a search metric agent inside a search organization. The same principles that make search good — relevance ranking, authority signals, freshness, context-dependent retrieval — are exactly what a knowledge/context layer needs. Our domain expertise is a moat, not just a feature.

---

## 2. Provenance Fields Per Knowledge Entry

Every knowledge entry (metric definition, diagnostic pattern, pipeline component description) needs 5 provenance fields to be trustworthy at scale.

### Field Definitions

**1. Ownership Signal**
- Not "who wrote the Confluence page" but "who would you Slack right now if this metric looked wrong?"
- That's the actual domain owner — the person who can validate or correct the entry
- If you can't name that person, the entry is already suspect
- Maps to Glean CEO's point: canonical metrics are inferred from who produces them

**2. Usage Signal**
- Is this entry actively referenced in dashboards, alerts, or recent investigations?
- An entry describing a table nobody has queried in 6 months is a dead entry
- Can be determined from query logs without building anything — one-time check during audit
- Binary at first (active/dormant), can become quantitative later with hit-rate tracking

**3. Freshness Marker**
- When was this entry last validated by a human (not when the Confluence page was last edited, which could be a formatting change)
- Starts as the date audited
- Becomes the mechanism for refresh: entries not re-validated in >90 days get flagged

**4. Confidence Level**
- **Definitional (100%):** formula-based, won't change unless the metric is redefined (e.g., Click Quality formula)
- **Empirical (needs case count):** based on observed patterns — stronger with more cases, weaker with few (e.g., "connector failures typically cause X% movement")
- Users need to know when they're relying on well-established rules vs hypotheses-that-became-convention
- Prevents the dangerous assumption that everything in the knowledge base is equally reliable

**5. Scope/Applicability Boundary**
- Which segments, product versions, connector types does this entry apply to?
- Prevents over-generalization across diverse tenant configurations
- Example: "This baseline applies to enterprise tenants with 5+ connectors — standard tenants with 1-2 connectors will show different values"
- Critical at 100+ users because user base will span more diverse configurations

### Implementation

Add provenance fields as YAML metadata on each entry during the next knowledge audit. No infrastructure required — just discipline.

```yaml
# Example provenance block (added to each top-level entry)
provenance:
  owner: "jane.doe"           # who to Slack if this looks wrong
  usage: active               # active | dormant
  last_validated: 2026-03-14  # human validation date
  confidence: definitional    # definitional | empirical
  scope: "all segments"       # or "enterprise only", "ai_on only", etc.
```

---

## 3. Correction Workflow

### Two Categories, Designed for Volume

At 100+ users, expect 10–20 corrections/month and 5–10 additions/month. The workflow must be low-friction for capture and lightweight for processing.

#### Corrections (something is wrong → fix directly)

- Trigger: a knowledge entry contributed to a wrong diagnosis, or a factual error is discovered
- Action: fix the entry directly, add a one-line changelog entry
- No staging gate — speed matters. Wrong knowledge is worse than no knowledge.
- Require a one-line "reason for change" to build institutional memory
- Examples:
  - `fct_search_clicks` replaced by `fct_search_events_v2` → update table reference
  - Baseline for ai_on shifted from 0.220 to 0.235 after model update → update baseline

#### Additions (new knowledge → async review before merging)

- Trigger: a new pattern, baseline, or diagnostic shortcut is discovered during an investigation
- Action: add to staging area, reviewed within 24 hours before merging
- Why the gate: new knowledge can conflict with existing entries in non-obvious ways
- At scale, a reviewer rotation (weekly responsibility) prevents bottleneck on one person
- Any entry can optionally have an expiration date for time-bounded context:
  - Example: "Q1 2026: Product X deprecated, expect ~10% drop in affected metrics"

### Changelog Format

```yaml
# In corrections.yaml — append after each correction
- date: 2026-03-14
  type: correction        # correction | addition
  entry: "metric_definitions.yaml > baseline_by_segment > ai_on"
  change: "Updated Click Quality baseline from 0.220 to 0.235"
  reason: "Post-model-update recalibration validated by 30-day data"
  author: "jane.doe"
```

---

## 4. Refresh Mechanism (Usage-Driven at Scale)

### Post-Session Tag Pass

After each diagnostic/review session, 5-minute tag pass:
- Which knowledge entries were hit during this session?
- Did they hold up (used correctly, led to right diagnosis) or not (stale, misleading, incomplete)?

At 100+ users, this generates real usage signal within weeks — sufficient to identify fastest-decaying knowledge domains without building any automated staleness detector.

### Expected Decay Pattern

| Knowledge Domain | Expected Decay Rate | Why |
|---|---|---|
| Third-Party Connectors | Fast (weeks) | Connector APIs change frequently, new connectors added |
| Search Experience / UX | Fast (weeks) | Feature launches, A/B tests, UI changes |
| AI Answer Configuration | Medium (months) | Model migrations, threshold tuning |
| Ranking / Retrieval | Slow (quarters) | Foundational algorithms change less often |
| Query Understanding | Slow (quarters) | Core NLP pipeline is relatively stable |
| Metric Definitions | Very slow (yearly) | Formulas change only with deliberate redesign |

### Monthly Review Pass

DS team leads review entries with:
- **Lowest hit rate** → may be dead knowledge, consider archiving
- **Highest correction rate** → knowledge domain is decaying fast, needs more frequent validation
- **No recent validation** (>90 days since `last_validated`) → schedule re-validation

---

## 5. Feedback Loop Architecture

```
Diagnostic session
    → Correction captured (low-friction, inline during review)
    → Categorize: Correction (fix) or Addition (new)
    → Route:
        Correction → direct update + changelog entry (same day)
        Addition   → 24-hour async review → merge or discard
    → Monthly: aggregate corrections → identify decaying knowledge domains
    → Quarterly: review decay patterns → adjust validation cadence
```

### Design Principle: Write-Heavy, Read-Light

- **Very easy** to capture a correction during a review session (low friction write)
- **Relatively infrequent** to process corrections into the knowledge layer (batched read)
- If the capture step is hard, people won't do it — the entire system fails
- If the processing step is real-time, all time goes to knowledge maintenance instead of agent improvement

### Capture Format

During a diagnostic session, corrections are captured inline:

```
CORRECTION: [entry path] — [what's wrong] — [what it should be] — [evidence]
```

Example:
```
CORRECTION: metric_definitions > baseline_by_segment > enterprise — baseline 0.295 is outdated — should be 0.305 — validated against last 30 days of production data
```

One line. No form. No separate tool. This is the minimum viable capture that scales.

---

## 6. Stakeholder Vocabulary Mapping

When communicating with stakeholders, eng leads, or external audiences, these industry terms (from the a16z article) map to SAIN architecture:

| Industry Term (a16z) | SAIN Equivalent |
|---|---|
| Context layer / Context OS | Knowledge layer (three-tier progressive loading) |
| Context graph | Sub-domain knowledge structure with cross-references |
| Provenance-based metric resolution | Ownership + usage signals on knowledge entries |
| Semantic layer (traditional) | Static metric definitions (what we're upgrading from) |
| Self-updating context flows | Feedback loop (correction workflow + refresh mechanism) |
| Tribal knowledge capture | Human refinement of knowledge entries |
| Canonical metric inference | Pattern signatures + hypothesis-level tags |

### Why This Matters

The a16z article gives us external validation and vocabulary that resonates with stakeholders in industry terms. "We're building a context layer for our diagnostic agent" lands better than "we're curating YAML files." Same architecture, different framing for different audiences.

---

## 7. Scaling Roadmap

### Phase 1: Now (2–5 DSs)

- Add provenance fields to YAML entries during next knowledge audit
- No infrastructure required — just metadata discipline
- Activate knowledge routing table (rule 04) for context-efficient loading
- Deliverable: provenance-tagged knowledge entries + working routing table

### Phase 2: Month 1 (100+ Engineers)

- Activate correction workflow (corrections vs additions, changelog)
- Assign reviewer rotation (weekly responsibility for addition reviews)
- Start tracking entry hit rates from diagnostic sessions
- Deliverable: operational correction workflow + first month of usage data

### Phase 3: Month 2–3 (Steady State)

- Aggregate corrections → identify decay patterns by knowledge domain
- Validate expected decay rates (Section 4) against actual data
- Decide if automated staleness detection is worth building based on actual decay rate
- Deliverable: empirical decay rate data + decision on automation investment

### Migration Triggers (When This System Outgrows Itself)

| Trigger | Threshold | Action |
|---|---|---|
| Knowledge files | >15 files | Consider semantic retrieval over routing table |
| Routing intents | >60 intents | Routing table becomes unwieldy — migrate to search-based lookup |
| Correction volume | >30/month | Manual processing becomes bottleneck — invest in automation |
| Entry count | >500 entries | YAML files become hard to navigate — consider database-backed store |

### What to Resist

Do NOT build a "self-updating context flow" (article's step 5) before having data on what actually goes stale and how fast. Month 1–2 sessions will provide that data empirically. Then decide whether automated staleness detection is worth building or whether a monthly human review pass is sufficient given actual decay rate. Practical constraints first.

---

*End of design spec. Ready for implementation against the scaling roadmap.*
