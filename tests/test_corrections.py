"""Tests for the corrections knowledge layer."""

import pytest
import yaml
from pathlib import Path


class TestLoadCorrections:
    def test_loads_from_default_path(self):
        from core.corrections import load_corrections
        corrections = load_corrections()
        assert isinstance(corrections, list)

    def test_missing_file_returns_empty(self, tmp_path):
        from core.corrections import load_corrections
        result = load_corrections(yaml_path=str(tmp_path / "nonexistent.yaml"))
        assert result == []

    def test_each_correction_has_required_fields(self):
        from core.corrections import load_corrections
        corrections = load_corrections()
        for c in corrections:
            assert "metric" in c
            assert "original_archetype" in c
            assert "corrected_to" in c
            assert "context" in c


class TestFindRelevantCorrections:
    def test_exact_match(self):
        from core.corrections import find_relevant_corrections
        corrections = [
            {"metric": "click_quality", "original_archetype": "ranking_regression",
             "corrected_to": "mix_shift", "date": "2026-02-15", "context": "test"},
            {"metric": "ai_trigger", "original_archetype": "model_degradation",
             "corrected_to": "config_change", "date": "2026-02-20", "context": "test2"},
        ]
        result = find_relevant_corrections("click_quality", "ranking_regression", corrections)
        assert len(result) == 1
        assert result[0]["corrected_to"] == "mix_shift"

    def test_metric_only_match(self):
        from core.corrections import find_relevant_corrections
        corrections = [
            {"metric": "click_quality", "original_archetype": "ranking_regression",
             "corrected_to": "mix_shift", "date": "2026-02-15", "context": "test"},
        ]
        result = find_relevant_corrections("click_quality", "behavioral_change", corrections)
        assert len(result) == 1

    def test_no_match(self):
        from core.corrections import find_relevant_corrections
        corrections = [
            {"metric": "click_quality", "original_archetype": "ranking_regression",
             "corrected_to": "mix_shift", "date": "2026-02-15", "context": "test"},
        ]
        result = find_relevant_corrections("ai_trigger", "model_degradation", corrections)
        assert len(result) == 0

    def test_sorted_by_date_newest_first(self):
        """Within the same archetype-priority tier, newest corrections come first."""
        from core.corrections import find_relevant_corrections
        # Both entries have the SAME archetype so they're in the same priority tier.
        # This isolates the date-sorting behavior from archetype-priority sorting.
        corrections = [
            {"metric": "click_quality", "original_archetype": "a",
             "corrected_to": "b", "date": "2026-01-01", "context": "old"},
            {"metric": "click_quality", "original_archetype": "a",
             "corrected_to": "d", "date": "2026-03-01", "context": "new"},
        ]
        result = find_relevant_corrections("click_quality", "a", corrections)
        assert result[0]["date"] == "2026-03-01"

    def test_expired_corrections_filtered(self):
        """Corrections older than max_age_days are excluded (Memory Time Bomb prevention)."""
        from datetime import date, timedelta
        from core.corrections import find_relevant_corrections
        recent_date = str(date.today() - timedelta(days=10))
        ancient_date = str(date.today() - timedelta(days=365))
        corrections = [
            {"metric": "click_quality", "original_archetype": "a",
             "corrected_to": "b", "date": ancient_date, "context": "ancient"},
            {"metric": "click_quality", "original_archetype": "c",
             "corrected_to": "d", "date": recent_date, "context": "recent"},
        ]
        result = find_relevant_corrections("click_quality", "a", corrections, max_age_days=90)
        assert len(result) == 1
        assert result[0]["context"] == "recent"

    def test_no_expiration_when_explicitly_disabled(self):
        """When max_age_days is None, all corrections are returned regardless of age."""
        from datetime import date, timedelta
        from core.corrections import find_relevant_corrections
        ancient_date = str(date.today() - timedelta(days=2000))
        corrections = [
            {"metric": "click_quality", "original_archetype": "a",
             "corrected_to": "b", "date": ancient_date, "context": "very old"},
        ]
        result = find_relevant_corrections("click_quality", "a", corrections, max_age_days=None)
        assert len(result) == 1

    def test_archetype_exact_match_ranked_higher(self):
        """Exact archetype match should appear before metric-only match."""
        from core.corrections import find_relevant_corrections
        corrections = [
            {"metric": "click_quality", "original_archetype": "behavioral_change",
             "corrected_to": "x", "date": "2026-03-01", "context": "metric-only"},
            {"metric": "click_quality", "original_archetype": "ranking_regression",
             "corrected_to": "mix_shift", "date": "2026-02-15", "context": "exact match"},
        ]
        result = find_relevant_corrections("click_quality", "ranking_regression", corrections)
        assert result[0]["context"] == "exact match"


