"""Coverage-round ledger utilities for adaptive simulation campaigns."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .signature_candidates import estimate_euler_direction, euler_update_feature_vector
from .profile_exploration import audit_qprime_coverage, load_csv_records


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


def audit_borehole_csv(
    path: str,
    *,
    qprime_bh_key: str = "Qp_bh_mean",
    cutoffs: Iterable[float] | None = None,
) -> Dict[str, Any]:
    """Convert one batch-runner borehole CSV into a provenance-aware audit."""
    return audit_borehole_records(
        load_csv_records(path), qprime_bh_key=qprime_bh_key,
        cutoffs=cutoffs, source_csv=str(Path(path)),
    )


def audit_borehole_records(
    records: Iterable[Dict[str, Any]],
    *,
    qprime_bh_key: str = "Qp_bh_mean",
    cutoffs: Iterable[float] | None = None,
    source_csv: str | None = None,
) -> Dict[str, Any]:
    """Audit in-memory campaign records with the same CSV provenance rules."""
    records = list(records)
    if not records:
        raise ValueError("borehole CSV contains no records")
    has_domain_metadata = all(
        row.get("domain_id") not in {None, ""}
        and row.get("generation_signature_hash") not in {None, ""}
        for row in records
    )
    domain_keys = ("domain_id",) if has_domain_metadata else ("case_name", "seed")
    audit = audit_qprime_coverage(
        records,
        qprime_bh_key=qprime_bh_key,
        cutoffs=cutoffs,
        domain_keys=domain_keys,
    )
    audit.update(
        {
            "source_csv": source_csv,
            "domain_keys": list(domain_keys),
            "provenance_status": "complete" if has_domain_metadata else "incomplete",
            "n_records_with_domain_id": sum(
                row.get("domain_id") not in {None, ""} for row in records
            ),
            "n_records_with_generation_signature_hash": sum(
                row.get("generation_signature_hash") not in {None, ""}
                for row in records
            ),
        }
    )
    return audit
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


def build_screening_round_record(
    *,
    round_id: int,
    run_id: str,
    after_audit: Dict[str, Any],
    candidates: Iterable[Dict[str, Any]],
    before_audit: Dict[str, Any] | None = None,
    parent_round_id: int | None = None,
    round_type: str = "coverage_screening",
    status: str = "provisional",
    next_action: str = "expand",
    runtime_status: str = "planned",
    actual_runtime_seconds: float | None = None,
    euler_update: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Combine candidate identity, audit delta, and execution metadata."""
    candidate_list = list(candidates)
    signature_hashes = {
        candidate.get("generation_signature_hash")
        for candidate in candidate_list
        if candidate.get("generation_signature_hash")
    }
    domain_ids = {
        candidate.get("domain_id")
        for candidate in candidate_list
        if candidate.get("domain_id")
    }
    extra: Dict[str, Any] = {
        "candidate_ids": [candidate.get("candidate_id") for candidate in candidate_list],
        "candidate_signature_hashes": sorted(signature_hashes),
        "candidate_domain_ids": sorted(domain_ids),
        "candidate_count": len(candidate_list),
        "runtime_status": runtime_status,
    }
    if actual_runtime_seconds is not None:
        if actual_runtime_seconds < 0:
            raise ValueError("actual_runtime_seconds must be non-negative")
        extra["actual_runtime_seconds"] = float(actual_runtime_seconds)
    if euler_update is not None:
        extra["euler_update"] = dict(euler_update)
    return build_round_record(
        round_id=round_id,
        run_id=run_id,
        round_type=round_type,
        after_audit=after_audit,
        before_audit=before_audit,
        parent_round_id=parent_round_id,
        n_domains=len(domain_ids),
        n_signatures=len(signature_hashes),
        status=status,
        next_action=next_action,
        extra=extra,
    )


def record_screening_round_from_csv(
    *,
    after_csv: str,
    candidates: Iterable[Dict[str, Any]],
    round_id: int,
    run_id: str,
    ledger_path: str | None = None,
    before_audit: Dict[str, Any] | None = None,
    parent_round_id: int | None = None,
    cutoffs: Iterable[float] | None = None,
    runtime_status: str = "completed",
    actual_runtime_seconds: float | None = None,
) -> Dict[str, Any]:
    """Audit a runner CSV and optionally append its screening ledger record."""
    after_audit = audit_borehole_csv(after_csv, cutoffs=cutoffs)
    record = build_screening_round_record(
        round_id=round_id,
        run_id=run_id,
        before_audit=before_audit,
        after_audit=after_audit,
        candidates=candidates,
        parent_round_id=parent_round_id,
        runtime_status=runtime_status,
        actual_runtime_seconds=actual_runtime_seconds,
    )
    if ledger_path is not None:
        append_ledger(ledger_path, record)
    return {"audit": after_audit, "record": record}


def build_euler_update_record(
    *,
    feature_vector: Dict[str, float],
    feature_delta: Dict[str, float],
    coverage_delta_record: Dict[str, float],
    coverage_residual: Dict[str, float],
    step_size: float,
    bounds: Dict[str, tuple[float, float]],
    discrete_features: Iterable[str] = (),
) -> Dict[str, Any]:
    """Record one bounded explicit-Euler-style signature update."""
    direction = estimate_euler_direction(
        feature_delta,
        coverage_delta_record,
        coverage_residual,
    )
    updated_features = euler_update_feature_vector(
        feature_vector,
        direction,
        step_size=step_size,
        bounds=bounds,
        discrete_features=discrete_features,
    )
    return {
        "update_method": "bounded_explicit_euler_style",
        "feature_vector_before": dict(feature_vector),
        "feature_delta": dict(feature_delta),
        "coverage_delta": dict(coverage_delta_record),
        "coverage_residual": dict(coverage_residual),
        "direction": direction,
        "step_size": float(step_size),
        "feature_vector_after": updated_features,
        "discrete_features": sorted(set(discrete_features)),
    }


def append_ledger(path: str, record: Dict[str, Any]) -> None:
    """Append one round record to a JSON Lines ledger."""
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


__all__ = [
    "audit_borehole_csv",
    "append_ledger",
    "build_round_record",
    "build_screening_round_record",
    "build_euler_update_record",
    "coverage_delta",
    "deduplicate_domain_records",
    "record_screening_round_from_csv",
]
