"""Coverage-round ledger utilities for adaptive simulation campaigns."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _bin_map(audit: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {int(row["bin_index"]): row for row in audit.get("bins", [])}


def coverage_delta(
    before: Dict[str, Any] | None,
    after: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare two coverage audits without interpreting suitability."""
    after_bins = _bin_map(after)
    before_bins = _bin_map(before or {})
    before_unobserved = {
        index for index, row in before_bins.items() if row.get("status") == "UNOBSERVED"
    }
    after_unobserved = {
        index for index, row in after_bins.items() if row.get("status") == "UNOBSERVED"
    }
    return {
        "observed_qprime_range_before": (
            [before["observed_min"], before["observed_max"]] if before else None
        ),
        "observed_qprime_range_after": [after["observed_min"], after["observed_max"]],
        "unobserved_bins_before": len(before_unobserved),
        "unobserved_bins_after": len(after_unobserved),
        "newly_observed_bins": sorted(before_unobserved - after_unobserved),
        "remaining_gap_bins": sorted(after_unobserved),
        "unobserved_bin_delta": len(after_unobserved) - len(before_unobserved),
    }


def deduplicate_domain_records(
    records: Iterable[Dict[str, Any]],
    *,
    domain_key: str = "domain_id",
    signature_key: str = "generation_signature_hash",
) -> Dict[str, Any]:
    """Separate duplicate domains from records eligible for a new round."""
    seen = set()
    unique: List[Dict[str, Any]] = []
    duplicates: List[Any] = []
    for row in records:
        domain = row.get(domain_key)
        signature = row.get(signature_key)
        identity = (domain, signature)
        if domain in {None, ""}:
            raise KeyError(f"records must contain a non-empty '{domain_key}'")
        if identity in seen:
            duplicates.append(domain)
            continue
        seen.add(identity)
        unique.append(dict(row))
    return {
        "unique_records": unique,
        "duplicate_domain_ids": sorted(set(duplicates), key=str),
        "n_unique": len(unique),
        "n_duplicates": len(duplicates),
    }


def build_round_record(
    *,
    round_id: int,
    run_id: str,
    round_type: str,
    after_audit: Dict[str, Any],
    before_audit: Dict[str, Any] | None = None,
    parent_round_id: int | None = None,
    n_domains: int | None = None,
    n_signatures: int | None = None,
    status: str = "provisional",
    next_action: str = "expand",
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build one JSONL-compatible summary row for a coverage round."""
    if round_id < 0:
        raise ValueError("round_id must be non-negative")
    if not run_id:
        raise ValueError("run_id must not be empty")
    record = {
        "round_id": int(round_id),
        "run_id": run_id,
        "parent_round_id": parent_round_id,
        "round_type": round_type,
        "n_domains": n_domains,
        "n_signatures": n_signatures,
        "status": status,
        "next_action": next_action,
    }
    record.update(coverage_delta(before_audit, after_audit))
    if extra:
        record.update(extra)
    return record


def append_ledger(path: str, record: Dict[str, Any]) -> None:
    """Append one round record to a JSON Lines ledger."""
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


__all__ = [
    "append_ledger",
    "build_round_record",
    "coverage_delta",
    "deduplicate_domain_records",
]
