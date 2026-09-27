"""Build the next signature from reviewed local probe responses."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from src.core.signature_candidates import build_euler_update_candidate_from_probes


def load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--feature-bounds", required=True)
    parser.add_argument("--probes", required=True)
    parser.add_argument("--round-id", type=int, required=True)
    parser.add_argument("--target-region", required=True)
    parser.add_argument("--screening-seed", type=int, required=True)
    parser.add_argument("--step-size", type=float, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--generator-version", default="qsimex-generation-v1")
    args = parser.parse_args(argv)

    bounds = {
        path: tuple(values)
        for path, values in load_json(args.feature_bounds).items()
    }
    probes = load_json(args.probes)
    candidate = build_euler_update_candidate_from_probes(
        args.case,
        round_id=args.round_id,
        target_region=args.target_region,
        screening_seed=args.screening_seed,
        feature_bounds=bounds,
        probes=probes,
        step_size=args.step_size,
        generator_version=args.generator_version,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    case_path = output_dir / f"{candidate['candidate_id']}.yaml"
    case_path.write_text(
        yaml.safe_dump(candidate["case"], sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    candidate["case_path"] = str(case_path)
    (output_dir / "candidate.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_id": candidate["candidate_id"],
                "case_path": str(case_path),
                "generation_signature_hash": candidate["generation_signature_hash"],
                "domain_id": candidate["domain_id"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
