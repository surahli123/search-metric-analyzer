# PRD: Search Quality Metric Movement Diagnosis Agent

## 1) Document Control
- Author: Data Science / Search Quality
- Date: 2026-02-07
- Status: Draft v1 (research-backed)

### Terminology (canonical for this PRD)
- `AI Search (SAIN)`: answer-generation and answer-orchestration stage that can affect user behavior independently from core retrieval/ranking.
- `QSR`: query-success metric family; must be analyzed with answer-engagement and click-path decomposition.
- `DLCTR`: discounted long-click metric; must be analyzed with rank position/depth decomposition.

## 2) Background and Problem Statement
Search quality teams routinely observe movement in topline metrics (e.g., NDCG, CTR, reformulation rate, abandonment, latency-adjusted success), but diagnosis is slow and manual. Analysts often spend cycles stitching logs, checking experiment integrity, slicing dimensions, and validating hypotheses before they can identify likely root causes.

Goal: build an agent that shortens time-to-diagnosis while preserving statistical rigor and auditability.

## 3) Research Summary: Prior Best Practices

### 3.1 Agentic analytics pattern (LLM + tools + governance)
- OpenAI’s in-house data agent describes an architecture where a language model plans/executes analysis through tools, with strong emphasis on reliability controls, evaluability, and analyst-in-the-loop operation.
- Practical takeaway: treat the agent as an orchestrator over trusted analytics tools, not a free-form answer engine.

Source:
- OpenAI, *Inside our in-house data agent* (2025): https://openai.com/index/inside-our-in-house-data-agent/

### 3.2 Metric trustworthiness before diagnosis
- Microsoft ExP’s experimentation guidance emphasizes prechecks (sample ratio mismatch, instrumentation correctness, triggered analysis correctness) and trustworthy decision criteria before interpretation.
- Practical takeaway: diagnosis pipeline should gate on data-quality and experiment-integrity checks before any RCA.

Source:
- Microsoft Research ExP, *Trustworthy Online Controlled Experiments: Five Puzzling Outcomes Explained* (KDD 2019): https://www.microsoft.com/en-us/research/publication/trustworthy-online-controlled-experiments-five-puzzling-outcomes-explained/

### 3.3 Automated anomaly detection + root-cause ranking in metric platforms
- LinkedIn’s ThirdEye formalizes KPI monitoring with anomaly detection and root cause analysis over dimensions and correlated metrics.
- Practical takeaway: combine robust anomaly detection with dimension-contribution ranking and metric-relationship graphs.

Source:
- LinkedIn Engineering, *ThirdEye: A framework for monitoring and root cause analysis of operational metrics* (2019): https://engineering.linkedin.com/blog/2019/thirdeye-open-source
- Project docs: https://thirdeye.readthedocs.io/

### 3.4 Causal methods for movement attribution
- CausalImpact (Bayesian structural time series) is a widely used approach for estimating causal effect of interventions on time series when randomized experiments are unavailable.
- Practical takeaway: include causal fallback mode for non-experimental regressions (launches, traffic shifts, seasonality shocks).

Source:
- Brodersen et al., *Inferring causal impact using Bayesian structural time-series models* (Annals of Applied Statistics, 2015): https://projecteuclid.org/journals/annals-of-applied-statistics/volume-9/issue-1/Inferring-causal-impact-using-Bayesian-structural-time-series-models/10.1214/14-AOAS788.full

### 3.5 Site Reliability operations pattern for incident response
- Google SRE guidance stresses clear SLIs/SLOs, burn-rate/alerting discipline, and incident response workflows that can be adapted for metric incidents.
- Practical takeaway: adopt a metric-incident lifecycle (detect, triage, diagnose, mitigate, postmortem) with explicit ownership and runbooks.

Source:
- Google SRE Book / Workbook: https://sre.google/books/

Internal architecture context brief:
- See `/Users/surahli/Documents/New project/Search_Metric_Analyzer/search-system-findings-brief.md` for workflow context, inferred QSR/DLCTR debugging challenges, and triage hypotheses.

## 4) Product Vision
An analyst copiloting agent that:
1. Detects and validates metric movement.
2. Produces ranked, testable root-cause hypotheses with quantified evidence.
3. Recommends next analyses/actions.
4. Stores decisions and evidence for reproducibility.

## 5) Goals and Non-Goals

### Goals
- Reduce median time-to-first-plausible-cause by >=50%.
- Increase diagnosis precision@3 (top-3 hypotheses contains true cause) to target >=70% in offline replay.
- Enforce statistical quality gates (SRM checks, variance/confidence reporting, guardrail validation).
- Provide audit trail: queries, datasets, model versions, and rationale.

