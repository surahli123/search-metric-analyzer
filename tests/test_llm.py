"""Tests for the LLM factory and JSON extraction helpers.

Test categories:
    A. extract_json() — 3-strategy JSON extraction from LLM responses
    B. Error hierarchy — error types, attributes, inheritance
    C. Error classification — transient vs permanent mapping
    D. Retry logic — exponential backoff, attempt counting, error propagation
    E. make_anthropic_llm() — factory behavior (mocked SDK)
    E2. make_openai_llm() — OpenAI-compatible factory (mocked SDK)
    F. Module exports — harness __init__.py re-exports

All tests mock the LLM SDKs — no real API calls are made.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch, PropertyMock
import types

import pytest

from harness.errors import (
    LLMAPIError,
    LLMError,
    LLMParseError,
    OrchestratorError,
    StageError,
)
from harness.llm import (
    _call_with_retry,
    _classify_api_error,
    extract_json,
)


# ===========================================================================
# A. extract_json() — 3-strategy JSON extraction
# ===========================================================================


class TestExtractJsonStrategy1:
    """Strategy 1: Direct json.loads() on the full response."""

    def test_pure_json_object(self):
        """When the response IS a valid JSON object, return it directly."""
        text = '{"metric": "click_quality", "delta": -0.05}'
        result = extract_json(text)
        assert result == {"metric": "click_quality", "delta": -0.05}

    def test_pure_json_array(self):
        """When the response IS a valid JSON array, return it directly."""
        text = '[{"hypothesis": "ranking_regression"}, {"hypothesis": "mix_shift"}]'
        result = extract_json(text)
        assert len(result) == 2
        assert result[0]["hypothesis"] == "ranking_regression"

    def test_pure_json_with_whitespace(self):
        """Leading/trailing whitespace shouldn't break direct parse."""
        text = '  \n  {"status": "ok"}  \n  '
        result = extract_json(text)
        assert result == {"status": "ok"}

    def test_nested_json(self):
        """Deeply nested JSON should parse correctly."""
        data = {
            "analysis": {
                "decomposition": {
                    "dimensions": ["tenant_tier", "ai_enablement"],
                    "top_contributor": {"segment": "standard", "pct": 85.0},
                }
            }
        }
        text = json.dumps(data)
        result = extract_json(text)
        assert result == data

    def test_empty_object(self):
        """Empty JSON object should parse fine."""
        result = extract_json("{}")
        assert result == {}

    def test_empty_array(self):
        """Empty JSON array should parse fine."""
        result = extract_json("[]")
        assert result == []


class TestExtractJsonStrategy2:
    """Strategy 2: Regex extract {...} or [...] then parse."""

    def test_json_wrapped_in_prose(self):
        """Common LLM pattern: prose before and after JSON."""
        text = (
            "Here's my analysis:\n"
            '{"hypothesis": "ranking_regression", "confidence": 0.85}\n'
            "Let me know if you need more detail."
        )
        result = extract_json(text)
        assert result["hypothesis"] == "ranking_regression"

    def test_json_in_markdown_fence(self):
        """LLMs often wrap JSON in ```json ... ``` fences."""
        text = (
            "```json\n"
            '{"metric": "sqs", "direction": "down"}\n'
            "```"
        )
        result = extract_json(text)
        assert result["metric"] == "sqs"

    def test_multiline_json_in_prose(self):
        """Multi-line pretty-printed JSON embedded in prose."""
        text = (
            "Based on the data, here's the result:\n"
            "{\n"
            '  "archetype": "ai_adoption",\n'
            '  "segments": [\n'
            '    {"tier": "standard", "delta": -0.02},\n'
            '    {"tier": "premium", "delta": -0.01}\n'
            "  ]\n"
            "}\n"
            "This indicates a positive AI adoption pattern."
        )
        result = extract_json(text)
        assert result["archetype"] == "ai_adoption"
        assert len(result["segments"]) == 2

    def test_json_array_in_prose(self):
        """Array JSON embedded in prose should be extracted."""
        text = (
            "The hypotheses are:\n"
            '[{"name": "h1"}, {"name": "h2"}]\n'
            "Ranked by likelihood."
        )
        result = extract_json(text)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_json_object_preferred_over_array(self):
        """When both object and array are present, object is found first."""
        text = 'prefix {"key": "value"} middle [1,2,3] suffix'
        result = extract_json(text)
        # Object regex is tried first, so we get the object.
        assert result == {"key": "value"}


