# Lead Agent: Complex Mode

## Purpose

Run the full investigation pipeline with parallel sub-agent dispatch for
high-severity events, multi-metric investigations, and deep dives. This mode
mirrors the in-house production system's Complex investigation pattern:
multiple sub-agents investigate hypotheses in parallel, with error isolation
and circuit breaker protection.

## When This Mode Activates

- Question type: `sev` with P0/P1 severity
- Question type: `experiment` with multiple metrics
- Question type: `deep_dive` (always)
- User override to `complex`

## Execution Flow

```
Question → UNDERSTAND → HYPOTHESIZE → DISPATCH (parallel) → SYNTHESIZE → Report
              (deterministic)   (LLM)       (ThreadPoolExecutor)   (LLM)
```

Same pipeline stages as Medium, but DISPATCH runs sub-agents in parallel
using ThreadPoolExecutor. Each hypothesis gets its own investigation thread.

## Token Budget

- **Target:** ~40,000 tokens total
- **UNDERSTAND knowledge:** Up to 5,000 tokens (full metric_definitions + historical_patterns)
- **HYPOTHESIZE prompt:** Up to 5,000 tokens (more corrections context)
- **DISPATCH per-hypothesis:** Up to 4,000 tokens × N hypotheses (parallel)
- **SYNTHESIZE:** Up to 8,000 tokens (more evidence to synthesize)

## Parallel DISPATCH Architecture

### Sub-Agent Dispatch
- Each hypothesis spawns an investigation sub-agent
- Sub-agents run in parallel via ThreadPoolExecutor (max_workers=5)
- Each sub-agent gets focused context (only its hypothesis + relevant knowledge)

### Error Isolation
- One sub-agent failure → "inconclusive" finding (others continue)
- Circuit breaker: 3 failures in same tier → StageError raised
- Per-agent timeout: separate from global pipeline timeout

### Coverage Check
- After all sub-agents complete, verify every hypothesis has at least one finding
- Missing coverage → warning in trace (not a halt)

## Pipeline Stages

### UNDERSTAND (Deterministic)
Same as Medium mode. More knowledge context loaded (full metric definitions).

### HYPOTHESIZE (LLM, Soft Gate)
Same as Medium mode. May generate more hypotheses for complex questions.

### DISPATCH (Parallel, Soft Gate)
- Build execution plan from hypothesis set
- Dispatch sub-agents in parallel (ThreadPoolExecutor)
- Collect findings with per-hypothesis error isolation
- Circuit breaker: abort if 3+ agents fail in same tier
- SRM check for experiment-type investigations
- Output: `FindingSet` with parallel execution metadata

### SYNTHESIZE (LLM, Retry Gate)
Same as Medium mode. More evidence to synthesize from parallel investigations.

## Quality Expectations

- All seam_validator business rules enforced
- Parallel execution doesn't compromise finding quality
- Circuit breaker prevents runaway failures
- Each hypothesis must have coverage (finding or inconclusive)
- Report quality score must meet threshold despite complexity
- Investigation trace captures parallel execution timeline

## Latency Improvement

Sequential (Medium): ~120s for 3 hypotheses (40s × 3)
Parallel (Complex): ~50s for 3 hypotheses (40s × 1, parallelized)

~60% reduction in DISPATCH stage latency for 3+ hypothesis investigations.
