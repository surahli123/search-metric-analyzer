"""Trace module for Search Metric Analyzer v2.

Provides investigation tracing with dual-audience design:
- human_summary: for DS/eng reviewing why the system reached a conclusion
- agent_context: for downstream LLM agents reasoning about prior stages

The trace system captures 4 IC9 "Invisible Decisions":
1. metric_direction — which way did the metric move? (UNDERSTAND)
2. hypothesis_inclusion — which hypotheses were kept/dropped? (HYPOTHESIZE)
3. context_construction — what context was given to sub-agents? (DISPATCH)
4. narrative_selection — which narrative framing was chosen? (SYNTHESIZE)
"""

from trace.span import TraceSpan, SeamSpan
from trace.collector import InvestigationTrace
