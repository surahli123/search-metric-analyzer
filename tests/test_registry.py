"""Tests for agent registry — loading, validation, contract parsing, execution plans.

Covers:
- load_registry: YAML parsing, schema validation
- validate_registry: required fields, dependency refs, file existence, cycle detection
- parse_contract: CONTRACT block extraction from .md files
- build_execution_plan: simple/medium/complex mode plans
- Integration: registry.yaml + all agent .md files validate correctly
"""

import os
import tempfile

import pytest
import yaml

from harness.registry import (
    load_registry,
    validate_registry,
    parse_contract,
    build_execution_plan,
    _detect_cycles,
    _normalize_step,
    REQUIRED_AGENT_FIELDS,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# =============================================================================
# load_registry tests
# =============================================================================

class TestLoadRegistry:
    """Tests for YAML parsing and schema validation."""

    def test_loads_project_registry(self):
        """The real registry.yaml loads successfully."""
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "registry.yaml")
        registry = load_registry(path)
        assert "agents" in registry
        assert isinstance(registry["agents"], list)
        assert len(registry["agents"]) == 7  # 7 agents defined

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_registry("/nonexistent/registry.yaml")

    def test_empty_file_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write("")
            f.flush()
            with pytest.raises(ValueError, match="YAML mapping"):
                load_registry(f.name)
        os.unlink(f.name)

    def test_missing_agents_key_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump({"version": 1}, f)
            f.flush()
            with pytest.raises(ValueError, match="missing required.*agents"):
                load_registry(f.name)
        os.unlink(f.name)

    def test_agents_not_list_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump({"agents": "not a list"}, f)
            f.flush()
            with pytest.raises(ValueError, match="must be a list"):
                load_registry(f.name)
        os.unlink(f.name)


# =============================================================================
# validate_registry tests
# =============================================================================

class TestValidateRegistry:
    """Tests for comprehensive registry validation."""

    def test_project_registry_is_valid(self):
        """The real registry validates with zero errors."""
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "registry.yaml")
        registry = load_registry(path)
        errors = validate_registry(registry, base_dir=PROJECT_ROOT)
        assert errors == [], f"Registry validation errors: {errors}"

    def test_missing_required_fields(self):
        registry = {"agents": [{"name": "broken"}]}
        errors = validate_registry(registry)
        assert any("missing required fields" in e for e in errors)

    def test_invalid_dependency_ref(self):
        registry = {"agents": [
            {"name": "a", "file": "a.md", "pipeline_step": 1, "depends_on": ["nonexistent"]},
        ]}
        errors = validate_registry(registry, base_dir="/tmp")
        assert any("nonexistent" in e for e in errors)

    def test_missing_agent_file(self):
        registry = {"agents": [
            {"name": "a", "file": "agents/does_not_exist.md", "pipeline_step": 1},
        ]}
        errors = validate_registry(registry, base_dir="/tmp")
        assert any("does not exist" in e for e in errors)

    def test_non_dict_agent_entry(self):
        registry = {"agents": ["not a dict"]}
        errors = validate_registry(registry)
        assert any("not a mapping" in e for e in errors)

    def test_duplicate_agent_names(self):
        """Fix #7: duplicate agent names produce a validation error."""
        registry = {"agents": [
            {"name": "a", "file": "a.md", "pipeline_step": 1},
            {"name": "a", "file": "b.md", "pipeline_step": 2},
        ]}
        errors = validate_registry(registry, base_dir="/tmp")
        assert any("Duplicate agent name" in e for e in errors)


# =============================================================================
# Cycle detection tests
# =============================================================================

class TestCycleDetection:
    """Tests for Kahn's algorithm cycle detection."""

    def test_no_cycles_in_project_registry(self):
        """The real registry has no cycles."""
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "registry.yaml")
        registry = load_registry(path)
        errors = _detect_cycles(registry["agents"])
        assert errors == []

    def test_simple_cycle_detected(self):
        agents = [
            {"name": "a", "depends_on": ["b"]},
            {"name": "b", "depends_on": ["a"]},
        ]
        errors = _detect_cycles(agents)
        assert len(errors) == 1
        assert "cycle" in errors[0].lower()

    def test_three_node_cycle_detected(self):
        agents = [
            {"name": "a", "depends_on": ["c"]},
            {"name": "b", "depends_on": ["a"]},
            {"name": "c", "depends_on": ["b"]},
        ]
        errors = _detect_cycles(agents)
        assert len(errors) == 1

    def test_dag_with_diamond_no_cycle(self):
        """Diamond dependency (A→B, A→C, B→D, C→D) is not a cycle."""
        agents = [
            {"name": "a", "depends_on": []},
            {"name": "b", "depends_on": ["a"]},
            {"name": "c", "depends_on": ["a"]},
            {"name": "d", "depends_on": ["b", "c"]},
        ]
        errors = _detect_cycles(agents)
        assert errors == []

    def test_self_cycle_detected(self):
        agents = [{"name": "a", "depends_on": ["a"]}]
        errors = _detect_cycles(agents)
        assert len(errors) == 1


# =============================================================================
# parse_contract tests
# =============================================================================

