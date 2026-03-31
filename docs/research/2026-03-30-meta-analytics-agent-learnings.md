# Meta Analytics Agent — Learnings for SMA/KDD Pipeline

**Source:** [Inside Meta's Home-Grown AI Analytics Agent](https://medium.com/@AnalyticsAtMeta/inside-metas-home-grown-ai-analytics-agent-4ea6779acfb3)

## Key Design Patterns to Adopt

### 1. Iterative Reasoning Loop (highest priority for KDD)

Meta's agent doesn't plan SQL once and execute. It runs a **loop**: write query → execute → inspect results → decide if correct → adjust or re-discover tables → repeat.

**What they do:** The agent checks query results for sanity ("That's strange, the query went back to 2023 but earliest data is 2026"). When results look wrong, it re-discovers tables and tries different approaches autonomously.

**What we do:** We plan SQL once (HYPOTHESIZE), execute, retry on error, try alternatives on failure. But we don't **inspect the result and decide if it makes sense**. We tried a sanity check (step 5e) but the LLM couldn't write corrected SQL.

**The gap:** Meta's agent runs multiple queries in sequence, building understanding. Our pipeline is one-shot: plan → execute → done. The iterative loop is the single biggest architectural difference.

**Actionable for SMA:**
- Change from 2-LLM-call pipeline to N-call iterative loop
- After getting a SQL result, show it to the LLM with the question: "Does this answer the question? If not, what's wrong and what should you query next?"
- Key difference from our failed sanity check: Meta's agent can run *additional* queries to verify (e.g., check table metadata, verify date ranges), not just rewrite the same query
- Allow up to 5 iterations before returning the best answer
- This is the #1 thing that would break through the 52% accuracy ceiling

### 2. Personal Context / "Shared Memory" (medium priority)

Meta's killer feature: offline LLM pipelines process every query an analyst has run to build personalized table descriptions, usage patterns, and column-level documentation.

**What they do:** Before answering, the agent already knows which tables the user cares about and how they use them. 88% of queries use tables from the past 90 days.

**What we do for KDD:** Each task comes with its own tables. No cross-task learning. Every task starts from scratch.

**Actionable for SMA:**
- **KDD immediate:** Build a "task type → SQL pattern" memory. If we've seen "percentage of X with condition Y" before, store the SQL template: `CAST(COUNT(CASE WHEN ... END) AS REAL) * 100 / COUNT(*)`
- **Search metrics:** Our `corrections.yaml` is a primitive version of this. Upgrade to store successful diagnostic patterns, not just corrections.
- **Long term:** For a production data agent, build user-specific context from their query history (exactly Meta's approach)

### 3. Cookbook / Recipe / Ingredient Architecture (medium priority)

Meta separates HOW to analyze (Recipes) from WHAT the data means (Ingredients).

**Direct mapping to SMA:**
| Meta Concept | SMA Equivalent | Status |
|---|---|---|
| Cookbook | Domain (SearchMetricsDomain, DataAnalysisDomain) | Exists |
| Recipe | Stage prompts (hypothesize, synthesize) | Exists but rigid |
| Ingredients - Tables | Schema context (_build_schema_context) | Exists |
| Ingredients - Documentation | knowledge.md per task | Exists |
| Ingredients - Text Snippets | Metric definitions YAML | Exists |
| Ingredients - Memories | corrections.yaml | Exists (primitive) |
| Reference Experts | Not implemented | Gap |
| Custom Validators | Seam validator (contracts/) | Exists |

**Key gap: "Reference Experts"** — Meta lets you point at a colleague's query history. For KDD, this could mean: store the gold SQL patterns from tasks we've solved correctly, and show them as examples for similar new tasks. This is few-shot learning with real examples.

### 4. Show Your Work / Transparency (low priority for accuracy, high for UX)

Every data point accompanied by the SQL that produced it. "Thinking UI" shows planning steps.

**What we do:** trace/ module captures investigation spans, web UI shows them.

**Already covered.** Our trace system is close to Meta's approach.

## What Would Move the Needle Most (Ranked)

### Tier 1: Implement Now

**Iterative SQL reasoning loop** — Transform from 2-call to N-call pipeline:
```
Current:  HYPOTHESIZE → execute → format answer
Proposed: HYPOTHESIZE → execute → INSPECT → (decide: done / adjust query / try different table) → execute → ... → format answer
```

Expected impact: +5-8 accuracy (25→30-33/50). This is exactly what catches task_169 (agent would see 82M and say "that's not a reasonable average monthly consumption").

The image of the Meta agent's iterative loop shows exactly this: Write Query → Execute → Inspect Results → (Wrong query? Adjust / Wrong table? Re-discover) → loop back.

### Tier 2: Build Next

**SQL pattern memory** — Store successful SQL patterns by question type:
- "percentage of X" → `CAST(COUNT(CASE WHEN ... END) AS REAL) * 100 / COUNT(*)`
- "average monthly X" → `SUM(X) / 12` or `AVG(X) GROUP BY month`
- "how many times more" → `A / B` (ratio)
- "which X has lowest Y" → `ORDER BY Y ASC LIMIT 1`

Inject 2-3 relevant patterns into HYPOTHESIZE prompt based on question keywords.
Expected impact: +2-3 accuracy on the consistently wrong aggregation tasks.

### Tier 3: Future

**Cross-task learning** — After each batch run, extract patterns from correct answers and store them. "For tasks with `event` + `budget` tables, the correct JOIN is on `link_to_event`". Build a small knowledge base of successful query patterns.

## Key Lessons Validated by Our Experience

| Meta Lesson | Our Evidence |
|---|---|
| "Start with a falsifiable bet" | We validated: code fixes >> prompt tuning via v1-v14 iterations |
| "Personal context is killer" | Our JSON schema fix (showing columns) = +3 completion. Context matters. |
| "Show your work" | Our trace module serves this purpose |
| "Ship early, learn fast" | Weekend prototype → 77% adoption. Our v1→v14 iteration confirms: ship → measure → fix → repeat |
| "The agent is only as good as its domain knowledge" | The 12 consistently wrong tasks fail because the LLM lacks SQL pattern knowledge, not because the pipeline is wrong |

## Implementation Plan

If we adopt the iterative reasoning loop, here's the minimal change:

1. After `_execute_sql_for_task` returns successfully, add a new step:
2. Show the LLM: question + SQL + result + schema
3. Ask: "Does this result answer the question correctly? If yes, return `{"done": true}`. If no, explain what's wrong and provide a new SQL query."
4. If `done=false`, execute the new SQL and repeat (max 3 iterations)
5. Return the final result

**Key difference from our failed sanity check (step 5e):** the iterative loop gives the LLM the full context (schema + previous result) so it can write a fundamentally different query, not just tweak the failed one. Meta's agent runs 4+ queries in the example screenshot.

Cost: ~2-3 extra LLM calls per task on average (tasks that get it right on first try still exit quickly). ~$0.01-0.02/task vs current $0.007/task.