class TestAppendCorrection:
    """Tests for the write path — appending corrections to YAML."""

    def test_append_to_existing_file(self, tmp_path):
        from core.corrections import append_correction, load_corrections
        yaml_path = str(tmp_path / "corrections.yaml")
        Path(yaml_path).write_text("corrections: []\n")

        append_correction(
            metric="click_quality",
            original_archetype="ranking_regression",
            corrected_to="mix_shift",
            context="Test correction",
            corrected_by="DS Lead",
            source="user_correction",
            yaml_path=yaml_path,
        )
        result = load_corrections(yaml_path=yaml_path)
        assert len(result) == 1
        assert result[0]["metric"] == "click_quality"
        assert result[0]["source"] == "user_correction"
        assert "date" in result[0]

    def test_append_creates_file_if_missing(self, tmp_path):
        from core.corrections import append_correction, load_corrections
        yaml_path = str(tmp_path / "new_corrections.yaml")

        append_correction(
            metric="ai_trigger",
            original_archetype="model_degradation",
            corrected_to="config_change",
            context="Auto-captured from SQL error",
            source="sql_error",
            yaml_path=yaml_path,
        )
        result = load_corrections(yaml_path=yaml_path)
        assert len(result) == 1
        assert result[0]["source"] == "sql_error"

    def test_append_preserves_existing_entries(self, tmp_path):
        from core.corrections import append_correction, load_corrections
        yaml_path = str(tmp_path / "corrections.yaml")
        Path(yaml_path).write_text(yaml.dump({"corrections": [
            {"metric": "click_quality", "original_archetype": "a",
             "corrected_to": "b", "date": "2026-01-01", "context": "old",
             "source": "user_correction"},
        ]}))

        append_correction(
            metric="ai_trigger",
            original_archetype="c",
            corrected_to="d",
            context="new entry",
            source="sql_error",
            yaml_path=yaml_path,
        )
        result = load_corrections(yaml_path=yaml_path)
        assert len(result) == 2

    def test_source_field_required(self, tmp_path):
        """Source must be one of: user_correction, sql_error, skill_feedback."""
        from core.corrections import append_correction
        yaml_path = str(tmp_path / "corrections.yaml")
        with pytest.raises(ValueError, match="source"):
            append_correction(
                metric="click_quality",
                original_archetype="a",
                corrected_to="b",
                context="test",
                source="invalid_source",
                yaml_path=yaml_path,
            )


class TestCLI:
    """CLI interface for appending corrections."""

    def test_cli_add_writes_correction(self, tmp_path):
        import subprocess, sys, json
        yaml_path = str(tmp_path / "corrections.yaml")
        result = subprocess.run(
            [sys.executable, "core/corrections.py",
             "--add",
             "--metric", "click_quality",
             "--original", "ranking_regression",
             "--corrected-to", "mix_shift",
             "--context", "Test via CLI",
             "--source", "user_correction",
             "--yaml-path", yaml_path],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "appended"

        from core.corrections import load_corrections
        corrections = load_corrections(yaml_path=yaml_path)
        assert len(corrections) == 1

    def test_cli_add_missing_required_arg(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "core/corrections.py", "--add", "--metric", "click_quality"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0  # Missing required args
