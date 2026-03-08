# IC9 Architectural Review: Search Metric Analysis Agent — Full Pipeline Assessment

## Review Info
- **Date:** 2026-03-01
- **Reviewer Role:** IC9 Search Architect
- **Scope:** Complete 4-stage pipeline: UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE
- **Evidence Base:** 20 audit questions (Q1–Q5 × 4 stages), Session 118 as empirical grounding, ~50 screenshots of agent self-audit responses
- **Audit Duration:** 2026-02-28 through 2026-03-01 (3 sessions)

---

## Verdict

**This is a well-designed system with a fundamentally inverted control architecture.**

The pipeline's conceptual design is strong: question decomposition → hypothesis generation → parallel investigation → evidence synthesis is the right shape for automated metric analysis. The domain modeling is sophisticated — six sub-domains, hypothesis-driven investigation, structured evidence collection, and confidence-graded conclusions. The agent's self-audit responses were consistently strong (grades ranging A- to A across 20 questions), demonstrating deep understanding of its own architecture.

But the implementation has a critical structural flaw: **enforcement weakens as you move downstream through the pipeline, while the consequence of errors increases.** UNDERSTAND has code gates. HYPOTHESIZE has a hybrid approach. DISPATCH has prompt instructions only. SYNTHESIZE — which produces the final report that engineers act on — has zero code enforcement and ~50% compliance on its own "mandatory" items.

The system is building a house where the foundation is reinforced concrete and the roof is a suggestion.

**Overall maturity assessment: Strong V1 prototype, not production-ready.** The investigation logic works. The failure modes are manageable at current scale. But without the structural fixes identified in this audit, reliability will degrade as usage scales and edge cases compound.

---

## What the System Gets Right

**The investigation architecture is sound.** The four-stage pipeline mirrors how a skilled data scientist actually works: understand the question, form hypotheses, gather evidence, synthesize conclusions. The separation between Lead Agent (orchestration) and Sub-Agents (execution) is the right abstraction. Hypothesis-driven investigation with explicit SUPPORTED/REJECTED/INCONCLUSIVE verdicts is more disciplined than most automated analysis systems.

**The domain model is sophisticated.** Six sub-domains (Query Understanding, Retrieval, Ranking, Interleaver, Third-Party Connectors, Search Experience) with domain-specific knowledge digests. The recognition that Third-Party Connectors require always-loaded context due to high domain knowledge velocity shows real operational understanding.

**The confidence framework is well-designed on paper.** The C10 formula — weighted average with 7 cap rules, effect-size proportionality checks, and residual unexplained thresholds — is more rigorous than many human-produced analyses. The problem isn't the design; it's that execution is model-dependent with no code validating the arithmetic.

**The checkpoint system provides good state management.** pipeline_state.yaml captures hypothesis sets, context snapshots, and sub-agent status at each stage boundary. The C1-C11 checkpoint numbering creates a traceable progression. The harness *infrastructure* is solid; it's the *enforcement* layer that's missing.

**The agent demonstrated exceptional self-awareness in its audit responses.** It self-identified that Session 118 skipped mandatory checks. It flagged that Validation Dispatch may not exist. It acknowledged that its SQL Query Index was omitted. This level of honest self-audit is rare and suggests the underlying model reasoning is strong — the failures are structural, not cognitive.

---

## What the System Gets Wrong

### 1. The Inverse Enforcement Problem

This is the audit's central finding. Across all four stages:

| Stage | Code Enforcement | Consequence of Failure | The Problem |
|---|---|---|---|
| UNDERSTAND | Manifest routing, C1 gates | Wrong inputs to pipeline | Enforcement appropriate |
| HYPOTHESIZE | Hybrid (some code, some prompt) | Wrong investigation scope | Enforcement adequate |
| DISPATCH | Zero — all prompt instructions | Wrong evidence gathered | **Under-enforced** |
| SYNTHESIZE | Zero — all prompt instructions | Wrong conclusions delivered to user | **Critically under-enforced** |

In a well-designed pipeline, validation should *tighten* as you approach the output layer, because downstream errors are harder to recover from and have real-world consequences. This system does the opposite. The stage that produces the report an engineer will use to decide whether to rollback a production change has the least structural protection of any stage.

This isn't an incremental problem. It's an architectural inversion that means every prompt-instructed "mandatory" check is actually optional, every "required" report section is actually suggested, and every "do not skip" instruction has approximately a coin-flip chance of being followed.

### 2. The Invisible Decision Chain

Each stage has one highest-leverage decision that is completely untraced:

| Stage | Invisible Decision | What It Controls | Why It's Dangerous |
|---|---|---|---|
| UNDERSTAND | metric_direction | Which direction is "bad" | If wrong, every hypothesis tests the wrong thing |
| HYPOTHESIZE | Hypothesis inclusion/exclusion | What gets investigated | If a key hypothesis is excluded, right answer is unreachable |
| DISPATCH | Sub-agent context construction | What evidence each sub-agent can find | If context is wrong, sub-agent can't find right evidence |
| SYNTHESIZE | Root cause narrative selection | What conclusion is presented | If framing is wrong, engineer takes wrong action |

