# v1.5 Minimal Multi-Agent Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a same-day, minimal multi-agent bridge by adding one bounded Connector Investigator subagent spike that can confirm/reject low-confidence diagnoses.

**Architecture:** Keep the current 4-tool deterministic pipeline as the spine, then add one optional post-diagnosis connector investigation step. The investigator is adapter-based: it generates bounded SQL checks from archetype `confirms_if` hints and executes them through an injected executor (local fake for now, Databricks adapter next). Diagnosis consumes the investigator verdict to keep/upgrade confidence or downgrade to `insufficient_evidence`.

**Tech Stack:** Python 3.10+, existing `tools/*`, `pytest`, synthetic eval runner.

---

## Today Scope (Minimal Done)

1. Add `tools/connector_investigator.py` with bounded execution limits (`max_queries=3`, timeout budget).
2. Wire optional connector investigation into `run_diagnosis()` for `Medium`/`Low` confidence only.
3. Add tests proving gating, timeout, and decision-status downgrade behavior.
4. Run targeted tests + full `pytest -q` + stress eval.

Out of scope for today: live Databricks authentication wiring, 10-agent orchestration, debate phase, production scheduler.

### Task 1: Write Failing Contract Tests First

**Files:**
- Create: `tests/test_connector_investigator.py`
- Modify: `tests/test_diagnose.py`

**Step 1: Write the failing test**

```python
def test_connector_investigator_skips_high_confidence():
    result = run_diagnosis(decomposition=decomp_high_confidence(), connector_investigator=fake_inv)
    assert result["connector_investigation"]["ran"] is False

def test_connector_investigator_runs_medium_confidence():
    result = run_diagnosis(decomposition=decomp_medium_confidence(), connector_investigator=fake_inv)
    assert result["connector_investigation"]["ran"] is True

def test_rejected_connector_hypothesis_downgrades_to_insufficient_evidence():
    result = run_diagnosis(decomposition=decomp_medium_confidence(), connector_investigator=fake_rejecting_inv)
    assert result["decision_status"] == "insufficient_evidence"
    assert result["confidence"]["level"] == "Low"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_connector_investigator.py tests/test_diagnose.py -k connector -v`
Expected: FAIL (missing `connector_investigator` support / missing module).

**Step 3: Commit failing tests**

```bash
git add tests/test_connector_investigator.py tests/test_diagnose.py
git commit -m "test: add failing connector investigator contract tests"
```

### Task 2: Implement Minimal Investigator Module

**Files:**
- Create: `tools/connector_investigator.py`
- Modify: `tools/__init__.py`
- Test: `tests/test_connector_investigator.py`

**Step 1: Write the failing test**

```python
def test_max_three_queries_enforced():
    inv = ConnectorInvestigator(max_queries=3, timeout_seconds=120)
    result = inv.run(hypothesis=sample_hypothesis(), execute_query=fake_execute_ok)
    assert len(result["queries"]) <= 3

def test_timeout_returns_rejected_verdict():
    inv = ConnectorInvestigator(max_queries=3, timeout_seconds=0)
    result = inv.run(hypothesis=sample_hypothesis(), execute_query=fake_execute_slow)
    assert result["verdict"] == "rejected"
    assert "timeout" in result["reason"].lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_connector_investigator.py -v`
Expected: FAIL (`ConnectorInvestigator` not defined).

**Step 3: Write minimal implementation**

```python
class ConnectorInvestigator:
    def __init__(self, max_queries: int = 3, timeout_seconds: int = 120):
        self.max_queries = max_queries
        self.timeout_seconds = timeout_seconds

    def run(self, hypothesis: dict, execute_query) -> dict:
        # Generate <= max_queries SQL checks from confirms_if and connector hints.
        # Stop early on timeout; return deterministic rejected verdict.
        return {
            "ran": True,
            "verdict": "confirmed",
            "reason": "all bounded checks passed",
            "queries": [],
            "evidence": [],
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_connector_investigator.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tools/connector_investigator.py tools/__init__.py tests/test_connector_investigator.py
git commit -m "feat: add bounded connector investigator spike module"
```

