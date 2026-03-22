"""Stage modules for the SearchMetricOrchestrator pipeline.

Each stage is a standalone function that accepts explicit parameters
instead of self. This enables independent testing and keeps the
orchestrator class focused on pipeline coordination.

Stage functions:
- stage_understand: UNDERSTAND — deterministic analysis (no LLM)
- stage_hypothesize: HYPOTHESIZE — LLM generates hypotheses
- stage_dispatch: DISPATCH — sequential hypothesis investigation
- stage_dispatch_parallel: DISPATCH — parallel investigation via DAGExecutor
- stage_synthesize: SYNTHESIZE — LLM produces final report
"""

from harness.stages.understand import stage_understand
from harness.stages.hypothesize import stage_hypothesize
from harness.stages.dispatch import stage_dispatch, stage_dispatch_parallel
from harness.stages.synthesize import stage_synthesize

__all__ = [
    "stage_understand",
    "stage_hypothesize",
    "stage_dispatch",
    "stage_dispatch_parallel",
    "stage_synthesize",
]
