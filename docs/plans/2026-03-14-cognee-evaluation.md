# Cognee Evaluation: GraphRAG Knowledge Engine for Agent Memory

**Date:** 2026-03-14
**Status:** Evaluated — deferred to v3
**Repo:** https://github.com/topoteretes/cognee
**Stars:** 13.5k | **Language:** Python 3.10-3.13

## What Is It?

Open-source Python library that acts as a **knowledge engine and persistent memory system for AI agents**. Uses GraphRAG (hybrid graph + vector search) instead of pure vector similarity. Not a Claude Code skill — it's a standalone `pip install cognee` library with optional MCP server wrapper (`cognee-mcp`).

## Core Pipeline

| Stage | What Happens | Search Relevance Analogy |
|-------|-------------|--------------------------|
| **Add** | Ingest 38+ formats (PDF, CSV, code, URLs, S3) with dedup | Data ingestion pipeline |
| **Cognify** | LLM extracts entities/relationships → graph + vector embeddings | Feature engineering + index building |
| **Memify** | Feedback loop: prune stale nodes, reweight edges by usage | Online learning / exploration-exploitation |
| **Search** | 14 retrieval modes (vector, graph traversal, chain-of-thought hybrid) | Ranking pipeline with multiple signals |

## Architecture

| Layer | Default | Production |
|-------|---------|-----------|
| Graph Store | Kuzu | Neo4j, FalkorDB |
| Vector Store | LanceDB | Qdrant, Pinecone |
| Relational Store | SQLite | PostgreSQL |

Additional stack: FastAPI, LiteLLM, RDFLib, Alembic migrations, OpenTelemetry, Sentry/Langfuse observability.

## Why It's Interesting For Us

1. **GraphRAG = ranking problem** — which entities/edges are most relevant to a query? Maps directly to search relevance expertise.
2. **Memify = feedback-driven refinement** — like click-through rate signals strengthening ranking features. Edges traversed successfully get stronger, stale nodes get pruned.
3. **14 retrieval modes** — rich design space for ranking strategy experiments.
4. **Multi-agent support** — persistent memory across agents with multi-tenant isolation.
5. **Ontology grounding** — formal domain schemas to reduce hallucinations (relevant for domain knowledge agent).
6. **cognee-mcp** — MCP server wrapper exists, could integrate with Claude Code once a running instance is set up.

## Why Not Now

1. **Wrong layer.** We're building Layer 2 (orchestrator, Phase 2.2). Cognee is a Layer 1 replacement — it changes the foundation, doesn't extend it.
2. **Operational complexity.** Database migrations (Alembic), async Python patterns, graph database management. Beyond current comfort level.
3. **LLM cost.** Every `cognify()` call hits the LLM API for entity extraction. No built-in cost/benefit metrics.
4. **No built-in eval.** No NDCG, MRR, precision/recall out of the box. Would need custom evaluation framework.
5. **Scope creep risk.** Adding a heavyweight dependency mid-Phase 2 derails the current roadmap.

## When to Revisit

- **Trigger:** Phase 2 complete, orchestrator stable, looking for smarter retrieval backend for Layer 3 specialist agents.
- **Experiment scope:** `pip install cognee`, try on a small dataset (e.g., Maven course notes), benchmark GraphRAG retrieval quality vs baseline vector search.
- **Success criteria:** Measurable improvement in retrieval relevance (NDCG, MRR) that justifies the operational overhead.

## Quick Start (When Ready)

```python
import cognee

await cognee.add("path/to/documents")
await cognee.cognify()  # Build knowledge graph + vector embeddings
results = await cognee.search("query", top_k=10)
```

## Key Concepts to Explore Later

- **Memify feedback loop** — reinforcement learning on retrieval graph, maps to CTR signals in ranking
- **Ontology support** — formal domain schemas for search relevance domain (query intent types, ranking signal categories)
- **cognee-mcp** — MCP server integration for Claude Code (requires running cognee instance first)
- **14 retrieval modes** — evaluate which modes produce best results for search diagnostic queries

## References

- [Cognee: GraphRAG for Reliable LLM Results](https://www.cognee.ai/blog/deep-dives/cognee-graphrag-supercharging-search-with-knowledge-graphs-and-vector-magic)
- [From RAG to Graphs: How Cognee Builds AI Memory](https://memgraph.com/blog/from-rag-to-graphs-cognee-ai-memory)
- [Cognee - AI Memory Explained: 5-Scene Breakdown](https://www.cognee.ai/blog/fundamentals/ai-memory-in-five-scenes)
