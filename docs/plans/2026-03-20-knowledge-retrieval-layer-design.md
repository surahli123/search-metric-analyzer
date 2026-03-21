# Knowledge Retrieval Layer Design

## Context & Motivation

### Problem
The in-house Search Metric Agent's knowledge layer suffers from **retrieval inefficiency**: the manifest-based pre-load architecture wastes tokens at the UNDERSTAND stage and causes visible investigation failures when routing under-scopes the agent.

**Root cause:** The harness routes knowledge via keyword matching BEFORE the model reasons, and the model can never up-scope if the routing was wrong. The feedback loop is asymmetric — you can under-scope the agent but the agent can't recover.

**Symptoms observed in-house:**
1. Token waste — Complex investigations load 55K tokens when 8K were needed
2. UNDERSTAND stage failures — wrong knowledge loaded, agent confidently produces wrong conclusions
3. Confluence search backing store retrieves wrong answers — ranking by recency/popularity instead of authority/specificity

### Design Influence
Three reference architectures informed this design:

**OpenAI Data Agent:** 6-layer knowledge pyramid (Table Usage → Human Annotations → Codex Enrichment → Institutional Knowledge → Memory → Runtime Context). Offline pre-processing into RAG embeddings + live retrieval via semantic search + exact text match. Key insight: agents auto-enrich knowledge about code (Codex Enrichment layer).

**Vercel AI Data Agent:** Tool-based on-demand access (LoadCatalog, SearchCatalog, RecallContext, LoadEntityDetails, SearchSchema). The agent is its own knowledge router — no manifest, no pre-loading. Semantic catalog lives in a sandbox.

**a16z Context Layer:** Context layer = superset of semantic layer (canonical entities + identity resolution + tribal knowledge + governance + self-updating flows). "Metric disambiguation is fundamentally a search problem" (Glean CEO).

### Architecture Decision
**Hybrid approach:** Pre-load a minimal kernel (~330 tokens of invariant knowledge) + on-demand retrieval via TF-IDF + API embeddings for everything else. This combines the reliability of always-available core knowledge with the precision of query-time retrieval.

This replaces the current `harness/manifest.yaml` pre-load architecture. The manifest becomes a permission boundary (what each agent CAN access) rather than a loading instruction (what to pre-load).

---

## Priority Order (IC9 Search Review)

An IC9 search architecture review reordered priorities from the original plan:

| Priority | Component | Why |
|---|---|---|
| **P0** | Chunk boundaries + schema | Everything else depends on good chunks. Bad chunks = garbage-in-garbage-out. |
| **P1** | Retrieval evaluation test set | Can't validate any retrieval design without ground truth. |
| **P2** | Query expansion in question_parser | Solves 80% of "TF-IDF can't find it" without new dependencies. |
| **P3** | TF-IDF retrieval with direct scoring | The actual retrieval engine. |
| **P4** | Auto-enrichment pipeline | Generates chunk metadata. |
| **P5** | API embeddings (hybrid) | Semantic matching for the 20% TF-IDF + expansion can't handle. |
| **P6** | Kernel optimization | Shrink always-loaded context. |

**Key reframe from IC9 review:**
- The "something changed overnight" problem is a **query understanding** failure, not a retrieval failure. Fix query expansion (P2) before adding embeddings (P5).
- At 56 chunks, use **direct scoring** — RRF is unnecessary complexity at this scale.
- **Chunk boundaries** (P0) matter more than the retrieval algorithm (P3). You could build the world's best hybrid retrieval and it would fail if chunks are wrong.
- **Retrieval evaluation** (P1) must exist before building retrieval. Same principle as eval sets before ranking model changes.

---

## Section 1: Chunk Schema (P0)

### Chunk Data Structure

```json
{
  "chunk_id": "co_movement/ai_adoption_positive",
  "source_file": "metric_definitions.yaml",
  "source_section": "co_movement_diagnostic_table",
  "context_header": "Co-movement diagnostic table: compare metric directions simultaneously to narrow hypotheses before decomposition.",
  "content": "CQ↓ + SQS stable/↑ + AI Trigger↑ + AI Success↑ = AI answers cannibalizing clicks. POSITIVE signal, not regression. Users get answers without clicking. Do NOT treat as regression.",
  "token_estimate": 120,
  "keywords": ["click_quality", "search_quality_success", "ai_trigger", "ai_adoption", "inverse_co_movement"],
  "authority": "definitional",
  "stage_tags": ["understand", "hypothesize"],
  "staleness_tier": "stable",
  "cross_refs": ["kernel/inverse_co_movement", "metric/click_quality_baselines"]
}
```

**Field definitions:**

| Field | Type | Purpose |
|---|---|---|
| `chunk_id` | string | Unique ID: `{domain}/{concept}`. Used for retrieval eval ground truth. |
| `source_file` | string | Origin YAML filename. For provenance tracking. |
| `source_section` | string | YAML section key within source file. |
| `context_header` | string | Shared text prepended when chunk is retrieved. Gives agent context about what this chunk is part of. |
| `content` | string | Actual chunk text. What gets injected into agent context. |
| `token_estimate` | int | Pre-computed token count. Used for budget enforcement. |
| `keywords` | list[str] | Specific terms for TF-IDF boosting. Metric names, component names, pattern names. |
| `authority` | enum | `definitional` (formulas, thresholds) > `empirical` (patterns, benchmarks) > `contextual` (corrections, incidents). |
| `stage_tags` | list[str] | Pipeline stages where this chunk is relevant. Used for stage boost in scoring. |
| `staleness_tier` | enum | `stable` (formulas) / `semi_stable` (baselines) / `volatile` (corrections, incidents). Drives refresh expectations. |
| `cross_refs` | list[str] | Related chunk IDs. Used by enrichment pipeline for cross-reference generation. |

