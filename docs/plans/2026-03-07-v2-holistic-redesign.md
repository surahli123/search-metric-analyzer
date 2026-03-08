# Search Metric Analyzer — v2.0 Holistic Redesign Plan

## Context

The user's in-house enterprise version of the Search Metric Analysis Agent was audited at IC9 level (IC9_review_FULL_PIPELINE_assessment.md). The audit found the system has strong investigation logic but a fundamentally **inverted control architecture**: enforcement is strongest at UNDERSTAND (the lowest-stakes stage) and completely absent at SYNTHESIZE (the highest-stakes stage). The open-source version being built in this repo is the opportunity to get it right from the start.

**What prompted this:** The in-house harness audit revealed 40+ failure modes, 4 untraced "Invisible Decisions," zero feedback loops, and ~50% compliance on mandatory SYNTHESIZE sections. The user wants to build an open-source version that fixes these problems structurally, not with more prompt instructions.

**Intended outcome:** A dual-mode open-source toolkit where:
1. The Python core is the deterministic spine (unchanged logic, better structure)
2. Stage boundaries are Python-enforced contracts (not prompt instructions)
3. Every key decision is traced for both human auditing and agent context
4. Both a skill-file mode (Claude Code) and a Python orchestrator mode (production) share the same contracts and trace schema

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    SHARED CORE (both modes)                  │
│                                                              │
│  /core/          ← deterministic tools (renamed from /tools/)│
│  /contracts/     ← TypedDict seam schemas (NEW)             │
│  /trace/         ← TraceSpan + InvestigationTrace (NEW)     │
└──────────────────────────┬──────────────────────────────────┘
                           │ used by
          ┌────────────────┴────────────────┐
          ▼                                 ▼
   MODE A: Skill File                MODE B: Python Orchestrator
   /skills/search-metric-            /harness/orchestrator.py
   analyzer.md                       (calls Claude API directly)

   For: Claude Code users            For: Production teams
   Enforcement: at tool level        Enforcement: at stage boundaries
   Trace: emitted via CLI hook       Trace: accumulated in-process
```

The four IC9 Invisible Decisions become traced `decision` span events. The four stage boundaries become Python-validated seams.

---

## Step 1: Move Files from /Downloads

**Before any code changes, move these files into the repo:**

| Source | Destination |
|--------|-------------|
| `/Users/surahli/Downloads/IC9_review_FULL_PIPELINE_assessment.md` | `docs/research/IC9_review_FULL_PIPELINE_assessment.md` |
| `/Users/surahli/Downloads/tech_talk_script_with_diagrams (2).html` | `docs/talks/tech_talk_script_with_diagrams.html` |
| `/Users/surahli/Downloads/tech_talk_script_with_diagrams (2).md` | `docs/talks/tech_talk_script_with_diagrams.md` |

Create `docs/research/` and `docs/talks/` directories.

Also create `docs/research/openai-harness-engineering-notes.md` as a reference stub pointing to the OpenAI harness engineering post (URL: https://openai.com/index/harness-engineering/) — summarize key principles relevant to this project.

---

## Step 2: Directory Restructure

### New structure (show diff from current)

```
RENAME: /tools/  →  /core/          (no logic changes; update all imports in tests/)
NEW:    /contracts/                  (TypedDict schemas for stage seams)
NEW:    /trace/                      (TraceSpan + InvestigationTrace)
NEW:    /harness/                    (orchestrator.py — Mode B)
NEW:    /docs/research/              (IC9 review, external references)
NEW:    /docs/talks/                 (tech talk scripts)
KEEP:   /skills/                     (skill file — Mode A, updated)
KEEP:   /eval/                       (unchanged, extend in Step 6)
KEEP:   /data/knowledge/            (unchanged)
KEEP:   /tests/                     (extend with contracts/ and trace/ tests)
```

**Critical import path changes** (update tests + eval + skill file):
- `from tools.anomaly import ...` → `from core.anomaly import ...`
- `from tools.diagnose import ...` → `from core.diagnose import ...`
- `from tools.decompose import ...` → `from core.decompose import ...`
- `from tools.formatter import ...` → `from core.formatter import ...`
- `from tools.schema import ...` → `from core.schema import ...`
- `from tools.agent_orchestrator import ...` → `from harness.orchestrator import ...` (move + extend)

---

## Step 3: Trace System (`/trace/`)

### Files to create

**`/trace/span.py`** — TraceSpan TypedDict

```python
class TraceSpan(TypedDict):
    trace_id: str
    stage: str                  # UNDERSTAND | HYPOTHESIZE | DISPATCH | SYNTHESIZE
    swimlane: str               # deterministic | llm_generated | hybrid
    tool: str                   # e.g. "core.anomaly.check_data_quality"
    decision: str               # e.g. "metric_direction" — maps to IC9 Invisible Decision names
    code_enforced: bool         # True = Python gate; False = LLM/prompt
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    value: Any                  # The key decision value
    alternatives_considered: List[Dict]
    human_summary: str          # For human auditors
    agent_context: str          # For downstream agent reasoning
    timestamp_ms: int
    duration_ms: int
