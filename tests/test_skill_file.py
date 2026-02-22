"""Tests for the Search Metric Analyzer skill file.

Validates that the skill file exists, has correct structure, references
real tools with correct CLI flags, and encodes the full 4-step methodology.

WHY TEST A MARKDOWN FILE?
The skill file is a critical operational artifact — it tells Claude Code
exactly how to orchestrate the diagnostic workflow. If it references wrong
CLI flags, missing tools, or incorrect file paths, the entire workflow breaks.
These tests catch those issues before they become runtime failures.
"""

import re
import pytest
from pathlib import Path


# Path to the skill file (from project root)
ROOT = Path(__file__).parent.parent
SKILL_FILE = ROOT / "skills" / "search-metric-analyzer.md"
TOOLS_DIR = ROOT / "tools"
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"


class TestSkillFileExists:
    """Verify the skill file exists and is non-empty."""

    def test_skill_file_exists(self):
        assert SKILL_FILE.exists(), f"Skill file not found at {SKILL_FILE}"

    def test_skill_file_is_not_empty(self):
        content = SKILL_FILE.read_text()
        assert len(content) > 100, "Skill file is too short to be meaningful"


class TestSkillFileFrontmatter:
    """Verify YAML frontmatter has required fields."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_has_yaml_frontmatter(self, content):
        """Skill files use YAML frontmatter delimited by --- markers."""
        assert content.startswith("---"), "Skill file must start with YAML frontmatter (---)"
        # Must have closing --- marker
        second_marker = content.index("---", 3)
        assert second_marker > 3, "Skill file must have closing frontmatter marker (---)"

    def test_frontmatter_has_name(self, content):
        assert "name:" in content, "Frontmatter must include 'name' field"

    def test_frontmatter_has_description(self, content):
        assert "description:" in content, "Frontmatter must include 'description' field"

    def test_frontmatter_has_trigger(self, content):
        assert "trigger:" in content, "Frontmatter must include 'trigger' field"

    def test_trigger_mentions_key_metrics(self, content):
        """The trigger should fire on common metric names users would mention."""
        # Extract just the trigger section from frontmatter
        trigger_terms = ["Click Quality", "Search Quality Success", "AI Answer", "metric drop", "metric spike"]
        found = sum(1 for term in trigger_terms if term.lower() in content.lower())
        assert found >= 3, (
            f"Trigger should mention at least 3 key metric terms, found {found}. "
            f"Checked: {trigger_terms}"
        )


class TestSkillFileReferencesRealTools:
    """Verify the skill file references tools that actually exist."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_references_decompose_py(self, content):
        assert "decompose.py" in content, "Must reference tools/decompose.py"

    def test_references_anomaly_py(self, content):
        assert "anomaly.py" in content, "Must reference tools/anomaly.py"

    def test_references_diagnose_py(self, content):
        assert "diagnose.py" in content, "Must reference tools/diagnose.py"

    def test_references_formatter_py(self, content):
        assert "formatter.py" in content, "Must reference tools/formatter.py"

    def test_referenced_tools_exist(self, content):
        """Every tool referenced in the skill file must exist on disk."""
        expected_tools = [
            "decompose.py", "anomaly.py", "diagnose.py", "formatter.py"
        ]
        for tool in expected_tools:
            tool_path = TOOLS_DIR / tool
            assert tool_path.exists(), (
                f"Skill file references {tool} but it doesn't exist at {tool_path}"
            )


