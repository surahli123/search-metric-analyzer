"""Search Metric Analyzer — Python Analysis Toolkit.

Tools are designed to be called as CLI scripts by Claude Code.
Each tool reads input (CSV/JSON), performs analysis, and outputs JSON to stdout.
"""

from tools.connector_investigator import ConnectorInvestigator

__all__ = ["ConnectorInvestigator"]
