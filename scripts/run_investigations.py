#!/usr/bin/env python3
"""Run investigation scenarios across multiple OpenAI-compatible models.

Loads 5 synthetic investigation scenarios, runs each through the full
orchestrator pipeline with each model, and outputs a comparison table
with automated pass/fail oracle checks.

Usage:
    .venv/bin/python scripts/run_investigations.py
    .venv/bin/python scripts/run_investigations.py --models deepseek qwen
    .venv/bin/python scripts/run_investigations.py --scenarios ranking_regression normal_variance

WHY this script:
    Running 5 scenarios × 4 models = 20 combinations manually is tedious.
    The lightweight oracle automates basic validation so you only need to
    manually inspect failures, not successes.
"""

import argparse
import csv
import json
import os
import sys
import time

# Add project root to path so we can import harness modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.llm import make_openai_llm
from harness.orchestrator import SearchMetricOrchestrator


# ---------------------------------------------------------------------------
# Scenario definitions — each has inputs for the orchestrator + oracle criteria
# ---------------------------------------------------------------------------

SCENARIOS = {
    "ranking_regression": {
        "csv": "data/investigations/scenario_ranking_regression.csv",
        "question": "Click Quality dropped 3.5% week-over-week. What caused this?",
        "metric_field": "click_quality_value",
        "dimensions": ["tenant_tier", "ai_enablement", "connector_type"],
        # Oracle: what keywords should appear in root_cause?
        "expected_keywords": ["ranking", "model", "algorithm"],
        "expected_severities": ["P1"],
    },
    "ai_adoption_positive": {
        "csv": "data/investigations/scenario_ai_adoption_positive.csv",
        "question": "Click Quality dropped 4% WoW for the ai_on segment. Is this a regression?",
        "metric_field": "click_quality_value",
        "dimensions": ["tenant_tier", "ai_enablement"],
        "expected_keywords": ["ai", "adoption", "positive", "expected", "inverse"],
        "expected_severities": ["normal", "P2"],
    },
    "connector_failure": {
        "csv": "data/investigations/scenario_connector_failure.csv",
        "question": "Click Quality dropped significantly for the confluence connector. What happened?",
        "metric_field": "click_quality_value",
        "dimensions": ["connector_type", "tenant_tier"],
        "expected_keywords": ["connector", "confluence", "pipeline", "data"],
        "expected_severities": ["P0", "P1"],
    },
    "mix_shift": {
        "csv": "data/investigations/scenario_mix_shift.csv",
        "question": "Click Quality dropped 2% WoW at the aggregate level. What caused this?",
        "metric_field": "click_quality_value",
        "dimensions": ["tenant_tier", "ai_enablement"],
        "expected_keywords": ["mix", "composition", "shift", "segment", "proportion"],
        "expected_severities": ["P1", "P2"],
    },
    "normal_variance": {
        "csv": "data/investigations/scenario_normal_variance.csv",
        "question": "Click Quality changed 0.5% WoW. Should we investigate?",
        "metric_field": "click_quality_value",
        "dimensions": ["tenant_tier", "ai_enablement"],
        "expected_keywords": ["normal", "variance", "fluctuation", "within", "noise"],
        "expected_severities": ["normal", "P2"],
    },
}


# ---------------------------------------------------------------------------
# Model definitions — ID + display name
# ---------------------------------------------------------------------------

MODELS = {
    "deepseek": {
        "id": "deepseek/deepseek-v3.2",
        "name": "DeepSeek V3.2",
    },
    "gpt_oss": {
        "id": "openai/gpt-oss-120b",
        "name": "GPT-OSS 120B",
    },
    "qwen": {
        "id": "qwen/qwen3-235b-a22b-instruct-2507",
        "name": "Qwen3 235B",
    },
    "kimi": {
        "id": "moonshotai/kimi-k2-instruct",
        "name": "Kimi K2",
    },
}


def load_csv(path: str) -> list[dict]:
    """Load a CSV file into a list of row dicts."""
    with open(path) as f:
        return list(csv.DictReader(f))


