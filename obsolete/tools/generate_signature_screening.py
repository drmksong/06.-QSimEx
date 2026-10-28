"""Generate a reviewable common-seed signature screening round."""

import argparse
import json
import sys
from pathlib import Path

# Allow direct execution from the QSimEx repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.signature_candidates import (
    build_simulation_manifest,
    build_gap_screening_pool,
    write_candidate_cases,
)


def parse_case_target(value: str) -> dict[str, str]:
    """Parse ``case_path=target_region`` command-line values."""
    case_path, separator, target_region = value.partition("=")
    if not separator or not case_path or not target_region:
        raise argparse.ArgumentTypeError(
            "case targets must use CASE_PATH=TARGET_REGION"
        )
    return {"case_path": case_path, "target_region": target_region}


def load_json(path: str):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a common-seed generation-signature screening pool."
    )
    parser.add_argument("--round-id", type=int, required=True)
    parser.add_argument("--screening-seed", type=int, required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--strategy-catalog", required=True)
    parser.add_argument("--max-candidates", type=int, required=True)
    parser.add_argument("--time-budget-seconds", type=float)
    parser.add_argument(
        "--time-budget-by-gap",
        help="JSON object mapping low_q_gap/internal_gap/high_q_gap to seconds",
    )
    parser.add_argument(
        "--case-target",
        type=parse_case_target,
        action="append",
        required=True,
        help="CASE_PATH=TARGET_REGION; repeat for each parent signature",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--correction-mode", default="pure")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    candidate_dir = output_dir / "candidates"
    audit = load_json(args.audit)
    strategy_catalog = load_json(args.strategy_catalog)
    time_budget_by_gap = (
        load_json(args.time_budget_by_gap) if args.time_budget_by_gap else None
    )
    pool = build_gap_screening_pool(
        audit,
        args.case_target,
        round_id=args.round_id,
        screening_seed=args.screening_seed,
        strategy_catalog=strategy_catalog,
        max_candidates=args.max_candidates,
        time_budget_seconds=args.time_budget_seconds,
        time_budget_by_gap=time_budget_by_gap,
    )
    write_candidate_cases(pool, str(candidate_dir))
    manifest = build_simulation_manifest(
        pool,
        round_id=args.round_id,
        output_dir=str(output_dir / "simulation"),
        backend=args.backend,
        correction_mode=args.correction_mode,
        screening_seed=args.screening_seed,
        seed_policy="one common seed per screening iteration",
        time_budget_seconds=args.time_budget_seconds,
        time_budget_by_gap=time_budget_by_gap,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "generation_signature_candidates.json").write_text(
        json.dumps(pool, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(
        f"generated candidates={len(pool)} seed={args.screening_seed} "
        f"output={output_dir} approval_required={manifest['approval_required']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())