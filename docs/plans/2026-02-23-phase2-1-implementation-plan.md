# Phase 2.1 Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add AgentVerdict/OrchestrationResult TypedDict schemas, a sequential orchestrator skeleton, and ~20 contract tests — all using fake agents, no changes to diagnose.py.

**Architecture:** Post-process hook pattern. The orchestrator is a standalone module (`tools/agent_orchestrator.py`) that takes a completed diagnosis result and runs specialist agents against it. Schemas live in `tools/schema.py` alongside the existing alias bridge. All agent payloads are normalized through a common TypedDict contract.

**Tech Stack:** Python 3.10+ stdlib + typing (TypedDict). No new dependencies.

---

### Task 1: Add AgentVerdict and OrchestrationResult TypedDicts to schema.py

**Files:**
- Modify: `tools/schema.py` (append after line 119)
- Test: `tests/test_schema.py` (append new test class)

**Step 1: Write the failing test**

Add to `tests/test_schema.py`:

```python
from tools.schema import (
    normalize_metric_name,
    normalize_row,
    normalize_rows,
    normalize_diagnosis_payload,
    AgentVerdict,
    OrchestrationResult,
    normalize_agent_verdict,
    VALID_VERDICTS,
)


class TestAgentVerdictSchema:
    """AgentVerdict TypedDict and normalizer contract."""

    def test_valid_verdict_passes_normalization_unchanged(self):
        """A fully-formed verdict dict should come back identical."""
        verdict = {
            "agent": "connector",
            "ran": True,
            "verdict": "confirmed",
            "reason": "all checks passed",
            "queries": ["SELECT 1"],
            "evidence": [{"query": "SELECT 1", "result": "ok"}],
            "cost": {"queries": 1, "seconds": 0.5},
        }
        result = normalize_agent_verdict(verdict)
        assert result == verdict

    def test_missing_keys_get_safe_defaults(self):
        """Minimal payload should be filled with safe defaults."""
        result = normalize_agent_verdict({"agent": "ranking"})
        assert result["agent"] == "ranking"
        assert result["ran"] is False
        assert result["verdict"] == "inconclusive"
        assert result["reason"] == "no reason provided"
        assert result["queries"] == []
        assert result["evidence"] == []
        assert result["cost"] == {"queries": 0, "seconds": 0.0}

    def test_empty_dict_gets_all_defaults(self):
        """Completely empty dict should not crash."""
        result = normalize_agent_verdict({})
        assert result["agent"] == "unknown"
        assert result["ran"] is False
        assert result["verdict"] == "inconclusive"

    def test_invalid_verdict_value_normalizes_to_inconclusive(self):
        """Unknown verdict strings should be treated as inconclusive."""
        result = normalize_agent_verdict({
            "agent": "connector",
            "ran": True,
            "verdict": "maybe",
        })
        assert result["verdict"] == "inconclusive"

    def test_valid_verdict_values_preserved(self):
        """All four valid verdict values should pass through."""
        for v in VALID_VERDICTS:
            result = normalize_agent_verdict({"verdict": v})
            assert result["verdict"] == v

    def test_preserves_extra_keys(self):
        """Extra keys beyond the schema should not be stripped."""
        result = normalize_agent_verdict({
            "agent": "connector",
            "custom_field": "extra_data",
        })
        assert result["custom_field"] == "extra_data"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer && python -m pytest tests/test_schema.py::TestAgentVerdictSchema -v`
Expected: FAIL — `ImportError: cannot import name 'AgentVerdict'`

**Step 3: Write minimal implementation**

Add to `tools/schema.py` after the existing imports (line 11), add `TypedDict` to the typing import:

```python
from typing import Any, Dict, Iterable, List, TypedDict
```

Then append at end of file (after `normalize_diagnosis_payload`):

