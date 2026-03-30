"""Prompt builders for the DataAnalysisDomain pipeline stages.

WHY SEPARATE FILE:
Mirrors the search_metrics pattern — prompts are pure functions (no side effects).
They take pipeline context in and return formatted strings. The domain class
delegates to these functions; they never call the domain back.

STAGES COVERED:
- HYPOTHESIZE: Plan SQL queries to answer the user's question
- SYNTHESIZE: Format raw query results into CSV answer format

STAGES NOT COVERED:
- UNDERSTAND: Skipped — runner builds context directly from data files
- DISPATCH: Deterministic — runner executes SQL directly, no LLM needed

PARAMETERIZATION (WHY):
The AutoRefine mutation loop needs to swap prompt variables (e.g., schema
emphasis wording, SQL dialect hints, output format rules) without editing
this file. PROMPT_CONFIG is the stable interface between this module and the
mutation loop: the loop calls set_prompt_config() with overrides, runs evals,
then calls reset_prompt_config() to restore defaults before the next mutation.
"""

from __future__ import annotations
import copy


# =============================================================================
# PROMPT_CONFIG — tunable variables for the AutoRefine mutation loop
# =============================================================================
#
# _DEFAULT_PROMPT_CONFIG is the immutable source of truth. PROMPT_CONFIG is the
# mutable working copy that prompt builders read from. The mutation loop calls
# set_prompt_config(overrides) to swap variables and reset_prompt_config() to
# restore defaults. Prompt builders MUST read from PROMPT_CONFIG, never from
# _DEFAULT_PROMPT_CONFIG directly.

_DEFAULT_PROMPT_CONFIG: dict = {
    # --- HYPOTHESIZE stage ---
    # Controls how strongly the prompt warns against hallucinating table names.
    # Mutation idea: softer phrasing, or adding "list available tables first".
    "schema_emphasis": (
        "Use ONLY table names listed in the AVAILABLE TABLES section. "
        "Do NOT guess or invent table names."
    ),
    # DuckDB-specific syntax guidance. Mutation idea: add/remove specific hints,
    # or replace with SQLite hints if the executor changes.
    "sql_dialect_hints": (
        "SQL must be valid DuckDB syntax (similar to SQLite but stricter on types). "
        "For string comparisons with numbers, use CAST: WHERE CAST(col AS INTEGER) > 5. "
        "For string literals with apostrophes, use doubled quotes: "
        "'Women''s Soccer' (NOT backslash). "
        "Always qualify column names with table aliases in JOINs."
    ),
    # Strategy for query complexity. Mutation idea: "attempt JOINs first if
    # the question spans multiple entities" (aggressive) vs current (conservative).
    "approach_strategy": (
        "Prefer simple queries (single table) before attempting JOINs."
    ),
    # How many SQL approaches to generate. Mutation idea: 1 (faster, less
    # diverse) vs 5 (slower, more coverage). 3 is the current sweet spot.
    "max_approaches": 3,

    # --- SYNTHESIZE stage ---
    # Output format instruction. Mutation idea: "TSV format" or "JSON lines".
    "output_format": "CSV format: a header row followed by data rows.",
    # Number precision rule. Mutation idea: "round to 2 decimal places" for
    # tasks where gold.csv uses rounded values.
    "number_format": (
        "Numbers: full precision (e.g., 60.77956989247312 not 60.78)"
    ),
    # Core output constraints. Mutation idea: allow markdown fences if the
    # downstream parser strips them anyway.
    "output_rules": (
        "Output ONLY the CSV content — no explanation, no markdown fences. "
        "Use comma as delimiter."
    ),
}

# Working copy — prompt builders read from this, mutation loop writes to it.
PROMPT_CONFIG: dict = copy.deepcopy(_DEFAULT_PROMPT_CONFIG)


def set_prompt_config(overrides: dict) -> None:
    """Merge overrides into PROMPT_CONFIG (shallow merge, not recursive).

    Called by the AutoRefine mutation loop before running an eval batch.
    Only keys present in _DEFAULT_PROMPT_CONFIG are accepted — unknown keys
    raise KeyError to catch typos early.

    Args:
        overrides: Dict of config keys to override. Values replace existing
                   ones (no deep merge). Example:
                   {"max_approaches": 5, "number_format": "round to 2dp"}
    """
    for key in overrides:
        if key not in _DEFAULT_PROMPT_CONFIG:
            raise KeyError(
                f"Unknown prompt config key: '{key}'. "
                f"Valid keys: {sorted(_DEFAULT_PROMPT_CONFIG.keys())}"
            )
    PROMPT_CONFIG.update(overrides)


def reset_prompt_config() -> None:
    """Restore PROMPT_CONFIG to factory defaults.

    Called by the AutoRefine mutation loop after each eval batch to ensure
    the next mutation starts from a clean baseline — not from the previous
    mutation's state.
    """
    PROMPT_CONFIG.clear()
    PROMPT_CONFIG.update(copy.deepcopy(_DEFAULT_PROMPT_CONFIG))


# =============================================================================
# HYPOTHESIZE stage prompts — plan SQL approaches
# =============================================================================

