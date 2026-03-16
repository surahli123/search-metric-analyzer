"""Search Metric Analyzer — Orchestration Harness.

Contains the multi-agent orchestrator, connector investigator, LLM factory,
and error hierarchy for production pipeline execution (Mode B).
"""
from harness.connector_investigator import ConnectorInvestigator
from harness.errors import (
    LLMAPIError,
    LLMError,
    LLMParseError,
    OrchestratorError,
    StageError,
)
from harness.llm import extract_json, make_anthropic_llm

__all__ = [
    "ConnectorInvestigator",
    # Error hierarchy
    "LLMAPIError",
    "LLMError",
    "LLMParseError",
    "OrchestratorError",
    "StageError",
    # LLM factory and helpers
    "extract_json",
    "make_anthropic_llm",
]
