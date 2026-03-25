"""Agent registry — loads agent definitions, validates dependencies, builds execution plans.

WHY THIS EXISTS:
As the number of agents grows beyond 3 lead agents, we need a structured way to:
1. Declare which agents exist and what they depend on
2. Validate that the dependency graph is acyclic (no circular dependencies)
3. Build execution plans that respect dependency order and enable parallelism

DESIGN DECISION: Registry is a YAML file (domains/search_metrics/agents/registry.yaml), not code.
Same rationale as the knowledge manifest — declarative config is easier to audit,
review, and modify than Python dictionaries buried in code. The registry schema
is validated at load time, so typos surface immediately.

ANALOGY: Think of this like a DAG scheduler (Airflow, dbt). Each agent is a node,
depends_on declares edges, and build_execution_plan() produces a topological sort
grouped into parallel-safe execution tiers.

CYCLE DETECTION: Uses Kahn's algorithm (BFS-based topological sort).
Why Kahn's over DFS? Kahn's naturally produces the execution order we need AND
detects cycles in the same pass — two birds, one stone. DFS would require a
separate pass to extract the tier grouping.
"""

from __future__ import annotations

import os
import re
from collections import deque
from typing import Any, Dict, List, Optional

import yaml

from trace.helpers import emit_deterministic_span


# =============================================================================
# Required fields for each agent entry in registry.yaml
# =============================================================================

# Every agent MUST have these fields. Optional fields (like depends_on)
# default to empty values if missing.
REQUIRED_AGENT_FIELDS = {"name", "file", "pipeline_step"}

# Valid pipeline steps — accepts both string names and integer step numbers.
# Integer steps (from registry.yaml): 1=understand, 2=hypothesize, 3=dispatch, 4=synthesize
# String steps (legacy): "understand", "hypothesize", "dispatch", "synthesize", "none"
VALID_PIPELINE_STEPS = {
    "understand", "hypothesize", "dispatch", "synthesize", "none",
    1, 2, 3, 4,
}

# Maps integer pipeline steps to string names (for normalization)
STEP_INT_TO_NAME = {1: "understand", 2: "hypothesize", 3: "dispatch", 4: "synthesize"}


# =============================================================================
# load_registry — parse YAML and validate schema
# =============================================================================