class TestExtractJsonStrategy3:
    """Strategy 3: Give up — raise LLMParseError."""

    def test_no_json_at_all(self):
        """Plain text with no JSON should raise LLMParseError."""
        with pytest.raises(LLMParseError) as exc_info:
            extract_json("This is just plain text with no JSON anywhere.")
        assert "Could not extract valid JSON" in str(exc_info.value)
        assert exc_info.value.raw_text == "This is just plain text with no JSON anywhere."
        assert "direct_parse" in exc_info.value.strategies_tried
        assert "regex_extract" in exc_info.value.strategies_tried
        assert "give_up" in exc_info.value.strategies_tried

    def test_invalid_json_braces(self):
        """Text with braces that aren't valid JSON should fail."""
        with pytest.raises(LLMParseError):
            extract_json("The function uses {x: 1} syntax which is not JSON.")

    def test_empty_string(self):
        """Empty string should raise LLMParseError."""
        with pytest.raises(LLMParseError):
            extract_json("")

    def test_raw_text_preserved_on_error(self):
        """The raw text should be preserved on the exception for re-prompting."""
        long_text = "A" * 500
        with pytest.raises(LLMParseError) as exc_info:
            extract_json(long_text)
        # Full raw text is preserved (not truncated — truncation is only for logs).
        assert exc_info.value.raw_text == long_text

    def test_number_string_not_dict_or_list(self):
        """A valid JSON number is not a dict or list — should fail."""
        with pytest.raises(LLMParseError):
            extract_json("42")

    def test_string_value_not_dict_or_list(self):
        """A valid JSON string is not a dict or list — should fail."""
        with pytest.raises(LLMParseError):
            extract_json('"just a string"')


# ===========================================================================
# B. Error hierarchy — types, attributes, inheritance
# ===========================================================================


class TestErrorHierarchy:
    """Verify the error class hierarchy and attributes."""

    def test_orchestrator_error_is_base(self):
        """All harness errors should inherit from OrchestratorError."""
        assert issubclass(StageError, OrchestratorError)
        assert issubclass(LLMError, OrchestratorError)
        assert issubclass(LLMAPIError, OrchestratorError)
        assert issubclass(LLMParseError, OrchestratorError)

    def test_llm_errors_inherit_from_llm_error(self):
        """LLMAPIError and LLMParseError both inherit from LLMError."""
        assert issubclass(LLMAPIError, LLMError)
        assert issubclass(LLMParseError, LLMError)

    def test_stage_error_attributes(self):
        """StageError should carry stage name and optional violations."""
        err = StageError("prompt too long", stage="HYPOTHESIZE", violations=["missing field"])
        assert err.stage == "HYPOTHESIZE"
        assert err.violations == ["missing field"]
        assert "prompt too long" in str(err)

    def test_stage_error_without_violations(self):
        """StageError without violations should still work."""
        err = StageError("missing data", stage="UNDERSTAND")
        assert err.stage == "UNDERSTAND"
        assert err.violations == []

    def test_llm_api_error_attributes(self):
        """LLMAPIError should carry status_code and is_transient."""
        err = LLMAPIError("rate limited", status_code=429, is_transient=True)
        assert err.status_code == 429
        assert err.is_transient is True

    def test_llm_api_error_permanent(self):
        """Permanent LLMAPIError should be flagged correctly."""
        err = LLMAPIError("unauthorized", status_code=401, is_transient=False)
        assert err.is_transient is False

    def test_llm_api_error_no_status_code(self):
        """Connection errors may not have a status code."""
        err = LLMAPIError("connection refused", status_code=None, is_transient=True)
        assert err.status_code is None
        assert err.is_transient is True

    def test_llm_parse_error_attributes(self):
        """LLMParseError should carry raw_text and strategies_tried."""
        err = LLMParseError(
            "parse failed",
            raw_text="not json",
            strategies_tried=["direct_parse", "regex_extract"],
        )
        assert err.raw_text == "not json"
        assert err.strategies_tried == ["direct_parse", "regex_extract"]

    def test_llm_parse_error_defaults(self):
        """LLMParseError with no optional args should have safe defaults."""
        err = LLMParseError("parse failed")
        assert err.raw_text is None  # None when not provided
        assert err.strategies_tried == []

    def test_catch_all_orchestrator_errors(self):
        """A single except OrchestratorError should catch all harness errors."""
        errors = [
            OrchestratorError("base"),
            StageError("test", stage="UNDERSTAND"),
            LLMError("llm base"),
            LLMAPIError("api", status_code=500, is_transient=True),
            LLMParseError("parse"),
        ]
        for err in errors:
            with pytest.raises(OrchestratorError):
                raise err


