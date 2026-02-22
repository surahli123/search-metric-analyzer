#!/usr/bin/env python3
"""Tests for the eval framework: scoring spec structure + eval runner.

TDD Red phase: write tests first, then implement eval/run_eval.py.

The eval framework has two parts:
1. Scoring specs (YAML) — define what a correct diagnosis looks like for each case
2. Eval runner (Python) — loads specs, runs diagnosis, evaluates with LLM-as-judge

These tests verify:
- All 5 scoring spec YAML files exist and parse correctly
- Every spec has the required fields for LLM-as-judge evaluation
- Rubric weights sum to 100 and individual criteria points match dimension weight
- The eval runner can load specs, score a mock diagnosis, and aggregate results
"""

import yaml
import json
import pytest
from pathlib import Path

# ── Paths ──
EVAL_DIR = Path(__file__).parent.parent / "eval"
SPECS_DIR = EVAL_DIR / "scoring_specs"

# All 5 eval cases — expanded from 3 to 5 during Socratic rubric design
ALL_CASE_FILES = [
    "case1_single_cause.yaml",
    "case2_ai_adoption_trap.yaml",
    "case3_multi_cause.yaml",
    "case4_mix_shift.yaml",
    "case5_false_alarm.yaml",
]


# ──────────────────────────────────────────────────
# Test Group 1: Scoring Spec File Existence
# ──────────────────────────────────────────────────

class TestScoringSpecsExist:
    """Verify that all 5 scoring spec YAML files are present."""

    @pytest.mark.parametrize("case_file", ALL_CASE_FILES)
    def test_scoring_spec_exists(self, case_file):
        """Each eval case must have a scoring spec YAML file."""
        spec_path = SPECS_DIR / case_file
        assert spec_path.exists(), f"Missing scoring spec: {case_file}"

    def test_no_extra_specs(self):
        """Only expected scoring spec files should exist (no stale files)."""
        actual_files = sorted(f.name for f in SPECS_DIR.glob("*.yaml"))
        assert actual_files == sorted(ALL_CASE_FILES), (
            f"Unexpected files in scoring_specs/: {set(actual_files) - set(ALL_CASE_FILES)}"
        )


# ──────────────────────────────────────────────────
# Test Group 2: Scoring Spec Required Fields
# ──────────────────────────────────────────────────