```

**`/trace/collector.py`** — InvestigationTrace

```python
class InvestigationTrace:
    def __init__(self, trace_id: str, question: str): ...
    def emit(self, span: TraceSpan) -> None: ...
    def emit_seam(self, stage: str, schema: str, passed: bool, checks: Dict) -> None: ...
    def to_json(self) -> str: ...          # Human-readable full trace
    def agent_context_for(self, stage: str) -> str: ...  # Agent-readable summary of prior stages
```

**`/trace/schema.py`** — Full trace JSON schema + validation

### Trace emission strategy

Each `/core/` function gets a `trace: Optional[InvestigationTrace] = None` parameter. If trace is provided, the function emits a span. If None, works silently (backwards compatible).

The IC9 four Invisible Decisions map to trace `decision` values:
1. `metric_direction` → emitted by `core.anomaly.detect_step_change()`
2. `hypothesis_inclusion` → emitted by HYPOTHESIZE stage (LLM-generated span)
3. `context_construction` → emitted when sub-agent context is assembled in DISPATCH
4. `narrative_selection` → emitted by SYNTHESIZE stage (LLM-generated span)

---

## Step 4: Stage Contracts (`/contracts/`)

### Files to create

**`/contracts/understand.py`**
```python
class UnderstandResult(TypedDict):
    question: str
    metric: str
    direction: str              # "up" | "down" | "stable"
    severity: str               # "P0" | "P1" | "P2" | "normal"
    data_quality_status: str    # "pass" | "warn" | "fail"
    step_change: Optional[StepChangeResult]
    co_movement_pattern: CoMovementResult
    metric_direction: str       # IC9 Invisible Decision #1 — now required field
```

**`/contracts/hypothesize.py`**
```python
class HypothesisBrief(TypedDict):
    hypothesis_id: str
    archetype: str
    priority: int
    confirms_if: List[str]      # Non-empty required at seam
    rejects_if: List[str]
    expected_magnitude: str     # IC9 Phase 2 fix — required field
    source: str                 # IC9 Phase 1 fix — "data_driven" | "playbook" | "novel"
    is_contrarian: bool         # At least one must be True at seam

class HypothesisSet(TypedDict):
    hypotheses: List[HypothesisBrief]   # ≥ 3 required at seam
    exclusions: List[ExcludedHypothesis]  # What was excluded + why (Invisible Decision #2)
    investigation_context: str          # User question + movement significance for sub-agents
```

**`/contracts/dispatch.py`**
```python
class SubAgentFinding(TypedDict):
    agent_name: str
    hypothesis_id: str
    verdict: str                # "confirmed" | "rejected" | "inconclusive"
    evidence: List[Dict]        # Raw data citations (not just narrative)
    narrative: str
    adjacent_observations: List[str]  # IC9 Phase 2: "Unexpected Findings" escape valve

