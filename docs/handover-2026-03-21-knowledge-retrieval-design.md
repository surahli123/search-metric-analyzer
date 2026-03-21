# Handover: SMA — Wave 6 Knowledge Retrieval Layer Design Complete

**Project:** Search Metric Analyzer
**Path:** /Users/surahli/Documents/projects/Search_Metric_Analyzer/
**Branch:** `main` (design docs not yet committed — on `feature/phoenix-integration`, need to switch to a Wave 6 branch)

## Last Session (2026-03-21)

Deep design session on knowledge retrieval layer. Discussed in-house inefficiencies (token waste, UNDERSTAND stage failures, Confluence search quality problems). Studied OpenAI (6-layer pyramid + Codex Enrichment + RAG), Vercel (ToolLoopAgent with on-demand catalog tools), and a16z (context layer architecture). Conducted IC9 search architecture review that reordered priorities. Produced spec + implementation plan, both reviewed and approved.

## Current State

- **Spec approved:** `docs/plans/2026-03-20-knowledge-retrieval-layer-design.md`
  - 56-chunk boundary design across 5 knowledge YAMLs
  - Hybrid TF-IDF + API embeddings retrieval with ~330-token kernel
  - 25-case retrieval evaluation test set
  - Query expansion in question_parser for symptomatic→domain mapping
  - Manifest.yaml becomes permission boundaries (default DENY, kernel exempt)

- **Implementation plan ready:** `docs/plans/2026-03-20-knowledge-retrieval-layer-plan.md`
  - 8 tasks with TDD steps, reviewed and blocker-fixes applied
  - Parallel execution map: Tasks 2+3 independent, Tasks 5+6 independent
  - Sequential chain: 1→3→4→7

- **Not yet committed** — design docs exist on disk but haven't been committed to a branch yet

## Next Steps (Priority Order)

1. **Create branch + commit design docs** — Create `feature/wave6-knowledge-retrieval` from `main`, commit spec + plan
2. **Check memory for priority context** — Memory notes that running 3-5 real investigations (Approach C) and decomposing orchestrator.py are P1 before Wave 6. Decide whether to do those first or start Wave 6.
3. **Execute Wave 6 plan** — 8 tasks, start with Task 1 (schema) + Task 2 (query expansion) in parallel
4. **New dependency:** scikit-learn (TF-IDF), httpx (embedding API, P5 only)

## Key Context

- The IC9 search review found that "something changed overnight" failures are **query understanding problems, not retrieval problems** — fix query expansion (P2) before adding embeddings (P5)
- Direct scoring at 56 chunks, NOT RRF — unnecessary complexity at this scale
- Chunk boundaries matter more than the retrieval algorithm — P0 priority
- OpenAI's key insight: **agents auto-enrich knowledge about code** (Codex Enrichment layer) — SMA's auto-enrichment pipeline (P4) is the equivalent
- Vercel's key insight: **agent is its own knowledge router** — no manifest pre-loading. SMA's hybrid approach pre-loads only a 330-token kernel, everything else on demand.

## Files to Read First
- `docs/plans/2026-03-20-knowledge-retrieval-layer-design.md` — Full spec (read Section 1 for chunk schema, Section 7 for integration)
- `docs/plans/2026-03-20-knowledge-retrieval-layer-plan.md` — Implementation plan (8 tasks)
- `harness/question_parser.py` — Existing parser to extend (Task 2)
- `harness/orchestrator.py` — Orchestrator to integrate retriever into (Task 7)
- `data/knowledge/metric_definitions.yaml` — Largest knowledge source (21 chunks)
