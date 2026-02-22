# Search Metric Analyzer — Execution Kickoff Prompt

> Copy everything below the line into a new Claude Code session opened in:
> `/Users/surahli/Documents/New project/Search_Metric_Analyzer/`

---

## Prompt to paste:

```
Load the superpowers:executing-plans skill. You are implementing the Search Metric Analyzer v1.

## What to Read First

1. **Implementation plan:** `docs/plans/2026-02-21-search-metric-analyzer-implementation.md` — this is your task list. Follow it task by task.
2. **Design doc:** `docs/plans/2026-02-21-search-metric-analyzer-design.md` — this is the approved architecture. Do not deviate from it.
3. **Project CLAUDE.md:** `CLAUDE.md` in the project root — code conventions and domain context.
4. **Reference sessions:** `docs/references/` — prior design discussions if you need deeper context on any design decision.

## Execution Workflow

Execute the 10 tasks from the implementation plan in order. At each checkpoint, follow this review protocol:

### After Every Task (mandatory):
1. Run `pytest tests/ -v` to verify all tests pass
2. Dispatch the **code-reviewer** subagent (from `~/.claude/agents/`) to review the code you just wrote. The reviewer should check:
   - Code correctness and edge cases
   - Adherence to project conventions (heavy comments, small functions, JSON output to stdout)
   - Whether the implementation matches the design doc specification
3. Fix any issues the reviewer flags before committing
4. Commit with a descriptive message

### After Tasks 3, 4, 5, 6 (Python tool implementations):
- In addition to code review, dispatch the **test-writer** subagent to:
  - Review existing tests for coverage gaps
  - Propose additional edge-case tests (empty inputs, boundary values, malformed data)
  - Propose integration tests between tools (e.g., decompose output feeds into diagnose)
  - Write the proposed tests and run them

### Tasks 3 & 4 — Run in Parallel:
- decompose.py (Task 3) and anomaly.py (Task 4) have no dependencies on each other
- Use superpowers:dispatching-parallel-agents to implement them simultaneously
- After both complete, run code-reviewer and test-writer on both before proceeding

### Task 7 — Extended Synthetic Data Generator:
- This is the largest task (~600 lines of existing code to modify)
- The existing generator is at `generators/generate_synthetic_data.py` — READ IT FULLY before modifying
- Key changes: add Enterprise dimensions (tenant_tier, ai_enablement, industry_vertical, connector_type), add period column (baseline/current), add scenarios S9-S12
- After implementation, run the generator and verify output with `pytest tests/test_generator.py -v`
- Also run `python tools/decompose.py --input data/synthetic/synthetic_metric_aggregate.csv --metric dlctr_value --dimensions tenant_tier` to verify the generated data works with our analysis tools

### Task 8 — Skill File (Special Handling):
- The skill file at `skills/search-metric-analyzer.md` encodes the diagnostic methodology
- After writing it, DO NOT just code-review it — present the skill file to me for manual review
- This file contains domain expertise that needs human verification
- I will check: hypothesis ordering, validation check thresholds, anti-pattern rules, output format

### Task 9 — Eval Framework (Critical Quality Gate):
- This task requires extra scrutiny. After implementing:
  1. Dispatch code-reviewer for the Python eval runner
  2. Dispatch test-writer for eval runner tests
  3. Then dispatch a SEPARATE review focused specifically on the scoring specs:
     - Are the `must_find` root causes specific enough for LLM-as-judge to evaluate?
     - Are the `must_not_do` anti-patterns testable (not vague)?
     - Do the 3 cases actually cover different investigation archetypes?
     - Is the LLM-as-judge prompt unambiguous?
  4. Present the scoring specs to me for final review

### Task 10 — Integration Test:
- After all tools are implemented, run the full integration test
- Use superpowers:verification-before-completion before claiming done
- Run: `pytest tests/ -v --tb=long` and show me the full output

## Key Domain Context

This is an **Enterprise Search** platform (like Glean). Critical things to know:
- **Tenant tiers** (standard/premium/enterprise) have different metric baselines
- **AI enablement** (ai_on/ai_off) fundamentally changes click behavior — DLCTR drops when AI answers work, and that's GOOD
- **QSR formula:** max(qsr_component_click, sain_trigger * sain_success)
- **Connector types** (Confluence, Slack, GDrive, etc.) each have different failure modes
- **Mix-shift** causes 30-40% of Enterprise Search metric movements — always check it
- **Co-movement diagnostic table** in `data/knowledge/metric_definitions.yaml` is the first thing to check during intake

## Code Quality Standards

- Every Python tool must work as BOTH an importable module AND a CLI script
- All output to stdout must be valid JSON (Claude Code reads it)
- Heavy comments explaining WHY decisions were made
- Small functions (<30 lines), small files (<300 lines)
- Knowledge lives in YAML files, not hardcoded in Python
- Tests use fixtures from `tests/conftest.py` — don't duplicate test data

## Definition of Done (v1)

Do not claim done until:
- [ ] `pytest tests/ -v` shows 0 failures
- [ ] At least 3 scenario types work end-to-end (verify with integration test)
- [ ] Slack message output passes anti-pattern check (no hedging, no data dumps)
- [ ] All 4 validation checks produce correct status for test scenarios
- [ ] Skill file is committed and loadable
- [ ] Code-reviewer has reviewed every task
- [ ] Test-writer has proposed and implemented additional tests for Tasks 3-6
- [ ] Eval scoring specs have been reviewed for rigor
- [ ] All work is committed with descriptive messages
```
