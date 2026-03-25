"""Domain registry — maps domain names to DomainInterface implementations.

HOW IT WORKS:
Each domain module (search_metrics, data_analysis) registers itself when imported.
The orchestrator calls get_domain("search_metrics") to get the right implementation.

This is a simple service locator pattern. We use it instead of dependency injection
because the orchestrator needs to pick a domain dynamically (based on question type
or configuration), not at import time.

USAGE:
    from domains import get_domain, register_domain, list_domains

    # Registration (done by domain module's __init__.py):
    register_domain(SearchMetricsDomain())

    # Lookup (done by orchestrator):
    domain = get_domain("search_metrics")
    knowledge = domain.get_knowledge("co_movement_patterns", stage="hypothesize")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from contracts.domain_interface import DomainInterface


# ---------------------------------------------------------------------------
# Registry — simple dict mapping domain name -> instance
# ---------------------------------------------------------------------------

_DOMAINS: Dict[str, "DomainInterface"] = {}


def register_domain(domain: "DomainInterface") -> None:
    """Register a domain implementation.

    Args:
        domain: An object implementing DomainInterface. Must have a unique 'name'.

    Raises:
        ValueError: If a domain with the same name is already registered.
    """
    if domain.name in _DOMAINS:
        raise ValueError(
            f"Domain '{domain.name}' is already registered. "
            f"Each domain name must be unique."
        )
    _DOMAINS[domain.name] = domain


def get_domain(name: str) -> "DomainInterface":
    """Look up a registered domain by name.

    Args:
        name: Domain identifier (e.g., 'search_metrics', 'data_analysis').

    Returns:
        The registered DomainInterface implementation.

    Raises:
        KeyError: If no domain with that name is registered.
    """
    if name not in _DOMAINS:
        available = list(_DOMAINS.keys()) or ["(none registered)"]
        raise KeyError(
            f"Domain '{name}' not found. Available domains: {available}"
        )
    return _DOMAINS[name]


def list_domains() -> List[str]:
    """Return names of all registered domains."""
    return list(_DOMAINS.keys())


def _reset_registry() -> None:
    """Clear all registered domains. For testing only."""
    _DOMAINS.clear()