### Chunk Boundaries

#### metric_definitions.yaml → 20 chunks

**Kernel chunks (always loaded, ~330 tokens total):**

| Chunk ID | Content | ~Tokens |
|---|---|---|
| `kernel/metric_formulas` | Formulas only for all 6 metrics (CQ, SQS, AT, AS, ZRR, latency) | 150 |
| `kernel/alert_thresholds` | P0/P1/P2 thresholds for CQ and SQS | 100 |
| `kernel/inverse_co_movement` | AI-CQ inverse rule + "do NOT treat as regression" | 80 |

**Per-metric chunks (7 total):**

| Chunk ID | Content | ~Tokens |
|---|---|---|
| `metric/click_quality` | Full CQ: description, components, decomposition dimensions, normal range, co-movements | 180 |
| `metric/click_quality_baselines` | CQ baselines by segment (ai_on=0.220, ai_off=0.310, enterprise=0.295, premium=0.280, standard=0.245) + notes | 150 |
| `metric/search_quality_success` | Full SQS: description, components, dimensions, normal range | 140 |
| `metric/ai_trigger_rate` | AT definition, dimensions, normal range | 90 |
| `metric/ai_success_rate` | AS definition, dimensions, normal range | 100 |
| `metric/zero_result_rate` | ZRR definition, normal range | 70 |
| `metric/latency_p50` | Latency definition, normal range | 70 |

CQ gets a separate baselines chunk because "what's the CQ formula?" ≠ "what's the enterprise CQ baseline?" — different queries, different retrieval needs.

**Co-movement pattern chunks (9 total, 1 per diagnostic pattern):**

Shared context header: *"Co-movement diagnostic table: compare metric directions simultaneously to narrow hypotheses. Use to identify the most likely cause BEFORE running decomposition."*

| Chunk ID | Pattern | Likely Cause | ~Tokens |
|---|---|---|---|
| `co_movement/ranking_regression` | CQ↓ SQS↓ AI stable stable | ranking_relevance_regression | 100 |
| `co_movement/ai_adoption_positive` | CQ↓ SQS stable/↑ AI↑ ↑ | ai_answers_working (POSITIVE) | 120 |
| `co_movement/broad_degradation` | CQ↓ SQS↓ AI↓ ↓ | broad_quality_degradation | 100 |
| `co_movement/ai_quality_regression` | CQ↓ SQS↓ AT stable AS↓ | sain_quality_regression | 100 |
| `co_movement/click_behavior_change` | CQ↓ SQS stable AI stable stable | click_behavior_change | 90 |
| `co_movement/ai_trigger_regression` | CQ stable SQS↓ AT↓ AS stable | sain_trigger_regression | 90 |
| `co_movement/ai_success_regression` | CQ stable SQS↓ AT stable AS↓ | sain_success_regression | 90 |
| `co_movement/query_understanding_regression` | CQ↓ SQS↓ AT↓ AS stable/↓ | query_understanding_regression | 120 |
| `co_movement/no_significant_movement` | All stable | normal fluctuation | 70 |

Individual chunking (not clusters) enables retrieval of the ONE relevant pattern for a given metric direction combination.

**Hypothesis priority chunk (1 total):**

| Chunk ID | Content | ~Tokens |
|---|---|---|
| `hypothesis/priority_order` | Full 8-item priority list with rationale (instrumentation first → user behavior last) | 200 |

#### historical_patterns.yaml → 12 chunks

**Seasonal patterns (5 chunks):**

Context header: *"Seasonal patterns: recurring metric movements with known causes. Check calendar alignment and segment by the key dimension before investigating."*

| Chunk ID | Pattern | ~Tokens |
|---|---|---|
| `seasonal/enterprise_onboarding_wave` | Large tenant batch onboarding drags metrics via mix-shift | 120 |
| `seasonal/ai_batch_rollout` | AI enablement → CQ↓ but SQS↑ (POSITIVE) | 110 |
| `seasonal/connector_outage` | Third-party connector degradation → CQ↓ ZRR↑ | 100 |
| `seasonal/end_of_quarter_surge` | Finance/compliance searches → exploratory queries → lower CTR | 80 |
| `seasonal/weekend_weekday_cycle` | Weekend has fewer queries, power user skew → apparent CQ↑ | 80 |

**Known incidents (3 chunks):**

Context header: *"Known past incidents: specific events with data signatures. Use data_signature fields to match against current observation."*

| Chunk ID | Incident | ~Tokens |
|---|---|---|
| `incident/2025_11_logging_anomaly` | Click tracking pipeline migration dropped 8% of events. Step-change, all segments equal. | 100 |
| `incident/2025_09_connector_outage` | Confluence API rate limiting. Gradual onset, concentrated in connector. | 90 |
| `incident/2025_08_model_regression` | L3 ranker retraining position bias. Concentrated in standard tier, positions 3-5. | 100 |

