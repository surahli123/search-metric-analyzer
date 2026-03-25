"""Search Metrics domain — DomainInterface implementation for Enterprise Search diagnosis.

This is the first domain module. It wraps all search-specific logic that was
previously scattered across harness/, agents/, and data/knowledge/.

WHAT THIS MODULE OWNS:
- prompts.py: LLM prompt builders for HYPOTHESIZE, DISPATCH, SYNTHESIZE stages
- knowledge/: 6 YAML files (metric definitions, patterns, pipeline, tradeoffs, eval, corrections)
- agents/: 10 agent .md files + registry.yaml
- rules.py: search-specific quality gate rules (populated in Wave 7A.2)

HOW THE ORCHESTRATOR USES THIS:
(Wave 7A.2 — currently the orchestrator still calls these directly)
    domain = get_domain("search_metrics")
    prompts = domain.get_prompts("hypothesize")
    knowledge = domain.get_knowledge("co_movement_patterns", stage="hypothesize")
    rules = domain.get_quality_rules()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

import yaml


# ---------------------------------------------------------------------------
# Path constants — all paths relative to this file's location
# ---------------------------------------------------------------------------

# domains/search_metrics/__init__.py -> domains/search_metrics/
_DOMAIN_DIR = Path(__file__).resolve().parent

# Knowledge YAMLs live alongside this module
_KNOWLEDGE_DIR = _DOMAIN_DIR / "knowledge"

# Agent definitions (10 .md files + registry.yaml)
_AGENTS_DIR = _DOMAIN_DIR / "agents"


class SearchMetricsDomain:
    """DomainInterface implementation for enterprise search metric diagnosis.

    This domain handles metric movements in Enterprise Search platforms
    (like Glean). Key concepts: Click Quality, Search Quality Success,
    AI Trigger/Success, co-movement patterns, mix-shift, tenant tiers.
    """

    @property
    def name(self) -> str:
        return "search_metrics"

    def parse_question(self, raw_question: str) -> Dict[str, Any]:
        """Extract structured intent from a search metric question.

        Currently delegates to harness/question_parser.py — will be moved
        here in Wave 7A.2 when the orchestrator starts using domain.parse_question().

        Raises:
            NotImplementedError: Until Wave 7A.2 completes the delegation.
        """
        # TODO(Wave 7A.2): Move question_parser logic here
        raise NotImplementedError(
            "parse_question() delegation not yet implemented. "
            "The orchestrator still calls harness/question_parser.py directly."
        )

    def get_prompts(self, stage: str) -> Dict[str, Callable]:
        """Return prompt builder functions for a pipeline stage.

        Args:
            stage: One of 'hypothesize', 'dispatch', 'synthesize'.

        Returns:
            Dict mapping prompt role to builder function.
            Keys depend on the stage — see each stage's implementation.
        """
        # Import here to avoid circular imports at module load time.
        # The prompts module is self-contained (no imports from harness/).
        from domains.search_metrics.prompts import (
            build_hypothesize_system_prompt,
            build_hypothesize_user_prompt,
            normalize_hypothesis_set,
            build_dispatch_system_prompt,
            build_dispatch_user_prompt,
            build_synthesize_system_prompt,
            build_synthesize_user_prompt,
            build_synthesize_retry_prompt,
            normalize_synthesis_report,
        )

        stage_prompts = {
            "hypothesize": {
                "system_prompt": build_hypothesize_system_prompt,
                "user_prompt": build_hypothesize_user_prompt,
                "normalize": normalize_hypothesis_set,
            },
            "dispatch": {
                "system_prompt": build_dispatch_system_prompt,
                "user_prompt": build_dispatch_user_prompt,
            },
            "synthesize": {
                "system_prompt": build_synthesize_system_prompt,
                "user_prompt": build_synthesize_user_prompt,
                "retry_prompt": build_synthesize_retry_prompt,
                "normalize": normalize_synthesis_report,
            },
        }

        if stage not in stage_prompts:
            raise ValueError(
                f"Unknown stage '{stage}'. Valid stages: {list(stage_prompts.keys())}"
            )

        return stage_prompts[stage]

    def get_quality_rules(self) -> List[Dict[str, Any]]:
        """Return search-specific quality gate rules.

        These rules enforce domain invariants like:
        - AI adoption trap detection (CQ↓ + AI↑ = expected, not regression)
        - Mix-shift consideration when contribution > 25%
        - Effect size proportionality for P0 severity
        - Search-specific question type validation

        Returns:
            List of rule dicts, each with 'name', 'stage', and 'check' keys.
        """
        from domains.search_metrics.rules import SEARCH_METRIC_RULES
        return SEARCH_METRIC_RULES

    def get_knowledge(
        self, query: str, stage: str = "", token_budget: int = 1500
    ) -> str:
        """Retrieve search metric domain knowledge for context injection.

        Uses the manifest.yaml routing table to select the right knowledge
        files and sections for the given stage. This is the enriched API
        (query + stage + token_budget) from the eng review.

        Args:
            query: What knowledge is needed (e.g., 'co_movement_patterns').
            stage: Current pipeline stage — routes to different YAML files.
            token_budget: Max approximate tokens to return.

        Returns:
            Knowledge text suitable for LLM prompt injection.
        """
        # For now, load the manifest and return knowledge for the given stage.
        # This is a simplified implementation — Wave 7A.2 will integrate
        # with the existing knowledge routing logic more deeply.
        manifest_path = _DOMAIN_DIR.parent.parent / "harness" / "manifest.yaml"

        if not manifest_path.exists():
            return f"[No manifest found at {manifest_path}]"

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        routes = manifest.get("routes", {})

        # Determine which route to use — prefer stage, fall back to query
        route_key = stage if stage in routes else query
        if route_key not in routes:
            return f"[No knowledge route for stage='{stage}', query='{query}']"

        route = routes[route_key]
        knowledge_files = route.get("knowledge_files", [])

        # Load and concatenate knowledge from each file
        parts = []
        for file_spec in knowledge_files:
            file_path = _DOMAIN_DIR.parent.parent / file_spec["path"]
            if not file_path.exists():
                parts.append(f"[Missing: {file_spec['path']}]")
                continue

            with open(file_path) as f:
                content = yaml.safe_load(f)

            # If sections are specified, extract only those
            sections = file_spec.get("sections", [])
            if sections and isinstance(content, dict):
                for section in sections:
                    if section in content:
                        parts.append(
                            yaml.dump({section: content[section]}, default_flow_style=False)
                        )
            else:
                parts.append(yaml.dump(content, default_flow_style=False))

        return "\n---\n".join(parts)

    def get_agents(self) -> Dict[str, Any]:
        """Return agent definitions for the DISPATCH stage.

        Returns:
            Dict with:
            - 'registry_path': Path to the agents registry.yaml
            - 'agents_dir': Path to the directory containing agent .md files
        """
        return {
            "registry_path": str(_AGENTS_DIR / "registry.yaml"),
            "agents_dir": str(_AGENTS_DIR),
        }

    # -----------------------------------------------------------------------
    # Convenience: knowledge directory path for core tools that need it
    # -----------------------------------------------------------------------

    @property
    def knowledge_dir(self) -> Path:
        """Path to this domain's knowledge YAML directory.

        Used by core tools (anomaly.py, corrections.py) that need to resolve
        knowledge file paths. The core tools accept a path parameter — this
        property provides the domain-specific path to pass in.
        """
        return _KNOWLEDGE_DIR