### Non-Goals (v1)
- Fully autonomous rollback/launch decisions.
- Replacing experimentation platform or observability stack.
- Long-horizon strategic planning.

## 6) Users and Primary Jobs-to-be-Done
- Search Data Scientists: quickly explain movement and prioritize deep-dives.
- Search Engineers / PMs: understand likely drivers and mitigation options.
- On-call quality owners: triage metric incidents with consistent playbooks.

## 7) Functional Requirements
1. Movement Intake
- Inputs: metric, time window, affected population, experiment IDs, release markers.
- Trigger modes: scheduled monitoring, threshold alert, ad-hoc user request.

2. Trust Gates (must-pass checks)
- Data freshness/completeness.
- Logging/instrumentation health.
- Experiment validity checks (including SRM-like tests where applicable).
- Guardrail metric sanity.

3. RCA Engine (multi-stage)
- Stage A: Change decomposition by dimensions (query class, locale, device, vertical, cohort, rank bucket, latency bucket).
- Stage B: Correlated-metric graph analysis (e.g., CTR down + reformulation up + latency up).
- Stage C: Event alignment (deployments, indexing changes, traffic mix shifts, policy changes).
- Stage D: Causal estimation mode when randomized evidence unavailable.
- Stage E: AI Search (SAIN) attribution mode for answer-generation and answer-policy effects.

3.1 Required QSR and DLCTR Decomposition
- Decompose QSR and DLCTR by SAIN-shown vs SAIN-not-shown cohorts.
- Decompose QSR by answer-engagement path vs click path contribution.
- Decompose DLCTR by position/depth buckets and source/interleaving share.
- Report each decomposition with effect size, uncertainty, and segment coverage.

3.2 Overlap-Aware Attribution Policy
- Detect concurrent experiments/releases that overlap the incident window across stages (rewrite, retrieval, ranking, SAIN, UI, logging).
- If overlap remains unresolved, downgrade attribution confidence by one level and mark output as "multi-candidate unresolved overlap."
- Prevent single-cause claims when two or more plausible overlapping changes remain after disconfirming checks.

4. Hypothesis Generation and Ranking
- Generate candidate causes with evidence scores:
  - Effect size
  - Statistical confidence
  - Temporal alignment
  - Mechanistic consistency with known metric DAG
- Return top-k hypotheses with confidence bands and disconfirming tests.

4.1 Failure Taxonomy (Actionable v1)
| Failure class | Likely stage(s) | Metric signature (QSR/DLCTR and guardrails) | Fast validation checks | Likely owning team(s) |
|---|---|---|---|---|
| Query rewrite drift | Query understanding/rewrite | QSR down on ambiguous/long-tail queries; DLCTR mixed; reformulation up | Compare rewrite output diffs on fixed query set; bucket by query intent class | Query Intelligence / NLP |
| Retrieval coverage loss | Candidate retrieval | QSR down and DLCTR down; recall proxies down; zero-result rate up | Candidate-set size and source coverage deltas by connector/query class | Retrieval / Connector |
| Reranker miscalibration | Reranking | DLCTR down with stable/improving recall; rank-depth clicks shift deeper | Offline re-score with previous model; feature importance and score distribution shift | Ranking / Relevance |
| Interleaving policy shift | Cross-source merge | DLCTR down from deeper click depth; QSR flat/mixed; source mix shifts | Source contribution and position share before/after; blend-policy diff | Ranking Platform |
| Permission filtering regression | Permission/policy filtering | QSR down for specific tenant/cohort; accessible-result guardrail drops | Pre/post-filter candidate counts; ACL decision error rate by product | Auth/Platform + Integrations |
| SAIN generation/policy regression | AI Search (SAIN) | QSR down in answer-shown cohorts; DLCTR mixed/down; reformulation up after answer view | Compare SAIN-on vs SAIN-off cohorts; answer quality judgments; policy/version diffs | AI Search / Answer |
| Telemetry/metric pipeline issue | Interaction logging + metric layer | Abrupt QSR/DLCTR jump without plausible behavioral correlate | Schema/version change audit; missing-event rates; replay checks | Data Platform / Metrics |

5. Analyst Interaction
- Conversational workflow with deterministic tool calls.
- Drill-down commands that generate reproducible SQL/notebooks.
- “Why not?” mode to challenge top hypothesis.

6. Outputs
- Incident brief (1-pager), ranked hypotheses, suggested mitigations, and next-step checklist.
- Machine-readable JSON for dashboards and ticketing integration.