# ===========================================================================
# C. Error classification — transient vs permanent
# ===========================================================================


class TestErrorClassification:
    """Test _classify_api_error() transient/permanent mapping."""

    def test_rate_limit_429_is_transient(self):
        """HTTP 429 (rate limit) should be classified as transient."""
        exc = Exception("rate limited")
        exc.status_code = 429  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert isinstance(result, LLMAPIError)
        assert result.is_transient is True
        assert result.status_code == 429

    def test_server_error_500_is_transient(self):
        """HTTP 500 should be classified as transient."""
        exc = Exception("internal server error")
        exc.status_code = 500  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert result.is_transient is True

    def test_server_error_502_is_transient(self):
        """HTTP 502 should be classified as transient."""
        exc = Exception("bad gateway")
        exc.status_code = 502  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert result.is_transient is True

    def test_server_error_503_is_transient(self):
        """HTTP 503 should be classified as transient."""
        exc = Exception("service unavailable")
        exc.status_code = 503  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert result.is_transient is True

    def test_auth_error_401_is_permanent(self):
        """HTTP 401 (unauthorized) should be classified as permanent."""
        exc = Exception("invalid api key")
        exc.status_code = 401  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert result.is_transient is False
        assert result.status_code == 401

    def test_bad_request_400_is_permanent(self):
        """HTTP 400 (bad request) should be classified as permanent."""
        exc = Exception("invalid request")
        exc.status_code = 400  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert result.is_transient is False

    def test_forbidden_403_is_permanent(self):
        """HTTP 403 (forbidden) should be classified as permanent."""
        exc = Exception("forbidden")
        exc.status_code = 403  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert result.is_transient is False

    def test_not_found_404_is_permanent(self):
        """HTTP 404 should be classified as permanent."""
        exc = Exception("not found")
        exc.status_code = 404  # type: ignore[attr-defined]
        result = _classify_api_error(exc)
        assert result.is_transient is False

    def test_timeout_exception_is_transient(self):
        """Timeout exceptions (by class name) should be transient."""
        # Simulate an anthropic.APITimeoutError without importing the SDK.
        exc = type("APITimeoutError", (Exception,), {})("request timed out")
        result = _classify_api_error(exc)
        assert result.is_transient is True
        assert result.status_code is None

    def test_connection_exception_is_transient(self):
        """Connection exceptions (by class name) should be transient."""
        exc = type("APIConnectionError", (Exception,), {})("connection refused")
        result = _classify_api_error(exc)
        assert result.is_transient is True
        assert result.status_code is None

    def test_unknown_exception_is_permanent(self):
        """Unknown exception types without status_code default to permanent."""
        exc = RuntimeError("something unexpected")
        result = _classify_api_error(exc)
        assert result.is_transient is False


# ===========================================================================
# D. Retry logic — exponential backoff
# ===========================================================================


