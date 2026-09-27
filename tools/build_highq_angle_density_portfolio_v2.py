"""Build revised high-Q signatures using density and actual-angle paths."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

SOURCE = Path("cases/scenario_12_coverage_high_q.yaml")
OUTPUT = Path("cases/highq_portfolio_v2")
DENSITY_FACTORS = (1000.0, 2000.0, 5000.0, 10000.0)
ORIENTATION_VARIANTS = {
    "angle60_focused": {"mean_dip": 60.0, "mean_dip_dir": 90.0, "fisher_kappa": 8.0},
    "angle60_broad": {"mean_dip": 60.0, "mean_dip_dir": 90.0, "fisher_kappa": 2.0},
}
SIZE_VARIANTS = {
    "large_base": {"size_alpha": 2.5, "size_r_min": 10.0, "size_r_max": 100.0},
    "large_tail": {"size_alpha": 2.5, "size_r_min": 20.0, "size_r_max": 150.0},
}
SEEDS = (325, 326, 327, 328)


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_p32 = float(source["joint_sets"][0]["P32"])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for density in DENSITY_FACTORS:
        for orientation_name, orientation in ORIENTATION_VARIANTS.items():
            for size_name, size in SIZE_VARIANTS.items():
                case = copy.deepcopy(source)
                name = f"highq_v2_d{int(density)}_{orientation_name}_{size_name}"
                case["name"] = name
                case["description"] = (
                    "Revised high-Q signature: strong density, angle-controlled orientation, "
                    "and large-fracture size range; no small-size reduction."
                )
                case["seed"] = SEEDS[0]
                case["tags"] = {
                    "coverage_stage": "high_q_portfolio_v2",
                    "parent_case": SOURCE.stem,
                    "density_factor": density,
                    "orientation_variant": orientation_name,
                    "expected_mean_plane_angle_deg": 60.0,
                    "size_variant": size_name,
                    "screening_seeds": list(SEEDS),
                    "target_gap_qprime_bh": [76.14615754863519, 174.5235314204193],
                    "approval_status": "proposed_review_before_execution",
                }
                for joint_set in case["joint_sets"]:
                    joint_set["P32"] = base_p32 * density
                    joint_set.update(orientation)
                    joint_set.update(size)
                path = OUTPUT / f"{name}.yaml"
                path.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8")
                cases.append(str(path))
    manifest = {
        "stage": "high_q_portfolio_v2",
        "parent_round": 14,
        "source": str(SOURCE),
        "density_factors": list(DENSITY_FACTORS),
        "orientation_variants": ORIENTATION_VARIANTS,
        "size_variants": SIZE_VARIANTS,
        "seeds": list(SEEDS),
        "candidate_count": len(cases),
        "run_count": len(cases) * len(SEEDS),
        "status": "proposed_review_before_execution",
        "historical_portfolio_preserved": True,
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