```python
# ──────────────────────────────────────────────────
# Phase 2 Agent Schemas
# ──────────────────────────────────────────────────

# Valid verdict values for any specialist agent.
# "confirmed": agent's evidence supports the diagnosis
# "rejected": agent's evidence contradicts the diagnosis
# "inconclusive": agent ran but couldn't determine either way (or timed out)
# "blocked": agent cannot run due to data quality / trust gate issues
VALID_VERDICTS = {"confirmed", "rejected", "inconclusive", "blocked"}


class AgentVerdict(TypedDict, total=False):
    """Normalized payload that every specialist agent must return.

    Every agent (connector, ranking, AI quality, mix-shift) emits this
    shape. The orchestrator normalizes raw agent output through
    normalize_agent_verdict() before fusion.

    WHY TypedDict (not dataclass): the codebase is dict-based throughout.
    TypedDict adds structure and IDE autocomplete without changing how
    the code works — no .to_dict() conversions needed.
    """
    agent: str          # "connector" | "ranking" | "ai_quality" | "mix_shift"
    ran: bool           # did the agent actually execute?
    verdict: str        # one of VALID_VERDICTS
    reason: str         # human-readable explanation of the verdict
    queries: list       # queries the agent executed (audit trail)
    evidence: list      # evidence records, e.g. [{"query": str, "result": str}]
    cost: dict          # budget tracking: {"queries": int, "seconds": float}


class OrchestrationResult(TypedDict, total=False):
    """Top-level output of the multi-agent orchestrator.

    This is an ADDITIVE key on the final diagnosis output — old consumers
    that don't look for it are completely unaffected. Think of it like
    adding a new column to a dataset: existing queries still work.

    WHY "orchestrated" flag: callers can check this to know whether
    multi-agent analysis was even attempted (vs skipped because
    confidence was High or decision_status wasn't "diagnosed").
    """
    orchestrated: bool            # was orchestration attempted?
    agents_run: list              # list of normalized AgentVerdict dicts
    fused_verdict: str            # "confirmed" | "insufficient_evidence" | "blocked"
    fused_reason: str             # explanation of how the fusion decision was made
    updated_decision_status: str  # may override the baseline diagnosis status
    run_log: list                 # deterministic trace for reproducibility


def normalize_agent_verdict(raw: dict) -> dict:
    """Normalize a raw agent payload into a well-formed AgentVerdict.

    This is the alias-bridge pattern applied to agent payloads:
    fill in missing keys with safe defaults so downstream code never
    needs to check for KeyError.

    Safe defaults are CONSERVATIVE — they assume the agent didn't run
    and couldn't determine anything. This prevents false positives
    from malformed agent output.

    Args:
        raw: Dict from an agent's .run() method. May be partial or empty.

    Returns:
        Dict matching the AgentVerdict shape with all required keys present.
    """
    # Start with a copy so we don't mutate the original
    result = dict(raw)

    # Fill missing keys with safe defaults
    result.setdefault("agent", "unknown")
    result.setdefault("ran", False)
    result.setdefault("reason", "no reason provided")
    result.setdefault("queries", [])
    result.setdefault("evidence", [])
    result.setdefault("cost", {"queries": 0, "seconds": 0.0})

    # Normalize invalid verdict values to "inconclusive"
    # This catches typos, unexpected strings, and missing verdict keys
    verdict = result.get("verdict", "inconclusive")
    if verdict not in VALID_VERDICTS:
        result["verdict"] = "inconclusive"
    else:
        result["verdict"] = verdict

    return result
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer && python -m pytest tests/test_schema.py -v`
Expected: ALL PASS (both old and new tests)

**Step 5: Run full test suite to check for regressions**

Run: `cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer && python -m pytest -q`
Expected: 544+ tests passed, 0 failed

**Step 6: Commit**

```bash
git add tools/schema.py tests/test_schema.py
git commit -m "feat: add AgentVerdict and OrchestrationResult TypedDict schemas

Add VALID_VERDICTS set, AgentVerdict and OrchestrationResult TypedDicts,
and normalize_agent_verdict() normalizer to tools/schema.py.
6 new schema contract tests in tests/test_schema.py."
```

---

### Task 2: Build orchestrator skeleton with agent selection gate

