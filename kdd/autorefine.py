"""AutoRefine mutation runner — systematically tests prompt variations.

HOW IT WORKS (the "AutoRefine loop"):
1. Run canary tasks with the CURRENT (baseline) prompts
2. For each mutation:
   a. Apply mutation overrides via set_prompt_config()
   b. Run canary tasks with the mutated prompts
   c. Compare to baseline: did accuracy go up? any regressions?
   d. Reset prompts via reset_prompt_config()
3. Return a report: which mutations helped, which hurt, which need investigation

WHY THIS EXISTS:
Prompt engineering is empirical — you can't tell if "emphasize table names more"
helps or hurts without actually running it. AutoRefine automates the test loop
so we get data instead of opinions. Think of it as A/B testing for prompts,
but run sequentially against a fixed canary set.

ANALOGY FOR DATA SCIENTISTS:
This is a hyperparameter sweep, but for prompt text instead of learning rates.
The "canary tasks" are your validation set. Each mutation is one hyperparameter
configuration. The verdict logic is your early-stopping criterion.

DEPENDENCIES (built in parallel lanes):
- kdd.canary (Lane A): run_canary(), CANARY_TASKS
- domains.data_analysis.prompts (Lane B): PROMPT_CONFIG, set_prompt_config(), reset_prompt_config()

CLI usage:
    python -m kdd.autorefine
    python -m kdd.autorefine --mutations explicit_table_list,strict_cast_hints
    python -m kdd.autorefine --verbose
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, List, Optional

# Lane A dependency: canary task runner
from kdd.canary import run_canary, CANARY_TASKS

# Lane B dependency: prompt config (mutable global prompt variables)
from domains.data_analysis.prompts import (
    PROMPT_CONFIG,
    set_prompt_config,
    reset_prompt_config,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mutation definitions — each overrides one or more PROMPT_CONFIG keys
# ---------------------------------------------------------------------------
# These are the prompt variations we want to test. Each mutation is a small,
# targeted change to one aspect of the prompts. We test them in isolation
# so we know WHICH change caused any improvement or regression.
#
# WHY NOT TEST COMBINATIONS: Combinatorial explosion. With 5 mutations,
# there are 31 non-empty subsets. Testing each takes ~$0.05 in API cost
# (5 canary tasks x $0.004/call x 2 calls/task). Running all 31 combos
# costs ~$1.55 vs ~$0.25 for single mutations. Start with singles, then
# combine the winners in a follow-up round.

MUTATIONS: List[Dict[str, Any]] = [
    {
        "name": "explicit_table_list",
        "description": "Repeat table names in the instruction itself",
        "overrides": {
            "schema_emphasis": (
                "CRITICAL: The ONLY available tables are listed above. "
                "Your SQL MUST reference exactly these table names. "
                "If you use any table name not in the list, the query WILL fail."
            ),
        },
    },
    {
        "name": "no_join_preference",
        "description": "Remove the preference for simple queries over JOINs",
        "overrides": {
            "approach_strategy": (
                "Use JOINs when the question requires data from multiple tables. "
                "Match ON conditions to the schema's foreign keys."
            ),
        },
    },
    {
        "name": "values_only_output",
        "description": "Tell SYNTHESIZE to output only values, no headers",
        "overrides": {
            "output_format": (
                "Output ONLY the data values. No column headers. "
                "One value per line."
            ),
        },
    },
    {
        "name": "strict_cast_hints",
        "description": "More aggressive type casting instructions",
        "overrides": {
            "sql_dialect_hints": (
                "DuckDB is STRICT about types. ALWAYS use CAST() when comparing "
                "different types: CAST(col AS INTEGER), CAST(col AS DATE), "
                "CAST(col AS DOUBLE). Never compare VARCHAR to INTEGER directly. "
                "For dates stored as strings, use CAST(date_col AS DATE). "
                "For apostrophes in strings, use '' not backslash."
            ),
        },
    },
    {
        "name": "fewer_approaches",
        "description": "Generate only 1 approach instead of up to 3",
        "overrides": {
            "max_approaches": 1,
        },
    },
]


# ---------------------------------------------------------------------------
# Verdict logic — decides keep / discard / investigate per mutation
# ---------------------------------------------------------------------------
# The verdict determines what to do with a mutation:
#   "keep"        — mutation improves accuracy with no regressions
#   "discard"     — mutation caused regressions (accuracy went down)
#   "investigate" — mixed results: some improvements AND some regressions
#
# WHY REGRESSIONS MATTER MORE THAN IMPROVEMENTS:
# A mutation that fixes 2 tasks but breaks 1 is net-positive by accuracy,
# but the broken task might be a critical category. We flag it as
# "investigate" rather than auto-accepting. Safety over speed.

def _compute_verdict(
    baseline_result: Dict[str, Any],
    mutation_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare a mutation's canary result against the baseline.

    Computes the accuracy delta and identifies which tasks changed.
    Returns a dict with delta metrics, changed task lists, and a verdict.

    Args:
        baseline_result: Output from run_canary() with baseline prompts.
        mutation_result: Output from run_canary() with mutated prompts.

    Returns:
        {
            "delta_completed": int,   # change in completed count vs baseline
            "delta_accurate": int,    # change in accurate count vs baseline
            "regressions": [...],     # task_ids that went from pass -> fail
            "improvements": [...],    # task_ids that went from fail -> pass
            "verdict": "keep" | "discard" | "investigate",
        }
    """
    # Extract per-task results for comparison.
    # run_canary returns {"results": {task_id: {"match": bool, ...}, ...}}
    baseline_tasks = baseline_result.get("results", {})
    mutation_tasks = mutation_result.get("results", {})

    # Compute deltas on the aggregate counts
    delta_completed = (
        mutation_result.get("completed", 0)
        - baseline_result.get("completed", 0)
    )
    delta_accurate = (
        mutation_result.get("accurate", 0)
        - baseline_result.get("accurate", 0)
    )

    # Find per-task regressions and improvements
    regressions = []
    improvements = []

    for task_id in baseline_tasks:
        baseline_match = baseline_tasks[task_id].get("match", False)
        mutation_match = mutation_tasks.get(task_id, {}).get("match", False)

        if baseline_match and not mutation_match:
            # This task PASSED at baseline but FAILED with the mutation — regression
            regressions.append(task_id)
        elif not baseline_match and mutation_match:
            # This task FAILED at baseline but PASSED with the mutation — improvement
            improvements.append(task_id)

    # --- Verdict logic ---
    # Priority: no regressions > accuracy improvement > investigation
    if delta_accurate > 0 and len(regressions) == 0:
        verdict = "keep"
    elif len(regressions) > 0 and len(improvements) == 0:
        # Pure regression: accuracy went down (or stayed same) with regressions
        verdict = "discard"
    elif len(regressions) > 0 and len(improvements) > 0:
        # Mixed: some better, some worse — needs human review
        verdict = "investigate"
    elif delta_accurate < 0:
        # Accuracy dropped even without specific task regressions
        # (e.g., a new task failed to complete entirely)
        verdict = "discard"
    else:
        # No change in accuracy, no regressions — mutation had no effect
        verdict = "discard"

    return {
        "delta_completed": delta_completed,
        "delta_accurate": delta_accurate,
        "regressions": regressions,
        "improvements": improvements,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Main entry point — the AutoRefine loop
# ---------------------------------------------------------------------------

def run_autorefine(
    llm_callable,
    mutations: Optional[List[Dict[str, Any]]] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Run the AutoRefine loop: baseline -> mutate -> evaluate -> compare.

    Steps:
    1. Run canary tasks with current (baseline) prompts
    2. For each mutation:
       a. Apply mutation via set_prompt_config()
       b. Run canary tasks
       c. Compare to baseline (regressions? improvements?)
       d. Reset prompts via reset_prompt_config()
    3. Return report: which mutations helped, which hurt

    Args:
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
            Same interface used by kdd.runner.
        mutations: List of mutation dicts to test. If None, uses MUTATIONS
            (the built-in set of prompt variations).
        verbose: If True, include full canary results in the output.
            If False, only include summary metrics.

    Returns:
        {
            "baseline": canary_result,
            "mutations": [
                {
                    "name": str,
                    "description": str,
                    "result": canary_result,       # only when verbose=True
                    "delta_completed": int,
                    "delta_accurate": int,
                    "regressions": [str, ...],
                    "improvements": [str, ...],
                    "verdict": "keep" | "discard" | "investigate",
                },
            ],
            "best_mutation": str | None,  # name of best, or None if baseline wins
        }
    """
    # Use the default mutation set if none provided
    if mutations is None:
        mutations = MUTATIONS

    # --- Step 1: Run baseline ---
    # The baseline uses whatever prompts are currently configured.
    # We DON'T call reset_prompt_config() here because the caller may have
    # intentionally set a custom config before calling run_autorefine().
    logger.info("Running baseline canary tasks (%d tasks)", len(CANARY_TASKS))
    baseline = run_canary(llm_callable)
    logger.info(
        "Baseline: %d/%d completed, %d accurate",
        baseline.get("completed", 0),
        len(CANARY_TASKS),
        baseline.get("accurate", 0),
    )

    # --- Step 2: Test each mutation ---
    mutation_reports = []

    for mutation in mutations:
        name = mutation["name"]
        description = mutation.get("description", "")
        overrides = mutation.get("overrides", {})

        logger.info("Testing mutation: %s (%s)", name, description)

        # 2a. Apply the mutation's prompt overrides
        set_prompt_config(overrides)

        try:
            # 2b. Run canary tasks with mutated prompts
            mutation_result = run_canary(llm_callable)

            # 2c. Compare against baseline
            comparison = _compute_verdict(baseline, mutation_result)

            report = {
                "name": name,
                "description": description,
                "delta_completed": comparison["delta_completed"],
                "delta_accurate": comparison["delta_accurate"],
                "regressions": comparison["regressions"],
                "improvements": comparison["improvements"],
                "verdict": comparison["verdict"],
            }

            # Include full canary result only when verbose (saves memory)
            if verbose:
                report["result"] = mutation_result

            mutation_reports.append(report)

            logger.info(
                "  Mutation '%s': delta_accurate=%+d, verdict=%s, "
                "regressions=%s, improvements=%s",
                name,
                comparison["delta_accurate"],
                comparison["verdict"],
                comparison["regressions"],
                comparison["improvements"],
            )

        finally:
            # 2d. ALWAYS reset prompts back to defaults, even on error.
            # Without this, a crashed mutation would leave dirty config
            # for the next mutation — cascading failures.
            reset_prompt_config()

    # --- Step 3: Find the best mutation ---
    # "Best" = highest delta_accurate among mutations with verdict="keep".
    # If no mutation is better than baseline, best_mutation is None.
    best_mutation = _find_best_mutation(mutation_reports)

    result = {
        "baseline": baseline if verbose else _summarize_canary(baseline),
        "mutations": mutation_reports,
        "best_mutation": best_mutation,
    }

    return result


def _find_best_mutation(reports: List[Dict[str, Any]]) -> Optional[str]:
    """Find the best mutation among those with verdict="keep".

    Returns the mutation name with the highest delta_accurate,
    or None if no mutation beat the baseline.

    Tiebreaker: if two mutations have the same delta_accurate,
    prefer the one with fewer overrides (simpler change).
    """
    keepers = [r for r in reports if r["verdict"] == "keep"]

    if not keepers:
        return None

    # Sort by delta_accurate descending; ties broken by name (deterministic)
    keepers.sort(key=lambda r: (-r["delta_accurate"], r["name"]))
    return keepers[0]["name"]


def _summarize_canary(canary_result: Dict[str, Any]) -> Dict[str, Any]:
    """Create a compact summary of a canary result (for non-verbose mode).

    Strips the per-task result details to save output space.
    Keeps only the aggregate counts.
    """
    return {
        "completed": canary_result.get("completed", 0),
        "accurate": canary_result.get("accurate", 0),
        "regressions": canary_result.get("regressions", []),
        "improvements": canary_result.get("improvements", []),
    }


# ---------------------------------------------------------------------------
# CLI entrypoint: python -m kdd.autorefine
# ---------------------------------------------------------------------------

def _print_summary_table(result: Dict[str, Any]) -> None:
    """Print a human-readable summary table to stdout.

    Shows baseline stats and a row per mutation with verdict.
    Designed for quick scanning in a terminal.
    """
    baseline = result["baseline"]
    mutations = result["mutations"]

    # Header
    print("\n=== AutoRefine Results ===\n")
    print(
        f"Baseline: {baseline.get('completed', '?')} completed, "
        f"{baseline.get('accurate', '?')} accurate"
    )
    print()

    # Column headers for the mutation table
    header = f"{'Mutation':<25} {'Δ Accurate':>10} {'Regressions':>12} {'Improvements':>13} {'Verdict':>12}"
    print(header)
    print("-" * len(header))

    for m in mutations:
        # Format delta with +/- sign for clarity
        delta = f"{m['delta_accurate']:+d}"
        reg_count = str(len(m["regressions"]))
        imp_count = str(len(m["improvements"]))
        verdict = m["verdict"].upper()

        print(
            f"{m['name']:<25} {delta:>10} {reg_count:>12} {imp_count:>13} {verdict:>12}"
        )

    # Bottom line — the recommendation
    print()
    best = result.get("best_mutation")
    if best:
        print(f">>> Best mutation: {best}")
    else:
        print(">>> No mutation beat the baseline. Current prompts are best.")
    print()


def main():
    """CLI entrypoint — runs the full AutoRefine loop and prints results.

    Supports filtering to specific mutations via --mutations flag.
    Always prints a summary table; use --verbose for full JSON output.
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="AutoRefine: systematic prompt mutation testing.",
        epilog=(
            "Examples:\n"
            "  python -m kdd.autorefine\n"
            "  python -m kdd.autorefine --mutations explicit_table_list,strict_cast_hints\n"
            "  python -m kdd.autorefine --verbose --output autorefine_results.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mutations",
        help=(
            "Comma-separated list of mutation names to test. "
            "If omitted, tests all built-in mutations."
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Include full canary results in output.",
    )
    parser.add_argument(
        "--output",
        help="Write full JSON results to this file.",
    )
    parser.add_argument(
        "--model", default="",
        help="LLM model name. Default reads from env.",
    )

    args = parser.parse_args()

    # --- Filter mutations if --mutations flag provided ---
    selected_mutations = None
    if args.mutations:
        requested_names = set(args.mutations.split(","))
        available_names = {m["name"] for m in MUTATIONS}
        unknown = requested_names - available_names
        if unknown:
            print(
                f"Error: Unknown mutation(s): {', '.join(sorted(unknown))}\n"
                f"Available: {', '.join(sorted(available_names))}",
                file=sys.stderr,
            )
            sys.exit(1)
        selected_mutations = [
            m for m in MUTATIONS if m["name"] in requested_names
        ]

    # --- Create LLM callable ---
    # Reuse the runner's CLI LLM factory for consistency
    from kdd.runner import _make_cli_llm
    llm = _make_cli_llm(args.model)

    # --- Run the AutoRefine loop ---
    result = run_autorefine(
        llm_callable=llm,
        mutations=selected_mutations,
        verbose=args.verbose,
    )

    # --- Output ---
    # Always print the human-readable summary table
    _print_summary_table(result)

    # Optionally write full JSON to a file
    if args.output:
        output_text = json.dumps(result, indent=2, default=str)
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"Full results written to {args.output}")

    # Exit 0 if we found a better mutation, 1 if baseline wins.
    # This lets CI scripts chain: if autorefine finds improvement, apply it.
    sys.exit(0 if result.get("best_mutation") else 1)


if __name__ == "__main__":
    main()
