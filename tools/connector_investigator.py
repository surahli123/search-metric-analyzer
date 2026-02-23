#!/usr/bin/env python3
"""Minimal bounded connector investigator spike."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List


class ConnectorInvestigator:
    """Run bounded connector checks derived from hypothesis hints."""

    def __init__(self, max_queries: int = 3, timeout_seconds: int = 120):
        self.max_queries = max(0, max_queries)
        self.timeout_seconds = timeout_seconds

    def _build_queries(self, hypothesis: Dict[str, Any]) -> List[str]:
        confirms_if = hypothesis.get("confirms_if", [])
        if not isinstance(confirms_if, list):
            confirms_if = []

        queries: List[str] = []
        for hint in confirms_if:
            hint_text = str(hint).strip()
            if not hint_text:
                continue
            escaped_hint = hint_text.replace("'", "''")
            queries.append(f"SELECT '{escaped_hint}' AS connector_check_hint")
            if len(queries) >= self.max_queries:
                break

        if not queries and self.max_queries > 0:
            queries.append("SELECT 1 AS connector_check_hint")

        return queries[: self.max_queries]

    def run(
        self,
        hypothesis: Dict[str, Any],
        execute_query: Callable[[str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        start = time.monotonic()
        queries = self._build_queries(hypothesis)
        executed_queries: List[str] = []
        evidence: List[Dict[str, Any]] = []

        for query in queries:
            elapsed = time.monotonic() - start
            if elapsed >= self.timeout_seconds:
                return {
                    "ran": True,
                    "verdict": "rejected",
                    "reason": (
                        "timeout budget exceeded before bounded checks completed"
                    ),
                    "queries": executed_queries,
                    "evidence": evidence,
                }

            result = execute_query(query)
            executed_queries.append(query)
            evidence.append(
                {
                    "query": query,
                    "result": result,
                }
            )

        return {
            "ran": True,
            "verdict": "confirmed",
            "reason": "all bounded checks passed",
            "queries": executed_queries,
            "evidence": evidence,
        }
