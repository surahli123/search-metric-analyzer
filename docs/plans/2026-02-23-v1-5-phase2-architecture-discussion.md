# v1.5 -> Phase 2 Architecture Discussion

Date: 2026-02-23  
Status: Discussion record for follow-up implementation PRs

## 1) Goal of This Discussion

Capture the most important architectural choices that remain open after v1.5,
and define default recommendations so future PRs can stay consistent.

## 2) What Is Already Settled

- v1.5 minimal bridge is merged.
- Connector investigation is optional and bounded.
- Contract precedence (trust gate and unresolved overlap) is enforced.
- Stress-path behavior is stable (`6/6 GREEN` baseline and connector-spike mode).

## 3) Open Decisions and Options

### A) Where orchestration should live

Option 1: embed orchestration directly in `tools/diagnose.py`  
Pros: less indirection, fast initial shipping.  
Cons: larger diagnosis module, harder isolated testing.

Option 2: add `tools/agent_orchestrator.py` and keep `diagnose.py` thin  
Pros: cleaner contracts, easier unit tests, clearer budgets/cancellation paths.  
Cons: extra abstraction and plumbing work.

Recommendation: **Option 2**.

### B) Agent execution model

Option 1: sequential agent execution  
Pros: deterministic logs, simpler failure handling.  
Cons: slower in high-fanout scenarios.

Option 2: bounded parallel execution with per-agent and global budgets  
Pros: lower tail latency, realistic for multi-agent expansion.  
Cons: more complexity (timeouts/cancellation/race behavior).

Recommendation: **Option 2**, with strict caps and deterministic merge order.

### C) Fusion policy strictness

Option 1: majority-confirmed wins unless trust gate blocks  
Pros: straightforward and explainable.  
Cons: can over-trust weak/duplicative evidence.

Option 2: hard-reject veto for single-cause claims + confidence-aware tie-breaks  
Pros: safer for false-positive prevention.  
Cons: increases `insufficient_evidence` frequency.

Recommendation: **Option 2**.

### D) Schema evolution strategy

Option 1: replace diagnosis schema fields as multi-agent mode expands  
Pros: cleaner final schema faster.  
Cons: high break risk for formatter/eval/tools.

Option 2: additive schema evolution with normalization in `tools/schema.py`  
Pros: backward compatibility and safer rollout.  
Cons: temporary payload verbosity.

Recommendation: **Option 2**.

## 4) Risks to Watch

1. Timeout semantics drift between investigator modules.
2. Contract drift on `blocked_by_data_quality` and `insufficient_evidence`.
3. Eval green score masking weak calibration in specific scenarios.
4. Over-coupling between hypotheses and connector query generation.

## 5) Proposed Follow-up Milestones

### Milestone 1: Orchestrator skeleton

- Introduce orchestration module and verdict schema.
- Keep connector agent as the only active adapter initially.
- Add timeout/cancellation unit tests.

### Milestone 2: Multi-agent adapter expansion

- Add ranking, AI, and mix-shift adapters (stub + deterministic fake executors).
- Wire fusion policy with reject-veto and explicit inconclusive paths.

### Milestone 3: Eval hardening

- Add disagreement and timeout stress scenarios.
- Add anti-pattern scoring for overconfident fused diagnoses.

## 6) Minimum Merge Checklist for Phase 2 PRs

1. Preserve v1.5 decision-status and blocked severity semantics.
2. Keep connector timeout behavior explicitly tested (including in-flight timeout).
3. Validate stress stability on existing scenario set before adding new scenarios.
4. Include one docs update that records any schema or precedence changes.

## 7) Decision Owners

- Diagnosis contract + confidence semantics: Search Quality DS
- Multi-agent orchestration/runtime budgets: Search Platform
- Eval rubric and anti-pattern policies: PM + DS maintainers

## 8) Immediate Next PR Recommendation

Create a focused foundation PR that adds:

1. `tools/agent_orchestrator.py` skeleton
2. `AgentVerdict` normalization in `tools/schema.py`
3. unit tests for timeout/inconclusive conversion
4. no behavior change to existing v1.5 connector path by default