class TestSkillFileCLIFlags:
    """Verify CLI invocations use flags that actually exist in the tools.

    This is critical: if the skill tells Claude Code to run
    `python tools/anomaly.py --mode quality` but the actual flag is --check,
    the workflow will fail at runtime.
    """

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    @pytest.fixture
    def anomaly_source(self):
        return (TOOLS_DIR / "anomaly.py").read_text()

    @pytest.fixture
    def decompose_source(self):
        return (TOOLS_DIR / "decompose.py").read_text()

    @pytest.fixture
    def diagnose_source(self):
        return (TOOLS_DIR / "diagnose.py").read_text()

    @pytest.fixture
    def formatter_source(self):
        return (TOOLS_DIR / "formatter.py").read_text()

    def test_anomaly_uses_correct_check_flag(self, content, anomaly_source):
        """anomaly.py uses --check (not --mode)."""
        # The skill file should use --check for anomaly.py
        # Find all anomaly.py invocations in the skill file
        anomaly_lines = [
            line for line in content.split("\n")
            if "anomaly.py" in line and "python" in line.lower()
        ]
        for line in anomaly_lines:
            assert "--mode" not in line, (
                f"Skill file uses '--mode' for anomaly.py, but actual flag is '--check'. "
                f"Line: {line}"
            )

    def test_anomaly_check_values_are_valid(self, content, anomaly_source):
        """Check values used in skill must match anomaly.py's choices."""
        valid_checks = ["all", "data_quality", "step_change", "co_movement", "baseline"]
        anomaly_lines = [
            line for line in content.split("\n")
            if "anomaly.py" in line and "--check" in line
        ]
        for line in anomaly_lines:
            # Extract the value after --check
            match = re.search(r"--check\s+(\w+)", line)
            if match:
                check_val = match.group(1)
                assert check_val in valid_checks, (
                    f"Invalid --check value '{check_val}' in anomaly.py invocation. "
                    f"Valid: {valid_checks}. Line: {line}"
                )

    def test_decompose_uses_correct_flags(self, content, decompose_source):
        """decompose.py uses --input, --metric, --dimensions."""
        decompose_lines = [
            line for line in content.split("\n")
            if "decompose.py" in line and "python" in line.lower()
        ]
        # At minimum, --input and --metric should be referenced
        assert any("--input" in line for line in decompose_lines), (
            "decompose.py invocations must use --input flag"
        )
        assert any("--metric" in line for line in decompose_lines), (
            "decompose.py invocations must use --metric flag"
        )

    def test_diagnose_uses_correct_input_flag(self, content, diagnose_source):
        """diagnose.py uses --input for JSON input."""
        diagnose_lines = [
            line for line in content.split("\n")
            if "diagnose.py" in line and "python" in line.lower()
        ]
        assert any("--input" in line for line in diagnose_lines), (
            "diagnose.py invocations must use --input flag"
        )

    def test_formatter_uses_correct_flags(self, content, formatter_source):
        """formatter.py uses --input (not --format, which doesn't exist)."""
        formatter_lines = [
            line for line in content.split("\n")
            if "formatter.py" in line and "python" in line.lower()
        ]
        for line in formatter_lines:
            assert "--format" not in line, (
                f"Skill file uses '--format' for formatter.py, but that flag doesn't exist. "
                f"formatter.py only takes --input. Line: {line}"
            )


class TestSkillFileKnowledgeReferences:
    """Verify the skill file references knowledge files that exist."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_references_metric_definitions(self, content):
        assert "metric_definitions.yaml" in content, (
            "Must reference data/knowledge/metric_definitions.yaml"
        )

    def test_references_historical_patterns(self, content):
        assert "historical_patterns.yaml" in content, (
            "Must reference data/knowledge/historical_patterns.yaml"
        )

    def test_knowledge_files_exist(self):
        """Referenced knowledge files must exist on disk."""
        assert (KNOWLEDGE_DIR / "metric_definitions.yaml").exists()
        assert (KNOWLEDGE_DIR / "historical_patterns.yaml").exists()


class TestSkillFileFourStepWorkflow:
    """Verify all 4 diagnostic steps are encoded in the skill file."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_has_step_1_intake(self, content):
        content_lower = content.lower()
        assert "step 1" in content_lower, "Must include Step 1"
        assert "intake" in content_lower or "triage" in content_lower, (
            "Step 1 must be labeled as Intake/Triage"
        )

    def test_has_step_2_decompose(self, content):
        content_lower = content.lower()
        assert "step 2" in content_lower, "Must include Step 2"
        assert "decompose" in content_lower or "investigate" in content_lower, (
            "Step 2 must be labeled as Decompose/Investigate"
        )

    def test_has_step_3_validate(self, content):
        content_lower = content.lower()
        assert "step 3" in content_lower, "Must include Step 3"
        assert "validate" in content_lower, "Step 3 must be labeled as Validate"

    def test_has_step_4_synthesize(self, content):
        content_lower = content.lower()
        assert "step 4" in content_lower, "Must include Step 4"
        assert "synthesize" in content_lower or "format" in content_lower, (
            "Step 4 must be labeled as Synthesize/Format"
        )


class TestSkillFileSeverityClassification:
    """Verify severity thresholds match the design doc and decompose.py."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_mentions_p0_threshold(self, content):
        """P0 = >5% movement (from design doc Section 5)."""
        assert "P0" in content, "Must define P0 severity"

    def test_mentions_p1_threshold(self, content):
        """P1 = 2-5% movement."""
        assert "P1" in content, "Must define P1 severity"

    def test_mentions_p2_threshold(self, content):
        """P2 = <2% movement."""
        assert "P2" in content, "Must define P2 severity"


class TestSkillFileHypothesisPriority:
    """Verify the 7-priority hypothesis ordering from the design doc."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_instrumentation_is_listed(self, content):
        """Instrumentation/Logging must be first priority."""
        assert "instrumentation" in content.lower() or "logging" in content.lower()

    def test_connector_is_listed(self, content):
        """Connector/data pipeline must be listed."""
        assert "connector" in content.lower()

    def test_user_behavior_is_last(self, content):
        """User behavior must be explicitly marked as last."""
        assert "user behavior" in content.lower() or "behavior shift" in content.lower()
        # Should mention checking it LAST
        assert "last" in content.lower()


