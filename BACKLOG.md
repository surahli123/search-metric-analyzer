# Backlog — Search Metric Analyzer v2.0 Holistic Redesign

Last updated: 2026-03-07

---

## In Progress

### Wave 2: Directory Restructure
- [x] Rename `tools/` → `core/` (git mv, preserve history)
- [x] Move `tools/agent_orchestrator.py` → `harness/orchestrator.py`
- [x] Move `tools/connector_investigator.py` → `harness/connector_investigator.py`
- [ ] Create `core/__init__.py` and `harness/__init__.py`
- [ ] Update all imports in `tests/*.py` (~14 files)
- [ ] Update all imports in `eval/*.py`
- [ ] Update all imports in `generators/*.py`
- [ ] Update CLI paths in `skills/search-metric-analyzer.md`
- [ ] Fix `contribution_pct` naming ambiguity — check `decompose.py` output format, align `MixShiftResult`
- [ ] Run full test suite — must stay at 694 passed, 21 skipped

---

## Upcoming

### Wave 3: Trace Emission + Orchestrator
- [ ] Add `trace: Optional[InvestigationTrace] = None` parameter to `core/anomaly.py` functions
- [ ] Add trace emission to `core/decompose.py` functions
- [ ] Add trace emission to `core/diagnose.py` functions
- [ ] Add trace emission to `core/formatter.py` functions
- [ ] Build `harness/orchestrator.py` — full 4-stage pipeline controller with Claude API
- [ ] Import verdict fusion from old orchestrator (don't rewrite from scratch)
- [ ] Add tests for trace emission in core tools
- [ ] Add tests for orchestrator pipeline

### Wave 4: Skill File + Eval
- [ ] Update `skills/search-metric-analyzer.md` — add seam validator subprocess calls after each stage
- [ ] Add trace context reads at SYNTHESIZE stage in skill file
- [ ] Add `investigation_context` to sub-agent context at DISPATCH stage
- [ ] Extend `eval/run_eval.py` — add trace coverage checks (4 IC9 Invisible Decisions)
- [ ] Extend eval — add seam check coverage (4 seam validations ran and passed)
- [ ] Add eval scenario S8b (SYNTHESIZE compliance — catches missing mandatory sections)
- [ ] Run eval stress test — all 5 scenarios must stay GREEN (avg >= 91/100)

---

## Open Code Review Items (from Wave 1 review)

Priority: fix during the wave where they naturally fit.

- [ ] `contribution_pct` naming — ratio (0.0-1.0) vs percentage (0-100). Fix during Wave 2 when wiring `decompose.py` output. (Important)
- [ ] `constrained_by` field validation — add warning in `InvestigationTrace.emit()` when `swimlane == "llm_generated"` and `constrained_by` missing. Fix during Wave 3 when adding LLM spans. (Important)
- [ ] Business rules return single violation — document as known limitation or change return type to `List[str]`. (Suggestion)
- [ ] `narrative_data_coherence` false-negative bias — add docstring noting that mixed-direction text passes. (Suggestion)
- [ ] `CoMovementResult.runner_up` double-optional — `Optional[str]` + `total=False` is redundant. (Suggestion)
- [ ] `InvestigationTrace.emit()` mutates span dict in-place — add docstring note. (Suggestion)

---

## Deferred to v2.1+

- [ ] Cross-mode conformance test — run same scenarios through Mode A and Mode B, compare trace outputs
- [ ] Hypothesis re-generation loop (breaks One-Shot Constraint)
- [ ] Memory quality system (Memory Time Bomb)
- [ ] Inter-batch context flow
- [ ] Calibrate severity thresholds (one-size-fits-all → metric-specific)
- [ ] Simpson's Paradox reversal check in decompose.py
- [ ] Archetype-specific actions for `unknown_pattern` fallback
- [ ] `click_behavior_change` lumps UX + mix-shift without prioritization

---

## Done

### Wave 1: Trace + Contracts (2026-03-07)
- [x] Create `trace/` module (span.py, collector.py, schema.py)
- [x] Create `contracts/` module (understand.py, hypothesize.py, dispatch.py, synthesize.py, seam_validator.py)
- [x] Implement 11 business rules with tiered gates (hard/soft/retry)
- [x] Implement Amendment 2: `rule_hypotheses_consistent_with_co_movement`
- [x] Implement Amendment 3: `MixShiftResult` in UnderstandResult
- [x] Implement Amendment 4: `agent_context_for()` with token budget
- [x] Write 144 tests (57 trace + 87 contracts)
- [x] Move IC9 review + tech talk docs into repo
- [x] Create OpenAI harness engineering reference stub
- [x] Save v2 design doc
- [x] Run IC9-calibrated review (DS Lead, PM Lead, Principal AI Eng)
- [x] Fix Critical #1: word-boundary regex in `rule_effect_size_proportionality`
- [x] Fix Critical #2: update `validate_seam` signature in design doc
- [x] Set up `.worktrees/` with gitignore
