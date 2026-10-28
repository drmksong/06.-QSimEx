"""Build one high-Q signature from the observed d5000->d10000 response."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

SOURCE = Path("cases/highq_portfolio_v2/highq_v2_d10000_angle60_focused_large_base.yaml")
OUTPUT = Path("cases/next_highq")
SEED = 333
DENSITY_FACTOR = 2.0
OBSERVED_RESPONSE = {
    "from_density_factor": 5000.0,
    "to_density_factor": 10000.0,
    "qprime_delta": -17.08,
    "rqd_delta": -6.29,
    "borehole_count_delta": 17.0,
}


def main() -> int:
    case = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    case["name"] = "highq_euler_d20000_focused_large_base"
    case["description"] = (
        "Single Euler-style high-Q update from the observed d5000 to d10000 "
        "response; density advanced one step while orientation and large size remain fixed."
    )
    case["seed"] = SEED
    case["tags"] = {
        "coverage_stage": "high_q_euler_update",
        "parent_case": SOURCE.stem,
        "parent_density_factor": 10000.0,
        "density_update_factor": DENSITY_FACTOR,
        "proposed_density_factor": 20000.0,
        "target_gap_qprime_bh": [76.14615754863519, 174.5235314204193],
        "update_method": "bounded_explicit_euler_style_density_step",
        "observed_response": OBSERVED_RESPONSE,
        "common_seed": SEED,
        "approval_status": "proposed_review_before_execution",
    }
    for joint_set in case["joint_sets"]:
        joint_set["P32"] = float(joint_set["P32"]) * DENSITY_FACTOR

    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{case['name']}.yaml"
    path.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8")
    manifest = {
        "stage": "high_q_euler_update",
        "parent_case": str(SOURCE),
        "case_path": str(path),
        "seed": SEED,
        "proposed_density_factor": 20000.0,
        "observed_response": OBSERVED_RESPONSE,
        "target_gap_qprime_bh": [76.14615754863519, 174.5235314204193],
        "candidate_count": 1,
        "status": "proposed_review_before_execution",
    }
    (OUTPUT / "highq_euler_d20000_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
