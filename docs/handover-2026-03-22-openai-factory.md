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

## Novita AI Models (for reference)
| Model | Input/Mt | Output/Mt | Model ID |
|-------|----------|-----------|----------|
| DeepSeek V3.2 | $0.27 | $0.40 | `deepseek/deepseek-v3.2` |
| GLM-4.7-Flash | $0.07 | $0.40 | `glm-4.7-flash` |
| MiniMax M2.7 | $0.30 | $1.20 | `minimax/minimax-m2.7` |
| Kimi K2.5 | $0.60 | $3.00 | `moonshotai/kimi-k2.5` |
| GPT-OSS 120B | $0.05 | $0.25 | `openai-gpt-oss-120b` |