def check_oracle(
    synthesis: dict,
    expected_keywords: list[str],
    expected_severities: list[str],
) -> tuple[bool, str]:
    """Check if the investigation result matches oracle criteria.

    Returns (passed, reason) tuple.

    WHY lightweight oracle: We can't perfectly judge diagnosis quality
    automatically, but we CAN check that the root cause contains
    expected domain terms and the severity is in the right ballpark.
    This catches gross failures (wrong diagnosis, wrong severity)
    while accepting reasonable variation in wording.
    """
    root_cause = str(synthesis.get("root_cause", "")).lower()
    severity = str(synthesis.get("severity", "")).lower()
    tldr = str(synthesis.get("tldr", "")).lower()

    # Check keywords — at least one must appear in root_cause or tldr
    combined_text = root_cause + " " + tldr
    keyword_match = any(kw in combined_text for kw in expected_keywords)

    # Check severity — must be one of the expected values
    severity_match = any(
        severity == exp.lower() for exp in expected_severities
    )

    if not keyword_match and not severity_match:
        return False, f"No keyword match AND wrong severity ({severity})"
    if not keyword_match:
        return False, f"No keyword match in root_cause/tldr"
    if not severity_match:
        return False, f"Wrong severity: got {severity}, expected {expected_severities}"

    return True, "OK"


def run_one(
    scenario_key: str,
    scenario: dict,
    model_key: str,
    model: dict,
    base_url: str,
) -> dict:
    """Run a single (scenario, model) investigation and return results."""
    print(f"  [{model['name']}] × [{scenario_key}] ...", end=" ", flush=True)

    try:
        llm = make_openai_llm(
            base_url=base_url,
            model=model["id"],
        )
        orch = SearchMetricOrchestrator(llm_callable=llm)
        rows = load_csv(scenario["csv"])

        start = time.time()
        result = orch.run(
            question=scenario["question"],
            rows=rows,
            metric_field=scenario["metric_field"],
            dimensions=scenario["dimensions"],
        )
        elapsed = time.time() - start

        # Extract synthesis (the final report)
        synthesis = result.get("synthesis", {})
        stages = result.get("stages_completed", [])
        mode = result.get("mode", "unknown")

        # Run oracle check
        passed, reason = check_oracle(
            synthesis,
            scenario["expected_keywords"],
            scenario["expected_severities"],
        )

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({elapsed:.1f}s) — {reason}")

        return {
            "scenario": scenario_key,
            "model": model["name"],
            "status": status,
            "reason": reason,
            "severity": synthesis.get("severity", "?"),
            "mode": mode,
            "stages": len(stages),
            "elapsed": round(elapsed, 1),
            "error": None,
        }

    except Exception as exc:
        print(f"ERROR — {type(exc).__name__}: {exc}")
        return {
            "scenario": scenario_key,
            "model": model["name"],
            "status": "ERROR",
            "reason": str(exc)[:100],
            "severity": "?",
            "mode": "?",
            "stages": 0,
            "elapsed": 0,
            "error": type(exc).__name__,
        }


def print_results_table(results: list[dict]) -> None:
    """Print a formatted comparison table of all results."""
    print("\n" + "=" * 90)
    print("INVESTIGATION RESULTS MATRIX")
    print("=" * 90)
    print(
        f"{'Scenario':<25} {'Model':<16} {'Status':<7} {'Sev':<7} "
        f"{'Mode':<8} {'Time':<7} {'Reason'}"
    )
    print("-" * 90)

    for r in results:
        print(
            f"{r['scenario']:<25} {r['model']:<16} {r['status']:<7} "
            f"{r['severity']:<7} {r['mode']:<8} {r['elapsed']:<7} "
            f"{r['reason'][:30]}"
        )

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")

    print("-" * 90)
    print(f"TOTAL: {total} | PASS: {passed} | FAIL: {failed} | ERROR: {errors}")
    print(f"Pass rate: {passed / total * 100:.0f}%" if total > 0 else "No results")
    print("=" * 90)


def main():
    parser = argparse.ArgumentParser(
        description="Run investigation scenarios across multiple models."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=list(MODELS.keys()),
        default=list(MODELS.keys()),
        help="Which models to test (default: all)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=list(SCENARIOS.keys()),
        default=list(SCENARIOS.keys()),
        help="Which scenarios to test (default: all)",
    )
    parser.add_argument(
        "--base-url",
        default="https://api.novita.ai/openai/v1",
        help="OpenAI-compatible API base URL",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay in seconds between investigations (avoid rate limits)",
    )
    args = parser.parse_args()

    print(f"Running {len(args.scenarios)} scenarios × {len(args.models)} models")
    print(f"Base URL: {args.base_url}")
    print()

    results = []
    for scenario_key in args.scenarios:
        scenario = SCENARIOS[scenario_key]
        for model_key in args.models:
            model = MODELS[model_key]
            result = run_one(scenario_key, scenario, model_key, model, args.base_url)
            results.append(result)

            # Delay between runs to avoid rate limits
            if args.delay > 0:
                time.sleep(args.delay)

    print_results_table(results)

    # Save results to JSON for later analysis
    output_path = "data/investigation_results.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
