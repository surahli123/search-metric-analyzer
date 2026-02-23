# AGENT.md (Search Metric Analyzer)

## Scope
- Applies under `/Users/surahli/Documents/New project/Search_Metric_Analyzer`.
- Inherits global defaults from `/Users/surahli/Documents/New project/AGENT.md`.

## Objective
- Diagnose Search Quality metric movement with reproducible, evidence-backed analysis.

## Required Workflow
1. Run trust/data-quality checks before attribution.
2. Decompose movement by SAIN vs click path and key segments.
3. Prefer multiple hypotheses with uncertainty over forced single-cause claims.
4. Produce reproducible evidence artifacts for handoff.

## Canonical References
- PRD: `/Users/surahli/Documents/New project/Search_Metric_Analyzer/search-quality-metric-diagnosis-agent-prd.md`
- System context: `/Users/surahli/Documents/New project/Search_Metric_Analyzer/search-system-findings-brief.md`
- Synthetic validation spec: `/Users/surahli/Documents/New project/Search_Metric_Analyzer/synthetic-validation-scenarios.md`
- Synthetic runbook: `/Users/surahli/Documents/New project/Search_Metric_Analyzer/README_synthetic_validation.md`

## Release Gate (Synthetic)
- Use the synthetic validation spec as source of truth.
- Do not treat logic as ready unless synthetic acceptance gates in the spec are satisfied.

## Maintenance
- Update this file when domain workflow/constraints change.
- Keep details in the referenced docs; keep this file concise.
