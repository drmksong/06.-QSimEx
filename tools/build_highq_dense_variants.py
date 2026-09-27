"""Build dense replacements for the original high-Q portfolio variants."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

SOURCE_DIR = Path("cases/highq_portfolio")
OUTPUT_DIR = Path("cases/highq_portfolio")
SOURCE_VARIANTS = (
    "highq_d5_base_base.yaml",
    "highq_d5_base_compact.yaml",
    "highq_d5_rotated_base.yaml",
    "highq_d5_rotated_compact.yaml",
)
DENSITY_FACTORS = (100.0, 250.0, 500.0)
BASE_FACTOR = 5.0


def main() -> int:
    cases = []
    for source_name in SOURCE_VARIANTS:
        source = yaml.safe_load((SOURCE_DIR / source_name).read_text(encoding="utf-8"))
        variant = source_name.removeprefix("highq_d5_").removesuffix(".yaml")
        for factor in DENSITY_FACTORS:
            case = copy.deepcopy(source)
            label = int(factor)
            case["name"] = f"highq_dense_d{label}_{variant}"
            case["description"] = (
                "Dense replacement of the original high-Q variant; density increased "
                "while its orientation and size variant remain unchanged."
            )
            case["tags"] = {
                **(case.get("tags") or {}),
                "coverage_stage": "high_q_dense_replacement",
                "parent_case": source_name,
                "density_factor": factor,
                "replaces_original_density_factors": [5.0, 20.0, 50.0],
                "approval_status": "proposed_review_before_execution",
            }
            scale = factor / BASE_FACTOR
            for joint_set in case["joint_sets"]:
                joint_set["P32"] = float(joint_set["P32"]) * scale
            path = OUTPUT_DIR / f"{case['name']}.yaml"
            path.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8")
            cases.append(str(path))
    manifest = {
        "stage": "high_q_dense_replacement",
        "replaced_active_variants": list(SOURCE_VARIANTS),
        "density_factors": list(DENSITY_FACTORS),
        "candidate_count": len(cases),
        "paths": cases,
        "historical_originals_preserved": True,
        "status": "proposed_review_before_execution",
    }
    (OUTPUT_DIR / "dense_replacement_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
