"""Data Analysis domain — DomainInterface implementation for KDD-style tasks.

This is the second domain module. Unlike SearchMetricsDomain (which is stateless
and uses a manifest routing table for 6 YAML files), DataAnalysisDomain is
task-scoped: it receives a knowledge path and context files at construction time.
A new instance is created per task.

WHAT THIS MODULE OWNS:
- prompts.py: LLM prompt builders for HYPOTHESIZE and SYNTHESIZE stages
- Quality rules: 2 lightweight rules (answer not empty, answer format valid)

WHAT THIS MODULE DOES NOT OWN:
- No knowledge YAML files (knowledge comes from the task directory)
- No agents (DISPATCH is deterministic — runner executes SQL directly)
- No UNDERSTAND stage (runner builds context from data files directly)

HOW IT DIFFERS FROM SearchMetricsDomain:
| Concern      | SearchMetricsDomain          | DataAnalysisDomain            |
|--------------|------------------------------|-------------------------------|
| Lifecycle    | Singleton (stateless)        | Per-task (task-scoped)        |
| Knowledge    | 6 YAML + manifest routing    | Single knowledge.md per task  |
| Prompts      | Search diagnosis prompts     | Text-to-SQL prompts           |
| Quality rules| 4 search-specific rules      | 2 lightweight rules           |
| Agents       | 10 agent .md files           | None (LLM-only pipeline)      |

HOW THE ORCHESTRATOR USES THIS:
    domain = DataAnalysisDomain(
        knowledge_path="/path/to/task/knowledge.md",
        context_files={"csv": [...], "db": [...], "json": [], "md": [...]},
    )
    prompts = domain.get_prompts("hypothesize")
    knowledge = domain.get_knowledge("schema")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class DataAnalysisDomain:
    """DomainInterface implementation for data analysis tasks (e.g., KDD Cup).

    Task-scoped: receives the task's knowledge path and context files at
    construction time. Each task gets its own domain instance, unlike
    SearchMetricsDomain which is a shared singleton.
    """

    # -----------------------------------------------------------------------
    # Construction — task-scoped initialization
    # -----------------------------------------------------------------------

    def __init__(
        self,
        knowledge_path: str = "",
        context_files: Optional[Dict[str, List[str]]] = None,
    ):
        """Initialize a task-scoped data analysis domain.

        Args:
            knowledge_path: Path to the task's knowledge.md file.
                If empty, get_knowledge() returns empty string.
            context_files: Dict mapping file type to list of paths.
                Expected keys: "csv", "db", "json", "md".
                Used by the runner to discover available data files.
                Not used by the domain itself — stored for downstream access.
        """
        self._knowledge_path = knowledge_path
        self._context_files = context_files

    # -----------------------------------------------------------------------
    # DomainInterface implementation
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique identifier for this domain."""
        return "data_analysis"

    @property
    def knowledge_path(self) -> str:
        """Path to this task's knowledge.md file.

        Exposed as a property so the runner can access it after construction.
        """
        return self._knowledge_path

    @property
    def context_files(self) -> Optional[Dict[str, List[str]]]:
        """Discovered data files for this task.

        Exposed as a property so the runner can build schema context from
        the CSV/DB/JSON files discovered in the task directory.
        """
        return self._context_files

    def parse_question(self, raw_question: str) -> Dict[str, Any]:
        """Extract structured intent from a data analysis question.

        For data analysis, questions are self-contained — no NLP extraction
        is needed. We just tag the question type and pass through the raw text.
        The runner and LLM handle the actual question understanding.

        Args:
            raw_question: The natural language question to answer.

        Returns:
            Dict with 'question_type' and 'raw_question'.
        """
        return {
            "question_type": "data_analysis",
            "raw_question": raw_question,
        }

    def get_prompts(self, stage: str) -> Dict[str, Callable]:
        """Return prompt builder functions for a pipeline stage.

        Only HYPOTHESIZE and SYNTHESIZE have prompts:
        - HYPOTHESIZE: Plan SQL queries to answer the question
        - SYNTHESIZE: Format query results as CSV answer

        UNDERSTAND and DISPATCH are not LLM stages for data analysis:
        - UNDERSTAND is skipped (runner builds context directly)
        - DISPATCH is deterministic (runner executes SQL directly)

        Args:
            stage: One of 'hypothesize', 'synthesize'.

        Returns:
            Dict mapping prompt role to builder function.

        Raises:
            ValueError: If stage is not 'hypothesize' or 'synthesize'.
        """
        # Import here to avoid circular imports at module load time.
        # Mirrors the SearchMetricsDomain pattern.
        from domains.data_analysis.prompts import (
            build_hypothesize_system_prompt,
            build_hypothesize_user_prompt,
            build_synthesize_system_prompt,
            build_synthesize_user_prompt,
        )

        stage_prompts: Dict[str, Dict[str, Callable]] = {
            "hypothesize": {
                "system_prompt": build_hypothesize_system_prompt,
                "user_prompt": build_hypothesize_user_prompt,
            },
            "synthesize": {
                "system_prompt": build_synthesize_system_prompt,
                "user_prompt": build_synthesize_user_prompt,
            },
        }

        if stage not in stage_prompts:
            raise ValueError(
                f"Unknown stage '{stage}'. "
                f"Valid stages for data_analysis: {list(stage_prompts.keys())}"
            )

        return stage_prompts[stage]

    def get_quality_rules(self) -> List[Dict[str, Any]]:
        """Return lightweight quality gate rules for data analysis.

        Two rules:
        1. rule_answer_not_empty: The synthesis must produce a non-empty answer.
           Without this, the pipeline could silently produce blank output.
        2. rule_answer_format_valid: The answer must have non-whitespace content.
           Catches cases where the LLM returns only whitespace or formatting.

        Returns:
            List of rule dicts, each with 'name', 'stage', and 'check' keys.
        """
        return [
            {
                "name": "rule_answer_not_empty",
                "stage": "SYNTHESIZE",
                "check": _rule_answer_not_empty,
            },
            {
                "name": "rule_answer_format_valid",
                "stage": "SYNTHESIZE",
                "check": _rule_answer_format_valid,
            },
        ]

    def get_knowledge(
        self, query: str, stage: str = "", token_budget: int = 1500
    ) -> str:
        """Retrieve knowledge from this task's knowledge.md file.

        Unlike SearchMetricsDomain (which uses a manifest routing table to
        select from 6 YAML files), DataAnalysisDomain has a single knowledge
        source per task. The query, stage, and token_budget params are accepted
        for protocol compliance but ignored — we always return the full file.

        Args:
            query: Accepted for protocol compliance (ignored).
            stage: Accepted for protocol compliance (ignored).
            token_budget: Accepted for protocol compliance (ignored).

        Returns:
            Content of the knowledge.md file, or empty string if no file.
        """
        if not self._knowledge_path:
            return ""

        path = Path(self._knowledge_path)
        if not path.exists():
            return ""

        return path.read_text(encoding="utf-8")

    def get_agents(self) -> Dict[str, Any]:
        """Return agent definitions for the DISPATCH stage.

        DataAnalysisDomain has no agents — DISPATCH is deterministic.
        The runner executes SQL directly using sql_executor, so no LLM
        agent definitions are needed.

        Returns:
            Dict with empty registry and empty agents_dir.
        """
        return {
            "registry": {},
            "agents_dir": "",
        }


