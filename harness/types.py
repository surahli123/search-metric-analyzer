"""Type aliases shared across harness modules.

Centralized here to avoid circular imports — stage modules import from
this file, not from each other or from orchestrator.py.
"""
from typing import Callable

# LLM callable signature: (prompt, system_message, max_tokens) -> response_text
# Every stage that calls the LLM uses this same 3-arg signature.
# Defined here so stage modules can type-hint without importing orchestrator.
LLMCallable = Callable[[str, str, int], str]
