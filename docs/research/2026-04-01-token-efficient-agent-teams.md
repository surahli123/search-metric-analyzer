# Token-Efficient Agent Teams — Design Patterns

**Context:** Discussion from KDD v23 session while cross-learning from AutoKaggle.
Applies to OMC agent teams, Claude Code subagents, and any multi-agent orchestration.

## Why Token Usage Spikes with Agent Teams

Each agent gets the full system prompt + CLAUDE.md + rules + conversation context loaded into its context window. With OMC teams, you're paying that base cost N times (once per worker).

## How to Minimize It

### 1. Context-Lean Communication (AutoKaggle's Pattern)

The most important lesson from AutoKaggle: agents communicate via file paths and one-line signals, never full file contents.

- **Bad:** Send the full schema + question + knowledge to every agent
- **Good:** Write context to a file, send the path, let the agent read only what it needs

### 2. Scoped Subagent Prompts

Our `.claude/rules/05-subagent-discipline.md` already enforces this:
- **Goal:** 1-2 sentences
- **Owns:** specific files only
- **Must not touch:** everything else
- **Verify:** targeted test command

The smaller the prompt, the fewer tokens. Don't send background context the agent doesn't need.

### 3. Use the Right Agent Size

From CLAUDE.md model routing:
- `haiku` for quick lookups, simple tasks
- `sonnet` for standard work
- `opus` only for architecture/deep analysis

Most OMC team workers should be sonnet or haiku, not opus.

### 4. Sequential Over Parallel When Possible

5 parallel agents = 5x the base context cost. If tasks have dependencies, run them sequentially through 1 agent instead. Only parallelize truly independent work.

### 5. Keep CLAUDE.md and Rules Lean

Every byte in CLAUDE.md gets loaded into every agent's context. Our CLAUDE.md is ~250 lines of learnings — that's a lot of tokens multiplied by N agents. Consider moving rarely-needed learnings to memory files that agents don't auto-load.

### 6. The AutoKaggle Formula

- **Orchestrator:** stays context-lean, reads only state.json + results.tsv
- **Workers:** re-spawned every 15 rounds to prevent context overflow
- **Communication:** structured JSON files, not chat history

## Rough Token Math

| Setup | Base Context | Total for 5 Tasks |
|-------|-------------|-------------------|
| Base context (system + CLAUDE.md + rules) | ~15-20K tokens per agent | — |
| 5 parallel agents | ~100K tokens just for base context | ~100K+ |
| Single agent doing 5 sequential tasks | ~20K tokens total | ~20K |

## Bottom Line

Use `1:agent × N tasks` (sequential) instead of `N:agent × 1 task` (parallel) unless the tasks are truly independent and time-critical. This matches the learning already in CLAUDE.md: "OMC teams: 1:agent × N, not N:agent × 1."

## Application to KDD Pipeline

Our batch runner already follows this pattern efficiently:
- Each batch process is a single Python process running 10 tasks sequentially
- 5 parallel batch processes = 5 OS processes (cheap), not 5 LLM agents
- The LLM is called per-task within each process, sharing the connection

For future multi-agent KDD (AutoKaggle-style):
- Orchestrator reads only `state.json` + `results.tsv`
- Researcher/Builder/Reviewer communicate via files in `/tmp/kdd_state/`
- Each agent re-spawned every 15 rounds to prevent context bloat
- Use haiku for Reviewer (structured checklist), sonnet for Builder (SQL generation)
