# Knowledge Retrieval Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manifest-based pre-load knowledge architecture with hybrid TF-IDF + API embeddings on-demand retrieval, reducing token waste by 73-91% while improving retrieval precision.

**Architecture:** 56 knowledge chunks across 5 YAMLs, retrieved via hybrid TF-IDF + embedding search with a ~330-token always-loaded kernel. Manifest.yaml becomes permission boundaries. Query expansion in question_parser handles symptomatic queries before retrieval runs.

**Tech Stack:** Python 3.10+, scikit-learn (TF-IDF), httpx (embedding API), PyYAML (existing)

**Spec:** `docs/plans/2026-03-20-knowledge-retrieval-layer-design.md`

**Branch:** Create `feature/wave6-knowledge-retrieval` from `main`

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| **Create** | `harness/knowledge_retriever.py` | KnowledgeChunk, ScoredChunk, TFIDFRetriever, HybridRetriever, KnowledgeRetriever ABC |
| **Create** | `harness/enrich_knowledge.py` | Offline enrichment CLI: chunk YAMLs, fit TF-IDF, generate embeddings |
| **Create** | `eval/retrieval_eval.yaml` | 25 ground truth test cases for retrieval quality |
| **Create** | `eval/run_retrieval_eval.py` | Retrieval evaluation runner + scorecard |
| **Create** | `tests/test_knowledge_retriever.py` | Unit tests for retriever |
| **Create** | `tests/test_enrich_knowledge.py` | Unit tests for enrichment pipeline |
| **Create** | `tests/test_query_expansion.py` | Unit tests for query expansion |
| **Create** | `tests/test_retrieval_eval.py` | Tests for the eval runner itself |
| **Modify** | `harness/question_parser.py` | Add QUERY_EXPANSION_MAP + expand_query() |
| **Modify** | `harness/manifest.yaml` | Loading instructions → permission boundaries |
| **Modify** | `harness/orchestrator.py` | Add retriever init + kernel loading + per-stage retrieval |
| **Modify** | `harness/prompts.py` | Inject kernel + retrieved chunks into system prompts |
| **Modify** | `agents/*.md` (7 files) | CONTRACT blocks: knowledge_required → knowledge_access |
| **Modify** | `requirements.txt` | Add scikit-learn, httpx |
| **Modify** | `.gitignore` | Add generated artifacts (_tfidf.pkl, _embeddings.npy, _chunks/) |
| **Generated** | `data/knowledge/_index.json` | Chunk metadata index |
| **Generated** | `data/knowledge/_tfidf.pkl` | Fitted TF-IDF vectorizer |
| **Generated** | `data/knowledge/_chunks/` | Individual chunk text files |

---

## Task 1: KnowledgeChunk Schema + Retriever Interface

**Files:**
- Create: `harness/knowledge_retriever.py`
- Create: `tests/test_knowledge_retriever.py`

- [ ] **Step 1: Write tests for KnowledgeChunk and ScoredChunk dataclasses**

```python
# tests/test_knowledge_retriever.py
"""Tests for the knowledge retrieval layer."""
import pytest
from harness.knowledge_retriever import KnowledgeChunk, ScoredChunk


class TestKnowledgeChunk:
    def test_create_chunk(self):
        chunk = KnowledgeChunk(
            chunk_id="co_movement/ai_adoption_positive",
            source_file="metric_definitions.yaml",
            source_section="co_movement_diagnostic_table",
            context_header="Co-movement diagnostic table.",
            content="CQ down, SQS stable, AI up = POSITIVE signal.",
            token_estimate=120,
            keywords=["click_quality", "ai_trigger", "ai_adoption"],
            authority="definitional",
            stage_tags=["understand", "hypothesize"],
            staleness_tier="stable",
            cross_refs=["kernel/inverse_co_movement"],
        )
        assert chunk.chunk_id == "co_movement/ai_adoption_positive"
        assert chunk.authority == "definitional"

    def test_chunk_domain_extraction(self):
        """Domain = first segment of chunk_id before '/'."""
        chunk = KnowledgeChunk(
            chunk_id="pipeline/query_understanding",
            source_file="search_pipeline_knowledge.yaml",
            source_section="pipeline_components",
            context_header="",
            content="",
            token_estimate=280,
            keywords=[],
            authority="empirical",
            stage_tags=["dispatch"],
            staleness_tier="semi_stable",
            cross_refs=[],
        )
        assert chunk.domain == "pipeline"

    def test_kernel_chunk_domain(self):
        chunk = KnowledgeChunk(
            chunk_id="kernel/metric_formulas",
            source_file="metric_definitions.yaml",
            source_section="metrics",
            context_header="",
            content="CQ = sum(long_clicks * log2_discount(rank)) / impressions",
            token_estimate=150,
            keywords=["click_quality", "formula"],
            authority="definitional",
            stage_tags=[],
            staleness_tier="stable",
            cross_refs=[],
        )
        assert chunk.domain == "kernel"

    def test_scored_chunk(self):
        chunk = KnowledgeChunk(
            chunk_id="test/chunk", source_file="", source_section="",
            context_header="", content="content", token_estimate=50,
            keywords=[], authority="empirical", stage_tags=[],
            staleness_tier="stable", cross_refs=[],
        )
        scored = ScoredChunk(chunk=chunk, score=0.85, retrieval_path="tfidf")
        assert scored.score == 0.85
        assert scored.retrieval_path == "tfidf"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_knowledge_retriever.py -v`