def build_hypothesize_system_prompt() -> str:
    """System prompt for HYPOTHESIZE stage.

    Tells the LLM to act as a data analyst who plans SQL queries.
    The LLM receives schema info and a question, and must propose
    up to max_approaches SQL approaches to answer it.

    All tunable text fragments are read from PROMPT_CONFIG so the
    AutoRefine mutation loop can swap them without editing this function.
    """
    cfg = PROMPT_CONFIG  # Local alias for readability
    max_n = cfg["max_approaches"]

    return (
        "You are a data analyst. Given a question and database schema, "
        f"plan 1-{max_n} SQL queries that could answer the question.\n\n"
        "For each SQL approach, provide:\n"
        "1. A brief description of the approach\n"
        "2. The SQL query to execute\n"
        "3. Why this approach might work\n\n"
        "Return ONLY a valid JSON object matching this schema:\n"
        "{\n"
        '  "approaches": [\n'
        "    {\n"
        '      "description": "Count all rows in the events table",\n'
        '      "sql": "SELECT COUNT(*) AS total FROM events",\n'
        '      "rationale": "Direct count answers the question"\n'
        "    }\n"
        "  ],\n"
        '  "best_approach_index": 0,\n'
        '  "reasoning": "Why the best approach was chosen"\n'
        "}\n\n"
        "CRITICAL REQUIREMENTS:\n"
        f"- {cfg['schema_emphasis']}\n"
        "- Use ONLY column names that appear in the schema. "
        "Check the schema carefully before writing SQL.\n"
        f"- {cfg['sql_dialect_hints']}\n"
        f"- {cfg['approach_strategy']}\n"
        "- If the question requires aggregation, use appropriate GROUP BY\n"
        "- Read the question carefully for implicit operations:\n"
        "  * 'average monthly X' may need SUM(X)/12 or GROUP BY month\n"
        "  * 'how many times more' means a ratio (A/B), not a difference\n"
        "  * 'percentage' needs CAST(... AS REAL) * 100 / total\n"
        "  * 'lowest cost' needs ORDER BY cost ASC LIMIT 1, not MIN()\n"
        f"- Generate at least 1 SQL approach, up to {max_n}"
    )


def build_hypothesize_user_prompt(
    question: str,
    knowledge: str,
    schema_info: str,
) -> str:
    """User prompt for HYPOTHESIZE stage.

    Provides the LLM with all the context it needs to plan SQL queries:
    the question, any domain knowledge from the task, and the database schema.

    Args:
        question: The natural language question to answer.
        knowledge: Content from the task's knowledge.md file (may be empty).
        schema_info: Database schema (CREATE TABLE statements, CSV headers, etc.).

    Returns:
        Formatted user prompt string.
    """
    sections = []

    # Section 1: The question to answer
    sections.append(f"QUESTION:\n{question}")

    # Section 2: Domain knowledge (context about the data)
    if knowledge:
        sections.append(f"DOMAIN KNOWLEDGE:\n{knowledge}")

    # Section 3: Database schema — the most important context for SQL planning
    sections.append(f"DATABASE SCHEMA:\n{schema_info}")

    # Section 4: Instruction reminder
    sections.append(
        "Plan 1-3 SQL approaches to answer the question. "
        "Use only tables and columns from the schema above."
    )

    return "\n\n".join(sections)


# =============================================================================
# SYNTHESIZE stage prompts — format query results as CSV answer
# =============================================================================

def build_synthesize_system_prompt() -> str:
    """System prompt for SYNTHESIZE stage.

    Tells the LLM to format raw SQL query results into the expected
    CSV answer format (header row + data rows). This is the final step
    before the answer is compared against gold.csv for evaluation.

    All tunable text fragments are read from PROMPT_CONFIG so the
    AutoRefine mutation loop can swap them without editing this function.
    """
    cfg = PROMPT_CONFIG  # Local alias for readability

    return (
        "You are a data analyst formatting query results as a final answer.\n\n"
        "Given a question and raw SQL query results, produce the answer in "
        f"{cfg['output_format']}\n\n"
        "RULES:\n"
        f"- {cfg['output_rules']}\n"
        "- First row is the column header\n"
        "- If the result is a single value, output the column name then the value\n"
        f"- {cfg['number_format']}\n"
        "- Strings: no quotes unless they contain commas\n"
        "- Do NOT wrap in markdown code fences\n\n"
        "EXAMPLES:\n"
        "  Question: 'How many events are there?'\n"
        "  Result: count=42\n"
        "  Answer:\n"
        "  COUNT(*)\n"
        "  42\n\n"
        "  Question: 'List the top 3 cities by population'\n"
        "  Result: NYC 8M, LA 4M, CHI 2.7M\n"
        "  Answer:\n"
        "  city,population\n"
        "  NYC,8000000\n"
        "  LA,4000000\n"
        "  CHI,2700000"
    )


def build_synthesize_user_prompt(
    question: str,
    query_result: str,
) -> str:
    """User prompt for SYNTHESIZE stage.

    Provides the raw query result and the original question so the LLM
    can format the answer correctly. The question is needed because the
    gold.csv format depends on what was asked.

    Args:
        question: The original natural language question.
        query_result: Raw output from SQL execution (may be tabular or scalar).

    Returns:
        Formatted user prompt string.
    """
    sections = []

    sections.append(f"ORIGINAL QUESTION:\n{question}")
    sections.append(f"RAW QUERY RESULT:\n{query_result}")
    sections.append(
        "Format the result above as CSV (header row + data rows). "
        "Output ONLY the CSV content — no explanation."
    )

    return "\n\n".join(sections)
