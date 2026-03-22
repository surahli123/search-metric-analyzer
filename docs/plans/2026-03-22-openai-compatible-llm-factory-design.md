# Design: Generic OpenAI-Compatible LLM Factory

**Status:** APPROVED
**Branch:** TBD (create before implementation)
**Eng Review:** 1 round CLEARED — 2 issues resolved, 0 open

## Problem Statement

The Search Metric Analyzer orchestrator needs an LLM to run investigations (HYPOTHESIZE, DISPATCH, SYNTHESIZE stages). The only factory is `make_anthropic_llm()`, which requires Anthropic API credits ($$$). The user has $50 in Novita AI credits and wants to test the full pipeline cheaply using open-source models (DeepSeek V3.2, Kimi K2.5, MiniMax, etc.) via Novita's OpenAI-compatible API.

This also sets up KDD competition generalization — the pipeline needs to work with any LLM provider.

## Constraints

- $50 Novita AI budget (~12,500 investigations at DeepSeek V3.2 pricing)
- Must reuse existing `_call_with_retry()` and `extract_json()` — no duplication
- Must work with any OpenAI-compatible API (Novita, Together, Groq, local vLLM)
- `openai` SDK is an OPTIONAL dependency (same pattern as `anthropic`)
- Phoenix auto-instrumentation must work for OpenAI SDK calls too

## Architecture

```
harness/llm.py (MODIFIED — ~50 lines added)
├── make_anthropic_llm()       # existing — unchanged
├── make_openai_llm()          # NEW — OpenAI-compatible factory
│   ├── base_url: str          # e.g., "https://api.novita.ai/openai/v1"
│   ├── api_key: str | None    # explicit > env fallback chain
│   └── model: str             # e.g., "deepseek/deepseek-v3.2"
├── extract_json()             # existing — shared by both factories
├── _call_with_retry()         # existing — shared by both factories
└── _classify_api_error()      # MODIFIED — handles both SDK exception types

requirements-dev.txt (MODIFIED — 1 line added)
└── openai                     # OpenAI-compatible SDK
└── openinference-instrumentation-openai  # Phoenix auto-instrumentation

harness/phoenix_tracer.py (MODIFIED — ~5 lines added)
└── register_phoenix()         # Add OpenAIInstrumentor().instrument()
```

## Key Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | API key resolution | Explicit param + env fallback (NOVITA_API_KEY → OPENAI_API_KEY) | Most reliable. Explicit > magic. No env var collisions between providers. |
| 2 | Error classification | Extend existing `_classify_api_error()` | DRY. One function handles both SDKs via exception class name inspection. |
| 3 | Phoenix instrumentation | Add `openinference-instrumentation-openai` | Without this, OpenAI SDK calls are invisible in Phoenix traces. ~5 lines. |
| 4 | Dependency pattern | Optional import at factory call time | Matches `make_anthropic_llm()` pattern. `import openai` only when called. |

## Usage

```python
from harness.llm import make_openai_llm
from harness.orchestrator import SearchMetricOrchestrator

# Create LLM callable pointing at Novita AI
llm = make_openai_llm(
    base_url="https://api.novita.ai/openai/v1",
    api_key="your-novita-key",  # or set NOVITA_API_KEY env var
    model="deepseek/deepseek-v3.2",
)

# Use it exactly like make_anthropic_llm() — same signature
orch = SearchMetricOrchestrator(llm_callable=llm)
result = orch.run(
    question="Click Quality dropped 6.2% WoW",
    rows=metric_rows,
    metric_field="click_quality_value",
    dimensions=["tenant_tier", "ai_enablement"],
)
```

## Pre-Implementation Fix

**Delete stale `LLMCallable` alias in `harness/llm.py:45`.** It says `Callable[[str], str]` (1-arg) but the actual callable signature is `(prompt, system, max_tokens) -> str` (3-arg, per `harness/types.py`). This is a pre-existing bug that would confuse the implementer.

## Function Signature

```python
def make_openai_llm(
    base_url: str = "https://api.novita.ai/openai/v1",
    model: str = "deepseek/deepseek-v3.2",
    api_key: str | None = None,
    timeout: float = 120.0,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
) -> Callable[[str, str, int], str]:
```

**API key resolution order:**
1. `api_key` parameter (if provided)
2. `NOVITA_API_KEY` environment variable
3. `OPENAI_API_KEY` environment variable
4. Raise `ValueError` with helpful message