6.1 Minimum Evidence Packet Contract (for escalation)
- `incident_id`: unique incident identifier.
- `time_window`: start/end timestamps and baseline window.
- `metrics_moved`: QSR, DLCTR, and guardrails with effect size and uncertainty intervals.
- `impacted_segments`: top positive/negative contributors by dimension and cohort.
- `tested_hypotheses`: tested and disconfirmed hypotheses with evidence pointers.
- `release_experiment_links`: linked deployments, experiment IDs, and overlap flags.
- `owner_recommendation`: likely owner function, next action, and ETA target.
- `confidence_and_abstain`: confidence level and abstain reason if unsupported attribution.
- `artifact_links`: SQL/jobs/notebooks/report artifacts for reproducibility.

## 8) Non-Functional Requirements
- Reliability: >99.5% successful analysis job completion.
- Latency: P50 < 2 min for standard incident, P95 < 10 min.
- Security: RBAC, row/column-level data controls, PII-safe prompts.
- Reproducibility: same inputs produce traceable, versioned outputs.
- Explainability: every claim mapped to evidence artifacts.
- Observability for attribution:
  - Stable query/session IDs across rewrite, retrieval, ranking, SAIN, and metric pipelines.
  - End-to-end lineage from shown result -> click -> long click -> metric aggregation.
  - SAIN policy/version stamps in interaction logs for every answer-shown event.
  - Per-stage experiment/release annotations joinable to incident windows.
- Fail-safe requirement: if attribution is unsupported due to conflicting or insufficient evidence, output must return `insufficient_evidence` with required follow-up checks.

## 9) Proposed System Architecture
1. Orchestration Layer (LLM agent)
- Planner for analysis steps.
- Tool router (SQL engine, feature store, metric catalog, experiment logs, deployment events).
- Policy guardrails (allowed tools, data domains, output schema).

2. Analytics Layer
- Time-series anomaly detectors.
- Decomposition/attribution services.
- Causal inference services.
- Knowledge graph of metric dependencies.

3. Evidence Layer
- Metric definitions and owners.
- Experiment metadata.
- Release/indexing/event logs.
- Historical incident memory and resolved RCA cases.

4. Serving Layer
- Chat UI + API.
- RCA report generator.
- Integrations: PagerDuty/Jira/Slack/dashboard annotations.

## 10) Decision Policy (Best-Practice-Informed)
- Default hierarchy:
1. Validate integrity (no diagnosis before trust gates pass).
2. Prefer randomized evidence when available.
3. Use decomposition to localize affected segments.
4. Use causal estimation only with explicit assumptions and diagnostics.
5. Present multiple competing hypotheses and uncertainty.

10.1 Fail-safe and Abstain Policy
- If top hypotheses have overlapping confidence intervals and no disconfirming separation, abstain from single-cause conclusion.
- If unresolved overlap across concurrent experiments/releases exists, emit multi-candidate output with downgraded confidence.
- Required abstain payload: unresolved factors, blocking checks, owner escalation target, and next validation actions.

10.2 Deterministic Ranking Policy
- Use consistent scoring components for hypothesis ranking: effect size, statistical confidence, temporal alignment, mechanism consistency.
- Define deterministic tie-breaker order: higher disconfirming-test pass count -> broader impacted segment coverage -> lower model complexity.
- Calibrate confidence labels (`high`, `medium`, `low`) against offline replay benchmarks and review quarterly.

## 11) Evaluation Plan

Synthetic scenario validation pack:
- See `/Users/surahli/Documents/New project/Search_Metric_Analyzer/synthetic-validation-scenarios.md` for seasonality, L3/interleaver, SAIN, overlap, and logging-anomaly validation scenarios with pass/fail assertions. Includes numeric scenario knobs, confidence rubric, and long-click edge rules.
- Execution artifacts are written to `data/synthetic/synthetic_search_session_log.csv`, `data/synthetic/synthetic_metric_aggregate.csv`, `data/synthetic/validation_results.csv`, and `data/synthetic/validation_report.md`.

Required validator artifact contract (must be present for every run):
- `validation_results.csv` must include: `scenario_id`, `expected_label`, `predicted_label`, `diagnosis_score`, `confidence_label`, `penalty_flags`, `overall_pass`.
- `validation_report.md` must include: total scenarios, pass/fail counts, formula invariant violations, per-scenario table.
- Missing required fields/artifacts invalidates the run for rollout gating.

### Synthetic Acceptance Gate (required)
- Scenario pass requirement: `9/9` scenarios must pass.
- Formula invariants: `0` violations for `qsr_component_click == dlctr_value` and `qsr_value == greatest(dlctr_value, sain_success * sain_trigger)`.
- Overlap behavior: `S7` must not produce single-cause `high` confidence.
- Data-quality behavior: `S8` must produce `blocked_by_data_quality`.

### Generalization Guardrail (anti-overfitting)
- Phase A: pass synthetic acceptance gate above.
- Phase B: pass holdout historical replay that is not generated from synthetic scenario logic.
- Promotion to online evaluation is blocked unless both Phase A and Phase B pass.

