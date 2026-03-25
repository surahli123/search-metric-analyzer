"""Tests for DomainInterface Protocol and SearchMetricsDomain implementation.

Validates that:
1. SearchMetricsDomain satisfies the DomainInterface Protocol (runtime_checkable)
2. All methods return the expected types
3. Domain registration and lookup work correctly
4. Knowledge routing returns non-empty content for valid stages
5. Prompt builders are callable and return the right structure
"""

import pytest
from pathlib import Path

from contracts.domain_interface import DomainInterface
from domains import register_domain, get_domain, list_domains, _reset_registry
from domains.search_metrics import SearchMetricsDomain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registry():
    """Reset domain registry before each test to avoid cross-test contamination."""
    _reset_registry()
    yield
    _reset_registry()


@pytest.fixture
def domain():
    """Create a SearchMetricsDomain instance."""
    return SearchMetricsDomain()


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    """Verify SearchMetricsDomain satisfies DomainInterface Protocol."""

    def test_isinstance_check(self, domain):
        """runtime_checkable Protocol should pass isinstance."""
        assert isinstance(domain, DomainInterface)

    def test_name_property(self, domain):
        assert domain.name == "search_metrics"

    def test_has_parse_question(self, domain):
        assert hasattr(domain, "parse_question")
        assert callable(domain.parse_question)

    def test_has_get_prompts(self, domain):
        assert hasattr(domain, "get_prompts")
        assert callable(domain.get_prompts)

    def test_has_get_quality_rules(self, domain):
        assert hasattr(domain, "get_quality_rules")
        assert callable(domain.get_quality_rules)

    def test_has_get_knowledge(self, domain):
        assert hasattr(domain, "get_knowledge")
        assert callable(domain.get_knowledge)

    def test_has_get_agents(self, domain):
        assert hasattr(domain, "get_agents")
        assert callable(domain.get_agents)


# ---------------------------------------------------------------------------
# Domain registry
# ---------------------------------------------------------------------------

class TestDomainRegistry:
    """Test domain registration and lookup."""

    def test_register_and_lookup(self, domain):
        register_domain(domain)
        retrieved = get_domain("search_metrics")
        assert retrieved is domain

    def test_list_domains_empty(self):
        assert list_domains() == []

    def test_list_domains_after_register(self, domain):
        register_domain(domain)
        assert list_domains() == ["search_metrics"]

    def test_duplicate_registration_raises(self, domain):
        register_domain(domain)
        with pytest.raises(ValueError, match="already registered"):
            register_domain(domain)

    def test_unknown_domain_raises(self):
        with pytest.raises(KeyError, match="not found"):
            get_domain("nonexistent_domain")

    def test_reset_clears_registry(self, domain):
        register_domain(domain)
        assert len(list_domains()) == 1
        _reset_registry()
        assert len(list_domains()) == 0


# ---------------------------------------------------------------------------
# get_prompts
# ---------------------------------------------------------------------------

class TestGetPrompts:
    """Test prompt retrieval for each pipeline stage."""

    def test_hypothesize_prompts(self, domain):
        prompts = domain.get_prompts("hypothesize")
        assert "system_prompt" in prompts
        assert "user_prompt" in prompts
        assert "normalize" in prompts
        # Verify they're callable
        assert callable(prompts["system_prompt"])
        assert callable(prompts["user_prompt"])
        assert callable(prompts["normalize"])

    def test_dispatch_prompts(self, domain):
        prompts = domain.get_prompts("dispatch")
        assert "system_prompt" in prompts
        assert "user_prompt" in prompts
        assert callable(prompts["system_prompt"])

    def test_synthesize_prompts(self, domain):
        prompts = domain.get_prompts("synthesize")
        assert "system_prompt" in prompts
        assert "user_prompt" in prompts
        assert "retry_prompt" in prompts
        assert "normalize" in prompts

    def test_unknown_stage_raises(self, domain):
        with pytest.raises(ValueError, match="Unknown stage"):
            domain.get_prompts("nonexistent_stage")

    def test_hypothesize_system_prompt_content(self, domain):
        """System prompt should mention the AI adoption trap domain rule."""
        prompts = domain.get_prompts("hypothesize")
        system_prompt = prompts["system_prompt"]()
        assert "AI" in system_prompt or "ai" in system_prompt
        assert "hypothesis" in system_prompt.lower()


