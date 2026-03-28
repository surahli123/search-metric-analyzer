"""Tests for KDD answer evaluator.

Validates that:
1. Exact numeric matches score 1.0
2. Float tolerance handles precision differences (1e-6)
3. String comparison is case-insensitive
4. Multi-row gold files are compared row-by-row
5. SQL-expression headers (e.g., "COUNT(DISTINCT T1.event_id)") are handled
6. Empty predicted strings return match=False
7. Missing gold files return match=False with error
8. Numeric equivalence (e.g., "1.0" matches "1")
"""

import csv
import os
import tempfile
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures — create gold CSV files in temp directories
# ---------------------------------------------------------------------------

@pytest.fixture
def gold_single_int(tmp_path):
    """Gold file with a single integer value: header + one data row."""
    gold = tmp_path / "gold.csv"
    gold.write_text("count\n42\n")
    return str(gold)


@pytest.fixture
def gold_single_float(tmp_path):
    """Gold file with a single float value."""
    gold = tmp_path / "gold.csv"
    gold.write_text("avg_score\n3.14159\n")
    return str(gold)


@pytest.fixture
def gold_multi_row(tmp_path):
    """Gold file with multiple rows — tests row-by-row comparison."""
    gold = tmp_path / "gold.csv"
    gold.write_text("name,score\nAlice,95\nBob,87\n")
    return str(gold)


@pytest.fixture
def gold_sql_header(tmp_path):
    """Gold file with SQL-expression header like real KDD data."""
    # Real KDD gold.csv often has headers like "COUNT(DISTINCT T1.event_id)"
    gold = tmp_path / "gold.csv"
    gold.write_text("COUNT(DISTINCT T1.event_id)\n1\n1\n1\n1\n")
    return str(gold)


@pytest.fixture
def gold_string_values(tmp_path):
    """Gold file with string values for case-insensitive comparison."""
    gold = tmp_path / "gold.csv"
    gold.write_text("city\nNew York\n")
    return str(gold)


# ---------------------------------------------------------------------------
# Tests — numeric matching
# ---------------------------------------------------------------------------

class TestNumericMatching:
    """Numeric values should match within tolerance."""

    def test_exact_integer_match(self, gold_single_int):
        """'42' matches '42' exactly."""
        from kdd.evaluator import evaluate

        result = evaluate("count\n42", gold_single_int)

        assert result["match"] is True
        assert result["score"] == 1.0

    def test_integer_as_float_matches(self, gold_single_int):
        """'42.0' should match '42' via numeric comparison."""
        from kdd.evaluator import evaluate

        result = evaluate("count\n42.0", gold_single_int)

        assert result["match"] is True
        assert result["score"] == 1.0

    def test_float_tolerance(self, gold_single_float):
        """'3.14159' matches '3.14159' (within 1e-6)."""
        from kdd.evaluator import evaluate

        result = evaluate("avg_score\n3.14159", gold_single_float)

        assert result["match"] is True

    def test_float_beyond_tolerance_fails(self, gold_single_float):
        """'3.15' does NOT match '3.14159' — too far apart."""
        from kdd.evaluator import evaluate

        result = evaluate("avg_score\n3.15", gold_single_float)

        assert result["match"] is False
        assert result["score"] == 0.0

    def test_numeric_equivalence_one_vs_one_point_zero(self, tmp_path):
        """'1.0' should match '1' via numeric comparison."""
        gold = tmp_path / "gold.csv"
        gold.write_text("value\n1\n")

        from kdd.evaluator import evaluate

        result = evaluate("value\n1.0", str(gold))

        assert result["match"] is True


# ---------------------------------------------------------------------------
# Tests — string matching
# ---------------------------------------------------------------------------

class TestStringMatching:
    """String values compared case-insensitively."""

    def test_case_insensitive_match(self, gold_string_values):
        """'new york' matches 'New York' case-insensitively."""
        from kdd.evaluator import evaluate

        result = evaluate("city\nnew york", gold_string_values)

        assert result["match"] is True
        assert result["score"] == 1.0

    def test_string_mismatch(self, gold_string_values):
        """'Los Angeles' does NOT match 'New York'."""
        from kdd.evaluator import evaluate

        result = evaluate("city\nLos Angeles", gold_string_values)

        assert result["match"] is False


# ---------------------------------------------------------------------------
# Tests — multi-row comparison
# ---------------------------------------------------------------------------

class TestMultiRowMatching:
    """Multi-row gold files are compared row-by-row."""

    def test_multi_row_exact_match(self, gold_multi_row):
        """All rows match in order."""
        from kdd.evaluator import evaluate

        result = evaluate("name,score\nAlice,95\nBob,87", gold_multi_row)

        assert result["match"] is True
        assert result["score"] == 1.0

    def test_multi_row_partial_mismatch(self, gold_multi_row):
        """One row matches, one doesn't — overall match is False."""
        from kdd.evaluator import evaluate

        result = evaluate("name,score\nAlice,95\nBob,90", gold_multi_row)

        assert result["match"] is False


# ---------------------------------------------------------------------------
# Tests — SQL expression headers
# ---------------------------------------------------------------------------

class TestSQLExpressionHeaders:
    """Gold files with SQL expression headers (common in KDD data)."""

    def test_sql_header_values_match(self, gold_sql_header):
        """Values match even when header is a SQL expression like COUNT(DISTINCT ...)."""
        from kdd.evaluator import evaluate

        result = evaluate("COUNT(DISTINCT T1.event_id)\n1\n1\n1\n1", gold_sql_header)

        assert result["match"] is True


# ---------------------------------------------------------------------------
# Tests — error cases
# ---------------------------------------------------------------------------

class TestErrorCases:
    """Edge cases and error handling."""

    def test_empty_predicted_returns_no_match(self, gold_single_int):
        """Empty prediction string should return match=False."""
        from kdd.evaluator import evaluate

        result = evaluate("", gold_single_int)

        assert result["match"] is False
        assert result["score"] == 0.0

    def test_gold_file_missing_returns_error(self):
        """Non-existent gold file should return match=False with error details."""
        from kdd.evaluator import evaluate

        result = evaluate("42", "/nonexistent/gold.csv")

        assert result["match"] is False
        assert "error" in result["details"].lower() or "not found" in result["details"].lower()

    def test_result_has_predicted_and_gold_values(self, gold_single_int):
        """Result dict should include both predicted and gold values for debugging."""
        from kdd.evaluator import evaluate

        result = evaluate("count\n42", gold_single_int)

        assert "predicted_values" in result
        assert "gold_values" in result
        assert len(result["gold_values"]) > 0
        assert len(result["predicted_values"]) > 0