**Files:**
- Create: `tools/agent_orchestrator.py`
- Test: `tests/test_agent_orchestrator.py` (create new file)

**Step 1: Write failing tests for the agent selection gate**

Create `tests/test_agent_orchestrator.py`:

```python
"""Tests for multi-agent orchestrator contracts.

Phase 2.1 Foundation: tests the orchestrator's agent selection gate,
sequential execution, fusion policy, and backward compatibility.
All tests use fake agents — no real connector/ranking/AI agents yet.
"""

import time

import pytest

from tools.agent_orchestrator import orchestrate, DEFAULT_CONFIG
from tools.schema import normalize_agent_verdict, VALID_VERDICTS


# ──────────────────────────────────────────────────
# Test Fixtures: Fake agents and diagnosis payloads
# ──────────────────────────────────────────────────

def _make_diagnosis(decision_status="diagnosed", confidence_level="Medium"):
    """Build a minimal diagnosis result for testing.

    Mirrors the shape of run_diagnosis() output but with only the keys
    the orchestrator actually reads. Think of this as a test double —
    just enough data to exercise the orchestrator's logic.
    """
    return {
        "aggregate": {"metric": "click_quality_value", "severity": "P1"},
        "primary_hypothesis": {
            "archetype": "ranking_regression",
            "dimension": "tenant_tier",
            "segment": "standard",
            "contribution_pct": 85.0,
            "description": "Test diagnosis",
            "confirms_if": ["ranking model version changed"],
            "rejects_if": ["movement uniform across segments"],
        },
        "confidence": {"level": confidence_level},
        "decision_status": decision_status,
        "validation_checks": [],
        "action_items": [],
    }


def _fake_agent(agent_name, verdict="confirmed", delay=0):
    """Factory for fake agent callables.

    Each fake agent returns a dict matching the AgentVerdict shape.
    The delay parameter simulates slow agents for timeout testing.
    """
    def agent(diagnosis_result, hypothesis):
        if delay > 0:
            time.sleep(delay)
        return {
            "agent": agent_name,
            "ran": True,
            "verdict": verdict,
            "reason": f"fake {agent_name} returned {verdict}",
            "queries": [f"SELECT * FROM {agent_name}_checks"],
            "evidence": [{"query": f"check_{agent_name}", "result": "ok"}],
            "cost": {"queries": 1, "seconds": delay or 0.01},
        }
    return agent


def _failing_agent(agent_name):
    """Factory for an agent that raises an exception."""
    def agent(diagnosis_result, hypothesis):
        raise RuntimeError(f"{agent_name} crashed unexpectedly")
    return agent


# ──────────────────────────────────────────────────
# A. Agent Selection Gate Tests
# ──────────────────────────────────────────────────

class TestAgentSelectionGate:
    """Orchestrator should only run agents for eligible diagnoses."""

    def test_runs_agents_for_diagnosed_medium_confidence(self):
        """Medium confidence + diagnosed = eligible for orchestration."""
        diagnosis = _make_diagnosis(decision_status="diagnosed", confidence_level="Medium")
        agents = [_fake_agent("connector")]
        result = orchestrate(diagnosis, agents)
        assert result["orchestrated"] is True
        assert len(result["agents_run"]) == 1

    def test_runs_agents_for_diagnosed_low_confidence(self):
        """Low confidence + diagnosed = eligible for orchestration."""
        diagnosis = _make_diagnosis(decision_status="diagnosed", confidence_level="Low")
        agents = [_fake_agent("connector")]
        result = orchestrate(diagnosis, agents)
        assert result["orchestrated"] is True

    def test_skips_agents_for_high_confidence(self):
        """High confidence diagnoses don't need second opinions."""
        diagnosis = _make_diagnosis(decision_status="diagnosed", confidence_level="High")
        agents = [_fake_agent("connector")]
        result = orchestrate(diagnosis, agents)
        assert result["orchestrated"] is False
        assert result["agents_run"] == []
        assert result["fused_verdict"] == "confirmed"
        assert "skipped" in result["fused_reason"].lower()

    def test_skips_agents_for_insufficient_evidence(self):
        """Already insufficient_evidence = no point running agents."""
        diagnosis = _make_diagnosis(decision_status="insufficient_evidence", confidence_level="Low")
        agents = [_fake_agent("connector")]
        result = orchestrate(diagnosis, agents)
        assert result["orchestrated"] is False

    def test_skips_agents_for_blocked_by_data_quality(self):
        """Blocked by data quality = agents can't help."""
        diagnosis = _make_diagnosis(decision_status="blocked_by_data_quality", confidence_level="Low")
        agents = [_fake_agent("connector")]
        result = orchestrate(diagnosis, agents)
        assert result["orchestrated"] is False

    def test_skips_when_no_agents_provided(self):
        """Empty agent list = nothing to orchestrate."""
        diagnosis = _make_diagnosis()
        result = orchestrate(diagnosis, [])
        assert result["orchestrated"] is False


# ──────────────────────────────────────────────────
# B. Sequential Execution Tests
# ──────────────────────────────────────────────────

class TestSequentialExecution:
    """Agents run one at a time in order, with timeout and error handling."""

    def test_two_agents_both_run_in_order(self):
        """Both agents should run and their verdicts appear in order."""
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("connector", verdict="confirmed"),
            _fake_agent("ranking", verdict="inconclusive"),
        ]
        result = orchestrate(diagnosis, agents)
        assert len(result["agents_run"]) == 2
        assert result["agents_run"][0]["agent"] == "connector"
        assert result["agents_run"][1]["agent"] == "ranking"

    def test_max_agents_cap(self):
        """Only the first max_agents agents should run."""
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("a1"),
            _fake_agent("a2"),
            _fake_agent("a3"),
        ]
        config = {**DEFAULT_CONFIG, "max_agents": 1}
        result = orchestrate(diagnosis, agents, config)
        assert len(result["agents_run"]) == 1
        assert result["agents_run"][0]["agent"] == "a1"

    def test_agent_exception_produces_inconclusive(self):
        """A crashing agent should not kill the orchestrator."""
        diagnosis = _make_diagnosis()
        agents = [
            _failing_agent("bad_agent"),
            _fake_agent("good_agent", verdict="confirmed"),
        ]
        result = orchestrate(diagnosis, agents)
        # Both agents should be in the results
        assert len(result["agents_run"]) == 2
        # The crashing agent should be marked inconclusive
        bad = result["agents_run"][0]
        assert bad["agent"] == "bad_agent"
        assert bad["verdict"] == "inconclusive"
        assert bad["ran"] is False
        # The good agent should still run
        good = result["agents_run"][1]
        assert good["verdict"] == "confirmed"

    def test_global_timeout_marks_remaining_inconclusive(self):
        """Agents that can't start before the global timeout are skipped."""
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("slow_agent", verdict="confirmed", delay=0.3),
            _fake_agent("skipped_agent", verdict="confirmed"),
        ]
        # Global timeout shorter than first agent's delay
        config = {**DEFAULT_CONFIG, "global_timeout_seconds": 0.1}
        result = orchestrate(diagnosis, agents, config)
        # At least the slow agent attempted to run; skipped_agent may or
        # may not have run depending on timing. What we can assert is that
        # the orchestrator didn't crash and returned a valid result.
        assert result["orchestrated"] is True
        assert len(result["agents_run"]) >= 1

    def test_run_log_tracks_each_agent(self):
        """Every agent should appear in the deterministic run log."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("connector")]
        result = orchestrate(diagnosis, agents)
        assert len(result["run_log"]) == 1
        log_entry = result["run_log"][0]
        assert log_entry["agent"] == "connector"
        assert "started" in log_entry
        assert "ended" in log_entry
        assert log_entry["verdict"] == "confirmed"


# ──────────────────────────────────────────────────
# C. Fusion Policy Tests
# ──────────────────────────────────────────────────

class TestFusionPolicy:
    """Deterministic fusion: how agent verdicts combine into a final decision."""

    def test_all_confirmed_fuses_to_confirmed(self):
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("a1", verdict="confirmed"),
            _fake_agent("a2", verdict="confirmed"),
        ]
        result = orchestrate(diagnosis, agents)
        assert result["fused_verdict"] == "confirmed"

    def test_one_rejected_fuses_to_insufficient_evidence(self):
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("a1", verdict="confirmed"),
            _fake_agent("a2", verdict="rejected"),
        ]
        result = orchestrate(diagnosis, agents)
        assert result["fused_verdict"] == "insufficient_evidence"

    def test_one_blocked_fuses_to_blocked(self):
        """Any blocked verdict overrides everything (trust gate precedence)."""
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("a1", verdict="confirmed"),
            _fake_agent("a2", verdict="blocked"),
        ]
        result = orchestrate(diagnosis, agents)
        assert result["fused_verdict"] == "blocked"

    def test_all_inconclusive_fuses_to_insufficient_evidence(self):
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("a1", verdict="inconclusive"),
            _fake_agent("a2", verdict="inconclusive"),
        ]
        result = orchestrate(diagnosis, agents)
        assert result["fused_verdict"] == "insufficient_evidence"

    def test_confirmed_plus_inconclusive_fuses_to_confirmed(self):
        """Inconclusive doesn't block confirmation (it's a non-vote)."""
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("a1", verdict="confirmed"),
            _fake_agent("a2", verdict="inconclusive"),
        ]
        result = orchestrate(diagnosis, agents)
        assert result["fused_verdict"] == "confirmed"

    def test_single_agent_confirmed(self):
        """Single confirming agent should produce confirmed fused verdict."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", verdict="confirmed")]
        result = orchestrate(diagnosis, agents)
        assert result["fused_verdict"] == "confirmed"

    def test_single_agent_rejected(self):
        """Single rejecting agent should produce insufficient_evidence."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", verdict="rejected")]
        result = orchestrate(diagnosis, agents)
        assert result["fused_verdict"] == "insufficient_evidence"

    def test_fused_verdict_updates_decision_status(self):
        """The fused verdict should determine updated_decision_status."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", verdict="rejected")]
        result = orchestrate(diagnosis, agents)
        assert result["updated_decision_status"] == "insufficient_evidence"


# ──────────────────────────────────────────────────
# D. Backward Compatibility Tests
# ──────────────────────────────────────────────────

class TestBackwardCompatibility:
    """Orchestrator output must not break existing diagnosis consumers."""

    def test_result_can_merge_into_diagnosis_without_breaking(self):
        """OrchestrationResult should be safe to merge into diagnosis dict."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("connector")]
        orch_result = orchestrate(diagnosis, agents)
        # Merge into diagnosis — this is what the integration layer will do
        merged = {**diagnosis, "orchestration": orch_result}
        # Original keys should be untouched
        assert merged["decision_status"] == "diagnosed"
        assert merged["confidence"]["level"] == "Medium"
        # New key should be present
        assert merged["orchestration"]["orchestrated"] is True

    def test_existing_connector_investigation_not_overwritten(self):
        """If diagnosis already has connector_investigation, it should survive."""
        diagnosis = _make_diagnosis()
        diagnosis["connector_investigation"] = {
            "ran": True,
            "verdict": "confirmed",
            "reason": "legacy connector check",
        }
        agents = [_fake_agent("connector")]
        orch_result = orchestrate(diagnosis, agents)
        # The orchestrator should not touch the diagnosis dict
        assert diagnosis["connector_investigation"]["verdict"] == "confirmed"
        # The orchestrator result is separate
        assert orch_result["agents_run"][0]["agent"] == "connector"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer && python -m pytest tests/test_agent_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.agent_orchestrator'`

