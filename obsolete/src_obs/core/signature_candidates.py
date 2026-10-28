"""Generate reviewable generation-signature candidates for coverage rounds."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml


RECIPES = (
    "density_scale",
    "roughness_scale",
    "orientation_spread",
    "size_envelope",
)

_STRATEGY_STATUSES = {
    "proposed",
    "approved_for_screening",
    "screened",
    "retain",
    "deprioritized",
    "rejected",
}


def validate_strategy_catalog(
    strategy_catalog: Dict[str, Iterable[Dict[str, Any]]],
) -> None:
    """Validate reviewed catalog metadata without inventing feature rules."""
    if not isinstance(strategy_catalog, dict) or not strategy_catalog:
        raise ValueError("strategy_catalog must be a non-empty mapping")
    for target_gap, strategies in strategy_catalog.items():
        if target_gap not in {"low_q_gap", "internal_gap", "high_q_gap"}:
            raise ValueError(f"unknown target gap: {target_gap}")
        for strategy in strategies:
            if not isinstance(strategy, dict):
                raise TypeError("each strategy catalog item must be a mapping")
            status = strategy.get("status", "approved_for_screening")
            if status not in _STRATEGY_STATUSES:
                raise ValueError(f"unknown strategy status: {status}")
            if "changed_features" in strategy:
                required = {
                    "strategy_id",
                    "parent_signature",
                    "expected_effect",
                    "selection_reason",
                    "validity_constraints",
                }
                missing = sorted(key for key in required if key not in strategy)
                if missing:
                    raise ValueError(
                        f"catalog strategy is missing required fields: {missing}"
                    )
                if not isinstance(strategy["changed_features"], list):
                    raise TypeError("changed_features must be a list")
                for feature in strategy["changed_features"]:
                    if not isinstance(feature, dict) or not feature.get("name"):
                        raise ValueError("each changed feature requires a name")
            elif not (
                strategy.get("feature_family") == "D"
                and strategy.get("candidate_case_path")
            ) and (not strategy.get("recipe") or strategy.get("factor") is None):
                raise ValueError(
                    "strategy requires changed_features, a reviewed D candidate case, "
                    "or legacy recipe/factor"
                )

_IDENTITY_METADATA_KEYS = frozenset(
    {
        "name",
        "case_name",
        "description",
        "tags",
        "seed",
        "execution_id",
        "run_id",
        "round_id",
        "runtime",
        "runtime_breakdown",
        "domain_id",
        "generation_signature_hash",
        "candidate_id",
    }
)


def _canonical_identity_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical_identity_value(item)
            for key, item in sorted(value.items())
            if key not in _IDENTITY_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_canonical_identity_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_identity_value(item) for item in value]
    return value


def _generation_identity_mapping(case_mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Project a case YAML mapping onto the runner's generation-feature schema."""
    if not {"domain", "tunnel", "joint_sets"}.issubset(case_mapping):
        return case_mapping
    domain = case_mapping["domain"]
    tunnel = case_mapping["tunnel"]
    rqd = case_mapping.get("rqd", {})
    return {
        "domain_size": [domain["nx"], domain["ny"], domain["nz"]],
        "grid_spacing": [domain["dx"], domain["dy"], domain["dz"]],
        "tunnel": {
            "center_y": tunnel["center_y"],
            "center_z": tunnel["center_z"],
            "radius": tunnel["radius"],
        },
        "borehole_offsets": [
            [borehole.get("dy", 0.0), borehole.get("dz", 0.0)]
            for borehole in case_mapping.get("boreholes", [])
        ],
        "rqd_scan_length": rqd.get("scan_length", 5.0),
        "joint_sets": case_mapping["joint_sets"],
        "global_params": case_mapping.get("global_params", {}),
    }


