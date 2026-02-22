# Search Metric Analyzer — v1 Design Document

**Date:** 2026-02-21
**Status:** Approved
**Author:** Search DS Team

---

## 1. Problem Statement

The Search DS team (2 Senior DSs) needs to debug metric movements faster and produce trustworthy Slack messages and reports for Eng Leads (Dir/VP level). Today's workflow — dashboards + ad-hoc SQL + tribal knowledge — takes hours per investigation. The team lacks complete domain context across all Search components to fully explain drops and help Eng prioritize.

### Bottlenecks Being Solved

1. **Speed** (primary): Manual process of checking dashboards, running SQL, cross-referencing experiments takes hours when it should take minutes
2. **Knowledge gap**: Even senior DSs don't hold complete domain context for every Search component
3. **Attribution accuracy**: Multi-cause overlap cases (experiment + seasonality + mix-shift) need systematic decomposition

### What This Is NOT

- Not a real-time monitoring/alerting system (Eng Leads bring the metric drop to us)
- Not a replacement for senior DS judgment (it's a force multiplier)
- Not a full attribution system in v1 (decomposition + smart handoff to manual verification)

---

## 2. Target Users & Stakeholders

| Audience | What They Need | Decision They Make |
|----------|---------------|-------------------|
| Search DS team (primary) | Faster, more systematic diagnosis | Where to investigate deeper |
| Search Eng Lead / Manager | Clear summary + confidence level | Is this an incident? Should Eng prioritize a fix? Roll back an experiment? |
| Eng Dir/VP (hands-on) | High-level findings with business context | Is search quality trending well? Any strategic concerns? |

---

## 3. v1 Scope & Success Criteria

### In Scope

- Diagnostic workflow on synthetic data (13 scenarios)
- Claude Code skill + Python analysis toolkit
- Template-based Slack message + short report output
- Dual-judge auto-eval (LLM-as-judge + DS Analysis Review Agent)
- 2 operating modes: Quick and Standard
- Integration with Search Domain Expert Skills (always-on context)

### Out of Scope (v2+)

- Real data connectors (SQL, warehouse)
- Full attribution with experiment metadata
- Debate phase for ambiguous multi-cause cases
- Autonomous operation (Codex/scheduled runs)
- UI or API beyond Claude Code conversation

### Success Criteria for v1 Demo

1. Tool takes a synthetic metric movement and produces a correct diagnosis with appropriate confidence
2. Output includes Slack message (5-8 lines) and short report (1 page) in template format
3. At least 3 scenario types work end-to-end (single-cause, multi-cause overlap, false alarm)
4. Output passes DS Analysis Review Agent quality check (score >= 60)
5. MVE auto-eval: 3 cases x 3 runs, majority pass
6. Demo-able to IC9 and Search Leads as proof of concept

---

## 4. Architecture

### Approach: Skill + Analysis Toolkit (in Claude Code)

Claude Code is the orchestrator. Two skills provide knowledge and methodology. Python scripts handle computation.

```
Claude Code Session
├── Search Metric Analyzer Skill (diagnostic methodology + output templates)
├── Search Domain Expert Skills (always-on domain knowledge — active contributor)
├── Python Analysis Toolkit
│   ├── decompose.py      — dimensional decomposition + mix-shift
│   ├── anomaly.py        — anomaly detection vs historical baselines
│   ├── diagnose.py       — validation checks + confidence scoring
│   └── formatter.py      — Slack message + report from templates
├── Synthetic Data (from existing generator, extended to 13 scenarios)
└── Eval Pipeline (LLM-as-judge + DS Analysis Review Agent)
```

### Domain Expert Skills Integration

The Domain Expert Skills is an **active contributor**, not a passive knowledge base. Both skills are loaded in the same Claude Code session. The Metric Analyzer skill instructs Claude Code to draw on domain knowledge naturally throughout the workflow:

- When generating hypotheses: prioritize based on recent system changes and domain priors
- When interpreting decomposition: reference known patterns and expected data signatures
- When validating: check magnitude plausibility against historical precedents
- When synthesizing: include team ownership, strategic context, domain terminology

No explicit handoff points — domain knowledge is woven in at every stage, the way a senior DS naturally uses their experience.

---

## 5. Diagnostic Workflow

### 4-Step Linear Methodology

```
Step 1: INTAKE & TRIAGE
│   Input: metric name, time period, data file(s)
│   Actions:
│   ├── Parse and validate input data
│   ├── Compute headline movement (WoW, MoM delta)
│   ├── Run data quality gate (completeness, freshness, join coverage)
│   ├── Classify severity: P0 (>5%), P1 (2-5%), P2 (<2%)
│   ├── Co-movement analysis (check related metrics immediately)
│   └── Domain Expert Skills: surface recent system changes, initial hypotheses
│   Output: triage summary + severity + data quality verdict + co-movement pattern
│   Gate: If data quality FAILS → stop, report "blocked by data quality"
│
Step 2: DECOMPOSE & INVESTIGATE
│   2a: Dimensional Decomposition (sequential — needed by all hypotheses)
│   ├── Break metric by tenant_tier, ai_enablement, industry, connector_type,
│   │   query_type, position_bucket
│   ├── Mix-shift analysis (behavioral vs compositional change)
│   └── Output: decomposition table
│
│   2b: Hypothesis Investigation
│   ├── Quick mode: linear, top 2 hypotheses only
│   ├── Standard mode: parallel subagents (up to 3 simultaneous)
│   │   ├── Agent H1: Instrumentation/Logging + Connector check
│   │   ├── Agent H2: Algorithm/Model/Experiment check
│   │   └── Agent H3: Seasonal/External + AI feature effect check
│   └── Each agent checks expected data signatures for their hypotheses
│
│   2c: Evidence Fusion
│   ├── Rank hypotheses by evidence strength
│   ├── Check for multi-cause overlap
│   └── If any dimension >50% contribution, offer to drill down further
│   Output: ranked hypothesis list with evidence summaries
│
Step 3: VALIDATE
│   Input: hypotheses + decomposition
│   4 validation checks:
│   ├── Check 1: Logging Artifact Detection (overnight step-change >=2%?)
│   ├── Check 2: Decomposition Completeness (segments explain >=90%?)
│   ├── Check 3: Temporal Consistency (cause precedes effect?)
│   ├── Check 4: Mix Shift Detection (>=30% from composition change?)
│   Assign confidence: High / Medium / Low with explicit criteria
│   Output: validated diagnosis with confidence
│   Gate: If decomposition <70% → INCOMPLETE, do not present as definitive
│
Step 4: SYNTHESIZE & FORMAT
│   Generate using templates:
│   ├── TL;DR (3 sentences: what happened, why, what to do)
│   ├── Slack message (5-8 lines, domain terminology, actionable)
│   ├── Short report (1 page, structured sections including Business Impact)
│   └── Investigation checklist (manual follow-ups for smart handoff)
│   Anti-patterns enforced:
│   ├── No data dumps (15 charts without narrative)
│   ├── No hedge parades ("it could be X, or maybe Y")
│   ├── No orphaned recommendations ("investigate further" with no owner)
│   └── No passive voice root causes ("the metric was impacted")
```

### Hypothesis Priority Ordering

Fixed priority for investigation — encoded in the skill:

1. **Instrumentation/Logging anomaly** (cheap to verify, expensive to miss)
2. **Connector/data pipeline change** (always check regardless of triage)
3. **Algorithm/Model change** (ranking model, embedding model)
4. **Experiment ramp/de-ramp**
5. **AI feature effect** (AI answer adoption, threshold change, model migration)
6. **Seasonal/External pattern**
7. **User behavior shift** (null hypothesis — check LAST)

### Operating Modes

| Aspect | Quick Mode | Standard Mode |
|--------|-----------|---------------|
| Steps | 1 + simplified 2 + 4 | All 4 steps |
| Decomposition | Top-level dimensions only | Full dimensional + mix-shift |
| Hypothesis depth | Top 2 hypotheses, linear | Full ordering, parallel subagents |
| Validation checks | Data quality gate only | All 4 checks |
| Output | TL;DR + Slack only | TL;DR + Slack + report + checklist |
| Cost | Lower (fewer API calls) | Higher (parallel subagents) |
| Use case | "Is this worth investigating?" | "What happened and what should we do?" |

---

## 6. Co-Movement Diagnostic Table

Checked at Step 1 (Intake) — the pattern narrows the hypothesis space before decomposition.

| DLCTR | QSR | SAIN Trigger | SAIN Success | Zero-Result Rate | Latency | Likely Cause |
|-------|-----|-------------|-------------|-----------------|---------|-------------|
| down | down | stable | stable | stable | stable | Ranking/relevance regression |
| down | stable/up | up | up | stable | stable | AI answers working (positive — cannibalizing clicks) |
| down | down | down | down | stable | stable | Broad quality degradation (check model/experiment) |
| down | down | stable | down | stable | stable | SAIN quality regression (AI answers wrong) |
| down | down | stable | stable | up | stable | Connector outage / index gap |
| down | down | stable | stable | stable | up | Serving degradation / model fallback |
| down | stable | stable | stable | stable | stable | Click behavior change (UX, display, mix-shift) |
| stable | down | down | stable | stable | stable | SAIN trigger regression (AI not surfacing answers) |
| stable | down | stable | down | stable | stable | SAIN success regression (AI answers surfacing but wrong) |

---

## 7. Data Model & Knowledge Encoding

### metric_definitions.yaml

Encodes metric formulas, relationships, Enterprise Search-specific decomposition dimensions, and segment-specific baselines.

Key Enterprise dimensions:
- **tenant_tier**: standard, premium, enterprise
- **ai_enablement**: ai_on, ai_off
- **industry_vertical**: tech, healthcare, finance, retail, other
- **connector_type**: confluence, slack, gdrive, jira, sharepoint, other

Key relationships:
- QSR = max(qsr_component_click, sain_trigger * sain_success)
- qsr_component_click = dlctr
- AI answers and DLCTR have **inverse** co-movement (more AI answers = fewer clicks = expected)
- Different baselines per segment (ai_on tenants have structurally lower DLCTR)

Includes the co-movement diagnostic table for fast pattern matching at Intake.

### historical_patterns.yaml

Encodes known recurring patterns and past incidents:
- Enterprise onboarding waves (new tenants drag down aggregate via mix-shift)
- AI feature rollouts (click cannibalization — positive signal)
- Connector outages (third-party dependency failures)
- Seasonal enterprise patterns (end-of-quarter, audit season)
- Known incidents with data signatures for pattern matching

### Diagnostic Shortcuts

Heuristics that skip stages when fast signals are available:
- Connector health dashboard showing failures → jump to connector root cause
- Model fallback rate spiked → jump to serving/latency investigation
- Single large tenant dominating the drop → jump to tenant-specific analysis

---

## 8. Scenarios (13 Total)

| # | Scenario | Category | Complexity |
|---|----------|----------|-----------|
| S0 | Stable baseline | Control | Low |
| S1 | Seasonal pattern (end-of-quarter) | Time-based | Low |
| S2 | AI feature batch rollout (AI answer trap) | Feature effect | Medium |
| S3 | Ranking model improvement (Premium tier) | Algorithm | Medium |
| S4 | Ranking model regression (Standard tier) | Algorithm | Medium |
| S5 | AI answers cannibalizing clicks | Feature effect | Medium |
| S6 | Connector outage (e.g., Confluence down) | Infrastructure | Medium |
| S7 | Overlap: AI rollout + whale tenant churn | Multi-cause | High |
| S8 | Connector sync lag / stale index | Infrastructure | Medium |
| S9 | Tenant portfolio: new joins + churns (mix-shift) | Mix-shift | High |
| S10 | Connector extraction quality regression (silent) | Pipeline | High |
| S11 | Auth credential expiry (silent connector failure) | Pipeline | Medium |
| S12 | LLM provider / model migration (quality + latency) | Model change | Medium |

### Enterprise Search-Specific Scenario Categories

**Tenant Lifecycle:** S9 covers simultaneous joins + churns with sub-scenarios: healthy growth (new tenants dragging aggregate), negative selection (best tenants churning), tier migration offsets.

**Connector Pipeline:** S6, S8, S10, S11 cover 4 stages of the connector lifecycle: Setup/Config (S11: auth expiry), Ingestion/Extraction (S10: silent quality regression), Indexing (S8: sync lag), Ranking/Serving (S6: outage).

**AI/Model Effects:** S2, S5, S12 cover AI answer adoption (positive signal misread as regression), click cannibalization, and LLM provider/model migration (quality shift, latency impact, cost optimization tradeoffs).

---

## 9. Output Format

### Template-Based Generation

`formatter.py` generates structured markdown templates. Claude Code fills narrative sections with natural language using domain context.

### Slack Message Template (5-8 lines)

```
[emoji] {METRIC} Movement Alert — [Severity: {severity}] [Confidence: {confidence}]

TL;DR: {metric} {direction} {magnitude}% {period}, {root_cause_summary}.
{data_quality_note_if_applicable}

Key findings:
{finding_1}
{finding_2}
{finding_3}

Confidence: {CONFIDENCE} — {confidence_reasoning}
{what_would_change_confidence}

{action_items_with_owners}
```

### Short Report Template (1 page)

Sections:
1. **Header**: Metric, date, severity, confidence
2. **Summary**: Same TL;DR as Slack (3 sentences)
3. **Decomposition Table**: Dimension, contribution %, direction
4. **Diagnosis**: Primary hypothesis, evidence, alternatives considered
5. **Validation Checks**: 4-check status table (pass/fail with detail)
6. **Business Impact**: Is this within acceptable range? Projected impact if persistent? OKR implications?
7. **Recommended Actions**: Action, owner, expected impact, verification metric
8. **What Would Change This Assessment**: Upgrade/downgrade conditions

### Output Principles

- TL;DR always first, always mandatory, max 3 sentences
- Numbers always have context (% of drop, not just %)
- Confidence stated explicitly with criteria, never hedged language
- Every recommendation has an owner and expected impact
- "Intentional tradeoff" label for expected metric movements (AI adoption, cost optimization)

---

## 10. Validation Checks

### 4 Mandatory Checks (v1)

| # | Check | Trigger | Severity |
|---|-------|---------|----------|
| 1 | Logging Artifact Detection | Overnight step-change >= 2% | HALT if confirmed |
| 2 | Decomposition Completeness | Segments explain >= 90% of total | HALT if < 70%, WARN if < 90% |
| 3 | Temporal Consistency | Metric changed after proposed cause | HALT if violated |
| 4 | Mix Shift Detection | >= 30% from composition change | INVESTIGATE (flag, don't halt) |

### Confidence Calibration

- **High**: Root cause confirmed by multiple independent evidence lines (decomposition + temporal match + co-movement + historical precedent)
- **Medium**: Well-supported but missing one check, or < 90% of drop explained
- **Low**: Single evidence line, or multiple plausible alternatives not resolved

Always state: "Would upgrade to {level} if {specific condition}."

---

## 11. Auto-Eval Framework (MVE)

### Dual-Judge Architecture

| Judge | Focus | Method |
|-------|-------|--------|
| LLM-as-Judge | Investigation quality (substance) | Scoring spec rubric, 3 runs majority vote |
| DS Analysis Review Agent | Communication quality (delivery) | Deduction-based scoring (analysis + communication reviewers) |

### 3 Eval Cases

| Case | Scenario | Archetype | Tests |
|------|----------|-----------|-------|
| 1 | S4: Ranking regression | Single-cause, clean signal | Can it find an obvious problem? |
| 2 | S7: AI rollout + tenant churn | Multi-cause overlap | Can it handle ambiguity without over-attributing? |
| 3 | S0/S1: Stable/seasonal | False alarm / restraint | Can it say "no action needed"? |

### Scoring Specs

Each case defines: must_find (root cause), must_check (required dimensions), must_not_do (anti-patterns), output_quality (TL;DR, confidence, actionability).

### 3-Run Majority Vote

Each case runs 3 times. Aggregation:
- 3/3 pass: GREEN (reliable)
- 2/3 pass: YELLOW (investigate variance)
- 0-1/3 pass: RED (block)

LLM-as-judge: different model from agent, temperature 0, structured JSON output, rubric baked verbatim into prompt.

### Demo Pass Criteria

| Case | LLM-as-Judge | Review Agent | Required |
|------|-------------|-------------|---------|
| Case 1 (single-cause) | 3/3 GREEN | Score >= 60 | Both pass |
| Case 2 (multi-cause) | 2/3 GREEN | Score >= 60 | Both pass |
| Case 3 (false alarm) | 3/3 GREEN | Score >= 60 | Both pass |

---

## 12. Project Structure

```
Search_Metric_Analyzer/
├── CLAUDE.md                          # Project-level instructions
├── README.md                          # How to run, key decisions
├── requirements.txt                   # Python dependencies (minimal)
│
├── skills/
│   └── search-metric-analyzer.md      # Diagnostic methodology skill
│
├── tools/                             # Python analysis toolkit
│   ├── __init__.py
│   ├── decompose.py                   # Dimensional decomposition + mix-shift
│   ├── anomaly.py                     # Anomaly detection vs baselines
│   ├── diagnose.py                    # Validation checks + confidence scoring
│   └── formatter.py                   # Slack + report template generation
│
├── data/
│   ├── synthetic/                     # Generated test data
│   └── knowledge/                     # Encoded domain knowledge
│       ├── metric_definitions.yaml    # Formulas, relationships, baselines, co-movement table
│       └── historical_patterns.yaml   # Seasonal patterns, past incidents, shortcuts
│
├── templates/                         # Output templates
│   ├── slack_message.md
│   ├── short_report.md
│   └── scenario_knobs_template.csv
│
├── tests/                             # Unit tests
│   ├── test_decompose.py
│   ├── test_anomaly.py
│   ├── test_diagnose.py
│   └── test_formatter.py
│
├── eval/                              # Auto-eval framework
│   ├── scoring_specs/                 # Per-case rubrics
│   │   ├── case1_single_cause.yaml
│   │   ├── case2_multi_cause.yaml
│   │   └── case3_false_alarm.yaml
│   ├── run_eval.py                    # MVE runner (3 cases x 3 runs)
│   └── results/                       # Eval output
│
├── generators/                        # Data generation (existing, extended)
│   ├── generate_synthetic_data.py
│   └── validate_scenarios.py
│
└── docs/
    ├── plans/
    │   └── 2026-02-21-search-metric-analyzer-design.md
    └── references/                    # Session records and prior design work
        ├── search-metric-debug-system.md
        ├── Search_Metric_Agent_AutoEval_Plan.md
        ├── Session_Log_Eval_Design_Discussion.md
        └── session-log-search-debug-architecture-2026-02-21.md
```

---

## 13. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Runtime | Claude Code (conversational) | Leverages existing orchestration, composes with other skills/agents, allows follow-up questions |
| Architecture | Skill + Python toolkit | Modular, independently testable, lowest build effort |
| Data source (v1) | Synthetic only | Proof of concept — real data integration in v2 |
| Output generation | Template-based | Consistent structure, testable, easy to iterate on format |
| Hypothesis investigation | Parallel subagents (Standard), linear (Quick) | Balance thoroughness and cost |
| Domain knowledge | Always-on (both skills in same session) | Natural integration, no rigid handoff points |
| Eval | Dual-judge (substance + delivery) | Orthogonal quality dimensions — correct diagnosis AND clear communication |
| Validation checks | 4 checks including mix-shift | Mix-shift is behind 30-40% of Enterprise Search metric movements |

---

## 14. What v2 Adds

- Real data connectors (warehouse integration)
- Full attribution with experiment metadata and release logs
- Additional validation checks (Simpson's Paradox, magnitude plausibility)
- Debate phase for ambiguous multi-cause cases
- Full/Deep operating modes
- Codex support for autonomous scheduled analysis
- Historical replay benchmark (offline eval on real past incidents)

---

## 15. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Tool gets diagnosis wrong, sent to Eng Lead | Trust destroyed | 4 validation checks + dual-judge eval + mandatory confidence calibration |
| AI answer adoption misidentified as regression | Wrong action taken (rollback good feature) | Explicit "AI answer trap" scenario + co-movement table with SAIN signals |
| Synthetic data doesn't represent real patterns | Tool works on synth but fails on real data | Enterprise-specific scenarios based on actual past incidents; v2 adds real data |
| Output too generic / robotic | Low adoption | Template-based with domain terminology; Review Agent checks communication quality |
| Skill prompt quality degrades with complexity | Inconsistent behavior | Keep skill under 120 instructions; heavy detail in knowledge YAML files |
