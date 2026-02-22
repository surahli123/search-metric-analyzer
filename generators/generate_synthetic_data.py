#!/usr/bin/env python3
"""Generate synthetic search session and metric aggregate CSVs for scenarios S0-S8.

Stdlib-only implementation.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import random
from pathlib import Path
from typing import Dict, List, Tuple

BASELINE = {
    "dlctr_mean": 0.280,
    "sain_trigger_rate": 0.220,
    "sain_success_rate": 0.620,
    "p3_click_share": 0.270,
    "mean_clicked_rank": 2.6,
    "exploratory_share": 0.50,
}

# Baseline expected QSR from canonical formula using baseline rates.
BASELINE_QSR = BASELINE["dlctr_mean"] + (
    BASELINE["sain_trigger_rate"] * BASELINE["sain_success_rate"]
) * (1 - BASELINE["dlctr_mean"])

SCENARIOS: Dict[str, Dict[str, float | str | bool]] = {
    "S0": {
        "name": "Baseline stable",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "sain_trigger_delta": 0.00,
        "sain_success_delta": 0.00,
        "expected_dlctr_delta": 0.000,
        "expected_qsr_delta": 0.000,
        "seasonality": "none",
        "l3_marker": False,
        "sain_marker": False,
    },
    "S1": {
        "name": "Normal seasonality",
        "volume_delta_rel": 0.06,
        "exploratory_delta": 0.04,
        "p3_delta": 0.00,
        "rank_delta": 0.10,
        "sain_trigger_delta": 0.00,
        "sain_success_delta": 0.00,
        "expected_dlctr_delta": 0.000,
        "expected_qsr_delta": 0.000,
        "seasonality": "weekly_pattern",
        "l3_marker": False,
        "sain_marker": False,
    },
    "S2": {
        "name": "Seasonality shock",
        "volume_delta_rel": 0.18,
        "exploratory_delta": 0.12,
        "p3_delta": 0.00,
        "rank_delta": 0.20,
        "sain_trigger_delta": 0.00,
        "sain_success_delta": 0.00,
        "expected_dlctr_delta": -0.015,
        "expected_qsr_delta": -0.010,
        "seasonality": "holiday_shock",
        "l3_marker": False,
        "sain_marker": False,
    },
    "S3": {
        "name": "L3 3P boost benign",
        "volume_delta_rel": 0.02,
        "exploratory_delta": 0.08,
        "p3_delta": 0.08,
        "rank_delta": 0.20,
        "sain_trigger_delta": 0.00,
        "sain_success_delta": 0.00,
        "expected_dlctr_delta": -0.006,
        "expected_qsr_delta": 0.004,
        "seasonality": "none",
        "l3_marker": True,
        "sain_marker": False,
    },
    "S4": {
        "name": "L3 3P overboost regression",
        "volume_delta_rel": 0.01,
        "exploratory_delta": -0.05,
        "p3_delta": 0.18,
        "rank_delta": 0.80,
        "sain_trigger_delta": 0.00,
        "sain_success_delta": 0.00,
        "expected_dlctr_delta": -0.035,
        "expected_qsr_delta": -0.022,
        "seasonality": "none",
        "l3_marker": True,
        "sain_marker": False,
    },
    "S5": {
        "name": "SAIN uplift with click cannibalization",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.50,
        "sain_trigger_delta": 0.12,
        "sain_success_delta": 0.10,
        "expected_dlctr_delta": -0.020,
        "expected_qsr_delta": 0.006,
        "seasonality": "none",
        "l3_marker": False,
        "sain_marker": True,
    },
    "S6": {
        "name": "SAIN regression",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.10,
        "sain_trigger_delta": 0.10,
        "sain_success_delta": -0.25,
        "expected_dlctr_delta": 0.000,
        "expected_qsr_delta": -0.030,
        "seasonality": "none",
        "l3_marker": False,
        "sain_marker": True,
    },
    "S7": {
        "name": "Overlap seasonality + L3",
        "volume_delta_rel": 0.19,
        "exploratory_delta": 0.07,
        "p3_delta": 0.18,
        "rank_delta": 1.00,
        "sain_trigger_delta": 0.00,
        "sain_success_delta": 0.00,
        "expected_dlctr_delta": -0.045,
        "expected_qsr_delta": -0.030,
        "seasonality": "holiday_shock",
        "l3_marker": True,
        "sain_marker": False,
    },
    "S8": {
        "name": "Logging anomaly",
        "volume_delta_rel": 0.00,
        "exploratory_delta": 0.00,
        "p3_delta": 0.00,
        "rank_delta": 0.00,
        "sain_trigger_delta": 0.00,
        "sain_success_delta": 0.00,
        "expected_dlctr_delta": 0.000,
        "expected_qsr_delta": 0.000,
        "seasonality": "none",
        "l3_marker": False,
        "sain_marker": False,
    },
}

SESSION_HEADERS = [
    "session_id",
    "query_id",
    "event_ts",
    "query_token",
    "query_class",
    "seasonality_tag",
    "sain_experience_type",
    "sain_trigger",
    "sain_success",
    "sain_engaged",
    "ranked_results_json",
    "clicked_rank",
    "clicked_doc_token",
    "clicked_connector",
    "click_ts",
    "release_id",
    "experiment_id",
    "scenario_id",
]

METRIC_HEADERS = [
    "session_id",
    "query_id",
    "metric_ts",
    "dlctr_value",
    "is_long_click",
    "dlctr_discount_weight",
    "sain_trigger",
    "sain_success",
    "qsr_component_click",
    "qsr_component_sain",
    "qsr_value",
    "qsr_dominant_component",
    "p3_click_share",
    "mean_clicked_rank",
    "clicked_flag",
    "freshness_lag_min",
    "completeness_pct",
    "join_coverage_pct",
    "scenario_id",
]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def discount(rank: int) -> float:
    return 1.0 / math.log2(rank + 1)


def rank_from_mean(mean_rank: float, rng: random.Random) -> int:
    sampled = int(round(rng.gauss(mean_rank, 1.2)))
    return int(clamp(sampled, 1, 10))


def estimate_discount_from_sampler(mean_rank: float, seed: int, samples: int = 4000) -> float:
    """Estimate expected discount using the same rank sampler as generation."""
    est_rng = random.Random(seed)
    vals: List[float] = []
    for _ in range(samples):
        vals.append(discount(rank_from_mean(mean_rank, est_rng)))
    return sum(vals) / len(vals)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic search validation datasets")
    parser.add_argument("--rows-per-scenario", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="data/synthetic")
    parser.add_argument("--write-templates-only", action="store_true")
    return parser.parse_args()


def derive_success_prob(target_dlctr: float, target_qsr: float, trigger_rate: float) -> float:
    if trigger_rate <= 0:
        return 0.0
    # qsr = dlctr + p_sain * (1 - dlctr), where p_sain = trigger * success
    required_p_sain = (target_qsr - target_dlctr) / max(1e-9, (1 - target_dlctr))
    required_p_sain = clamp(required_p_sain, 0.0, 1.0)
    return clamp(required_p_sain / trigger_rate, 0.0, 1.0)


def scenario_markers(sid: str) -> Tuple[str, str]:
    if sid in {"S3", "S4"}:
        return "", f"exp_l3_{sid.lower()}"
    if sid == "S7":
        return "rel_l3_overlap", "exp_l3_overlap"
    if sid in {"S5", "S6"}:
        return f"rel_sain_{sid.lower()}", ""
    return "", ""


def scenario_sain_experience(sid: str, rng: random.Random) -> str:
    if sid in {"S5", "S6"}:
        return rng.choice(["BOOKMARK", "PEOPLE_ENTITY_CARD", "NLQ_ANSWER"])
    if rng.random() < 0.18:
        return rng.choice(["BOOKMARK", "PEOPLE_ENTITY_CARD", "NLQ_ANSWER"])
    return "NONE"


def build_ranked_results(sid: str, row_idx: int, p3_share: float, rng: random.Random) -> List[Dict[str, str | int]]:
    ranked: List[Dict[str, str | int]] = []
    for rank in range(1, 11):
        connector = "3P" if rng.random() < p3_share else "1P"
        ranked.append(
            {
                "rank": rank,
                "doc_token": f"{sid.lower()}_doc_{row_idx}_{rank}",
                "connector": connector,
            }
        )
    return ranked


def write_templates(project_root: Path) -> None:
    templates_dir = project_root / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Scenario knobs template
    knobs_headers = [
        "scenario_id",
        "volume_delta_rel",
        "exploratory_query_share_delta_abs",
        "p3_click_share_delta_abs",
        "mean_clicked_rank_delta_abs",
        "sain_trigger_rate_delta_abs",
        "sain_success_rate_delta_abs",
        "expected_dlctr_delta_abs",
        "expected_dlctr_delta_rel",
        "expected_qsr_delta_abs",
        "expected_qsr_delta_rel",
    ]
    knobs_path = templates_dir / "scenario_knobs_template.csv"
    with knobs_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=knobs_headers)
        writer.writeheader()
        for sid, cfg in SCENARIOS.items():
            rel_dlctr = cfg["expected_dlctr_delta"] / BASELINE["dlctr_mean"] if BASELINE["dlctr_mean"] else 0.0
            rel_qsr = cfg["expected_qsr_delta"] / BASELINE_QSR if BASELINE_QSR else 0.0
            writer.writerow(
                {
                    "scenario_id": sid,
                    "volume_delta_rel": cfg["volume_delta_rel"],
                    "exploratory_query_share_delta_abs": cfg["exploratory_delta"],
                    "p3_click_share_delta_abs": cfg["p3_delta"],
                    "mean_clicked_rank_delta_abs": cfg["rank_delta"],
                    "sain_trigger_rate_delta_abs": cfg["sain_trigger_delta"],
                    "sain_success_rate_delta_abs": cfg["sain_success_delta"],
                    "expected_dlctr_delta_abs": cfg["expected_dlctr_delta"],
                    "expected_dlctr_delta_rel": f"{rel_dlctr:.4f}",
                    "expected_qsr_delta_abs": cfg["expected_qsr_delta"],
                    "expected_qsr_delta_rel": f"{rel_qsr:.4f}",
                }
            )

    # Session template
    session_path = templates_dir / "session_log_template.csv"
    with session_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SESSION_HEADERS)
        writer.writeheader()
        writer.writerow(
            {
                "session_id": "S0_sess_0",
                "query_id": "S0_q_0",
                "event_ts": "2026-01-05T00:00:00Z",
                "query_token": "query_tok_x",
                "query_class": "exploratory",
                "seasonality_tag": "none",
                "sain_experience_type": "NONE",
                "sain_trigger": 0,
                "sain_success": 0,
                "sain_engaged": 0,
                "ranked_results_json": "[]",
                "clicked_rank": "",
                "clicked_doc_token": "",
                "clicked_connector": "",
                "click_ts": "",
                "release_id": "",
                "experiment_id": "",
                "scenario_id": "S0",
            }
        )

    # Metric aggregate template
    metric_path = templates_dir / "metric_aggregate_template.csv"
    with metric_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METRIC_HEADERS)
        writer.writeheader()
        writer.writerow(
            {
                "session_id": "S0_sess_0",
                "query_id": "S0_q_0",
                "metric_ts": "2026-01-05T00:00:00Z",
                "dlctr_value": "0.000000",
                "is_long_click": 0,
                "dlctr_discount_weight": "0.000000",
                "sain_trigger": 0,
                "sain_success": 0,
                "qsr_component_click": "0.000000",
                "qsr_component_sain": "0.000000",
                "qsr_value": "0.000000",
                "qsr_dominant_component": "DLCTR",
                "p3_click_share": "0.000000",
                "mean_clicked_rank": "",
                "clicked_flag": 0,
                "freshness_lag_min": 30,
                "completeness_pct": "99.700",
                "join_coverage_pct": "99.300",
                "scenario_id": "S0",
            }
        )


def generate_data(project_root: Path, output_dir: Path, rows_per_scenario: int, seed: int) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_ts = dt.datetime(2026, 1, 5, 0, 0, 0, tzinfo=dt.timezone.utc)
    session_rows: List[Dict[str, str | int]] = []

    for sid in sorted(SCENARIOS.keys()):
        cfg = SCENARIOS[sid]

        target_dlctr = clamp(BASELINE["dlctr_mean"] + float(cfg["expected_dlctr_delta"]), 0.01, 0.95)
        target_qsr = clamp(BASELINE_QSR + float(cfg["expected_qsr_delta"]), 0.01, 0.99)

        trigger_rate = clamp(
            BASELINE["sain_trigger_rate"] + float(cfg["sain_trigger_delta"]), 0.0, 1.0
        )
        success_prob = derive_success_prob(target_dlctr, target_qsr, trigger_rate)

        p3_share = clamp(BASELINE["p3_click_share"] + float(cfg["p3_delta"]), 0.02, 0.98)
        mean_rank_target = clamp(BASELINE["mean_clicked_rank"] + float(cfg["rank_delta"]), 1.0, 10.0)
        exploratory_share = clamp(
            BASELINE["exploratory_share"] + float(cfg["exploratory_delta"]), 0.05, 0.95
        )

        expected_weight = estimate_discount_from_sampler(
            mean_rank_target, seed + (sum(ord(c) for c in sid) * 17)
        )
        click_prob_base = clamp(target_dlctr / max(1e-9, expected_weight), 0.01, 0.98)

        release_id, experiment_id = scenario_markers(sid)

        for i in range(rows_per_scenario):
            # Spread timestamps over 14 days for periodicity inspection.
            minute_offset = i % (14 * 24 * 60)
            event_ts = start_ts + dt.timedelta(minutes=minute_offset, seconds=i % 41)

            seasonality_tag = str(cfg["seasonality"])
            if sid == "S1":
                dow = event_ts.weekday()
                periodic = math.sin((2 * math.pi * dow) / 7.0)
                click_prob = clamp(click_prob_base * (1.0 + 0.18 * periodic), 0.01, 0.99)
            else:
                click_prob = click_prob_base

            if sid == "S2":
                # Shock window at first 30% of rows.
                if i < int(rows_per_scenario * 0.30):
                    seasonality_tag = "holiday_shock"
            if sid == "S7":
                seasonality_tag = "holiday_shock"

            query_class = "exploratory" if rng.random() < exploratory_share else "navigational"
            if sid == "S4" and rng.random() < 0.15:
                query_class = "navigational"

            sain_trigger = 1 if rng.random() < trigger_rate else 0
            if sain_trigger:
                sain_experience_type = rng.choice(["BOOKMARK", "PEOPLE_ENTITY_CARD", "NLQ_ANSWER"])
            else:
                sain_experience_type = "NONE"
            sain_success = 1 if (sain_trigger and rng.random() < success_prob) else 0
            sain_engaged = sain_success

            ranked_results = build_ranked_results(sid, i, p3_share, rng)

            clicked = rng.random() < click_prob
            clicked_rank = ""
            clicked_doc_token = ""
            clicked_connector = ""
            click_ts = ""
            if clicked:
                rank = rank_from_mean(mean_rank_target, rng)
                clicked_rank = rank
                chosen = ranked_results[rank - 1]
                clicked_doc_token = str(chosen["doc_token"])
                clicked_connector = str(chosen["connector"])
                click_ts = (event_ts + dt.timedelta(seconds=rng.randint(2, 8))).isoformat().replace("+00:00", "Z")

            session_rows.append(
                {
                    "session_id": f"{sid}_sess_{i}",
                    "query_id": f"{sid}_q_{i}",
                    "event_ts": event_ts.isoformat().replace("+00:00", "Z"),
                    "query_token": f"qt_{sid.lower()}_{i}",
                    "query_class": query_class,
                    "seasonality_tag": seasonality_tag,
                    "sain_experience_type": sain_experience_type,
                    "sain_trigger": sain_trigger,
                    "sain_success": sain_success,
                    "sain_engaged": sain_engaged,
                    "ranked_results_json": json.dumps(ranked_results, separators=(",", ":")),
                    "clicked_rank": clicked_rank,
                    "clicked_doc_token": clicked_doc_token,
                    "clicked_connector": clicked_connector,
                    "click_ts": click_ts,
                    "release_id": release_id,
                    "experiment_id": experiment_id,
                    "scenario_id": sid,
                }
            )

    # Compute metric rows with long-click from next query in session sequence.
    # (Each generated session usually has one query; rule still applies.)
    sorted_rows = sorted(session_rows, key=lambda r: (r["session_id"], r["event_ts"], r["query_id"]))
    metric_rows: List[Dict[str, str | int | float]] = []
    for idx, row in enumerate(sorted_rows):
        next_event_ts = None
        if idx + 1 < len(sorted_rows) and sorted_rows[idx + 1]["session_id"] == row["session_id"]:
            next_event_ts = dt.datetime.fromisoformat(str(sorted_rows[idx + 1]["event_ts"]).replace("Z", "+00:00"))

        clicked_rank_raw = row["clicked_rank"]
        clicked_rank = int(clicked_rank_raw) if str(clicked_rank_raw).strip() else None
        clicked_flag = 1 if clicked_rank is not None else 0

        is_long_click = 0
        anomaly = 0
        dlctr_discount = 0.0

        click_ts_raw = str(row["click_ts"])
        click_ts = (
            dt.datetime.fromisoformat(click_ts_raw.replace("Z", "+00:00"))
            if click_ts_raw.strip()
            else None
        )

        if clicked_rank is not None:
            if next_event_ts is None:
                is_long_click = 1
            elif click_ts is None:
                is_long_click = 0
            elif next_event_ts <= click_ts:
                anomaly = 1
                is_long_click = 0
            else:
                delta_sec = (next_event_ts - click_ts).total_seconds()
                is_long_click = 1 if delta_sec >= 40 else 0

            if is_long_click:
                dlctr_discount = discount(clicked_rank)

        dlctr_value = dlctr_discount
        sain_trigger = int(row["sain_trigger"])
        sain_success = int(row["sain_success"])
        qsr_component_click = dlctr_value
        qsr_component_sain = float(sain_success * sain_trigger)
        qsr_value = max(qsr_component_click, qsr_component_sain)
        qsr_dominant = "DLCTR" if qsr_component_click >= qsr_component_sain else "SAIN"

        sid = str(row["scenario_id"])
        if sid == "S8":
            freshness = 240
            completeness = 96.5
            join_coverage = 96.0
        else:
            freshness = 30
            completeness = 99.7
            join_coverage = 99.3
            if anomaly:
                completeness = 98.9

        p3_click_share = 1.0 if (clicked_flag and row["clicked_connector"] == "3P") else 0.0
        mean_clicked_rank = clicked_rank if clicked_flag else ""

        metric_rows.append(
            {
                "session_id": row["session_id"],
                "query_id": row["query_id"],
                "metric_ts": row["event_ts"],
                "dlctr_value": f"{dlctr_value:.6f}",
                "is_long_click": is_long_click,
                "dlctr_discount_weight": f"{dlctr_discount:.6f}",
                "sain_trigger": sain_trigger,
                "sain_success": sain_success,
                "qsr_component_click": f"{qsr_component_click:.6f}",
                "qsr_component_sain": f"{qsr_component_sain:.6f}",
                "qsr_value": f"{qsr_value:.6f}",
                "qsr_dominant_component": qsr_dominant,
                "p3_click_share": f"{p3_click_share:.6f}",
                "mean_clicked_rank": mean_clicked_rank,
                "clicked_flag": clicked_flag,
                "freshness_lag_min": freshness,
                "completeness_pct": f"{completeness:.3f}",
                "join_coverage_pct": f"{join_coverage:.3f}",
                "scenario_id": sid,
            }
        )

    session_path = output_dir / "synthetic_search_session_log.csv"
    with session_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SESSION_HEADERS)
        writer.writeheader()
        writer.writerows(session_rows)

    metric_path = output_dir / "synthetic_metric_aggregate.csv"
    with metric_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METRIC_HEADERS)
        writer.writeheader()
        writer.writerows(metric_rows)

    summary = {
        "seed": seed,
        "rows_per_scenario": rows_per_scenario,
        "scenario_count": len(SCENARIOS),
        "session_rows": len(session_rows),
        "metric_rows": len(metric_rows),
        "baseline_qsr_reference": round(BASELINE_QSR, 6),
    }
    with (output_dir / "generation_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent

    write_templates(project_root)
    if args.write_templates_only:
        return

    output_dir = (project_root / args.output_dir).resolve()
    generate_data(project_root, output_dir, args.rows_per_scenario, args.seed)


if __name__ == "__main__":
    main()