**Diagnostic shortcuts (4 chunks):**

Context header: *"Diagnostic shortcuts: if condition is true, skip full decomposition and jump directly to root cause investigation."*

| Chunk ID | Condition | ~Tokens |
|---|---|---|
| `shortcut/connector_health` | Connector dashboard shows failures → skip to connector root cause | 60 |
| `shortcut/model_fallback_rate` | Fallback rate spiked → jump to serving/latency | 60 |
| `shortcut/single_tenant_dominance` | One tenant >40% of movement → tenant-specific analysis | 60 |
| `shortcut/overnight_step_change` | >2% overnight step-change → check instrumentation first | 60 |

#### search_pipeline_knowledge.yaml → 9 chunks

**Pipeline components (5 chunks):**

Each includes function, approaches, AND failure modes together — failure modes are meaningless without component context.

Context header: *"Search pipeline components: L0-L3 architecture. Each component includes approaches (cost tiers) and failure modes (with metric signatures and diagnostic checks)."*

| Chunk ID | Component | ~Tokens |
|---|---|---|
| `pipeline/query_understanding` | Function, 4 approaches (rule → LLM), 2 failure modes (misclassification, hallucinated category) | 280 |
| `pipeline/query_corrections` | Function, 2 approaches, 2 failure modes (harmful synonym expansion, low net improvement) | 200 |
| `pipeline/content_classification` | Function, 3 approaches, 2 failure modes (low ceiling attribute, vocabulary mismatch) | 240 |
| `pipeline/ranking` | Function, 3 approaches, 2 failure modes (boost weight imbalance, missing interactions) | 220 |
| `pipeline/vector_search` | Function, 3 approaches, 2 failure modes (lexical mismatch, top-K truncation) | 220 |

These are the largest chunks (~200-280 tokens estimated; actual may be ~300-400 after YAML→text conversion). Token estimates will be validated during enrichment pipeline (P4) and updated in `_index.json`. Kept intact because splitting component function from failure modes breaks diagnostic reasoning.

**Causal chains (3 chunks):**

Context header: *"Cross-component causal chains: when a failure in one component cascades downstream. Use to explain multi-metric drops with a single root cause."*

| Chunk ID | Chain | ~Tokens |
|---|---|---|
| `causal/qu_misclassification_cascade` | QU misclassification → wrong category boost → click quality drops | 100 |
| `causal/content_classification_cascade` | Bad content labels → ranking noise → gradual degradation | 90 |
| `causal/synonym_expansion_cascade` | Bad synonyms → BM25 inflation → variable per-query impact | 80 |

**Benchmarks (1 chunk):**

| Chunk ID | Content | ~Tokens |
|---|---|---|
| `benchmark/ndcg_reference` | NDCG progression (BM25=0.541 → hybrid=0.665) + classifier precision table | 200 |

#### architecture_tradeoffs.yaml → 7 chunks

**Cost optimization patterns (4 chunks):**

Context header: *"Cost optimization patterns: when quality drops coincide with cost/latency decreases, check if an optimization was deployed."*

| Chunk ID | Pattern | ~Tokens |
|---|---|---|
| `cost/model_tiering` | Swap expensive model for cheap one. Precision collapse + tail degradation failure modes. | 250 |
| `cost/batch_processing` | Pre-compute enrichments offline. Cold start gap + stale enrichment failure modes. | 220 |
| `cost/semantic_caching` | Cache by embedding similarity. False cache hit + numerical confusion + staleness. | 280 |
| `cost/constraint_reduction` | Hallucinate + embed resolve. Resolution error + hallucination drift. | 230 |

**Token economics + diagnostic implications (3 chunks):**

| Chunk ID | Content | ~Tokens |
|---|---|---|
| `cost/token_economics` | Model cost comparison + component token costs table | 150 |
| `cost/diagnostic_step2d` | When ranking hypotheses, check for recent cost optimization | 100 |
| `cost/diagnostic_step4` | Distinguish intentional tradeoff from unintended regression | 100 |

#### evaluation_methods.yaml → 7 chunks

**Evaluation approaches (2 chunks):**

Context header: *"Evaluation methods: how metrics are computed. Critical for distinguishing real quality changes from measurement artifacts."*

| Chunk ID | Method | ~Tokens |
|---|---|---|
| `eval/pointwise_umbrella` | UMBRELLA framework: 0-3 scale, 73.3% agreement, chain-of-thought prompt | 280 |
| `eval/pairwise_preference` | Pairwise with double-check: swap-based debiasing, 90.8% precision decision tree | 280 |

**Measurement pitfalls (4 chunks):**

Context header: *"Measurement pitfalls: ways metrics can fool you. Check these before concluding a metric movement is real."*

| Chunk ID | Pitfall | ~Tokens |
|---|---|---|
| `pitfall/unlabeled_not_irrelevant` | Unlabeled ≠ irrelevant. NDCG undercount when new relevant results appear. | 100 |
| `pitfall/judge_calibration_shift` | LLM judge drift across model versions. Golden set check. | 100 |
| `pitfall/position_bias` | LHS/RHS bias in pairwise. Swap-based debiasing. | 100 |
| `pitfall/conservative_judge_bias` | Judge stricter than humans on borderline cases. Persistent negative offset. | 100 |

