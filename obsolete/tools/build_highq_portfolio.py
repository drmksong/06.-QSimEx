"""Build a structured high-Q coverage portfolio for many-seed screening."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/scenario_12_coverage_high_q.yaml")
OUTPUT = Path("cases/highq_portfolio")
DENSITY_FACTORS = (5.0, 20.0, 50.0)
ORIENTATION_VARIANTS = {
    "base": {"mean_dip": 60.0, "mean_dip_dir": 45.0, "fisher_kappa": 8.0},
    "rotated": {"mean_dip": 60.0, "mean_dip_dir": 90.0, "fisher_kappa": 8.0},
}
SIZE_VARIANTS = {
    "base": {"size_r_min": 10.0, "size_r_max": 100.0, "size_alpha": 2.5},
    "compact": {"size_r_min": 5.0, "size_r_max": 50.0, "size_alpha": 2.5},
}
SEEDS = (325, 326, 327, 328)
TARGET_GAP = [76.14615754863519, 174.5235314204193]


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_joint_set = source["joint_sets"][0]
    base_p32 = float(base_joint_set["P32"])
    cases = []
    for density_factor in DENSITY_FACTORS:
        for orientation_name, orientation in ORIENTATION_VARIANTS.items():
            for size_name, size in SIZE_VARIANTS.items():
                name = f"highq_d{int(density_factor)}_{orientation_name}_{size_name}"
                case = copy.deepcopy(source)
                case["name"] = name
                case["description"] = (
                    "High-Q portfolio probe; density, orientation, and size variant "
                    "are explicit factors for coverage reachability analysis."
                )
                case["seed"] = SEEDS[0]
                case["tags"] = {
                    "coverage_stage": "high_q_portfolio",
                    "parent_case": SOURCE.stem,
                    "target_gap_qprime_bh": TARGET_GAP,
                    "density_factor": density_factor,
                    "orientation_variant": orientation_name,
                    "size_variant": size_name,
                    "screening_seeds": list(SEEDS),
                    "approval_status": "proposed",
                }
                joint_set = case["joint_sets"][0]
                joint_set["P32"] = base_p32 * density_factor
                joint_set.update(orientation)
                joint_set.update(size)
                cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (OUTPUT / f"{case['name']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    manifest = {
        "stage": "high_q_portfolio",
        "source": str(SOURCE),
        "target_gap_qprime_bh": TARGET_GAP,
        "density_factors": list(DENSITY_FACTORS),
        "orientation_variants": ORIENTATION_VARIANTS,
        "size_variants": SIZE_VARIANTS,
        "seeds": list(SEEDS),
        "candidate_count": len(cases),
        "run_count": len(cases) * len(SEEDS),
        "status": "proposed_review_before_execution",
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