Expected: FAIL (ImportError — module doesn't exist yet)

- [ ] **Step 3: Implement KnowledgeChunk and ScoredChunk**

```python
# harness/knowledge_retriever.py
"""Knowledge retrieval layer — on-demand chunk retrieval replacing manifest pre-load.

WHY THIS EXISTS:
The manifest-based pre-load architecture wastes tokens (loading 55K when 8K needed)
and causes visible investigation failures when routing under-scopes the agent.
This module provides on-demand retrieval: the agent searches for what it needs,
the retriever returns precisely relevant chunks.

DESIGN: See docs/plans/2026-03-20-knowledge-retrieval-layer-design.md

ARCHITECTURE:
  Kernel (~330 tokens, always loaded) + on-demand retrieval (TF-IDF + embeddings).
  Manifest.yaml = permission boundaries, not loading instructions.
  CONTRACT blocks = what agents CAN access, not what to pre-load.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class KnowledgeChunk:
    """A single retrievable piece of knowledge.

    Each chunk represents one diagnostic concept with enough context
    to be useful in isolation (via context_header).
    """
    chunk_id: str           # Unique ID: {domain}/{concept}
    source_file: str        # Origin YAML filename
    source_section: str     # YAML section key
    context_header: str     # Prepended when retrieved — explains what this chunk is part of
    content: str            # Actual chunk text injected into agent context
    token_estimate: int     # Pre-computed token count for budget enforcement
    keywords: List[str]     # Terms for TF-IDF boosting (metric names, components, patterns)
    authority: str          # "definitional" > "empirical" > "contextual"
    stage_tags: List[str]   # Pipeline stages where this chunk is relevant
    staleness_tier: str     # "stable" / "semi_stable" / "volatile"
    cross_refs: List[str]   # Related chunk IDs

    @property
    def domain(self) -> str:
        """Domain = first segment of chunk_id (before '/').
        Used for CONTRACT permission filtering."""
        return self.chunk_id.split("/")[0]


@dataclass
class ScoredChunk:
    """A chunk with its retrieval score and path taken."""
    chunk: KnowledgeChunk
    score: float
    retrieval_path: str     # "tfidf" | "embedding" | "hybrid"


class KnowledgeRetriever(ABC):
    """Abstract retriever interface — swap backends without changing callers.

    Implementations: TFIDFRetriever (P3), HybridRetriever (P5).
    """

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int = 5,
        stage: Optional[str] = None,
        extra_keywords: Optional[List[str]] = None,
        allowed_domains: Optional[List[str]] = None,
    ) -> List[ScoredChunk]:
        """Search knowledge chunks, returning top-K scored results."""
        ...

    @abstractmethod
    def load_kernel(self) -> str:
        """Return concatenated kernel chunk content (~330 tokens)."""
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_knowledge_retriever.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add harness/knowledge_retriever.py tests/test_knowledge_retriever.py
git commit -m "feat(wave6): add KnowledgeChunk schema and KnowledgeRetriever interface"
```

---

## Task 2: Query Expansion in question_parser.py

**Files:**
- Modify: `harness/question_parser.py`
- Create: `tests/test_query_expansion.py`

- [ ] **Step 1: Write tests for query expansion**

```python
# tests/test_query_expansion.py
"""Tests for query expansion in question parser."""
import pytest
from harness.question_parser import expand_query, QUERY_EXPANSION_MAP


class TestQueryExpansion:
    def test_exact_symptom_match(self):
        result = expand_query("something changed overnight")
        assert "step_change" in result
        assert "instrumentation" in result
        assert "logging_anomaly" in result

    def test_case_insensitive(self):
        result = expand_query("Something Changed Overnight")
        assert "step_change" in result

    def test_multiple_symptom_match(self):
        """Multiple expansion rules can fire — results accumulate."""
        result = expand_query("something changed overnight and looks weird")
        assert "step_change" in result       # from "something changed"
        assert "regression" in result         # from "looks weird"

    def test_no_match_returns_empty(self):
        result = expand_query("Click Quality dropped 3%")
        assert result == []

    def test_ai_adoption_symptom(self):
        result = expand_query("users are not clicking but seem happy")
        assert "ai_adoption" in result
        assert "inverse_co_movement" in result

    def test_cost_tradeoff_symptom(self):
        result = expand_query("we saved money but quality got worse")
        assert "cost_optimization" in result
        assert "model_tiering" in result

    def test_expansion_map_has_expected_entries(self):
        assert len(QUERY_EXPANSION_MAP) >= 10

    def test_parse_question_includes_expanded_keywords(self):
        """parse_question() output dict includes expanded_keywords field."""
        from harness.question_parser import parse_question
        brief = parse_question("something changed overnight")
        assert "expanded_keywords" in brief
        assert "step_change" in brief["expanded_keywords"]

    def test_parse_question_empty_expansion(self):
        from harness.question_parser import parse_question
        brief = parse_question("Click Quality dropped 3% for enterprise")
        assert "expanded_keywords" in brief
        assert brief["expanded_keywords"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_query_expansion.py -v`
Expected: FAIL (expand_query not defined, expanded_keywords not in brief)

- [ ] **Step 3: Implement expand_query() and QUERY_EXPANSION_MAP**

Add to `harness/question_parser.py` after the existing `METRIC_ALIASES` block (~line 65):

```python
# =============================================================================
# Query expansion — maps symptomatic language to domain keywords
# =============================================================================

# WHY: Users describe symptoms ("something changed overnight"), not diagnoses
# ("step_change pattern"). This bridges the vocabulary gap so TF-IDF retrieval
# can find the right knowledge chunks without needing semantic embeddings.
# ANALOGY: Like query expansion/synonym mapping in the L0 QU layer.
QUERY_EXPANSION_MAP = {
    "changed overnight":     ["step_change", "instrumentation", "logging_anomaly", "overnight"],
    "something changed":     ["step_change", "deployment", "experiment_ramp"],
    "looks weird":           ["regression", "anomaly", "unexpected_movement"],
    "after rollout":         ["ai_batch_rollout", "experiment_ramp", "feature_effect"],
    "after a model change":  ["model_tiering", "algorithm_model", "retraining"],
    "don't add up":          ["mix_shift", "simpsons_paradox", "segment_composition"],
    "real or noise":         ["normal_fluctuation", "measurement_pitfall", "p2_threshold"],
    "saved money but":       ["cost_optimization", "model_tiering", "quality_tradeoff"],
    "not clicking but":      ["ai_adoption", "inverse_co_movement", "ai_answers_working"],
    "slow and bad":          ["latency", "serving_degradation", "model_fallback"],
}


def expand_query(question: str) -> list:
    """Map symptomatic phrases to domain keywords for retrieval boosting.

    Scans the raw question (case-insensitive) against QUERY_EXPANSION_MAP.
    Multiple rules can fire — all matching expansions accumulate.

    Returns:
        List of domain keywords (may be empty if no symptoms matched).
    """
    expanded = []
    question_lower = question.lower()
    for phrase, keywords in QUERY_EXPANSION_MAP.items():
        if phrase in question_lower:
            expanded.extend(keywords)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for kw in expanded:
        if kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result
```

Then modify `parse_question()` to add the new field (after existing `investigation_plan` line, ~line 414):

```python
    # --- Step 5.5: Expand query for retrieval ---
    expanded_keywords = expand_query(question)
```

And add it to the brief dict:

```python
    brief = {
        "raw_question": question,
        "question_type": question_type,
        "metric_hints": metric_hints,
        "time_range_hints": time_range_hints,
        "complexity_signals": complexity_signals,
        "investigation_plan": investigation_plan,
        "expanded_keywords": expanded_keywords,    # NEW
    }
```

- [ ] **Step 4: Run new tests + existing tests to verify all pass**

Run: `pytest tests/test_query_expansion.py tests/test_question_parser.py -v`
Expected: ALL PASS (new tests + no regression on existing 51 tests)

- [ ] **Step 5: Commit**

```bash
git add harness/question_parser.py tests/test_query_expansion.py
git commit -m "feat(wave6): add query expansion for symptomatic-to-domain keyword mapping"
```

---

## Task 3: Deterministic Chunker (Enrichment Pipeline Phase 1)

**Files:**
- Create: `harness/enrich_knowledge.py`
- Create: `tests/test_enrich_knowledge.py`

This task builds the chunker only — TF-IDF fitting comes in Task 5 after the retriever exists.

- [ ] **Step 1: Write tests for chunking logic**

```python
# tests/test_enrich_knowledge.py
"""Tests for the knowledge enrichment pipeline."""
import json
import os
import pytest
from harness.enrich_knowledge import (
    chunk_knowledge_yamls,
    CHUNK_BOUNDARIES,
    load_yaml_file,
)


class TestChunking:
    def test_chunk_boundaries_defined_for_all_files(self):
        """Every knowledge YAML has chunk boundary definitions."""
        expected_files = [
            "metric_definitions.yaml",
            "historical_patterns.yaml",
            "search_pipeline_knowledge.yaml",
            "architecture_tradeoffs.yaml",
            "evaluation_methods.yaml",
        ]
        for f in expected_files:
            assert f in CHUNK_BOUNDARIES, f"Missing chunk boundaries for {f}"

    def test_total_chunk_count(self):
        """Should produce 56 fixed chunks (per spec)."""
        chunks = chunk_knowledge_yamls("data/knowledge/")
        # Filter out dynamic corrections
        fixed = [c for c in chunks if not c["chunk_id"].startswith("correction/")]
        assert len(fixed) == 56, f"Expected 56 fixed chunks, got {len(fixed)}"

    def test_kernel_chunks_exist(self):
        chunks = chunk_knowledge_yamls("data/knowledge/")
        kernel_ids = [c["chunk_id"] for c in chunks if c["chunk_id"].startswith("kernel/")]
        assert "kernel/metric_formulas" in kernel_ids
        assert "kernel/alert_thresholds" in kernel_ids
        assert "kernel/inverse_co_movement" in kernel_ids

    def test_co_movement_individual_patterns(self):
        """Each co-movement pattern gets its own chunk."""
        chunks = chunk_knowledge_yamls("data/knowledge/")
        co_movement_ids = [c["chunk_id"] for c in chunks if c["chunk_id"].startswith("co_movement/")]
        assert len(co_movement_ids) == 9
        assert "co_movement/ai_adoption_positive" in co_movement_ids
        assert "co_movement/ranking_regression" in co_movement_ids

    def test_context_headers_present(self):
        """Co-movement chunks share a context header."""
        chunks = chunk_knowledge_yamls("data/knowledge/")
        co_movement = [c for c in chunks if c["chunk_id"].startswith("co_movement/")]
        for chunk in co_movement:
            assert chunk["context_header"], f"{chunk['chunk_id']} missing context_header"
            assert "diagnostic table" in chunk["context_header"].lower()

    def test_pipeline_components_include_failure_modes(self):
        """Pipeline chunks keep function + failure modes together."""
        chunks = chunk_knowledge_yamls("data/knowledge/")
        qu = next(c for c in chunks if c["chunk_id"] == "pipeline/query_understanding")
        assert "failure" in qu["content"].lower() or "misclassification" in qu["content"].lower()

    def test_chunk_has_required_fields(self):
        """Every chunk has all required schema fields."""
        required = ["chunk_id", "source_file", "source_section", "context_header",
                     "content", "token_estimate", "keywords", "authority",
                     "stage_tags", "staleness_tier", "cross_refs"]
        chunks = chunk_knowledge_yamls("data/knowledge/")
        for chunk in chunks:
            for field in required:
                assert field in chunk, f"{chunk['chunk_id']} missing field '{field}'"

    def test_click_quality_has_separate_baselines(self):
        """CQ gets a separate baselines chunk."""
        chunks = chunk_knowledge_yamls("data/knowledge/")
        ids = [c["chunk_id"] for c in chunks]
        assert "metric/click_quality" in ids
        assert "metric/click_quality_baselines" in ids

    def test_write_index_json(self):
        """Enrichment pipeline can write _index.json."""
        chunks = chunk_knowledge_yamls("data/knowledge/")
        # Verify JSON-serializable
        json_str = json.dumps(chunks, indent=2)
        parsed = json.loads(json_str)
        assert len(parsed) == len(chunks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_enrich_knowledge.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement chunker**

Create `harness/enrich_knowledge.py` with:
- `CHUNK_BOUNDARIES` dict defining extraction strategy per YAML section
- `load_yaml_file()` helper
- `chunk_knowledge_yamls(knowledge_dir)` that reads all 5 YAMLs and returns list of chunk dicts
- `write_index(chunks, output_dir)` that writes `_index.json`
- CLI entrypoint: `python harness/enrich_knowledge.py [--knowledge-dir data/knowledge/]`

Key implementation details:
- Kernel extraction: pull specific fields (formulas, thresholds, inverse rule) from metric_definitions.yaml
- Per-metric chunking: iterate `metrics:` dict, create one chunk per metric
- Co-movement: iterate `co_movement_diagnostic_table:` list, one chunk per pattern
- Pipeline: iterate `pipeline_components:` dict, keep function + approaches + failure_modes together
- Keywords: extract from YAML keys, metric names, pattern names (no LLM needed)
- Authority: `definitional` for formulas/thresholds, `empirical` for patterns/benchmarks, `contextual` for corrections/incidents
- Token estimates: approximate with `len(content.split()) * 1.3`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_enrich_knowledge.py -v`
Expected: ALL PASS

- [ ] **Step 5: Generate and inspect the index**

Run: `python harness/enrich_knowledge.py --knowledge-dir data/knowledge/`
Verify: `data/knowledge/_index.json` exists with 56+ entries
Inspect: `python -c "import json; d=json.load(open('data/knowledge/_index.json')); print(len(d), 'chunks'); print([c['chunk_id'] for c in d[:5]])"`

- [ ] **Step 6: Commit**

```bash
git add harness/enrich_knowledge.py tests/test_enrich_knowledge.py
git commit -m "feat(wave6): add deterministic knowledge chunker with 56-chunk boundary spec"
```

---

## Task 4: TF-IDF Retriever

**Files:**
- Modify: `harness/knowledge_retriever.py` (add TFIDFRetriever)
- Modify: `harness/enrich_knowledge.py` (add TF-IDF fitting)
- Modify: `tests/test_knowledge_retriever.py` (add TFIDFRetriever tests)
- Modify: `requirements.txt` (add scikit-learn)

- [ ] **Step 1: Add scikit-learn dependency**

```bash
echo "scikit-learn>=1.4" >> requirements.txt
pip install scikit-learn
```

- [ ] **Step 2: Write tests for TFIDFRetriever**

Add to `tests/test_knowledge_retriever.py`:

```python
from harness.knowledge_retriever import TFIDFRetriever


class TestTFIDFRetriever:
    @pytest.fixture
    def sample_chunks(self):
        """Create a small set of test chunks."""
        return [
            KnowledgeChunk(
                chunk_id="metric/click_quality", source_file="metric_definitions.yaml",
                source_section="metrics", context_header="Metric definitions.",
                content="Click Quality measures position-discounted long click rate.",
                token_estimate=180, keywords=["click_quality", "formula", "long_click"],
                authority="definitional", stage_tags=["understand"],
                staleness_tier="stable", cross_refs=[],
            ),
            KnowledgeChunk(
                chunk_id="seasonal/connector_outage", source_file="historical_patterns.yaml",
                source_section="seasonal_patterns", context_header="Seasonal patterns.",
                content="Connector outage causes zero result spike and click quality drop.",
                token_estimate=100, keywords=["connector", "outage", "zero_result"],
                authority="empirical", stage_tags=["understand", "hypothesize"],
                staleness_tier="volatile", cross_refs=[],
            ),
            KnowledgeChunk(
                chunk_id="kernel/metric_formulas", source_file="metric_definitions.yaml",
                source_section="metrics", context_header="",
                content="CQ = sum(long_clicks * log2_discount(rank)) / impressions",
                token_estimate=150, keywords=["click_quality", "formula"],
                authority="definitional", stage_tags=[],
                staleness_tier="stable", cross_refs=[],
            ),
        ]

    @pytest.fixture
    def retriever(self, sample_chunks):
        return TFIDFRetriever.from_chunks(sample_chunks)

    def test_exact_keyword_match(self, retriever):
        results = retriever.search("click quality formula")
        assert len(results) > 0
        assert results[0].chunk.chunk_id in ["metric/click_quality", "kernel/metric_formulas"]

    def test_connector_query(self, retriever):
        results = retriever.search("connector outage")
        assert any(r.chunk.chunk_id == "seasonal/connector_outage" for r in results)

    def test_top_k_limit(self, retriever):
        results = retriever.search("click quality", top_k=1)
        assert len(results) == 1

    def test_stage_boost(self, retriever):
        """Stage-tagged chunks get boosted when stage matches."""
        results_with_stage = retriever.search("connector", stage="hypothesize")
        results_without_stage = retriever.search("connector")
        # Connector chunk has hypothesize tag — should score higher with stage
        connector_with = next((r for r in results_with_stage if r.chunk.chunk_id == "seasonal/connector_outage"), None)
        connector_without = next((r for r in results_without_stage if r.chunk.chunk_id == "seasonal/connector_outage"), None)
        if connector_with and connector_without:
            assert connector_with.score >= connector_without.score

    def test_domain_filtering(self, retriever):
        """allowed_domains restricts results to matching domains."""
        results = retriever.search("click quality", allowed_domains=["seasonal"])
        for r in results:
            assert r.chunk.domain in ("seasonal", "kernel"), f"Unexpected domain: {r.chunk.domain}"

    def test_kernel_always_allowed(self, retriever):
        """Kernel chunks pass domain filtering regardless of allowed_domains."""
        # Search for something that matches kernel content, with non-kernel domain filter
        results = retriever.search("CQ formula log2 discount", allowed_domains=["seasonal"])
        kernel_results = [r for r in results if r.chunk.domain == "kernel"]
        assert len(kernel_results) > 0, "Kernel chunks should not be filtered by domain permissions"

    def test_extra_keywords_boost(self, retriever):
        """Extra keywords from query expansion improve retrieval."""
        results_without = retriever.search("something happened")
        results_with = retriever.search("something happened", extra_keywords=["connector", "outage"])
        # With expansion, connector chunk should rank higher
        connector_with = next((r for r in results_with if r.chunk.chunk_id == "seasonal/connector_outage"), None)
        assert connector_with is not None

    def test_load_kernel(self, retriever):
        kernel_text = retriever.load_kernel()
        assert "CQ = sum" in kernel_text

    def test_scored_chunk_has_tfidf_path(self, retriever):
        results = retriever.search("click quality")
        for r in results:
            assert r.retrieval_path == "tfidf"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_knowledge_retriever.py::TestTFIDFRetriever -v`
Expected: FAIL (TFIDFRetriever not defined)

- [ ] **Step 4: Implement TFIDFRetriever**

Add to `harness/knowledge_retriever.py`:

```python
import json
import os
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine


# Authority boost multipliers
AUTHORITY_BOOST = {
    "definitional": 1.1,
    "empirical": 1.0,
    "contextual": 0.9,
}

STAGE_BOOST = 1.3


class TFIDFRetriever(KnowledgeRetriever):
    """TF-IDF based retriever with direct scoring.

    At 56 chunks, scores every chunk directly (no RRF needed).
    Keywords appended to content for vectorization — acts as synthetic terms.
    """

    def __init__(self, chunks, vectorizer, tfidf_matrix):
        self.chunks = chunks
        self.vectorizer = vectorizer
        self.tfidf_matrix = tfidf_matrix

    @classmethod
    def from_chunks(cls, chunks):
        """Build retriever from in-memory chunks (for testing)."""
        vectorizer = TfidfVectorizer(stop_words="english")
        texts = [c.content + " " + " ".join(c.keywords) for c in chunks]
        tfidf_matrix = vectorizer.fit_transform(texts)
        return cls(chunks, vectorizer, tfidf_matrix)

    @classmethod
    def from_index(cls, index_dir):
        """Load from pre-computed index files."""
        with open(os.path.join(index_dir, "_index.json")) as f:
            raw = json.load(f)
        chunks = [KnowledgeChunk(**entry) for entry in raw]
        with open(os.path.join(index_dir, "_tfidf.pkl"), "rb") as f:
            data = pickle.load(f)
        return cls(chunks, data["vectorizer"], data["matrix"])

    def search(self, query, top_k=5, stage=None, extra_keywords=None, allowed_domains=None):
        enriched = query
        if extra_keywords:
            enriched += " " + " ".join(extra_keywords)

        query_vec = self.vectorizer.transform([enriched])
        scores = sklearn_cosine(query_vec, self.tfidf_matrix)[0].copy()

        for i, chunk in enumerate(self.chunks):
            # Stage boost
            if stage and stage in chunk.stage_tags:
                scores[i] *= STAGE_BOOST
            # Authority boost
            scores[i] *= AUTHORITY_BOOST.get(chunk.authority, 1.0)
            # Domain permission filter (kernel always allowed)
            if allowed_domains and not self._domain_match(chunk, allowed_domains):
                scores[i] = 0.0

        ranked = sorted(enumerate(scores), key=lambda x: -x[1])[:top_k]
        return [ScoredChunk(self.chunks[i], float(s), "tfidf") for i, s in ranked if s > 0]

    def _domain_match(self, chunk, allowed_domains):
        domain = chunk.domain
        return domain == "kernel" or domain in allowed_domains

    def load_kernel(self):
        kernel_chunks = sorted(
            [c for c in self.chunks if c.chunk_id.startswith("kernel/")],
            key=lambda c: c.chunk_id,
        )
        return "\n\n".join(c.content for c in kernel_chunks)
```

- [ ] **Step 5: Run all retriever tests**

Run: `pytest tests/test_knowledge_retriever.py -v`
Expected: ALL PASS

- [ ] **Step 6: Add TF-IDF fitting to enrichment pipeline**

Modify `harness/enrich_knowledge.py` to add `fit_tfidf(chunks, output_dir)` that:
1. Builds text corpus: content + keywords for each chunk
2. Fits `TfidfVectorizer(stop_words="english")`
3. Saves `{"vectorizer": vectorizer, "matrix": matrix}` to `_tfidf.pkl`

- [ ] **Step 7: Run enrichment pipeline end-to-end**

Run: `python harness/enrich_knowledge.py --knowledge-dir data/knowledge/ --fit-tfidf`
Verify: `_index.json` and `_tfidf.pkl` both exist in `data/knowledge/`

- [ ] **Step 8: Update .gitignore**

Add to `.gitignore`:
```
# Generated knowledge index artifacts
data/knowledge/_tfidf.pkl
data/knowledge/_embeddings.npy
data/knowledge/_chunks/
```

- [ ] **Step 9: Commit**

```bash
git add harness/knowledge_retriever.py tests/test_knowledge_retriever.py harness/enrich_knowledge.py requirements.txt .gitignore
git commit -m "feat(wave6): add TFIDFRetriever with direct scoring and domain permission filtering"
```

---

## Task 5: Retrieval Evaluation Test Set

**Files:**
- Create: `eval/retrieval_eval.yaml`
- Create: `eval/run_retrieval_eval.py`
- Create: `tests/test_retrieval_eval.py`

- [ ] **Step 1: Write the 25 test cases**

Create `eval/retrieval_eval.yaml` with all 25 test cases from the spec (Section 2). Each case has: id, query, question_type, must_retrieve, should_retrieve, must_not_retrieve, kernel_sufficient.

- [ ] **Step 2: Write tests for the eval runner**

```python
# tests/test_retrieval_eval.py
"""Tests for the retrieval evaluation runner."""
import pytest
from eval.run_retrieval_eval import (
    load_eval_cases,
    score_single_case,
    compute_aggregate_scores,
)


class TestRetrievalEval:
    def test_load_eval_cases(self):
        cases = load_eval_cases("eval/retrieval_eval.yaml")
        assert len(cases) == 25

    def test_score_perfect_retrieval(self):
        """All must_retrieve found, no must_not_retrieve found."""
        score = score_single_case(
            retrieved=["metric/click_quality", "metric/click_quality_baselines"],
            must_retrieve=["metric/click_quality", "metric/click_quality_baselines"],
            must_not_retrieve=["eval/pointwise_umbrella"],
        )
        assert score["recall_must"] == 1.0
        assert score["noise_rate"] == 0.0

    def test_score_partial_retrieval(self):
        score = score_single_case(
            retrieved=["metric/click_quality"],
            must_retrieve=["metric/click_quality", "metric/click_quality_baselines"],
            must_not_retrieve=[],
        )
        assert score["recall_must"] == 0.5

    def test_aggregate_scores(self):
        case_scores = [
            {"recall_must": 1.0, "noise_rate": 0.0},
            {"recall_must": 0.5, "noise_rate": 0.1},
        ]
        agg = compute_aggregate_scores(case_scores)
        assert agg["mean_recall_must"] == 0.75
        assert agg["mean_noise_rate"] == 0.05
```

- [ ] **Step 3: Implement eval runner**

Create `eval/run_retrieval_eval.py` with:
- `load_eval_cases(yaml_path)` — reads test cases
- `score_single_case(retrieved, must_retrieve, must_not_retrieve)` — computes recall + noise
- `compute_aggregate_scores(case_scores)` — aggregates across all cases
- `run_eval(retriever, eval_path)` — runs all cases through retriever, prints scorecard
- CLI: `python eval/run_retrieval_eval.py --index-dir data/knowledge/`

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_retrieval_eval.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run the eval against the TF-IDF retriever**

Run: `python eval/run_retrieval_eval.py --index-dir data/knowledge/`
Expected: Scorecard output. keyword_coverage ≥ 0.95, conceptual_coverage likely < 0.75 (embeddings not yet added).

- [ ] **Step 6: Commit**

```bash
git add eval/retrieval_eval.yaml eval/run_retrieval_eval.py tests/test_retrieval_eval.py
git commit -m "feat(wave6): add retrieval evaluation test set with 25 ground truth cases"
```

---

## Task 6: Manifest + CONTRACT Block Updates

**Files:**
- Modify: `harness/manifest.yaml`
- Modify: `agents/understand.md`, `agents/hypothesize.md`, `agents/dispatch-ranking.md`, `agents/dispatch-connector.md`, `agents/dispatch-ai-quality.md`, `agents/investigation-sub-agent.md`, `agents/synthesize.md`

- [ ] **Step 1: Update manifest.yaml to permission semantics**

Replace the current `routes:` block with the `permissions:` block from the spec (Section 7). Include the `# Default policy: DENY` comment.

- [ ] **Step 2: Update all 7 agent CONTRACT blocks**

Change `knowledge_context:` to `knowledge_access:` in each agent's CONTRACT block. (Note: the existing field is `knowledge_context:`, not `knowledge_required:` — verify with `grep knowledge_context agents/*.md`.) Use the corresponding `allowed_domains`, `max_retrievals`, and `retrieval_budget` from the manifest.

- [ ] **Step 3: Run existing registry tests to check for regressions**

Run: `pytest tests/test_registry.py -v`
Expected: ALL PASS (CONTRACT block format may need test updates if tests parse the old format)

- [ ] **Step 4: Commit**

```bash
git add harness/manifest.yaml agents/*.md
git commit -m "feat(wave6): convert manifest to permission boundaries, update agent CONTRACT blocks"
```

---

## Task 7: Orchestrator Integration

**Files:**
- Modify: `harness/orchestrator.py`
- Create: `tests/test_orchestrator_retrieval.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_orchestrator_retrieval.py
"""Tests for orchestrator + knowledge retriever integration."""
import pytest
from harness.orchestrator import SearchMetricOrchestrator
from harness.knowledge_retriever import KnowledgeChunk, TFIDFRetriever


@pytest.fixture
def test_retriever():
    """Build an in-memory retriever for testing (no disk index needed)."""
    chunks = [
        KnowledgeChunk(
            chunk_id="kernel/metric_formulas", source_file="metric_definitions.yaml",
            source_section="metrics", context_header="",
            content="CQ = sum(long_clicks * log2_discount(rank)) / impressions. SQS = max(click_component, ai_trigger * ai_success).",
            token_estimate=150, keywords=["click_quality", "formula", "search_quality_success"],
            authority="definitional", stage_tags=[], staleness_tier="stable", cross_refs=[],
        ),
        KnowledgeChunk(
            chunk_id="kernel/alert_thresholds", source_file="metric_definitions.yaml",
            source_section="metrics", context_header="",
            content="P0: >5% movement. P1: 2-5%. P2: 0.5-2%.",
            token_estimate=100, keywords=["threshold", "p0", "p1", "severity"],
            authority="definitional", stage_tags=[], staleness_tier="stable", cross_refs=[],
        ),
        KnowledgeChunk(
            chunk_id="kernel/inverse_co_movement", source_file="metric_definitions.yaml",
            source_section="metrics", context_header="",
            content="AI answers and clicks have INVERSE co-movement. More AI = fewer clicks = EXPECTED. Do NOT treat as regression.",
            token_estimate=80, keywords=["inverse", "ai_adoption", "co_movement"],
            authority="definitional", stage_tags=[], staleness_tier="stable", cross_refs=[],
        ),
    ]
    return TFIDFRetriever.from_chunks(chunks)


class TestOrchestratorRetrieval:
    def test_orchestrator_accepts_retriever(self, test_retriever):
        """Orchestrator accepts injected retriever (dependency injection)."""
        orch = SearchMetricOrchestrator(llm_callable=lambda **kw: "{}", retriever=test_retriever)
        assert orch.retriever is not None

    def test_orchestrator_has_kernel(self, test_retriever):
        """Orchestrator loads kernel from retriever at init."""
        orch = SearchMetricOrchestrator(llm_callable=lambda **kw: "{}", retriever=test_retriever)
        assert orch.kernel is not None
        assert len(orch.kernel) > 50

    def test_kernel_contains_formulas(self, test_retriever):
        orch = SearchMetricOrchestrator(llm_callable=lambda **kw: "{}", retriever=test_retriever)
        assert "CQ" in orch.kernel or "click_quality" in orch.kernel.lower()

    def test_orchestrator_without_retriever(self):
        """Orchestrator works without retriever (graceful degradation)."""
        orch = SearchMetricOrchestrator(llm_callable=lambda **kw: "{}")
        assert orch.retriever is None
        assert orch.kernel == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator_retrieval.py -v`
Expected: FAIL (retriever/kernel attributes don't exist yet)

- [ ] **Step 3: Wire retriever into orchestrator __init__**

Modify `harness/orchestrator.py`:
- Accept optional `retriever` parameter for dependency injection (tests pass in-memory retriever)
- Import TFIDFRetriever (with try/except for graceful degradation if index not built)
- In `__init__`, if no retriever passed, attempt to load from `data/knowledge/`; set to None if index not built
- Load kernel text from retriever (empty string if retriever is None)
- Store both as instance attributes

- [ ] **Step 4: Add retrieval calls to each pipeline stage**

Modify `harness/orchestrator.py` stage methods to call `retriever.search()` before LLM calls:

```python
# In _run_understand():
if self.retriever:
    chunks = self.retriever.search(
        query=brief["raw_question"],
        stage="understand",
        extra_keywords=brief.get("expanded_keywords", []),
        allowed_domains=self._get_permissions("understand").get("allowed_domains"),
    )
    knowledge_context = self._format_chunks(chunks)
else:
    knowledge_context = ""

# Similarly in _run_hypothesize(), _run_dispatch(), _run_synthesize()
```

Add helper `_get_permissions(stage)` that reads manifest.yaml permissions for the stage.
Add helper `_format_chunks(chunks)` that prepends context_header + content for each chunk.

- [ ] **Step 5: Modify prompts.py to inject kernel + retrieved knowledge**

Modify `harness/prompts.py`:
- Add `kernel_context` parameter to `build_understand_system_prompt()` and similar
- Prepend kernel text as "## Always-Available Knowledge" section in system prompt
- Add retrieved chunks as "## Retrieved Knowledge" section in system prompt

- [ ] **Step 6: Add trace spans for retrieval calls**

Every `retriever.search()` call emits a trace span (per spec Section 7):

```python
# In each stage method, wrap retrieval in trace span:
with self.trace.span("knowledge_retrieval", stage="understand") as span:
    chunks = self.retriever.search(...)
    span.set_attributes({
        "query": brief["raw_question"],
        "expanded_keywords": brief.get("expanded_keywords", []),
        "chunks_returned": [c.chunk.chunk_id for c in chunks],
        "scores": [round(c.score, 4) for c in chunks],
        "retrieval_path": chunks[0].retrieval_path if chunks else "none",
        "tokens_retrieved": sum(c.chunk.token_estimate for c in chunks),
    })
```

This makes Invisible Decision #3 (sub-agent context construction) visible.

- [ ] **Step 7: Run integration tests + existing orchestrator tests**

Run: `pytest tests/test_orchestrator_retrieval.py tests/test_orchestrator.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add harness/orchestrator.py harness/prompts.py tests/test_orchestrator_retrieval.py
git commit -m "feat(wave6): wire knowledge retriever into orchestrator with per-stage retrieval + trace"
```

---

## Task 8: API Embeddings Hybrid (Optional — P5)

**Files:**
- Modify: `harness/knowledge_retriever.py` (add HybridRetriever)
- Modify: `harness/enrich_knowledge.py` (add embedding generation)
- Modify: `requirements.txt` (add httpx)
- Create: `tests/test_hybrid_retriever.py`

This task is P5 — implement after Tasks 1-7 are done and TF-IDF retrieval eval results are reviewed. Can be deferred to a separate session.

- [ ] **Step 1: Add httpx dependency**

```bash
echo "httpx>=0.27" >> requirements.txt
pip install httpx
```

- [ ] **Step 2: Write tests for HybridRetriever**

Test that HybridRetriever:
- Degrades to TF-IDF when embedding API unavailable
- Combines scores with configurable weights
- Uses pre-computed query templates when available
- Traces the retrieval path ("hybrid" vs "tfidf")

- [ ] **Step 3: Implement HybridRetriever**

Extend `knowledge_retriever.py` with:
- `HybridRetriever(TFIDFRetriever)` that adds embedding scoring path
- `_get_query_embedding()` with template matching → API → fallback chain
- Configurable `tfidf_weight` (default 0.5)
- Pre-computed query template loading from `_index.json`

- [ ] **Step 4: Add embedding generation to enrichment pipeline**

Extend `enrich_knowledge.py` with `--with-embeddings` flag:
- Calls embedding API for each chunk content
- Saves to `_embeddings.npy`

- [ ] **Step 5: Run retrieval eval with hybrid retriever**

Run: `python eval/run_retrieval_eval.py --index-dir data/knowledge/ --hybrid`
Expected: conceptual_coverage should improve from TF-IDF-only baseline

- [ ] **Step 6: Commit**

```bash
git add harness/knowledge_retriever.py harness/enrich_knowledge.py tests/test_hybrid_retriever.py requirements.txt
git commit -m "feat(wave6): add HybridRetriever with API embeddings + pre-computed query templates"
```

---

## Parallel Execution Map

```
Task 1 (schema) ─────────────────────────> Task 4 (TF-IDF retriever) ──> Task 7 (orchestrator)
                                              │
Task 2 (query expansion) ── independent       │
                                              │
Task 3 (chunker) ────────────────────────> Task 4 (needs chunks)
                                              │
Task 5 (eval test set) ── needs chunk IDs ──> Task 5 (run eval)
                                              │
Task 6 (manifest/CONTRACT) ── independent     │
                                              │
                                           Task 8 (hybrid, optional P5)
```

**Can run in parallel:** Tasks 2 + 3 (query expansion + chunker are independent)
**Can run in parallel:** Tasks 5 + 6 (eval test set + manifest updates are independent)
**Sequential dependencies:** 1 → 3 → 4 → 7 (schema → chunker → retriever → orchestrator)

---

## Deferred: P6 (Kernel Optimization)

P6 (kernel optimization — shrink always-loaded context from ~1,200 to ~330 tokens) is **already addressed by design**: the kernel is defined as 3 chunks totaling ~330 tokens in the spec (Section 1). There is no separate optimization step needed — the kernel was designed at the optimized size from the start.

If retrieval eval (Task 5) reveals that certain chunks should be promoted to or demoted from the kernel, adjust the `kernel/` prefix assignments in the chunk boundary definitions and re-run enrichment.
