# AutoKaggle — Architecture Analysis for SMA/KDD Pipeline

**Source:** https://github.com/ShaneZhong/autokaggle
**Author:** Shane Zhong (colleague) — top 1% (42/4000+) in Kaggle customer churn competition

## Core Architecture: 4-Agent Team

1. **Researcher** — scrapes winning strategies, produces condensed briefs
2. **Builder** — plans experiments, writes self-contained training scripts
3. **Reviewer** — 6-point validation before execution, retrospectives every 10 rounds
4. **Orchestrator** — coordinates via file paths + one-line signals, loops indefinitely

## Key Design Patterns to Adopt

### 1. Structured Reviewer (highest priority)
AutoKaggle's Reviewer does 6-point validation:
- Tunnel vision check
- Forgotten learnings check
- Narrow search space check
- Weak ensemble check
- ROI check
- Campaign retrospective (every 10 rounds)

**Our gap:** Our iterative loop just asks "is this correct?" — too simple.
**Fix:** Replace with a structured validation that checks:
- Does the SQL use the right aggregation for the question type?
- Does the result magnitude make sense given the data?
- Are all tables referenced in the question used in the SQL?
- Does the WHERE clause match the question's filter conditions?

### 2. Persistent Learnings (LEARNINGS.md pattern)
AutoKaggle accumulates generalizable rules across campaigns:
- "Ridge stacking on correlated models hurts LB if correlation > 0.995"
- Each learning is tagged with the round it was discovered

**Our gap:** We have corrections.yaml but it's search-metrics-specific and not updated per KDD run.
**Fix:** Create `kdd/learnings.json` that stores:
- Task patterns that work (question type → SQL pattern → success/fail)
- Common errors (table X doesn't have column Y, use Z instead)
- Updated after each batch run

### 3. Multi-Round Iteration (Orchestrator pattern)
AutoKaggle runs 100+ rounds: Research → Plan → Review → Execute → Learn → Repeat.
Each round takes ~minutes, not hours.

**Our gap:** We run 1 round per task (plan SQL → execute → done).
**Fix:** For hard tasks, run up to 3 "rounds":
- Round 1: Standard pipeline (current)
- Round 2: If wrong, use learnings from Round 1 to retry with different approach
- Round 3: If still wrong, try with maximum context (all schema details + learnings)

### 4. Experiment Registry (experiments.json)
AutoKaggle tracks every experiment: model, CV score, LB score, status.
This enables: "what have we tried?" → avoid repeating failed approaches.

**Our gap:** No tracking of what SQL was tried per task across runs.
**Fix:** Optional — store per-task SQL attempts and results for cross-run learning.

### 5. Context-Lean Communication
AutoKaggle agents communicate via:
- File paths only (not file contents)
- One-line return signals ("DONE", "APPROVED", "CV_SCORE=0.85")
- Shared knowledge files read at startup

**Our alignment:** We already do this partially (SQL result → format → answer).
**Gap:** Our iterative loop passes full context, which causes prompt truncation.

## Implementation Priority

1. **KDD Learnings File** — accumulate task-level learnings across runs
2. **Structured SQL Reviewer** — replace simple "is this correct?" with checklist
3. **Multi-round retry with learnings** — use past failures to improve next attempt
4. **Experiment tracking** — optional, for debugging

## Key Insight

AutoKaggle's power comes from the LOOP, not any single agent. 100+ iterations
with feedback beats 1 perfect attempt. Our pipeline does 1 attempt with retries.
The shift: from "get it right the first time" to "iterate until right."