class TestScoringSpecStructure:
    """Every scoring spec must have the mandatory fields for LLM-as-judge."""

    @pytest.fixture(params=ALL_CASE_FILES)
    def spec(self, request):
        """Load a scoring spec YAML for parametrized testing."""
        spec_path = SPECS_DIR / request.param
        with open(spec_path) as f:
            return yaml.safe_load(f)

    def test_has_case_section(self, spec):
        """Must have a 'case' section with name, scenario, archetype, purpose."""
        assert "case" in spec
        case = spec["case"]
        for key in ["name", "scenario", "archetype", "purpose"]:
            assert key in case, f"case section missing '{key}'"

    def test_has_rubric_with_4_dimensions(self, spec):
        """Must have a 'rubric' section with exactly 4 scoring dimensions."""
        assert "rubric" in spec
        rubric = spec["rubric"]
        expected_dims = {
            "root_cause_accuracy",
            "confidence_calibration",
            "investigation_completeness",
            "actionability",
        }
        assert set(rubric.keys()) == expected_dims, (
            f"Rubric dimensions mismatch. Expected {expected_dims}, got {set(rubric.keys())}"
        )

    def test_rubric_weights_sum_to_100(self, spec):
        """The 4 rubric dimension weights must sum to exactly 100."""
        rubric = spec["rubric"]
        total_weight = sum(dim["weight"] for dim in rubric.values())
        assert total_weight == 100, f"Rubric weights sum to {total_weight}, expected 100"

    def test_rubric_weights_match_design(self, spec):
        """Verify the co-designed rubric weights: 40/25/20/15."""
        rubric = spec["rubric"]
        assert rubric["root_cause_accuracy"]["weight"] == 40
        assert rubric["confidence_calibration"]["weight"] == 25
        assert rubric["investigation_completeness"]["weight"] == 20
        assert rubric["actionability"]["weight"] == 15

    def test_each_dimension_has_criteria(self, spec):
        """Each rubric dimension must have a 'criteria' list with points."""
        rubric = spec["rubric"]
        for dim_name, dim in rubric.items():
            assert "criteria" in dim, f"{dim_name} missing 'criteria'"
            criteria = dim["criteria"]
            assert len(criteria) >= 2, f"{dim_name} should have at least 2 criteria"
            for c in criteria:
                assert "description" in c, f"{dim_name} criterion missing 'description'"
                assert "points" in c, f"{dim_name} criterion missing 'points'"

    def test_dimension_criteria_points_match_weight(self, spec):
        """Sum of criteria points within each dimension must equal its weight."""
        rubric = spec["rubric"]
        for dim_name, dim in rubric.items():
            total_points = sum(c["points"] for c in dim["criteria"])
            assert total_points == dim["weight"], (
                f"{dim_name}: criteria points sum to {total_points}, "
                f"but weight is {dim['weight']}"
            )

    def test_has_must_find(self, spec):
        """Must have a 'must_find' section with root_cause and semantic_match."""
        assert "must_find" in spec
        must_find = spec["must_find"]
        assert "root_cause" in must_find, "must_find missing 'root_cause'"
        assert "semantic_match" in must_find, "must_find missing 'semantic_match'"
        assert must_find["semantic_match"] is True, "semantic_match should be True"

    def test_has_must_check_dimensions(self, spec):
        """Must have 'must_check_dimensions' list with at least one dimension."""
        assert "must_check_dimensions" in spec
        dims = spec["must_check_dimensions"]
        assert isinstance(dims, list) and len(dims) >= 1, (
            "must_check_dimensions should be a non-empty list"
        )

    def test_has_must_not_do(self, spec):
        """Must have 'must_not_do' section with anti-pattern rules."""
        assert "must_not_do" in spec
        anti_patterns = spec["must_not_do"]
        assert isinstance(anti_patterns, list) and len(anti_patterns) >= 2, (
            "must_not_do should have at least 2 anti-patterns"
        )

    def test_has_output_quality(self, spec):
        """Must have 'output_quality' section with required quality checks."""
        assert "output_quality" in spec
        oq = spec["output_quality"]
        for key in ["has_tldr", "confidence_stated", "confidence_level", "no_anti_patterns"]:
            assert key in oq, f"output_quality missing '{key}'"

    def test_has_scoring_thresholds(self, spec):
        """Must have 'scoring' section with pass and green thresholds."""
        assert "scoring" in spec
        scoring = spec["scoring"]
        assert scoring["pass"] == 60, f"Pass threshold should be 60, got {scoring['pass']}"
        assert scoring["green"] == 80, f"Green threshold should be 80, got {scoring['green']}"

    def test_has_pass_threshold(self, spec):
        """Must have 'pass_threshold' in case section (e.g., '3/3 GREEN')."""
        case = spec["case"]
        assert "pass_threshold" in case, "case section missing 'pass_threshold'"
        # Should be one of: "3/3 GREEN" or "2/3 GREEN"
        assert case["pass_threshold"] in ("3/3 GREEN", "2/3 GREEN"), (
            f"Unexpected pass_threshold: {case['pass_threshold']}"
        )


# ──────────────────────────────────────────────────
# Test Group 3: Scenario-Specific Validation
# ──────────────────────────────────────────────────

class TestCaseSpecificContent:
    """Validate that each case has content specific to its investigation archetype."""

    def _load_spec(self, filename):
        with open(SPECS_DIR / filename) as f:
            return yaml.safe_load(f)

    def test_case1_is_single_cause(self):
        """Case 1 (S4) should test single-cause ranking regression."""
        spec = self._load_spec("case1_single_cause.yaml")
        assert spec["case"]["scenario"] == "S4"
        assert spec["case"]["archetype"] == "single_cause_clean_signal"
        assert spec["case"]["pass_threshold"] == "3/3 GREEN"
        # Must find ranking model as root cause
        assert "ranking" in spec["must_find"]["root_cause"].lower()

    def test_case2_is_ai_adoption_trap(self):
        """Case 2 (S5) should test AI adoption misinterpretation."""
        spec = self._load_spec("case2_ai_adoption_trap.yaml")
        assert spec["case"]["scenario"] == "S5"
        assert spec["case"]["archetype"] == "ai_adoption_trap"
        assert spec["case"]["pass_threshold"] == "3/3 GREEN"
        # Must find AI adoption as root cause
        assert "ai" in spec["must_find"]["root_cause"].lower()
        # Must check ai_enablement dimension
        assert "ai_enablement" in spec["must_check_dimensions"]

    def test_case3_is_multi_cause(self):
        """Case 3 (S7) should test multi-cause overlap with ambiguity."""
        spec = self._load_spec("case3_multi_cause.yaml")
        assert spec["case"]["scenario"] == "S7"
        assert spec["case"]["archetype"] == "multi_cause_overlap"
        assert spec["case"]["pass_threshold"] == "2/3 GREEN"
        # Should mention multiple causes
        root = spec["must_find"]["root_cause"].lower()
        assert "multiple" in root or "overlap" in root or "both" in root

    def test_case4_is_mix_shift(self):
        """Case 4 (S9) should test tenant portfolio mix-shift."""
        spec = self._load_spec("case4_mix_shift.yaml")
        assert spec["case"]["scenario"] == "S9"
        assert spec["case"]["archetype"] == "mix_shift_no_regression"
        assert spec["case"]["pass_threshold"] == "2/3 GREEN"
        # Must find mix-shift
        assert "mix-shift" in spec["must_find"]["root_cause"].lower() or \
               "mix_shift" in spec["must_find"]["root_cause"].lower()
        assert "tenant_tier" in spec["must_check_dimensions"]

    def test_case5_is_false_alarm(self):
        """Case 5 (S0) should test false alarm / restraint."""
        spec = self._load_spec("case5_false_alarm.yaml")
        assert spec["case"]["scenario"] == "S0"
        assert spec["case"]["archetype"] == "false_alarm_restraint"
        assert spec["case"]["pass_threshold"] == "2/3 GREEN"
        # Must find no significant movement
        root = spec["must_find"]["root_cause"].lower()
        assert "no significant" in root or "normal" in root or "within" in root


