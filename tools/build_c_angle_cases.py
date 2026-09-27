"""Build angle-controlled orientation probes for borehole sensitivity analysis."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import yaml


SOURCE = Path("cases/a_density/a_density_4x_3set.yaml")
OUTPUT = Path("cases/c_angle")
SEED = 317
DIRECTIONS = (0.0, 5.0, 15.0, 30.0, 60.0, 90.0)
FIXED_DIP = 60.0


def expected_plane_angle(dip: float, dip_dir: float) -> float:
    normal_x = abs(math.sin(math.radians(dip)) * math.sin(math.radians(dip_dir)))
    return math.degrees(math.asin(normal_x))


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_total_p32 = sum(float(item["P32"]) for item in source["joint_sets"])
    cases = []
    for direction in DIRECTIONS:
        case = copy.deepcopy(source)
        label = f"dir_{int(direction):03d}"
        case["name"] = f"c_angle_{label}_4x_3set"
        case["description"] = (
            "Angle-controlled orientation probe; dip fixed at 60 degrees and "
            "dip direction varied to control borehole-plane angle."
        )
        case["seed"] = SEED
        case["tags"] = {
            "coverage_stage": "C_orientation_angle_control",
            "parent_case": SOURCE.stem,
            "mean_dip_fixed": FIXED_DIP,
            "mean_dip_dir": direction,
            "expected_borehole_plane_angle_deg": expected_plane_angle(FIXED_DIP, direction),
            "common_seed": SEED,
            "matched_non_orientation_features": True,
        }
        for joint_set in case["joint_sets"]:
            joint_set["mean_dip"] = FIXED_DIP
            joint_set["mean_dip_dir"] = direction
        cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (OUTPUT / f"{case['name']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    manifest = {
        "stage": "C_orientation_angle_control",
        "source": str(SOURCE),
        "common_seed": SEED,
        "fixed_mean_dip": FIXED_DIP,
        "dip_directions": list(DIRECTIONS),
        "expected_plane_angles_deg": [expected_plane_angle(FIXED_DIP, value) for value in DIRECTIONS],
        "changed_feature": "mean_dip_dir",
        "controlled_features": [
            "joint_set_structure",
            "P32",
            "size_distribution",
            "mean_dip",
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