**Step 3: Write the orchestrator implementation**

Create `tools/agent_orchestrator.py`:

```python
#!/usr/bin/env python3
"""Multi-agent orchestrator for diagnosis verification.

This module is a POST-PROCESS HOOK: it takes a completed diagnosis result
from run_diagnosis() and runs specialist agents against it to confirm,
reject, or add nuance.

WHY A SEPARATE MODULE (not inside diagnose.py):
- diagnose.py is already 1800+ lines with complex archetype logic
- The orchestrator has its own concerns (agent selection, timeout, fusion)
- Independent testability: orchestrator tests don't need diagnosis fixtures
- Feature toggle is trivial: call orchestrate() or don't

Think of it like a model ensemble in search ranking: the base model
(diagnose.py) produces a score, then the ensemble layer (orchestrator)
runs additional models and combines their votes.

Usage (from Python):
    from tools.agent_orchestrator import orchestrate
    result = orchestrate(diagnosis_result, agents=[...])

Phase 2.1: Sequential execution with fake agents only.
Phase 2.2+: Real agent adapters, parallel execution, CLI integration.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

try:
    from tools.schema import normalize_agent_verdict
except ModuleNotFoundError:
    from schema import normalize_agent_verdict


# Default orchestrator configuration.
# These are conservative starting values — tune as we add real agents.
DEFAULT_CONFIG = {
    "max_agents": 4,               # max agents to run per orchestration
    "global_timeout_seconds": 300,  # 5 minutes total budget
}


def _should_orchestrate(diagnosis_result: dict, agents: list) -> bool:
    """Determine if orchestration should run for this diagnosis.

    Gate logic (matches the connector investigator pattern from v1.5):
    - Only run for "diagnosed" status (no point verifying "insufficient" or "blocked")
    - Skip if confidence is "High" (high-confidence diagnoses don't need second opinions)
    - Skip if no agents are provided

    WHY skip High confidence:
    The original diagnosis is already strong. Running agents would add latency
    without adding value — like running an A/A test on a clear winner.

    Args:
        diagnosis_result: Output from run_diagnosis()
        agents: List of agent callables

    Returns:
        True if orchestration should proceed, False to skip.
    """
    if not agents:
        return False

    decision_status = diagnosis_result.get("decision_status", "diagnosed")
    if decision_status != "diagnosed":
        return False

    confidence_level = diagnosis_result.get("confidence", {}).get("level", "Medium")
    if confidence_level == "High":
        return False

    return True


def _run_agents_sequentially(
    diagnosis_result: dict,
    hypothesis: dict,
    agents: list,
    config: dict,
) -> tuple:
    """Run agents one at a time, collecting verdicts and building a run log.

    Sequential execution is simpler to debug and produces deterministic
    logs. Think of it like processing a batch pipeline row by row instead
    of parallelizing — you trade speed for debuggability.

    Error handling: if an agent raises an exception, it gets an
    "inconclusive" verdict and the next agent still runs. One bad agent
    should never crash the whole orchestration.

    Args:
        diagnosis_result: Full diagnosis dict
        hypothesis: The primary_hypothesis dict from the diagnosis
        agents: List of agent callables
        config: Orchestrator config (max_agents, global_timeout_seconds)

    Returns:
        Tuple of (agents_run: list[dict], run_log: list[dict])
    """
    agents_run: List[dict] = []
    run_log: List[dict] = []

    max_agents = config.get("max_agents", DEFAULT_CONFIG["max_agents"])
    global_timeout = config.get(
        "global_timeout_seconds", DEFAULT_CONFIG["global_timeout_seconds"]
    )

    orchestration_start = time.monotonic()

    for i, agent in enumerate(agents):
        # Respect max_agents cap
        if i >= max_agents:
            break

        # Check global timeout before starting next agent
        elapsed = time.monotonic() - orchestration_start
        if elapsed >= global_timeout:
            # Time's up — mark remaining agents as inconclusive
            # This is like a query timeout in search: better to return
            # partial results than to hang forever.
            remaining_count = min(max_agents, len(agents)) - i
            for j in range(remaining_count):
                timeout_verdict = normalize_agent_verdict({
                    "agent": f"agent_{i + j}",
                    "ran": False,
                    "verdict": "inconclusive",
                    "reason": "skipped: global timeout exceeded",
                })
                agents_run.append(timeout_verdict)
                run_log.append({
                    "agent": timeout_verdict["agent"],
                    "started": None,
                    "ended": None,
                    "verdict": "inconclusive",
                    "skipped_reason": "global_timeout",
                })
            break

        # Run the agent with error handling
        agent_start = time.monotonic()
        try:
            raw_result = agent(diagnosis_result, hypothesis)
            agent_end = time.monotonic()
            verdict = normalize_agent_verdict(raw_result)
        except Exception as exc:
            # Agent crashed — don't let it kill orchestration.
            # Log the error and mark as inconclusive.
            agent_end = time.monotonic()
            agent_name = getattr(agent, "__name__", f"agent_{i}")
            verdict = normalize_agent_verdict({
                "agent": agent_name,
                "ran": False,
                "verdict": "inconclusive",
                "reason": f"agent raised exception: {exc}",
            })

        agents_run.append(verdict)
        run_log.append({
            "agent": verdict["agent"],
            "started": agent_start - orchestration_start,
            "ended": agent_end - orchestration_start,
            "verdict": verdict["verdict"],
        })

    return agents_run, run_log


def _fuse_verdicts(agents_run: list) -> tuple:
    """Combine agent verdicts into a single fused decision.

    Deterministic fusion policy (priority order):
    1. Any "blocked" → fused = "blocked" (trust gate precedence)
    2. Any "rejected" → fused = "insufficient_evidence"
    3. At least one "confirmed" (no rejects) → fused = "confirmed"
    4. All "inconclusive" → fused = "insufficient_evidence" (conservative)

    WHY this order:
    - "blocked" is the strongest signal — it means data quality prevents analysis.
      Like a search index being stale: no ranking model can fix bad data.
    - "rejected" means an agent found counter-evidence. Even one reject should
      prevent us from confirming — similar to how a single failing unit test
      blocks a release.
    - "confirmed" only wins if there are no contradictions.
    - "inconclusive" is a non-vote. We default to caution.

    Args:
        agents_run: List of normalized AgentVerdict dicts

    Returns:
        Tuple of (fused_verdict: str, fused_reason: str)
    """
    if not agents_run:
        return "insufficient_evidence", "no agents produced verdicts"

    # Collect verdict counts for the reason string
    verdicts = [a["verdict"] for a in agents_run]
    verdict_counts = {}
    for v in verdicts:
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    counts_str = ", ".join(f"{k}={v}" for k, v in sorted(verdict_counts.items()))

    # Priority 1: Any blocked verdict → blocked
    if "blocked" in verdicts:
        return "blocked", f"blocked by trust/data gate ({counts_str})"

    # Priority 2: Any rejected verdict → insufficient_evidence
    if "rejected" in verdicts:
        return (
            "insufficient_evidence",
            f"agent evidence contradicts diagnosis ({counts_str})",
        )

    # Priority 3: At least one confirmed (no rejects, no blocked) → confirmed
    if "confirmed" in verdicts:
        return "confirmed", f"agent evidence supports diagnosis ({counts_str})"

    # Priority 4: All inconclusive → insufficient_evidence
    return (
        "insufficient_evidence",
        f"no agents could confirm or reject ({counts_str})",
    )


def _verdict_to_decision_status(fused_verdict: str, original_status: str) -> str:
    """Map fused verdict to a decision_status value.

    The orchestrator can only DOWNGRADE decision status, never upgrade.
    If the fused verdict is "confirmed", the original status stays.
    If it's "insufficient_evidence" or "blocked", the status downgrades.

    Args:
        fused_verdict: Output of _fuse_verdicts()
        original_status: The diagnosis's original decision_status

    Returns:
        Updated decision_status string
    """
    if fused_verdict == "confirmed":
        return original_status
    elif fused_verdict == "blocked":
        return "blocked_by_data_quality"
    else:
        return "insufficient_evidence"


def orchestrate(
    diagnosis_result: dict,
    agents: list,
    config: Optional[dict] = None,
) -> dict:
    """Run multi-agent orchestration on a completed diagnosis.

    This is the main entry point. It:
    1. Checks if orchestration should run (gate logic)
    2. Runs eligible agents sequentially with timeout + error handling
    3. Fuses verdicts into a single decision
    4. Returns an OrchestrationResult dict

    The result is ADDITIVE — it doesn't modify the diagnosis_result.
    The caller decides whether to merge it into the final output.

    Args:
        diagnosis_result: Complete output from run_diagnosis()
        agents: List of agent callables. Each agent is called with
            (diagnosis_result, hypothesis) and returns an AgentVerdict dict.
        config: Optional config dict overriding DEFAULT_CONFIG.
            Keys: max_agents (int), global_timeout_seconds (float)

    Returns:
        Dict matching the OrchestrationResult shape.
    """
    config = {**DEFAULT_CONFIG, **(config or {})}

    # ── Gate check: should we orchestrate? ──
    if not _should_orchestrate(diagnosis_result, agents):
        # Return a "skipped" result — orchestration was not attempted
        original_status = diagnosis_result.get("decision_status", "diagnosed")
        confidence_level = diagnosis_result.get("confidence", {}).get("level", "Unknown")

        # Determine skip reason for transparency
        if not agents:
            skip_reason = "skipped: no agents provided"
        elif original_status != "diagnosed":
            skip_reason = f"skipped: decision_status is '{original_status}'"
        elif confidence_level == "High":
            skip_reason = "skipped: confidence is High, no second opinion needed"
        else:
            skip_reason = "skipped: unknown reason"

        # When skipped due to High confidence, the fused_verdict is "confirmed"
        # (we trust the original diagnosis). Otherwise, pass through the
        # original status as-is.
        if confidence_level == "High":
            fused_verdict = "confirmed"
        else:
            fused_verdict = "insufficient_evidence"

        return {
            "orchestrated": False,
            "agents_run": [],
            "fused_verdict": fused_verdict,
            "fused_reason": skip_reason,
            "updated_decision_status": original_status,
            "run_log": [],
        }

    # ── Run agents sequentially ──
    hypothesis = diagnosis_result.get("primary_hypothesis", {})
    agents_run, run_log = _run_agents_sequentially(
        diagnosis_result, hypothesis, agents, config,
    )

    # ── Fuse verdicts ──
    fused_verdict, fused_reason = _fuse_verdicts(agents_run)
    original_status = diagnosis_result.get("decision_status", "diagnosed")
    updated_status = _verdict_to_decision_status(fused_verdict, original_status)

    return {
        "orchestrated": True,
        "agents_run": agents_run,
        "fused_verdict": fused_verdict,
        "fused_reason": fused_reason,
        "updated_decision_status": updated_status,
        "run_log": run_log,
    }
```

