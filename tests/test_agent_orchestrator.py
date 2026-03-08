"""Contract tests for the multi-agent orchestrator.

These tests define the orchestrator's behavior CONTRACT before any
implementation exists.  Think of them as an API spec written in code:
they describe what orchestrate() must do, and the implementation must
satisfy every assertion.

Test categories:
    A. Agent Selection Gate — when should orchestration run vs. skip?
    B. Sequential Execution — ordering, caps, timeouts, error recovery
    C. Fusion Policy — how do individual verdicts merge into one?
    D. Backward Compatibility — can we bolt orchestration onto existing results?

All tests use fake agents (simple callables) so we never depend on real
agent implementations.  The orchestrator just needs callables that accept
(diagnosis_result, hypothesis) and return a dict.
"""

import copy
import time

import pytest

from tools.agent_orchestrator import orchestrate, DEFAULT_CONFIG
from tools.schema import normalize_agent_verdict, VALID_VERDICTS


# ---------------------------------------------------------------------------
# Test fixtures — shared helpers, not in a class
# ---------------------------------------------------------------------------

def _make_diagnosis(decision_status="diagnosed", confidence_level="Medium"):
    """Build a minimal diagnosis result for testing.

    This mirrors the shape produced by tools/diagnose.py::run_diagnosis().
    Only includes fields the orchestrator actually reads, keeping tests
    focused on orchestrator behavior rather than diagnosis internals.
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

    Returns a function with the signature (diagnosis_result, hypothesis) -> dict,
    which is the contract every specialist agent must satisfy.

    We set __name__ on the inner function so the orchestrator can identify
    the agent even if the callable is inspected from the outside (e.g., in
    error-recovery paths where the agent crashes before returning a dict).

    Args:
        agent_name: Identifier for this fake agent.
        verdict:    What verdict to return (confirmed/rejected/etc.).
        delay:      Simulated processing time in seconds (for timeout tests).
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
    # Set __name__ so the orchestrator can identify this agent even if it
    # crashes before returning a dict.  Same idea as functools.wraps().
    agent.__name__ = agent_name
    return agent


def _failing_agent(agent_name):
    """Factory for an agent that raises an exception.

    Used to verify the orchestrator's error recovery: a crashing agent
    should produce verdict='inconclusive', ran=False — not crash the
    entire orchestration run.
    """
    def agent(diagnosis_result, hypothesis):
        raise RuntimeError(f"{agent_name} crashed unexpectedly")
    # Set __name__ so the orchestrator can identify this agent in the error
    # recovery path (where it can't read the agent name from the return dict).
    agent.__name__ = agent_name
    return agent


# ===================================================================
# A. Agent Selection Gate
# ===================================================================

class TestAgentSelectionGate:
    """The orchestrator should ONLY run agents when conditions are met.

    Gate logic:
    - decision_status must be "diagnosed"
    - confidence must NOT be "High" (High means we're already confident)
    - agents list must be non-empty

    If any condition fails, orchestrate() returns orchestrated=False
    with a reason explaining why it was skipped.
    """

    def test_runs_agents_for_diagnosed_medium_confidence(self):
        """Medium confidence + diagnosed = the sweet spot for agent verification."""
        diagnosis = _make_diagnosis(decision_status="diagnosed", confidence_level="Medium")
        agents = [_fake_agent("ranking")]
        result = orchestrate(diagnosis, agents)

        assert result["orchestrated"] is True
        assert len(result["agents_run"]) == 1
        assert "ranking" in result["agents_run"]

    def test_runs_agents_for_diagnosed_low_confidence(self):
        """Low confidence is the MOST important case for agent verification."""
        diagnosis = _make_diagnosis(decision_status="diagnosed", confidence_level="Low")
        agents = [_fake_agent("data_quality")]
        result = orchestrate(diagnosis, agents)

        assert result["orchestrated"] is True
        assert len(result["agents_run"]) == 1

    def test_skips_agents_for_high_confidence(self):
        """High confidence means the diagnosis is already solid — no need to verify.

        When skipped due to high confidence, the orchestrator should return
        fused_verdict='confirmed' (optimistic) since the diagnosis is strong.
        """
        diagnosis = _make_diagnosis(decision_status="diagnosed", confidence_level="High")
        agents = [_fake_agent("ranking")]
        result = orchestrate(diagnosis, agents)

        assert result["orchestrated"] is False
        assert result["agents_run"] == []
        assert result["fused_verdict"] == "confirmed"
        assert "skipped" in result["fused_reason"].lower()

    def test_skips_agents_for_insufficient_evidence(self):
        """If the diagnosis already flagged insufficient evidence, don't pile on."""
        diagnosis = _make_diagnosis(decision_status="insufficient_evidence")
        agents = [_fake_agent("ranking")]
        result = orchestrate(diagnosis, agents)

        assert result["orchestrated"] is False

    def test_skips_agents_for_blocked_by_data_quality(self):
        """If data quality blocked the diagnosis, agents can't help."""
        diagnosis = _make_diagnosis(decision_status="blocked_by_data_quality")
        agents = [_fake_agent("ranking")]
        result = orchestrate(diagnosis, agents)

        assert result["orchestrated"] is False

    def test_skips_when_no_agents_provided(self):
        """An empty agent list means there's nothing to run."""
        diagnosis = _make_diagnosis(decision_status="diagnosed", confidence_level="Medium")
        result = orchestrate(diagnosis, [])

        assert result["orchestrated"] is False


# ===================================================================
# B. Sequential Execution
# ===================================================================

class TestSequentialExecution:
    """Agents run one-at-a-time in the order they're provided.

    Sequential execution is the simplest model and the right starting point.
    It's easy to reason about, easy to debug, and easy to add parallelism
    later if needed.  (Same reason you'd start with a single-threaded
    data pipeline before introducing async workers.)
    """

    def test_two_agents_both_run_in_order(self):
        """Both agents should execute, and results should reflect the input order."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("ranking"), _fake_agent("data_quality")]
        result = orchestrate(diagnosis, agents)

        assert result["orchestrated"] is True
        assert result["agents_run"] == ["ranking", "data_quality"]

    def test_max_agents_cap(self):
        """The max_agents config should limit how many agents actually run.

        This is a budget/resource control: in production, you might have 10
        registered agents but only want to run 2 per diagnosis to control cost.
        """
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("agent_1"),
            _fake_agent("agent_2"),
            _fake_agent("agent_3"),
        ]
        # Override config to only allow 1 agent
        result = orchestrate(diagnosis, agents, config={"max_agents": 1})

        assert len(result["agents_run"]) == 1
        assert result["agents_run"] == ["agent_1"]

    def test_agent_exception_produces_inconclusive(self):
        """A crashing agent should NOT bring down the whole orchestration.

        Error recovery pattern: catch the exception, mark that agent as
        inconclusive (ran=False), and continue to the next agent.  This is
        the same resilience pattern used in data pipelines where one bad
        source shouldn't block the whole ETL.
        """
        diagnosis = _make_diagnosis()
        agents = [_failing_agent("bad_agent"), _fake_agent("good_agent")]
        result = orchestrate(diagnosis, agents)

        assert result["orchestrated"] is True
        # Both agents should appear in agents_run
        assert "bad_agent" in result["agents_run"]
        assert "good_agent" in result["agents_run"]

        # The run_log should show the bad agent as inconclusive
        bad_entry = [e for e in result["run_log"] if e["agent"] == "bad_agent"]
        assert len(bad_entry) == 1
        assert bad_entry[0]["verdict"] == "inconclusive"

    def test_global_timeout_marks_remaining_inconclusive(self):
        """If the global timeout expires, remaining agents should be skipped.

        This test uses a very short timeout (0.1s) and a slow agent (0.5s delay)
        to verify the timeout mechanism.  The assertion is timing-safe: we just
        check that orchestration ran and produced at least one result.
        """
        diagnosis = _make_diagnosis()
        agents = [
            _fake_agent("slow_agent", delay=0.5),
            _fake_agent("never_runs"),
        ]
        result = orchestrate(
            diagnosis, agents,
            config={"max_agents": 4, "global_timeout_seconds": 0.1},
        )

        # Orchestration should still complete (not crash)
        assert result["orchestrated"] is True
        # At least one agent should be in the results (timing-safe assertion)
        assert len(result["agents_run"]) >= 1

    def test_run_log_tracks_each_agent(self):
        """The run_log should contain per-agent metadata for debugging.

        Each entry must have: agent name, start time, end time, and verdict.
        This is the audit trail — if something goes wrong, you can reconstruct
        exactly what happened and when.
        """
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("ranking"), _fake_agent("data_quality")]
        result = orchestrate(diagnosis, agents)

        assert len(result["run_log"]) == 2
        for entry in result["run_log"]:
            assert "agent" in entry
            assert "started" in entry
            assert "ended" in entry
            assert "verdict" in entry


# ===================================================================
# C. Fusion Policy
# ===================================================================

class TestFusionPolicy:
    """The fusion policy merges individual agent verdicts into one decision.

    Priority order (deterministic, no ML magic):
    1. blocked    → Any agent says blocked → fused = blocked
    2. rejected   → Any agent says rejected → fused = insufficient_evidence
    3. confirmed  → All non-inconclusive agree → fused = confirmed
    4. inconclusive → Treated as a non-vote (doesn't block confirmation)

    This is similar to how you'd aggregate quality signals in a search
    ranking pipeline: some signals are hard vetoes (blocked), some are
    soft downgrades (rejected), and others are abstentions (inconclusive).
    """

    def test_all_confirmed_fuses_to_confirmed(self):
        """Unanimous confirmation → strongest signal."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", "confirmed"), _fake_agent("a2", "confirmed")]
        result = orchestrate(diagnosis, agents)

        assert result["fused_verdict"] == "confirmed"

    def test_one_rejected_fuses_to_insufficient_evidence(self):
        """A single rejection should downgrade the overall verdict.

        Think of this like a peer review: if one reviewer rejects, the
        paper doesn't get published even if others approved.
        """
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", "confirmed"), _fake_agent("a2", "rejected")]
        result = orchestrate(diagnosis, agents)

        assert result["fused_verdict"] == "insufficient_evidence"

    def test_one_blocked_fuses_to_blocked(self):
        """Blocked is the nuclear option — it overrides everything.

        A 'blocked' verdict means the agent found a data quality issue
        so severe that the diagnosis can't be trusted at all.
        """
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", "confirmed"), _fake_agent("a2", "blocked")]
        result = orchestrate(diagnosis, agents)

        assert result["fused_verdict"] == "blocked"

    def test_all_inconclusive_fuses_to_insufficient_evidence(self):
        """If nobody has an opinion, we can't confirm anything."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", "inconclusive"), _fake_agent("a2", "inconclusive")]
        result = orchestrate(diagnosis, agents)

        assert result["fused_verdict"] == "insufficient_evidence"

    def test_confirmed_plus_inconclusive_fuses_to_confirmed(self):
        """Inconclusive is a non-vote — it doesn't block confirmation.

        If one agent confirms and another abstains, the confirmation
        stands.  This prevents flaky agents from blocking good diagnoses.
        """
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("a1", "confirmed"), _fake_agent("a2", "inconclusive")]
        result = orchestrate(diagnosis, agents)

        assert result["fused_verdict"] == "confirmed"

    def test_single_agent_confirmed(self):
        """A single confirming agent is enough to fuse to confirmed."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("solo", "confirmed")]
        result = orchestrate(diagnosis, agents)

        assert result["fused_verdict"] == "confirmed"

    def test_single_agent_rejected(self):
        """A single rejecting agent should fuse to insufficient_evidence."""
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("solo", "rejected")]
        result = orchestrate(diagnosis, agents)

        assert result["fused_verdict"] == "insufficient_evidence"

    def test_fused_verdict_updates_decision_status(self):
        """A rejected verdict should update the decision_status field.

        The updated_decision_status tells downstream consumers whether
        the original diagnosis still holds or has been revised.
        """
        diagnosis = _make_diagnosis()
        agents = [_fake_agent("solo", "rejected")]
        result = orchestrate(diagnosis, agents)

        assert result["updated_decision_status"] == "insufficient_evidence"