class TestParseContract:
    """Tests for CONTRACT block extraction from .md files."""

    def test_parses_understand_contract(self):
        """The understand.md agent has a parseable CONTRACT block."""
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "understand.md")
        contract = parse_contract(path)
        # Should have a contract (may be empty dict if no block exists)
        assert isinstance(contract, dict)

    def test_parses_all_agent_contracts(self):
        """Every agent .md file can be parsed without errors."""
        agents_dir = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents")
        md_files = [f for f in os.listdir(agents_dir) if f.endswith(".md")]
        for md_file in md_files:
            path = os.path.join(agents_dir, md_file)
            contract = parse_contract(path)
            assert isinstance(contract, dict), f"Failed to parse {md_file}"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_contract("/nonexistent/agent.md")

    def test_no_contract_block_returns_empty(self):
        """File without CONTRACT block returns empty dict (not an error)."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Agent\n\nNo contract here.")
            f.flush()
            result = parse_contract(f.name)
            assert result == {}
        os.unlink(f.name)

    def test_contract_block_parsed_as_yaml(self):
        """CONTRACT block YAML is properly parsed."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(
                "# Agent\n\n"
                "<!-- CONTRACT_START\n"
                "name: test_agent\n"
                "inputs:\n"
                "  - {name: data, type: List, required: true}\n"
                "CONTRACT_END -->\n"
            )
            f.flush()
            result = parse_contract(f.name)
            assert result["name"] == "test_agent"
            assert len(result["inputs"]) == 1
        os.unlink(f.name)

    def test_invalid_yaml_in_contract_raises(self):
        """Invalid YAML in CONTRACT block raises ValueError."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(
                "<!-- CONTRACT_START\n"
                "bad: yaml: [unclosed\n"
                "CONTRACT_END -->\n"
            )
            f.flush()
            with pytest.raises(ValueError, match="Invalid YAML"):
                parse_contract(f.name)
        os.unlink(f.name)


# =============================================================================
# build_execution_plan tests
# =============================================================================

class TestBuildExecutionPlan:
    """Tests for execution plan generation."""

    @pytest.fixture
    def project_registry(self):
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "registry.yaml")
        return load_registry(path)

    def test_simple_mode_returns_empty(self, project_registry):
        """Simple mode skips the pipeline — returns empty plan."""
        plan = build_execution_plan(project_registry, mode="simple")
        assert plan == []

    def test_medium_mode_sequential(self, project_registry):
        """Medium mode: all agents in sequential tiers (one agent per tier)."""
        plan = build_execution_plan(project_registry, mode="medium")
        assert len(plan) > 0
        for tier in plan:
            assert len(tier) == 1  # Sequential: one agent per tier

    def test_complex_mode_parallel_dispatch(self, project_registry):
        """Complex mode: dispatch agents in a single parallel tier."""
        plan = build_execution_plan(project_registry, mode="complex")
        assert len(plan) > 0
        # Find the dispatch tier (step 3 — should have multiple agents)
        dispatch_tiers = [
            tier for tier in plan
            if any(a.get("pipeline_step") == 3 for a in tier)
        ]
        assert len(dispatch_tiers) == 1
        # Dispatch tier should have 4 agents (ranking, connector, ai-quality, sub-agent)
        assert len(dispatch_tiers[0]) == 4

    def test_complex_has_4_tiers(self, project_registry):
        """Complex mode: 4 tiers (understand, hypothesize, dispatch, synthesize)."""
        plan = build_execution_plan(project_registry, mode="complex")
        assert len(plan) == 4

    def test_empty_registry_returns_empty(self):
        plan = build_execution_plan({"agents": []}, mode="complex")
        assert plan == []


# =============================================================================
# _normalize_step tests
# =============================================================================

class TestNormalizeStep:
    """Tests for integer→string step normalization."""

    def test_int_1_to_understand(self):
        assert _normalize_step(1) == "understand"

    def test_int_3_to_dispatch(self):
        assert _normalize_step(3) == "dispatch"

    def test_string_passthrough(self):
        assert _normalize_step("dispatch") == "dispatch"

    def test_unknown_int_to_none(self):
        assert _normalize_step(99) == "none"


# =============================================================================
# Integration: agent count and structure
# =============================================================================

class TestRegistryIntegration:
    """Integration tests verifying registry structure matches expectations."""

    def test_seven_agents_defined(self):
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "registry.yaml")
        registry = load_registry(path)
        assert len(registry["agents"]) == 7

    def test_three_critical_agents(self):
        """3 agents are marked critical: understand, hypothesize, synthesize."""
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "registry.yaml")
        registry = load_registry(path)
        critical = [a for a in registry["agents"] if a.get("critical")]
        assert len(critical) == 3
        critical_names = {a["name"] for a in critical}
        assert critical_names == {"understand", "hypothesize", "synthesize"}

    def test_four_dispatch_agents(self):
        """4 agents in the dispatch stage (pipeline_step=3)."""
        path = os.path.join(PROJECT_ROOT, "domains", "search_metrics", "agents", "registry.yaml")
        registry = load_registry(path)
        dispatch = [a for a in registry["agents"] if a.get("pipeline_step") == 3]
        assert len(dispatch) == 4
