"""Build one high-Q bridge signature from the validated high-Q parent."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/scenario_12_coverage_high_q.yaml")
OUTPUT = Path("cases/next_highq")
SEED = 325
DENSITY_FACTOR = 5.0
TARGET_GAP = [76.14615754863519, 174.5235314204193]


def main() -> int:
    case = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    case["name"] = "next_highq_bridge_density5x"
    case["description"] = (
        "High-Q bridge probe from scenario_12; P32 increased fivefold while "
        "size, orientation, structure, geometry, and material inputs remain fixed."
    )
    case["seed"] = SEED
    case["tags"] = {
        "coverage_stage": "next_highq_bridge",
        "parent_case": SOURCE.stem,
        "density_factor": DENSITY_FACTOR,
        "target_gap_qprime_bh": TARGET_GAP,
        "common_seed": SEED,
        "changed_feature": "P32",
        "matched_non_density_features": True,
        "approval_status": "validated_for_screening",
    }
    for joint_set in case["joint_sets"]:
        joint_set["P32"] = float(joint_set["P32"]) * DENSITY_FACTOR

    OUTPUT.mkdir(parents=True, exist_ok=True)
    case_path = OUTPUT / f"{case['name']}.yaml"
    case_path.write_text(
        yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest = {
        "stage": "next_highq_bridge",
        "source": str(SOURCE),
        "case_path": str(case_path),
        "common_seed": SEED,
        "density_factor": DENSITY_FACTOR,
        "target_gap_qprime_bh": TARGET_GAP,
        "changed_feature": "P32",
        "expected_effect": "move_high_q_parent_toward_internal_high_gap",
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