## Message Construction (differs from Anthropic)

OpenAI puts system messages in the `messages` array, NOT as a top-level kwarg:

```python
# Anthropic (existing):
kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
if system:
    kwargs["system"] = system  # top-level kwarg

# OpenAI (new — must build messages differently):
messages = []
if system:
    messages.append({"role": "system", "content": system})
messages.append({"role": "user", "content": prompt})
```

## Response Extraction (differs from Anthropic)

```python
# Anthropic: response.content[0].text
# OpenAI:    response.choices[0].message.content

response = client.chat.completions.create(**kwargs)
if response.choices and len(response.choices) > 0:
    content = response.choices[0].message.content
    return content if content else ""
return ""
```

**Edge case:** `choices` can be empty or `message.content` can be `None` (e.g., tool_calls response). Guard both.

## Error Classification Updates

`_classify_api_error()` currently inspects Anthropic SDK exceptions. Both SDKs use `status_code` attributes and similar class naming patterns ("Timeout", "Connection"), so the existing classifier may already work. **Verify during implementation** — if it does, the only change is updating the docstring. If not, add OpenAI-specific handling:

| OpenAI Exception | Status Code | Transient? |
|-----------------|-------------|------------|
| `openai.RateLimitError` | 429 | Yes — retry |
| `openai.APITimeoutError` | None | Yes — retry |
| `openai.APIConnectionError` | None | Yes — retry |
| `openai.InternalServerError` | 500 | Yes — retry |
| `openai.AuthenticationError` | 401 | No — fail fast |
| `openai.BadRequestError` | 400 | No — fail fast |

Detection: both SDKs use `status_code` attributes and similar class names. Verify existing `_classify_api_error()` handles both before adding new logic. If it already works, just update the docstring.

## Phoenix Integration Update

In `register_phoenix()`, add after the Anthropic instrumentor:

```python
try:
    from openinference.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument(tracer_provider=provider)
except ImportError:
    pass  # openai instrumentation not installed — skip
```

This is safe because:
- The import is inside try/except (same pattern as existing AnthropicInstrumentor)
- If the openai instrumentor isn't installed, it silently skips
- If it IS installed, all `client.chat.completions.create()` calls emit LLM spans

## Test Plan

8 tests in `tests/test_llm.py` (existing file):

| Test | What it verifies |
|------|-----------------|
| `test_make_openai_llm_returns_callable` | Factory returns `(str, str, int) -> str` callable |
| `test_openai_llm_calls_api_correctly` | Correct model, messages, max_tokens passed to SDK |
| `test_openai_llm_api_key_from_env` | Falls back to NOVITA_API_KEY then OPENAI_API_KEY |
| `test_openai_llm_no_api_key_raises` | Clear ValueError when no key found anywhere |
| `test_openai_llm_missing_package_raises` | ImportError with helpful install message |
| `test_classify_error_openai_rate_limit` | 429 classified as transient |
| `test_classify_error_openai_auth` | 401 classified as permanent |
| `test_openai_llm_empty_choices` | Handles empty `choices` array or `None` content gracefully |

All tests mock the OpenAI SDK — no real API calls.

## File Change Summary

| File | Action | Lines |
|------|--------|-------|
| `harness/llm.py` | MODIFY | ~50 added |
| `harness/phoenix_tracer.py` | MODIFY | ~5 added |
| `requirements-dev.txt` | MODIFY | 2 lines added |
| `tests/test_llm.py` | MODIFY | ~90 added (8 tests) |
| `harness/llm.py:45` | FIX | Delete stale 1-arg `LLMCallable` alias |

## NOT in Scope

- Multi-provider routing (use provider A for stage X, provider B for stage Y)
- Cost tracking / token counting per provider
- Model quality comparison (DeepSeek vs Kimi vs MiniMax)
- KDD-specific adaptations (separate design when needed)
- Streaming support (not needed for pipeline — batch responses only)

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Open-source models produce unparseable JSON | `extract_json()` already handles markdown fences, prose wrapping. If model quality is too low, switch to a better model — the factory is model-agnostic. |
| Novita API rate limits | `_call_with_retry()` handles 429 with exponential backoff. |
| $50 budget runs out | At $0.004/investigation, would need 12,500 runs. Not a realistic risk for testing. |
