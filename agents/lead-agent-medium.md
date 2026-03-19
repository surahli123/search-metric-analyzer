# Lead Agent: Medium Mode

## Purpose

Run the standard 4-stage investigation pipeline for questions that need analysis
but don't require parallel sub-agent dispatch. This is the default mode — the
current SMA behavior for P2 severity events, experiments, trends, and
system understanding questions.

## When This Mode Activates

- Question type: `sev` (P2/normal severity)
- Question type: `experiment` (single-metric)
- Question type: `trend`
- Question type: `system_understanding`
- Fallback for unrecognized types

## Execution Flow

```
Question → UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE → Report
              (deterministic)   (LLM)       (LLM, sequential)   (LLM)
```

All 4 pipeline stages run sequentially. DISPATCH investigates hypotheses
one at a time (no parallelism — that's Complex mode).

## Token Budget

- **Target:** ~20,000 tokens total
- **UNDERSTAND knowledge:** Up to 3,500 tokens (metric_definitions + historical_patterns)
- **HYPOTHESIZE prompt:** Up to 4,000 tokens
- **DISPATCH per-hypothesis:** Up to 3,000 tokens × 3 hypotheses
- **SYNTHESIZE:** Up to 5,000 tokens

## Pipeline Stages

### UNDERSTAND (Deterministic)
- Check data quality (hard gate — pipeline halts on failure)
- Run decomposition across standard dimensions
- Detect step changes
- Match co-movement pattern
- Output: `UnderstandResult` validated by seam_validator

### HYPOTHESIZE (LLM, Soft Gate)
- Generate 3+ hypotheses based on UNDERSTAND output
- Load relevant corrections (past diagnostic mistakes to avoid)
- Must include contrarian hypothesis
- Output: `HypothesisSet` validated by seam_validator

### DISPATCH (LLM, Soft Gate, Sequential)
- Investigate each hypothesis via LLM (one at a time)
- Per-hypothesis error isolation (failure → inconclusive, not pipeline halt)
- For experiments: SRM check applies (rule_srm_check)
- Output: `FindingSet` validated by seam_validator

### SYNTHESIZE (LLM, Retry Gate)
- Produce structured report with 7 mandatory sections
- First attempt validated; if fails, retry once with violation feedback
- If both fail, continue with completeness_warnings (soft fallback)
- Report quality score must meet threshold (rule_report_quality_score)
- Output: `SynthesisReport` validated by seam_validator

## Quality Expectations

- All 11+ seam_validator business rules enforced
- Hypothesis priority ordering preserved (instrumentation first, behavior last)
- AI adoption trap correctly identified (not flagged as regression)
- Mix-shift considered when detected