class FindingSet(TypedDict):
    findings: List[SubAgentFinding]
    # Seam checks:
    # - Each finding has ≥1 evidence item (not just narrative)
    # - Narrative-to-data check: numbers in narrative plausible vs evidence
```

**`/contracts/synthesize.py`**
```python
class SynthesisReport(TypedDict):
    tldr: str                   # ≤ 3 sentences
    confidence_grade: str       # "High" | "Medium" | "Low"
    severity: str
    root_cause: str
    dimensional_breakdown: str
    hypothesis_and_evidence: str
    validation_summary: str
    recommended_actions: List[ActionItem]  # Each has owner field
    upgrade_condition: str      # Required — "Would upgrade to X if Y"
    # Seam checks:
    # - All 7 sections non-empty
    # - Proportionality: P0 severity → no "minor" / "slight" language
```

**`/contracts/seam_validator.py`** — CLI + importable

```python
def validate_seam(result: Dict[str, Any], stage: str,
                  trace: Optional[InvestigationTrace] = None,
                  business_rules: Optional[List[Callable]] = None,
                  **kwargs) -> Dict[str, Any]:
    """Validate stage output against business rules with tiered gate behavior.

    Uses stage name to look up rules and gate tier (hard/soft/retry).
    Emits seam_validation span to trace. Returns validation result dict.
    Raises SeamViolation only for hard/retry tiers on failure."""
    ...

# Business rules per seam:
UNDERSTAND_RULES = [
    rule_data_quality_not_failed,
    rule_metric_direction_set,
]
HYPOTHESIZE_RULES = [
    rule_min_three_hypotheses,
    rule_all_have_confirms_if,
    rule_has_contrarian_hypothesis,    # IC9 Phase 2 fix
    rule_expected_magnitude_present,   # IC9 Phase 2 fix
]
DISPATCH_RULES = [
    rule_each_finding_has_evidence,
    rule_narrative_data_coherence,     # IC9 Phase 2: narrative-to-data check
]
SYNTHESIZE_RULES = [
    rule_all_mandatory_sections_present,   # IC9 Phase 1: 7 sections
    rule_effect_size_proportionality,      # IC9 Phase 2: P0 → strong language
    rule_upgrade_condition_stated,
]
```

---

## Step 5: Harness Modes

### Mode A: Skill File (updated `/skills/search-metric-analyzer.md`)

Changes to the existing skill file:
1. Call `seam_validator.py` after each stage (Python subprocess): `python -m contracts.seam_validator --stage understand --input /tmp/understand_out.json`
2. Store trace events in `/tmp/investigation_trace.json` during session
3. At DISPATCH stage: include `investigation_context` in sub-agent context (IC9 Phase 2 fix)
4. At SYNTHESIZE stage: read `trace.agent_context_for("DISPATCH")` to get evidence summary (not just narrative)

### Mode B: Python Orchestrator (new `/harness/orchestrator.py`)

```python
class SearchMetricOrchestrator:
    """Full Python-controlled UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE.

    Each stage:
    1. Validates input contract (TypedDict)
    2. Invokes Claude via API (or calls Python tools for deterministic stages)
    3. Validates output contract (TypedDict + business rules)
    4. Emits trace span
    """

    def run(self, question: str, data_path: str,
            model: str = "claude-opus-4-6") -> InvestigationReport:
        trace = InvestigationTrace(trace_id=uuid4(), question=question)

        # Stage 1: UNDERSTAND (mostly deterministic Python tools)
        understand_result = self._stage_understand(question, data_path, trace)
        validate_seam(understand_result, UnderstandResult, trace, UNDERSTAND_RULES)

        # Stage 2: HYPOTHESIZE (Claude + scoring)
        if understand_result["data_quality_status"] == "fail":
            return self._build_blocked_report(understand_result, trace)
        hyp_result = self._stage_hypothesize(understand_result, trace)
        validate_seam(hyp_result, HypothesisSet, trace, HYPOTHESIZE_RULES)

        # Stage 3: DISPATCH (Claude sub-agents with bounded tools)
        finding_set = self._stage_dispatch(hyp_result, trace)
        validate_seam(finding_set, FindingSet, trace, DISPATCH_RULES)

        # Stage 4: SYNTHESIZE (Claude with full trace context)
        synthesis = self._stage_synthesize(finding_set, trace)
        validate_seam(synthesis, SynthesisReport, trace, SYNTHESIZE_RULES)

        return InvestigationReport(synthesis=synthesis, trace=trace)
