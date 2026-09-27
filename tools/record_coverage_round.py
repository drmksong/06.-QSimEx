"""Record a completed coverage round from runner output artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow direct execution from the QSimEx repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.coverage_rounds import record_screening_round_from_csv


def load_json(path: str):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert runner CSV output into coverage audit and ledger artifacts."
    )
    parser.add_argument("--after-csv", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--round-id", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--audit-output", required=True)
    parser.add_argument("--before-audit")
    parser.add_argument("--parent-round-id", type=int)
    parser.add_argument("--cutoffs", type=float, nargs="+")
    parser.add_argument("--runtime-status", default="completed")
    parser.add_argument("--actual-runtime-seconds", type=float)
    args = parser.parse_args(argv)

    candidate_payload = load_json(args.candidates)
    candidates = (
        candidate_payload.get("candidates", [])
        if isinstance(candidate_payload, dict)
        else candidate_payload
    )
    before_audit = load_json(args.before_audit) if args.before_audit else None
    result = record_screening_round_from_csv(
        after_csv=args.after_csv,
        candidates=candidates,
        round_id=args.round_id,
        run_id=args.run_id,
        ledger_path=args.ledger,
        before_audit=before_audit,
        parent_round_id=args.parent_round_id,
        cutoffs=args.cutoffs,
        runtime_status=args.runtime_status,
        actual_runtime_seconds=args.actual_runtime_seconds,
    )
    Path(args.audit_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.audit_output).write_text(
        json.dumps(result["audit"], ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(
        f"recorded round={args.round_id} run={args.run_id} "
        f"provenance={result['audit']['provenance_status']} "
        f"ledger={args.ledger}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
