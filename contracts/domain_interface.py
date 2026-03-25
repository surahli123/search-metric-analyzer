"""Domain interface protocol — the contract between orchestrator and domain modules.

WHY A PROTOCOL:
The orchestrator needs to call domain-specific logic (prompts, knowledge, rules)
without importing domain modules directly. A Protocol defines the shape of any
domain module — the orchestrator depends on the Protocol, not the implementation.

Think of it like an API contract: the orchestrator says "I need these methods,"
and each domain module (search_metrics, data_analysis) implements them differently.

USAGE:
    from contracts.domain_interface import DomainInterface

    class MyDomain:
        name = "my_domain"
        def get_knowledge(self, query, stage="", token_budget=1500): ...
        # ... other methods

    # Type checking: isinstance won't work with Protocol, but mypy validates it.
    # At runtime, we use structural subtyping — if it has the right methods, it works.

ENRICHED KNOWLEDGE API:
    get_knowledge(query, stage, token_budget) — the stage and token_budget params
    enable domain-specific routing. For search_metrics, this means the manifest.yaml
    routing table can return different knowledge per pipeline stage. For simpler
    domains (data_analysis), these params can be ignored.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class DomainInterface(Protocol):
    """What every domain module must provide.

    Each method maps to a concern the orchestrator delegates to the domain:
    - parse_question: understand what the user is asking (domain-specific NLP)
    - get_prompts: provide LLM prompt templates for each pipeline stage
    - get_quality_rules: provide domain-specific validation rules
    - get_knowledge: retrieve relevant domain knowledge for context injection
    - get_agents: provide agent definitions for DISPATCH stage
    """

    @property
    def name(self) -> str:
        """Unique identifier for this domain (e.g., 'search_metrics', 'data_analysis')."""
        ...

    def parse_question(self, raw_question: str) -> Dict[str, Any]:
        """Extract structured intent from a natural language question.

        Returns a dict that can be used to populate a QuestionBrief.
        Domain-specific: search_metrics extracts metric names and time ranges,
        data_analysis might extract table names and aggregation types.
        """
        ...

    def get_prompts(self, stage: str) -> Dict[str, Callable]:
        """Return prompt builder functions for a pipeline stage.

        Args:
            stage: Pipeline stage name ('hypothesize', 'dispatch', 'synthesize').

        Returns:
            Dict mapping prompt role to builder function. Expected keys vary
            by stage but typically include 'system_prompt' and 'user_prompt'.
        """
        ...

    def get_quality_rules(self) -> List[Dict[str, Any]]:
        """Return domain-specific quality gate rules.

        Each rule dict has:
        - 'name': str — rule identifier (e.g., 'hypotheses_consistent_with_co_movement')
        - 'stage': str — which pipeline stage this rule applies to
        - 'check': Callable — function(result_dict) -> List[str] (violation messages)

        These rules are registered with seam_validator alongside generic rules.
        """
        ...

    def get_knowledge(
        self, query: str, stage: str = "", token_budget: int = 1500
    ) -> str:
        """Retrieve relevant domain knowledge for context injection.

        Args:
            query: What knowledge is needed (e.g., 'co_movement_patterns',
                   'metric_definitions', or a free-text question).
            stage: Current pipeline stage — enables stage-specific routing.
                   For search_metrics, different stages need different YAMLs.
                   Simpler domains can ignore this parameter.
            token_budget: Approximate max tokens for the returned knowledge.
                         Prevents context bloat in LLM prompts.

        Returns:
            Knowledge text suitable for injection into an LLM prompt.
        """
        ...

    def get_agents(self) -> Dict[str, Any]:
        """Return agent definitions for the DISPATCH stage.

        Returns:
            Dict with:
            - 'registry': parsed registry.yaml content (agent metadata + deps)
            - 'agents_dir': Path to the directory containing agent .md files
        """
        ...