### Offline (replay)
- Build benchmark from past metric incidents with known outcomes.
- Metrics:
  - Precision@k for true cause retrieval
  - MRR for cause ranking
  - Calibration of confidence scores
  - Expected calibration error (ECE) for confidence labels
  - Confidence reliability by label (`high`, `medium`, `low`)
  - Time-to-first-actionable-insight (simulated)

### Online (shadow + assisted)
- Compare analyst-only vs analyst+agent:
  - Time-to-diagnosis
  - Reopen rate of incidents
  - False-cause rate
  - User trust rating

### Quality Gates
- Hallucination checks: unsupported claim rate.
- SQL correctness tests on golden datasets.
- Safety checks for sensitive-data leakage.

### Scenario Re-Baselining and Threshold Tuning
- Recompute synthetic baseline calibration and scenario knobs at least quarterly.
- Trigger immediate re-baselining when either occurs:
  - Connector mix shifts by `>= 5` absolute points.
  - SAIN trigger rate shifts by `>= 5` absolute points.
  - Two consecutive validation runs fail signature checks for the same scenario family.
- Any re-baselining update must include updated baseline snapshot and changelog entry in validation artifacts.

## 12) Rollout Plan
1. Phase 0 (2-4 weeks): data contracts + metric catalog hardening.
2. Phase 1 (4-6 weeks): trust gates + decomposition MVP (no LLM autonomy).
3. Phase 2 (4-8 weeks): LLM orchestration with constrained tools and report generation.
4. Phase 3 (4-8 weeks): causal mode, incident memory, and online A/B evaluation.
5. Phase 4: broaden metric surface and automation level.

Phase promotion gates:
1. Phase 1 -> Phase 2 requires synthetic acceptance gate pass for two consecutive runs.
2. Phase 2 -> Phase 3 requires holdout replay pass plus false-cause rate <= `15%`.
3. Phase 3 -> Phase 4 requires sustained online false-cause rate <= `10%` for two release cycles and no unresolved ownership delays for SAIN-attributed incidents.

## 13) Risks and Mitigations
- Risk: spurious attribution from confounding.
- Mitigation: randomized evidence precedence, causal diagnostics, explicit assumptions.

- Risk: over-trust in fluent but weak explanations.
- Mitigation: evidence-linked outputs, confidence calibration, “show query/evidence” by default.

- Risk: data quality/instrumentation drift.
- Mitigation: hard fail trust gates, ownership and SLA on telemetry pipelines.

- Risk: operational complexity and tool fragility.
- Mitigation: staged rollout, narrow tool allowlist, replay-based regression testing.

## 14) Open Questions
- What is the canonical metric DAG for search quality and guardrails?
- Which dimensions are mandatory in v1 decomposition?
- What confidence threshold should trigger human escalation?
- Which incident classes qualify for automated recommendation vs manual-only?

## 15) Deferred P2 Risks (Phase 2+)
1. Overlap/confounding hardening with advanced causal controls
- Why deferred: v1 will use overlap-aware downgrade and abstain policies first; advanced causal controls require additional infra and benchmarking.
- Promotion trigger: false-cause rate remains above target after two release cycles despite v1 controls.
- Provisional owner: Data Science + Experimentation Platform.

2. SAIN-specific ownership and guardrail operating model hardening
- Why deferred: v1 introduces SAIN attribution paths first; operating guardrail ownership and paging policy require cross-org alignment.
- Promotion trigger: two or more SAIN-attributed incidents in a quarter with delayed mitigation due to ownership ambiguity.
- Provisional owner: AI Search / Answer + Search Quality Operations.

## 16) Appendix: Suggested Initial Tech Stack
- Warehouse: existing enterprise SQL platform.
- Orchestration: constrained agent runtime with tool schemas.
- Modeling: anomaly detection + BSTS/CausalImpact service.
- Artifacting: versioned report store + lineage metadata.

## 17) Source Links
- OpenAI in-house data agent: https://openai.com/index/inside-our-in-house-data-agent/
- Microsoft ExP trustworthy experimentation paper: https://www.microsoft.com/en-us/research/publication/trustworthy-online-controlled-experiments-five-puzzling-outcomes-explained/
- LinkedIn ThirdEye overview: https://engineering.linkedin.com/blog/2019/thirdeye-open-source
- ThirdEye documentation: https://thirdeye.readthedocs.io/
- CausalImpact paper (BSTS): https://projecteuclid.org/journals/annals-of-applied-statistics/volume-9/issue-1/Inferring-causal-impact-using-Bayesian-structural-time-series-models/10.1214/14-AOAS788.full
- Google SRE books/workbooks: https://sre.google/books/