class TestSkillFileValidationChecks:
    """Verify the 4 mandatory validation checks are documented."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_logging_artifact_check(self, content):
        content_lower = content.lower()
        assert "logging artifact" in content_lower or "step-change" in content_lower

    def test_decomposition_completeness_check(self, content):
        content_lower = content.lower()
        assert "decomposition completeness" in content_lower or "90%" in content

    def test_temporal_consistency_check(self, content):
        content_lower = content.lower()
        assert "temporal consistency" in content_lower or "cause precedes effect" in content_lower

    def test_mix_shift_check(self, content):
        content_lower = content.lower()
        assert "mix shift" in content_lower or "mix-shift" in content_lower
        assert "30%" in content, "Must reference 30% mix-shift threshold"


class TestSkillFileAntiPatterns:
    """Verify anti-patterns are explicitly documented (NON-NEGOTIABLE per design doc)."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_no_data_dumps_rule(self, content):
        content_lower = content.lower()
        assert "data dump" in content_lower, "Must warn against data dump anti-pattern"

    def test_no_hedge_parades_rule(self, content):
        content_lower = content.lower()
        assert "hedge" in content_lower, "Must warn against hedge parade anti-pattern"

    def test_no_orphaned_recommendations_rule(self, content):
        content_lower = content.lower()
        assert "orphan" in content_lower, "Must warn against orphaned recommendations"

    def test_no_passive_voice_rule(self, content):
        content_lower = content.lower()
        assert "passive voice" in content_lower, "Must warn against passive voice"


class TestSkillFileAIAdoptionSpecialCase:
    """Verify the AI adoption special case is explicitly handled.

    This is the "AI answer trap" from the design doc: Click Quality drops because
    AI answers are working, which is a POSITIVE signal, not a regression.
    Misidentifying this wastes engineering time and could roll back a good feature.
    """

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_ai_adoption_effect_documented(self, content):
        content_lower = content.lower()
        assert "ai" in content_lower and "adoption" in content_lower, (
            "Must document AI adoption special case"
        )

    def test_labels_as_positive(self, content):
        content_lower = content.lower()
        assert "positive" in content_lower, (
            "Must explicitly label AI adoption Click Quality decline as positive"
        )

    def test_do_not_treat_as_regression(self, content):
        content_lower = content.lower()
        assert "not" in content_lower and "regression" in content_lower, (
            "Must explicitly say 'do NOT treat as regression'"
        )


class TestSkillFileOperatingModes:
    """Verify both Quick and Standard operating modes are documented."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_quick_mode_documented(self, content):
        content_lower = content.lower()
        assert "quick" in content_lower, "Must document Quick operating mode"

    def test_standard_mode_documented(self, content):
        content_lower = content.lower()
        assert "standard" in content_lower, "Must document Standard operating mode"


class TestSkillFileCoMovement:
    """Verify co-movement diagnostic table is referenced or encoded."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_co_movement_referenced(self, content):
        content_lower = content.lower()
        assert "co-movement" in content_lower or "co_movement" in content_lower, (
            "Must reference co-movement diagnostic table"
        )

    def test_mentions_metric_directions(self, content):
        """Co-movement check compares directions of related metrics."""
        content_lower = content.lower()
        # Should mention at least some of these metrics in co-movement context
        metrics = ["click_quality", "search_quality_success", "ai_answer", "zero-result", "latency"]
        found = sum(1 for m in metrics if m in content_lower)
        assert found >= 3, (
            f"Co-movement section should reference at least 3 related metrics, found {found}"
        )


class TestSkillFileOutputRequirements:
    """Verify output format requirements from design doc Section 9."""

    @pytest.fixture
    def content(self):
        return SKILL_FILE.read_text()

    def test_tldr_requirement(self, content):
        """TL;DR always first, always mandatory, max 3 sentences."""
        content_lower = content.lower()
        assert "tl;dr" in content_lower or "tldr" in content_lower

    def test_confidence_explicitly_stated(self, content):
        content_lower = content.lower()
        assert "confidence" in content_lower
        assert "high" in content_lower and "medium" in content_lower and "low" in content_lower

    def test_owner_requirement(self, content):
        """Every action has an owner."""
        content_lower = content.lower()
        assert "owner" in content_lower

    def test_what_would_change_confidence(self, content):
        """Must state what would change the confidence level."""
        content_lower = content.lower()
        assert "would" in content_lower and "change" in content_lower or "upgrade" in content_lower