def compute_generation_signature_hash(case_mapping: Dict[str, Any]) -> str:
    """Hash canonical generation/configuration data without run metadata."""
    canonical = _canonical_identity_value(_generation_identity_mapping(case_mapping))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_domain_id(
    case_mapping: Dict[str, Any],
    *,
    seed: int,
    generator_version: str = "unknown",
    domain_identity: Dict[str, Any] | None = None,
) -> str:
    """Hash generation identity plus seed and generator/domain identity."""
    payload = {
        "generation": _canonical_identity_value(_generation_identity_mapping(case_mapping)),
        "seed": int(seed),
        "generator_version": str(generator_version),
        "domain_identity": _canonical_identity_value(domain_identity or {}),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def estimate_euler_direction(
    feature_delta: Dict[str, float],
    coverage_delta: Dict[str, float],
    coverage_residual: Dict[str, float],
) -> Dict[str, float]:
    """Estimate a local feature direction from one finite-difference probe."""
    common_metrics = set(coverage_delta) & set(coverage_residual)
    denominator = sum(float(coverage_delta[name]) ** 2 for name in common_metrics)
    if denominator <= 0.0:
        raise ValueError("coverage_delta must contain a non-zero observed direction")
    projection = sum(
        float(coverage_delta[name]) * float(coverage_residual[name])
        for name in common_metrics
    ) / denominator
    return {
        name: float(delta) * projection
        for name, delta in feature_delta.items()
        if math.isfinite(float(delta))
    }


def estimate_euler_direction_from_probes(
    probes: Iterable[Dict[str, Dict[str, float]]],
) -> Dict[str, float]:
    """Combine local probe directions without feature or probe weights."""
    probe_list = list(probes)
    if not probe_list:
        raise ValueError("probes must not be empty")
    directions = []
    for probe in probe_list:
        directions.append(
            estimate_euler_direction(
                probe["feature_delta"],
                probe["coverage_delta"],
                probe["coverage_residual"],
            )
        )
    feature_names = set().union(*(direction.keys() for direction in directions))
    return {
        name: sum(direction.get(name, 0.0) for direction in directions) / len(directions)
        for name in feature_names
    }


def euler_update_feature_vector(
    features: Dict[str, float],
    direction: Dict[str, float],
    *,
    step_size: float,
    bounds: Dict[str, tuple[float, float]],
    discrete_features: Iterable[str] = (),
) -> Dict[str, float]:
    """Apply one bounded Euler step in normalized feature space."""
    if step_size <= 0.0 or not math.isfinite(step_size):
        raise ValueError("step_size must be a positive finite number")
    discrete = set(discrete_features)
    updated = dict(features)
    for name, value in features.items():
        if name in discrete or name not in direction:
            continue
        if name not in bounds:
            raise KeyError(f"missing bounds for continuous feature: {name}")
        lower, upper = bounds[name]
        if lower > upper:
            raise ValueError(f"invalid bounds for feature: {name}")
        candidate = float(value) + step_size * float(direction[name])
        updated[name] = min(max(candidate, lower), upper)
    return updated


def _get_mapping_path(mapping: Dict[str, Any], path: str) -> Any:
    value: Any = mapping
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                raise KeyError(f"feature path not found: {path}")
            value = value[part]
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            if index >= len(value):
                raise KeyError(f"feature path not found: {path}")
            value = value[index]
        else:
            raise KeyError(f"feature path not found: {path}")
    return value


def _set_mapping_path(mapping: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    target: Any = mapping
    for part in parts[:-1]:
        if isinstance(target, dict):
            if part not in target:
                raise KeyError(f"feature path not found: {path}")
            target = target[part]
        elif isinstance(target, list) and part.isdigit():
            index = int(part)
            if index >= len(target):
                raise KeyError(f"feature path not found: {path}")
            target = target[index]
        else:
            raise KeyError(f"feature path not found: {path}")
    final_part = parts[-1]
    if isinstance(target, dict):
        if final_part not in target:
            raise KeyError(f"feature path not found: {path}")
        target[final_part] = value
    elif isinstance(target, list) and final_part.isdigit():
        index = int(final_part)
        if index >= len(target):
            raise KeyError(f"feature path not found: {path}")
        target[index] = value
    else:
        raise KeyError(f"feature path not writable: {path}")


def extract_normalized_features(
    case_mapping: Dict[str, Any],
    feature_bounds: Dict[str, tuple[float, float]],
) -> Dict[str, float]:
    """Extract explicitly selected case features into normalized [0, 1] space."""
    normalized: Dict[str, float] = {}
    for path, bounds in feature_bounds.items():
        lower, upper = bounds
        if lower >= upper:
            raise ValueError(f"invalid bounds for feature: {path}")
        value = float(_get_mapping_path(case_mapping, path))
        if value < lower or value > upper:
            raise ValueError(f"feature value outside bounds: {path}")
        normalized[path] = (value - lower) / (upper - lower)
    return normalized


def apply_normalized_features(
    case_mapping: Dict[str, Any],
    normalized_features: Dict[str, float],
    feature_bounds: Dict[str, tuple[float, float]],
) -> Dict[str, Any]:
    """Apply normalized [0, 1] features to a copied case mapping."""
    updated = copy.deepcopy(case_mapping)
    for path, normalized in normalized_features.items():
        if path not in feature_bounds:
            raise KeyError(f"missing bounds for feature: {path}")
        if not 0.0 <= float(normalized) <= 1.0:
            raise ValueError(f"normalized feature outside [0, 1]: {path}")
        lower, upper = feature_bounds[path]
        _set_mapping_path(
            updated,
            path,
            lower + float(normalized) * (upper - lower),
        )
    return updated


def build_euler_update_candidate(
    case_path: str,
    *,
    round_id: int,
    target_region: str,
    screening_seed: int,
    feature_bounds: Dict[str, tuple[float, float]],
    feature_delta: Dict[str, float],
    coverage_delta: Dict[str, float],
    coverage_residual: Dict[str, float],
    step_size: float,
    discrete_features: Iterable[str] = (),
    generator_version: str = "unknown",
    reason: str = "bounded explicit-Euler-style update",
) -> Dict[str, Any]:
    """Build one candidate by applying a ledger-derived normalized update."""
    source = load_case_mapping(case_path)
    normalized_before = extract_normalized_features(source, feature_bounds)
    direction = estimate_euler_direction(
        feature_delta,
        coverage_delta,
        coverage_residual,
    )
    normalized_after = euler_update_feature_vector(
        normalized_before,
        direction,
        step_size=step_size,
        bounds={path: (0.0, 1.0) for path in feature_bounds},
        discrete_features=discrete_features,
    )
    candidate_case = apply_normalized_features(
        source,
        normalized_after,
        feature_bounds,
    )
    source_name = str(source.get("name", Path(case_path).stem))
    signature_hash = compute_generation_signature_hash(candidate_case)
    candidate_id = f"r{round_id:03d}-euler-{signature_hash[:12]}"
    candidate_case["name"] = f"{source_name}__{candidate_id}"
    candidate_case["seed"] = int(screening_seed)
    domain_id = compute_domain_id(
        candidate_case,
        seed=screening_seed,
        generator_version=generator_version,
    )
    candidate_case.setdefault("tags", {})
    candidate_case["tags"].update(
        {
            "coverage_round": round_id,
            "coverage_target": target_region,
            "candidate_id": candidate_id,
            "generation_signature_hash": signature_hash,
            "domain_id": domain_id,
            "update_method": "bounded_explicit_euler_style",
            "parent_case": source_name,
            "generator_version": generator_version,
        }
    )
    return {
        "candidate_id": candidate_id,
        "parent_case_path": str(case_path),
        "target_region": target_region,
        "reason": reason,
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "seed_values": [int(screening_seed)],
        "feature_bounds": dict(feature_bounds),
        "normalized_features_before": normalized_before,
        "feature_delta": dict(feature_delta),
        "coverage_delta": dict(coverage_delta),
        "coverage_residual": dict(coverage_residual),
        "direction": direction,
        "step_size": float(step_size),
        "normalized_features_after": normalized_after,
        "case": candidate_case,
    }


def build_euler_update_candidate_from_probes(
    case_path: str,
    *,
    round_id: int,
    target_region: str,
    screening_seed: int,
    feature_bounds: Dict[str, tuple[float, float]],
    probes: Iterable[Dict[str, Dict[str, float]]],
    step_size: float,
    discrete_features: Iterable[str] = (),
    generator_version: str = "unknown",
    reason: str = "multi-probe bounded explicit-Euler-style update",
) -> Dict[str, Any]:
    """Build one candidate from an unweighted set of local response probes."""
    probe_list = list(probes)
    source = load_case_mapping(case_path)
    normalized_before = extract_normalized_features(source, feature_bounds)
    direction = estimate_euler_direction_from_probes(probe_list)
    normalized_after = euler_update_feature_vector(
        normalized_before,
        direction,
        step_size=step_size,
        bounds={path: (0.0, 1.0) for path in feature_bounds},
        discrete_features=discrete_features,
    )
    candidate_case = apply_normalized_features(source, normalized_after, feature_bounds)
    source_name = str(source.get("name", Path(case_path).stem))
    signature_hash = compute_generation_signature_hash(candidate_case)
    candidate_id = f"r{round_id:03d}-euler-probes-{signature_hash[:12]}"
    candidate_case["name"] = f"{source_name}__{candidate_id}"
    candidate_case["seed"] = int(screening_seed)
    domain_id = compute_domain_id(candidate_case, seed=screening_seed, generator_version=generator_version)
    candidate_case.setdefault("tags", {})
    candidate_case["tags"].update(
        {
            "coverage_round": round_id,
            "coverage_target": target_region,
            "candidate_id": candidate_id,
            "generation_signature_hash": signature_hash,
            "domain_id": domain_id,
            "update_method": "bounded_explicit_euler_style_multi_probe",
            "parent_case": source_name,
            "generator_version": generator_version,
        }
    )
    return {
        "candidate_id": candidate_id,
        "parent_case_path": str(case_path),
        "target_region": target_region,
        "reason": reason,
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "seed_values": [int(screening_seed)],
        "normalized_features_before": normalized_before,
        "probes": probe_list,
        "direction": direction,
        "step_size": float(step_size),
        "normalized_features_after": normalized_after,
        "case": candidate_case,
    }

def load_case_mapping(case_path: str) -> Dict[str, Any]:
    with Path(case_path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict) or not data.get("joint_sets"):
        raise ValueError("case YAML must contain a joint_sets mapping")
    return data


def _hash_signature(data: Dict[str, Any]) -> str:
    return compute_generation_signature_hash(data)


def _interpolate_value(left: Any, right: Any, fraction: float) -> Any:
    if isinstance(left, bool) or isinstance(right, bool):
        return copy.deepcopy(left)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) + (float(right) - float(left)) * fraction
    if isinstance(left, dict) and isinstance(right, dict):
        result = copy.deepcopy(left)
        for key in left.keys() & right.keys():
            result[key] = _interpolate_value(left[key], right[key], fraction)
        return result
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [
            _interpolate_value(left_item, right_item, fraction)
            for left_item, right_item in zip(left, right)
        ]
    return copy.deepcopy(left)


def _collect_numeric_deltas(
    left: Any,
    right: Any,
    path: str = "",
) -> List[Dict[str, Any]]:
    if isinstance(left, bool) or isinstance(right, bool):
        return []
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if float(left) == float(right):
            return []
        return [{"path": path, "left": left, "right": right}]
    if isinstance(left, dict) and isinstance(right, dict):
        changes: List[Dict[str, Any]] = []
        for key in left.keys() & right.keys():
            if key in {"seed", "tags", "name", "description"}:
                continue
            child_path = f"{path}.{key}" if path else str(key)
            changes.extend(_collect_numeric_deltas(left[key], right[key], child_path))
        return changes
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        changes = []
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            changes.extend(_collect_numeric_deltas(left_item, right_item, f"{path}[{index}]"))
        return changes
    return []


def build_neighbor_midpoint_candidate(
    left_case_path: str,
    right_case_path: str,
    *,
    round_id: int,
    target_region: str,
    screening_seed: int,
    fraction: float = 0.5,
    reason: str = "neighbor signature midpoint",
) -> Dict[str, Any]:
    """Build a candidate by interpolating numeric values between two parents."""
    if not 0.0 < fraction < 1.0:
        raise ValueError("fraction must be between 0 and 1")
    left = load_case_mapping(left_case_path)
    right = load_case_mapping(right_case_path)
    if len(left["joint_sets"]) != len(right["joint_sets"]):
        raise ValueError("neighbor cases must have the same joint-set count")
    data = _interpolate_value(left, right, fraction)
    left_name = str(left.get("name", Path(left_case_path).stem))
    right_name = str(right.get("name", Path(right_case_path).stem))
    signature_hash = _hash_signature(data)
    candidate_id = f"r{round_id:03d}-midpoint-{signature_hash[:12]}"
    data["name"] = f"{left_name}__{right_name}__{candidate_id}"
    data["seed"] = int(screening_seed)
    domain_id = compute_domain_id(data, seed=screening_seed)
    data.setdefault("tags", {})
    data["tags"].update(
        {
            "coverage_round": round_id,
            "coverage_target": target_region,
            "candidate_id": candidate_id,
            "generation_signature_hash": signature_hash,
            "domain_id": domain_id,
            "parent_signatures": [left_name, right_name],
            "interpolation_fraction": fraction,
        }
    )
    return {
        "candidate_id": candidate_id,
        "parent_case_paths": [str(left_case_path), str(right_case_path)],
        "target_region": target_region,
        "interpolation_fraction": fraction,
        "changed_features": _collect_numeric_deltas(left, right),
        "reason": reason,
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "seed_values": [int(screening_seed)],
        "case": data,
    }


def build_selective_neighbor_candidate(
    parent_case_path: str,
    target_case_path: str,
    changed_feature_paths: Iterable[str],
    *,
    round_id: int,
    target_region: str,
    screening_seed: int,
    fraction: float = 1.0,
    generator_version: str = "unknown",
    reason: str = "selective neighbor finite-difference probe",
) -> Dict[str, Any]:
    """Move selected feature paths from a parent toward a target case."""
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must be greater than 0 and no greater than 1")
    parent = load_case_mapping(parent_case_path)
    target = load_case_mapping(target_case_path)
    selected_paths = list(changed_feature_paths)
    if not selected_paths:
        raise ValueError("changed_feature_paths must not be empty")
    candidate_case = copy.deepcopy(parent)
    changes = []
    for path in selected_paths:
        parent_value = _get_mapping_path(parent, path)
        target_value = _get_mapping_path(target, path)
        candidate_value = _interpolate_value(parent_value, target_value, fraction)
        _set_mapping_path(candidate_case, path, candidate_value)
        changes.append(
            {
                "path": path,
                "parent": parent_value,
                "target": target_value,
                "candidate": candidate_value,
            }
        )
    parent_name = str(parent.get("name", Path(parent_case_path).stem))
    target_name = str(target.get("name", Path(target_case_path).stem))
    signature_hash = compute_generation_signature_hash(candidate_case)
    candidate_id = f"r{round_id:03d}-probe-{signature_hash[:12]}"
    candidate_case["name"] = f"{parent_name}__{candidate_id}"
    candidate_case["seed"] = int(screening_seed)
    domain_id = compute_domain_id(
        candidate_case,
        seed=screening_seed,
        generator_version=generator_version,
    )
    candidate_case.setdefault("tags", {})
    candidate_case["tags"].update(
        {
            "coverage_round": round_id,
            "coverage_target": target_region,
            "candidate_id": candidate_id,
            "generation_signature_hash": signature_hash,
            "domain_id": domain_id,
            "parent_signature": parent_name,
            "target_signature": target_name,
            "update_method": "selective_neighbor_probe",
            "generator_version": generator_version,
        }
    )
    return {
        "candidate_id": candidate_id,
        "parent_case_paths": [str(parent_case_path), str(target_case_path)],
        "target_region": target_region,
        "changed_features": changes,
        "interpolation_fraction": fraction,
        "reason": reason,
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "seed_values": [int(screening_seed)],
        "case": candidate_case,
    }


def _apply_recipe(
    data: Dict[str, Any],
    recipe: str,
    factor: float,
    direction: str = "forward",
) -> Dict[str, Any]:
    if direction not in {"forward", "reverse"}:
        raise ValueError("direction must be 'forward' or 'reverse'")
    if factor <= 1.0:
        raise ValueError("candidate factors must be greater than 1")
    scale = factor if direction == "forward" else 1.0 / factor
    candidate = copy.deepcopy(data)
    joint_sets = candidate["joint_sets"]
    if recipe == "density_scale":
        for joint_set in joint_sets:
            if "P32" in joint_set:
                joint_set["P32"] = max(float(joint_set["P32"]) * scale, 1e-9)
            if "mean_spacing" in joint_set:
                joint_set["mean_spacing"] = max(float(joint_set["mean_spacing"]) / scale, 1e-9)
    elif recipe == "roughness_scale":
        for joint_set in joint_sets:
            if "Jr_mean" in joint_set:
                joint_set["Jr_mean"] = max(float(joint_set["Jr_mean"]) / scale, 1e-9)
            if "Ja_mean" in joint_set:
                joint_set["Ja_mean"] = float(joint_set["Ja_mean"]) * scale
    elif recipe == "orientation_spread":
        for joint_set in joint_sets:
            if "fisher_kappa" in joint_set:
                joint_set["fisher_kappa"] = max(float(joint_set["fisher_kappa"]) / scale, 1e-9)
    elif recipe == "size_envelope":
        for joint_set in joint_sets:
            if "size_r_min" in joint_set:
                joint_set["size_r_min"] = max(float(joint_set["size_r_min"]) / scale, 1e-9)
            if "size_r_max" in joint_set:
                joint_set["size_r_max"] = float(joint_set["size_r_max"]) * scale
    else:
        raise ValueError(f"unknown recipe: {recipe}")
    return candidate


def _gap_class(gap: Dict[str, Any], audit: Dict[str, Any]) -> str:
    observed_min = float(audit["observed_min"])
    observed_max = float(audit["observed_max"])
    upper = float(gap["qprime_bh_upper"])
    lower = float(gap["qprime_bh_lower"])
    if upper <= observed_min:
        return "low_q_gap"
    if lower >= observed_max:
        return "high_q_gap"
    return "internal_gap"


def rank_coverage_gaps(
    audit: Dict[str, Any],
    *,
    gap_class_priority: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Return unobserved bins in deterministic priority order.

    When ``gap_class_priority`` is supplied, its order is used as an explicit
    policy. Without it, gaps are ordered only by their logarithmic width and
    bin index. This function only ranks observed evidence; it does not infer a
    cutoff or suitability.
    """
    if "bins" not in audit or "observed_min" not in audit or "observed_max" not in audit:
        raise KeyError("audit must contain bins, observed_min, and observed_max")
    gaps = []
    for gap in audit["bins"]:
        if gap.get("status") != "UNOBSERVED":
            continue
        lower = float(gap["qprime_bh_lower"])
        upper = float(gap["qprime_bh_upper"])
        gap_class = _gap_class(gap, audit)
        width = upper / max(lower, 1e-12)
        gaps.append(
            {
                **gap,
                "gap_class": gap_class,
                "priority_width": width,
            }
        )
    class_order = None
    if gap_class_priority is not None:
        class_order = {name: index for index, name in enumerate(gap_class_priority)}
        unknown_classes = set(class_order) - {"internal_gap", "low_q_gap", "high_q_gap"}
        if unknown_classes:
            raise ValueError(f"unknown gap classes: {sorted(unknown_classes)}")
    return sorted(
        gaps,
        key=lambda gap: (
            class_order.get(gap["gap_class"], len(class_order)) if class_order is not None else 0,
            -gap["priority_width"],
            int(gap["bin_index"]),
        ),
    )


def _round_robin_plans(plans: List[Dict[str, Any]], max_candidates: int) -> List[Dict[str, Any]]:
    by_bin: Dict[int, List[Dict[str, Any]]] = {}
    for plan in plans:
        by_bin.setdefault(int(plan["bin_index"]), []).append(plan)
    selected: List[Dict[str, Any]] = []
    bin_indices = list(by_bin)
    depth = 0
    while len(selected) < max_candidates and depth < max(
        len(items) for items in by_bin.values()
    ):
        for bin_index in bin_indices:
            items = by_bin[bin_index]
            if depth < len(items):
                selected.append(items[depth])
                if len(selected) >= max_candidates:
                    return selected
        depth += 1
    return selected


def plan_gap_candidates(
    audit: Dict[str, Any],
    *,
    strategy_catalog: Dict[str, Iterable[Dict[str, Any]]],
    max_candidates: int,
    gap_class_priority: Iterable[str] | None = None,
    time_budget_seconds: float | None = None,
    time_budget_by_gap: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    """Plan deterministic candidate mutations from coverage gaps.

    The planner deliberately returns plans, not YAML cases. Feature recipes
    are supplied by a reviewed catalog; this function does not invent feature
    directions or factors.
    """
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    if time_budget_seconds is not None and time_budget_seconds <= 0:
        raise ValueError("time_budget_seconds must be positive")
    if time_budget_seconds is not None and time_budget_by_gap is not None:
        raise ValueError("choose either total or per-gap time budgets")
    if time_budget_by_gap is not None:
        if not time_budget_by_gap:
            raise ValueError("time_budget_by_gap must not be empty")
        if any(value <= 0 for value in time_budget_by_gap.values()):
            raise ValueError("per-gap time budgets must be positive")
    plans: List[Dict[str, Any]] = []
    validate_strategy_catalog(strategy_catalog)
    for gap in rank_coverage_gaps(audit, gap_class_priority=gap_class_priority):
        strategies = list(strategy_catalog.get(gap["gap_class"], ()))
        targeted_strategies = [
            strategy
            for catalog_strategies in strategy_catalog.values()
            for strategy in catalog_strategies
            if int(gap["bin_index"])
            in (strategy.get("validity_constraints") or {}).get("target_bins", ())
        ]
        seen_strategy_ids = {strategy.get("strategy_id") for strategy in strategies}
        strategies.extend(
            strategy for strategy in targeted_strategies
            if strategy.get("strategy_id") not in seen_strategy_ids
        )
        for strategy in strategies:
            recipe = strategy.get("recipe")
            direction = strategy.get("direction", "forward")
            factor = strategy.get("factor")
            reason = strategy.get("reason")
            changed_features = strategy.get("changed_features")
            if not changed_features and (not recipe or factor is None):
                raise ValueError(
                    "strategy requires changed_features or legacy recipe/factor"
                )
            estimated_runtime = strategy.get("estimated_runtime_seconds")
            expected_information_gain = strategy.get("expected_information_gain")
            if time_budget_seconds is not None:
                if estimated_runtime is None or expected_information_gain is None:
                    raise ValueError(
                        "time-aware screening requires estimated runtime and "
                        "expected information gain"
                    )
                estimated_runtime = float(estimated_runtime)
                expected_information_gain = float(expected_information_gain)
                if estimated_runtime <= 0 or expected_information_gain < 0:
                    raise ValueError(
                        "runtime must be positive and information gain non-negative"
                    )
            plans.append(
                {
                    "bin_index": int(gap["bin_index"]),
                    "target_region": gap["gap_class"],
                    "qprime_bh_range": [
                        float(gap["qprime_bh_lower"]),
                        float(gap["qprime_bh_upper"]),
                    ],
                    "recipe": recipe,
                    "direction": direction,
                    "factor": factor,
                    "strategy_id": strategy.get("strategy_id"),
                    "status": strategy.get("status", "approved_for_screening"),
                    "feature_family": strategy.get("feature_family"),
                    "parent_signature": strategy.get("parent_signature"),
                    "parent_case_path": strategy.get("parent_case_path"),
                    "candidate_case_path": strategy.get("candidate_case_path"),
                    "changed_features": changed_features,
                    "step_size": strategy.get("step_size"),
                    "generator_version": strategy.get("generator_version"),
                    "expected_effect": strategy.get("expected_effect"),
                    "selection_reason": strategy.get("selection_reason"),
                    "validity_constraints": strategy.get("validity_constraints"),
                    "response_update": strategy.get("response_update"),
                    "reason": reason or gap.get("recommendation", "coverage gap"),
                    "estimated_runtime_seconds": estimated_runtime,
                    "expected_information_gain": expected_information_gain,
                    "efficiency_score": (
                        expected_information_gain / estimated_runtime
                        if estimated_runtime is not None and estimated_runtime > 0
                        else None
                    ),
                }
            )
    if not plans:
        raise ValueError("audit contains no UNOBSERVED bins")
    if time_budget_seconds is None and time_budget_by_gap is None:
        return _round_robin_plans(plans, max_candidates)

    if time_budget_by_gap is not None:
        selected_by_gap: Dict[str, List[Dict[str, Any]]] = {}
        for gap_class, budget in time_budget_by_gap.items():
            gap_plans = [
                plan for plan in plans if plan["target_region"] == gap_class
            ]
            selected: List[Dict[str, Any]] = []
            elapsed = 0.0
            ranked_plans = sorted(
                gap_plans,
                key=lambda item: (
                    -float(item["efficiency_score"] or 0.0),
                    int(item["bin_index"]),
                    str(item["recipe"]),
                ),
            )
            for plan in _round_robin_plans(ranked_plans, len(ranked_plans)):
                runtime = plan.get("estimated_runtime_seconds")
                if runtime is None or plan.get("expected_information_gain") is None:
                    raise ValueError(
                        "time-aware screening requires estimated runtime and "
                        "expected information gain"
                    )
                runtime = float(runtime)
                if elapsed + runtime <= budget:
                    selected.append(plan)
                    elapsed += runtime
            if selected:
                selected_by_gap[gap_class] = selected

        if not selected_by_gap:
            raise ValueError("no candidate fits the per-gap time budgets")

        selected = []
        max_depth = max(len(items) for items in selected_by_gap.values())
        gap_classes = list(selected_by_gap)
        for index in range(max_depth):
            for gap_class in gap_classes:
                items = selected_by_gap[gap_class]
                if index < len(items):
                    selected.append(items[index])
                    if len(selected) >= max_candidates:
                        return selected
        return selected

    selected: List[Dict[str, Any]] = []
    elapsed = 0.0
    for plan in sorted(
        plans,
        key=lambda item: (
            -float(item["efficiency_score"]),
            int(item["bin_index"]),
            str(item["recipe"]),
        ),
    ):
        runtime = float(plan["estimated_runtime_seconds"])
        if elapsed + runtime > time_budget_seconds:
            continue
        selected.append(plan)
        elapsed += runtime
        if len(selected) >= max_candidates:
            break
    if not selected:
        raise ValueError("no candidate fits the screening time budget")
    return selected


def _build_planned_candidate(
    case_path: str,
    *,
    round_id: int,
    screening_seed: int,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    if plan.get("feature_family") in {"A", "B", "C", "D"}:
        return build_reviewed_strategy_candidate(
            plan,
            round_id=round_id,
            screening_seed=screening_seed,
        )
    if not plan.get("recipe"):
        raise ValueError(
            "changed_features plans require build_euler_update_candidate; "
            "recipe-based materialization is not implicit"
        )
    source = load_case_mapping(case_path)
    data = _apply_recipe(
        source,
        plan["recipe"],
        float(plan["factor"]),
        direction=plan["direction"],
    )
    source_name = str(source.get("name", Path(case_path).stem))
    signature_hash = _hash_signature(data)
    candidate_id = (
        f"r{round_id:03d}-bin{plan['bin_index']}-"
        f"{plan['recipe']}-{plan['direction']}-{signature_hash[:12]}"
    )
    data["name"] = f"{source_name}__{candidate_id}"
    data["seed"] = int(screening_seed)
    domain_id = compute_domain_id(data, seed=screening_seed)
    data.setdefault("tags", {})
    data["tags"].update(
        {
            "coverage_round": round_id,
            "coverage_target": plan["target_region"],
            "parent_case": source_name,
            "candidate_id": candidate_id,
            "generation_signature_hash": signature_hash,
            "domain_id": domain_id,
            "generation_signature_direction": plan["direction"],
            "generation_signature_recipe": plan["recipe"],
            "generation_signature_factor": float(plan["factor"]),
        }
    )
    return {
        "candidate_id": candidate_id,
        "parent_case_path": str(case_path),
        "parent_case_name": source_name,
        "target_region": plan["target_region"],
        "gap_bin_index": plan["bin_index"],
        "qprime_bh_range": plan["qprime_bh_range"],
        "recipe": plan["recipe"],
        "direction": plan["direction"],
        "factor": float(plan["factor"]),
        "reason": plan["reason"],
        "estimated_runtime_seconds": plan.get("estimated_runtime_seconds"),
        "expected_information_gain": plan.get("expected_information_gain"),
        "efficiency_score": plan.get("efficiency_score"),
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "seed_values": [int(screening_seed)],
        "case": data,
    }


def build_reviewed_strategy_candidate(
    plan: Dict[str, Any],
    *,
    round_id: int,
    screening_seed: int,
    generator_version: str = "qsimex-generation-v1",
) -> Dict[str, Any]:
    """Materialize one approved single-feature plan or reviewed discrete D case."""
    family = plan.get("feature_family")
    if family not in {"A", "B", "C", "D"}:
        raise ValueError("reviewed strategy requires feature_family D, A, B, or C")
    if plan.get("status") != "approved_for_screening":
        raise ValueError("strategy must be approved_for_screening before materialization")
    parent_path = plan.get("parent_case_path")
    if not parent_path:
        raise ValueError("strategy requires parent_case_path")
    parent = load_case_mapping(str(parent_path))
    parent_signature = compute_generation_signature_hash(parent)
    if parent_signature != plan.get("parent_signature"):
        raise ValueError("strategy parent signature does not match parent_case_path")

    changed_feature = None
    orientation_validation = None
    if family == "D":
        candidate_path = plan.get("candidate_case_path")
        if not candidate_path:
            raise ValueError("D strategy requires candidate_case_path")
        candidate_case = load_case_mapping(str(candidate_path))
        if compute_generation_signature_hash(candidate_case) == parent_signature:
            raise ValueError("D strategy candidate must have a distinct signature")
    else:
        changes = plan.get("changed_features")
        if not isinstance(changes, list) or len(changes) != 1:
            raise ValueError(f"{family} strategy must change exactly one feature")
        changed_feature = dict(changes[0])
        feature_path = changed_feature.get("name")
        if not feature_path:
            raise ValueError("changed feature requires a name")
        if "target_value" not in changed_feature:
            raise ValueError("changed feature requires an explicit target_value")
        bounds = changed_feature.get("bounds")
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise ValueError("changed feature requires explicit [lower, upper] bounds")
        lower, upper = (float(bounds[0]), float(bounds[1]))
        target_value = float(changed_feature["target_value"])
        if not all(math.isfinite(value) for value in (lower, upper, target_value)):
            raise ValueError("feature value and bounds must be finite")
        if lower >= upper or not lower <= target_value <= upper:
            raise ValueError("target_value must be inside its approved feature bounds")
        parent_value = float(_get_mapping_path(parent, feature_path))
        if not lower <= parent_value <= upper:
            raise ValueError("parent feature is outside the strategy's approved bounds")
        candidate_case = copy.deepcopy(parent)
        _set_mapping_path(candidate_case, feature_path, target_value)
        changed_feature.update({
            "parent_value": parent_value,
            "target_value": target_value,
            "bounds": [lower, upper],
        })
        if family == "C":
            joint_set_index = int(feature_path.split(".")[1])
            before_set = parent["joint_sets"][joint_set_index]
            after_set = candidate_case["joint_sets"][joint_set_index]
            if feature_path.endswith((".mean_dip", ".mean_dip_dir")):
                before_dip = math.radians(float(before_set["mean_dip"]))
                before_dir = math.radians(float(before_set["mean_dip_dir"]))
                after_dip = math.radians(float(after_set["mean_dip"]))
                after_dir = math.radians(float(after_set["mean_dip_dir"]))
                before_normal = (
                    math.sin(before_dip) * math.cos(before_dir),
                    math.sin(before_dip) * math.sin(before_dir),
                    math.cos(before_dip),
                )
                after_normal = (
                    math.sin(after_dip) * math.cos(after_dir),
                    math.sin(after_dip) * math.sin(after_dir),
                    math.cos(after_dip),
                )
                cosine = min(1.0, max(-1.0, sum(
                    left * right for left, right in zip(before_normal, after_normal)
                )))
                plane_angle = math.degrees(math.acos(abs(cosine)))
                if plane_angle <= 1e-12:
                    raise ValueError("C orientation target does not change the realized plane angle")
                orientation_validation = {
                    "method": "unoriented_plane_normal_angle",
                    "realized_plane_angle_degrees": plane_angle,
                    "status": "mean_plane_changed",
                }
            else:
                orientation_validation = {
                    "method": "fisher_kappa_distribution_change",
                    "realized_plane_angle_degrees": 0.0,
                    "status": "orientation_spread_only",
                }

    signature_hash = compute_generation_signature_hash(candidate_case)
    candidate_id = (
        f"r{round_id:03d}-{family.lower()}-{signature_hash[:12]}"
    )
    parent_name = str(parent.get("name", Path(str(parent_path)).stem))
    root_name = parent_name.split("__r", maxsplit=1)[0]
    candidate_case["name"] = f"{root_name}__{candidate_id}"
    candidate_case["seed"] = int(screening_seed)
    domain_id = compute_domain_id(
        candidate_case,
        seed=screening_seed,
        generator_version=generator_version,
    )
    candidate_case.setdefault("tags", {}).update({
        "candidate_id": candidate_id,
        "coverage_round": int(round_id),
        "coverage_target": plan["target_region"],
        "feature_family": family,
        "strategy_id": plan["strategy_id"],
        "parent_case": parent_name,
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "generator_version": generator_version,
        "update_method": "reviewed_strategy_candidate",
    })
    return {
        "candidate_id": candidate_id,
        "candidate_case_path": plan.get("candidate_case_path") if family == "D" else None,
        "parent_case_path": str(parent_path),
        "parent_signature": parent_signature,
        "target_region": plan["target_region"],
        "bin_index": int(plan["bin_index"]),
        "feature_family": family,
        "strategy_id": plan["strategy_id"],
        "changed_feature": changed_feature,
        "orientation_validation": orientation_validation,
        "selection_reason": plan.get("selection_reason"),
        "expected_effect": plan.get("expected_effect"),
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "seed": int(screening_seed),
        "case": candidate_case,
    }


def build_gap_screening_pool(
    audit: Dict[str, Any],
    parent_cases: Iterable[Dict[str, str]],
    *,
    round_id: int,
    screening_seed: int,
    strategy_catalog: Dict[str, Iterable[Dict[str, Any]]],
    max_candidates: int,
    gap_class_priority: Iterable[str] | None = None,
    time_budget_seconds: float | None = None,
    time_budget_by_gap: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    """Build a reviewable common-seed pool from an observed coverage audit.

    Parent cases are selected by matching ``target_region`` when possible.
    The function never invents a target range or cutoff; each candidate keeps
    the gap bin and the explicit feature mutation used to reach it.
    """
    if not isinstance(screening_seed, int):
        raise TypeError("screening_seed must be an integer")
    targets = list(parent_cases)
    if not targets:
        raise ValueError("parent_cases must not be empty")
    for target in targets:
        if not target.get("case_path") or not target.get("target_region"):
            raise ValueError("each parent case requires case_path and target_region")

    plans = plan_gap_candidates(
        audit,
        strategy_catalog=strategy_catalog,
        max_candidates=max_candidates,
        gap_class_priority=gap_class_priority,
        time_budget_seconds=time_budget_seconds,
        time_budget_by_gap=time_budget_by_gap,
    )
    candidates: List[Dict[str, Any]] = []
    seen_hashes = set()
    for plan in plans:
        matching = [
            target
            for target in targets
            if target["target_region"] == plan["target_region"]
        ]
        if not matching:
            continue
        parent = matching[0]
        candidate = _build_planned_candidate(
            parent["case_path"],
            round_id=round_id,
            screening_seed=screening_seed,
            plan=plan,
        )
        if candidate["generation_signature_hash"] in seen_hashes:
            continue
        seen_hashes.add(candidate["generation_signature_hash"])
        candidates.append(candidate)
    if not candidates:
        raise ValueError("gap planning produced no unique candidates")
    return candidates


def propose_signature_candidates(
    case_path: str,
    *,
    round_id: int,
    target_region: str,
    seed_values: Iterable[int],
    factors: Iterable[float] = (1.25, 1.5),
    recipes: Iterable[str] = RECIPES,
) -> List[Dict[str, Any]]:
    """Create candidate case mappings without executing simulation.

    ``target_region`` is descriptive metadata such as ``low_q_gap`` or
    ``high_q_gap``. It does not become a cutoff or a suitability label.
    """
    if round_id < 0:
        raise ValueError("round_id must be non-negative")
    if not target_region:
        raise ValueError("target_region must not be empty")
    seeds = [int(seed) for seed in seed_values]
    if not seeds:
        raise ValueError("seed_values must not be empty")
    source = load_case_mapping(case_path)
    candidates = []
    for recipe in recipes:
        for factor in factors:
            if factor <= 1.0:
                raise ValueError("candidate factors must be greater than 1")
            data = _apply_recipe(source, recipe, float(factor))
            source_name = str(source.get("name", Path(case_path).stem))
            signature_hash = _hash_signature(data)
            candidate_id = f"r{round_id:03d}-{recipe}-{factor:g}-{signature_hash[:12]}"
            data["name"] = f"{source_name}__{candidate_id}"
            data["seed"] = seeds[0]
            domain_id = compute_domain_id(data, seed=seeds[0])
            data.setdefault("tags", {})
            data["tags"].update(
                {
                    "coverage_round": round_id,
                    "coverage_target": target_region,
                    "parent_case": source_name,
                    "candidate_id": candidate_id,
                    "generation_signature_hash": signature_hash,
                    "domain_id": domain_id,
                }
            )
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "parent_case_path": str(case_path),
                    "parent_case_name": source_name,
                    "target_region": target_region,
                    "recipe": recipe,
                    "factor": float(factor),
                    "generation_signature_hash": signature_hash,
                    "domain_id": domain_id,
                    "seed_values": seeds,
                    "case": data,
                }
            )
    return candidates


def write_candidate_cases(
    candidates: Iterable[Dict[str, Any]],
    output_dir: str,
) -> List[str]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for candidate in candidates:
        path = destination / f"{candidate['candidate_id']}.yaml"
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(candidate["case"], handle, sort_keys=False, allow_unicode=True)
        candidate["case_path"] = str(path)
        paths.append(str(path))
    return paths


def build_simulation_manifest(
    candidates: Iterable[Dict[str, Any]],
    *,
    round_id: int,
    output_dir: str,
    backend: str = "auto",
    correction_mode: str = "pure",
    screening_seed: int | None = None,
    seed_policy: str = "candidate seed values",
    time_budget_seconds: float | None = None,
    time_budget_by_gap: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """Build a reviewable manifest for an approved candidate set."""
    candidate_list = list(candidates)
    manifest = {
        "round_id": int(round_id),
        "round_type": "coverage_expansion",
        "backend": backend,
        "correction_mode": correction_mode,
        "output_dir": str(output_dir),
        "candidate_count": len(candidate_list),
        "seed_policy": seed_policy,
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "case_path": candidate.get("case_path"),
                "parent_case_path": candidate["parent_case_path"],
                "target_region": candidate["target_region"],
                "generation_signature_hash": candidate["generation_signature_hash"],
                "domain_id": candidate.get("domain_id"),
                "seed_values": candidate["seed_values"],
                "estimated_runtime_seconds": candidate.get("estimated_runtime_seconds"),
                "expected_information_gain": candidate.get("expected_information_gain"),
                "efficiency_score": candidate.get("efficiency_score"),
            }
            for candidate in candidate_list
        ],
        "approval_required": True,
    }
    if screening_seed is not None:
        manifest["screening_seed"] = int(screening_seed)
    if time_budget_seconds is not None:
        if time_budget_seconds <= 0:
            raise ValueError("time_budget_seconds must be positive")
        manifest["time_budget_seconds"] = float(time_budget_seconds)
    if time_budget_by_gap is not None:
        if not time_budget_by_gap or any(
            value <= 0 for value in time_budget_by_gap.values()
        ):
            raise ValueError("per-gap time budgets must be positive")
        manifest["time_budget_by_gap"] = {
            str(key): float(value) for key, value in time_budget_by_gap.items()
        }
    return manifest


__all__ = [
    "RECIPES",
    "build_neighbor_midpoint_candidate",
    "build_selective_neighbor_candidate",
    "build_gap_screening_pool",
    "build_euler_update_candidate",
    "build_euler_update_candidate_from_probes",
    "build_simulation_manifest",
    "apply_normalized_features",
    "compute_domain_id",
    "compute_generation_signature_hash",
    "estimate_euler_direction",
    "estimate_euler_direction_from_probes",
    "euler_update_feature_vector",
    "extract_normalized_features",
    "load_case_mapping",
    "plan_gap_candidates",
    "propose_signature_candidates",
    "rank_coverage_gaps",
    "validate_strategy_catalog",
    "write_candidate_cases",
]
