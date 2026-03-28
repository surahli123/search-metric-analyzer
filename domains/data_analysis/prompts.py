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
"""

from __future__ import annotations


# =============================================================================
# HYPOTHESIZE stage prompts — plan SQL approaches
# =============================================================================

def build_hypothesize_system_prompt() -> str:
    """System prompt for HYPOTHESIZE stage.

    Tells the LLM to act as a data analyst who plans SQL queries.
    The LLM receives schema info and a question, and must propose
    1-3 SQL approaches to answer it.
    """
    return (
        "You are a data analyst. Given a question and database schema, "
        "plan 1-3 SQL queries that could answer the question.\n\n"
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
        "- Use ONLY table names listed in the AVAILABLE TABLES section. "
        "Do NOT guess or invent table names.\n"
        "- Use ONLY column names that appear in the schema. "
        "Check the schema carefully before writing SQL.\n"
        "- SQL must be valid DuckDB syntax (similar to SQLite but stricter on types)\n"
        "- For string comparisons with numbers, use CAST: WHERE CAST(col AS INTEGER) > 5\n"
        "- For string literals with apostrophes, use doubled quotes: 'Women''s Soccer' (NOT backslash)\n"
        "- Always qualify column names with table aliases in JOINs to avoid ambiguity\n"
        "- Prefer simple queries (single table) before attempting JOINs\n"
        "- If the question requires aggregation, use appropriate GROUP BY\n"
        "- Generate at least 1 SQL approach, up to 3"
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
    """
    return (
        "You are a data analyst formatting query results as a final answer.\n\n"
        "Given a question and raw SQL query results, extract ONLY the answer values.\n\n"
        "CRITICAL RULES:\n"
        "- Output ONLY the raw values — no column headers, no explanation, no markdown\n"
        "- If the answer is a single number, output just that number on one line\n"
        "- If the answer has multiple values, output one per line, comma-separated if multi-column\n"
        "- Numbers: plain format, full precision (e.g., 60.77956989247312 not 60.78)\n"
        "- Strings: no quotes unless they contain commas\n"
        "- Do NOT include column names or headers — just the data values\n"
        "- Do NOT wrap in markdown code fences\n\n"
        "EXAMPLES:\n"
        "  Question: 'How many events are there?'\n"
        "  Result: total=42\n"
        "  Answer: 42\n\n"
        "  Question: 'List the top 3 cities by population'\n"
        "  Result: NYC 8M, LA 4M, CHI 2.7M\n"
        "  Answer:\n"
        "  NYC,8000000\n"
        "  LA,4000000\n"
        "  CHI,2700000\n\n"
        "  Question: 'What is the average score?'\n"
        "  Result: avg_score=85.5\n"
        "  Answer: 85.5"
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
