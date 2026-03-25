# Handover — Domain Plugin Extraction (In Progress)

## Project
Search Metric Analyzer — `/Users/surahli/Documents/projects/Search_Metric_Analyzer`

## Branch
`feature/wave-7a-domain-extraction` — 3 commits ahead of main, 1 uncommitted file (test_stages.py with TDD tests for next step)

## Last Session Summary
Extracted the search_metrics domain into a plugin architecture (`domains/search_metrics/`). Moved agents, knowledge YAMLs, and prompts out of the harness into a domain module with a `DomainInterface` protocol. Seam validator rules that are domain-specific were moved to `domains/search_metrics/rules.py`. HYPOTHESIZE stage is wired to accept a `domain` parameter. DISPATCH and SYNTHESIZE still need wiring.

## Current State
- **Tests**: 1,253 collected, 1,155 passed, 1 failed (TDD — test written ahead of impl), 17 skipped
- **Failing test**: `TestDispatchDomainWiring::test_stage_dispatch_accepts_domain` — DISPATCH doesn't accept `domain` param yet
- **3 committed changes**:
  1. `3e16856` — Extract search_metrics domain (move agents/, knowledge/, prompts.py → domains/search_metrics/)
  2. `ec9d9bb` — Add DomainInterface protocol + search_metrics domain rules
  3. `1ba45cc` — Wire domain parameter into stage_hypothesize
- **1 uncommitted change**: `tests/test_stages.py` — TDD tests for DISPATCH + SYNTHESIZE domain wiring (written, not yet implemented)

## What's Been Done (Domain Extraction)
- `contracts/domain_interface.py` — DomainInterface Protocol (get_prompts, get_rules, get_knowledge_paths, get_agents_dir, etc.)
- `domains/__init__.py` — Domain registry with `load_domain()` and `get_domain()`
- `domains/search_metrics/__init__.py` — SearchMetricsDomain implementing DomainInterface
- `domains/search_metrics/rules.py` — 10 domain-specific seam validator rules extracted from seam_validator.py
- `domains/search_metrics/agents/` — All 10 agent .md files + registry.yaml (moved from agents/)
- `domains/search_metrics/knowledge/` — All 6 YAML files (moved from data/knowledge/)
- `domains/search_metrics/prompts.py` — Prompt builders (moved from harness/prompts.py)
- Seam validator now loads rules from domain at runtime instead of hardcoding them

## Next Steps (in order)
1. **Wire `domain` param into DISPATCH stage** — `harness/stages/dispatch.py` needs `domain` parameter for `stage_dispatch()` and `stage_dispatch_parallel()`. Use `domain.get_prompts()` for dispatch prompts. Tests already written (the failing ones).
2. **Wire `domain` param into SYNTHESIZE stage** — Same pattern as HYPOTHESIZE/DISPATCH. Tests already written in the uncommitted test_stages.py.
3. **Wire `domain` through orchestrator** — `harness/orchestrator.py` `_run_pipeline()` needs to pass `domain` to all stage functions. The orchestrator should accept `domain` in its constructor or `run()` method.
4. **Update `run_v2()` → auto-detect domain** — When `domain` is not passed explicitly, detect from question context or default to `search_metrics`.
5. **Run full test suite** — All 1,253 tests should pass after wiring.
6. **PR to main** — Domain extraction complete.

## Architecture After This Work

```
harness/            — Domain-agnostic orchestration (stages, executor, registry)
domains/
  __init__.py       — Domain registry (load_domain, get_domain)
  search_metrics/   — Search metrics domain plugin
    __init__.py     — SearchMetricsDomain(DomainInterface)
    agents/         — Agent .md files + registry.yaml
    knowledge/      — YAML knowledge files
    prompts.py      — Prompt builders
    rules.py        — Domain-specific seam validator rules
contracts/
  domain_interface.py — DomainInterface Protocol
  seam_validator.py   — Now loads rules from domain at runtime
```

This makes the harness reusable for KDD competition — create `domains/kdd_data_agent/` implementing the same DomainInterface.

## Key Context
- The DomainInterface is a Python Protocol (structural subtyping) — domains don't need to inherit from a base class
- Domain rules are loaded via `domain.get_rules(stage)` in seam_validator, replacing hardcoded STAGE_RULES
- Knowledge file paths now come from `domain.get_knowledge_paths()` instead of hardcoded `data/knowledge/`
- Agent registry path comes from `domain.get_agents_dir()` instead of hardcoded `agents/`
- PR #27 (OpenAI LLM factory) is already merged to main

## Files to Read First
- `contracts/domain_interface.py` — The Protocol definition
- `domains/search_metrics/__init__.py` — How a domain implements the interface
- `harness/stages/hypothesize.py` — Example of a stage wired with domain param
- `tests/test_stages.py` (bottom) — TDD tests for the next steps
- `tests/test_domain_interface.py` — Domain protocol compliance tests
