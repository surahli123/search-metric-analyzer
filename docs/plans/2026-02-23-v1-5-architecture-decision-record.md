# v1.5 Architecture Decision Record (ADR)

Date: 2026-02-23  
Status: Accepted  
Scope: Search Metric Analyzer v1.5 minimal multi-agent bridge

## 1) Context

v1.4 established a deterministic diagnosis spine:

`decompose -> anomaly -> diagnose -> formatter`

v1.5 needed to add one bounded multi-agent bridge capability without destabilizing
existing behavior, scoring contracts, or formatter/eval compatibility.

## 2) Decision Summary

1. Keep the deterministic 4-tool pipeline as the execution spine.
2. Add an optional Connector Investigator hook inside `run_diagnosis()`.
3. Run connector investigation only when:
   - `decision_status == diagnosed`
   - confidence is `Medium` or `Low`
4. Enforce bounded connector execution:
   - max 3 generated checks
   - global timeout budget (120s default)
   - timeout during execution returns `verdict=rejected`
5. Preserve contract precedence:
   - trust-gate fail -> `blocked_by_data_quality`
   - unresolved overlap -> `insufficient_evidence`
   - connector rejection -> `insufficient_evidence` (only for eligible diagnosed path)
6. Preserve blocked severity semantics:
   - `aggregate.severity=blocked`
   - preserve `aggregate.original_severity`

## 3) Architecture Shape

### Deterministic Core

- `tools/decompose.py`: segment attribution and mix-shift.
- `tools/anomaly.py`: step-change, co-movement, trust-gate checks.
- `tools/diagnose.py`: contract synthesis, confidence, action items.
- `tools/formatter.py`: reporting surfaces (Slack + short report).

### Optional Connector Bridge

- `tools/connector_investigator.py` provides a bounded investigator utility.
- `tools/diagnose.py` accepts `connector_investigator` as an injected callable.
- `eval/run_stress_test.py --enable-connector-spike` enables stress-path smoke
  wiring with a deterministic local stub executor.

## 4) Contract Invariants (Non-Negotiable)

1. Trust-gate block has top precedence over definitive diagnosis claims.
2. Multi-cause unresolved overlap cannot be emitted as confident single-cause.
3. Connector checks must be bounded in both query count and wall-clock budget.
4. Diagnosis output remains backward-compatible; new fields are additive.
5. Existing S7/S8 behavioral contracts must remain stable in stress scoring.

## 5) Rationale and Tradeoffs

### Why this decision

- Delivers immediate risk reduction for weak-confidence diagnoses.
- Keeps runtime and blast radius small.
- Enables incremental move to full multi-agent orchestration in Phase 2.

### Tradeoffs accepted in v1.5

- No live external data-plane executor in this phase (local deterministic stub
  in stress-path mode only).
- No cross-agent fusion policy yet; only connector-specific post-check.
- Connector checks are hypothesis-hint driven, not globally optimized plans.

## 6) Deferred Work

Deferred to Phase 2+:

- Orchestrator with multiple specialist agents.
- Evidence fusion and consensus policy across agents.
- Per-agent budget accounting and observability fields.
- External auth/secret wiring for live connector backends.

## 7) Operational Guardrails

For every follow-up merge touching this area, require:

1. `pytest tests/test_diagnose.py tests/test_eval.py -q`
2. `python3 eval/run_stress_test.py`
3. `python3 eval/run_stress_test.py --enable-connector-spike`
4. `pytest -q`

## 8) Trigger to Revisit This ADR

Revisit if any of the following changes:

- Connector checks become unbounded or externalized by default.
- Additional agent types are introduced in diagnosis path.
- Output schema removes or redefines current decision-status semantics.
- Stress regression shows S7/S8 contract drift.
