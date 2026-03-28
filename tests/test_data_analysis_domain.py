"""Tests for DataAnalysisDomain — DomainInterface implementation for KDD-style tasks.

Validates that:
1. DataAnalysisDomain satisfies the DomainInterface Protocol (runtime_checkable)
2. parse_question returns correct shape (question_type + raw_question)
3. get_prompts returns callable builders for hypothesize and synthesize
4. get_quality_rules returns 2 lightweight rules with correct shape
5. get_knowledge reads from knowledge_path and returns content
6. get_knowledge with empty path returns empty string
7. get_agents returns empty registry (no agents for data analysis)
8. Prompt builders return non-empty strings
9. Quality rule checks work correctly on valid/invalid inputs
"""

import os
import pytest
from pathlib import Path

from contracts.domain_interface import DomainInterface
from domains.data_analysis import DataAnalysisDomain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Reuse the existing test fixture knowledge.md
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_KNOWLEDGE_PATH = str(_FIXTURES_DIR / "knowledge.md")


@pytest.fixture
def domain():
    """Create a DataAnalysisDomain with a real knowledge file."""
    return DataAnalysisDomain(
        knowledge_path=_KNOWLEDGE_PATH,
        context_files={
            "csv": [str(_FIXTURES_DIR / "csv" / "attendees.csv")],
            "db": [str(_FIXTURES_DIR / "db" / "events.db")],
            "json": [],
            "md": [_KNOWLEDGE_PATH],
        },
    )


@pytest.fixture
def empty_domain():
    """Create a DataAnalysisDomain with no knowledge path (edge case)."""
    return DataAnalysisDomain()


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    """Verify DataAnalysisDomain satisfies DomainInterface Protocol."""

    def test_isinstance_check(self, domain):
        """runtime_checkable Protocol should pass isinstance."""
        assert isinstance(domain, DomainInterface)

    def test_name_property(self, domain):
        """name should return 'data_analysis'."""
        assert domain.name == "data_analysis"

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
# parse_question
# ---------------------------------------------------------------------------

class TestParseQuestion:
    """parse_question should return a minimal structured dict."""

    def test_returns_correct_shape(self, domain):
        result = domain.parse_question("What is the total attendance?")
        assert isinstance(result, dict)
        assert result["question_type"] == "data_analysis"
        assert result["raw_question"] == "What is the total attendance?"

    def test_preserves_raw_question_exactly(self, domain):
        """Raw question should be stored verbatim, no transformation."""
        raw = "SELECT COUNT(*) FROM events WHERE year > 2020"
        result = domain.parse_question(raw)
        assert result["raw_question"] == raw

    def test_empty_question(self, domain):
        """Empty string should still return the correct shape."""
        result = domain.parse_question("")
        assert result["question_type"] == "data_analysis"
        assert result["raw_question"] == ""


# ---------------------------------------------------------------------------
# get_prompts
# ---------------------------------------------------------------------------

class TestGetPrompts:
    """Test prompt retrieval for hypothesize and synthesize stages."""

    def test_hypothesize_prompts_structure(self, domain):
        prompts = domain.get_prompts("hypothesize")
        assert "system_prompt" in prompts
        assert "user_prompt" in prompts
        assert callable(prompts["system_prompt"])
        assert callable(prompts["user_prompt"])

    def test_synthesize_prompts_structure(self, domain):
        prompts = domain.get_prompts("synthesize")
        assert "system_prompt" in prompts
        assert "user_prompt" in prompts
        assert callable(prompts["system_prompt"])
        assert callable(prompts["user_prompt"])

    def test_unknown_stage_raises(self, domain):
        with pytest.raises(ValueError, match="Unknown stage"):
            domain.get_prompts("nonexistent_stage")

    def test_dispatch_stage_raises(self, domain):
        """DISPATCH is deterministic — no prompts needed, should raise."""
        with pytest.raises(ValueError, match="Unknown stage"):
            domain.get_prompts("dispatch")

    def test_hypothesize_system_prompt_content(self, domain):
        """System prompt should mention SQL and data analysis."""
        prompts = domain.get_prompts("hypothesize")
        system = prompts["system_prompt"]()
        assert isinstance(system, str)
        assert len(system) > 50
        assert "SQL" in system or "sql" in system

    def test_hypothesize_user_prompt_content(self, domain):
        """User prompt should include the question and schema info."""
        prompts = domain.get_prompts("hypothesize")
        user = prompts["user_prompt"](
            question="What is the total attendance?",
            knowledge="Some knowledge about the data",
            schema_info="CREATE TABLE events (id INT, name TEXT)",
        )
        assert isinstance(user, str)
        assert "total attendance" in user
        assert "CREATE TABLE" in user

    def test_synthesize_system_prompt_content(self, domain):
        """System prompt should mention formatting answers as CSV."""
        prompts = domain.get_prompts("synthesize")
        system = prompts["system_prompt"]()
        assert isinstance(system, str)
        assert len(system) > 50
        assert "CSV" in system or "csv" in system

    def test_synthesize_user_prompt_content(self, domain):
        """User prompt should include query result and original question."""
        prompts = domain.get_prompts("synthesize")
        user = prompts["user_prompt"](
            question="What is the total attendance?",
            query_result="total_attendance\n150",
        )
        assert isinstance(user, str)
        assert "total attendance" in user
        assert "150" in user


# ---------------------------------------------------------------------------
# get_quality_rules
# ---------------------------------------------------------------------------

