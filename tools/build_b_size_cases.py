"""Build matched size-distribution probes for the B exploration stage."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/d_matched/d_matched_3set.yaml")
OUTPUT = Path("cases/b_size")
SEED = 309
PROBES = (
    ("alpha_low", {"size_alpha": 2.5}),
    ("alpha_high", {"size_alpha": 4.0}),
    ("max_radius_high", {"size_r_max": 24.0}),
)


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_total_p32 = sum(float(item["P32"]) for item in source["joint_sets"])
    base_sets = source["joint_sets"]
    cases = []
    for probe_name, changes in PROBES:
        case = copy.deepcopy(source)
        case["name"] = f"b_size_{probe_name}_3set"
        case["description"] = (
            "B-only matched size-distribution probe; total P32, joint-set structure, "
            "orientation, geometry, and material inputs fixed."
        )
        case["seed"] = SEED
        case["tags"] = {
            "coverage_stage": "B_size_distribution",
            "parent_case": SOURCE.stem,
            "size_probe": probe_name,
            "common_seed": SEED,
            "matched_non_size_features": True,
        }
        for joint_set in case["joint_sets"]:
            joint_set.update(changes)
        if sum(float(item["P32"]) for item in case["joint_sets"]) != base_total_p32:
            raise ValueError(f"P32 changed for {case['name']}")
        for before, after in zip(base_sets, case["joint_sets"]):
            for key in (
                "set_id",
                "P32",
                "mean_spacing",
                "mean_dip",
                "mean_dip_dir",
                "fisher_kappa",
                "Jr_mean",
                "Jr_std",
                "Ja_mean",
                "Ja_std",
            ):
                if before[key] != after[key]:
                    raise ValueError(f"non-size feature changed: {case['name']} {key}")
        cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (OUTPUT / f"{case['name']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    manifest = {
        "stage": "B_size_distribution",
        "source": str(SOURCE),
        "common_seed": SEED,
        "base_total_p32": base_total_p32,
        "probes": [name for name, _ in PROBES],
        "cases": [case["name"] for case in cases],
        "changed_feature_group": "size_alpha_or_size_r_max",
        "controlled_features": [
            "joint_set_structure",
            "P32",
            "mean_spacing",
            "orientation",
            "domain",
            "tunnel",
            "boreholes",
            "rqd",
            "Jr_Ja",
        ],
        "approval_status": "validated_for_screening",
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
