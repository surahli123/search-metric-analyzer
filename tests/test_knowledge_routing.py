"""Tests that the knowledge routing table references resolve to actual files and sections.

WHY: The routing table in .claude/rules/04-knowledge-routing.md maps diagnostic
intents to specific YAML sections. If a file moves, a section key changes, or
a new file is added without updating the routing table, the agent silently loads
the wrong context. These tests catch that drift.
"""

import re
import yaml
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent
RULES_DIR = ROOT / ".claude" / "rules"
KNOWLEDGE_DIR = ROOT / "domains" / "search_metrics" / "knowledge"
ROUTING_TABLE_PATH = RULES_DIR / "04-knowledge-routing.md"


def _parse_single_intent_routes(content: str):
    """Extract (intent, file, section_key, is_nested) tuples from Single-Intent Routes tables.

    Parses markdown table rows like:
      | Metric formula, definition | metric_definitions.yaml | `metrics:` | ~12 |
      | Failure mode per component | search_pipeline_knowledge.yaml | `failure_modes:` (within each component) | — |
      | Eval rubric for retrospective | eval/eval_rubric_approach_a.md | — | full file |
    """
    routes = []
    # Pattern 1: rows with backtick-wrapped section keys
    pattern_with_key = re.compile(
        r'\| ([^|]+?) \| ([^|]+?) \| `([^`]+?)`([^|]*?) \| [^|]+ \|'
    )
    for match in pattern_with_key.finditer(content):
        intent = match.group(1).strip()
        file_ref = match.group(2).strip()
        section_key = match.group(3).strip().rstrip(':')  # Remove trailing colon
        annotation = match.group(4).strip()
        is_nested = 'within' in annotation.lower()
        routes.append((intent, file_ref, section_key, is_nested))

    # Pattern 2: rows WITHOUT section keys (using — or "full file")
    # These reference whole files like eval rubrics or session records
    pattern_no_key = re.compile(
        r'\| ([^|]+?) \| ([^|]+?) \| —[^|]* \| [^|]+ \|'
    )
    for match in pattern_no_key.finditer(content):
        intent = match.group(1).strip()
        file_ref = match.group(2).strip()
        # Skip header/separator rows
        if file_ref.startswith('---') or file_ref == 'File':
            continue
        routes.append((intent, file_ref, None, False))  # No section key

    return routes


def _parse_composite_intent_files(content: str):
    """Extract file references from the Composite Intents table.

    Parses patterns like:
      | "Why did [metric] drop?" | rules 01+03 | metric_definitions `co_movement_diagnostic_table:` → historical_patterns |

    WHY two patterns: The table uses bare knowledge file names (e.g., "metric_definitions")
    without .yaml extension, plus .md paths for docs. We need to catch both.
    """
    files = set()
    # Find the Composite Intents section, stop before next ## section
    if "## Composite Intents" not in content:
        return files
    composite_section = content.split("## Composite Intents")[1]
    if "## " in composite_section[1:]:
        composite_section = composite_section[:composite_section.index("\n## ", 1)]

    # Pattern 1: Explicit .yaml file references
    yaml_refs = re.findall(r'(\w+(?:_\w+)*\.yaml)', composite_section)
    files.update(yaml_refs)

    # Pattern 2: Bare knowledge file names (word_word without extension)
    # These appear as standalone references like "metric_definitions" or "historical_patterns"
    bare_refs = re.findall(r'(?:→\s*|,\s*)(\w+(?:_\w+)+)(?:\s|`|\|)', composite_section)
    for ref in bare_refs:
        # Only add if a matching .yaml exists in knowledge dir
        if (KNOWLEDGE_DIR / f"{ref}.yaml").exists():
            files.add(f"{ref}.yaml")

    # Pattern 3: .md file paths (e.g., eval/eval_rubric_approach_a.md)
    md_refs = re.findall(r'([\w/\-]+\.md)', composite_section)
    for ref in md_refs:
        files.add(ref)

    return files


def _find_key_recursive(data, target_key):
    """Recursively search for a key in nested dicts.

    WHY: Some routing table entries reference nested keys like `failure_modes:`
    which live inside pipeline component dicts, not at the top level.
    """
    if isinstance(data, dict):
        if target_key in data:
            return True
        for value in data.values():
            if _find_key_recursive(value, target_key):
                return True
    elif isinstance(data, list):
        for item in data:
            if _find_key_recursive(item, target_key):
                return True
    return False


