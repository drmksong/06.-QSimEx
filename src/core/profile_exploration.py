"""Exploratory Q' profile summaries by borehole-level Q'."""

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import numpy as np

from .qprime_cutoff_search import generate_qprime_cutoffs


DEFAULT_PROFILE_COLUMNS = {
    "qprime_face": "Qp_face_mean",
    "intersection_risk": "miss_ratio",
    "fracture_density": "face_fracture_density",
    "orientation_gap": "orientation_bias_gap_to_face",
}


def classify_profile_states(
    summaries: Iterable[Dict[str, Any]],
    profile_names: Iterable[str] | None = None,
    change_tolerance: float = 0.25,
    stability_tolerance: float = 0.05,
    stable_bins: int = 1,
    min_records: int = 1,
) -> Dict[str, List[str]]:
    """Classify profile bins as PR, TR, or POST from adjacent changes.

    The classification describes profile change state only. It does not assign
    disposal suitability and does not use a fixed Q' suitability threshold.
    """
    rows = list(summaries)
    if not rows:
        raise ValueError("summaries must not be empty")
    if change_tolerance < 0 or stability_tolerance < 0:
        raise ValueError("tolerances must be non-negative")
    if stable_bins < 1 or min_records < 1:
        raise ValueError("stable_bins and min_records must be positive")

    names = list(profile_names or DEFAULT_PROFILE_COLUMNS)
    states: Dict[str, List[str]] = {}
    for name in names:
        medians = np.asarray(
            [_as_float(row.get(f"{name}_median")) for row in rows], dtype=float
        )
        counts = np.asarray(
            [int(row.get(f"{name}_n", 0) or 0) for row in rows], dtype=int
        )
        valid = np.isfinite(medians) & (counts >= min_records)
        if not valid.all():
            states[name] = ["TR"] * len(rows)
            continue

        changes = np.full(len(rows), np.nan, dtype=float)
        for index in range(1, len(rows)):
            denominator = max(abs(medians[index - 1]), abs(medians[index]), 1.0)
            changes[index] = abs(medians[index] - medians[index - 1]) / denominator

        transition_indices = [
            index for index in range(1, len(rows))
            if changes[index] > change_tolerance
        ]
        if not transition_indices:
            states[name] = ["PR"] * len(rows)
            continue

        transition = transition_indices[0]
        stable_start = None
        for start in range(transition + 1, len(rows)):
            end = start + stable_bins
            if end <= len(rows) and np.all(changes[start:end] <= stability_tolerance):
                stable_start = start
                break

        if stable_start is None:
            states[name] = [
                "PR" if index < transition else "TR" for index in range(len(rows))
            ]
            continue

        states[name] = [
            "PR" if index < transition else
            "TR" if index < stable_start else
            "POST"
            for index in range(len(rows))
        ]
    return states


def search_profile_boundaries(
    records: Iterable[Dict[str, Any]],
    qprime_bh_key: str = "Qp_bh_mean",
    profile_columns: Dict[str, str] | None = None,
    cutoffs: Iterable[float] | None = None,
    change_tolerance: float = 0.25,
    stability_tolerance: float = 0.05,
    stable_bins: int = 1,
    min_records: int = 1,
) -> Dict[str, Any]:
    """Search simulation-based lower and upper cutoff candidates.

    The search uses virtual-excavation reference profiles only. It does not
    derive suitability labels and does not calculate safety performance.
    """
    rows = list(records)
    profile_columns = profile_columns or DEFAULT_PROFILE_COLUMNS
    cutoff_values = list(cutoffs or generate_qprime_cutoffs())
    summaries = summarize_profiles(
        rows,
        qprime_bh_key=qprime_bh_key,
        profile_columns=profile_columns,
        cutoffs=cutoff_values,
    )
    profile_states = classify_profile_states(
        summaries,
        profile_names=profile_columns,
        change_tolerance=change_tolerance,
        stability_tolerance=stability_tolerance,
        stable_bins=stable_bins,
        min_records=min_records,
    )
    from .qprime_cutoff_search import combine_profile_states

    boundary = combine_profile_states(cutoff_values[:-1], profile_states)
    if boundary["status"] == "identified":
        reason = "common PR and POST profile regions identified"
    elif all(
        state == "TR"
        for states in profile_states.values()
        for state in states
    ):
        reason = "insufficient valid profile bins for state classification"
    else:
        reason = "common PR and POST profile regions are not identifiable"
    return {
        "status": boundary["status"],
        "reason": reason,
        "lower_cutoff": boundary["lower_cutoff"],
        "upper_cutoff": boundary["upper_cutoff"],
        "cutoffs": cutoff_values,
        "summaries": summaries,
        "profile_states": profile_states,
        "common_states": boundary["common_states"],
        "common_bad_indices": boundary["common_bad_indices"],
        "common_good_indices": boundary["common_good_indices"],
        "n_records": len(rows),
    }


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def summarize_profiles(
    records: Iterable[Dict[str, Any]],
    qprime_bh_key: str = "Qp_bh_mean",
    profile_columns: Dict[str, str] | None = None,
    cutoffs: Iterable[float] | None = None,
    domain_keys: tuple[str, ...] = ("case_name", "seed"),
) -> List[Dict[str, Any]]:
    """Summarize profile distributions in logarithmic Q' bins.

    This function reports distributions only. It does not assign PR/TR/POST
    states and does not interpret profiles as disposal suitability.
    """
    rows = list(records)
    if not rows:
        raise ValueError("records must not be empty")
    profile_columns = profile_columns or DEFAULT_PROFILE_COLUMNS
    cutoffs = list(cutoffs or generate_qprime_cutoffs())
    if len(cutoffs) < 2:
        raise ValueError("at least two cutoffs are required")
    if any(qprime_bh_key not in row for row in rows):
        raise KeyError(f"records must contain '{qprime_bh_key}'")
    missing_profiles = [
        (name, column)
        for name, column in profile_columns.items()
        if any(column not in row for row in rows)
    ]
    if missing_profiles:
        raise KeyError(f"profile columns missing: {missing_profiles}")

    q_values = np.asarray([_as_float(row[qprime_bh_key]) for row in rows])
    output = []
    for bin_index, (lower, upper) in enumerate(zip(cutoffs[:-1], cutoffs[1:])):
        in_bin = np.isfinite(q_values) & (q_values >= lower)
        if bin_index == len(cutoffs) - 2:
            in_bin &= q_values <= upper
        else:
            in_bin &= q_values < upper
        selected = [row for row, included in zip(rows, in_bin) if included]
        summary: Dict[str, Any] = {
            "bin_index": bin_index,
            "qprime_bh_lower": lower,
            "qprime_bh_upper": upper,
            "n_records": len(selected),
        }
        domains = {
            tuple(row.get(key) for key in domain_keys)
            for row in selected
        }
        summary["n_domains"] = len(domains)
        for name, column in profile_columns.items():
            values = np.asarray([_as_float(row[column]) for row in selected])
            values = values[np.isfinite(values)]
            summary[f"{name}_n"] = int(values.size)
            summary[f"{name}_median"] = float(np.median(values)) if values.size else None
            summary[f"{name}_q25"] = float(np.quantile(values, 0.25)) if values.size else None
            summary[f"{name}_q75"] = float(np.quantile(values, 0.75)) if values.size else None
        output.append(summary)
    return output


