# OpenAI Harness Engineering — Reference Notes

**Source:** https://openai.com/index/harness-engineering/

## Why This Is Relevant

This project (Search Metric Analyzer v2) faces the same core challenge OpenAI's harness engineering addresses: how to build reliable multi-stage AI pipelines where enforcement happens at stage boundaries, not just in prompts.

## Key Principles (from the post)

1. **Deterministic scaffolding around non-deterministic models** — Use code to enforce invariants that prompts cannot guarantee. Our implementation: Python seam contracts at stage boundaries.

2. **Trace everything** — Every decision, every intermediate result, every branch taken. Our implementation: TraceSpan with dual-audience design (human_summary + agent_context).

3. **Fail loudly at boundaries** — When a stage produces output that doesn't meet the contract, halt or degrade gracefully — never silently continue. Our implementation: SeamViolation with tiered gates (hard at UNDERSTAND, soft at HYPOTHESIZE/DISPATCH, retry+soft at SYNTHESIZE).

4. **Separate what from how** — The "what" (contracts, schemas, business rules) should be shared across execution modes. The "how" (skill file vs orchestrator) can vary. Our implementation: /contracts/ shared by Mode A and Mode B.

## Differences From Our Approach

- OpenAI operates at massive scale; we're a diagnostic tool for 2 Senior DSs. Our trace doesn't need distributed systems infrastructure.
- Their harness is fully autonomous; ours has a human-in-the-loop (the DS reviewing the report). This means our SYNTHESIZE stage needs to be optimized for human readability, not just correctness.
- Their failure modes are about throughput and latency; ours are about diagnostic accuracy and false alarm prevention.