**Evaluation diagnostic (1 chunk):**

| Chunk ID | Content | ~Tokens |
|---|---|---|
| `eval/diagnostic_implications` | Step 1e (measurement vs real) + Step 3 (cross-check methodology) | 120 |

#### corrections.yaml → dynamic chunks

Each correction becomes its own chunk (dynamic, grows over time):

| Chunk ID | Content | ~Tokens |
|---|---|---|
| `correction/{date}_{metric}` | Full correction entry with context and lesson | ~100 each |

Context header: *"Diagnostic corrections: past mistakes and what was learned. Check for corrections matching the current metric before forming hypotheses."*

### Chunk Inventory Summary

| File | Chunks | Total Tokens |
|---|---|---|
| metric_definitions.yaml | 20 (3 kernel + 17 retrievable) | 330 kernel + 2,100 retrievable |
| historical_patterns.yaml | 12 | 920 |
| search_pipeline_knowledge.yaml | 9 | 1,430 |
| architecture_tradeoffs.yaml | 7 | 1,330 |
| evaluation_methods.yaml | 7 | 1,080 |
| corrections.yaml | 1+ (dynamic) | ~100 per entry |
| **Total** | **56 fixed + dynamic** | **330 kernel + ~6,860 retrievable** |

Average chunk size: ~125 tokens. Well within <500 entry scalability ceiling.

---

## Section 2: Retrieval Evaluation (P1)

### Test Case Schema

```yaml
# eval/retrieval_eval.yaml
test_cases:
  - id: "ret_001"
    query: "Click Quality dropped 3% for enterprise tier"
    question_type: "sev"
    expected_mode: "complex"
    must_retrieve:             # precision check
      - chunk_id: "metric/click_quality"
        reason: "Need full CQ definition to interpret the drop"
      - chunk_id: "metric/click_quality_baselines"
        reason: "Need enterprise baseline (0.295) to assess severity"
      - chunk_id: "co_movement/ranking_regression"
        reason: "CQ↓ without AI context → ranking regression pattern"
    should_retrieve:           # recall bonus
      - chunk_id: "shortcut/single_tenant_dominance"
      - chunk_id: "seasonal/enterprise_onboarding_wave"
    must_not_retrieve:         # noise check
      - chunk_id: "eval/pointwise_umbrella"
        reason: "Evaluation methodology not relevant to diagnostic"
      - chunk_id: "cost/semantic_caching"
        reason: "Cost optimization not indicated"
    kernel_sufficient: false
```

### Test Cases (25 total)

**Exact keyword queries (TF-IDF should nail — 8 cases):**

| ID | Query | Must Retrieve |
|---|---|---|
| ret_001 | "Click Quality dropped 3% for enterprise tier" | CQ def, CQ baselines, ranking_regression |
| ret_002 | "What's the SQS formula?" | SQS def (kernel may suffice) |
| ret_003 | "Confluence connector went down" | connector_outage, shortcut/connector_health |
| ret_004 | "AI trigger rate dropped, AI success stable" | ai_trigger_regression |
| ret_005 | "Is this a P0 or P1?" | (kernel only — thresholds) |
| ret_006 | "Check hypothesis priority order" | hypothesis/priority_order |
| ret_007 | "Recent corrections for click_quality" | Any correction chunk with metric=click_quality (dynamic — test uses fixture) |
| ret_008 | "NDCG benchmark for hybrid retrieval" | benchmark/ndcg_reference |

**Conceptual/symptomatic queries (need expansion or embeddings — 8 cases):**

| ID | Query | Must Retrieve |
|---|---|---|
| ret_009 | "Something changed overnight" | shortcut/overnight_step_change, incident/2025_11_logging |
| ret_010 | "Metrics look weird after a rollout" | seasonal/ai_batch_rollout, co_movement/ai_adoption_positive |
| ret_011 | "Is this a real problem or just noise?" | (kernel thresholds) + pitfall/judge_calibration_shift |
| ret_012 | "Numbers don't add up across segments" | seasonal/enterprise_onboarding_wave |
| ret_013 | "Quality got worse but we saved money" | cost/model_tiering, cost/diagnostic_step2d |
| ret_014 | "Users aren't clicking but seem happy" | co_movement/ai_adoption_positive |
| ret_015 | "Search is slow and results are bad" | metric/latency_p50, pipeline/ranking |
| ret_016 | "We changed a model and things broke" | cost/model_tiering, incident/2025_08_model_regression |

**Stage-specific queries (test stage boost — 5 cases):**

| ID | Query | Stage | Must Retrieve |
|---|---|---|---|
| ret_017 | "What patterns match CQ↓ SQS↓?" | UNDERSTAND | ranking_regression, broad_degradation, qu_regression |
| ret_018 | "Could this be a connector issue?" | HYPOTHESIZE | seasonal/connector_outage, shortcut/connector_health |
| ret_019 | "What evidence should I look for?" | DISPATCH | Pipeline failure mode diagnostic_checks |
| ret_020 | "How confident should I be?" | SYNTHESIZE | eval/diagnostic_implications |
| ret_021 | "Same thing as November?" | HYPOTHESIZE | incident/2025_11_logging_anomaly |