def load_registry(path: str) -> Dict[str, Any]:
    """Parse domains/search_metrics/agents/registry.yaml and validate its top-level schema.

    WHY validate here instead of letting callers handle bad data?
    Fail-fast principle: if the registry is malformed, we want to surface
    that immediately at startup rather than getting cryptic KeyErrors
    deep in the pipeline. Same reason search systems validate index schemas
    at build time, not at query time.

    Args:
        path: Path to the registry YAML file.

    Returns:
        Parsed registry dict with an "agents" key containing the agent list.

    Raises:
        FileNotFoundError: If the registry file doesn't exist.
        ValueError: If the YAML is malformed or missing required structure.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Registry file not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    # Guard against empty file or non-dict YAML
    if not isinstance(raw, dict):
        raise ValueError(
            f"Registry must be a YAML mapping, got {type(raw).__name__}. "
            f"Expected top-level key 'agents:' with a list of agent entries."
        )

    if "agents" not in raw:
        raise ValueError(
            "Registry missing required top-level key 'agents'. "
            "The registry must define agents: [...]"
        )

    if not isinstance(raw["agents"], list):
        raise ValueError(
            f"'agents' must be a list, got {type(raw['agents']).__name__}. "
            f"Each entry should be a mapping with name, file, pipeline_step."
        )

    return raw


# =============================================================================
# validate_registry — check all agents for required fields, valid refs, cycles
# =============================================================================

def validate_registry(
    registry: Dict[str, Any],
    base_dir: str = ".",
    trace: Optional[Any] = None,
) -> List[str]:
    """Validate the full registry: schema, file existence, dependency graph.

    Returns a list of validation errors. Empty list = valid registry.
    This follows the "collect all errors" pattern rather than "fail on first" —
    so users can fix everything in one pass instead of playing whack-a-mole.

    Checks performed (in order):
    1. Required fields — every agent has name, file, pipeline_step
    2. Pipeline step validity — pipeline_step is in VALID_PIPELINE_STEPS
    3. Dependency references — all depends_on entries point to existing agents
    4. File existence — agent .md files exist on disk
    5. Cycle detection — dependency graph is a DAG (Kahn's algorithm)

    Args:
        registry: Parsed registry dict from load_registry().
        base_dir: Root directory for resolving relative file paths.
            Defaults to "." (current working directory).
        trace: Optional InvestigationTrace for recording validation results.

    Returns:
        List of human-readable error strings. Empty = valid.
    """
    errors: List[str] = []
    agents = registry.get("agents", [])

    # Build a name set for dependency reference checking.
    # Fix #7: also detect duplicate agent names — two agents with the same name
    # would cause ambiguous dependency references and execution plan errors.
    agent_names = set()
    for agent in agents:
        if isinstance(agent, dict) and "name" in agent:
            name = agent["name"]
            if name in agent_names:
                errors.append(
                    f"Duplicate agent name '{name}' — each agent must have a unique name"
                )
            agent_names.add(name)

    for i, agent in enumerate(agents):
        # --- Check 1: Must be a dict ---
        if not isinstance(agent, dict):
            errors.append(f"Agent at index {i} is not a mapping (got {type(agent).__name__})")
            continue

        agent_name = agent.get("name", f"<unnamed at index {i}>")

        # --- Check 2: Required fields ---
        missing = REQUIRED_AGENT_FIELDS - set(agent.keys())
        if missing:
            errors.append(
                f"Agent '{agent_name}' missing required fields: {sorted(missing)}"
            )

        # --- Check 3: Pipeline step validity ---
        step = agent.get("pipeline_step", "")
        if step and step not in VALID_PIPELINE_STEPS:
            errors.append(
                f"Agent '{agent_name}' has invalid pipeline_step '{step}'. "
                f"Must be one of: {sorted(VALID_PIPELINE_STEPS)}"
            )

        # --- Check 4: Dependency references exist ---
        depends_on = agent.get("depends_on", [])
        if not isinstance(depends_on, list):
            errors.append(
                f"Agent '{agent_name}' depends_on must be a list, "
                f"got {type(depends_on).__name__}"
            )
        else:
            for dep in depends_on:
                if dep not in agent_names:
                    errors.append(
                        f"Agent '{agent_name}' depends on '{dep}' "
                        f"which is not defined in the registry"
                    )

        # --- Check 5: Agent file exists on disk ---
        agent_file = agent.get("file", "")
        if agent_file:
            full_path = os.path.join(base_dir, agent_file)
            if not os.path.isfile(full_path):
                errors.append(
                    f"Agent '{agent_name}' references file '{agent_file}' "
                    f"which does not exist (resolved: {full_path})"
                )

    # --- Check 6: Cycle detection via Kahn's algorithm ---
    cycle_errors = _detect_cycles(agents)
    errors.extend(cycle_errors)

    # --- Emit trace span on validation failure ---
    # Only trace failures — successful validation is the normal path
    # and doesn't need a trace record (same as not logging 200 OK responses).
    if errors and trace is not None:
        emit_deterministic_span(
            trace,
            tool="harness.registry.validate_registry",
            decision="registry_validation",
            value="failed",
            stage="STARTUP",
            human_summary=f"Registry validation failed with {len(errors)} error(s)",
            agent_context=f"errors={errors}",
            outputs={"error_count": len(errors), "errors": errors},
        )

    return errors


# =============================================================================
# _detect_cycles — Kahn's algorithm for topological sort + cycle detection
# =============================================================================

def _detect_cycles(agents: List[Dict[str, Any]]) -> List[str]:
    """Detect cycles in the agent dependency graph using Kahn's algorithm.

    WHY Kahn's algorithm?
    Kahn's is BFS-based topological sort. It processes nodes with zero
    in-degree first (no dependencies), then removes their edges, revealing
    the next tier of processable nodes. If any nodes remain after BFS
    exhausts, those nodes form a cycle.

    This is analogous to how a build system (make, bazel) resolves
    compilation order — you can't compile a module until its dependencies
    are compiled.

    Returns:
        List of error strings. Empty = no cycles (graph is a DAG).
    """
    # Build adjacency list and in-degree map
    # adj[A] = [B, C] means "A must run before B and C"
    # in_degree[B] = 2 means "B depends on 2 other agents"
    agent_names = set()
    adj: Dict[str, List[str]] = {}
    in_degree: Dict[str, int] = {}

    for agent in agents:
        if not isinstance(agent, dict):
            continue
        name = agent.get("name")
        if not name:
            continue
        agent_names.add(name)
        adj.setdefault(name, [])
        in_degree.setdefault(name, 0)

    # Build edges: if B depends_on A, then A → B (A must finish before B starts)
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        name = agent.get("name")
        if not name:
            continue
        for dep in agent.get("depends_on", []):
            if dep in agent_names:
                adj.setdefault(dep, []).append(name)
                in_degree[name] = in_degree.get(name, 0) + 1

    # Kahn's BFS: start with nodes that have zero in-degree (no dependencies)
    queue: deque = deque()
    for name in agent_names:
        if in_degree.get(name, 0) == 0:
            queue.append(name)

    visited_count = 0
    while queue:
        node = queue.popleft()
        visited_count += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # If we didn't visit all nodes, the unvisited ones form cycle(s)
    if visited_count < len(agent_names):
        # Identify which agents are in the cycle (non-zero in-degree remaining)
        cycle_agents = sorted(
            name for name in agent_names
            if in_degree.get(name, 0) > 0
        )
        return [
            f"Dependency cycle detected among agents: {cycle_agents}. "
            f"Break the cycle by removing a depends_on reference."
        ]

    return []


# =============================================================================
# parse_contract — extract CONTRACT block from agent .md files
# =============================================================================

def parse_contract(agent_md_path: str) -> Dict[str, Any]:
    """Extract and parse a CONTRACT block from an agent markdown file.

    Agent .md files can embed structured contract data in HTML comments:

        <!-- CONTRACT_START
        input_schema:
          required: [metric_data, question_brief]
        output_schema:
          required: [findings, confidence]
        CONTRACT_END -->

    WHY HTML comments? They're invisible in rendered markdown but parseable
    by code. This keeps agent files readable as documentation while also
    serving as machine-readable contracts. Same pattern as frontmatter in
    Jekyll/Hugo, but using comments so the contract doesn't render.

    Args:
        agent_md_path: Path to the agent .md file.

    Returns:
        Parsed contract dict. Empty dict if no CONTRACT block found.

    Raises:
        FileNotFoundError: If the .md file doesn't exist.
        ValueError: If CONTRACT block exists but contains invalid YAML.
    """
    if not os.path.isfile(agent_md_path):
        raise FileNotFoundError(f"Agent file not found: {agent_md_path}")

    with open(agent_md_path, "r") as f:
        content = f.read()

    # Pattern: <!-- CONTRACT_START ... CONTRACT_END -->
    # Using re.DOTALL so '.' matches newlines within the block.
    # Fix #10: \r?\n handles both Unix and Windows line endings.
    pattern = r"<!--\s*CONTRACT_START\s*\r?\n(.*?)\r?\nCONTRACT_END\s*-->"
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        # No contract block — not an error, just means this agent
        # doesn't have a machine-readable contract (yet).
        return {}

    contract_yaml = match.group(1)

    try:
        parsed = yaml.safe_load(contract_yaml)
    except yaml.YAMLError as e:
        raise ValueError(
            f"Invalid YAML in CONTRACT block of {agent_md_path}: {e}"
        )

    # Guard against CONTRACT block containing just a string or list
    # instead of a mapping — easy mistake when writing YAML by hand
    if not isinstance(parsed, dict):
        raise ValueError(
            f"CONTRACT block in {agent_md_path} must be a YAML mapping, "
            f"got {type(parsed).__name__}"
        )

    return parsed


# =============================================================================
# build_execution_plan — topological sort grouped by pipeline_step
# =============================================================================

def build_execution_plan(
    registry: Dict[str, Any],
    mode: str = "complex",
    trace: Optional[Any] = None,
) -> List[List[Dict[str, Any]]]:
    """Produce ordered execution steps grouped by pipeline_step.

    The execution plan is a list of tiers. Each tier is a list of agents
    that can run in parallel (same pipeline_step, all dependencies satisfied).
    Tiers execute sequentially; agents within a tier execute in parallel.

    MODES:
    - "simple": Returns empty list — simple mode skips the pipeline entirely.
      The lead-agent-simple handles everything directly via knowledge lookup.
    - "medium": All agents run sequentially — one agent per tier.
      Conservative execution for standard investigations.
    - "complex": Agents grouped by pipeline_step for parallel execution.
      Each pipeline_step becomes a tier; agents in the same step run together.

    ANALOGY: Think of pipeline_step as a MapReduce stage. Within a stage,
    work is parallelized (map phase). Between stages, there's a synchronization
    barrier (shuffle/reduce). Simple mode is like a single-node query that
    skips distributed execution entirely.

    Args:
        registry: Parsed registry dict from load_registry().
        mode: Execution mode — "simple", "medium", or "complex".
        trace: Optional InvestigationTrace for recording the plan.

    Returns:
        List of tiers, where each tier is a list of agent dicts.
        Empty list for "simple" mode (no pipeline execution).
    """
    # --- Simple mode: no pipeline ---
    if mode == "simple":
        return []

    agents = registry.get("agents", [])
    if not agents:
        return []

    # --- Medium mode: sequential execution (one agent per tier) ---
    # WHY sequential for medium? Medium investigations are straightforward
    # enough that parallelism adds complexity without meaningful speedup.
    # Each agent gets the full context window's attention sequentially.
    if mode == "medium":
        # Sort by pipeline_step order to maintain stage progression
        sorted_agents = _sort_by_pipeline_order(agents)
        plan = [[agent] for agent in sorted_agents]

        if trace is not None:
            emit_deterministic_span(
                trace,
                tool="harness.registry.build_execution_plan",
                decision="execution_plan",
                value="medium_sequential",
                stage="STARTUP",
                human_summary=(
                    f"Built sequential execution plan with {len(plan)} steps "
                    f"(medium mode)"
                ),
                agent_context=f"mode=medium, steps={len(plan)}",
            )

        return plan

    # --- Complex mode: group by pipeline_step for parallel tiers ---
    # Agents with the same pipeline_step form a parallel tier.
    # Tiers execute in pipeline_step order: understand → hypothesize → dispatch → synthesize.
    step_groups: Dict[str, List[Dict[str, Any]]] = {}
    for agent in agents:
        step = _normalize_step(agent.get("pipeline_step", "none"))
        step_groups.setdefault(step, []).append(agent)

    # Build tiers in pipeline order (skip "none" — those agents aren't in the pipeline)
    pipeline_order = ["understand", "hypothesize", "dispatch", "synthesize"]
    plan: List[List[Dict[str, Any]]] = []

    for step in pipeline_order:
        group = step_groups.get(step, [])
        if group:
            plan.append(group)

    if trace is not None:
        tier_summary = [
            f"{step}: {len(step_groups.get(step, []))} agent(s)"
            for step in pipeline_order
            if step_groups.get(step)
        ]
        emit_deterministic_span(
            trace,
            tool="harness.registry.build_execution_plan",
            decision="execution_plan",
            value="complex_parallel",
            stage="STARTUP",
            human_summary=(
                f"Built parallel execution plan with {len(plan)} tiers "
                f"(complex mode): {', '.join(tier_summary)}"
            ),
            agent_context=f"mode=complex, tiers={len(plan)}, breakdown={tier_summary}",
        )

    return plan


# =============================================================================
# _sort_by_pipeline_order — deterministic ordering for sequential plans
# =============================================================================

# Pipeline step → sort priority. Lower number = earlier in the pipeline.
# Agents with unknown steps sort last (shouldn't happen if validation passed).
_STEP_ORDER = {
    "understand": 0, 1: 0,
    "hypothesize": 1, 2: 1,
    "dispatch": 2, 3: 2,
    "synthesize": 3, 4: 3,
    "none": 99,
}


def _normalize_step(step) -> str:
    """Normalize pipeline step to string name (handles int→str conversion)."""
    if isinstance(step, int):
        return STEP_INT_TO_NAME.get(step, "none")
    return str(step)


def _sort_by_pipeline_order(agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort agents by their pipeline_step in stage progression order.

    Agents in the same pipeline_step maintain their original list order
    (stable sort). This ensures deterministic execution order for medium mode.
    """
    return sorted(
        agents,
        key=lambda a: _STEP_ORDER.get(a.get("pipeline_step", "none"), 50),
    )