These four decisions form a causal chain. Each inherits all upstream errors. SM-1 (root cause narrative selection) is the **terminal amplifier** — it takes whatever the previous three stages produced and constructs a plausible, professional-sounding narrative around it. A wrong metric_direction in UNDERSTAND becomes a wrong hypothesis set in HYPOTHESIZE becomes wrong evidence in DISPATCH becomes a convincing wrong conclusion in SYNTHESIZE.

The system has no mechanism to detect that this chain has gone wrong. Every stage's Invisible Decision looks reasonable in isolation. The error only becomes visible when a human expert looks at the final report and asks "wait, didn't you check X?" — and X was excluded three stages ago.

### 3. The Zero Feedback Loop Architecture

The pipeline is strictly feed-forward. Information flows in one direction: UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE → user. There is no structural mechanism for any stage to say "something is wrong, go back."

The one proto-feedback-loop — Validation Dispatch (Phase 4.5) in SYNTHESIZE — is prompt-instructed, untraced, and may not even be implemented. The agent reported that `agents/validation.md` may not exist in the codebase. If confirmed, the system literally has no error correction capability at any level.

This means:
- If UNDERSTAND gets metric_direction wrong, nothing catches it
- If HYPOTHESIZE excludes a critical hypothesis, nothing catches it
- If a sub-agent misinterprets its query results, nothing catches it
- If SYNTHESIZE writes a hallucinated causal claim, nothing catches it

Each failure propagates silently to the final report. The system's only safety net is the quality of its initial decisions — and those decisions are untraced.

### 4. The Evidence Bottleneck

The pipeline progressively narrows its evidence base:

```
User question (rich, ambiguous)
  → QuestionBrief (structured, some context lost)
    → HypothesisBrief per H (narrowed to specific hypothesis)
      → Sub-agent context (further narrowed by untraced Decision 5)
        → SQL queries (specific data extraction)
          → results/*.json (raw data)
            → finding.md (narrative interpretation of data)
              → report.md (narrative interpretation of narrative)
```