### Task 3: Wire Investigator into Diagnosis Pipeline

**Files:**
- Modify: `tools/diagnose.py`
- Modify: `tests/test_diagnose.py`
- Test: `tests/test_connector_investigator.py`

**Step 1: Write the failing test**

```python
def test_connector_rejection_downgrades_diagnosis():
    result = run_diagnosis(
        decomposition=decomp_medium_confidence(),
        co_movement_result={"likely_cause": "ranking_relevance_regression"},
        connector_investigator=fake_rejecting_inv,
    )
    assert result["decision_status"] == "insufficient_evidence"
    assert result["confidence"]["level"] == "Low"
    assert any("connector" in a["action"].lower() for a in result["action_items"])
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_diagnose.py -k connector -v`
Expected: FAIL (no integration yet).

**Step 3: Write minimal implementation**

```python
def run_diagnosis(..., connector_investigator=None):
    ...
    should_run = (
        connector_investigator is not None
        and decision_status == "diagnosed"
        and confidence["level"] in {"Medium", "Low"}
    )
    if should_run:
        investigation = connector_investigator(primary_hypothesis, decomposition)
        result["connector_investigation"] = investigation
        if investigation.get("verdict") == "rejected":
            result["decision_status"] = "insufficient_evidence"
            result["confidence"]["level"] = "Low"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_diagnose.py tests/test_connector_investigator.py -k connector -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tools/diagnose.py tests/test_diagnose.py tests/test_connector_investigator.py
git commit -m "feat: gate medium/low diagnoses with connector investigator verdict"
```

### Task 4: Add a CLI Spike Switch + Smoke Test

**Files:**
- Modify: `eval/run_stress_test.py`
- Modify: `tests/test_eval.py`
- Modify: `tests/test_tool_entrypoints.py`

**Step 1: Write the failing test**

```python
def test_stress_test_accepts_connector_spike_flag():
    proc = subprocess.run(
        [sys.executable, "eval/run_stress_test.py", "--enable-connector-spike"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval.py tests/test_tool_entrypoints.py -k connector_spike -v`
Expected: FAIL (`--enable-connector-spike` unknown).

**Step 3: Write minimal implementation**

```python
parser.add_argument("--enable-connector-spike", action="store_true")
# When enabled, inject fake/local connector executor into run_diagnosis calls.
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval.py tests/test_tool_entrypoints.py -k connector_spike -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add eval/run_stress_test.py tests/test_eval.py tests/test_tool_entrypoints.py
git commit -m "feat: add connector spike switch for stress-path smoke validation"
```

### Task 5: Final Verification + Release Candidate Notes

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Step 1: Add docs for today’s spike contract**

```markdown
- Connector Investigator spike:
  - Runs only on Medium/Low confidence.
  - Max 3 checks, 2-minute timeout.
  - Can downgrade to insufficient_evidence.
```

**Step 2: Run full verification**

Run:
- `pytest -q`
- `python3 eval/run_stress_test.py`
- `python3 eval/run_stress_test.py --enable-connector-spike`

Expected:
- Tests all pass.
- Stress matrix remains GREEN.
- No contract regression on S7/S8.

**Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: record v1.5 minimal multi-agent bridge spike"
```

**Step 4: Prepare handoff summary**

Include:
- What changed
- What was intentionally deferred
- Exact command outputs for verification

---

## Same-Day Timeline (Aggressive but realistic)

- 00:00-00:30: Task 1
- 00:30-01:30: Task 2
- 01:30-02:30: Task 3
- 02:30-03:15: Task 4
- 03:15-04:00: Task 5

Target: 4 hours for a minimal bridge if no infra blocker appears.