**Edge cases (4 cases):**

| ID | Query | Expected Behavior |
|---|---|---|
| ret_022 | "Tell me everything about search" | Not all chunks — only high-authority overviews |
| ret_023 | "What is the meaning of life?" | Nothing relevant (empty or very low scores) |
| ret_024 | "CQ up, SQS up, AI stable" | no_significant_movement, NOT regression patterns |
| ret_025 | "click_quality_value dropped in ai_off" | CQ def + CQ baselines (alias handling) |

### Scoring Metrics

```python
# Per test case:
recall_must = len(retrieved ∩ must_retrieve) / len(must_retrieve)
noise_rate  = len(retrieved ∩ must_not_retrieve) / len(retrieved)

# Aggregate:
mean_recall_must     = avg(recall_must)       # target: ≥0.90
mean_noise_rate      = avg(noise_rate)         # target: ≤0.05
keyword_coverage     = mean_recall on ret_001-008   # target: ≥0.95
conceptual_coverage  = mean_recall on ret_009-016   # target: ≥0.75
```

---

## Section 3: Query Expansion (P2)

### Expansion Map

New constant added to `harness/question_parser.py`. This supplements (does NOT replace) the existing `METRIC_ALIASES` dict (21 entries, lines 34-65) and `CLASSIFICATION_PATTERNS`.

**Matching strategy:** Case-insensitive substring match against the raw question. Multiple rules can fire — all matching expansions are accumulated. This is consistent with the existing regex-based matching in `extract_metric_hints()`.

```python
# NEW — added to harness/question_parser.py alongside existing constants
QUERY_EXPANSION_MAP = {
    # Symptom phrase → domain keywords for retrieval boosting
    # Matching: case-insensitive substring (re.search with re.IGNORECASE)
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
```

**Note:** The existing `METRIC_ALIASES` dict (which maps "cq" → "click_quality", "ai trigger" → "ai_trigger", etc.) is **not modified**. The canonical metric names remain `click_quality`, `search_quality_success`, `ai_trigger`, `ai_success` (no `_rate` suffix) — consistent with the co-movement table and contracts.

### Integration

The existing `parse_question()` function returns a plain dict (not a dataclass). We extend it with one new field, preserving the existing API:

```python
# In parse_question(), after building the brief dict (existing lines 407-414):
brief = {
    "raw_question": question,         # existing field name (NOT "raw")
    "question_type": question_type,   # existing
    "metric_hints": metric_hints,     # existing (NOT "metrics_mentioned")
    "time_range_hints": time_range_hints,  # existing
    "complexity_signals": complexity_signals,  # existing
    "investigation_plan": investigation_plan,  # existing
    "expanded_keywords": expand_query(question),  # NEW field
}
```

The `expand_query()` helper scans the raw question against `QUERY_EXPANSION_MAP` and returns accumulated domain keywords. These feed into the retriever's TF-IDF scoring as additional search terms.

---

## Section 4: TF-IDF Retrieval Engine (P3)

### New File: `harness/knowledge_retriever.py`

```python
@dataclass
class KnowledgeChunk:
    chunk_id: str
    source_file: str
    context_header: str
    content: str
    token_estimate: int
    keywords: list[str]
    authority: str          # definitional | empirical | contextual
    stage_tags: list[str]
    staleness_tier: str
    cross_refs: list[str]

@dataclass
class ScoredChunk:
    chunk: KnowledgeChunk
    score: float
    retrieval_path: str     # "tfidf" | "embedding" | "hybrid"

class KnowledgeRetriever(ABC):
    """Abstract interface — swap backends without changing callers."""
    @abstractmethod
    def search(self, query: str, top_k: int = 5, stage: str = None,
               extra_keywords: list[str] = None,
               allowed_domains: list[str] = None) -> list[ScoredChunk]: ...

    @abstractmethod
    def load_kernel(self) -> str: ...

class TFIDFRetriever(KnowledgeRetriever):
    def __init__(self, index_path: str):
        self.chunks = load_index(index_path)
        self.vectorizer = load_tfidf(index_path)
        # TF-IDF on content + keywords (keywords act as synthetic terms)
        self.tfidf_matrix = self.vectorizer.transform(
            [c.content + " " + " ".join(c.keywords) for c in self.chunks]
        )

    def search(self, query, top_k=5, stage=None, extra_keywords=None, allowed_domains=None):
        # Enrich query with expanded keywords
        enriched = query
        if extra_keywords:
            enriched += " " + " ".join(extra_keywords)

        # Cosine similarity against all chunks (<1ms at 56 chunks)
        query_vec = self.vectorizer.transform([enriched])
        scores = cosine_similarity(query_vec, self.tfidf_matrix)[0]

        # Apply boosts + filters
        for i, chunk in enumerate(self.chunks):
            if stage and stage in chunk.stage_tags:
                scores[i] *= 1.3                              # stage relevance
            if chunk.authority == "definitional":
                scores[i] *= 1.1                              # authority boost
            elif chunk.authority == "contextual":
                scores[i] *= 0.9                              # contextual discount
            if allowed_domains and not self._domain_match(chunk, allowed_domains):
                scores[i] = 0.0                               # CONTRACT filter

        ranked = sorted(enumerate(scores), key=lambda x: -x[1])[:top_k]
        return [ScoredChunk(self.chunks[i], s, "tfidf") for i, s in ranked if s > 0]

    def _domain_match(self, chunk, allowed_domains):
        """Domain = first segment of chunk_id (before '/').
        Example: chunk_id='co_movement/ranking_regression' → domain='co_movement'.
        Kernel chunks (domain='kernel') are ALWAYS allowed regardless of permissions."""
        domain = chunk.chunk_id.split("/")[0]
        return domain == "kernel" or domain in allowed_domains

    def load_kernel(self):
        """Return concatenated content of all kernel/* chunks.
        Order: metric_formulas → alert_thresholds → inverse_co_movement.
        Context headers are NOT included (kernel is self-explanatory)."""
        kernel_chunks = sorted(
            [c for c in self.chunks if c.chunk_id.startswith("kernel/")],
            key=lambda c: c.chunk_id
        )
        return "\n\n".join(c.content for c in kernel_chunks)
```

