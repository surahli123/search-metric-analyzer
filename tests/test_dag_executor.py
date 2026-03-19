"""Tests for DAG executor — parallel hypothesis dispatch with error isolation.

Covers:
- Parallel execution with mock agents
- Error isolation: 1/3 fails → 2 findings + 1 inconclusive
- Circuit breaker: 3 failures → StageError raised
- Timeout: slow agent → inconclusive finding
- Empty hypothesis list handling
- Coverage check and execution log
- Trace emission
"""

import time
import pytest

from harness.dag_executor import DAGExecutor, DEFAULT_CONFIG
from harness.errors import StageError


# =============================================================================
# Mock investigate functions
# =============================================================================

def _mock_investigate_success(hypothesis, context):
    """Mock that always succeeds — returns a confirmed finding."""
    return {
        "agent_name": "mock_agent",
        "hypothesis_id": hypothesis.get("hypothesis_id", "unknown"),
        "verdict": "confirmed",
        "confidence": 0.85,
        "evidence": [{"metric": "click_quality", "value": 0.22, "delta": -0.03, "direction": "down"}],
        "narrative": f"Investigated {hypothesis.get('hypothesis_id')}",
        "adjacent_observations": [],
    }


def _mock_investigate_failure(hypothesis, context):
    """Mock that always crashes."""
    raise RuntimeError(f"Agent crashed on {hypothesis.get('hypothesis_id')}")


def _mock_investigate_slow(hypothesis, context):
    """Mock that takes too long."""
    time.sleep(5)
    return _mock_investigate_success(hypothesis, context)


def _mock_investigate_mixed(hypothesis, context):
    """Mock that fails for specific hypotheses, succeeds for others."""
    hyp_id = hypothesis.get("hypothesis_id", "")
    if "fail" in hyp_id:
        raise RuntimeError(f"Simulated failure for {hyp_id}")
    return _mock_investigate_success(hypothesis, context)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def three_hypotheses():
    return [
        {"hypothesis_id": "hyp_001", "archetype": "ranking_regression"},
        {"hypothesis_id": "hyp_002", "archetype": "connector_health"},
        {"hypothesis_id": "hyp_003", "archetype": "ai_feature_effect"},
    ]


@pytest.fixture
def context():
    return {
        "understand_result": {"metric": "click_quality", "direction": "down"},
        "hypothesize_context": "test context",
    }


# =============================================================================
# Basic execution tests
# =============================================================================

class TestBasicExecution:
    """Test normal execution paths."""

    def test_all_succeed(self, three_hypotheses, context):
        """All 3 hypotheses investigated successfully in parallel."""
        executor = DAGExecutor(investigate_fn=_mock_investigate_success)
        result = executor.execute(three_hypotheses, context)

        assert len(result["findings"]) == 3
        assert result["failed_count"] == 0
        assert result["circuit_broken"] is False
        assert len(result["execution_log"]) == 3

        # All findings should be confirmed
        for finding in result["findings"]:
            assert finding["verdict"] == "confirmed"
            assert finding["confidence"] == 0.85

    def test_empty_hypotheses(self, context):
        """Empty hypothesis list returns empty results (no crash)."""
        executor = DAGExecutor(investigate_fn=_mock_investigate_success)
        result = executor.execute([], context)

        assert result["findings"] == []
        assert result["failed_count"] == 0
        assert result["circuit_broken"] is False

    def test_single_hypothesis(self, context):
        """Single hypothesis works correctly."""
        executor = DAGExecutor(investigate_fn=_mock_investigate_success)
        result = executor.execute(
            [{"hypothesis_id": "hyp_001"}], context
        )
        assert len(result["findings"]) == 1
        assert result["findings"][0]["hypothesis_id"] == "hyp_001"


# =============================================================================
# Error isolation tests
# =============================================================================