```

Move `tools/agent_orchestrator.py` → `harness/orchestrator.py` (extend, don't rewrite).
Keep `tools/connector_investigator.py` → `harness/connector_investigator.py` (unchanged logic).

---

## Step 6: Core Tool Updates (minimal changes)

Add trace emission to each tool. Example for `core/anomaly.py`:

```python
# Before:
def check_data_quality(rows) -> Dict:
    result = {...}
    return result

# After:
def check_data_quality(rows, trace: Optional[InvestigationTrace] = None) -> Dict:
    result = {...}
    if trace:
        trace.emit(TraceSpan(
            stage="UNDERSTAND", swimlane="deterministic", tool="core.anomaly.check_data_quality",
            decision="data_quality_gate", code_enforced=True,
            inputs={"row_count": len(rows)}, outputs=result, value=result["status"],
            human_summary=f"Data quality gate {result['status'].upper()} ...",
            agent_context=f"Proceed={result['status'] != 'fail'}. ..."
        ))
    return result
```

**No logic changes** to anomaly.py, decompose.py, diagnose.py, formatter.py, schema.py. Only add optional trace parameter and span emission.

---

## Step 7: IC9 Fix Mapping

| IC9 Phase | IC9 Item | Implementation Here |
|-----------|----------|---------------------|
| Phase 1 | synthesis_decision trace event | `narrative_selection` span in SYNTHESIZE |
| Phase 1 | Code-enforce mandatory sections | `rule_all_mandatory_sections_present` in SYNTHESIZE seam |
| Phase 1 | Log full dispatch context per sub-agent | `context_construction` span in DISPATCH |
| Phase 1 | Archive HypothesisBrief set | Stored in `HypothesisSet` TypedDict; persisted in trace |
| Phase 1 | Add `source` field to HypothesisBrief | `source` field in `HypothesisBrief` TypedDict |
| Phase 1 | 3 UNDERSTAND tracing additions | `metric_direction`, `routing_decision`, `knowledge_modules` spans |
| Phase 2 | Adjacent Observations | `adjacent_observations` in `SubAgentFinding` TypedDict |
| Phase 2 | `investigation_context` in dispatch | Required field in `HypothesisSet` TypedDict |
| Phase 2 | Narrative-to-data verification | `rule_narrative_data_coherence` in DISPATCH seam |
| Phase 2 | Effect-size proportionality | `rule_effect_size_proportionality` in SYNTHESIZE seam |
| Phase 2 | Default routing to Complex | `orchestrator.py` default; skill file instruction updated |
| Phase 2 | `expected_magnitude` in HypothesisBrief | Required field in TypedDict |
| Phase 2 | Contrarian hypothesis requirement | `rule_has_contrarian_hypothesis` in HYPOTHESIZE seam |
| Deferred | Hypothesis re-generation loop | v2+ (breaks One-Shot Constraint) |
| Deferred | Memory quality system | v2+ (Memory Time Bomb) |
| Deferred | Inter-batch context flow | v2+ |

---

## Step 8: Eval Extensions (minimal)

The existing eval framework (`eval/run_eval.py`, 6 scenarios) is sound. Extend only:

1. Add **trace output validation** to each eval run: verify all 4 Invisible Decisions have trace spans
2. Add **seam check coverage** to eval: verify all 4 seam validations ran and passed
3. Add eval scenario **S8b** (SYNTHESIZE compliance): tests that mandatory section checks catch violations
4. Keep existing 6 scenarios unchanged — they measure diagnostic accuracy, which hasn't changed

---

## Critical Files to Modify

| File | Change Type | What Changes |
|------|-------------|--------------|
| `tools/*.py` | RENAME + extend | Rename to `core/`; add trace emission (optional parameter) |
| `tools/agent_orchestrator.py` | MOVE + extend | → `harness/orchestrator.py`; extend to full 4-stage |
| `tools/connector_investigator.py` | MOVE | → `harness/connector_investigator.py` (no logic changes) |
| `skills/search-metric-analyzer.md` | UPDATE | Add seam validation CLI calls; add trace context reads |
| `tests/test_*.py` | UPDATE | Update imports `tools.` → `core.` |
| `eval/run_eval.py` | EXTEND | Add trace coverage checks |

**New files to create:**

| File | Purpose |
|------|---------|
| `trace/span.py` | TraceSpan TypedDict |
| `trace/collector.py` | InvestigationTrace class |
| `trace/schema.py` | Full trace JSON schema |
| `contracts/understand.py` | UnderstandResult TypedDict |
| `contracts/hypothesize.py` | HypothesisBrief, HypothesisSet TypedDicts |
| `contracts/dispatch.py` | SubAgentFinding, FindingSet TypedDicts |
| `contracts/synthesize.py` | SynthesisReport, ActionItem TypedDicts |
| `contracts/seam_validator.py` | validate_seam() + business rules |
| `harness/orchestrator.py` | Mode B: Full Python-controlled 4-stage flow |
| `docs/research/IC9_review_FULL_PIPELINE_assessment.md` | Moved from Downloads |
| `docs/talks/tech_talk_script_with_diagrams.html` | Moved from Downloads |
| `docs/talks/tech_talk_script_with_diagrams.md` | Moved from Downloads |
| `docs/research/openai-harness-engineering-notes.md` | Reference summary (from URL) |
| `docs/plans/2026-03-07-v2-holistic-redesign.md` | This design doc (committed) |

---

## Recommended Execution Order

1. Move files from Downloads (no code risk; add docs/research/ and docs/talks/ dirs)
2. Create `/trace/` module (pure new code; no existing code touched)
3. Create `/contracts/` module (pure new code; defines schemas)
4. Rename `/tools/` → `/core/` and update imports in tests + eval
5. Add trace emission to core tools (backwards-compatible; optional parameter)
6. Create `/harness/orchestrator.py` (extend agent_orchestrator.py)
7. Update skill file (Mode A: add seam validator calls)
8. Run full test suite + eval to verify nothing broke

---

## Verification

**After each step:**
- `pytest tests/ -v` → 571 tests still passing (no regressions)

**After Step 5 (trace emission):**
- Manual run: `python -c "from core.anomaly import check_data_quality; from trace.collector import InvestigationTrace; t = InvestigationTrace('test', 'test'); check_data_quality(rows, trace=t); print(t.to_json())"`
- Verify: trace JSON contains a span with `decision="data_quality_gate"` and `code_enforced=True`

**After Step 3 (contracts):**
- `python -m contracts.seam_validator --stage synthesize --input eval/fixtures/s4_synthesis.json`
- Verify: passes for valid output, raises `SeamViolation` for output with missing mandatory section

**After orchestrator (Step 6):**
- Run `python harness/orchestrator.py --question "CQ dropped 6.2%" --data data/synthetic/synthetic_metric_aggregate.csv`
- Verify: investigation completes, trace.json shows all 4 stage seams validated, all 4 Invisible Decisions traced

**Eval regression check:**
- `python eval/run_stress_test.py` → All 5 scenarios still GREEN (avg ≥ 91/100)
- Plus: new trace coverage check passes for all scenarios

**What "done" looks like:**
- All tests pass
- Eval scores unchanged (architecture changes don't affect diagnostic accuracy)
- A full investigation trace JSON shows all 4 Invisible Decision spans
- SYNTHESIZE seam catches a missing mandatory section in a test fixture
- Both Mode A (skill file) and Mode B (orchestrator) produce traces in the same format