### Scoring Design

Direct scoring on all 56 chunks (not RRF — unnecessary at this scale):

| Signal | Weight | Rationale |
|---|---|---|
| TF-IDF cosine similarity | Base score | Core relevance signal |
| Stage tag match | ×1.3 | Prioritize stage-appropriate knowledge |
| Authority = definitional | ×1.1 | Mild preference for authoritative sources |
| Authority = contextual | ×0.9 | Mild discount for time-bounded knowledge |
| CONTRACT domain filter | 0.0 if not allowed | Hard permission boundary |

---

## Section 5: Auto-Enrichment Pipeline (P4)

### New File: `harness/enrich_knowledge.py`

```
Usage: python harness/enrich_knowledge.py [--with-embeddings] [--llm-enrich]

Offline batch job:
1. Read all knowledge YAMLs
2. Chunk per boundary spec (deterministic, no LLM needed)
3. Generate metadata per chunk:
   - Without --llm-enrich: extract from YAML structure (keywords from keys, cross-refs from co_movements)
   - With --llm-enrich: LLM generates summaries, keywords, cross-refs, when_useful
4. Fit TF-IDF vectorizer on chunk content + keywords
5. Optionally generate API embeddings (--with-embeddings)
6. Write output files
```

### Output Files

| File | Contents | Generated By |
|---|---|---|
| `data/knowledge/_index.json` | Chunk metadata (schema from Section 1) | Always |
| `data/knowledge/_tfidf.pkl` | Fitted TfidfVectorizer + sparse matrix | Always |
| `data/knowledge/_embeddings.npy` | Pre-computed chunk embeddings | Only with `--with-embeddings` |
| `data/knowledge/_chunks/` | Individual chunk text files (for debugging) | Always |

### Chunking Strategy

The chunker is deterministic — boundaries are defined in code, not discovered by LLM:

```python
CHUNK_BOUNDARIES = {
    "metric_definitions.yaml": {
        "kernel": [...],                          # extract specific fields
        "metrics": {"strategy": "one_per_metric", "split_baselines": ["click_quality"]},
        "co_movement_diagnostic_table": {"strategy": "one_per_pattern"},
        "hypothesis_priority": {"strategy": "single_chunk"},
    },
    "historical_patterns.yaml": {
        "seasonal_patterns": {"strategy": "one_per_entry"},
        "known_incidents": {"strategy": "one_per_entry"},
        "diagnostic_shortcuts": {"strategy": "one_per_entry"},
    },
    "search_pipeline_knowledge.yaml": {
        "pipeline_components": {"strategy": "one_per_component"},  # keep failure modes with component
        "causal_chains": {"strategy": "one_per_chain"},
        "benchmarks": {"strategy": "single_chunk"},
    },
    "architecture_tradeoffs.yaml": {
        "cost_optimization_patterns": {"strategy": "one_per_pattern"},
        "token_economics": {"strategy": "single_chunk"},
        "diagnostic_implications": {"strategy": "one_per_subkey"},  # splits on YAML sub-keys (step_2d_evidence, step_4_synthesis)
    },
    "evaluation_methods.yaml": {
        "evaluation_approaches": {"strategy": "one_per_approach"},
        "measurement_pitfalls": {"strategy": "one_per_pitfall"},
        "diagnostic_implications": {"strategy": "single_chunk"},
    },
}
```

### Re-Run Triggers

The enrichment pipeline should re-run when any knowledge YAML changes. A pre-commit hook can warn if YAMLs changed but `_index.json` didn't.

**Incremental vs full re-run:** At 56 chunks, full re-run is fast (<5 seconds for TF-IDF, <30 seconds with embeddings). No incremental path needed at this scale. For corrections.yaml (dynamic, grows over time), the full re-run is still trivial — a new correction adds ~1 chunk. Incremental enrichment is a v2+ optimization if the chunk count exceeds ~500.

### Security Note

`_tfidf.pkl` uses Python pickle format (standard for scikit-learn). Pickle files are a deserialization attack vector if sourced from untrusted origins. Since this file is generated locally and gitignored (not distributed), risk is low. If distribution is needed later, migrate to a JSON-serializable format (e.g., export TF-IDF vocabulary + IDF weights as JSON, reconstruct at load time).

---

## Section 6: API Embeddings Hybrid (P5)

### Pre-Computed Query Templates