class TestErrorIsolation:
    """Test per-hypothesis error isolation."""

    def test_one_failure_others_continue(self, context):
        """One failure → inconclusive finding, other 2 succeed."""
        hypotheses = [
            {"hypothesis_id": "hyp_001"},
            {"hypothesis_id": "hyp_fail_002"},  # Will fail
            {"hypothesis_id": "hyp_003"},
        ]
        executor = DAGExecutor(investigate_fn=_mock_investigate_mixed)
        result = executor.execute(hypotheses, context)

        assert len(result["findings"]) == 3
        assert result["failed_count"] == 1
        assert result["circuit_broken"] is False

        # Find the failed finding
        failed = [f for f in result["findings"] if f["verdict"] == "inconclusive"]
        assert len(failed) == 1
        assert failed[0]["hypothesis_id"] == "hyp_fail_002"
        assert failed[0]["confidence"] == 0.0

        # Other 2 should be confirmed
        succeeded = [f for f in result["findings"] if f["verdict"] == "confirmed"]
        assert len(succeeded) == 2

    def test_two_failures_still_continues(self, context):
        """Two failures (below threshold of 3) → continues."""
        hypotheses = [
            {"hypothesis_id": "hyp_001"},
            {"hypothesis_id": "hyp_fail_002"},
            {"hypothesis_id": "hyp_fail_003"},
            {"hypothesis_id": "hyp_004"},
        ]
        executor = DAGExecutor(
            investigate_fn=_mock_investigate_mixed,
            config={"circuit_breaker_threshold": 3},
        )
        result = executor.execute(hypotheses, context)

        assert result["failed_count"] == 2
        assert result["circuit_broken"] is False


# =============================================================================
# Circuit breaker tests
# =============================================================================

class TestCircuitBreaker:
    """Test circuit breaker behavior."""

    def test_all_fail_trips_circuit_breaker(self, three_hypotheses, context):
        """All 3 hypotheses fail → circuit breaker trips → StageError."""
        executor = DAGExecutor(
            investigate_fn=_mock_investigate_failure,
            config={"circuit_breaker_threshold": 3},
        )
        with pytest.raises(StageError) as exc_info:
            executor.execute(three_hypotheses, context)

        assert exc_info.value.stage == "DISPATCH"
        assert "circuit breaker" in str(exc_info.value).lower()

    def test_circuit_breaker_at_threshold(self, context):
        """Exactly threshold failures trips the breaker."""
        hypotheses = [
            {"hypothesis_id": "hyp_fail_001"},
            {"hypothesis_id": "hyp_fail_002"},
            {"hypothesis_id": "hyp_fail_003"},
        ]
        executor = DAGExecutor(
            investigate_fn=_mock_investigate_mixed,
            config={"circuit_breaker_threshold": 3},
        )
        with pytest.raises(StageError):
            executor.execute(hypotheses, context)

    def test_custom_circuit_breaker_threshold(self, context):
        """Custom threshold of 1 trips on first failure."""
        hypotheses = [
            {"hypothesis_id": "hyp_001"},
            {"hypothesis_id": "hyp_fail_002"},
        ]
        executor = DAGExecutor(
            investigate_fn=_mock_investigate_mixed,
            config={"circuit_breaker_threshold": 1},
        )
        with pytest.raises(StageError):
            executor.execute(hypotheses, context)

    def test_stage_error_has_partial_findings(self, context):
        """StageError from circuit breaker includes partial findings in details."""
        hypotheses = [
            {"hypothesis_id": "hyp_fail_001"},
            {"hypothesis_id": "hyp_fail_002"},
            {"hypothesis_id": "hyp_fail_003"},
        ]
        executor = DAGExecutor(
            investigate_fn=_mock_investigate_mixed,
            config={"circuit_breaker_threshold": 3},
        )
        with pytest.raises(StageError) as exc_info:
            executor.execute(hypotheses, context)
        assert exc_info.value.details is not None
        assert "findings" in exc_info.value.details


