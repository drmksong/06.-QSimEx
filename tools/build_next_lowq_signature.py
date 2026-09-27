"""Build one evidence-combined low-Q coverage signature."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml


SOURCE = Path("cases/a_density/a_density_8x_3set.yaml")
OUTPUT = Path("cases/next_lowq")
SEED = 321
MEAN_DIP = 60.0
MEAN_DIP_DIR = 60.0


def main() -> int:
    case = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    case["name"] = "next_lowq_density8_angle49_3set"
    case["description"] = (
        "Evidence-combined low-Q coverage probe: validated high-density "
        "signature plus high borehole-plane-angle orientation."
    )
    case["seed"] = SEED
    case["tags"] = {
        "coverage_stage": "next_lowq_signature",
        "parent_case": SOURCE.stem,
        "density_factor": 8.0,
        "mean_dip": MEAN_DIP,
        "mean_dip_dir": MEAN_DIP_DIR,
        "expected_borehole_plane_angle_deg": 48.59037789072913,
        "common_seed": SEED,
        "evidence_sources": ["A_density", "C_angle"],
        "target_gap": "qprime_bh_below_1_204",
        "approval_status": "validated_for_screening",
    }
    for joint_set in case["joint_sets"]:
        joint_set["mean_dip"] = MEAN_DIP
        joint_set["mean_dip_dir"] = MEAN_DIP_DIR

    OUTPUT.mkdir(parents=True, exist_ok=True)
    case_path = OUTPUT / f"{case['name']}.yaml"
    case_path.write_text(
        yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest = {
        "stage": "next_lowq_signature",
        "case_path": str(case_path),
        "source": str(SOURCE),
        "common_seed": SEED,
        "target_gap": "qprime_bh_below_1_204",
        "evidence_sources": ["A_density", "C_angle"],
        "changed_feature_groups": ["density", "orientation_angle"],
        "expected_effect": "extend_low_q_coverage",
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