Instead of calling the embedding API at runtime, pre-compute embeddings for ~30-50 known diagnostic patterns:

```json
{
  "query_templates": [
    {
      "pattern": "step_change",
      "canonical": "metric changed suddenly overnight step change deployment",
      "embedding": [0.12, -0.34, "..."],
      "maps_to_chunks": ["shortcut/overnight_step_change", "incident/2025_11_logging_anomaly"]
    },
    {
      "pattern": "ai_adoption",
      "canonical": "AI answers click quality inverse cannibalize positive signal",
      "embedding": [0.08, 0.45, "..."],
      "maps_to_chunks": ["co_movement/ai_adoption_positive", "seasonal/ai_batch_rollout"]
    }
  ]
}
```

At runtime, the question parser maps to a known pattern → use pre-computed embedding → zero API dependency. Only truly novel queries need the live API call.

### HybridRetriever

```python
class HybridRetriever(KnowledgeRetriever):
    def search(self, query, top_k=5, stage=None, extra_keywords=None, allowed_domains=None):
        # Path 1: TF-IDF (always, <1ms)
        tfidf_scores = self._tfidf_score_all(query, extra_keywords)

        # Path 2: Embedding (try pre-computed template, then API, then skip)
        embed_scores = self._embedding_score_all(query)

        # Direct scoring merge (not RRF — unnecessary at 56 chunks)
        # Initial weights: equal (0.5/0.5). Tune via retrieval eval set (P1).
        # Domain is keyword-dense → TF-IDF may deserve higher weight. Let eval decide.
        w_tfidf = self.config.get("tfidf_weight", 0.5)
        w_embed = 1.0 - w_tfidf
        for i, chunk in enumerate(self.chunks):
            if embed_scores is not None:
                combined = w_tfidf * tfidf_scores[i] + w_embed * embed_scores[i]
            else:
                combined = tfidf_scores[i]  # TF-IDF only fallback

            # Apply boosts (same as TFIDFRetriever)
            combined *= stage_boost(chunk, stage)
            combined *= authority_boost(chunk)
            combined *= domain_filter(chunk, allowed_domains)

            scores[i] = combined

        return top_k_results(scores)

    def _embedding_score_all(self, query):
        # Step 1: Check pre-computed templates (no API call)
        template = match_query_template(query)
        if template:
            query_embedding = template["embedding"]
        else:
            # Step 2: Try API
            try:
                query_embedding = self.embedding_api.embed(query)
            except APIError:
                self.trace.warn("embedding_api_unavailable", fallback="tfidf_only")
                return None  # degrade gracefully

        return cosine_similarity_all(query_embedding, self.chunk_embeddings)
```

### Embedding API Configuration

```python
EMBEDDING_CONFIG = {
    "provider": "anthropic",      # or "openai", configurable
    "model": "voyage-3-lite",     # lightweight, good for short chunks
    "dimension": 512,
    "batch_size": 50,             # for offline enrichment
}
```

Dependency: `httpx` (~1MB) for API calls. No ML libraries.

---

## Section 7: Integration with Existing Architecture

### Kernel Loading

Loaded once at orchestrator startup:

```python
class SearchMetricOrchestrator:
    def __init__(self, llm_callable, ...):
        self.retriever = HybridRetriever("data/knowledge/")
        self.kernel = self.retriever.load_kernel()  # ~330 tokens
```

Kernel content prepended to every LLM call as system context.

### Manifest Semantics Change

**Before (loading instructions):**
```yaml
routes:
  understand:
    knowledge_files:
      - {path: metric_definitions.yaml, max_tokens: 2000}
```

**After (permission boundaries):**
```yaml
# Default policy: DENY. Agents not listed here get zero retrievals.
# Kernel chunks (domain='kernel') are exempt — always accessible.
permissions:
  understand:
    allowed_domains: [metric, co_movement, seasonal, incident, shortcut, hypothesis]
    max_retrievals: 5
    max_tokens: 3000
  hypothesize:
    allowed_domains: [co_movement, hypothesis, correction, seasonal]
    max_retrievals: 3
    max_tokens: 2000
  dispatch-ranking:
    allowed_domains: [pipeline, causal, benchmark, correction]
    max_retrievals: 3
    max_tokens: 2000
  dispatch-connector:
    allowed_domains: [pipeline, seasonal, incident, correction]
    max_retrievals: 3
    max_tokens: 2000
  dispatch-ai-quality:
    allowed_domains: [cost, pipeline, co_movement, correction]
    max_retrievals: 3
    max_tokens: 2000
  investigation-sub-agent:
    allowed_domains: [metric, pipeline, seasonal, incident, correction, benchmark]
    max_retrievals: 3
    max_tokens: 2000
  synthesize:
    allowed_domains: [eval, pitfall, correction, co_movement]
    max_retrievals: 2
    max_tokens: 1000
```

**Design decisions:**
- Default policy is DENY — unlisted agents get kernel only. This prevents accidental over-retrieval.
- `investigation-sub-agent` gets broad access (metric, pipeline, seasonal, incident, correction, benchmark) because it investigates specific hypotheses and needs diverse evidence.
- `synthesize` gets `co_movement` access (added) because final synthesis may need to reference the diagnostic pattern that was identified.
- `understand` does NOT get `pipeline` or `causal` — pipeline knowledge is for DISPATCH agents who investigate specific components. UNDERSTAND identifies the pattern; DISPATCH investigates the cause.
- Kernel chunks (domain=`kernel`) are always accessible regardless of permissions.