# ---------------------------------------------------------------------------
# Quality rules — private to this module
# ---------------------------------------------------------------------------
# These follow the same signature as search_metrics/rules.py:
#     rule_fn(result: dict, **kwargs) -> Optional[str]
#     Returns None if the rule passes, or a violation string if it fails.
# ---------------------------------------------------------------------------

def _rule_answer_not_empty(result: Dict[str, Any], **kwargs) -> Optional[str]:
    """Check that the synthesis produced a non-empty answer.

    WHY THIS RULE:
    The pipeline can silently produce empty output if the LLM fails to
    generate an answer or the SQL returned no rows. An empty answer is
    always wrong — better to flag it and retry or report the failure.
    """
    answer = result.get("answer", "")
    if not answer:
        return (
            "Synthesis produced an empty answer. "
            "The pipeline must produce a non-empty response."
        )
    return None


def _rule_answer_format_valid(result: Dict[str, Any], **kwargs) -> Optional[str]:
    """Check that the answer has parseable non-whitespace content.

    WHY THIS RULE:
    The LLM sometimes returns only whitespace, markdown formatting, or
    code fences without actual data. The answer must contain at least one
    line of non-whitespace content to be considered valid.
    """
    answer = result.get("answer", "")
    # Strip whitespace and check if anything remains
    stripped = answer.strip()
    if not stripped:
        return (
            "Answer contains only whitespace or is empty. "
            "Must contain at least one line of non-whitespace content."
        )
    return None