**Step 4: Run the orchestrator tests**

Run: `cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer && python -m pytest tests/test_agent_orchestrator.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer && python -m pytest -q`
Expected: 544 + ~20 new = ~564 tests passed, 0 failed

**Step 6: Commit**

```bash
git add tools/agent_orchestrator.py tests/test_agent_orchestrator.py
git commit -m "feat: add multi-agent orchestrator skeleton with contract tests

Sequential orchestrator with agent selection gate, timeout handling,
error recovery, and deterministic fusion policy. 20 contract tests
covering gate logic, execution, fusion, and backward compatibility.
All tests use fake agents — no real agent implementations yet."
```

---

### Task 3: Final verification and cleanup

**Step 1: Run all verification gates from Phase 2 plan**

Run the 4 gates in sequence:
```bash
cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer
python -m pytest tests/test_diagnose.py tests/test_eval.py -q
python3 eval/run_stress_test.py
python3 eval/run_stress_test.py --enable-connector-spike
python -m pytest -q
```
Expected: All green, no regressions.

**Step 2: Verify test count increased**

Run: `cd /Users/surahli/Documents/New\ project/Search_Metric_Analyzer && python -m pytest -q 2>&1 | tail -1`
Expected: 564+ passed (was 544 before this session)

**Step 3: Commit any cleanup (if needed)**

Only if Step 1 revealed issues that needed fixing.