### Agent CONTRACT Block Changes

```markdown
<!-- BEFORE: loading instruction -->
## CONTRACT
knowledge_required:
  - metric_definitions.yaml (max_tokens: 2000)
  - historical_patterns.yaml (max_tokens: 1500)

<!-- AFTER: permission boundary -->
## CONTRACT
knowledge_access:
  allowed_domains: [metric, co_movement, seasonal, incident, shortcut, hypothesis]
  max_retrievals: 5
  retrieval_budget: 3000 tokens
```

### Trace Integration

Every retrieval call emits a trace span:

```python
with trace.span("knowledge_retrieval", stage=stage) as span:
    results = self.retriever.search(query, stage=stage, ...)
    span.set_attributes({
        "query": query,
        "expanded_keywords": extra_keywords,
        "chunks_returned": [r.chunk.chunk_id for r in results],
        "scores": [r.score for r in results],
        "retrieval_path": results[0].retrieval_path if results else "none",
        "tokens_retrieved": sum(r.chunk.token_estimate for r in results),
    })
```

This makes Invisible Decision #3 (sub-agent context construction) **visible**.

### Pipeline Flow: When Retrieval Happens

QUESTION_PARSE is deterministic (no LLM, no retrieval). It produces expanded_keywords. The first retrieval happens at UNDERSTAND — the orchestrator calls `search_knowledge()` with the parsed question + expanded_keywords before invoking the UNDERSTAND agent's LLM call. Subsequent stages can make their own retrieval calls.

```
QUESTION_PARSE: parse_question() → expanded_keywords (no retrieval)
UNDERSTAND:     search_knowledge(question, expanded_keywords) → chunks → LLM call
HYPOTHESIZE:    search_knowledge(hypotheses) → chunks → LLM call
DISPATCH:       each sub-agent calls search_knowledge(hypothesis) → chunks → LLM call
SYNTHESIZE:     search_knowledge(findings) → chunks → LLM call
```

### Token Budget Comparison

| Investigation Type | Current Pre-Load | New Hybrid | Savings |
|---|---|---|---|
| Simple (formula lookup) | 3,500 tokens | ~330 (kernel only) | 91% |
| Medium (standard pipeline) | ~7,000 tokens | ~330 + 2-3 retrievals (~1,530) | 78% |
| Complex (full investigation) | ~10,000+ tokens | ~330 + 4-6 retrievals (~2,730) | 73% |
| Worst case (in-house) | 55,000 tokens | ~330 + 10 retrievals (~5,330) | 90% |

---

## Files Changed / Created

| Action | File | Purpose |
|---|---|---|
| **New** | `harness/knowledge_retriever.py` | KnowledgeChunk, ScoredChunk, TFIDFRetriever, HybridRetriever |
| **New** | `harness/enrich_knowledge.py` | Offline enrichment pipeline CLI |
| **New** | `data/knowledge/_index.json` | Chunk metadata index (generated) |
| **New** | `data/knowledge/_tfidf.pkl` | Fitted TF-IDF model (generated) |
| **New** | `data/knowledge/_embeddings.npy` | Pre-computed embeddings (generated, optional) |
| **New** | `data/knowledge/_chunks/` | Chunk text files (generated, for inspection) |
| **New** | `eval/retrieval_eval.yaml` | 25 retrieval ground truth test cases |
| **New** | `eval/run_retrieval_eval.py` | Retrieval evaluation script |
| **Modify** | `harness/manifest.yaml` | Loading instructions → permission boundaries |
| **Modify** | `harness/orchestrator.py` | Add kernel loading + retriever init |
| **Modify** | `harness/question_parser.py` | Add QUERY_EXPANSION_MAP + METRIC_ALIASES + expanded_keywords |
| **Modify** | `agents/*.md` | CONTRACT blocks: knowledge_required → knowledge_access |
| **Modify** | `requirements.txt` | Add scikit-learn |
| **Modify** | `.gitignore` | Add _tfidf.pkl, _embeddings.npy (generated artifacts) |

## New Dependencies

| Dependency | Purpose | Size | Required? |
|---|---|---|---|
| `scikit-learn` | TF-IDF vectorization + cosine similarity | ~30MB | Yes (P3) |
| `numpy` | Matrix operations (transitive from scikit-learn) | ~15MB | Yes |
| `httpx` | Embedding API calls | ~1MB | Only for P5 |

---

## Appendix: Ranking Signals Reference

The retrieval ranking is designed to be the **opposite of Confluence search** (which failed for the in-house agent):

| Signal | Confluence (wrong for agents) | SMA Retriever (right for agents) |
|---|---|---|
| Primary ranking | Recency (newest first) | **Authority** (definitions > patterns > corrections) |
| Secondary ranking | Popularity (most viewed) | **Specificity** (exact metric/component match) |
| Granularity | Full pages | **Per-concept chunks** with context headers |
| Feedback | User clicks | **Gate pass/fail** (future: investigation outcomes) |
| Recovery | None (results are final) | **Agent can re-query** with refined terms |
