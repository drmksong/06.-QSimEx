"""Build matched orientation probes for the C exploration stage."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/a_density/a_density_4x_3set.yaml")
OUTPUT = Path("cases/c_orientation")
SEED = 317
PROBES = (
    ("dip_high", {"mean_dip": 60.0}),
    ("direction_rotated", {"mean_dip_dir": 90.0}),
    ("spread_wide", {"fisher_kappa": 10.0}),
)


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_total_p32 = sum(float(item["P32"]) for item in source["joint_sets"])
    base_sets = source["joint_sets"]
    cases = []
    for probe_name, changes in PROBES:
        case = copy.deepcopy(source)
        case["name"] = f"c_orientation_{probe_name}_4x_3set"
        case["description"] = (
            "C-only matched orientation probe; total P32, joint-set structure, "
            "size distribution, geometry, and material inputs fixed."
        )
        case["seed"] = SEED
        case["tags"] = {
            "coverage_stage": "C_orientation",
            "parent_case": SOURCE.stem,
            "orientation_probe": probe_name,
            "common_seed": SEED,
            "matched_non_orientation_features": True,
        }
        for joint_set in case["joint_sets"]:
            joint_set.update(changes)
        if abs(sum(float(item["P32"]) for item in case["joint_sets"]) - base_total_p32) > 1e-12:
            raise ValueError(f"P32 changed for {case['name']}")
        for before, after in zip(base_sets, case["joint_sets"]):
            for key in (
                "set_id",
                "P32",
                "mean_spacing",
                "size_alpha",
                "size_r_min",
                "size_r_max",
                "Jr_mean",
                "Jr_std",
                "Ja_mean",
                "Ja_std",
            ):
                if before[key] != after[key]:
                    raise ValueError(f"non-orientation feature changed: {case['name']} {key}")
        cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (OUTPUT / f"{case['name']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    manifest = {
        "stage": "C_orientation",
        "source": str(SOURCE),
        "common_seed": SEED,
        "base_total_p32": base_total_p32,
        "probes": [name for name, _ in PROBES],
        "cases": [case["name"] for case in cases],
        "changed_feature_group": "mean_dip_or_mean_dip_dir_or_fisher_kappa",
        "controlled_features": [
            "joint_set_structure",
            "P32",
            "size_distribution",
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
