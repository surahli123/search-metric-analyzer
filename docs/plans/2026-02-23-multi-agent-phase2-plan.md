# Multi-Agent Phase 2 Plan (Full Architecture)

Date: 2026-02-23  
Owner: Search Metric Analyzer maintainers

## 1) Objective

Evolve the v1.5 minimal connector-investigator bridge into a production-grade
multi-agent diagnosis system while keeping deterministic contracts and
evaluation guardrails intact.

## 2) Current Baseline (Phase 1 Delivered)

- Deterministic spine remains: `decompose -> anomaly -> diagnose -> formatter`.
- Optional connector investigator exists and is bounded:
  - runs only for eligible `Medium|Low` diagnosed cases
  - max 3 checks, 120-second timeout
  - can downgrade to `insufficient_evidence`
- Contract semantics already enforced:
  - trust-gate fail -> `blocked_by_data_quality`
  - blocked status preserves `original_severity`
  - unresolved overlap -> `insufficient_evidence`

## 3) Phase 2 Outcomes

1. Add a pluggable multi-agent orchestration layer with explicit budgets.
2. Support multiple specialist investigators (connector, ranking, AI quality,
   traffic mix) with a common verdict contract.
3. Add evidence fusion and consensus logic to reduce single-agent blind spots.
4. Expand eval and stress coverage to include disagreement, timeout, and
   partial-evidence scenarios.
5. Keep all v1 diagnosis contracts backward-compatible.

## 4) Target Architecture

## 4.1 Orchestration

- New coordinator module: `tools/agent_orchestrator.py`.
- Inputs: baseline diagnosis payload + confidence + decision status.
- Behavior:
  - select eligible specialist agents by archetype and confidence band
  - run agents with per-agent and global timeout budgets
  - collect normalized verdicts + evidence records
  - produce fused outcome: `confirmed | insufficient_evidence | blocked`

## 4.2 Specialist Agents

- `ConnectorAgent`: connector and source integrity checks.
- `RankingAgent`: ranking model/version and relevance shift checks.
- `AIAnswerAgent`: trigger/success quality path checks.
- `MixShiftAgent`: compositional diagnostics and stability checks.

All agents must emit a normalized payload:

```json
{
  "agent": "connector",
  "ran": true,
  "verdict": "confirmed|rejected|inconclusive|blocked",
  "reason": "string",
  "queries": [],
  "evidence": [],
  "cost": {"queries": 0, "seconds": 0}
}
```

## 4.3 Evidence Fusion

- New deterministic fusion policy in `tools/evidence_fusion.py`.
- Decision policy:
  - any `blocked` from trust/data gates -> `blocked_by_data_quality`
  - majority `confirmed` with no hard reject -> keep `diagnosed`
  - any hard reject against single-cause claim -> `insufficient_evidence`
  - unresolved split or weak evidence -> `insufficient_evidence`
- Preserve existing severity and confidence contracts.

## 5) Implementation Workstreams

## Workstream A: Contracts and Interfaces

- Define `AgentVerdict` and `OrchestrationResult` schema in `tools/schema.py`.
- Add normalization for agent payloads.
- Add compatibility tests for legacy outputs.

Acceptance:
- Existing CLI outputs remain parse-compatible.
- New fields are additive and normalized.

## Workstream B: Orchestrator MVP

- Implement coordinator with bounded parallel execution and cancellation.
- Add max-agent count and global timeout config.
- Add deterministic run logs for reproducibility.

Acceptance:
- Orchestrator runs selected agents and returns fused verdict.
- Timeouts and exceptions degrade to `inconclusive`, not crashes.

## Workstream C: Specialist Agent Adapters

- Refactor connector spike into adapter contract.
- Add ranking and AI adapter stubs with local fake executors.
- Add mix-shift verifier agent using existing decomposition outputs.

Acceptance:
- Each adapter has unit tests for success, reject, timeout, malformed payload.

## Workstream D: Diagnose Integration

- Integrate orchestrator into `run_diagnosis()` behind a feature flag.
- Maintain current trust-gate and overlap precedence.
- Add action-item synthesis from multi-agent outcomes.

Acceptance:
- Existing S7/S8 contract tests still pass.
- New multi-agent tests assert downgrade/confirm logic.

## Workstream E: Eval + Stress Expansion

- Add new scoring specs for:
  - agent disagreement
  - partial evidence / timeout
  - false confirmation suppression
- Extend `eval/run_stress_test.py` to emit per-agent verdict traces.

Acceptance:
- Stress matrix remains green on existing scenarios.
- New scenarios enforce consensus correctness and restraint.

## 6) Delivery Phases

Phase 2.1 (Foundation):
- schemas, orchestrator skeleton, connector adapter migration.

Phase 2.2 (Coverage):
- ranking/AI/mix adapters, fusion policy, unit and integration tests.

Phase 2.3 (Eval Hardening):
- new stress scenarios, scoring rules, regression baselines.

Phase 2.4 (Operational Readiness):
- observability fields, docs, rollout flags, failure playbooks.

## 7) Verification Gates

Minimum gate for each merge:

1. `pytest tests/test_diagnose.py tests/test_eval.py -q`
2. `python3 eval/run_stress_test.py`
3. `python3 eval/run_stress_test.py --enable-connector-spike`
4. full `pytest -q`

Release gate:

- No regressions on S7/S8 decision-status contracts.
- No contract regressions on blocked severity semantics.
- Stable or improved average stress score vs current baseline.

## 8) Risks and Mitigations

- Risk: agent disagreement increases false downgrades.
  - Mitigation: confidence-aware fusion thresholds + explicit inconclusive state.
- Risk: runtime explosion from multi-agent fan-out.
  - Mitigation: hard query/time budgets and capped agent selection.
- Risk: contract drift in output payloads.
  - Mitigation: schema normalization + snapshot tests at formatter boundary.

## 9) Deferred to Phase 3

- Live Databricks auth and secret management.
- Continuous scheduling/orchestration outside local CLI runs.
- Learning-based fusion policy (non-deterministic ranking of evidence).
