"""Error hierarchy for the SearchMetricOrchestrator pipeline.

WHY A CUSTOM HIERARCHY:
The orchestrator needs to distinguish between different failure modes to apply
the right recovery strategy:
- StageError: A specific pipeline stage failed (UNDERSTAND, HYPOTHESIZE, etc.)
  The caller can inspect which stage failed and potentially retry or skip.
- LLMError: The LLM callable failed (timeout, parse error, API error).
  Subcategories (LLMParseError, LLMAPIError) tell the caller whether to retry
  (API errors are often transient) or fix the prompt (parse errors persist).

All errors inherit from OrchestratorError so callers can catch broad or narrow.

Think of it like HTTP status codes:
- OrchestratorError = any 4xx/5xx
- StageError = 5xx (server/pipeline issue)
- LLMError = 502/503 (upstream dependency issue)
  - LLMAPIError = 503 (transient, retry)
  - LLMParseError = 502 (bad response, fix prompt)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class OrchestratorError(Exception):
    """Base error for all orchestrator pipeline failures.

    Catch this to handle any orchestrator error without caring about the
    specific failure mode. Equivalent to catching all 4xx/5xx HTTP errors.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.details = details or {}
        super().__init__(message)


class StageError(OrchestratorError):
    """A specific pipeline stage failed.

    Attributes:
        stage: Which stage failed ("UNDERSTAND", "HYPOTHESIZE", etc.)
        violations: List of specific validation violations that caused the failure.

    Recovery: Depends on the stage's gate tier (hard/soft/retry).
    - UNDERSTAND (hard): Cannot continue. Return blocked report.
    - HYPOTHESIZE (soft): Log warning, continue with degraded output.
    - DISPATCH (soft): Log warning, continue with partial findings.
    - SYNTHESIZE (retry): Retry once, then fall back to soft.
    """

    def __init__(
        self,
        message: str,
        stage: str,
        violations: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.stage = stage
        self.violations = violations or []
        super().__init__(message, details)


class LLMError(OrchestratorError):
    """The LLM callable failed during a pipeline stage.

    Base class for LLM-related errors. Subclasses distinguish between
    transient (API) and persistent (parse) failures.

    Attributes:
        stage: Which stage was executing when the LLM failed.
        is_transient: Whether the error is likely transient (retry-worthy).
    """

    def __init__(
        self,
        message: str,
        stage: str,
        is_transient: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.stage = stage
        self.is_transient = is_transient
        super().__init__(message, details)


class LLMParseError(LLMError):
    """LLM returned a response that couldn't be parsed as expected.

    This is a PERSISTENT error — retrying with the same prompt will likely
    produce the same unparseable output. The fix is to adjust the prompt
    or use a different extraction strategy.

    Example: Asked for JSON, got free-text narrative.

    Attributes:
        raw_response: The raw LLM response that couldn't be parsed.
    """

    def __init__(
        self,
        message: str,
        stage: str,
        raw_response: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.raw_response = raw_response
        # Parse errors are NOT transient — retrying won't help
        super().__init__(message, stage, is_transient=False, details=details)


class LLMAPIError(LLMError):
    """LLM API call failed (timeout, rate limit, server error).

    This is a TRANSIENT error — retrying after a delay will often succeed.
    The orchestrator should apply exponential backoff before retrying.

    Example: API returned 429 (rate limited) or 503 (server overloaded).

    Attributes:
        status_code: HTTP status code if available (e.g., 429, 503).
    """

    def __init__(
        self,
        message: str,
        stage: str,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.status_code = status_code
        # API errors ARE transient — retrying usually helps
        super().__init__(message, stage, is_transient=True, details=details)