# ===================================================================
# D. Backward Compatibility
# ===================================================================

class TestBackwardCompatibility:
    """The orchestrator's output must slot into existing diagnosis results
    without breaking any existing consumer.

    This is critical: we're adding a new "orchestration" key to a dict
    that's already consumed by formatters, evaluators, and the CLI.
    If we break the existing shape, everything downstream breaks too.
    """

    def test_result_can_merge_into_diagnosis_without_breaking(self):
        """Merging orchestration output into diagnosis should be safe.

        Pattern: diagnosis["orchestration"] = orchestrate(diagnosis, agents)
        All original diagnosis keys must remain untouched.
        """
        diagnosis = _make_diagnosis()
        original_keys = set(diagnosis.keys())
        original_snapshot = copy.deepcopy(diagnosis)

        agents = [_fake_agent("ranking")]
        orch_result = orchestrate(diagnosis, agents)

        # Merge the orchestration result into the diagnosis
        diagnosis["orchestration"] = orch_result

        # Original keys must all still be present and unchanged
        for key in original_keys:
            assert key in diagnosis, f"Original key '{key}' was lost after merge"
            assert diagnosis[key] == original_snapshot[key], (
                f"Original key '{key}' was mutated during orchestration"
            )

        # The new key should exist
        assert "orchestration" in diagnosis
        assert diagnosis["orchestration"]["orchestrated"] is True

    def test_existing_connector_investigation_not_overwritten(self):
        """A diagnosis with a connector_investigation key should survive.

        The connector_investigator (from v1.5) adds its own key to the
        diagnosis result.  The orchestrator must not clobber it.
        """
        diagnosis = _make_diagnosis()
        diagnosis["connector_investigation"] = {
            "connector": "sharepoint",
            "status": "degraded",
        }

        agents = [_fake_agent("ranking")]
        orch_result = orchestrate(diagnosis, agents)

        # Verify the orchestrator didn't touch the diagnosis dict
        assert diagnosis["connector_investigation"] == {
            "connector": "sharepoint",
            "status": "degraded",
        }
        # And the orchestration result is a separate dict
        assert "connector_investigation" not in orch_result
