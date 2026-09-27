"""Build matched density probes from the confirmed 3-set D structure."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/d_matched/d_matched_3set.yaml")
OUTPUT = Path("cases/a_density")
SEED = 305
FACTORS = (0.5, 2.0)


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_total = sum(float(item["P32"]) for item in source["joint_sets"])
    cases = []
    for factor in FACTORS:
        case = copy.deepcopy(source)
        case["name"] = f"a_density_{factor:g}x_3set"
        case["description"] = (
            "A-only density probe on confirmed 3-set D structure; "
            "all non-density features fixed."
        )
        case["seed"] = SEED
        case["tags"] = {
            "coverage_stage": "A_density",
            "parent_case": SOURCE.stem,
            "density_factor": factor,
            "common_seed": SEED,
            "matched_non_density_features": True,
        }
        for joint_set in case["joint_sets"]:
            joint_set["P32"] = float(joint_set["P32"]) * factor
        total = sum(float(item["P32"]) for item in case["joint_sets"])
        if abs(total - base_total * factor) > 1e-12:
            raise ValueError(f"density total mismatch for {case['name']}")
        cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (OUTPUT / f"{case['name']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    manifest = {
        "stage": "A_density",
        "source": str(SOURCE),
        "common_seed": SEED,
        "base_total_p32": base_total,
        "density_factors": list(FACTORS),
        "cases": [case["name"] for case in cases],
        "changed_feature": "total_p32",
        "controlled_features": [
            "joint_set_count",
            "size_distribution",
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
