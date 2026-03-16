"""Error hierarchy for the orchestration harness.

WHY A SEPARATE ERROR MODULE:
The orchestrator needs to distinguish between different failure modes so it
can decide whether to retry (transient) or bail out (permanent).  Putting
errors in their own module avoids circular imports — any layer can import
errors without pulling in the full orchestrator or LLM machinery.

Think of this like HTTP status codes: the error TYPE tells the caller what
happened and what they can do about it, without the caller needing to parse
error messages.

HIERARCHY:
    OrchestratorError          — Base for all harness errors
    ├── StageError             — A pipeline stage failed (UNDERSTAND, HYPOTHESIZE, etc.)
    └── LLMError               — Base for all LLM-related errors
        ├── LLMAPIError        — The API call itself failed (network, auth, rate limit)
        └── LLMParseError      — Got a response but couldn't parse it (JSON extraction)
"""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base exception for all orchestration harness errors.

    Every error raised by the harness inherits from this, so callers can
    catch OrchestratorError to handle all harness failures in one place.
    This is the same pattern as requests.RequestException or
    botocore.exceptions.BotoCoreError.
    """
    pass


class StageError(OrchestratorError):
    """A named pipeline stage failed.

    Attributes:
        stage: Which stage failed (e.g., "UNDERSTAND", "HYPOTHESIZE").
        cause: The underlying exception, if any.

    WHY not just raise the underlying exception?
    Because the orchestrator needs to know WHICH STAGE failed, not just
    WHAT failed.  A ValueError from UNDERSTAND means something very
    different than a ValueError from SYNTHESIZE.  Wrapping the original
    exception preserves the root cause while adding stage context.
    """

    def __init__(self, stage: str, message: str, cause: Exception | None = None):
        self.stage = stage
        self.cause = cause
        # Include the stage name in the message so it's visible in tracebacks
        # without needing to inspect attributes.
        full_message = f"[{stage}] {message}"
        if cause:
            full_message += f" (caused by {type(cause).__name__}: {cause})"
        super().__init__(full_message)


class LLMError(OrchestratorError):
    """Base exception for all LLM-related failures.

    Subclassed into API errors (the call failed) and parse errors
    (the call succeeded but the response was unusable).  This distinction
    matters because API errors are often transient (retry helps) while
    parse errors are often permanent (retrying the same prompt gives
    the same bad output).
    """
    pass


class LLMAPIError(LLMError):
    """The LLM API call failed — network, auth, rate limit, server error.

    Attributes:
        status_code: HTTP status code if available (None for connection errors).
        is_transient: Whether this error is worth retrying.

    TRANSIENT vs PERMANENT classification:
    - Transient (retry):   429 (rate limit), 5xx (server), timeouts, connection errors
    - Permanent (no retry): 401 (auth), 400 (bad request), other 4xx
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        is_transient: bool = False,
    ):
        self.status_code = status_code
        self.is_transient = is_transient
        # Include status code in message for easy debugging in logs.
        prefix = f"[HTTP {status_code}]" if status_code else "[Connection]"
        transient_tag = " (transient)" if is_transient else " (permanent)"
        super().__init__(f"{prefix}{transient_tag} {message}")


class LLMParseError(LLMError):
    """Got a response from the LLM but couldn't extract valid JSON.

    Attributes:
        raw_text: The raw LLM response that failed to parse.
        strategy_tried: Which extraction strategies were attempted.

    WHY keep the raw text?
    The orchestrator's retry logic may want to re-prompt with the raw text
    as context ("your previous response wasn't valid JSON, try again").
    Keeping it on the exception avoids needing to re-fetch it.
    """

    def __init__(
        self,
        message: str,
        raw_text: str = "",
        strategies_tried: list[str] | None = None,
    ):
        self.raw_text = raw_text
        self.strategies_tried = strategies_tried or []
        super().__init__(message)