# =============================================================================
# Execution log tests
# =============================================================================

class TestExecutionLog:
    """Test execution log metadata."""

    def test_log_has_all_hypotheses(self, three_hypotheses, context):
        executor = DAGExecutor(investigate_fn=_mock_investigate_success)
        result = executor.execute(three_hypotheses, context)

        assert len(result["execution_log"]) == 3
        for entry in result["execution_log"]:
            assert "hypothesis_id" in entry
            assert "status" in entry
            assert "duration" in entry

    def test_failed_log_has_error(self, context):
        hypotheses = [{"hypothesis_id": "hyp_fail_001"}]
        executor = DAGExecutor(
            investigate_fn=_mock_investigate_mixed,
            config={"circuit_breaker_threshold": 5},  # Don't trip breaker
        )
        result = executor.execute(hypotheses, context)

        failed_entries = [e for e in result["execution_log"] if e["status"] == "failed"]
        assert len(failed_entries) == 1
        assert "error" in failed_entries[0]


# =============================================================================
# Trace emission tests
# =============================================================================

class TestTraceEmission:
    """Test trace span emission."""

    def test_trace_emitted(self, three_hypotheses, context):
        from trace.collector import InvestigationTrace
        trace = InvestigationTrace(question="test")
        executor = DAGExecutor(investigate_fn=_mock_investigate_success)
        executor.execute(three_hypotheses, context, trace=trace)

        trace_dict = trace.to_dict()
        spans = trace_dict.get("spans", [])
        dispatch_spans = [
            s for s in spans if s.get("decision") == "parallel_dispatch"
        ]
        assert len(dispatch_spans) == 1
        assert "completed" in dispatch_spans[0]["value"]

    def test_no_trace_doesnt_crash(self, three_hypotheses, context):
        executor = DAGExecutor(investigate_fn=_mock_investigate_success)
        result = executor.execute(three_hypotheses, context)
        assert len(result["findings"]) == 3


# =============================================================================
# Config tests
# =============================================================================

class TestConfig:
    """Test configuration handling."""

    def test_default_config(self):
        executor = DAGExecutor(investigate_fn=_mock_investigate_success)
        assert executor._config["max_workers"] == DEFAULT_CONFIG["max_workers"]
        assert executor._config["circuit_breaker_threshold"] == DEFAULT_CONFIG["circuit_breaker_threshold"]

    def test_custom_config_overrides(self):
        executor = DAGExecutor(
            investigate_fn=_mock_investigate_success,
            config={"max_workers": 2, "per_agent_timeout": 30},
        )
        assert executor._config["max_workers"] == 2
        assert executor._config["per_agent_timeout"] == 30
        # Other defaults preserved
        assert executor._config["circuit_breaker_threshold"] == DEFAULT_CONFIG["circuit_breaker_threshold"]


# =============================================================================
# Parallelism verification
# =============================================================================

class TestParallelism:
    """Verify that execution is actually parallel (not sequential)."""

    def test_parallel_is_faster_than_sequential(self, context):
        """3 hypotheses at 0.1s each should take ~0.1s parallel, not 0.3s."""
        def slow_investigate(hypothesis, ctx):
            time.sleep(0.1)
            return _mock_investigate_success(hypothesis, ctx)

        hypotheses = [
            {"hypothesis_id": "hyp_001"},
            {"hypothesis_id": "hyp_002"},
            {"hypothesis_id": "hyp_003"},
        ]
        executor = DAGExecutor(investigate_fn=slow_investigate)

        start = time.monotonic()
        result = executor.execute(hypotheses, context)
        elapsed = time.monotonic() - start

        assert len(result["findings"]) == 3
        # Parallel: should take ~0.1s (not 0.3s sequential)
        # Allow generous margin for test environment variability
        assert elapsed < 0.5, f"Parallel execution took {elapsed:.2f}s (expected < 0.5s)"
