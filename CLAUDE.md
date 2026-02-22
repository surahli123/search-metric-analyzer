# Search Metric Analyzer

## Project Context
Enterprise Search metric diagnosis tool. Runs as a Claude Code skill + Python toolkit.
Designed for a team of 2 Senior DSs debugging metric movements for Eng Leads.

## Domain
Enterprise Search (like Glean). Key concepts:
- Tenant tiers (standard/premium/enterprise), AI enablement, connector types
- Metrics: Click Quality, Search Quality Success, AI trigger/success, zero-result rate, latency
- Search Quality Success formula: max(click_component, ai_trigger * ai_success)
- AI answers and Click Quality have INVERSE co-movement (more AI answers = fewer clicks = expected)

## Code Conventions
- Python 3.10+, stdlib + PyYAML only
- Heavy comments explaining WHY, not just WHAT
- Small functions, small files
- All tools are CLI scripts: `python tools/decompose.py --input data.csv`
- Output is always JSON to stdout (Claude Code reads it)

## Key Files
- Design doc: `docs/plans/2026-02-21-search-metric-analyzer-design.md`
- Metric definitions: `data/knowledge/metric_definitions.yaml`
- Historical patterns: `data/knowledge/historical_patterns.yaml`
- Skill file: `skills/search-metric-analyzer.md`

## Testing
Run: `pytest tests/ -v`
All tools have unit tests in `tests/test_<tool>.py`