At each step, information is compressed and interpretation is added. By the time SYNTHESIZE reads finding.md, it's working with a sub-agent's narrative summary of query results — not the data itself. SYNTHESIZE does not re-read results/*.json. The report is an interpretation of an interpretation, with no cross-check against ground truth.

This matters most when a sub-agent makes a subtle interpretive error — confusing correlation with causation, misreading the directionality of a metric, or overlooking a confounding variable in the data. These errors are embedded in finding.md's narrative and become invisible to SYNTHESIZE, which faithfully synthesizes the wrong interpretation into a confident report.

### 5. The Memory Time Bomb

The system writes learnings to global.md after each investigation, creating a growing knowledge base that feeds future HYPOTHESIZE stages. This is a good idea with a dangerous implementation:

- **No confidence levels:** A learning from one investigation looks identical to a learning validated across fifty
- **No expiration:** Learnings from six months ago carry the same weight as yesterday's
- **No scope boundaries:** A learning from one metric family can bias hypotheses for unrelated metrics
- **Append-only with user gate:** Users approve writes they can't meaningfully evaluate
- **Positive feedback loop:** Over-generalized learnings bias future hypotheses → investigations converge on expected patterns → confirmatory learnings written → cycle repeats

At current scale (presumably dozens of investigations), this is manageable. At hundreds of investigations, global.md becomes a self-reinforcing echo chamber where the system increasingly finds what it expects to find.

---

## The Four Stages — Comparative Assessment

### UNDERSTAND: The Rigid Gate

**Strength:** Most structurally sound stage. Manifest routing provides deterministic question classification. C1 checkpoint creates a clear boundary. Agent identified 8 harness decisions and 7 failure modes with remarkable specificity (real metric examples: QSR vs SAIN, FPS vs Quick Find, weighted QSR vs component QSRs). Only 2 of 8 harness decisions are fully traced.

**Critical Finding — The Manifest Routing Trap:** The harness classifies question complexity via keyword matching in `manifest.yaml` (Simple/Medium/Complex) *before the model ever reasons*. This determines which agent file loads, which knowledge modules are injected, and the token budget. The feedback loop is asymmetric: the harness can under-scope the model, but the model can never up-scope the harness. If `manifest.yaml` routes a Complex question to Simple, the model gets 5K tokens and metric-registry only — it literally cannot realize it needs playbooks or sev-archive because it doesn't know they exist. Recommended fix: default to Complex for ambiguous inputs (accept token cost to prevent terminal under-scoping).

**Critical Finding — Tracing Gaps Are Systematic:** Only 2 of 8 harness decisions are fully traced. The 6 untraced decisions include table pre-selection, knowledge module loading, token budget allocation, and the keyword-to-complexity mapping itself. Post-hoc diagnostics can see what the model decided but not what the harness decided before the model saw anything. Three minimum tracing additions (manifest route, knowledge modules, table selection) would make 5 of 8 traceable in ~1 day.

**Critical Finding — UNDERSTAND/HYPOTHESIZE Boundary Is Design Debt:** C4 sub-checks perform metric registry lookups, schema discovery via Socrates MCP, pipeline freshness SQL, and query log context — UNDERSTAND is already investigating. The agent drew the boundary as "metadata vs investigation data" but admitted "the line is fuzzy." Fix: formalize the UNDERSTAND Output Contract (metric, surface, time range, magnitude, cohort) as a validated schema with explicit UNKNOWN handling.

**Invisible Decision (metric_direction):** Which way is "bad" for a metric. If wrong, every downstream hypothesis tests the wrong direction. Not traced, not validated.

**Additional gaps identified:** F8 (resume investigation input type not analyzed as failure mode), Socrates MCP single-point-of-failure at scale, and evaluation set contamination (24 SEV archive incidents used for eval are also loaded as knowledge source for Complex investigations).

**Key risk:** Mis-classification is a silent terminal failure. The system doesn't know it's investigating the wrong question.

### HYPOTHESIZE: The Hybrid — And the System's Actual Workhorse

**Strength:** Best balance of code and prompt control. The agent produced the strongest self-analysis in the entire audit series (scorecard: Honesty 10/10, Self-awareness 10/10). Identified 7 harness decisions with 5 implicit sub-decisions, 6 model decisions with 6 implicit biases, 9 failure modes. Quality escalated across Q1→Q5.

**Critical Finding — HYPOTHESIZE Is Not a Generation Phase, It's Generate+Test:** The pipeline documentation suggests HYPOTHESIZE generates hypotheses and DISPATCH tests them. Reality: HYPOTHESIZE runs SQL queries for H_null (variance test), H0 (denominator check), H_exp (experiment check), temporal shape analysis, and DKS digest refresh. The "generation" phase is actually doing ~40% of the investigation. H_null in particular has **veto power** — if movement is within variance, the investigation may stop before any other hypothesis is generated. H_null is not a hypothesis; it's a gate. Fix: evaluate H_null accuracy as a standalone binary classifier (REJECTED/NOT_REJECTED), separate from hypothesis generation eval.

**Critical Finding — Shape-to-Priority Table Is Harness-Manufactured Anchoring Bias:** The shape-to-priority mapping (line 609-614) instructs: step-function → prioritize deployments, gradual drift → population shift. The agent assessed this as "correct 80% of the time but wrong when a step-function coincides with a non-deployment cause." This is not a model reasoning failure — the harness is encoding a heuristic that creates systematic bias. When the 20% case occurs, the harness has already poisoned the model's hypothesis ranking. Current protections (H0/H_exp always-on, Category Coverage Check) provide partial defense. Missing: no "contrarian hypothesis" prompt, no automatic re-ranking if top hypothesis rejected. Fix: add contrarian hypothesis requirement ("if highest-priority hypothesis involves temporal coincidence, generate one alternative that explains the same shape without it").

**Critical Finding — No Feedback Loop from DISPATCH/SYNTHESIZE Back to HYPOTHESIZE:** The system is single-pass generative. Whatever hypotheses HYPOTHESIZE produces on the first attempt are the only hypotheses that will ever be investigated. If the correct root cause isn't in the initial set, the investigation fails with "did not converge" — no mechanism to try again. Combined with HF1 (missing hypothesis is terminal), the system has exactly one shot at generating the right hypothesis set. Every other design decision is trying to make that one shot as good as possible.

**Critical Finding — F4 (False Confidence) Is the Most Dangerous UNDERSTAND Propagation:** The agent's severity ranking contradicts intuition: F4 (false confidence) > F2 (scope error) > F1 (misclassification). F1/F2 produce wrong inputs that may become visible when SQL returns unexpected results. F4 produces inputs that *look correct* — UNDERSTAND filled all fields confidently, but some are wrong. HYPOTHESIZE has no UNKNOWN trigger, proceeds confidently down the wrong path. The Input Contract's UNKNOWN handling only helps when UNDERSTAND knows it doesn't know; it does nothing for confidently-wrong inputs.

**Critical Finding — HypothesisBrief Schema Creates Structural Blind Spots:** The 6-field schema (id, category, mechanism, falsification_query, expected_direction, priority) has critical limitations: no multi-causal expression (can't express interaction effects), one-sentence mechanism field (can't capture multi-step causal chains), and missing fields (no `source` for playbook-vs-first-principles tracking, no `expected_magnitude` for effect-size proportionality, no confidence or interaction fields).

**Six Implicit Model Biases Identified:** Recency bias in DKS digests, anchoring to H_null verdict when barely rejected, playbook conformity bias, temporal shape anchoring, single-cause bias from independent hypothesis modeling, and survivorship bias in SEV archive (only contains detected incidents, systematically missing novel failure modes).

**Invisible Decision (hypothesis inclusion/exclusion):** What hypotheses make the cut. The most consequential filter in the pipeline because it defines the investigation's search space.

**Additional gaps:** H_null as binary classifier has no dedicated eval, playbook existence is not validated at HYPOTHESIZE entry, no analysis of what happens when multiple conditional triggers fire simultaneously, H0→hypothesis framing dependency is implicit (H0 shows denominator-driven but harness doesn't enforce adjusting subsequent hypotheses).

**Key risk:** The failure mode is "the right hypothesis was never tested." This is undetectable from within the system because you can't measure what you didn't investigate. The 70/20/10 playbook coverage estimate (~70% match, ~20% partial, ~10% genuinely novel) means the 10% novel tail is where the system is most likely to fail and least likely to know it.

### DISPATCH: The Prompt Disguised as a Harness

**Strength:** The general-purpose sub-agent architecture is elegant — one agent template handles all hypothesis types through context specialization. Batch execution provides parallelism. The finding.md structure (verdict, confidence table, evidence for/against) creates useful standardization. Agent's self-awareness about its own gaps (Decision 5, emergent hypothesis suppression, narrative-to-data verification) was notably stronger than in previous stages. The dispatch_decision trace event proposal is architecturally consistent with HYPOTHESIZE tracing.

**Critical Finding — DISPATCH Is a Prompt, Not a Harness:** Every gate in DISPATCH (category coverage, count threshold, C7 readiness, H0/SRM pre-checks, batch limit) is a prompt instruction. The 4-sub-agent limit is a prompt instruction (line 1068), not an API constraint — `invoke_subagents` would accept 5 or 6. If the model skips the SRM check for experiments, the investigation proceeds on invalid data and nothing catches it. The only externally enforced constraint is session directory creation. This is the structural inverse of UNDERSTAND's Manifest Routing Trap: UNDERSTAND was too rigid, DISPATCH is too soft. The system hasn't found a consistent philosophy for harness vs model control.

**Critical Finding — Sub-Agent Context Construction (Decision 5) Is the Highest-Leverage Untraced Decision in the Entire System:** The harness provides an 8-item template, but the model decides what knowledge files to include, which corrections to surface, which learnings to scope, which pitfalls are relevant, and how much schema discovery to inject. Currently not tracked. Every downstream sub-agent failure has a potential root cause in Decision 5 that is unattributable. If a sub-agent gets wrong answer, you can't distinguish model reasoning failure from context the Lead Agent never injected. Agent's Q5 proposal (structured trace event with completeness diff) is excellent and P0-level.

**Critical Finding — "General Purpose" Sub-Agent Architecture Bottlenecks All Specialization Through Decision 5:** No routing table exists. Every sub-agent is dispatched as "General Purpose" — a SAIN hypothesis and a denominator hypothesis are investigated by identically-configured sub-agents. All hypothesis-type-specific investigation intelligence flows through the untraced Decision 5 context construction. The Lead Agent reads full knowledge modules (corrections.yaml ~400 lines, global.md ~270 lines) during HYPOTHESIZE, but sub-agents receive only pre-scoped excerpts. SEV Archive and Investigation Playbooks are not injected into sub-agent context at all. This is a deliberate simplicity choice, but it makes Decision 5 load-bearing in a way the system doesn't acknowledge or measure.

**Critical Finding — Emergent Hypothesis Discovery Is Structurally Suppressed:** Sub-agent is instructed to "Stay scoped to your assigned hypothesis — do not investigate other hypotheses" (line 735). finding.md has no field for observations outside assigned hypothesis. C9 checks for finding existence and execution success, not emergent signals. This directly interacts with HYPOTHESIZE's One-Shot Constraint — the only chance to recover from a missing hypothesis is if a sub-agent discovers it during investigation, and the current design actively prevents this through three reinforcing mechanisms: prompt instruction, no output field, and C9 not checking for it. Fix: add `## Adjacent Observations` section to finding.md + soften scoping instruction.

**Critical Finding — Hallucinated Evidence (DF4) Is the Most Dangerous Output Class:** Sub-agent produces numbers in finding.md that don't match results/*.json — interpolates from partial results, confuses data from two queries, or generates finding before query completes. C13 Post-Query Validation catches structural invalidity (rate >100%, negative counts) but does NOT verify narrative numbers match result JSON. Agent's example: "sub-agent could report 'rate dropped from 72.3% to 70.1%' when actual data shows 72.3% to 71.8% — passes all current checks." Fix: automated narrative-to-data verification extracting numeric claims from finding.md and comparing against results/*.json.

**Critical Finding — Sub-Agent Context Gaps Degrade Investigation Calibration:** Two items excluded from sub-agent context are genuine gaps: (1) QuestionBrief not passed — sub-agent knows hypothesis but not user's actual concern or decision context, (2) H_null magnitude not passed — sub-agent can't calibrate whether borderline or strong movement. Token budget analysis (Q3e) shows sub-agents use ~17K-32K of ~55K budget — headroom exists for a compact `investigation_context` field. This manifests as DF7 (Wrong Domain Knowledge): structurally valid findings with misinterpreted data. Currently undetectable.

**Missing Failure Mode Identified (DF11 — Prompt Gate Bypass):** Since all DISPATCH gates are prompt instructions, there's a meta-failure: the model simply doesn't execute a gate it's instructed to perform. This doesn't exist in UNDERSTAND or HYPOTHESIZE because those have actual harness code for critical gates. DF11 is the failure mode that justifies promoting key gates to code enforcement.

**Failure Mode Rating Adjustments:** DF3 (Inconclusive Finding) upgraded to HIGH — 1 INCONCLUSIVE per batch = 25-33% capacity loss. DF5 (Batch Sequencing Waste) downgraded to LOW — low practical impact at current scale. DF8 (Emergent Evidence Loss) upgraded to HIGH — only recovery path for HF1 (Missing Hypothesis); compound impact with One-Shot Constraint.

**Invisible Decision (sub-agent context construction):** What context each sub-agent receives determines what evidence it can find. More consequential than any individual model decision because it silently determines the evidence ceiling for every hypothesis.

**Tracing Status:** 3 of 11 decision areas tracked. 8 untraced. Three untraced areas are critical-severity (Decision 5 context construction, emergent hypothesis discovery, narrative-to-data consistency).

**Key risk:** Hallucinated evidence (DF4). A sub-agent generates confident findings from misinterpreted data, and SYNTHESIZE builds a plausible narrative around the wrong evidence. This is the system's most dangerous failure class because the output looks correct.

### SYNTHESIZE: The Unguarded Final Stage

**Strength:** The conceptual design is thorough — reconciliation logic, 7-cap confidence framework, effect-size proportionality checks, residual analysis, validation dispatch. The synthesis_decision trace event schema from the agent's Q5 response is genuinely excellent — PR-ready, addresses 5 of 13 failure modes.

**Weakness:** Every one of these well-designed features is a prompt instruction with no code enforcement. Session 118 demonstrated ~50% compliance on "mandatory" items. Three required report sections omitted. Effect-size proportionality check skipped despite "mandatory before assigning grade." Validation Dispatch not exercised (and may not exist). The system's most consequential stage is its least protected.

**Invisible Decision (root cause narrative selection):** The terminal amplifier. SM-1 constructs a coherent narrative around whatever upstream stages produced. If any of the three upstream Invisible Decisions were wrong, SM-1 polishes the error into a professional-sounding report that an engineer will act on.

**Key risk:** The report looks authoritative regardless of whether the conclusion is correct. The system has no self-doubt mechanism — it doesn't know when it doesn't know.

---

## System-Level Failure Modes

Beyond the individual stage failure modes (which total 40+ across all stages), several system-level failure patterns emerge from the cross-stage analysis:

### SYS-1: Silent Cascade Failure

An error at any stage propagates undetected through all downstream stages, with each stage adding plausible-sounding interpretation that makes the error harder to identify. The four Invisible Decisions form a causal chain where each inherits and amplifies upstream errors.

**Example scenario:** UNDERSTAND classifies metric_direction wrong → HYPOTHESIZE generates hypotheses for the wrong direction → sub-agents gather evidence that appears to confirm the wrong direction (because data patterns exist in every direction) → SYNTHESIZE writes a confident report with the wrong root cause → engineer takes the wrong action.

**Detection:** None currently. Would require tracing the full Invisible Decision chain and comparing each decision against independent validation.

### SYS-2: False Confidence from Structural Compliance

The system can produce structurally perfect reports (all sections present, proper formatting, confidence grades, evidence citations) that are substantively wrong. Structural compliance creates an appearance of rigor that masks analytical errors.

**Example scenario:** Report has PM Summary, detailed analysis, SQL Query Index, confidence grade B+, and recommends specific action — but the winning hypothesis explains only 30% of the metric movement and the other 70% is unexplored because the hypothesis space was too narrow.

**Detection:** Effect-size proportionality check was designed to catch this, but Session 118 shows it was skipped despite "mandatory" language. Code enforcement of this check (P1-S2) is the minimum fix.

### SYS-3: Graceful-Looking Incompleteness

The system acknowledges gaps in its Uncertainty section without treating them as investigation failures. This creates reports that *seem* thorough because they mention what they don't know, without *acting* on the gaps.

**Example from Session 118:** Report acknowledges "why long clicks decrease" remains unexplained, but doesn't flag this as an incomplete investigation requiring follow-up. A reader sees the acknowledgment and thinks the system was diligent, when in fact it stopped investigating a major component of the metric movement.

**Detection:** Requires comparing residual unexplained movement against a threshold and flagging when significant portions of the metric change remain unexplored.

### SYS-4: Progressive Context Loss

Critical information established in early stages is progressively lost as it flows downstream. The most important example: `decision_context` (what action the user is trying to take) is captured at C3 in UNDERSTAND but buried in a YAML checkpoint by the time SYNTHESIZE runs. The report answers "what happened?" but not "what should I do about it?" — even though the system originally knew what decision the user was trying to make.

**Other examples:** QuestionBrief metadata gets compressed into context_snapshot; hypothesis rationale disappears by DISPATCH; sub-agent reasoning is compressed into finding.md narrative.

**Detection:** Compare final report against original QuestionBrief for decision_context alignment. Automatable with LLM-as-judge or keyword matching.

### SYS-5: Compounding Memory Bias

The system writes learnings after each investigation but has no mechanisms for learning quality control, expiration, scope limitation, or validation. Over time, this creates a self-reinforcing cycle where the system increasingly finds what it expects to find.

**Projected trajectory:** At 10 investigations, manageable. At 50, noticeable pattern convergence. At 200+, the system may be unable to identify genuinely novel root causes because its hypothesis generation is anchored to historical patterns that may no longer apply.

**Detection:** No current mechanism. Requires memory metadata (timestamps, confidence levels, scope boundaries) and periodic review triggers.

---

## Quantified Assessment

### By the Numbers

| Metric | Value | Detail |
|---|---|---|
| Total decisions mapped | ~55+ across all stages | UNDERSTAND: 8 harness, HYPOTHESIZE: 7 harness + 6 model + 11 implicit, DISPATCH: 6 harness + 5 model, SYNTHESIZE: 12 harness + 14 model |
| Code-enforced decisions | ~8 (mostly UNDERSTAND) | Manifest routing, C1 gate, some HYPOTHESIZE checks |
| Prompt-instructed decisions | ~47+ (everything else) | All of DISPATCH; all of SYNTHESIZE; most of HYPOTHESIZE model decisions |
| Invisible Decisions identified | 4 (one per stage, all untraced) | metric_direction → hypothesis inclusion → context construction → narrative selection |
| Structural feedback loops | 0 confirmed | Validation Dispatch may be phantom (agents/validation.md unverified) |
| Failure modes catalogued | 40+ across all stages | UNDERSTAND: 7 (F1-F7), HYPOTHESIZE: 9 (HF1-HF9), DISPATCH: 11 (DF1-DF11), SYNTHESIZE: 14 (SF1-SF14) |
| CRITICAL/Terminal failure modes | 3 | HF1 (missing hypothesis), DF4 (hallucinated evidence), SF-9 (hallucinated synthesis) |
| Implicit model biases identified | 6 (HYPOTHESIZE) | Recency, H_null anchoring, playbook conformity, shape anchoring, single-cause, survivorship |
| Session 118 "mandatory" compliance (SYNTH) | ~50% | 3 mandatory items skipped |
| Session 118 required section compliance (SYNTH) | 73% (8/11) | Validation Log, SQL Query Index, Sources omitted |
| Total prioritized action items | 35 items across all stages | Phase 1: 8, Phase 2: 11, Phase 3: 8, Phase 4: 8 |
| Agent self-audit quality | A- to A across 20 questions | Strongest: HYPOTHESIZE (Honesty 10/10, Self-awareness 10/10) |

### Stage Maturity Ratings

| Stage | Design Quality | Implementation Robustness | Observability | Overall |
|---|---|---|---|---|
| UNDERSTAND | Strong | Good | Partial | **Production-adjacent** |
| HYPOTHESIZE | Strong | Adequate | Low | **Advanced prototype** |
| DISPATCH | Strong | Weak (prompt-only) | Low | **Prototype** |
| SYNTHESIZE | Strong (on paper) | Weak (prompt-only, ~50% compliance) | Very low | **Prototype** |

The consistent pattern: design quality is strong everywhere, implementation robustness degrades downstream, and observability is poor throughout.

---

## Recommended Fix Strategy — All Stages

### Phase 1: Stop the Bleeding (Week 1)

SYNTHESIZE is the highest-consequence, least-protected stage — but P0 items exist across all four stages.

| # | Action | Stage | Impact | Effort |
|---|---|---|---|---|
| 1 | **Implement synthesis_decision trace event** (per 5d schema + narrative_decision extension) | SYNTH | Addresses 5 of 13 SYNTHESIZE failure modes with one instrumentation point | 1-2 days |
| 2 | **Verify agents/validation.md exists** — confirm Phase 4.5 ever executed | SYNTH | Confirms whether system's only feedback mechanism is real or phantom | Hours |
| 3 | **Code-enforce C9 completion, Validation Dispatch blocking, mandatory report sections** | SYNTH | Transforms SYNTHESIZE from ~50% compliance to code-enforced critical path | 3-4 days |
| 4 | **Log full dispatch context per sub-agent** as trace event + completeness diff (P0-D1) | DISPATCH | Unblocks all DISPATCH failure attribution; reveals evidence ceiling per hypothesis | 1-2 days |
| 5 | **Archive HypothesisBrief set in pipeline_state.yaml** + low-confidence alert | HYPO | Bootstraps all hypothesis evaluation; enables HF1 proxy detection | 2-3 days |
| 6 | **Add `source` field to HypothesisBrief** (playbook/first_principles/conditional/always_on) | HYPO | Enables playbook coverage measurement (70/20/10 validation); detects HF4 | 1 day |
| 7 | **Create H_null binary classifier eval** (separate from hypothesis generation eval) | HYPO | H_null has veto power over entire investigation — highest-impact binary decision in pipeline | 1-2 days |
| 8 | **Implement 3 UNDERSTAND tracing additions** (manifest route, knowledge modules, table selection) | UNDERSTAND | Makes 5 of 8 decisions traceable; unlocks F1/F3/F7 detection | 1 day |

Estimated effort: ~12-16 engineering days. These changes give you observability into the highest-leverage decisions at every stage and code enforcement where compliance is lowest.

### Phase 2: Close Critical Gaps (Weeks 2-3)

| # | Action | Stage | Impact | Effort |
|---|---|---|---|---|
| 9 | **Add `## Adjacent Observations` to finding.md** + soften "stay scoped" instruction + C9 check | DISPATCH | Opens only recovery path for HF1 (missing hypothesis) — the One-Shot Constraint's escape valve | 0.5 day |
| 10 | **Add `investigation_context` to dispatch template** (QuestionBrief.goal, decision, H_null magnitude) | DISPATCH | Fixes sub-agent calibration gaps; sub-agents currently don't know user's question or movement significance | 0.5 day |
| 11 | **Promote SRM check to code-enforced gate** | DISPATCH | False PASS on SRM is terminal; prompt compliance not guaranteed (DF11) | 1 day |
| 12 | **Implement narrative-to-data verification** (finding.md claims vs results/*.json) | DISPATCH | Detects DF4 (hallucinated evidence) — most dangerous output class | 1-2 days |
| 13 | **Code-enforce effect-size proportionality check** (SM-11) | SYNTH | Session 118: skipped despite "mandatory before assigning grade" | 1 day |
| 14 | **Add decision_context to synthesis prompt** + C10 checklist item | SYNTH | Reports answer "what should I do?" not just "what happened?" | Hours |
| 15 | **Formalize UNDERSTAND output contract** as validated schema with explicit UNKNOWN handling | UNDERSTAND | Separates F3 (under-specification, manageable) from F4 (false confidence, insidious) | 1 day |
| 16 | **Default manifest routing to Complex for ambiguous inputs** (Option C) | UNDERSTAND | Prevents terminal under-scoping; accept token cost to avoid silent failure | 0.5 day |
| 17 | **Add `expected_magnitude` to HypothesisBrief** + C10 proportionality cap | HYPO | Effect-size proportionality gap: experiment gets HIGH confidence when its 0.1pp can't explain 3pp drop (HF9) | 1 day |
| 18 | **Add contrarian hypothesis prompt requirement** | HYPO | When top hypothesis is temporal coincidence, force alternative explanation. Counters shape-to-priority anchoring bias | Hours |
| 19 | **Add maximum hypothesis threshold** (>6 WARN, >10 ERROR) | HYPO | Prevents hypothesis explosion (HF2) | Hours |

Estimated effort: ~8-10 engineering days. These close the most dangerous failure paths at each stage.

### Phase 3: Build Evaluation Infrastructure (Weeks 3-5)

| # | Action | Stage | Impact | Effort |
|---|---|---|---|---|
| 20 | **Implement report quality score formula** as automated monitoring | SYNTH | Floor metric: any report below 70 flagged. Needs human calibration quarterly | 1 day |
| 21 | **Build 5-10 canonical finding.md test fixtures** for isolation testing | SYNTH | Enables stage-specific evaluation — distinguish synthesis quality from upstream | 2-3 days |
| 22 | **Implement Tier 1+2 failure mode detection** (code + prompt traces) | SYNTH | Automated detection for 8 of 13 SYNTHESIZE failure modes | 2-3 days |
| 23 | **Label 24 SEV archive cases with ground truth** + create 4-6 held-out eval cases | UNDERSTAND | Bootstraps eval harness. Critical: held-out set must NOT be in knowledge sources (eval contamination — 24 SEV incidents used for eval are also loaded as knowledge for Complex investigations) | 2 days |
| 24 | **Design memory metadata system** (timestamps, confidence, scope, periodic review) | SYNTH | Foundation for memory quality control; prevents compounding bias at scale | 1-2 days |
| 25 | **Make H0 → hypothesis framing dependency explicit** | HYPO | If H0 shows denominator-driven, deprioritize quality regression hypotheses — currently implicit | Hours |
| 26 | **Add playbook existence validation** at HYPOTHESIZE entry | HYPO | Silent failure if metric family routes to nonexistent playbook file | Hours |
| 27 | **Archive results/*.json with session records** for future replay testing | DISPATCH | Enables full DISPATCH replay testing without live SQL dependency | Hours |

Estimated effort: ~10-12 engineering days. Gives you the ability to measure and trend system quality.

### Phase 4: Structural Improvements (Months 2-3)

| # | Action | Stage | Impact | Effort |
|---|---|---|---|---|
| 28 | **Structured `## Queries Executed` in finding.md** | SYNTH | Fixes evidence bottleneck — compilation task vs discovery task | Hours |
| 29 | **Evidence AGAINST section in reports** | SYNTH | Structural resistance to narrative bias (SF-6) | Hours |
| 30 | **Memory quality system** (expiration, periodic review, confidence levels) | SYNTH | Prevents compounding memory bias at scale (SF-5 + SF-10 loop) | Design |
| 31 | **SYNTHESIZE spot-check of raw results** for SEV-level investigations | SYNTH | Breaks the two-inference-layer evidence bottleneck | 1 day |
| 32 | **Design hypothesis re-generation loop** (SYNTHESIZE → HYPOTHESIZE) | HYPO/SYNTH | If confidence < C and no winner, generate expansion prompt for lightweight HYPOTHESIZE re-run. Breaks the One-Shot Constraint | 3-5 days |
| 33 | **Design specialized sub-agent protocols** per hypothesis category | DISPATCH | Reduces Decision 5 load-bearing weight; alternative to General Purpose architecture | Design |
| 34 | **Inter-batch context flow** — adjust batch 2 dispatch based on batch 1 findings | DISPATCH | Currently batches are independent; batch 2 may investigate already-explained hypotheses | 2-3 days |
| 35 | **Build full ground truth eval framework** with human-labeled cases | ALL | Ultimate quality metric — measures whether system gets right answer, not just follows process | 1-2 weeks |

**Total effort across all phases: ~45-58 engineering days (~2-3 months)**
**Phase 1+2 alone (~20-26 days) transforms the system from strong prototype to defensible production tool.**

---

## What This System Could Become

The gap between what this system *is* and what it *could be* is surprisingly small in engineering terms. The design is already right. The domain model is sophisticated. The investigation logic works. The agent demonstrates strong self-awareness and honest self-assessment.

What's missing is the boring stuff: code enforcement of decisions that are already well-specified in prompts, structured tracing of decisions that are already being made, and validation of outputs that already have quality criteria defined. The system's prompts describe a rigorous investigation process — the harness just doesn't ensure the process is followed.

With Phase 1-2 (~20-26 engineering days), this system would have:
- Code-enforced critical path through SYNTHESIZE (the most consequential stage)
- Full Invisible Decision chain tracing across all four stages
- Observability into the highest-leverage decisions at every stage
- The pipeline's first structural feedback loop (Validation Dispatch)
- Adjacent Observations as an escape valve for the One-Shot Constraint
- Sub-agents that know the user's question and movement significance
- Narrative-to-data verification catching hallucinated evidence
- H_null evaluated as the standalone gate it actually is
- Shape-to-priority anchoring bias countered by contrarian hypothesis requirement
- UNDERSTAND routing that defaults to over-scoping rather than under-scoping

That's a production-grade automated analysis system. The foundations are there. They just need the last 20% of implementation that makes the difference between a strong prototype and a reliable tool.

---

## Closing Notes

**For the Search engineers who will review this:** The system your team built thinks well. The investigation logic, domain decomposition, and confidence framework are genuinely sophisticated. The audit findings are not about design quality — they're about implementation discipline. The prompts describe the right behavior; the harness just needs to ensure it happens.

**For prioritization:** If you do nothing else, implement the synthesis_decision trace event and the DISPATCH context trace event. Two days of work, two JSON blobs per investigation, and you can suddenly see inside the two black boxes that produce your sub-agent evidence and final reports. Everything else builds on that visibility.

**For long-term architecture:** The Inverse Enforcement Problem is the fundamental thing to fix. Move code enforcement downstream toward the output layer. SYNTHESIZE should be the most structurally protected stage, not the least. The system should get *more careful* as it approaches its final answer, not less. And break the One-Shot Constraint — the system's inability to re-generate hypotheses when initial investigation fails is the deepest structural limitation.
