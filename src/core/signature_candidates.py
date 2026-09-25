"""Generate reviewable generation-signature candidates for coverage rounds."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml


RECIPES = (
    "density_scale",
    "roughness_scale",
    "orientation_spread",
    "size_envelope",
)


def load_case_mapping(case_path: str) -> Dict[str, Any]:
    with Path(case_path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict) or not data.get("joint_sets"):
        raise ValueError("case YAML must contain a joint_sets mapping")
    return data


def _hash_signature(data: Dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _apply_recipe(data: Dict[str, Any], recipe: str, factor: float) -> Dict[str, Any]:
    candidate = copy.deepcopy(data)
    joint_sets = candidate["joint_sets"]
    if recipe == "density_scale":
        for joint_set in joint_sets:
            if "P32" in joint_set:
                joint_set["P32"] = max(float(joint_set["P32"]) * factor, 1e-9)
            if "mean_spacing" in joint_set:
                joint_set["mean_spacing"] = max(float(joint_set["mean_spacing"]) / factor, 1e-9)
    elif recipe == "roughness_scale":
        for joint_set in joint_sets:
            if "Jr_mean" in joint_set:
                joint_set["Jr_mean"] = max(float(joint_set["Jr_mean"]) / factor, 1e-9)
            if "Ja_mean" in joint_set:
                joint_set["Ja_mean"] = float(joint_set["Ja_mean"]) * factor
    elif recipe == "orientation_spread":
        for joint_set in joint_sets:
            if "fisher_kappa" in joint_set:
                joint_set["fisher_kappa"] = max(float(joint_set["fisher_kappa"]) / factor, 1e-9)
    elif recipe == "size_envelope":
        for joint_set in joint_sets:
            if "size_r_min" in joint_set:
                joint_set["size_r_min"] = max(float(joint_set["size_r_min"]) / factor, 1e-9)
            if "size_r_max" in joint_set:
                joint_set["size_r_max"] = float(joint_set["size_r_max"]) * factor
    else:
        raise ValueError(f"unknown recipe: {recipe}")
    return candidate


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
            data.setdefault("tags", {})
            data["tags"].update(
                {
                    "coverage_round": round_id,
                    "coverage_target": target_region,
                    "parent_case": source_name,
                    "candidate_id": candidate_id,
                    "generation_signature_hash": signature_hash,
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
) -> Dict[str, Any]:
    """Build a reviewable manifest for an approved candidate set."""
    candidate_list = list(candidates)
    return {
        "round_id": int(round_id),
        "round_type": "coverage_expansion",
        "backend": backend,
        "correction_mode": correction_mode,
        "output_dir": str(output_dir),
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "case_path": candidate.get("case_path"),
                "parent_case_path": candidate["parent_case_path"],
                "target_region": candidate["target_region"],
                "generation_signature_hash": candidate["generation_signature_hash"],
                "seed_values": candidate["seed_values"],
            }
            for candidate in candidate_list
        ],
        "approval_required": True,
    }


__all__ = [
    "RECIPES",
    "build_simulation_manifest",
    "load_case_mapping",
    "propose_signature_candidates",
    "write_candidate_cases",
]