# ---------------------------------------------------------------------------
# get_knowledge
# ---------------------------------------------------------------------------

class TestGetKnowledge:
    """Test knowledge retrieval for different stages."""

    def test_understand_stage_returns_content(self, domain):
        """UNDERSTAND stage should load metric definitions + historical patterns."""
        knowledge = domain.get_knowledge("metric_defs", stage="understand")
        assert len(knowledge) > 100  # Non-trivial content
        assert "---" in knowledge or "metric" in knowledge.lower()

    def test_hypothesize_stage_returns_content(self, domain):
        knowledge = domain.get_knowledge("co_movement", stage="hypothesize")
        assert len(knowledge) > 50

    def test_unknown_stage_returns_message(self, domain):
        """Unknown stage should return a descriptive message, not crash."""
        knowledge = domain.get_knowledge("anything", stage="nonexistent")
        assert "No knowledge route" in knowledge

    def test_token_budget_parameter_accepted(self, domain):
        """get_knowledge should accept token_budget without error."""
        # Doesn't enforce budget yet, but shouldn't raise
        knowledge = domain.get_knowledge("test", stage="understand", token_budget=500)
        assert isinstance(knowledge, str)


# ---------------------------------------------------------------------------
# get_quality_rules
# ---------------------------------------------------------------------------

class TestGetQualityRules:
    """Test quality rule retrieval — populated with search-specific rules."""

    def test_returns_list(self, domain):
        rules = domain.get_quality_rules()
        assert isinstance(rules, list)

    def test_returns_four_search_rules(self, domain):
        """4 search-specific rules extracted from seam_validator."""
        rules = domain.get_quality_rules()
        assert len(rules) == 4

    def test_rules_have_required_keys(self, domain):
        """Each rule dict must have name, stage, and check."""
        for rule in domain.get_quality_rules():
            assert "name" in rule
            assert "stage" in rule
            assert "check" in rule
            assert callable(rule["check"])

    def test_rule_names(self, domain):
        """Verify the expected rule names are present."""
        names = {r["name"] for r in domain.get_quality_rules()}
        assert "question_brief_valid" in names
        assert "hypotheses_consistent_with_co_movement" in names
        assert "mix_shift_considered_when_detected" in names
        assert "effect_size_proportionality" in names

    def test_rules_cover_multiple_stages(self, domain):
        """Rules should span QUESTION_PARSE, HYPOTHESIZE, and SYNTHESIZE."""
        stages = {r["stage"] for r in domain.get_quality_rules()}
        assert "QUESTION_PARSE" in stages
        assert "HYPOTHESIZE" in stages
        assert "SYNTHESIZE" in stages


# ---------------------------------------------------------------------------
# get_agents
# ---------------------------------------------------------------------------

class TestGetAgents:
    """Test agent definition retrieval."""

    def test_returns_dict_with_required_keys(self, domain):
        agents = domain.get_agents()
        assert "registry_path" in agents
        assert "agents_dir" in agents

    def test_registry_path_exists(self, domain):
        agents = domain.get_agents()
        assert Path(agents["registry_path"]).exists()

    def test_agents_dir_exists(self, domain):
        agents = domain.get_agents()
        assert Path(agents["agents_dir"]).is_dir()

    def test_agents_dir_has_md_files(self, domain):
        agents = domain.get_agents()
        agents_dir = Path(agents["agents_dir"])
        md_files = list(agents_dir.glob("*.md"))
        assert len(md_files) >= 7  # At least 7 agent .md files


# ---------------------------------------------------------------------------
# parse_question (stub for 7A.1)
# ---------------------------------------------------------------------------

class TestParseQuestion:
    """parse_question is a stub in 7A.1 — verify it raises NotImplementedError."""

    def test_raises_not_implemented(self, domain):
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            domain.parse_question("Why did click quality drop?")


# ---------------------------------------------------------------------------
# knowledge_dir property
# ---------------------------------------------------------------------------

class TestKnowledgeDir:
    """Test the convenience knowledge_dir property."""

    def test_knowledge_dir_is_path(self, domain):
        assert isinstance(domain.knowledge_dir, Path)

    def test_knowledge_dir_exists(self, domain):
        assert domain.knowledge_dir.exists()

    def test_knowledge_dir_has_yaml_files(self, domain):
        yaml_files = list(domain.knowledge_dir.glob("*.yaml"))
        assert len(yaml_files) == 6  # 6 knowledge YAML files