class TestCallWithRetry:
    """Test _call_with_retry() backoff and error propagation."""

    def test_success_on_first_attempt(self):
        """When the call succeeds immediately, return the result."""
        call_fn = MagicMock(return_value="response text")
        result = _call_with_retry(call_fn, max_attempts=3)
        assert result == "response text"
        assert call_fn.call_count == 1

    @patch("harness.llm.time.sleep")
    def test_success_after_transient_error(self, mock_sleep):
        """Should retry on transient error and succeed on next attempt."""
        # First call raises transient error, second succeeds.
        transient_exc = type("APITimeoutError", (Exception,), {})("timeout")
        call_fn = MagicMock(side_effect=[transient_exc, "success"])
        result = _call_with_retry(
            call_fn, max_attempts=3, base_delay=1.0, max_delay=10.0
        )
        assert result == "success"
        assert call_fn.call_count == 2
        # Should have slept once (between attempt 1 and 2).
        mock_sleep.assert_called_once_with(1.0)  # base_delay * 2^0

    @patch("harness.llm.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        """Verify delay doubles each attempt: 1s, 2s, ..."""
        transient_exc = type("APITimeoutError", (Exception,), {})("timeout")
        call_fn = MagicMock(
            side_effect=[transient_exc, transient_exc, "success"]
        )
        result = _call_with_retry(
            call_fn, max_attempts=3, base_delay=1.0, max_delay=10.0
        )
        assert result == "success"
        assert call_fn.call_count == 3
        # Delays: attempt 0 → sleep(1.0), attempt 1 → sleep(2.0)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("harness.llm.time.sleep")
    def test_delay_capped_at_max(self, mock_sleep):
        """Delay should not exceed max_delay."""
        transient_exc = type("APITimeoutError", (Exception,), {})("timeout")
        call_fn = MagicMock(
            side_effect=[transient_exc, transient_exc, transient_exc, "success"]
        )
        result = _call_with_retry(
            call_fn, max_attempts=4, base_delay=2.0, max_delay=5.0
        )
        assert result == "success"
        # Delays: 2.0, 4.0, 5.0 (capped, would have been 8.0)
        calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert calls == [2.0, 4.0, 5.0]

    @patch("harness.llm.time.sleep")
    def test_all_transient_retries_exhausted(self, mock_sleep):
        """Should raise LLMAPIError after all attempts fail with transient errors."""
        transient_exc = type("APITimeoutError", (Exception,), {})("timeout")
        call_fn = MagicMock(
            side_effect=[transient_exc, transient_exc, transient_exc]
        )
        with pytest.raises(LLMAPIError) as exc_info:
            _call_with_retry(call_fn, max_attempts=3, base_delay=1.0)
        assert exc_info.value.is_transient is True
        assert call_fn.call_count == 3

    def test_permanent_error_fails_immediately(self):
        """Permanent errors should raise immediately without retrying."""
        permanent_exc = Exception("unauthorized")
        permanent_exc.status_code = 401  # type: ignore[attr-defined]
        call_fn = MagicMock(side_effect=permanent_exc)
        with pytest.raises(LLMAPIError) as exc_info:
            _call_with_retry(call_fn, max_attempts=3)
        assert exc_info.value.is_transient is False
        assert exc_info.value.status_code == 401
        # Should have only called once — no retries for permanent errors.
        assert call_fn.call_count == 1

    def test_single_attempt_no_retry(self):
        """With max_attempts=1, should not retry at all."""
        transient_exc = type("APITimeoutError", (Exception,), {})("timeout")
        call_fn = MagicMock(side_effect=transient_exc)
        with pytest.raises(LLMAPIError):
            _call_with_retry(call_fn, max_attempts=1)
        assert call_fn.call_count == 1


# ===========================================================================
# E. make_anthropic_llm() — factory behavior (mocked SDK)
# ===========================================================================


class TestMakeAnthropicLLM:
    """Test the factory function with a mocked Anthropic SDK."""

    def _make_mock_anthropic_module(self, response_text: str = "test response"):
        """Create a mock anthropic module with a mock client.

        Returns:
            (mock_module, mock_client) tuple — the module for patching and
            the client for assertions.
        """
        # Build a mock response that looks like an Anthropic Messages response.
        mock_content_block = MagicMock()
        mock_content_block.text = response_text

        mock_response = MagicMock()
        mock_response.content = [mock_content_block]

        # Build a mock client.
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        # Build a mock module that acts like `import anthropic`.
        mock_module = MagicMock()
        mock_module.Anthropic.return_value = mock_client

        return mock_module, mock_client

    def test_factory_returns_callable(self):
        """make_anthropic_llm() should return a callable."""
        mock_module, _ = self._make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            llm = make_anthropic_llm()
            assert callable(llm)

    def test_callable_returns_response_text(self):
        """The returned callable should return the model's response text."""
        mock_module, mock_client = self._make_mock_anthropic_module(
            response_text='{"hypothesis": "ranking_regression"}'
        )
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            llm = make_anthropic_llm(model="claude-sonnet-4-20250514")
            result = llm("Analyze this metric drop")
            assert result == '{"hypothesis": "ranking_regression"}'

    def test_callable_passes_system_message(self):
        """System message should be passed to the API when provided."""
        mock_module, mock_client = self._make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            llm = make_anthropic_llm()
            llm("prompt", system="You are a search analyst.")

            # Verify the system kwarg was passed.
            call_kwargs = mock_client.messages.create.call_args
            assert call_kwargs.kwargs.get("system") == "You are a search analyst."

    def test_callable_omits_empty_system(self):
        """Empty system message should NOT be passed to the API."""
        mock_module, mock_client = self._make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            llm = make_anthropic_llm()
            llm("prompt", system="")

            call_kwargs = mock_client.messages.create.call_args
            assert "system" not in call_kwargs.kwargs

    def test_callable_passes_max_tokens(self):
        """max_tokens should be forwarded to the API."""
        mock_module, mock_client = self._make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            llm = make_anthropic_llm()
            llm("prompt", max_tokens=1024)

            call_kwargs = mock_client.messages.create.call_args
            assert call_kwargs.kwargs.get("max_tokens") == 1024

    def test_callable_uses_configured_model(self):
        """The model parameter should be forwarded to the API."""
        mock_module, mock_client = self._make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            llm = make_anthropic_llm(model="claude-opus-4-20250514")
            llm("prompt")

            call_kwargs = mock_client.messages.create.call_args
            assert call_kwargs.kwargs.get("model") == "claude-opus-4-20250514"

    def test_callable_handles_empty_content(self):
        """If the response has no content blocks, return empty string."""
        mock_module, _ = self._make_mock_anthropic_module()
        # Override: empty content list.
        mock_response = MagicMock()
        mock_response.content = []
        mock_client = mock_module.Anthropic.return_value
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            llm = make_anthropic_llm()
            result = llm("prompt")
            assert result == ""

    def test_factory_sets_timeout_on_client(self):
        """The timeout parameter should be passed to the Anthropic client."""
        mock_module, _ = self._make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from harness.llm import make_anthropic_llm
            make_anthropic_llm(timeout=60.0)
            # Verify the client was created with the timeout.
            mock_module.Anthropic.assert_called_once_with(timeout=60.0)


class TestMakeAnthropicLLMImportError:
    """Test behavior when anthropic package is not installed."""

    def test_missing_anthropic_raises_import_error(self):
        """Should raise ImportError with helpful message when anthropic is missing."""
        # Remove anthropic from sys.modules and make import fail.
        with patch.dict("sys.modules", {"anthropic": None}):
            # Need to reload llm module to re-trigger the import.
            # Alternatively, just call the factory which does the import.
            with pytest.raises(ImportError) as exc_info:
                # Force re-import by importing from scratch.
                import importlib
                import harness.llm
                importlib.reload(harness.llm)
                harness.llm.make_anthropic_llm()
            assert "pip install anthropic" in str(exc_info.value)


# ===========================================================================
# E2. make_openai_llm() — OpenAI-compatible factory (mocked SDK)
# ===========================================================================


class TestMakeOpenAILLM:
    """Test the OpenAI-compatible factory with a mocked OpenAI SDK.

    Mirrors TestMakeAnthropicLLM structure for parity.
    WHY separate class: OpenAI message format (system in messages array) and
    response format (choices[0].message.content) differ from Anthropic.
    """

    def _make_mock_openai_module(self, response_text: str = "test response"):
        """Create a mock openai module with a mock client.

        Returns:
            (mock_module, mock_client) tuple — the module for patching and
            the client for assertions.
        """
        # Build a mock response that looks like an OpenAI ChatCompletion.
        # response.choices[0].message.content
        mock_message = MagicMock()
        mock_message.content = response_text

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Build a mock client.
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        # Build a mock module that acts like `import openai`.
        mock_module = MagicMock()
        mock_module.OpenAI.return_value = mock_client

        return mock_module, mock_client

    def test_factory_returns_callable(self):
        """make_openai_llm() should return a callable."""
        mock_module, _ = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(api_key="test-key")
            assert callable(llm)

    def test_callable_returns_response_text(self):
        """The returned callable should return the model's response text."""
        mock_module, _ = self._make_mock_openai_module(
            response_text='{"hypothesis": "ranking_regression"}'
        )
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(api_key="test-key")
            result = llm("Analyze this metric drop")
            assert result == '{"hypothesis": "ranking_regression"}'

    def test_callable_passes_system_message(self):
        """System message should be in the messages array, NOT a top-level kwarg."""
        mock_module, mock_client = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(api_key="test-key")
            llm("prompt", system="You are a search analyst.")

            call_kwargs = mock_client.chat.completions.create.call_args
            messages = call_kwargs.kwargs.get("messages", [])
            # First message should be system, second should be user.
            assert messages[0] == {"role": "system", "content": "You are a search analyst."}
            assert messages[1] == {"role": "user", "content": "prompt"}

    def test_callable_omits_empty_system(self):
        """Empty system message should NOT be included in messages array."""
        mock_module, mock_client = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(api_key="test-key")
            llm("prompt", system="")

            call_kwargs = mock_client.chat.completions.create.call_args
            messages = call_kwargs.kwargs.get("messages", [])
            # Only user message — no system message.
            assert len(messages) == 1
            assert messages[0] == {"role": "user", "content": "prompt"}

    def test_callable_passes_max_tokens(self):
        """max_tokens should be forwarded to the API."""
        mock_module, mock_client = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(api_key="test-key")
            llm("prompt", max_tokens=1024)

            call_kwargs = mock_client.chat.completions.create.call_args
            assert call_kwargs.kwargs.get("max_tokens") == 1024

    def test_callable_uses_configured_model(self):
        """The model parameter should be forwarded to the API."""
        mock_module, mock_client = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(
                model="deepseek/deepseek-v3.2",
                api_key="test-key",
            )
            llm("prompt")

            call_kwargs = mock_client.chat.completions.create.call_args
            assert call_kwargs.kwargs.get("model") == "deepseek/deepseek-v3.2"

    def test_callable_handles_empty_choices(self):
        """If the response has no choices, return empty string."""
        mock_module, _ = self._make_mock_openai_module()
        # Override: empty choices list.
        mock_response = MagicMock()
        mock_response.choices = []
        mock_client = mock_module.OpenAI.return_value
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(api_key="test-key")
            result = llm("prompt")
            assert result == ""

    def test_callable_handles_none_content(self):
        """If message.content is None (e.g., tool_calls response), return empty string."""
        mock_module, _ = self._make_mock_openai_module()
        # Override: content is None.
        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client = mock_module.OpenAI.return_value
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            llm = make_openai_llm(api_key="test-key")
            result = llm("prompt")
            assert result == ""

    def test_factory_sets_base_url_on_client(self):
        """The base_url parameter should be passed to the OpenAI client.

        WHY this test: the entire point of this factory is to talk to
        non-OpenAI providers (Novita, Groq, etc.) via base_url.
        """
        mock_module, _ = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            make_openai_llm(
                base_url="https://api.novita.ai/openai/v1",
                api_key="test-key",
            )
            # Verify the client was created with the base_url.
            call_kwargs = mock_module.OpenAI.call_args
            assert call_kwargs.kwargs.get("base_url") == "https://api.novita.ai/openai/v1"

    def test_factory_sets_timeout_on_client(self):
        """The timeout parameter should be passed to the OpenAI client."""
        mock_module, _ = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            from harness.llm import make_openai_llm
            make_openai_llm(timeout=60.0, api_key="test-key")
            call_kwargs = mock_module.OpenAI.call_args
            assert call_kwargs.kwargs.get("timeout") == 60.0


class TestOpenAILLMApiKeyResolution:
    """Test API key resolution chain for make_openai_llm().

    Resolution order: explicit param > NOVITA_API_KEY > OPENAI_API_KEY > ValueError.
    """

    def _make_mock_openai_module(self):
        """Minimal mock — we only care about key resolution, not responses."""
        mock_module = MagicMock()
        mock_client = MagicMock()
        mock_module.OpenAI.return_value = mock_client
        # Set up a minimal valid response so the factory doesn't error.
        mock_msg = MagicMock()
        mock_msg.content = "ok"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        return mock_module

    def test_explicit_api_key_overrides_env(self):
        """Explicit api_key parameter should take precedence over env vars."""
        mock_module = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            with patch.dict("os.environ", {"NOVITA_API_KEY": "env-novita", "OPENAI_API_KEY": "env-openai"}):
                from harness.llm import make_openai_llm
                make_openai_llm(api_key="explicit-key")
                call_kwargs = mock_module.OpenAI.call_args
                assert call_kwargs.kwargs.get("api_key") == "explicit-key"

    def test_api_key_from_novita_env(self):
        """Should fall back to NOVITA_API_KEY when no explicit key."""
        mock_module = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            with patch.dict("os.environ", {"NOVITA_API_KEY": "novita-key"}, clear=False):
                # Ensure OPENAI_API_KEY is not set.
                import os
                os.environ.pop("OPENAI_API_KEY", None)
                from harness.llm import make_openai_llm
                make_openai_llm(api_key=None)
                call_kwargs = mock_module.OpenAI.call_args
                assert call_kwargs.kwargs.get("api_key") == "novita-key"

    def test_api_key_from_openai_env(self):
        """Should fall back to OPENAI_API_KEY when NOVITA_API_KEY is absent."""
        mock_module = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "openai-key"}, clear=False):
                import os
                os.environ.pop("NOVITA_API_KEY", None)
                from harness.llm import make_openai_llm
                make_openai_llm(api_key=None)
                call_kwargs = mock_module.OpenAI.call_args
                assert call_kwargs.kwargs.get("api_key") == "openai-key"

    def test_no_api_key_raises_value_error(self):
        """Should raise ValueError with helpful message when no key found."""
        mock_module = self._make_mock_openai_module()
        with patch.dict("sys.modules", {"openai": mock_module}):
            with patch.dict("os.environ", {}, clear=True):
                from harness.llm import make_openai_llm
                with pytest.raises(ValueError) as exc_info:
                    make_openai_llm(api_key=None)
                assert "NOVITA_API_KEY" in str(exc_info.value)
                assert "OPENAI_API_KEY" in str(exc_info.value)


