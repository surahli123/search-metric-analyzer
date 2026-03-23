# Handover: OpenAI Factory Implemented + First Real Investigations Complete

## Project
**Search Metric Analyzer** — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`main` — PR #27 merged. Create a new feature branch for next work.

## Last Session Summary
Implemented `make_openai_llm()` factory (TDD, 21 tests), added Phoenix OpenAI auto-instrumentation
with broadened exception handling, built an investigation runner script with lightweight oracle,
and ran 6 real investigations (3 scenarios × 2 models) — all 6 PASS.

## Current State
- **OpenAI factory:** Merged to main, production-ready. Works with any OpenAI-compatible API.
- **Tests:** 1,324 total (21 new), all passing
- **Investigation results:** 6/6 PASS (DeepSeek V3.2 + Qwen3 235B)
  - ranking_regression → P1 (correct)
  - ai_adoption_positive → P2 (correct — not flagged as regression)
  - normal_variance → normal (correct — no action)
- **Phoenix:** Both Anthropic + OpenAI auto-instrumentation, graceful degradation on errors
- **Novita API key:** Set in `~/.zshrc` as `NOVITA_API_KEY` (verified working)
- **Virtual env:** `.venv/` with anthropic, pyyaml, pytest, openai, fastapi

## What Works
- Full 5-stage pipeline (QUESTION_PARSE → UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE)
- Both `make_anthropic_llm()` and `make_openai_llm()` — same callable signature, drop-in swap
- Investigation runner (`scripts/run_investigations.py`) with oracle validation
- 5 synthetic scenarios in `data/investigations/` ready for testing
- Seam validation fires correctly (DISPATCH soft gate caught narrative-data mismatch)

## Next Steps (in priority order)

### 1. Run remaining investigation scenarios
2 scenarios not yet tested: `connector_failure` and `mix_shift`. Run them with:
```bash
.venv/bin/python scripts/run_investigations.py --scenarios connector_failure mix_shift --models deepseek qwen
```

### 2. Test remaining models
GPT-OSS 120B ($0.05/$0.25) and Kimi K2 ($0.57/$2.30) not yet tested in the matrix.
```bash
.venv/bin/python scripts/run_investigations.py --models gpt_oss kimi
```

### 3. Web App Phase 2 — SSE streaming for Trace tab + real backend integration
- Currently the web app at https://search-metric-analyzer.vercel.app uses mock data
- Next: wire the real orchestrator to the FastAPI backend with SSE streaming
- See: `docs/plans/2026-03-14-web-app-architecture-design.md`

### 4. Wave 6 — Knowledge Retrieval Layer
- Replace manifest-based pre-load with hybrid TF-IDF + API embeddings
- See memory file: `project_knowledge_retrieval_redesign.md`

### 5. Wire Phoenix into eval stress test pipeline (deferred TODO in TODOS.md)
- Call `register_phoenix()` at start of `eval/run_stress_test.py`
- ~10 lines, low effort

## Key Files to Read First
- `harness/llm.py` — Both LLM factories (Anthropic + OpenAI)
- `scripts/run_investigations.py` — Investigation runner with oracle
- `data/investigation_results.json` — Latest results
- `docs/plans/2026-03-22-openai-compatible-llm-factory-design.md` — Approved spec

## Working Models (verified 2026-03-22)
| Model | Model ID | $/Mt (in/out) | Pipeline Status |
|-------|----------|---------------|-----------------|
| DeepSeek V3.2 | `deepseek/deepseek-v3.2` | $0.27/$0.40 | 6/6 PASS |
| Qwen3 235B | `qwen/qwen3-235b-a22b-instruct-2507` | $0.09/$0.58 | 6/6 PASS |
| GPT-OSS 120B | `openai/gpt-oss-120b` | $0.05/$0.25 | Untested in pipeline |
| Kimi K2 | `moonshotai/kimi-k2-instruct` | $0.57/$2.30 | Untested in pipeline |

## Gotchas
- **Phoenix trace export errors** to localhost:6006 are expected noise when Phoenix server isn't running
- **`orch.run()` returns a dict**, not a named object — access fields via `result['synthesis']`, `result['mode']`, etc.
- **Model IDs need provider prefix:** `deepseek/deepseek-v3.2` not `deepseek-v3.2`
- **Failed models (don't use):** GLM-4.7-Flash, GLM 4.7/5, MiniMax M2.7/M2.5, Kimi K2.5, GPT-OSS 20B
