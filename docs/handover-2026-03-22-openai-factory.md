# Handover: OpenAI-Compatible LLM Factory — Ready to Implement

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — create a feature branch before implementing.

## Last Session Summary
Implemented Phoenix/OTel integration (PR #26, merged). Then designed a generic OpenAI-compatible LLM factory so the pipeline can be tested cheaply using Novita AI ($50 credits). Design spec written, eng-reviewed (2 rounds), all blocking issues resolved.

## Current State
- **Phoenix integration:** Merged to main, 1,294 tests passing
- **OpenAI factory spec:** Approved at `docs/plans/2026-03-22-openai-compatible-llm-factory-design.md`
- **Novita API key:** Set in `~/.zshrc` as `NOVITA_API_KEY` (verified: `sk_jFdgx...MZos`)
- **No code written yet** for the factory — spec only

## Next Steps (in order)
1. **Create feature branch** (e.g., `feature/openai-llm-factory`)
2. **Implement `make_openai_llm()`** in `harness/llm.py` (~50 lines) — TDD, 8 tests
3. **Fix stale `LLMCallable` alias** in `harness/llm.py:45` (delete the 1-arg version)
4. **Add OpenAI instrumentor** to `harness/phoenix_tracer.py` register_phoenix() (~5 lines)
5. **Install deps:** `pip install openai openinference-instrumentation-openai` in `.venv/`
6. **Run a real investigation** against Novita AI to validate the full pipeline end-to-end
7. **Create PR** and merge

## Key Decisions (locked)
- **API format:** OpenAI-compatible via `openai` Python SDK with `base_url` override
- **API key:** Explicit param → `NOVITA_API_KEY` → `OPENAI_API_KEY` env fallback
- **Error handling:** Extend existing `_classify_api_error()` (verify it handles both SDKs first)
- **Phoenix:** Add `OpenAIInstrumentor().instrument()` for LLM span visibility
- **Recommended test model:** `deepseek/deepseek-v3.2` ($0.27/$0.40 per Mt — ~$0.004/investigation)

## Key Files to Read First
- `docs/plans/2026-03-22-openai-compatible-llm-factory-design.md` — **THE SPEC** (read this first)
- `harness/llm.py` — Existing `make_anthropic_llm()` factory (follow this pattern)
- `harness/phoenix_tracer.py` — Add OpenAI instrumentor here
- `requirements-dev.txt` — Add `openai` + `openinference-instrumentation-openai`

## Gotchas
- **Message format differs:** OpenAI puts system message in the `messages` array, NOT as a top-level kwarg like Anthropic
- **Response extraction differs:** OpenAI uses `response.choices[0].message.content`, not `response.content[0].text`
- **Stale type alias:** `harness/llm.py:45` has `LLMCallable = Callable[[str], str]` (wrong — should be 3-arg). Delete it.
- **Virtual env:** Use `.venv/bin/python` for all commands (system Python doesn't have deps)
- **`max_tokens` vs `max_completion_tokens`:** Some providers use the newer name. Test against Novita endpoint.

## Novita AI Model Test Results (tested 2026-03-22)

Model IDs require provider prefix (e.g., `deepseek/deepseek-v3.2`, not just `deepseek-v3.2`).

**Working models (valid JSON from search metric prompt):**

| Model | Model ID | $/Mt (in/out) | Latency | Notes |
|-------|----------|---------------|---------|-------|
| **DeepSeek V3.2** | `deepseek/deepseek-v3.2` | $0.27/$0.40 | ~2s | Best overall, start here |
| **GPT-OSS 120B** | `openai/gpt-oss-120b` | $0.05/$0.25 | 5.9s | Cheapest valid option |
| **Qwen3 235B Instruct** | `qwen/qwen3-235b-a22b-instruct-2507` | $0.09/$0.58 | 6.4s | Clean structured JSON |
| **Kimi K2 Instruct** | `moonshotai/kimi-k2-instruct` | $0.57/$2.30 | 4.9s | Good domain understanding |
| **Gemma 3 27B** | `google/gemma-3-27b-it` | budget | 9.0s | Works, wraps JSON in fences |
| Qwen 3.5-27B | `qwen/qwen3.5-27b` | $0.30/$2.40 | 32.6s | Valid but too slow |

**Failed models (empty or invalid JSON — not usable without prompt rework):**

| Model | Model ID | Issue |
|-------|----------|-------|
| GLM-4.7-Flash | `zai-org/glm-4.7-flash` | Empty response |
| GLM 4.7 / GLM 5 | `zai-org/glm-4.7`, `zai-org/glm-5` | Empty responses |
| MiniMax M2.7 / M2.5 | `minimax/minimax-m2.7`, `minimax/minimax-m2.5` | Empty/truncated |
| Kimi K2.5 | `moonshotai/kimi-k2.5` | Empty response |
| GPT-OSS 20B | `openai/gpt-oss-20b` | Too small, invalid JSON |