class TestMakeOpenAILLMImportError:
    """Test behavior when openai package is not installed."""

    def test_missing_openai_raises_import_error(self):
        """Should raise ImportError with helpful message when openai is missing."""
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(ImportError) as exc_info:
                import importlib
                import harness.llm
                importlib.reload(harness.llm)
                harness.llm.make_openai_llm(api_key="test")
            assert "pip install openai" in str(exc_info.value)


class TestClassifyErrorOpenAI:
    """Verify _classify_api_error() handles OpenAI SDK error types.

    WHY: The classifier uses class-name inspection (e.g., "Timeout" in name).
    Both Anthropic and OpenAI SDKs follow similar naming conventions, so the
    existing classifier should work for both. These tests verify that.
    """

    def test_openai_rate_limit_is_transient(self):
        """OpenAI 429 (rate limit) should be classified as transient."""
        exc = type("RateLimitError", (Exception,), {"status_code": 429})()
        result = _classify_api_error(exc)
        assert result.is_transient is True
        assert result.status_code == 429

    def test_openai_auth_error_is_permanent(self):
        """OpenAI 401 (auth failure) should be classified as permanent."""
        exc = type("AuthenticationError", (Exception,), {"status_code": 401})()
        result = _classify_api_error(exc)
        assert result.is_transient is False
        assert result.status_code == 401

    def test_openai_timeout_is_transient(self):
        """OpenAI APITimeoutError (no status code) should be transient."""
        exc = type("APITimeoutError", (Exception,), {"status_code": None})()
        result = _classify_api_error(exc)
        assert result.is_transient is True


