"""Build high-density bridge probes from the high-Q parent."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/scenario_12_coverage_high_q.yaml")
OUTPUT = Path("cases/highq_dense_bridge")
DENSITY_FACTORS = (100.0, 250.0, 500.0)
SEEDS = (329, 330, 331, 332)
TARGET_GAP = [76.14615754863519, 174.5235314204193]


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    base_p32 = float(source["joint_sets"][0]["P32"])
    cases = []
    for factor in DENSITY_FACTORS:
        case = copy.deepcopy(source)
        case["name"] = f"highq_dense_bridge_{int(factor)}x"
        case["description"] = (
            "High-Q dense bridge probe; P32 increased strongly while size, "
            "orientation, structure, geometry, and material inputs remain fixed."
        )
        case["seed"] = SEEDS[0]
        case["tags"] = {
            "coverage_stage": "high_q_dense_bridge",
            "parent_case": SOURCE.stem,
            "density_factor": factor,
            "target_gap_qprime_bh": TARGET_GAP,
            "screening_seeds": list(SEEDS),
            "changed_feature": "P32",
            "approval_status": "proposed_review_before_execution",
        }
        for joint_set in case["joint_sets"]:
            joint_set["P32"] = base_p32 * factor
        cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (OUTPUT / f"{case['name']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    manifest = {
        "stage": "high_q_dense_bridge",
        "source": str(SOURCE),
        "target_gap_qprime_bh": TARGET_GAP,
        "density_factors": list(DENSITY_FACTORS),
        "base_p32": base_p32,
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