def audit_qprime_coverage(
    records: Iterable[Dict[str, Any]],
    qprime_bh_key: str = "Qp_bh_mean",
    cutoffs: Iterable[float] | None = None,
    domain_keys: tuple[str, ...] = ("case_name", "seed"),
) -> Dict[str, Any]:
    """Report observed and missing Q' regions for configuration expansion.

    Empty bins are classified as coverage gaps, not as transition states. Gaps
    inside the observed range should be filled first; gaps outside it require a
    reachability pilot with new simulation configurations.
    """
    rows = list(records)
    if not rows:
        raise ValueError("records must not be empty")
    cutoff_values = list(cutoffs or generate_qprime_cutoffs())
    if len(cutoff_values) < 2:
        raise ValueError("at least two cutoffs are required")
    if any(left >= right for left, right in zip(cutoff_values, cutoff_values[1:])):
        raise ValueError("cutoffs must be strictly increasing")
    if any(qprime_bh_key not in row for row in rows):
        raise KeyError(f"records must contain '{qprime_bh_key}'")

    q_values = np.asarray([_as_float(row[qprime_bh_key]) for row in rows])
    finite = q_values[np.isfinite(q_values)]
    if finite.size == 0:
        raise ValueError(f"records contain no finite '{qprime_bh_key}' values")
    observed_min = float(np.min(finite))
    observed_max = float(np.max(finite))
    bins = []
    for bin_index, (lower, upper) in enumerate(zip(cutoff_values[:-1], cutoff_values[1:])):
        in_bin = np.isfinite(q_values) & (q_values >= lower)
        if bin_index == len(cutoff_values) - 2:
            in_bin &= q_values <= upper
        else:
            in_bin &= q_values < upper
        selected = [row for row, included in zip(rows, in_bin) if included]
        domains = {tuple(row.get(key) for key in domain_keys) for row in selected}
        cases = {row.get("case_name") for row in selected if row.get("case_name")}
        if selected:
            status = "observed"
            recommendation = "no coverage expansion required"
        elif upper < observed_min or lower > observed_max:
            status = "UNOBSERVED"
            recommendation = "test reachability with configuration expansion"
        else:
            status = "UNOBSERVED"
            recommendation = "add configurations to fill an internal coverage gap"
        bins.append(
            {
                "bin_index": bin_index,
                "qprime_bh_lower": float(lower),
                "qprime_bh_upper": float(upper),
                "n_records": len(selected),
                "n_domains": len(domains),
                "n_cases": len(cases),
                "status": status,
                "recommendation": recommendation,
            }
        )
    return {
        "qprime_bh_key": qprime_bh_key,
        "cutoffs": [float(value) for value in cutoff_values],
        "observed_min": observed_min,
        "observed_max": observed_max,
        "n_records": len(rows),
        "n_finite_records": int(finite.size),
        "bins": bins,
    }


def load_csv_records(path: str) -> List[Dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def save_profile_summary(path: str, summaries: Iterable[Dict[str, Any]], metadata: Dict[str, Any]) -> None:
    payload = {"metadata": metadata, "summaries": list(summaries)}
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize Q' profiles by borehole Q'.")
    parser.add_argument("--input", required=True, help="borehole-level CSV")
    parser.add_argument("--output", required=True, help="JSON profile summary")
    args = parser.parse_args(argv)
    records = load_csv_records(args.input)
    cutoffs = generate_qprime_cutoffs()
    summaries = summarize_profiles(records, cutoffs=cutoffs)
    save_profile_summary(
        args.output,
        summaries,
        {
            "input": args.input,
            "qprime_bh_key": "Qp_bh_mean",
            "cutoffs": cutoffs,
            "analysis": "exploratory distribution summary; no PR/TR/POST classification",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
