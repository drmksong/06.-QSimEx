"""Q' decision-cutoff search utilities."""

import json
import csv
import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import numpy as np
import yaml


DEFAULT_MIN_CUTOFF = 0.1
DEFAULT_MAX_CUTOFF = 400.0
DEFAULT_INTERVALS = 10
PROFILE_STATES = frozenset({"PR", "TR", "POST", "UNOBSERVED"})


def load_cutoff_config(path: str) -> Dict[str, Any]:
    """Load and validate the YAML configuration for cutoff exploration."""
    with Path(path).open("r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}

    config = raw_config.get("qprime_cutoff_search", raw_config)
    if not isinstance(config, dict):
        raise ValueError("qprime_cutoff_search configuration must be a mapping")

    minimum = config.get("minimum", DEFAULT_MIN_CUTOFF)
    maximum = config.get("maximum", DEFAULT_MAX_CUTOFF)
    intervals = config.get("intervals", DEFAULT_INTERVALS)
    generate_qprime_cutoffs(minimum, maximum, intervals)
    return {
        "minimum": float(minimum),
        "maximum": float(maximum),
        "intervals": int(intervals),
        "scale": config.get("scale", "logarithmic"),
    }


def save_cutoff_search_results(
    path: str,
    lower_results: Iterable[Dict[str, Any]],
    upper_results: Iterable[Dict[str, Any]],
    metadata: Dict[str, Any] | None = None,
) -> None:
    """Save independent lower/upper search results as a JSON summary."""
    payload = {
        "metadata": metadata or {},
        "lower_cutoff_results": list(lower_results),
        "upper_cutoff_results": list(upper_results),
    }
    payload = _json_safe(payload)
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    return value


def validate_borehole_records(
    records: Iterable[Dict[str, Any]],
    qprime_bh_key: str = "Qp_bh_mean",
    post_label_key: str = "post_excavation_label",
) -> Dict[str, int]:
    """Validate borehole-level fields without deriving any labels."""
    records = list(records)
    if not records:
        raise ValueError("records must not be empty")
    missing = [
        key for key in (qprime_bh_key, post_label_key)
        if any(key not in record for record in records)
    ]
    if missing:
        raise KeyError(f"required record fields missing: {missing}")

    qprime_values = np.asarray([record[qprime_bh_key] for record in records], dtype=float)
    labels = np.asarray([record[post_label_key] for record in records], dtype=float)
    if np.any(~np.isin(labels, [0.0, 1.0])):
        raise ValueError(f"{post_label_key} must contain only 0 or 1")
    return {
        "n_records": len(records),
        "n_finite_qprime_bh": int(np.isfinite(qprime_values).sum()),
        "n_missing_qprime_bh": int((~np.isfinite(qprime_values)).sum()),
        "n_suitable_outcomes": int((labels == 1.0).sum()),
        "n_unsuitable_outcomes": int((labels == 0.0).sum()),
    }


def summarize_cutoff_regions(
    records: Iterable[Dict[str, Any]],
    lower_cutoff: float,
    upper_cutoff: float,
    qprime_bh_key: str = "Qp_bh_mean",
) -> Dict[str, int]:
    """Summarize operating regions using borehole Q' only.

    This exploratory summary does not require EFPC output or a post-excavation
    label. It reports exposure by region; it does not claim safety performance.
    """
    rows = list(records)
    if not rows:
        raise ValueError("records must not be empty")
    lower_cutoff = float(lower_cutoff)
    upper_cutoff = float(upper_cutoff)
    if not np.isfinite(lower_cutoff) or not np.isfinite(upper_cutoff):
        raise ValueError("cutoffs must be finite")
    if lower_cutoff >= upper_cutoff:
        raise ValueError("lower_cutoff must be smaller than upper_cutoff")
    values = np.asarray([row[qprime_bh_key] for row in rows], dtype=float)
    finite = np.isfinite(values)
    return {
        "n_total": len(rows),
        "n_missing_qprime_bh": int((~finite).sum()),
        "n_hold": int((finite & (values < lower_cutoff)).sum()),
        "n_uncertain": int((finite & (values >= lower_cutoff) & (values < upper_cutoff)).sum()),
        "n_excavate": int((finite & (values >= upper_cutoff)).sum()),
    }


def search_cutoffs_from_records(
    records: Iterable[Dict[str, Any]],
    config: Dict[str, Any] | None = None,
    qprime_bh_key: str = "Qp_bh_mean",
    post_label_key: str = "post_excavation_label",
) -> Dict[str, Any]:
    """Run independent searches from simulation records.

    The post-excavation label must already be an explicit 0/1 evaluation
    outcome. This function never derives it from ``Qp_face_mean`` or any
    other single Q' threshold.
    """
    records = list(records)
    validation = validate_borehole_records(records, qprime_bh_key, post_label_key)

    config = config or {}
    minimum = config.get("minimum", DEFAULT_MIN_CUTOFF)
    maximum = config.get("maximum", DEFAULT_MAX_CUTOFF)
    intervals = config.get("intervals", DEFAULT_INTERVALS)
    cutoffs = generate_qprime_cutoffs(minimum, maximum, intervals)
    qprime_bh = [record[qprime_bh_key] for record in records]
    labels = [record[post_label_key] for record in records]
    return {
        "config": {
            "minimum": float(minimum),
            "maximum": float(maximum),
            "intervals": int(intervals),
            "scale": config.get("scale", "logarithmic"),
        },
        "n_records": len(records),
        "record_validation": validation,
        "lower_cutoff_results": search_lower_cutoffs(qprime_bh, labels, cutoffs),
        "upper_cutoff_results": search_upper_cutoffs(qprime_bh, labels, cutoffs),
    }


def build_search_records(
    comparison_rows: Iterable[Dict[str, Any]],
    post_excavation_labels: Iterable[int],
    qprime_bh_key: str = "Qp_bh_mean",
    post_label_key: str = "post_excavation_label",
) -> List[Dict[str, Any]]:
    """Attach explicit post-excavation labels to simulation comparison rows.

    Existing comparison fields, including ``Qp_face_mean``, are preserved for
    auditability. No label is inferred from any Q' value.
    """
    rows = list(comparison_rows)
    labels = list(post_excavation_labels)
    if len(rows) != len(labels):
        raise ValueError("comparison_rows and post_excavation_labels must have equal length")
    if any(qprime_bh_key not in row for row in rows):
        raise KeyError(f"comparison rows must contain '{qprime_bh_key}'")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("post_excavation_labels must contain only 0 or 1")

    records = []
    for row, label in zip(rows, labels):
        record = dict(row)
        record[post_label_key] = int(label)
        records.append(record)
    return records


def load_search_records(path: str) -> List[Dict[str, Any]]:
    """Load search records from a JSON list or a CSV with a header row."""
    input_path = Path(path)
    if input_path.suffix.lower() == ".json":
        with input_path.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            raise ValueError("JSON input must contain a list of records")
        return records

    if input_path.suffix.lower() == ".csv":
        with input_path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    raise ValueError("input records must be .json or .csv")


def run_cutoff_search(
    input_path: str,
    config_path: str,
    output_path: str,
    qprime_bh_key: str = "Qp_bh_mean",
    post_label_key: str = "post_excavation_label",
) -> Dict[str, Any]:
    """Run a configured cutoff search and write its JSON summary."""
    config = load_cutoff_config(config_path)
    records = load_search_records(input_path)
    result = search_cutoffs_from_records(
        records,
        config=config,
        qprime_bh_key=qprime_bh_key,
        post_label_key=post_label_key,
    )
    save_cutoff_search_results(
        output_path,
        result["lower_cutoff_results"],
        result["upper_cutoff_results"],
        metadata={
            "input_path": str(input_path),
            "config_path": str(config_path),
            "n_records": result["n_records"],
            "config": result["config"],
        },
    )
    return result


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search independent Q' decision cutoffs.")
    parser.add_argument("--input", required=True, help="CSV or JSON records")
    parser.add_argument("--config", required=True, help="YAML cutoff configuration")
    parser.add_argument("--output", required=True, help="JSON summary output")
    parser.add_argument("--qprime-bh-key", default="Qp_bh_mean")
    parser.add_argument("--post-label-key", default="post_excavation_label")
    args = parser.parse_args(argv)
    run_cutoff_search(
        args.input,
        args.config,
        args.output,
        qprime_bh_key=args.qprime_bh_key,
        post_label_key=args.post_label_key,
    )
    return 0


def generate_qprime_cutoffs(
    minimum: float = DEFAULT_MIN_CUTOFF,
    maximum: float = DEFAULT_MAX_CUTOFF,
    intervals: int = DEFAULT_INTERVALS,
) -> List[float]:
    """Generate positive Q' decision cutoffs on a logarithmic scale.

    ``intervals`` is the number of equal intervals in log space, so the
    returned list contains ``intervals + 1`` values including both endpoints.
    """
    minimum = float(minimum)
    maximum = float(maximum)
    if not np.isfinite(minimum) or not np.isfinite(maximum):
        raise ValueError("minimum and maximum must be finite")
    if minimum <= 0 or maximum <= minimum:
        raise ValueError("require 0 < minimum < maximum")
    if isinstance(intervals, bool) or int(intervals) != intervals or intervals < 1:
        raise ValueError("intervals must be a positive integer")

    return np.geomspace(minimum, maximum, num=int(intervals) + 1).tolist()


def combine_profile_states(
    cutoffs: Iterable[float],
    profiles: Mapping[str, Iterable[str]],
) -> Dict[str, Any]:
    """Combine profile states using common bad/good regions.

    Each profile supplies one ``PR``/``TR``/``POST`` state per cutoff. No profile
    weights or composite score are created. The result is ``not_identifiable``
    when common bad and good regions cannot be ordered.
    """
    cutoff_values = [float(value) for value in cutoffs]
    if len(cutoff_values) < 2:
        raise ValueError("at least two cutoff values are required")
    if any(not np.isfinite(value) for value in cutoff_values):
        raise ValueError("cutoff values must be finite")
    if any(left >= right for left, right in zip(cutoff_values, cutoff_values[1:])):
        raise ValueError("cutoff values must be strictly increasing")
    if not profiles:
        raise ValueError("at least one profile is required")

    profile_states = {}
    for name, states in profiles.items():
        states = list(states)
        if len(states) != len(cutoff_values):
            raise ValueError(f"profile '{name}' must match cutoff count")
        if any(state not in PROFILE_STATES for state in states):
            raise ValueError(f"profile '{name}' contains an invalid state")
        profile_states[name] = states

    common_bad = [
        index
        for index in range(len(cutoff_values))
        if all(states[index] == "PR" for states in profile_states.values())
    ]
    common_good = [
        index
        for index in range(len(cutoff_values))
        if all(states[index] == "POST" for states in profile_states.values())
    ]
    common_states = []
    for index in range(len(cutoff_values)):
        if any(states[index] == "UNOBSERVED" for states in profile_states.values()):
            common_states.append("UNOBSERVED")
        elif index in common_bad:
            common_states.append("PR")
        elif index in common_good:
            common_states.append("POST")
        else:
            common_states.append("TR")

    identifiable = bool(common_bad and common_good) and max(common_bad) < min(common_good)
    result: Dict[str, Any] = {
        "status": "identified" if identifiable else "not_identifiable",
        "cutoffs": cutoff_values,
        "profiles": profile_states,
        "common_bad_indices": common_bad,
        "common_good_indices": common_good,
        "common_states": common_states,
    }
    if identifiable:
        result["lower_cutoff"] = cutoff_values[max(common_bad)]
        result["upper_cutoff"] = cutoff_values[min(common_good)]
    else:
        result["lower_cutoff"] = None
        result["upper_cutoff"] = None
    return result


def classify_qprime(
    qprime_bh: float,
    lower_cutoff: float,
    upper_cutoff: float,
) -> str:
    """Classify a pre-excavation borehole Q' into an operating action.

    This function intentionally accepts no face-Q' value.  It represents the
    decision that must be made before excavation.
    """
    lower_cutoff = float(lower_cutoff)
    upper_cutoff = float(upper_cutoff)
    if not np.isfinite(lower_cutoff) or not np.isfinite(upper_cutoff):
        raise ValueError("cutoffs must be finite")
    if lower_cutoff >= upper_cutoff:
        raise ValueError("lower_cutoff must be smaller than upper_cutoff")

    qprime_bh = float(qprime_bh)
    if not np.isfinite(qprime_bh):
        return "unknown"
    if qprime_bh < lower_cutoff:
        return "hold"
    if qprime_bh >= upper_cutoff:
        return "excavate"
    return "uncertain"


def _prepare_evaluation_inputs(
    qprime_bh: Iterable[float],
    post_excavation_labels: Iterable[int],
):
    qprime_values = np.asarray(list(qprime_bh), dtype=float)
    labels = np.asarray(list(post_excavation_labels), dtype=float)
    if qprime_values.shape != labels.shape:
        raise ValueError("qprime_bh and post_excavation_labels must have equal length")
    if np.any(~np.isin(labels, [0.0, 1.0])):
        raise ValueError("post_excavation_labels must contain only 0 or 1")
    return qprime_values, labels


def evaluate_lower_cutoff(
    qprime_bh: Iterable[float],
    post_excavation_labels: Iterable[int],
    lower_cutoff: float,
) -> Dict[str, Any]:
    """Evaluate a lower cutoff independently.

    The lower cutoff protects the ``hold`` region.  Its false-reject rate is
    the fraction of suitable post-excavation outcomes among cases with
    ``Q'_BH < lower_cutoff``.
    """
    lower_cutoff = float(lower_cutoff)
    if not np.isfinite(lower_cutoff) or lower_cutoff <= 0:
        raise ValueError("lower_cutoff must be a positive finite value")
    qprime_values, labels = _prepare_evaluation_inputs(qprime_bh, post_excavation_labels)
    hold = np.isfinite(qprime_values) & (qprime_values < lower_cutoff)
    hold_count = int(hold.sum())
    suitable_hold = int(np.sum(labels[hold] == 1.0))
    return {
        "cutoff": lower_cutoff,
        "n_hold": hold_count,
        "suitable_hold": suitable_hold,
        "false_reject_rate": suitable_hold / hold_count if hold_count else np.nan,
    }


def evaluate_upper_cutoff(
    qprime_bh: Iterable[float],
    post_excavation_labels: Iterable[int],
    upper_cutoff: float,
) -> Dict[str, Any]:
    """Evaluate an upper cutoff independently.

    The upper cutoff protects the ``excavate`` region.  Its false-safe rate is
    the fraction of unsuitable post-excavation outcomes among cases with
    ``Q'_BH >= upper_cutoff``.
    """
    upper_cutoff = float(upper_cutoff)
    if not np.isfinite(upper_cutoff) or upper_cutoff <= 0:
        raise ValueError("upper_cutoff must be a positive finite value")
    qprime_values, labels = _prepare_evaluation_inputs(qprime_bh, post_excavation_labels)
    excavate = np.isfinite(qprime_values) & (qprime_values >= upper_cutoff)
    excavate_count = int(excavate.sum())
    unsuitable_excavate = int(np.sum(labels[excavate] == 0.0))
    return {
        "cutoff": upper_cutoff,
        "n_excavate": excavate_count,
        "unsuitable_excavate": unsuitable_excavate,
        "false_safe_rate": unsuitable_excavate / excavate_count if excavate_count else np.nan,
    }


def search_lower_cutoffs(
    qprime_bh: Iterable[float],
    post_excavation_labels: Iterable[int],
    cutoffs: Iterable[float] = (),
) -> List[Dict[str, Any]]:
    """Evaluate each lower cutoff independently."""
    qprime_values = list(qprime_bh)
    labels = list(post_excavation_labels)
    cutoff_values = list(cutoffs) or generate_qprime_cutoffs()
    return [
        evaluate_lower_cutoff(qprime_values, labels, cutoff)
        for cutoff in cutoff_values
    ]


def search_upper_cutoffs(
    qprime_bh: Iterable[float],
    post_excavation_labels: Iterable[int],
    cutoffs: Iterable[float] = (),
) -> List[Dict[str, Any]]:
    """Evaluate each upper cutoff independently."""
    qprime_values = list(qprime_bh)
    labels = list(post_excavation_labels)
    cutoff_values = list(cutoffs) or generate_qprime_cutoffs()
    return [
        evaluate_upper_cutoff(qprime_values, labels, cutoff)
        for cutoff in cutoff_values
    ]


__all__ = [
    "DEFAULT_MIN_CUTOFF",
    "DEFAULT_MAX_CUTOFF",
    "DEFAULT_INTERVALS",
    "PROFILE_STATES",
    "load_cutoff_config",
    "save_cutoff_search_results",
    "validate_borehole_records",
    "summarize_cutoff_regions",
    "search_cutoffs_from_records",
    "build_search_records",
    "load_search_records",
    "run_cutoff_search",
    "generate_qprime_cutoffs",
    "combine_profile_states",
    "classify_qprime",
    "evaluate_lower_cutoff",
    "evaluate_upper_cutoff",
    "search_lower_cutoffs",
    "search_upper_cutoffs",
]


if __name__ == "__main__":
    raise SystemExit(main())
