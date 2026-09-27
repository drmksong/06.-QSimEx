"""Analyze Q'/RQD sensitivity against measured borehole-plane angle."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator


def load_rows(path: str) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _mean(rows: list[dict[str, str]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {None, ""}]
    return statistics.mean(values) if values else float("nan")


def analyze(rows: list[dict[str, str]]) -> dict:
    required = {
        "borehole_plane_angle_mean_deg",
        "Qp_bh_mean",
        "RQD_bh_mean",
        "case_name",
        "seed",
    }
    if rows and not required.issubset(rows[0]):
        raise KeyError(f"rows must contain {sorted(required)}")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["case_name"]].append(row)

    points = []
    for case_name, case_rows in grouped.items():
        points.append(
            {
                "case_name": case_name,
                "seed_count": len({row["seed"] for row in case_rows}),
                "angle_mean_deg": _mean(case_rows, "borehole_plane_angle_mean_deg"),
                "angle_sd_deg": statistics.stdev(
                    float(row["borehole_plane_angle_mean_deg"]) for row in case_rows
                )
                if len(case_rows) > 1
                else 0.0,
                "qprime_mean": _mean(case_rows, "Qp_bh_mean"),
                "rqd_mean": _mean(case_rows, "RQD_bh_mean"),
            }
        )
    points.sort(key=lambda point: point["angle_mean_deg"])

    angles = np.asarray([point["angle_mean_deg"] for point in points], dtype=float)
    q_values = np.asarray([point["qprime_mean"] for point in points], dtype=float)
    rqd_values = np.asarray([point["rqd_mean"] for point in points], dtype=float)
    if len(points) < 2 or len(np.unique(angles)) != len(angles):
        raise ValueError("at least two unique angle points are required")

    slopes = []
    for left, right in zip(points, points[1:]):
        delta_angle = right["angle_mean_deg"] - left["angle_mean_deg"]
        slopes.append(
            {
                "angle_range_deg": [left["angle_mean_deg"], right["angle_mean_deg"]],
                "dqprime_dangle": (right["qprime_mean"] - left["qprime_mean"]) / delta_angle,
                "drqd_dangle": (right["rqd_mean"] - left["rqd_mean"]) / delta_angle,
            }
        )

    q_model = PchipInterpolator(angles, q_values, extrapolate=True)
    rqd_model = PchipInterpolator(angles, rqd_values, extrapolate=True)
    # The current experiment covers roughly 13~59 degrees. Only the missing
    # upper interval is extrapolated for the present use case.
    extrapolation_angles = [60.0, 90.0]
    raw_qprime = [float(q_model(angle)) for angle in extrapolation_angles]
    raw_rqd = [float(rqd_model(angle)) for angle in extrapolation_angles]
    return {
        "analysis": "angle_sensitivity_observed_and_pchip_extrapolation",
        "angle_definition": "borehole_plane_angle_mean_deg; 0 parallel, 90 perpendicular",
        "observed_angle_range_deg": [float(angles.min()), float(angles.max())],
        "points": points,
        "segment_slopes": slopes,
        "nonlinear_model": "PCHIP",
        "extrapolation": {
            "angles_deg": extrapolation_angles,
            "qprime_values_raw": raw_qprime,
            "rqd_values_raw": raw_rqd,
            "qprime_values_bounded": [max(0.0, value) for value in raw_qprime],
            "rqd_values_bounded": [min(100.0, max(0.0, value)) for value in raw_rqd],
            "status": "uncertain_outside_observed_range",
            "use_for_cutoff": False,
            "warning": "Raw PCHIP extrapolation may violate physical bounds; bounded values are descriptive only.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = analyze(load_rows(args.input))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps({"output": args.output, "points": len(result["points"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
