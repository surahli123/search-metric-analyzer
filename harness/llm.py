"""LLM factory for the orchestration harness.

WHY THIS MODULE EXISTS:
The orchestrator's HYPOTHESIZE, DISPATCH, and SYNTHESIZE stages all need to
call an LLM for reasoning.  Rather than coupling the orchestrator directly
to the Anthropic SDK, we wrap it in a factory that returns a simple callable:

    llm = make_anthropic_llm(model="claude-sonnet-4-20250514")
    response_text = llm("Analyze this metric drop...", system="You are a search analyst.")

This gives us:
1. **Testability** — Tests pass a mock callable instead of hitting a real API.
2. **Retry logic** — Exponential backoff for transient errors, fail-fast for permanent.
3. **JSON extraction** — LLM responses often contain JSON wrapped in prose;
   extract_json() pulls it out with a 3-strategy approach.
4. **Error classification** — Transient vs permanent errors determine retry behavior.

DESIGN DECISIONS:
- Synchronous (not async) — the orchestrator is a simple sequential pipeline.
- `anthropic` is an OPTIONAL dependency — checked at factory call time, not import time.
- The callable signature `(prompt, system, max_tokens) -> str` is intentionally
  simple.  The orchestrator builds structured prompts; the LLM just needs to
  execute them.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable

from harness.errors import LLMAPIError, LLMParseError, LLMRefusalError

# Module-level logger.  The orchestrator's logging config controls verbosity.
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type alias for the LLM callable that make_anthropic_llm() returns.
# This is the contract: prompt in, text out.  The orchestrator doesn't need
# to know anything about the Anthropic SDK, retry logic, or error handling.
# ---------------------------------------------------------------------------
LLMCallable = Callable[[str], str]



# ---------------------------------------------------------------------------
# Refusal Detection
# ---------------------------------------------------------------------------

REFUSAL_PHRASES = [
    "i cannot", "i can't", "i'm unable", "i am unable",
    "i'm not able", "i apologize, but i", "i'm sorry, but i cannot",
    "i don't think i should", "as an ai", "i must decline",
]


def detect_refusal(text: str) -> bool:
    """Check if an LLM response is a refusal rather than an attempt."""
    if not text:
        return False
    prefix = text[:300].lower()
    if "{" in text[:500]:
        return False
    return any(phrase in prefix for phrase in REFUSAL_PHRASES)


# ---------------------------------------------------------------------------
# JSON Extraction — 3-strategy approach
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict | list:
    """Extract JSON from an LLM response using a 3-strategy cascade.

    LLMs often wrap JSON in markdown fences, prose preambles, or trailing
    commentary.  This function tries increasingly aggressive extraction
    strategies until one works.

    Strategy 1: Direct parse — the response IS valid JSON.
    Strategy 2: Regex extract — find the first {...} or [...] block and parse it.
    Strategy 3: Give up — log a warning and raise LLMParseError.
                (A future version could re-prompt the LLM, but that requires
                 access to the LLM callable, which this standalone function
                 doesn't have.  The orchestrator handles re-prompting.)

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed JSON as a dict or list.

    Raises:
        LLMParseError: If no strategy can extract valid JSON.
    """
    strategies_tried: list[str] = []

    # --- Strategy 0: Refusal detection ---
    if detect_refusal(text):
        preview = text[:200] + "..." if len(text) > 200 else text
        logger.warning("LLM refused the task. Response preview: %s", preview)
        raise LLMRefusalError(
            message="LLM refused to perform the requested task.",
            raw_response=text,
        )

    # --- Strategy 1: Direct json.loads() on full response ---
    # Best case: the LLM followed instructions and returned pure JSON.
    strategies_tried.append("direct_parse")
    try:
        result = json.loads(text)
        if isinstance(result, (dict, list)):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # --- Strategy 2: Regex extract {...} or [...] then parse ---
    # Common pattern: LLM says "Here's the analysis:\n{...}\nLet me know..."
    # We use DOTALL so the regex spans multiple lines (JSON is often pretty-printed).
    strategies_tried.append("regex_extract")

    # Try to find a JSON object first (more common in our use case),
    # then fall back to JSON array.
    # WHY greedy match? We want the LARGEST valid JSON block, not the smallest.
    # Example: "text {outer: {inner: 1}} text" — we want the outer object.
    # But greedy can over-match if there are multiple top-level objects.
    # Since our prompts ask for a single JSON object, greedy is the right choice.
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, (dict, list)):
                    return result
            except json.JSONDecodeError:
                # The regex matched something that looks like JSON but isn't.
                # This happens with nested braces in prose, e.g., "use {x: 1} format".
                continue

    # --- Strategy 3: Give up — raise LLMParseError ---
    # At this point, the response doesn't contain parseable JSON.
    # Log a warning so operators can spot prompt engineering issues.
    # The caller (orchestrator) decides whether to retry or fail.
    strategies_tried.append("give_up")

    # Truncate the raw text for the log message to avoid flooding logs
    # with multi-KB LLM responses.
    preview = text[:200] + "..." if len(text) > 200 else text
    logger.warning(
        "JSON extraction failed after all strategies. "
        "Response preview: %s",
        preview,
    )

    raise LLMParseError(
        message=(
            "Could not extract valid JSON from LLM response. "
            "A re-prompt with explicit JSON instructions may help."
        ),
        raw_text=text,
        strategies_tried=strategies_tried,
    )


# ---------------------------------------------------------------------------
# Error Classification
# ---------------------------------------------------------------------------

def _classify_api_error(exc: Exception) -> LLMAPIError:
    """Classify an Anthropic SDK exception as transient or permanent.

    WHY classify errors?
    The retry loop needs to know whether retrying will help.  Rate limits
    and server errors are transient — waiting and retrying usually works.
    Auth errors and bad requests are permanent — retrying wastes time.

    This function inspects the exception type and status code to make
    that determination.  It wraps the raw SDK exception in our LLMAPIError
    so the rest of the harness doesn't need to import anthropic types.

    Args:
        exc: The exception raised by the Anthropic SDK.

    Returns:
        An LLMAPIError with is_transient set appropriately.
    """
    # Extract status_code if the exception has one (Anthropic SDK exceptions do).
    status_code = getattr(exc, "status_code", None)

    # Connection errors and timeouts don't have status codes.
    # They are always transient — the server was unreachable, not refusing us.
    if status_code is None:
        # Check for common connection/timeout exception types by name.
        # We can't import anthropic types here (it's optional), so we
        # inspect the class name instead.
        exc_name = type(exc).__name__
        if "Timeout" in exc_name or "Connection" in exc_name:
            return LLMAPIError(
                message=str(exc),
                status_code=None,
                is_transient=True,
            )
        # Unknown exception type — treat as permanent to be safe.
        # Better to fail fast than retry forever on an unknown error.
        return LLMAPIError(
            message=str(exc),
            status_code=None,
            is_transient=False,
        )

    # --- Status code classification ---
    # 429 = rate limit — transient, wait and retry.
    # 5xx = server error — transient, the server is having a bad time.
    # 4xx (except 429) = client error — permanent, our request is wrong.
    is_transient = status_code == 429 or status_code >= 500

    return LLMAPIError(
        message=str(exc),
        status_code=status_code,
        is_transient=is_transient,
    )


# ---------------------------------------------------------------------------
# Retry Logic
# ---------------------------------------------------------------------------

def _call_with_retry(
    call_fn: Callable[[], str],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
) -> str:
    """Call a function with exponential backoff retry on transient errors.

    Retry strategy:
    - Attempt 1: immediate
    - Attempt 2: wait base_delay seconds (1s default)
    - Attempt 3: wait base_delay * 2 seconds (2s default), capped at max_delay

    Only retries on transient errors (as classified by _classify_api_error).
    Permanent errors raise immediately — no point waiting.

    Args:
        call_fn:      Zero-arg callable that makes the API call and returns text.
        max_attempts: Maximum number of attempts (default 3).
        base_delay:   Initial delay in seconds between retries (default 1.0).
        max_delay:    Cap on delay to prevent excessive waits (default 10.0).

    Returns:
        The response text from a successful call.

    Raises:
        LLMAPIError: If all attempts fail or a permanent error occurs.
    """
    last_error: LLMAPIError | None = None

    for attempt in range(max_attempts):
        try:
            return call_fn()
        except LLMAPIError:
            # Already classified — re-raise to be caught below.
            raise
        except Exception as exc:
            # Classify the raw SDK exception into our error hierarchy.
            api_error = _classify_api_error(exc)

            # Permanent errors: fail immediately, don't waste time retrying.
            if not api_error.is_transient:
                raise api_error from exc

            last_error = api_error

            # Transient errors: wait and retry (unless this was the last attempt).
            if attempt < max_attempts - 1:
                # Exponential backoff: delay doubles each attempt.
                # base_delay * (2 ** attempt): 1s, 2s, 4s, 8s, ...
                # Capped at max_delay to prevent absurdly long waits.
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.info(
                    "Transient error on attempt %d/%d, retrying in %.1fs: %s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    api_error,
                )
                time.sleep(delay)

    # All attempts exhausted — raise the last error.
    # This should only happen with transient errors (permanent errors raise above).
    assert last_error is not None, "Should have at least one error after exhausting retries"
    raise last_error


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_anthropic_llm(
    model: str = "claude-sonnet-4-20250514",
    timeout: float = 120.0,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
) -> Callable[[str, str, int], str]:
    """Factory that returns a callable wrapping the Anthropic Client SDK.

    The returned callable has this signature:
        (prompt: str, system: str = "", max_tokens: int = 4096) -> str

    It handles:
    - SDK client creation (with configurable timeout)
    - Exponential backoff retry for transient errors
    - Error classification (transient vs permanent)

    IMPORTANT: The `anthropic` package is an OPTIONAL dependency.
    This factory checks for it at call time and raises ImportError with
    a helpful message if it's not installed.

    Args:
        model:       Anthropic model identifier (default: claude-sonnet-4-20250514).
        timeout:     Request timeout in seconds (default: 120s).
        max_retries: Maximum retry attempts for transient errors (default: 3).
        base_delay:  Initial retry delay in seconds (default: 1.0).
        max_delay:   Maximum retry delay in seconds (default: 10.0).

    Returns:
        A callable that sends prompts to the Anthropic API and returns response text.

    Raises:
        ImportError: If the `anthropic` package is not installed.
    """
    # --- Optional dependency check ---
    # We check at factory call time (not module import time) so that
    # importing harness.llm doesn't fail just because anthropic isn't installed.
    # This matters for tests and for code that only uses extract_json().
    try:
        import anthropic  # noqa: F811
    except ImportError:
        raise ImportError(
            "The 'anthropic' package is required for make_anthropic_llm(). "
            "Install it with: pip install anthropic"
        ) from None

    # Create the client once — reused across all calls from this callable.
    # The client handles connection pooling internally.
    client = anthropic.Anthropic(timeout=timeout)

    def llm_callable(
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
    ) -> str:
        """Call the Anthropic API with retry logic.

        Args:
            prompt:     The user message / prompt to send.
            system:     Optional system message for the model.
            max_tokens: Maximum tokens in the response (default 4096).

        Returns:
            The model's response text.

        Raises:
            LLMAPIError: If the API call fails after all retries.
        """
        def _do_call() -> str:
            """Inner function that makes the actual API call.

            Separated so _call_with_retry can call it without arguments.
            """
            # Build the messages list.  Anthropic expects a list of message dicts.
            messages = [{"role": "user", "content": prompt}]

            # Build kwargs — only include system if non-empty.
            # The Anthropic SDK accepts system as a top-level kwarg, not in messages.
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system

            response = client.messages.create(**kwargs)

            # Extract the text from the first content block.
            # Anthropic responses have a content list with TextBlock objects.
            if response.content and len(response.content) > 0:
                return response.content[0].text
            return ""

        return _call_with_retry(
            _do_call,
            max_attempts=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
        )

    return llm_callable