class TestKnowledgeRoutingIntegrity:
    """Verify routing table references resolve to actual files and sections."""

    @pytest.fixture(autouse=True)
    def load_routing_table(self):
        self.content = ROUTING_TABLE_PATH.read_text()
        self.routes = _parse_single_intent_routes(self.content)

    def test_routing_table_parseable(self):
        """Routing table markdown has expected structure."""
        assert "## Single-Intent Routes" in self.content, "Missing Single-Intent Routes section"
        assert "## Composite Intents" in self.content, "Missing Composite Intents section"
        assert "## Stop Rule" in self.content, "Missing Stop Rule section"
        assert "## Scalability Ceiling" in self.content, "Missing Scalability Ceiling section"

    def test_minimum_route_count(self):
        """Extracted routes >= 15. Catches silent regex failures."""
        assert len(self.routes) >= 15, (
            f"Only extracted {len(self.routes)} routes — regex may be broken. "
            f"Expected at least 15."
        )

    def test_all_referenced_yaml_files_exist(self):
        """Every YAML file referenced in routing table must exist."""
        yaml_files = {r[1] for r in self.routes if r[1].endswith('.yaml')}
        for filename in yaml_files:
            filepath = KNOWLEDGE_DIR / filename
            assert filepath.exists(), (
                f"Routing table references '{filename}' but file not found at {filepath}"
            )

    def test_all_referenced_doc_files_exist(self):
        """Non-YAML file paths (design doc, IC9 review, eval rubrics) must exist."""
        # Extract file paths that aren't YAML — these use relative paths from project root
        doc_refs = set()
        for route in self.routes:
            file_ref = route[1]
            if not file_ref.endswith('.yaml'):
                doc_refs.add(file_ref)

        for doc_path in doc_refs:
            # Handle glob patterns like "session-record-context-layer*.md"
            if '*' in doc_path:
                matches = list(ROOT.glob(doc_path))
                assert len(matches) > 0, (
                    f"Routing table references glob '{doc_path}' but no matches found"
                )
            else:
                filepath = ROOT / doc_path
                assert filepath.exists(), (
                    f"Routing table references '{doc_path}' but file not found at {filepath}"
                )

    def test_yaml_section_keys_resolve(self):
        """Every section key must exist in its target YAML file.

        WHY two-pass: Some routing table entries reference nested keys
        (e.g., baseline_by_segment inside metrics.click_quality) without
        explicit annotation. We try top-level first, then recursive search
        as a fallback. This catches truly missing keys without requiring
        every nested reference to be annotated.
        """
        yaml_routes = [(r[1], r[2], r[3]) for r in self.routes
                       if r[1].endswith('.yaml') and r[2] is not None]

        for filename, section_key, is_nested in yaml_routes:
            filepath = KNOWLEDGE_DIR / filename
            if not filepath.exists():
                continue  # File existence tested separately

            with open(filepath) as f:
                data = yaml.safe_load(f)

            if is_nested or section_key not in data:
                # Annotated nested keys or keys not found at top level —
                # use recursive search through the full YAML structure
                assert _find_key_recursive(data, section_key), (
                    f"Key '{section_key}' not found anywhere in {filename}. "
                    f"Top-level keys: {list(data.keys())}"
                )

    def test_composite_intent_files_referenced_exist(self):
        """Files referenced in composite intents table must exist."""
        refs = _parse_composite_intent_files(self.content)
        for filename in refs:
            if filename.endswith('.yaml'):
                # YAML files live in knowledge dir
                filepath = KNOWLEDGE_DIR / filename
            else:
                # .md files use paths relative to project root
                filepath = ROOT / filename
            assert filepath.exists(), (
                f"Composite intent references '{filename}' but file not found at {filepath}"
            )

    def test_no_duplicate_intents(self):
        """Each intent description should appear only once in routing table."""
        intents = [r[0] for r in self.routes]
        seen = set()
        duplicates = []
        for intent in intents:
            if intent in seen:
                duplicates.append(intent)
            seen.add(intent)
        assert len(duplicates) == 0, (
            f"Duplicate intents in routing table: {duplicates}"
        )
