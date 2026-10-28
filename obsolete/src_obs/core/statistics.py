"""Domain-cluster bootstrap for Q' profile exploration."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping

import numpy as np

from .profile_exploration import DEFAULT_PROFILE_COLUMNS, classify_profile_states, summarize_profiles
from .qprime_cutoff_search import combine_profile_states, generate_qprime_cutoffs


BOOTSTRAP_STAGES = (200, 500, 1000, 2000)


def _percentile_interval(values: Iterable[float]) -> Dict[str, float | None]:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if finite.size == 0:
        return {"lower": None, "median": None, "upper": None}
    return {
        "lower": float(np.percentile(finite, 2.5)),
        "median": float(np.percentile(finite, 50.0)),
        "upper": float(np.percentile(finite, 97.5)),
    }


def _validate_records(records: List[Dict[str, Any]], domain_key: str) -> List[Any]:
    if not records:
        raise ValueError("records must not be empty")
    if any(domain_key not in row or row[domain_key] in (None, "") for row in records):
        raise KeyError(f"records must contain a non-empty '{domain_key}'")
    domains = list(dict.fromkeys(row[domain_key] for row in records))
    if len(domains) < 2:
        raise ValueError("at least two independent domains are required")
    return domains


def cluster_bootstrap(
    records: Iterable[Dict[str, Any]],
    *,
    cutoffs: Iterable[float] | None = None,
    profile_columns: Mapping[str, str] | None = None,
    domain_key: str = "domain_id",
    iterations: int = 200,
    random_state: int = 20260925,
    change_tolerance: float = 0.25,
    stability_tolerance: float = 0.05,
    stable_bins: int = 1,
    min_records: int = 1,
    min_domains: int = 1,
) -> Dict[str, Any]:
    """Bootstrap Q' profiles by resampling complete independent domains.

    Rows belonging to a sampled domain are kept together. Simulation is never
    rerun; this function only resamples already-produced result rows.
    """
    rows = [dict(row) for row in records]
    domains = _validate_records(rows, domain_key)
    if isinstance(iterations, bool) or int(iterations) != iterations or iterations < 1:
        raise ValueError("iterations must be a positive integer")

    cutoff_values = list(cutoffs or generate_qprime_cutoffs())
    profile_map = dict(profile_columns or DEFAULT_PROFILE_COLUMNS)
    rows_by_domain = defaultdict(list)
    for row in rows:
        rows_by_domain[row[domain_key]].append(row)

    rng = np.random.default_rng(random_state)
    lower_values: List[float] = []
    upper_values: List[float] = []
    status_counts = Counter()
    state_counts: Dict[str, List[Counter]] = {
        name: [Counter() for _ in range(len(cutoff_values) - 1)]
        for name in profile_map
    }
    profile_medians: Dict[str, List[List[float]]] = {
        name: [[] for _ in range(len(cutoff_values) - 1)]
        for name in profile_map
    }

    for _ in range(int(iterations)):
        sampled_domains = rng.choice(domains, size=len(domains), replace=True)
        sampled_rows = [row for domain in sampled_domains for row in rows_by_domain[domain]]
        summaries = summarize_profiles(
            sampled_rows,
            profile_columns=profile_map,
            cutoffs=cutoff_values,
            domain_keys=(domain_key,),
        )
        states = classify_profile_states(
            summaries,
            profile_names=profile_map,
            change_tolerance=change_tolerance,
            stability_tolerance=stability_tolerance,
            stable_bins=stable_bins,
            min_records=min_records,
            min_domains=min_domains,
        )
        boundary = combine_profile_states(cutoff_values[:-1], states)
        status_counts[boundary["status"]] += 1

        if boundary["lower_cutoff"] is not None:
            lower_values.append(float(boundary["lower_cutoff"]))
        if boundary["upper_cutoff"] is not None:
            upper_values.append(float(boundary["upper_cutoff"]))

        for name, profile_states in states.items():
            for index, state in enumerate(profile_states):
                state_counts[name][index][state] += 1
        for name in profile_map:
            for index, summary in enumerate(summaries):
                median = summary.get(f"{name}_median")
                if median is not None and np.isfinite(float(median)):
                    profile_medians[name][index].append(float(median))

    state_proportions = {
        name: [
            {state: count / int(iterations) for state, count in counts.items()}
            for counts in bins
        ]
        for name, bins in state_counts.items()
    }
    median_intervals = {
        name: [_percentile_interval(values) for values in bins]
        for name, bins in profile_medians.items()
    }
    return {
        "method": "domain_cluster_bootstrap",
        "iterations": int(iterations),
        "random_state": int(random_state),
        "domain_key": domain_key,
        "n_records": len(rows),
        "n_domains": len(domains),
        "cutoffs": [float(value) for value in cutoff_values],
        "profile_columns": profile_map,
        "status_proportions": {
            status: count / int(iterations) for status, count in status_counts.items()
        },
        "n_identified": int(status_counts.get("identified", 0)),
        "lower_cutoff": _percentile_interval(lower_values),
        "upper_cutoff": _percentile_interval(upper_values),
        "profile_median_intervals": median_intervals,
        "profile_state_proportions": state_proportions,
    }


def run_bootstrap_schedule(
    records: Iterable[Dict[str, Any]],
    *,
    stages: Iterable[int] = BOOTSTRAP_STAGES[:3],
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Run staged bootstrap budgets, stopping when results stabilize."""
    results = []
    previous = None
    for iterations in stages:
        result = cluster_bootstrap(records, iterations=iterations, **kwargs)
        result["stability_against_previous"] = _schedule_stability(previous, result)
        results.append(result)
        previous = result
        if result["stability_against_previous"] is True:
            break
    return results


def _schedule_stability(previous: Dict[str, Any] | None, current: Dict[str, Any]) -> bool | None:
    if previous is None:
        return None
    for key in ("lower_cutoff", "upper_cutoff"):
        old = previous[key]["median"]
        new = current[key]["median"]
        if old is None or new is None:
            return False
        if not np.isclose(old, new, rtol=0.02, atol=0.01):
            return False
    statuses = set(previous["status_proportions"]) | set(current["status_proportions"])
    return all(
        np.isclose(
            previous["status_proportions"].get(status, 0.0),
            current["status_proportions"].get(status, 0.0),
            atol=0.02,
        )
        for status in statuses
    )


__all__ = ["BOOTSTRAP_STAGES", "cluster_bootstrap", "run_bootstrap_schedule"]
