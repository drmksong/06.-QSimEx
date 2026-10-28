"""Build an additional high-Q portfolio with broader density and lower-Q features."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

SOURCE = Path("cases/scenario_12_coverage_high_q.yaml")
OUTPUT = Path("cases/highq_portfolio")
DENSITY_FACTORS = (100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0)
VARIANTS = {
    "highangle_micro": {
        "mean_dip": 60.0,
        "mean_dip_dir": 90.0,
        "fisher_kappa": 8.0,
        "size_alpha": 3.2,
        "size_r_min": 0.5,
        "size_r_max": 30.0,
    },
    "highangle_broad_medium": {
        "mean_dip": 60.0,
        "mean_dip_dir": 90.0,
        "fisher_kappa": 2.0,
        "size_alpha": 2.8,
        "size_r_min": 2.0,
        "size_r_max": 50.0,
    },
}
SEEDS = (325, 326, 327, 328)


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_p32 = float(source["joint_sets"][0]["P32"])
    cases = []
    for factor in DENSITY_FACTORS:
        for variant_name, variant in VARIANTS.items():
            case = copy.deepcopy(source)
            name = f"highq_exp_d{int(factor)}_{variant_name}"
            case["name"] = name
            case["description"] = (
                "Expanded high-Q coverage probe combining strongly increased density, "
                "high borehole-plane-angle orientation, and size-distribution variation."
            )
            case["seed"] = SEEDS[0]
            case["tags"] = {
                "coverage_stage": "high_q_expanded_portfolio",
                "parent_case": SOURCE.stem,
                "density_factor": factor,
                "orientation_variant": variant_name,
                "screening_seeds": list(SEEDS),
                "target_gap_qprime_bh": [76.14615754863519, 174.5235314204193],
                "approval_status": "proposed_review_before_execution",
            }
            for joint_set in case["joint_sets"]:
                joint_set["P32"] = base_p32 * factor
                joint_set.update(variant)
            cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for case in cases:
        path = OUTPUT / f"{case['name']}.yaml"
        path.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8")
        paths.append(str(path))
    manifest = {
        "stage": "high_q_expanded_portfolio",
        "parent_round": 14,
        "source": str(SOURCE),
        "density_factors": list(DENSITY_FACTORS),
        "variants": VARIANTS,
        "seeds": list(SEEDS),
        "additional_candidate_count": len(cases),
        "total_round014_candidate_count": 14 + len(cases),
        "run_count_additional": len(cases) * len(SEEDS),
        "paths": paths,
        "status": "proposed_review_before_execution",
    }
    (OUTPUT / "expanded_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
