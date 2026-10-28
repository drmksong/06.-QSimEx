"""Build matched joint-set-structure cases for the D screening stage."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/scenario_11_coverage_low_q.yaml")
OUTPUT = Path("cases/d_matched")
TOTAL_P32 = 10.5
SEED = 302
SET_COUNTS = (1, 2, 3)


def build_cases() -> list[dict]:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    template = copy.deepcopy(source["joint_sets"][0])
    cases = []
    for set_count in SET_COUNTS:
        case = copy.deepcopy(source)
        case["name"] = f"d_matched_{set_count}set"
        case["description"] = (
            "D-only matched joint-set structure probe; total P32, "
            "size distribution, orientation, geometry, and material inputs fixed."
        )
        case["seed"] = SEED
        case["tags"] = {
            "coverage_stage": "D_joint_set_structure",
            "matched_group": "d_matched_total_p32_10_5",
            "joint_set_count": set_count,
            "common_seed": SEED,
            "immutable_source": str(SOURCE),
        }
        joint_sets = []
        for index in range(set_count):
            joint_set = copy.deepcopy(template)
            joint_set["set_id"] = index + 1
            joint_set["name"] = f"matched_template_{index + 1}"
            joint_set["P32"] = TOTAL_P32 / set_count
            joint_sets.append(joint_set)
        case["joint_sets"] = joint_sets
        cases.append(case)
    return cases


def validate(cases: list[dict]) -> None:
    reference = cases[0]["joint_sets"][0]
    for case in cases:
        total_p32 = sum(float(item["P32"]) for item in case["joint_sets"])
        if abs(total_p32 - TOTAL_P32) > 1e-12:
            raise ValueError(f"total P32 mismatch: {case['name']}")
        for item in case["joint_sets"]:
            for key in (
                "size_alpha",
                "size_r_min",
                "size_r_max",
                "mean_dip",
                "mean_dip_dir",
                "fisher_kappa",
                "Jr_mean",
                "Jr_std",
                "Ja_mean",
                "Ja_std",
            ):
                if item[key] != reference[key]:
                    raise ValueError(f"non-D feature changed: {case['name']} {key}")


def main() -> int:
    cases = build_cases()
    validate(cases)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (OUTPUT / f"{case['name']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    manifest = {
        "stage": "D_joint_set_structure",
        "source": str(SOURCE),
        "common_seed": SEED,
        "total_p32": TOTAL_P32,
        "set_counts": list(SET_COUNTS),
        "cases": [case["name"] for case in cases],
        "controlled_features": [
            "size_alpha",
            "size_r_min",
            "size_r_max",
            "mean_dip",
            "mean_dip_dir",
            "fisher_kappa",
            "Jr_mean",
            "Jr_std",
            "Ja_mean",
            "Ja_std",
            "domain",
            "tunnel",
            "boreholes",
            "rqd",
        ],
        "changed_feature": "joint_set_count_and_p32_allocation",
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
