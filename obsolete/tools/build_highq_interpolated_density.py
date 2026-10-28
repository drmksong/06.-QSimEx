"""Build interpolated density-only additions for the existing round-014 portfolio."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/scenario_12_coverage_high_q.yaml")
OUTPUT = Path("cases/highq_portfolio")
FACTORS = (10.0, 31.6227766017)
SEEDS = (325, 326, 327, 328)


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_p32 = float(source["joint_sets"][0]["P32"])
    cases = []
    for factor in FACTORS:
        label = "10" if factor == 10.0 else "31p6"
        case = copy.deepcopy(source)
        case["name"] = f"highq_d{label}_interp_base_base"
        case["description"] = (
            "Round-014 interpolated high-Q density probe; existing parent orientation "
            "and size are preserved while density is sampled between validated factors."
        )
        case["seed"] = SEEDS[0]
        case["tags"] = {
            "coverage_stage": "high_q_portfolio_interpolation",
            "parent_case": SOURCE.stem,
            "density_factor": factor,
            "interpolation_space": "log_density_factor",
            "screening_seeds": list(SEEDS),
            "approval_status": "proposed_review_before_execution",
        }
        for joint_set in case["joint_sets"]:
            joint_set["P32"] = base_p32 * factor
        path = OUTPUT / f"{case['name']}.yaml"
        path.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8")
        cases.append({"name": case["name"], "path": str(path), "factor": factor})

    manifest = {
        "stage": "high_q_portfolio_interpolation",
        "parent_round": 14,
        "parent_density_factors": [5.0, 20.0, 50.0],
        "interpolation_space": "log_density_factor",
        "interpolated_factors": list(FACTORS),
        "seeds": list(SEEDS),
        "cases": cases,
        "status": "proposed_review_before_execution",
    }
    (OUTPUT / "interpolated_density_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
