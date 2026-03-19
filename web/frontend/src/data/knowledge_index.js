// knowledge_index.js — Static metadata describing each knowledge file the system uses.
//
// WHY this exists: The Knowledge Base tab needs to show users what domain knowledge
// powers the diagnostic system. Rather than parsing YAML files at runtime (which would
// require a backend call), we maintain a static index here. This is the same pattern
// as scenarios.js — pre-baked data for the frontend to render without a live backend.
//
// HOW to update: When a new knowledge file is added to data/knowledge/, add an entry
// here with its id, name, file path, description, and section breakdown. The sections
// array maps to top-level YAML keys that a user would see if they opened the file.
//
// PROVENANCE: Section keys and descriptions are sourced from the knowledge routing
// table in .claude/rules/04-knowledge-routing.md. If the YAML files change structure,
// update this index to match.

export const KNOWLEDGE_FILES = [
  {
    id: 'metric_definitions',
    name: 'Metric Definitions',
    file: 'data/knowledge/metric_definitions.yaml',
    description: 'Core metric formulas, baselines by segment, alert thresholds, and the co-movement diagnostic table.',
    sections: [
      {
        key: 'metrics',
        label: 'Metric Formulas',
        summary: 'Click Quality, SQS, AI Trigger, AI Success, Zero Result Rate — formulas and component breakdowns',
      },
      {
        key: 'baseline_by_segment',
        label: 'Baselines by Segment',
        summary: 'Expected metric values for ai_on/ai_off, enterprise/premium/standard tiers',
      },
      {
        key: 'co_movement_diagnostic_table',
        label: 'Co-Movement Table',
        summary: '9-row diagnostic table mapping metric movement patterns to likely root causes',
      },
      {
        key: 'hypothesis_priority',
        label: 'Hypothesis Priority',
        summary: 'Fixed investigation order: instrumentation → connector → query understanding → algorithm → experiment → AI → seasonal → behavior',
      },
    ],
  },
  {
    id: 'historical_patterns',
    name: 'Historical Patterns',
    file: 'data/knowledge/historical_patterns.yaml',
    description: 'Known incidents, seasonal patterns, and diagnostic shortcuts from past investigations.',
    sections: [
      {
        key: 'seasonal_patterns',
        label: 'Seasonal Patterns',
        summary: 'Enterprise onboarding waves, AI batch rollouts, end-of-quarter surges, weekend/weekday cycles',
      },
      {
        key: 'known_incidents',
        label: 'Known Incidents',
        summary: 'Past metric movements with data signatures and root causes for pattern matching',
      },
      {
        key: 'diagnostic_shortcuts',
        label: 'Diagnostic Shortcuts',
        summary: 'Cases where decomposition can be skipped (connector failures, model fallback spikes, single-tenant dominance)',
      },
    ],
  },
  {
    id: 'search_pipeline',
    name: 'Search Pipeline',
    file: 'data/knowledge/search_pipeline_knowledge.yaml',
    description: 'Pipeline component definitions, failure modes, causal chains, and NDCG benchmarks.',
    sections: [
      {
        key: 'pipeline_components',
        label: 'Pipeline Components',
        summary: 'Query Understanding (L0), Retrieval (L1), Reranking (L2), Interleaver (L3) — architecture and failure modes',
      },
      {
        key: 'causal_chains',
        label: 'Causal Chains',
        summary: 'Cross-component cascade effects — how failures propagate through the pipeline',
      },
      {
        key: 'benchmarks',
        label: 'NDCG Benchmarks',
        summary: 'Expected NDCG ranges from BM25-only through full hybrid retrieval',
      },
    ],
  },
  {
    id: 'architecture_tradeoffs',
    name: 'Architecture Tradeoffs',
    file: 'data/knowledge/architecture_tradeoffs.yaml',
    description: 'Cost optimization patterns, token economics, and cost-quality tradeoff diagnostics.',
    sections: [
      {
        key: 'cost_optimization_patterns',
        label: 'Cost Optimization',
        summary: 'Model tiering, caching strategies, batch vs real-time tradeoffs',
      },
      {
        key: 'token_economics',
        label: 'Token Economics',
        summary: 'Cost comparison across embedding, reranking, and generation models',
      },
    ],
  },
  {
    id: 'evaluation_methods',
    name: 'Evaluation Methods',
    file: 'data/knowledge/evaluation_methods.yaml',
    description: 'LLM-as-judge methodology, measurement pitfalls, and artifact detection.',
    sections: [
      {
        key: 'evaluation_approaches',
        label: 'Evaluation Approaches',
        summary: 'LLM-as-judge methodology with bias mitigation and inter-rater agreement protocols',
      },
      {
        key: 'measurement_pitfalls',
        label: 'Measurement Pitfalls',
        summary: 'Common pitfalls: proxy metric traps, survivorship bias, Simpson\'s paradox, attribution gaps',
      },
    ],
  },
  {
    id: 'corrections',
    name: 'Corrections Log',
    file: 'data/knowledge/corrections.yaml',
    description: 'Past diagnostic mistakes and corrections — the system learns from its own errors.',
    sections: [
      {
        key: 'corrections',
        label: 'Corrections',
        summary: 'Historical corrections with 90-day expiry, used to prevent repeat misdiagnoses',
      },
    ],
  },
]