# ===========================================================================
# F. Module exports — harness __init__.py re-exports
# ===========================================================================


class TestModuleExports:
    """Verify that harness/__init__.py exports the new modules."""

    def test_error_exports(self):
        """Error classes should be importable from harness package."""
        from harness import (
            OrchestratorError,
            StageError,
            LLMError,
            LLMAPIError,
            LLMParseError,
        )
        # Verify they are the actual classes, not None or something else.
        assert issubclass(LLMAPIError, LLMError)

    def test_llm_exports(self):
        """extract_json and make_anthropic_llm should be importable from harness."""
        from harness import extract_json, make_anthropic_llm
        assert callable(extract_json)
        assert callable(make_anthropic_llm)

    def test_openai_llm_export(self):
        """make_openai_llm should be importable from harness."""
        from harness import make_openai_llm
        assert callable(make_openai_llm)


# ===========================================================================
# Edge cases and integration-like tests
# ===========================================================================


class TestExtractJsonEdgeCases:
    """Edge cases for JSON extraction that don't fit neatly into strategy categories."""

    def test_json_with_unicode(self):
        """JSON with unicode characters should parse correctly."""
        text = '{"query": "搜索质量", "result": "成功"}'
        result = extract_json(text)
        assert result["query"] == "搜索质量"

    def test_json_with_special_chars_in_strings(self):
        """JSON strings with escaped characters should parse correctly."""
        text = '{"message": "line1\\nline2\\ttab", "path": "C:\\\\Users"}'
        result = extract_json(text)
        assert "line1" in result["message"]

    def test_json_with_null_values(self):
        """JSON with null values should parse correctly."""
        text = '{"metric": "click_quality", "baseline": null}'
        result = extract_json(text)
        assert result["baseline"] is None

    def test_json_with_boolean_values(self):
        """JSON booleans (true/false) should parse correctly."""
        text = '{"is_regression": true, "is_expected": false}'
        result = extract_json(text)
        assert result["is_regression"] is True
        assert result["is_expected"] is False

    def test_multiple_json_objects_with_prose_between(self):
        """Multiple JSON objects separated by prose — greedy regex may over-match.

        The greedy {.*} pattern matches from the first { to the last },
        capturing everything in between.  If the intervening text is not
        valid JSON, extraction fails.  This is a known limitation documented
        in extract_json().  Our prompts always ask for a single JSON object,
        so this case shouldn't arise in practice.
        """
        text = (
            'Analysis: {"first": true} and also {"second": true} are found.'
        )
        # Greedy match produces '{"first": true} and also {"second": true}'
        # which is not valid JSON, so extraction fails.
        with pytest.raises(LLMParseError):
            extract_json(text)

    def test_single_json_object_in_prose_succeeds(self):
        """A single JSON object surrounded by prose should be extracted."""
        text = 'Analysis: {"result": "success", "count": 42} end.'
        result = extract_json(text)
        assert result == {"result": "success", "count": 42}

    def test_json_with_large_numbers(self):
        """Large numbers should parse correctly."""
        text = '{"impressions": 1234567890, "rate": 0.00001}'
        result = extract_json(text)
        assert result["impressions"] == 1234567890
        assert result["rate"] == 0.00001
