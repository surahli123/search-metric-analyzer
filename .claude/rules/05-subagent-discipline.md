# Subagent Discipline

## Pre-Dispatch Scoping — Required Fields

Every subagent prompt MUST include all five fields. No exceptions.

| Field | What to include | Example |
|-------|----------------|---------|
| **Goal** | What to accomplish (1-2 sentences) | "Add circuit breaker timeout config to DAGExecutor" |
| **Owns** | Files/directories the subagent may modify | `harness/dag_executor.py`, `tests/test_dag_executor.py` |
| **Must not touch** | Off-limits files/layers | `core/`, `contracts/`, `web/` |
| **Conventions** | Patterns to follow | "Heavy comments explaining WHY, small functions, test file = `tests/test_<module>.py`" |
| **Verify** | How to prove the work before returning | `pytest tests/test_dag_executor.py -v` |

If you can't fill all five fields, the task isn't scoped well enough to delegate.

## Layer Ownership Shortcuts

Derived from `02-architecture-boundaries.md`. Use these as defaults for "Must not touch":

| If subagent works in... | Must not touch |
|------------------------|----------------|
| `core/` | `harness/`, `contracts/`, `agents/`, `web/` |
| `contracts/` | `core/`, `harness/`, `agents/`, `web/` |
| `trace/` | `core/`, `contracts/`, `harness/`, `agents/`, `web/` |
| `harness/` | `core/`, `web/` |
| `agents/` | `core/`, `contracts/`, `trace/`, `web/` |
| `web/` | `core/`, `contracts/`, `trace/`, `harness/`, `agents/` |

**Cross-layer tasks** (e.g., adding a new contract field that harness consumes) require explicit justification in the prompt — name both layers, explain why the cross-cutting change is necessary, and list every file in both layers that will be touched.

## Post-Dispatch Protocol — After Every Subagent Completes

Run these four steps in order. Do not skip any.

### 1. Verify persistence
```
git diff          # confirm edits are on disk
grep -r "key_function_or_class" <modified_files>  # confirm key changes exist
```
Subagent reports are not proof — commits and edits can silently fail.

### 2. Run tests
```
pytest tests/test_<module>.py -v    # backend
cd web/frontend && npm test         # frontend (if web/ was touched)
```

### 3. Update memory (conditional)
Save a memory entry IF the subagent revealed:
- A non-obvious codebase pattern or constraint
- A failed approach worth avoiding next time
- A new convention or decision that future sessions need

Do NOT save: routine completions, expected test results, or information derivable from code.

### 4. Note silent failures
If the subagent reported success but verification (step 1) shows missing changes → save a feedback memory with the failure mode so it doesn't repeat.

## When NOT to Use Subagents

- Task takes <10 minutes and touches ≤2 files → do it inline
- Task is pure research (reading files, exploring) → use Explore agent (lighter weight)
- Task requires back-and-forth with the user → keep in main thread