class TestGetQualityRules:
    """Test quality rule retrieval — 2 lightweight rules."""

    def test_returns_list(self, domain):
        rules = domain.get_quality_rules()
        assert isinstance(rules, list)

    def test_returns_two_rules(self, domain):
        """DataAnalysisDomain should have exactly 2 quality rules."""
        rules = domain.get_quality_rules()
        assert len(rules) == 2

    def test_rules_have_required_keys(self, domain):
        """Each rule dict must have name, stage, and check."""
        for rule in domain.get_quality_rules():
            assert "name" in rule, f"Rule missing 'name': {rule}"
            assert "stage" in rule, f"Rule missing 'stage': {rule}"
            assert "check" in rule, f"Rule missing 'check': {rule}"
            assert callable(rule["check"]), f"Rule 'check' not callable: {rule}"

    def test_rule_names(self, domain):
        """Verify the expected rule names."""
        names = {r["name"] for r in domain.get_quality_rules()}
        assert "rule_answer_not_empty" in names
        assert "rule_answer_format_valid" in names

    def test_answer_not_empty_passes_with_content(self, domain):
        """Non-empty answer should pass."""
        rules = domain.get_quality_rules()
        rule = next(r for r in rules if r["name"] == "rule_answer_not_empty")
        # Provide a result dict with a non-empty answer
        violation = rule["check"]({"answer": "42"})
        assert violation is None

    def test_answer_not_empty_fails_when_empty(self, domain):
        """Empty answer should produce a violation."""
        rules = domain.get_quality_rules()
        rule = next(r for r in rules if r["name"] == "rule_answer_not_empty")
        violation = rule["check"]({"answer": ""})
        assert violation is not None
        assert "empty" in violation.lower()

    def test_answer_not_empty_fails_when_missing(self, domain):
        """Missing answer key should produce a violation."""
        rules = domain.get_quality_rules()
        rule = next(r for r in rules if r["name"] == "rule_answer_not_empty")
        violation = rule["check"]({})
        assert violation is not None

    def test_answer_format_valid_passes_csv(self, domain):
        """CSV-like output (header + values) should pass."""
        rules = domain.get_quality_rules()
        rule = next(r for r in rules if r["name"] == "rule_answer_format_valid")
        violation = rule["check"]({"answer": "name,count\nAlice,5"})
        assert violation is None

    def test_answer_format_valid_passes_single_value(self, domain):
        """Single value answer should pass (common for aggregation queries)."""
        rules = domain.get_quality_rules()
        rule = next(r for r in rules if r["name"] == "rule_answer_format_valid")
        violation = rule["check"]({"answer": "42"})
        assert violation is None

    def test_answer_format_valid_fails_whitespace_only(self, domain):
        """Whitespace-only answer should fail."""
        rules = domain.get_quality_rules()
        rule = next(r for r in rules if r["name"] == "rule_answer_format_valid")
        violation = rule["check"]({"answer": "   \n  "})
        assert violation is not None


# ---------------------------------------------------------------------------
# get_knowledge
# ---------------------------------------------------------------------------

class TestGetKnowledge:
    """Test knowledge retrieval from knowledge_path."""

    def test_reads_real_file(self, domain):
        """Should read the test fixture knowledge.md and return its content."""
        knowledge = domain.get_knowledge("anything")
        assert isinstance(knowledge, str)
        assert len(knowledge) > 0
        # The fixture has "Test Knowledge File" as its heading
        assert "Test Knowledge File" in knowledge

    def test_stage_parameter_accepted(self, domain):
        """stage parameter should be accepted without error (ignored)."""
        knowledge = domain.get_knowledge("query", stage="hypothesize")
        assert isinstance(knowledge, str)
        assert len(knowledge) > 0

    def test_token_budget_parameter_accepted(self, domain):
        """token_budget parameter should be accepted without error (ignored)."""
        knowledge = domain.get_knowledge("query", token_budget=500)
        assert isinstance(knowledge, str)

    def test_empty_path_returns_empty_string(self, empty_domain):
        """Domain with no knowledge_path should return empty string."""
        knowledge = empty_domain.get_knowledge("anything")
        assert knowledge == ""

    def test_missing_file_returns_empty_string(self):
        """Domain with a non-existent knowledge_path should return empty string."""
        domain = DataAnalysisDomain(knowledge_path="/nonexistent/path/knowledge.md")
        knowledge = domain.get_knowledge("anything")
        assert knowledge == ""


# ---------------------------------------------------------------------------
# get_agents
# ---------------------------------------------------------------------------

class TestGetAgents:
    """Test agent retrieval — should be empty for data analysis."""

    def test_returns_dict(self, domain):
        agents = domain.get_agents()
        assert isinstance(agents, dict)

    def test_has_required_keys(self, domain):
        agents = domain.get_agents()
        assert "registry" in agents
        assert "agents_dir" in agents

    def test_registry_is_empty(self, domain):
        """No agents for data analysis — registry should be empty dict."""
        agents = domain.get_agents()
        assert agents["registry"] == {}

    def test_agents_dir_is_empty_string(self, domain):
        """No agents dir for data analysis."""
        agents = domain.get_agents()
        assert agents["agents_dir"] == ""


# ---------------------------------------------------------------------------
# Constructor / initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    """Test constructor defaults and task-scoped behavior."""

    def test_default_knowledge_path(self):
        """Default knowledge_path should be empty string."""
        domain = DataAnalysisDomain()
        assert domain.knowledge_path == ""

    def test_default_context_files(self):
        """Default context_files should be None."""
        domain = DataAnalysisDomain()
        assert domain.context_files is None

    def test_stores_knowledge_path(self, domain):
        """knowledge_path should be stored from constructor."""
        assert domain.knowledge_path == _KNOWLEDGE_PATH

    def test_stores_context_files(self, domain):
        """context_files should be stored from constructor."""
        assert "csv" in domain.context_files
        assert "db" in domain.context_files