# ──────────────────────────────────────────────────
# Test Group 4: Eval Runner
# ──────────────────────────────────────────────────

class TestEvalRunner:
    """Tests for eval/run_eval.py — the eval runner skeleton."""

    def test_runner_module_exists(self):
        """eval/run_eval.py must exist as a module."""
        runner_path = EVAL_DIR / "run_eval.py"
        assert runner_path.exists(), "eval/run_eval.py not found"

    def test_runner_is_importable(self):
        """eval/run_eval.py should be importable as a module."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    def test_load_scoring_specs(self):
        """load_scoring_specs() should return a list of all 5 spec dicts."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        specs = module.load_scoring_specs()
        assert len(specs) == 5, f"Expected 5 specs, got {len(specs)}"
        # Verify each has case info
        for s in specs:
            assert "case" in s
            assert "rubric" in s

    def test_score_single_run(self):
        """score_single_run() should return a score dict with total and per-dimension."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Load case 1 spec
        specs = module.load_scoring_specs()
        case1_spec = next(s for s in specs if s["case"]["scenario"] == "S4")

        # Create a mock diagnosis output that should score well
        mock_diagnosis = {
            "aggregate": {
                "metric": "dlctr_value",
                "direction": "down",
                "relative_delta_pct": -6.25,
                "severity": "P0",
            },
            "primary_hypothesis": {
                "dimension": "tenant_tier",
                "segment": "standard",
                "contribution_pct": 82.0,
                "description": "Ranking model change degraded Standard tier queries",
            },
            "confidence": {
                "level": "High",
                "reasoning": "All checks passed, 92% explained, historical precedent.",
                "would_upgrade_if": None,
                "would_downgrade_if": "explained_pct drops below 90%",
            },
            "validation_checks": [
                {"check": "logging_artifact", "status": "PASS", "detail": "No step-change"},
                {"check": "decomposition_completeness", "status": "PASS", "detail": "92% explained"},
                {"check": "temporal_consistency", "status": "PASS", "detail": "Consistent"},
                {"check": "mix_shift", "status": "PASS", "detail": "Low mix-shift"},
            ],
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 82.0, "delta": -0.05},
                        {"segment_value": "premium", "contribution_pct": 10.0, "delta": -0.005},
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 8.0},
            "action_items": [
                "Check ranking model version deployed to Standard tier",
                "Review A/B test results for recent ranking changes",
            ],
        }

        # Format the diagnosis output (simulating what the formatter produces)
        from tools.formatter import format_diagnosis_output
        formatted = format_diagnosis_output(mock_diagnosis)

        result = module.score_single_run(case1_spec, mock_diagnosis, formatted)

        # Result should have required keys
        assert "total_score" in result
        assert "per_dimension" in result
        assert "grade" in result
        assert result["total_score"] >= 0
        assert result["total_score"] <= 100
        # A well-constructed diagnosis should score GREEN (>=80)
        assert result["grade"] == "GREEN", (
            f"Good diagnosis scored {result['grade']} ({result['total_score']}pts). "
            f"Per-dimension: {json.dumps({k: v['earned'] for k, v in result['per_dimension'].items()})}"
        )

    def test_aggregate_runs(self):
        """aggregate_runs() should produce GREEN/YELLOW/RED from 3 run scores."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 3/3 GREEN => GREEN
        runs_3g = [
            {"total_score": 85, "grade": "GREEN"},
            {"total_score": 90, "grade": "GREEN"},
            {"total_score": 82, "grade": "GREEN"},
        ]
        result = module.aggregate_runs(runs_3g, "3/3 GREEN")
        assert result["verdict"] == "GREEN"

        # 2/3 GREEN with 2/3 threshold => GREEN
        runs_2g = [
            {"total_score": 85, "grade": "GREEN"},
            {"total_score": 50, "grade": "RED"},
            {"total_score": 82, "grade": "GREEN"},
        ]
        result = module.aggregate_runs(runs_2g, "2/3 GREEN")
        assert result["verdict"] == "GREEN"

        # 1/3 GREEN with 3/3 threshold => RED
        runs_1g = [
            {"total_score": 85, "grade": "GREEN"},
            {"total_score": 50, "grade": "RED"},
            {"total_score": 55, "grade": "RED"},
        ]
        result = module.aggregate_runs(runs_1g, "3/3 GREEN")
        assert result["verdict"] == "RED"

    def test_bad_diagnosis_scores_red(self):
        """A completely wrong diagnosis should score RED."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        specs = module.load_scoring_specs()
        case1_spec = next(s for s in specs if s["case"]["scenario"] == "S4")

        # Wrong root cause, wrong confidence, no investigation, no actions
        bad_diagnosis = {
            "aggregate": {"metric": "dlctr_value", "direction": "down",
                         "relative_delta_pct": -6.25, "severity": "P2"},
            "primary_hypothesis": {
                "dimension": "unknown", "segment": "",
                "contribution_pct": 0,
                "description": "Seasonal user behavior pattern",
            },
            "confidence": {"level": "Low", "reasoning": "Not sure",
                          "would_upgrade_if": None, "would_downgrade_if": None},
            "validation_checks": [],
            "dimensional_breakdown": {},
            "mix_shift": {},
            "action_items": [],
        }

        from tools.formatter import format_diagnosis_output
        formatted = format_diagnosis_output(bad_diagnosis)

        result = module.score_single_run(case1_spec, bad_diagnosis, formatted)
        assert result["grade"] == "RED", (
            f"Wrong diagnosis scored {result['grade']} ({result['total_score']}pts)"
        )

    def test_aggregate_runs_yellow_for_2_green_with_3_threshold(self):
        """2/3 GREEN with 3/3 threshold should be YELLOW (close but not passing)."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        runs = [
            {"total_score": 85, "grade": "GREEN"},
            {"total_score": 82, "grade": "GREEN"},
            {"total_score": 50, "grade": "RED"},
        ]
        result = module.aggregate_runs(runs, "3/3 GREEN")
        assert result["verdict"] == "YELLOW", (
            f"2/3 GREEN with 3/3 threshold should be YELLOW, got {result['verdict']}"
        )

    def test_must_not_do_violations_deduct_points(self):
        """Violating must_not_do rules should reduce the score."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        specs = module.load_scoring_specs()
        case1_spec = next(s for s in specs if s["case"]["scenario"] == "S4")

        # Create a diagnosis that VIOLATES must_not_do: hedges excessively
        hedging_diagnosis = {
            "aggregate": {"metric": "dlctr_value", "direction": "down",
                         "relative_delta_pct": -6.25, "severity": "P0"},
            "primary_hypothesis": {
                "dimension": "tenant_tier", "segment": "standard",
                "contribution_pct": 82.0,
                "description": "Might be ranking model, possibly something else",
            },
            "confidence": {"level": "Low", "reasoning": "Uncertain",
                          "would_upgrade_if": None, "would_downgrade_if": None},
            "validation_checks": [],
            "dimensional_breakdown": {},
            "mix_shift": {},
            "action_items": [],
        }

        from tools.formatter import format_diagnosis_output
        formatted = format_diagnosis_output(hedging_diagnosis)

        result = module.score_single_run(case1_spec, hedging_diagnosis, formatted)
        # Should NOT get GREEN with a hedging diagnosis
        assert result["grade"] != "GREEN" or result["total_score"] < 80


# ──────────────────────────────────────────────────
# Test Group 5: LLM-as-Judge Prompt Construction
# ──────────────────────────────────────────────────

class TestJudgePromptConstruction:
    """Verify the LLM-as-judge prompt builder produces unambiguous prompts."""

    def test_build_judge_prompt_contains_rubric(self):
        """The judge prompt should contain the full rubric verbatim."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        specs = module.load_scoring_specs()
        case1_spec = specs[0]

        prompt = module.build_judge_prompt(case1_spec, "mock diagnosis output")

        # Must contain the rubric dimensions
        assert "root_cause_accuracy" in prompt
        assert "confidence_calibration" in prompt
        assert "investigation_completeness" in prompt
        assert "actionability" in prompt
        # Must contain the must_find root cause
        assert case1_spec["must_find"]["root_cause"] in prompt
        # Must contain must_not_do items
        for anti in case1_spec["must_not_do"]:
            if isinstance(anti, dict):
                for key in anti:
                    assert key in prompt

    def test_build_judge_prompt_requests_json_output(self):
        """The judge prompt should request structured JSON output."""
        import importlib.util
        runner_path = EVAL_DIR / "run_eval.py"
        spec = importlib.util.spec_from_file_location("run_eval", runner_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        specs = module.load_scoring_specs()
        prompt = module.build_judge_prompt(specs[0], "mock output")

        assert "json" in prompt.lower() or "JSON" in prompt
