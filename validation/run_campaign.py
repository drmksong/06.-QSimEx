"""Run an isolated QSimEx validation campaign.

The campaign owns its configs, runner outputs, audits, and ledger under one
work directory. It never reads prior production result directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, cast

import yaml

# Allow execution from the QSimEx repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.core.coverage_rounds import (
    audit_borehole_records,
    append_ledger,
    build_round_record,
    build_signature_overlap_report,
)
from src.core.signature_candidates import (
    apply_normalized_features,
    build_reviewed_strategy_candidate,
    build_euler_update_candidate_from_probes,
    compute_domain_id,
    compute_generation_signature_hash,
    extract_normalized_features,
    load_case_mapping,
    plan_gap_candidates,
    validate_strategy_catalog,
)
from src.core.profile_exploration import (
    audit_qprime_coverage,
    load_csv_records,
    search_profile_boundaries,
)
from src.core.qprime_cutoff_search import generate_qprime_cutoffs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--seed-stop", type=int, required=True)
    parser.add_argument("--iterations", type=int, default=4000)
    parser.add_argument("--backend", default="mlx")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Archive an existing isolated campaign before starting fresh",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted strategy-catalog campaign from its checkpoint",
    )
    parser.add_argument(
        "--stop-on-identified",
        action="store_true",
        help="Stop early when profile screening returns identified",
    )
    parser.add_argument(
        "--initial-csv",
        help="Reuse a completed iteration-0 borehole CSV in a new campaign workdir",
    )
    parser.add_argument(
        "--euler-spec",
        help="JSON spec containing case_path, feature_bounds, probes, and step_size",
    )
    parser.add_argument(
        "--strategy-catalog",
        help="Reviewed YAML/JSON gap-to-strategy catalog for planning or execution",
    )
    parser.add_argument(
        "--max-candidates-per-iteration",
        type=int,
        help="Optional cap on candidate plans; defaults to all catalog strategies",
    )
    parser.add_argument(
        "--repeatability-seed",
        type=int,
        action="append",
        default=[],
        help="Explicit independent E-phase seed; may be repeated",
    )
    return parser.parse_args(argv)


def load_main_strategy_catalog(path: str) -> tuple[dict, dict]:
    """Load a reviewed catalog and validate each family's parent/probe contract."""
    catalog_path = Path(path).resolve()
    if not catalog_path.is_file():
        raise FileNotFoundError(str(catalog_path))
    if catalog_path.suffix.lower() == ".json":
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("strategy catalog must be a mapping")
    catalog = payload.get("strategy_catalog", payload)
    if not isinstance(catalog, dict):
        raise ValueError("strategy_catalog must be a mapping by target gap")
    validate_strategy_catalog(catalog)

    family_suffixes = {
        "A": (".P32", ".mean_spacing"),
        "B": (".size_alpha", ".size_r_min", ".size_r_max"),
        "C": (".mean_dip", ".mean_dip_dir", ".fisher_kappa"),
    }
    for target_gap, strategies in catalog.items():
        for strategy in strategies:
            required = ("status", "feature_family", "parent_signature", "parent_case_path")
            missing = [key for key in required if not strategy.get(key)]
            if missing:
                raise ValueError(
                    f"strategy for {target_gap} is missing required fields: {missing}"
                )
            if strategy["feature_family"] not in {"D", "A", "B", "C"}:
                raise ValueError("feature_family must be one of D, A, B, or C")
            parent_path = Path(strategy["parent_case_path"])
            if not parent_path.is_absolute():
                parent_path = REPO_ROOT / parent_path
            parent_path = parent_path.resolve()
            if not parent_path.is_file():
                raise FileNotFoundError(str(parent_path))
            parent_case = load_case_mapping(str(parent_path))
            actual_signature = compute_generation_signature_hash(parent_case)
            if actual_signature != strategy["parent_signature"]:
                raise ValueError(
                    f"parent signature mismatch for strategy {strategy['strategy_id']}"
                )
            strategy["parent_case_path"] = str(parent_path)
            if strategy["feature_family"] == "D":
                candidate_path = strategy.get("candidate_case_path")
                if not candidate_path:
                    raise ValueError(
                        f"D strategy {strategy['strategy_id']} requires candidate_case_path"
                    )
                candidate_path = Path(candidate_path)
                if not candidate_path.is_absolute():
                    candidate_path = REPO_ROOT / candidate_path
                candidate_path = candidate_path.resolve()
                if not candidate_path.is_file():
                    raise FileNotFoundError(str(candidate_path))
                candidate_signature = compute_generation_signature_hash(
                    load_case_mapping(str(candidate_path))
                )
                if candidate_signature == actual_signature:
                    raise ValueError(
                        f"D strategy {strategy['strategy_id']} does not change its signature"
                    )
                strategy["candidate_case_path"] = str(candidate_path)
            else:
                changes = strategy.get("changed_features")
                if not isinstance(changes, list) or len(changes) != 1:
                    raise ValueError(
                        f"{strategy['feature_family']} strategy {strategy['strategy_id']} "
                        "must specify exactly one changed feature"
                    )
                feature_name = changes[0].get("name", "")
                if not feature_name.endswith(family_suffixes[strategy["feature_family"]]):
                    raise ValueError(
                        f"feature {feature_name!r} does not belong to family "
                        f"{strategy['feature_family']}"
                    )
                feature = changes[0]
                bounds = feature.get("bounds")
                if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                    raise ValueError(
                        f"strategy {strategy['strategy_id']} requires explicit feature bounds"
                    )
                if "target_value" not in feature:
                    raise ValueError(
                        f"strategy {strategy['strategy_id']} requires explicit target_value"
                    )
                lower, upper = (float(bounds[0]), float(bounds[1]))
                target_value = float(feature["target_value"])
                if lower >= upper or not lower <= target_value <= upper:
                    raise ValueError(
                        f"strategy {strategy['strategy_id']} target_value is outside approved bounds"
                    )
                extract_normalized_features(
                    parent_case, {feature_name: (lower, upper)}
                )
                step_size = strategy.get("step_size")
                if (step_size is None or not math.isfinite(float(step_size))
                        or float(step_size) <= 0):
                    raise ValueError(
                        f"strategy {strategy['strategy_id']} requires a positive step_size"
                    )
                response_update = strategy.get("response_update")
                if response_update is not None:
                    if response_update.get("method") != "bounded_explicit_euler":
                        raise ValueError(
                            f"strategy {strategy['strategy_id']} has an unsupported response update"
                        )
                    target_bins = response_update.get("target_bins")
                    if (not isinstance(target_bins, list) or not target_bins
                            or any(not isinstance(index, int) or index < 0 or index >= 10
                                   for index in target_bins)):
                        raise ValueError(
                            f"strategy {strategy['strategy_id']} requires primary target_bins"
                        )
                    update_bounds = response_update.get("feature_bounds")
                    if update_bounds != {feature_name: list(bounds)}:
                        raise ValueError(
                            f"strategy {strategy['strategy_id']} response bounds must match its probe"
                        )
                    if float(response_update.get("step_size", 0.0)) != float(step_size):
                        raise ValueError(
                            f"strategy {strategy['strategy_id']} response step must match its probe"
                        )

    approved_catalog = {
        gap_class: [
            strategy for strategy in strategies
            if strategy["status"] == "approved_for_screening"
        ]
        for gap_class, strategies in catalog.items()
    }
    settings = {
        "max_candidates_per_iteration": payload.get("max_candidates_per_iteration"),
        "gap_class_priority": payload.get("gap_class_priority"),
    }
    return approved_catalog, settings


def plan_reviewed_catalog_gaps(
    audit: dict,
    strategy_catalog: dict,
    *,
    max_candidates: int | None = None,
    gap_class_priority: list[str] | None = None,
) -> dict:
    """Plan approved catalog strategies for remaining primary-grid gaps only."""
    gaps = [row for row in audit["bins"] if row.get("status") == "UNOBSERVED"]
    approved_catalog = {
        gap_class: [
            strategy for strategy in strategy_catalog.get(gap_class, ())
            if strategy.get("status") == "approved_for_screening"
        ]
        for gap_class in ("low_q_gap", "internal_gap", "high_q_gap")
    }
    applicable_catalog: dict[str, list[dict[str, Any]]] = {
        gap_class: strategies
        for gap_class, strategies in approved_catalog.items()
        if strategies and any(
            _gap_class_for_range(row, audit) == gap_class for row in gaps
        )
    }
    if not gaps:
        status = "all_primary_bins_observed"
        plans = []
    elif not applicable_catalog:
        status = "await_approved_strategy"
        plans = []
    else:
        total_strategies = sum(len(items) for items in applicable_catalog.values())
        plans = plan_gap_candidates(
            audit,
            strategy_catalog=cast(
                Dict[str, Iterable[Dict[str, Any]]], applicable_catalog
            ),
            max_candidates=max_candidates or total_strategies,
            gap_class_priority=gap_class_priority,
        )
        status = "review_required" if plans else "await_approved_strategy"
    planned_bins = {int(plan["bin_index"]) for plan in plans}
    return {
        "status": status,
        "remaining_unobserved_bins": [int(row["bin_index"]) for row in gaps],
        "planned_bins": sorted(planned_bins),
        "unplanned_bins": [
            int(row["bin_index"]) for row in gaps
            if int(row["bin_index"]) not in planned_bins
        ],
        "candidate_plans": plans,
    }


def _gap_class_for_range(gap: dict, audit: dict) -> str:
    observed_min = float(audit["observed_min"])
    observed_max = float(audit["observed_max"])
    lower = float(gap["qprime_bh_lower"])
    upper = float(gap["qprime_bh_upper"])
    if upper <= observed_min:
        return "low_q_gap"
    if lower >= observed_max:
        return "high_q_gap"
    return "internal_gap"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_ledger_snapshot(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def _read_complete_case_csv(path: Path, case_name: str, seeds: set[str]) -> list[dict] | None:
    if not path.is_file():
        return None
    rows = load_csv_records(str(path))
    selected = [row for row in rows if row.get("case_name") == case_name]
    actual_seeds = {str(row.get("seed")) for row in selected}
    if not selected or actual_seeds != seeds:
        return None
    if any(not row.get("domain_id") or not row.get("generation_signature_hash") for row in selected):
        return None
    return rows


def _materialize_catalog_plan(
    plan: dict,
    *,
    iteration: int,
    candidate_dir: Path,
    screening_seed: int,
) -> dict:
    candidate = build_reviewed_strategy_candidate(
        plan, round_id=iteration, screening_seed=screening_seed,
        generator_version=plan.get("generator_version", "qsimex-generation-v1"),
    )
    family = candidate["feature_family"]
    if family == "D":
        case_path = str(Path(candidate["candidate_case_path"]).resolve())
        reviewed_case = load_case_mapping(case_path)
        case_name = str(reviewed_case.get("name", Path(case_path).stem))
    else:
        stabilize_candidate_case_name(candidate, candidate["parent_case_path"])
        candidate_dir.mkdir(parents=True, exist_ok=True)
        case_path_obj = candidate_dir / f"{candidate['candidate_id']}.yaml"
        case_path_obj.write_text(
            yaml.safe_dump(candidate["case"], sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        _write_json_atomic(candidate_dir / f"{candidate['candidate_id']}.json", candidate)
        case_path = str(case_path_obj.resolve())
        case_name = str(candidate["case"].get("name", Path(case_path).stem))

    changed_feature = candidate.get("changed_feature") or {}
    feature_name = changed_feature.get("name")
    bounds = changed_feature.get("bounds")
    return {
        "entry_id": candidate["candidate_id"],
        "case_path": case_path,
        "case_name": case_name,
        "role": "candidate",
        "strategy_id": candidate["strategy_id"],
        "feature_family": family,
        "target_region": candidate["target_region"],
        "target_bin": candidate["bin_index"],
        "parent_case_path": candidate["parent_case_path"],
        "parent_signature": candidate["parent_signature"],
        "generation_signature_hash": candidate["generation_signature_hash"],
        "changed_feature": changed_feature,
        "orientation_validation": candidate.get("orientation_validation"),
        "feature_bounds": ({feature_name: list(bounds)} if feature_name and bounds else {}),
        "step_size": plan.get("step_size"),
        "selection_reason": candidate.get("selection_reason"),
        "expected_effect": candidate.get("expected_effect"),
        "response_update": plan.get("response_update"),
    }


def _materialize_response_update(
    candidate: dict,
    *,
    candidate_dir: Path,
    strategy_id: str,
    feature_family: str,
    target_bin: int,
    response_update: dict,
    measured_probe: dict,
) -> dict:
    feature_names = [
        name
        for name, before in candidate["normalized_features_before"].items()
        if candidate["normalized_features_after"].get(name) != before
    ]
    if len(feature_names) != 1:
        raise ValueError("paired-response Euler update must change exactly one feature")
    feature_name = feature_names[0]
    lower, upper = candidate["feature_bounds"][feature_name]
    span = float(upper) - float(lower)
    parent_value = float(lower) + span * float(
        candidate["normalized_features_before"][feature_name]
    )
    target_value = float(lower) + span * float(
        candidate["normalized_features_after"][feature_name]
    )
    changed_feature = {
        "name": feature_name,
        "parent_value": parent_value,
        "target_value": target_value,
        "bounds": [float(lower), float(upper)],
    }
    stabilize_candidate_case_name(candidate, candidate["parent_case_path"])
    candidate_dir.mkdir(parents=True, exist_ok=True)
    case_path = candidate_dir / f"{candidate['candidate_id']}.yaml"
    case_path.write_text(
        yaml.safe_dump(candidate["case"], sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    _write_json_atomic(candidate_dir / f"{candidate['candidate_id']}.json", candidate)
    parent = load_case_mapping(candidate["parent_case_path"])
    return {
        "entry_id": candidate["candidate_id"],
        "case_path": str(case_path.resolve()),
        "case_name": str(candidate["case"]["name"]),
        "role": "paired_response_update",
        "strategy_id": strategy_id,
        "feature_family": feature_family,
        "target_region": candidate["target_region"],
        "target_bin": int(target_bin),
        "parent_case_path": candidate["parent_case_path"],
        "parent_signature": compute_generation_signature_hash(parent),
        "generation_signature_hash": candidate["generation_signature_hash"],
        "changed_feature": changed_feature,
        "feature_bounds": {feature_name: [float(lower), float(upper)]},
        "step_size": candidate["step_size"],
        "selection_reason": "qualifying paired-seed response update",
        "expected_effect": "continue toward the reviewed target bin",
        "response_update": response_update,
        "measured_probe": measured_probe,
    }


def run_reviewed_strategy_campaign(
    args: argparse.Namespace,
    *,
    workdir: Path,
    manifest: dict,
    case_paths: list[str],
    initial_csv: str | None,
    strategy_catalog: dict,
    strategy_catalog_settings: dict,
    resume: bool,
) -> dict:
    checkpoint_path = workdir / "campaign_checkpoint.json"
    catalog_path = Path(str(manifest["strategy_catalog"]))
    contract = {
        "seed_range": [args.seed_start, args.seed_stop],
        "backend": args.backend,
        "case_paths": case_paths,
        "strategy_catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "repeatability_seeds": sorted(set(getattr(args, "repeatability_seed", []) or [])),
    }
    if resume:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("contract") != contract:
            raise ValueError("resume configuration or strategy catalog differs from checkpoint")
    else:
        checkpoint = {
            "schema_version": 1,
            "contract": contract,
            "completed_jobs": {},
            "attempted_plans": [],
            "ledger_records": [],
            "source_csvs": [],
            "current_iteration": 0,
            "status": "running",
        }

    ledger_path = workdir / "ledger.jsonl"
    primary_seeds = {str(seed) for seed in range(args.seed_start, args.seed_stop + 1)}
    repeatability_seeds = contract["repeatability_seeds"]
    if primary_seeds & {str(seed) for seed in repeatability_seeds}:
        raise ValueError("E-phase repeatability seeds must be independent of primary seeds")

    def persist() -> None:
        checkpoint["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json_atomic(checkpoint_path, checkpoint)
        _write_ledger_snapshot(ledger_path, checkpoint["ledger_records"])
        manifest["status"] = checkpoint["status"]
        manifest["records"] = checkpoint["ledger_records"]
        manifest["checkpoint_path"] = str(checkpoint_path)
        manifest["remaining_unobserved_bins"] = checkpoint.get("remaining_unobserved_bins", [])
        manifest["profile_cutoff_identified"] = checkpoint.get("profile_cutoff_identified", False)
        _write_json_atomic(workdir / "campaign_manifest.json", manifest)

    if initial_csv and initial_csv not in checkpoint["source_csvs"]:
        source_rows = load_csv_records(initial_csv)
        if any(not row.get("domain_id") or not row.get("generation_signature_hash") for row in source_rows):
            raise ValueError("initial CSV must contain domain_id and generation_signature_hash provenance")
        checkpoint["source_csvs"].append(initial_csv)

    def completed_paths() -> list[Path]:
        paths = [Path(path) for path in checkpoint["source_csvs"]]
        paths.extend(
            Path(job["csv_path"])
            for job in checkpoint["completed_jobs"].values()
            if job.get("status") == "completed" and job.get("phase") != "repeatability_E"
        )
        return paths

    def cumulative_rows() -> tuple[list[dict], dict[str, str], int]:
        all_rows = [row for path in completed_paths() for row in load_csv_records(str(path))]
        domain_signatures: dict[str, str] = {}
        unique_rows: list[dict] = []
        seen_pairs: set[tuple[str, str]] = set()
        duplicate_count = 0
        for row in all_rows:
            domain = str(row.get("domain_id", ""))
            signature = str(row.get("generation_signature_hash", ""))
            if not domain or not signature:
                raise ValueError("isolated campaign requires domain and signature provenance")
            prior_signature = domain_signatures.get(domain)
            if prior_signature is not None and prior_signature != signature:
                raise ValueError(f"conflicting signature for domain_id: {domain}")
            domain_signatures[domain] = signature
            identity = (domain, signature)
            if identity in seen_pairs:
                duplicate_count += 1
                continue
            seen_pairs.add(identity)
            unique_rows.append(row)
        return unique_rows, domain_signatures, duplicate_count

    def run_job(
        job_id: str,
        case_path: str,
        seeds: set[str],
        job_dir: Path,
        *,
        phase: str,
    ) -> tuple[Path, list[dict]]:
        case = load_case_mapping(case_path)
        case_name = str(case.get("name", Path(case_path).stem))
        expected_signature = compute_generation_signature_hash(case)
        cached = checkpoint["completed_jobs"].get(job_id)
        if cached and cached.get("status") == "completed":
            cached_path = Path(cached["csv_path"])
            cached_rows = _read_complete_case_csv(cached_path, cached["case_name"], seeds)
            if cached_rows is not None:
                return cached_path, cached_rows
            cached["status"] = "invalidated_incomplete_csv"
            persist()

        for prior_job_id, prior_job in checkpoint["completed_jobs"].items():
            if (
                prior_job_id == job_id
                or prior_job.get("phase") != phase
                or prior_job.get("generation_signature_hash") != expected_signature
                or not prior_job.get("csv_path")
            ):
                continue
            prior_path = Path(prior_job["csv_path"])
            prior_rows = _read_complete_case_csv(
                prior_path, prior_job["case_name"], seeds
            )
            if prior_rows is None:
                continue
            checkpoint["completed_jobs"][job_id] = {
                **prior_job,
                "status": "completed",
                "reused_from_job_id": prior_job_id,
            }
            checkpoint["status"] = "running"
            persist()
            return prior_path, prior_rows

        attempt = 1
        while (job_dir / f"attempt_{attempt:02d}").exists():
            attempt += 1
        attempt_dir = job_dir / f"attempt_{attempt:02d}"
        simulation_dir = attempt_dir / "simulation"
        config = build_iteration_config(
            [case_path],
            output_dir=simulation_dir,
            seed_start=min(int(value) for value in seeds),
            seed_stop=max(int(value) for value in seeds),
            backend=args.backend,
        )
        attempt_dir.mkdir(parents=True, exist_ok=True)
        config_path = attempt_dir / "config.yml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        try:
            subprocess.run(
                [sys.executable, "run_profile_mc.py", "--config", str(config_path)],
                cwd=REPO_ROOT,
                check=True,
            )
        except Exception as exc:
            checkpoint["completed_jobs"][job_id] = {
                "status": "failed",
                "case_path": case_path,
                "case_name": case_name,
                "phase": phase,
                "attempt_dir": str(attempt_dir),
                "error": f"{type(exc).__name__}: {exc}",
            }
            checkpoint["status"] = "interrupted"
            persist()
            raise
        csv_path = simulation_dir / "all_cases_borehole_rows.csv"
        rows = _read_complete_case_csv(csv_path, case_name, seeds)
        if rows is None:
            checkpoint["completed_jobs"][job_id] = {
                "status": "incomplete_output",
                "case_path": case_path,
                "case_name": case_name,
                "phase": phase,
                "csv_path": str(csv_path),
                "attempt_dir": str(attempt_dir),
            }
            checkpoint["status"] = "interrupted"
            persist()
            raise ValueError(f"runner output is incomplete or lacks provenance: {csv_path}")
        selected = [row for row in rows if row.get("case_name") == case_name]
        signatures = {str(row["generation_signature_hash"]) for row in selected}
        if len(signatures) != 1:
            raise ValueError(f"candidate produced multiple generation signatures: {case_name}")
        checkpoint["completed_jobs"][job_id] = {
            "status": "completed",
            "case_path": case_path,
            "case_name": case_name,
            "phase": phase,
            "csv_path": str(csv_path),
            "generation_signature_hash": next(iter(signatures)),
            "domain_ids": sorted({str(row["domain_id"]) for row in selected}),
            "seed_values": sorted({str(row["seed"]) for row in selected}),
            "attempt_dir": str(attempt_dir),
        }
        checkpoint["status"] = "running"
        persist()
        return csv_path, rows

    baseline_names = {
        str(load_case_mapping(path).get("name", Path(path).stem)): path
        for path in case_paths
    }
    rows, _, _ = cumulative_rows()
    rows_by_case = {}
    for row in rows:
        rows_by_case.setdefault(str(row.get("case_name", "")), set()).add(str(row.get("seed")))
    for case_name, case_path in baseline_names.items():
        if rows_by_case.get(case_name) == primary_seeds:
            continue
        job_id = "baseline-" + hashlib.sha256(case_path.encode("utf-8")).hexdigest()[:16]
        job_dir = workdir / "baseline" / job_id
        run_job(job_id, case_path, primary_seeds, job_dir, phase="baseline")

    attempted = set(checkpoint["attempted_plans"])
    stop_reason = "iteration_limit"
    start_iteration = int(checkpoint.get("next_iteration", 0))
    for iteration in range(start_iteration, args.iterations):
        checkpoint["current_iteration"] = iteration
        rows, domain_signatures, duplicate_count = cumulative_rows()
        audit = audit_borehole_records(rows, cutoffs=generate_qprime_cutoffs(intervals=10))
        coverage_audit = audit_borehole_records(rows, cutoffs=generate_qprime_cutoffs(intervals=20))
        profile_search = search_profile_boundaries(
            rows,
            cutoffs=generate_qprime_cutoffs(intervals=10),
            min_records=1,
            min_domains=1,
            stable_bins=1,
        )
        unobserved = [row for row in audit["bins"] if row.get("status") == "UNOBSERVED"]
        checkpoint["remaining_unobserved_bins"] = [int(row["bin_index"]) for row in unobserved]
        checkpoint["profile_cutoff_identified"] = profile_search["status"] == "identified"
        checkpoint["profile_search"] = profile_search
        if not unobserved:
            stop_reason = "coverage_complete"
            checkpoint["status"] = "coverage_complete"
            break

        candidate_dir = workdir / f"iteration_{iteration:04d}" / "candidates"
        pending_queue = checkpoint.setdefault("pending_response_candidates", [])
        legacy_pending = checkpoint.pop("pending_response_candidate", None)
        if legacy_pending is not None and not any(
            item.get("entry_id") == legacy_pending.get("entry_id")
            for item in pending_queue
        ):
            pending_queue.append(legacy_pending)
        prefer_response = bool(pending_queue) and checkpoint.get(
            "last_selection_source"
        ) != "response"
        selected_candidate = pending_queue[0] if prefer_response else None
        selected_plan = None
        plan_key = None
        selection_source = "response" if selected_candidate is not None else "catalog"
        if selected_candidate is not None:
            selected_plan = {
                "strategy_id": selected_candidate["strategy_id"],
                "feature_family": selected_candidate["feature_family"],
                "bin_index": selected_candidate["target_bin"],
                "parent_signature": selected_candidate["parent_signature"],
            }
        else:
            all_plan_count = max(
                1,
                len(unobserved) * sum(len(value) for value in strategy_catalog.values()),
            )
            plans = plan_gap_candidates(
                audit,
                strategy_catalog=strategy_catalog,
                max_candidates=all_plan_count,
                gap_class_priority=strategy_catalog_settings.get("gap_class_priority"),
            )
            for plan in plans:
                candidate_plan_key = "|".join((
                    str(plan["strategy_id"]),
                    str(plan["bin_index"]),
                    str(plan["parent_signature"]),
                ))
                if candidate_plan_key in attempted:
                    continue
                try:
                    materialized = _materialize_catalog_plan(
                        plan,
                        iteration=iteration,
                        candidate_dir=candidate_dir,
                        screening_seed=args.seed_start,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    record = {
                        "round_id": iteration,
                        "round_type": "catalog_candidate_review",
                        "strategy_id": plan.get("strategy_id"),
                        "target_bin": plan.get("bin_index"),
                        "status": "awaiting_review",
                        "stop_reason": f"candidate_not_materializable: {exc}",
                        "remaining_unobserved_bins": checkpoint["remaining_unobserved_bins"],
                    }
                    checkpoint["ledger_records"].append(record)
                    checkpoint["status"] = "awaiting_review"
                    stop_reason = "candidate_not_materializable"
                    persist()
                    selected_plan = None
                    break
                if materialized["generation_signature_hash"] in set(domain_signatures.values()):
                    attempted.add(candidate_plan_key)
                    checkpoint["attempted_plans"] = sorted(attempted)
                    record = {
                        "round_id": iteration,
                        "round_type": "signature_screening",
                        "strategy_id": plan["strategy_id"],
                        "feature_family": plan["feature_family"],
                        "target_bin": plan["bin_index"],
                        "parent_signature_hash": plan["parent_signature"],
                        "generation_signature_hash": materialized["generation_signature_hash"],
                        "status": "deduplicated_signature",
                        "duplicate_domain_count": duplicate_count,
                        "remaining_unobserved_bins": checkpoint["remaining_unobserved_bins"],
                        "stop_reason": "candidate signature already exists in cumulative campaign",
                    }
                    checkpoint["ledger_records"].append(record)
                    persist()
                    continue
                selected_plan = plan
                selected_candidate = materialized
                plan_key = candidate_plan_key
                break

        if selected_plan is None and pending_queue:
            selected_candidate = pending_queue[0]
            selected_plan = {
                "strategy_id": selected_candidate["strategy_id"],
                "feature_family": selected_candidate["feature_family"],
                "bin_index": selected_candidate["target_bin"],
                "parent_signature": selected_candidate["parent_signature"],
            }
            selection_source = "response"

        if selected_plan is None:
            if checkpoint["status"] == "awaiting_review":
                break
            stop_reason = "no_unattempted_approved_candidates"
            checkpoint["status"] = "awaiting_review"
            checkpoint["stop_reason"] = stop_reason
            persist()
            break

        candidate = selected_candidate
        assert candidate is not None
        candidate_csv, _ = run_job(
            candidate["entry_id"],
            candidate["case_path"],
            primary_seeds,
            workdir / f"iteration_{iteration:04d}" / "jobs" / candidate["entry_id"],
            phase="signature_screening",
        )
        candidate_job = checkpoint["completed_jobs"][candidate["entry_id"]]
        if candidate_job["generation_signature_hash"] != candidate["generation_signature_hash"]:
            candidate_job["status"] = "invalid_signature_provenance"
            checkpoint["status"] = "interrupted"
            persist()
            raise ValueError(
                "runner generation signature does not match materialized candidate: "
                f"{candidate['entry_id']}"
            )
            candidate["case_path"] = candidate_job["case_path"]
            candidate["case_name"] = candidate_job["case_name"]
        if plan_key is not None:
            attempted.add(plan_key)
            checkpoint["attempted_plans"] = sorted(attempted)
        rows_after, after_domains, duplicate_count_after = cumulative_rows()
        after_audit = audit_borehole_records(rows_after, cutoffs=generate_qprime_cutoffs(intervals=10))
        after_coverage = audit_borehole_records(rows_after, cutoffs=generate_qprime_cutoffs(intervals=20))
        after_profile = search_profile_boundaries(
            rows_after,
            cutoffs=generate_qprime_cutoffs(intervals=10),
            min_records=1,
            min_domains=1,
            stable_bins=1,
        )
        signature_overlap = build_signature_overlap_report(
            rows_after, cutoffs=generate_qprime_cutoffs(intervals=20)
        )
        before_unobserved = {int(row["bin_index"]) for row in audit["bins"] if row.get("status") == "UNOBSERVED"}
        after_unobserved = {int(row["bin_index"]) for row in after_audit["bins"] if row.get("status") == "UNOBSERVED"}
        changed = candidate.get("changed_feature") or {}
        delta_x = None
        delta_x_normalized = None
        if changed:
            delta_x = float(changed["target_value"]) - float(changed["parent_value"])
            lower, upper = changed["bounds"]
            delta_x_normalized = delta_x / (float(upper) - float(lower))
        job_record = checkpoint["completed_jobs"][candidate["entry_id"]]
        measured_signatures = {
            str(row["generation_signature_hash"])
            for row in rows_after if str(row.get("case_name")) == candidate["case_name"]
        }
        record = {
            "round_id": iteration,
            "run_id": f"catalog-{iteration:04d}-{candidate['entry_id']}",
            "round_type": "signature_screening",
            "parent_round_id": max(0, iteration - 1) if iteration else None,
            "parent_case_path": candidate["parent_case_path"],
            "parent_signature_hash": candidate["parent_signature"],
            "strategy_id": candidate["strategy_id"],
            "feature_family": candidate["feature_family"],
            "changed_feature": changed,
            "orientation_validation": candidate.get("orientation_validation"),
            "delta_x": delta_x,
            "delta_x_normalized": delta_x_normalized,
            "delta_coverage": {
                "newly_observed_bins": sorted(before_unobserved - after_unobserved),
                "remaining_unobserved_bins": sorted(after_unobserved),
                "unobserved_bin_delta": len(after_unobserved) - len(before_unobserved),
            },
            "delta_C": {
                "newly_observed_bins": sorted(before_unobserved - after_unobserved),
                "unobserved_bin_delta": len(after_unobserved) - len(before_unobserved),
            },
            "generation_signature_hash": candidate["generation_signature_hash"],
            "measured_generation_signature_hashes": sorted(measured_signatures),
            "domain_ids": job_record["domain_ids"],
            "source_csv": str(candidate_csv),
            "cumulative_domain_count": len(after_domains),
            "duplicate_domain_count": duplicate_count_after,
            "signature_overlap_only_count": signature_overlap["n_overlap_only_signatures"],
            "signature_unique_coverage_count": signature_overlap["n_unique_coverage_signatures"],
            "coverage_complete": not after_unobserved,
            "profile_cutoff_identified": after_profile["status"] == "identified",
            "profile_search_status": after_profile["status"],
            "coverage_audit": after_audit,
            "coverage_audit_20": after_coverage,
            "status": "completed",
            "stop_reason": None,
        }
        if selection_source == "response":
            checkpoint["pending_response_candidates"] = [
                item for item in pending_queue
                if item.get("entry_id") != candidate["entry_id"]
            ]
        response_update = candidate.get("response_update")
        if response_update and after_unobserved:
            feature_bounds = {
                name: (float(bounds[0]), float(bounds[1]))
                for name, bounds in response_update["feature_bounds"].items()
            }
            try:
                measured_probe = observed_euler_probe(
                    rows_after,
                    parent_path=candidate["parent_case_path"],
                    probe_path=candidate["case_path"],
                    feature_bounds=feature_bounds,
                    target_bins=[int(index) for index in response_update["target_bins"]],
                    cutoffs=after_audit["cutoffs"],
                )
                physical_assessment = assess_physical_probe(measured_probe)
                record["paired_probe"] = measured_probe
                record["physical_assessment"] = physical_assessment
                record["paired_delta_C"] = measured_probe["coverage_delta"]
                if physical_assessment["status"] == "observed_local_response":
                    euler_candidate = build_euler_update_candidate_from_probes(
                        measured_probe["source_case_path"],
                        round_id=iteration + 1,
                        target_region=candidate["target_region"],
                        screening_seed=args.seed_start,
                        feature_bounds=feature_bounds,
                        probes=[measured_probe],
                        step_size=float(response_update["step_size"]),
                        generator_version=response_update.get(
                            "generator_version", "qsimex-generation-v1"
                        ),
                    )
                    parent_signature = compute_generation_signature_hash(
                        load_case_mapping(measured_probe["source_case_path"])
                    )
                    if euler_candidate["generation_signature_hash"] == parent_signature:
                        record["response_update_status"] = "awaiting_review"
                        record["response_update_stop_reason"] = (
                            "bounded paired response produced no signature change"
                        )
                    elif euler_candidate["generation_signature_hash"] in set(
                        after_domains.values()
                    ):
                        record["response_update_status"] = "deduplicated_signature"
                        record["response_update_stop_reason"] = (
                            "paired response candidate already exists in cumulative campaign"
                        )
                    else:
                        next_candidate = _materialize_response_update(
                            euler_candidate,
                            candidate_dir=(
                                workdir
                                / f"iteration_{iteration + 1:04d}"
                                / "candidates"
                            ),
                            strategy_id=candidate["strategy_id"],
                            feature_family=candidate["feature_family"],
                            target_bin=candidate["target_bin"],
                            response_update=response_update,
                            measured_probe=measured_probe,
                        )
                        checkpoint["pending_response_candidates"].append(next_candidate)
                        record["response_update_status"] = "next_candidate_planned"
                        record["next_candidate_id"] = next_candidate["entry_id"]
                        record["next_candidate_path"] = next_candidate["case_path"]
                        record["next_parent_signature_hash"] = next_candidate[
                            "parent_signature"
                        ]
                else:
                    record["response_update_status"] = "awaiting_review"
                    record["response_update_stop_reason"] = physical_assessment["status"]
            except (KeyError, TypeError, ValueError) as exc:
                record["response_update_status"] = "awaiting_review"
                record["response_update_stop_reason"] = f"paired_response_rejected: {exc}"
        checkpoint["ledger_records"].append(record)
        checkpoint["last_selection_source"] = selection_source
        checkpoint["next_iteration"] = iteration + 1
        checkpoint["last_candidate_csv"] = str(candidate_csv)
        checkpoint["remaining_unobserved_bins"] = sorted(after_unobserved)
        checkpoint["profile_cutoff_identified"] = after_profile["status"] == "identified"
        checkpoint["status"] = "running"
        iteration_dir = workdir / f"iteration_{iteration:04d}"
        _write_json_atomic(iteration_dir / "coverage_audit.json", after_audit)
        _write_json_atomic(iteration_dir / "coverage_audit_20.json", after_coverage)
        _write_json_atomic(iteration_dir / "profile_boundary_search.json", after_profile)
        _write_json_atomic(iteration_dir / "signature_overlap_20.json", signature_overlap)
        persist()
        if not after_unobserved:
            stop_reason = "coverage_complete"
            checkpoint["status"] = "coverage_complete"
            break

    if checkpoint["status"] not in {"coverage_complete", "awaiting_review"}:
        checkpoint["status"] = "iteration_limit"
        stop_reason = "iteration_limit"
    checkpoint["stop_reason"] = stop_reason
    screening_status = checkpoint["status"]
    if repeatability_seeds:
        screening_rows, _, _ = cumulative_rows()
        reference_qprime: dict[str, list[float]] = {}
        for row in screening_rows:
            reference_qprime.setdefault(str(row["generation_signature_hash"]), []).append(
                float(row["Qp_bh_mean"])
            )
        signature_cases: dict[str, str] = {}
        for path in case_paths:
            signature_cases.setdefault(
                compute_generation_signature_hash(load_case_mapping(path)), path
            )
        for job in checkpoint["completed_jobs"].values():
            if job.get("status") == "completed" and job.get("phase") == "signature_screening":
                signature_cases.setdefault(job["generation_signature_hash"], job["case_path"])
        completed_repeatability = {
            record["run_id"] for record in checkpoint["ledger_records"]
            if record.get("round_type") == "repeatability_E" and record.get("status") == "completed"
        }
        for signature, case_path in sorted(signature_cases.items()):
            for seed in repeatability_seeds:
                run_id = f"repeatability-{signature[:12]}-{seed}"
                if run_id in completed_repeatability:
                    continue
                csv_path, repeat_rows = run_job(
                    run_id,
                    case_path,
                    {str(seed)},
                    workdir / "repeatability_E" / run_id,
                    phase="repeatability_E",
                )
                measured = {
                    str(row["generation_signature_hash"])
                    for row in repeat_rows
                    if str(row.get("seed")) == str(seed)
                }
                if measured != {signature}:
                    checkpoint["completed_jobs"][run_id]["status"] = "invalid_signature_provenance"
                    checkpoint["status"] = "interrupted"
                    persist()
                    raise ValueError(f"E-phase changed signature for {run_id}")
                repeated_values = [
                    float(row["Qp_bh_mean"])
                    for row in repeat_rows if str(row.get("seed")) == str(seed)
                ]
                reference_values = reference_qprime.get(signature, [])
                repeated_mean = sum(repeated_values) / len(repeated_values)
                reference_mean = (
                    sum(reference_values) / len(reference_values)
                    if reference_values else None
                )
                checkpoint["ledger_records"].append({
                    "round_id": int(checkpoint.get("next_iteration", 0)),
                    "run_id": run_id,
                    "round_type": "repeatability_E",
                    "feature_family": "E",
                    "case_path": case_path,
                    "generation_signature_hash": signature,
                    "seed": seed,
                    "source_csv": str(csv_path),
                    "reference_qprime_mean": reference_mean,
                    "repeatability_qprime_mean": repeated_mean,
                    "delta_qprime_mean": (
                        repeated_mean - reference_mean
                        if reference_mean is not None else None
                    ),
                    "coverage_contribution": "excluded_independent_repeatability",
                    "status": "completed",
                    "stop_reason": None,
                })
                checkpoint["status"] = screening_status
                checkpoint["repeatability_status"] = "running"
                persist()
        checkpoint["repeatability_status"] = "completed"
        checkpoint["status"] = screening_status
    else:
        checkpoint["repeatability_status"] = "not_requested"
    manifest["coverage_complete"] = checkpoint["status"] == "coverage_complete"
    manifest["cutoff_identified"] = bool(checkpoint.get("profile_cutoff_identified"))
    manifest["remaining_unobserved_bins"] = checkpoint.get("remaining_unobserved_bins", [])
    manifest["resume_command"] = f"python validation/run_campaign.py --workdir {workdir} --resume ..."
    persist()
    return manifest


def build_iteration_config(
    case_paths: list[str],
    *,
    output_dir: Path,
    seed_start: int,
    seed_stop: int,
    backend: str,
) -> dict:
    return {
        "profile_mc_exploration": {
            "case_paths": case_paths,
            "seed_range": {"start": seed_start, "stop": seed_stop, "step": 1},
            "face_positions": [10, 20, 30],
            "borehole_window": 3,
            "backend": backend,
            "batch_size": 100,
            "correction_mode": "pure",
            "output_dir": str(output_dir),
            "save_each_case": True,
            "save_combined": True,
            "checkpoint_on_seed": True,
            "verbose": True,
        }
    }


def observed_euler_probe(
    records: list[dict],
    *,
    parent_path: str,
    probe_path: str,
    feature_bounds: dict[str, tuple[float, float]],
    target_bins: list[int],
    cutoffs: list[float],
) -> dict:
    """Measure a reviewed one-feature probe from paired, same-seed simulations."""
    parent = load_case_mapping(parent_path)
    probe = load_case_mapping(probe_path)
    parent_name = parent.get("name", Path(parent_path).stem)
    probe_name = probe.get("name", Path(probe_path).stem)
    if parent_name == probe_name:
        raise ValueError("parent and probe case names must differ")
    before = extract_normalized_features(parent, feature_bounds)
    after = extract_normalized_features(probe, feature_bounds)
    feature_delta = {
        name: after[name] - value for name, value in before.items()
        if after[name] != value
    }
    if len(feature_delta) != 1 or compute_generation_signature_hash(
        apply_normalized_features(probe, before, feature_bounds)
    ) != compute_generation_signature_hash(parent):
        raise ValueError("probe must change exactly one reviewed generation feature")
    if not target_bins or any(index < 0 or index >= len(cutoffs) - 1 for index in target_bins):
        raise ValueError("target_bins must contain valid indices on the update grid")

    observations = {}
    for name in (parent_name, probe_name):
        selected = [row for row in records if row.get("case_name") == name]
        seeds = {str(row["seed"]) for row in selected if row.get("seed") not in (None, "")}
        hashes = {row.get("generation_signature_hash") for row in selected}
        if not seeds or len(hashes) != 1 or None in hashes or "" in hashes:
            raise ValueError(f"missing or ambiguous simulation provenance for {name}")
        observations[name] = (selected, seeds, hashes.pop())
    if observations[parent_name][1] != observations[probe_name][1]:
        raise ValueError("parent and probe must share the same seed set")
    if observations[parent_name][2] == observations[probe_name][2]:
        raise ValueError("probe must generate a distinct signature")

    physical_response = {}
    seed_responses = {seed: {} for seed in observations[parent_name][1]}
    for field in (
        "Qp_bh_mean", "RQD_bh_mean", "borehole_n_intersections_sum",
        "borehole_plane_angle_mean_deg",
    ):
        means = {}
        for name, (selected, seeds, _) in observations.items():
            per_seed = []
            for seed in seeds:
                values = [
                    float(row[field]) for row in selected
                    if str(row["seed"]) == seed and row.get(field) not in (None, "", "nan")
                ]
                if values:
                    per_seed.append(sum(values) / len(values))
            if len(per_seed) == len(seeds):
                means[name] = sum(per_seed) / len(per_seed)
        if len(means) == 2:
            physical_response[field] = means[probe_name] - means[parent_name]
            for seed in seed_responses:
                per_case = {}
                for name, (selected, _, _) in observations.items():
                    values = [
                        float(row[field]) for row in selected
                        if str(row["seed"]) == seed and row.get(field) not in (None, "", "nan")
                    ]
                    per_case[name] = sum(values) / len(values)
                seed_responses[seed][field] = per_case[probe_name] - per_case[parent_name]
    if any("dip" in name or "kappa" in name for name in feature_delta):
        if "borehole_plane_angle_mean_deg" not in physical_response:
            raise ValueError("orientation probe requires measured borehole-plane angle")
        if physical_response["borehole_plane_angle_mean_deg"] == 0.0:
            raise ValueError("orientation probe did not change measured borehole-plane angle")

    frequencies = {}
    for name, (selected, seeds, _) in observations.items():
        per_seed = []
        for seed in sorted(seeds):
            audit = audit_qprime_coverage(
                [row for row in selected if str(row["seed"]) == seed],
                cutoffs=cutoffs,
            )
            per_seed.append([float(row["n_records"] > 0) for row in audit["bins"]])
        frequencies[name] = [
            sum(bin_values) / len(seeds) for bin_values in zip(*per_seed)
        ]
    distances = {}
    for name, (selected, seeds, _) in observations.items():
        per_seed_distances = []
        for seed in seeds:
            audit = audit_qprime_coverage(
                [row for row in selected if str(row["seed"]) == seed], cutoffs=cutoffs
            )
            observed_bins = [row["bin_index"] for row in audit["bins"] if row["n_records"]]
            if not observed_bins:
                raise ValueError(f"no in-range Q' bins for {name} at seed {seed}")
            per_seed_distances.append(sum(
                min(abs(index - target) for index in observed_bins)
                for target in target_bins
            ) / len(target_bins))
        distances[name] = sum(per_seed_distances) / len(seeds)
    nearer, farther = sorted((parent_name, probe_name), key=lambda name: distances[name])
    near_bins = frequencies[nearer]
    far_bins = frequencies[farther]
    feature_delta = {
        name: (after[name] - before[name]) * (1 if nearer == probe_name else -1)
        for name in feature_delta
    }
    coverage_delta = {
        f"bin_{index}": near_bins[index] - observed
        for index, observed in enumerate(far_bins)
    }
    coverage_delta["proximity_gain"] = distances[farther] - distances[nearer]
    residual = {"proximity_gain": distances[nearer]}
    return {
        "feature_delta": feature_delta,
        "coverage_delta": coverage_delta,
        "coverage_residual": residual,
        "physical_response": physical_response,
        "seed_physical_responses": seed_responses,
        "source_case_path": probe_path if nearer == probe_name else parent_path,
        "nearest_observed_bin": min(
            (index for index, value in enumerate(near_bins) if value > 0),
            key=lambda index: min(abs(index - target) for target in target_bins),
        ),
        "distance_to_target": distances[nearer],
        "parent_case": parent_name,
        "probe_case": probe_name,
        "seed_values": sorted(observations[parent_name][1]),
        "parent_signature_hash": observations[parent_name][2],
        "probe_signature_hash": observations[probe_name][2],
    }


def assess_physical_probe(probe: dict) -> dict:
    """Use measured responses to qualify one local update, not to set cutoffs."""
    feature, delta = next(iter(probe["feature_delta"].items()))
    response = probe["physical_response"]
    fields = ("Qp_bh_mean", "RQD_bh_mean", "borehole_n_intersections_sum")
    missing = [field for field in fields if field not in response]
    if missing:
        return {"status": "needs_measurement", "missing_metrics": missing}
    if (feature.endswith(".P32") or feature.endswith(".mean_spacing")) and response["borehole_n_intersections_sum"] == 0.0:
        return {"status": "no_intersection_response", "feature": feature}
    if response["Qp_bh_mean"] == 0.0 and response["RQD_bh_mean"] == 0.0:
        return {"status": "no_quality_response", "feature": feature}
    orientation = any(word in feature for word in ("dip", "kappa"))
    for field in ("Qp_bh_mean", "borehole_plane_angle_mean_deg" if orientation else "borehole_n_intersections_sum"):
        changes = [
            entry[field] for entry in probe.get("seed_physical_responses", {}).values()
            if field in entry
        ]
        if len(changes) > 1 and min(changes) < 0.0 < max(changes):
            return {"status": "needs_repeatability", "feature": feature, "conflicting_metric": field}
    if orientation:
        angle_change = response.get("borehole_plane_angle_mean_deg")
        if angle_change is None or angle_change == 0.0:
            return {"status": "needs_measured_angle_response", "feature": feature}
    sensitivities = {field: response[field] / delta for field in fields}
    angle_change = response.get("borehole_plane_angle_mean_deg")
    if orientation and angle_change is not None and angle_change != 0.0:
        sensitivities["Qp_bh_mean_per_plane_angle_deg"] = response["Qp_bh_mean"] / angle_change
        sensitivities["intersections_per_plane_angle_deg"] = response["borehole_n_intersections_sum"] / angle_change
    return {
        "status": "observed_local_response",
        "feature": feature,
        "delta_normalized_feature": delta,
        "sensitivity_per_normalized_feature": sensitivities,
    }


def build_density_reachability_probe(
    parent_path: str,
    probe_path: str,
    *,
    feature_bounds: dict[str, tuple[float, float]],
    round_id: int,
    target_region: str,
    screening_seed: int,
    generator_version: str,
) -> dict | None:
    """Extend a reviewed density probe without inventing a coverage gradient."""
    parent = load_case_mapping(parent_path)
    probe = load_case_mapping(probe_path)
    before = extract_normalized_features(parent, feature_bounds)
    after = extract_normalized_features(probe, feature_bounds)
    changes = {
        name: after[name] - value for name, value in before.items()
        if after[name] != value
    }
    if len(changes) != 1:
        raise ValueError("density reachability requires a one-feature probe")
    feature, feature_delta = next(iter(changes.items()))
    if not (feature.endswith(".P32") or feature.endswith(".mean_spacing")):
        raise ValueError("density reachability requires P32 or mean_spacing")
    if compute_generation_signature_hash(
        apply_normalized_features(parent, after, feature_bounds)
    ) != compute_generation_signature_hash(probe):
        raise ValueError("density reachability cannot change other generation features")

    origin = probe.get("tags", {}).get("density_probe_origin_normalized", before[feature])
    next_value = min(1.0, max(0.0, after[feature] + (after[feature] - origin)))
    if next_value == after[feature]:
        return None
    candidate_case = apply_normalized_features(
        probe, {feature: next_value}, feature_bounds
    )
    signature_hash = compute_generation_signature_hash(candidate_case)
    candidate_id = f"r{round_id:03d}-density-probe-{signature_hash[:12]}"
    candidate_case["name"] = f"{probe.get('name', Path(probe_path).stem)}__{candidate_id}"
    candidate_case["seed"] = int(screening_seed)
    domain_id = compute_domain_id(
        candidate_case, seed=screening_seed, generator_version=generator_version
    )
    candidate_case.setdefault("tags", {}).update({
        "coverage_round": round_id,
        "candidate_id": candidate_id,
        "coverage_target": target_region,
        "parent_case": probe.get("name", Path(probe_path).stem),
        "update_method": "density_reachability_probe",
        "density_probe_origin_normalized": origin,
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "generator_version": generator_version,
    })
    return {
        "candidate_id": candidate_id,
        "parent_case_path": probe_path,
        "comparison_case_path": parent_path,
        "target_region": target_region,
        "generation_signature_hash": signature_hash,
        "domain_id": domain_id,
        "feature_delta": {feature: next_value - after[feature]},
        "normalized_feature_before": after[feature],
        "normalized_feature_after": next_value,
        "density_probe_origin_normalized": origin,
        "reason": "extend observed density probe within reviewed exploration bounds",
        "case": candidate_case,
    }


def nearest_observed_signatures(audit: dict, target_bins: list[int]) -> dict:
    """Find the closest actually observed signatures on the log-bin grid."""
    observed = [row for row in audit["bins"] if row["signature_hashes"]]
    if not observed:
        return {"bin_indices": [], "signature_hashes": []}
    distance = min(
        abs(row["bin_index"] - target) for row in observed for target in target_bins
    )
    nearest = [
        row for row in observed
        if min(abs(row["bin_index"] - target) for target in target_bins) == distance
    ]
    return {
        "bin_indices": [row["bin_index"] for row in nearest],
        "signature_hashes": sorted({
            signature for row in nearest for signature in row["signature_hashes"]
        }),
    }


def next_unobserved_profile_target(
    audit: dict,
    target_bins: list[int],
) -> tuple[list[int], list[int]]:
    """Keep the reviewed target until reached, then advance through primary-grid gaps."""
    bins = audit.get("bins", [])
    all_bins = {int(row["bin_index"]) for row in bins}
    observed_bins = {
        int(row["bin_index"])
        for row in bins
        if row.get("status") == "observed" or int(row.get("n_records", 0) or 0) > 0
    }
    missing_bins = sorted(all_bins - observed_bins)
    if not missing_bins:
        return [], []

    pending_targets = sorted(set(target_bins) & set(missing_bins))
    if pending_targets:
        return pending_targets, missing_bins
    if not observed_bins:
        return [missing_bins[0]], missing_bins

    nearest_gap = min(
        missing_bins,
        key=lambda index: (
            min(abs(index - observed) for observed in observed_bins),
            index,
        ),
    )
    return [nearest_gap], missing_bins


def bound_limited_features(candidate: dict) -> list[str]:
    """Return features whose requested Euler movement was clipped to a bound."""
    before = candidate.get("normalized_features_before", {})
    after = candidate.get("normalized_features_after", {})
    direction = candidate.get("direction", {})
    return sorted(
        name
        for name, movement in direction.items()
        if name in before
        and name in after
        and abs(float(movement)) > 0.0
        and abs(float(after[name]) - float(before[name])) <= 1e-12
    )


def should_extend_density_reachability(
    probe: dict,
    physical_assessment: dict,
    response: float,
    probe_path: str,
) -> bool:
    """Continue approved density exploration without treating mixed Q' as a slope."""
    feature = next(iter(probe["feature_delta"]))
    if not (feature.endswith(".P32") or feature.endswith(".mean_spacing")):
        return False
    status = physical_assessment.get("status")
    if status == "needs_measurement":
        return False
    repeatability_with_coverage_progress = (
        status == "needs_repeatability"
        and physical_assessment.get("conflicting_metric") == "Qp_bh_mean"
        and probe["coverage_delta"].get("proximity_gain", 0.0) >= 0.0
    )
    has_reachability_signal = (
        response == 0.0
        or status in {"no_intersection_response", "no_quality_response"}
        or repeatability_with_coverage_progress
    )
    if not has_reachability_signal:
        return False
    return (
        response == 0.0
        or probe.get("source_case_path") == probe_path
        or repeatability_with_coverage_progress
    )


def stabilize_candidate_case_name(candidate: dict, parent_path: str) -> str:
    """Use the root case name so generated names do not grow each iteration."""
    parent = load_case_mapping(parent_path)
    parent_name = str(parent.get("name", Path(parent_path).stem))
    root_name = parent_name.split("__r", maxsplit=1)[0]
    stable_name = f"{root_name}__{candidate['candidate_id']}"
    candidate["case"]["name"] = stable_name
    return stable_name


def run_campaign(args: argparse.Namespace) -> dict:
    if args.seed_stop < args.seed_start:
        raise ValueError("seed-stop must be >= seed-start")
    if args.iterations <= 0:
        raise ValueError("iterations must be positive")
    case_paths = [str(Path(path).resolve()) for path in args.case]
    for path in case_paths:
        if not Path(path).is_file():
            raise FileNotFoundError(path)

    euler_spec = None
    strategy_catalog = None
    strategy_catalog_settings = {}
    strategy_catalog_path = getattr(args, "strategy_catalog", None)
    if strategy_catalog_path:
        if args.euler_spec:
            raise ValueError("choose either --euler-spec or --strategy-catalog for this campaign")
        strategy_catalog_path = str(Path(strategy_catalog_path).resolve())
        strategy_catalog, strategy_catalog_settings = load_main_strategy_catalog(
            strategy_catalog_path
        )
        strategy_parent_paths = [
            strategy["parent_case_path"]
            for strategies in strategy_catalog.values()
            for strategy in strategies
        ]
        case_paths = list(dict.fromkeys(case_paths + strategy_parent_paths))
    max_catalog_candidates = getattr(args, "max_candidates_per_iteration", None)
    if max_catalog_candidates is None and strategy_catalog is not None:
        max_catalog_candidates = strategy_catalog_settings.get(
            "max_candidates_per_iteration"
        )
    if max_catalog_candidates is not None and max_catalog_candidates <= 0:
        raise ValueError("max candidates per iteration must be positive")
    initial_csv = getattr(args, "initial_csv", None)
    if initial_csv:
        initial_csv = str(Path(initial_csv).resolve())
        if not Path(initial_csv).is_file():
            raise FileNotFoundError(initial_csv)
    resume_requested = bool(getattr(args, "resume", False))
    if resume_requested and (strategy_catalog is None or args.dry_run):
        raise ValueError("--resume is only available for non-dry-run strategy-catalog campaigns")
    if resume_requested and getattr(args, "force_overwrite", False):
        raise ValueError("--resume and --force-overwrite cannot be used together")
    if strategy_catalog is not None and args.dry_run:
        if initial_csv is None:
            raise ValueError(
                "--strategy-catalog plan-only mode requires --initial-csv for its coverage audit"
            )
    if args.euler_spec:
        euler_spec = json.loads(Path(args.euler_spec).read_text(encoding="utf-8"))
        if not euler_spec.get("case_path"):
            raise ValueError("euler spec requires case_path")
        euler_spec["case_path"] = str(Path(euler_spec["case_path"]).resolve())
        if euler_spec.get("probe_case_path"):
            euler_spec["probe_case_path"] = str(Path(euler_spec["probe_case_path"]).resolve())
            if not euler_spec.get("target_bins"):
                raise ValueError("observed Euler spec requires target_bins")
            if not {euler_spec["case_path"], euler_spec["probe_case_path"]}.issubset(case_paths):
                raise ValueError("parent and probe cases must run in iteration 0")
        if not args.dry_run and euler_spec.get("approval_status") != "approved_for_screening":
            raise ValueError("actual Euler campaign requires approved_for_screening spec")

    workdir = Path(args.workdir).resolve()
    archived_workdir = None
    existing_manifest = None
    if resume_requested:
        if not workdir.is_dir():
            raise FileNotFoundError(f"campaign workdir does not exist: {workdir}")
        manifest_path = workdir / "campaign_manifest.json"
        checkpoint_path = workdir / "campaign_checkpoint.json"
        if not manifest_path.is_file() or not checkpoint_path.is_file():
            raise FileNotFoundError("resume requires campaign_manifest.json and campaign_checkpoint.json")
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing_manifest.get("campaign_type") != "isolated_validation":
            raise ValueError("resume target is not an isolated validation campaign")
        if existing_manifest.get("seed_range") != [args.seed_start, args.seed_stop]:
            raise ValueError("resume seed range must match the checkpointed campaign")
        if existing_manifest.get("case_paths") != case_paths:
            raise ValueError("resume case paths must match the checkpointed campaign")
        if existing_manifest.get("strategy_catalog") != strategy_catalog_path:
            raise ValueError("resume strategy catalog path must match the checkpointed campaign")
    elif workdir.exists():
        if not workdir.is_dir() or workdir.is_symlink():
            raise FileExistsError(f"campaign workdir is not a real directory: {workdir}")
        if any(workdir.iterdir()):
            if not getattr(args, "force_overwrite", False):
                raise FileExistsError(
                    f"campaign workdir is not empty at {workdir}; choose a new workdir "
                    "or pass --force-overwrite to archive it"
                )
            existing_manifest_path = workdir / "campaign_manifest.json"
            try:
                existing_manifest = json.loads(
                    existing_manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise FileExistsError(
                    "--force-overwrite only archives a workdir with a valid "
                    "isolated campaign manifest"
                ) from exc
            if existing_manifest.get("campaign_type") != "isolated_validation":
                raise FileExistsError(
                    "--force-overwrite only archives an isolated validation campaign"
                )
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            archived_workdir = workdir.with_name(
                f"{workdir.name}.backup-{timestamp}"
            )
            suffix = 1
            while archived_workdir.exists():
                archived_workdir = workdir.with_name(
                    f"{workdir.name}.backup-{timestamp}-{suffix:02d}"
                )
                suffix += 1
            workdir.rename(archived_workdir)
            existing_manifest = None
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = existing_manifest or {
        "campaign_type": "isolated_validation",
        "existing_results_used": False,
        "profile_intervals": 10,
        "coverage_intervals": 20,
        "case_paths": case_paths,
        "seed_range": [args.seed_start, args.seed_stop],
        "iterations_requested": args.iterations,
        "stop_on_identified": bool(getattr(args, "stop_on_identified", False)),
        "backend": args.backend,
        "status": "dry_run" if args.dry_run else "planned",
        "euler_spec": args.euler_spec,
        "strategy_catalog": strategy_catalog_path,
        "max_candidates_per_iteration": max_catalog_candidates,
        "initial_csv": initial_csv,
        "initial_results_reused": bool(initial_csv),
        "previous_workdir_backup": (
            str(archived_workdir) if archived_workdir is not None else None
        ),
    }
    manifest["iterations_requested"] = args.iterations
    manifest["status"] = "resuming" if resume_requested else (
        "dry_run" if args.dry_run else "planned"
    )
    (workdir / "campaign_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if strategy_catalog is not None and not args.dry_run:
        return run_reviewed_strategy_campaign(
            args,
            workdir=workdir,
            manifest=manifest,
            case_paths=case_paths,
            initial_csv=initial_csv,
            strategy_catalog=strategy_catalog,
            strategy_catalog_settings=strategy_catalog_settings,
            resume=resume_requested,
        )

    if args.dry_run:
        dry_run_iterations = 1 if strategy_catalog is not None else args.iterations
        for iteration in range(dry_run_iterations):
            iteration_dir = workdir / f"iteration_{iteration:03d}"
            iteration_dir.mkdir(parents=True, exist_ok=True)
            config = build_iteration_config(
                case_paths,
                output_dir=iteration_dir / "simulation",
                seed_start=args.seed_start,
                seed_stop=args.seed_stop,
                backend=args.backend,
            )
            (iteration_dir / "config.yml").write_text(
                yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
            )
        if strategy_catalog is not None:
            if initial_csv is None:
                raise ValueError("strategy catalog planning requires an initial CSV")
            source_records = load_csv_records(initial_csv)
            audit = audit_borehole_records(
                source_records,
                cutoffs=generate_qprime_cutoffs(intervals=10),
                source_csv=initial_csv,
            )
            audit["source_csvs"] = [initial_csv]
            plan_result = plan_reviewed_catalog_gaps(
                audit,
                strategy_catalog,
                max_candidates=max_catalog_candidates,
                gap_class_priority=strategy_catalog_settings.get("gap_class_priority"),
            )
            iteration_dir = workdir / "iteration_000"
            audit_path = iteration_dir / "coverage_audit.json"
            audit_path.write_text(
                json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            plan_path = iteration_dir / "strategy_candidate_plans.json"
            plan_payload = {
                "schema_version": 1,
                "status": plan_result["status"],
                "execution_started": False,
                "iteration": 0,
                "source_audit": str(audit_path),
                "source_csvs": [initial_csv],
                **plan_result,
            }
            plan_path.write_text(
                json.dumps(plan_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            manifest["status"] = "strategy_plan_review_required"
            manifest["strategy_plan_path"] = str(plan_path)
            manifest["strategy_plan_status"] = plan_result["status"]
            manifest["strategy_plan_candidate_count"] = len(
                plan_result["candidate_plans"]
            )
            (workdir / "campaign_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return manifest

    ledger_path = workdir / "ledger.jsonl"
    current_case_paths = case_paths
    before_audit = None
    previous_records = None
    previous_case_path = None
    campaign_rows = []
    domain_signatures = {}
    campaign_csv_paths = []
    campaign_records = []
    for iteration in range(args.iterations):
        iteration_dir = workdir / f"iteration_{iteration:03d}"
        simulation_dir = iteration_dir / "simulation"
        config = build_iteration_config(
            current_case_paths,
            output_dir=simulation_dir,
            seed_start=args.seed_start,
            seed_stop=args.seed_stop,
            backend=args.backend,
        )
        config_path = iteration_dir / "config.yml"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        csv_path = simulation_dir / "all_cases_borehole_rows.csv"
        if iteration == 0 and initial_csv:
            simulation_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(initial_csv, csv_path)
        else:
            subprocess.run(
                [sys.executable, "run_profile_mc.py", "--config", str(config_path)],
                cwd=REPO_ROOT,
                check=True,
            )
        csv_records = load_csv_records(str(csv_path))
        new_domain_ids = set()
        for row in csv_records:
            domain_id = row.get("domain_id")
            signature = row.get("generation_signature_hash")
            if not domain_id or not signature:
                raise ValueError("isolated campaign requires domain and signature provenance")
            if domain_id in domain_signatures and domain_signatures[domain_id] != signature:
                raise ValueError(f"conflicting signature for domain_id: {domain_id}")
            if domain_id not in domain_signatures:
                new_domain_ids.add(domain_id)
            domain_signatures[domain_id] = signature
        campaign_rows.extend(
            row for row in csv_records if row["domain_id"] in new_domain_ids
        )
        campaign_csv_paths.append(str(csv_path))
        audit = audit_borehole_records(
            campaign_rows, cutoffs=generate_qprime_cutoffs(intervals=10)
        )
        coverage_audit = audit_borehole_records(
            campaign_rows, cutoffs=generate_qprime_cutoffs(intervals=20)
        )
        signature_overlap = build_signature_overlap_report(
            campaign_rows, cutoffs=generate_qprime_cutoffs(intervals=20)
        )
        audit["source_csvs"] = list(campaign_csv_paths)
        coverage_audit["source_csvs"] = list(campaign_csv_paths)
        profile_search = search_profile_boundaries(
            campaign_rows,
            cutoffs=generate_qprime_cutoffs(intervals=10),
            min_records=1,
            min_domains=1,
            stable_bins=1,
        )
        audit_path = iteration_dir / "coverage_audit.json"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        (iteration_dir / "coverage_audit_20.json").write_text(
            json.dumps(coverage_audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        overlap_path = iteration_dir / "signature_overlap_20.json"
        overlap_path.write_text(
            json.dumps(signature_overlap, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        profile_path = iteration_dir / "profile_boundary_search.json"
        profile_path.write_text(
            json.dumps(profile_search, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        record = build_round_record(
            round_id=iteration,
            run_id=f"validation-{iteration:03d}",
            round_type="validation_screening",
            before_audit=before_audit,
            after_audit=audit,
            n_domains=len(domain_signatures),
            n_signatures=len(set(domain_signatures.values())),
            extra={
                "iteration_dir": str(iteration_dir),
                "provenance_status": audit["provenance_status"],
                "new_domain_count": len(new_domain_ids),
                "duplicate_domain_count": len({row["domain_id"] for row in csv_records}) - len(new_domain_ids),
                "coverage_20_unobserved_bins": sum(
                    row["status"] == "UNOBSERVED" for row in coverage_audit["bins"]
                ),
                "coverage_20_audit_path": str(iteration_dir / "coverage_audit_20.json"),
                "signature_overlap_20_path": str(overlap_path),
                "signature_overlap_only_count": signature_overlap[
                    "n_overlap_only_signatures"
                ],
                "signature_unique_coverage_count": signature_overlap[
                    "n_unique_coverage_signatures"
                ],
                "profile_search_status": profile_search["status"],
                "profile_search_reason": profile_search["reason"],
                "lower_cutoff_candidate": profile_search["lower_cutoff"],
                "upper_cutoff_candidate": profile_search["upper_cutoff"],
            },
        )
        if strategy_catalog is not None:
            unobserved_bins = [
                row for row in audit["bins"] if row.get("status") == "UNOBSERVED"
            ]
            if not unobserved_bins:
                plans = []
                plan_status = "all_primary_bins_observed"
            else:
                available_count = sum(len(items) for items in strategy_catalog.values())
                max_candidates = max_catalog_candidates or max(1, available_count)
                plans = plan_gap_candidates(
                    audit,
                    strategy_catalog=strategy_catalog,
                    max_candidates=max_candidates,
                    gap_class_priority=strategy_catalog_settings.get("gap_class_priority"),
                )
                plan_status = "review_required"
            plan_path = iteration_dir / "strategy_candidate_plans.json"
            plan_payload = {
                "schema_version": 1,
                "status": plan_status,
                "execution_started": False,
                "iteration": iteration,
                "source_audit": str(audit_path),
                "source_csvs": list(campaign_csv_paths),
                "remaining_unobserved_bins": [
                    int(row["bin_index"]) for row in unobserved_bins
                ],
                "candidate_plans": plans,
            }
            plan_path.write_text(
                json.dumps(plan_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            record["strategy_candidate_plan_path"] = str(plan_path)
            record["strategy_candidate_count"] = len(plans)
            record["strategy_plan_status"] = plan_status
            record["next_action"] = (
                "strategy_candidate_review_required"
                if plans else plan_status
            )
            append_ledger(str(ledger_path), record)
            campaign_records.append(record)
            before_audit = audit
            break
        active_target_bins = []
        if euler_spec is not None and euler_spec.get("probe_case_path"):
            active_target_bins, remaining_profile_bins = next_unobserved_profile_target(
                audit, euler_spec["target_bins"]
            )
            record["active_target_bins"] = active_target_bins
            record["remaining_profile_bins"] = remaining_profile_bins
            if not remaining_profile_bins:
                record["next_action"] = "all_profile_bins_observed"
                record["profile_cutoff_identified"] = profile_search["status"] == "identified"
                append_ledger(str(ledger_path), record)
                campaign_records.append(record)
                before_audit = audit
                break
        if profile_search["status"] == "identified" and getattr(
            args, "stop_on_identified", False
        ):
            record["next_action"] = "stop_profile_search_identified"
            append_ledger(str(ledger_path), record)
            campaign_records.append(record)
            before_audit = audit
            break
        if euler_spec is not None and (
            iteration + 1 < args.iterations or euler_spec.get("probe_case_path")
        ):
            next_iteration_dir = workdir / f"iteration_{iteration + 1:03d}"
            feature_bounds = {
                key: tuple(value) for key, value in euler_spec["feature_bounds"].items()
            }
            if euler_spec.get("probe_case_path"):
                parent_path = previous_case_path or euler_spec["case_path"]
                probe_path = (current_case_paths[0] if previous_case_path
                              else euler_spec["probe_case_path"])
                measured_probe = observed_euler_probe(
                    (previous_records or []) + csv_records,
                    parent_path=parent_path,
                    probe_path=probe_path,
                    feature_bounds=feature_bounds,
                    target_bins=active_target_bins,
                    cutoffs=audit["cutoffs"],
                )
                record["euler_probe"] = measured_probe
                if iteration == 0:
                    nearest = nearest_observed_signatures(
                        audit, active_target_bins
                    )
                    record["nearest_observed_signatures"] = nearest
                    nearest_hash = (
                        measured_probe["probe_signature_hash"]
                        if measured_probe["source_case_path"] == probe_path
                        else measured_probe["parent_signature_hash"]
                    )
                    if nearest_hash not in nearest["signature_hashes"]:
                        compatible = None
                        for near_path in case_paths:
                            near_name = load_case_mapping(near_path).get("name", Path(near_path).stem)
                            near_hashes = {
                                row.get("generation_signature_hash") for row in csv_records
                                if row.get("case_name") == near_name
                            }
                            if len(near_hashes) != 1 or not near_hashes.issubset(nearest["signature_hashes"]):
                                continue
                            for other_path in (euler_spec["probe_case_path"], euler_spec["case_path"]):
                                if near_path == other_path:
                                    continue
                                try:
                                    attempt = observed_euler_probe(
                                        csv_records, parent_path=near_path,
                                        probe_path=other_path, feature_bounds=feature_bounds,
                                        target_bins=active_target_bins,
                                        cutoffs=audit["cutoffs"],
                                    )
                                except ValueError:
                                    continue
                                if (attempt["source_case_path"] == near_path
                                    and assess_physical_probe(attempt)["status"] == "observed_local_response"):
                                    compatible = attempt
                                    break
                            if compatible is not None:
                                break
                        if compatible is None:
                            record["next_action"] = "await_nearest_signature_probe"
                            record["euler_stop_reason"] = (
                                "a closer observed signature requires a paired one-feature probe with measured physical response"
                            )
                            append_ledger(str(ledger_path), record)
                            campaign_records.append(record)
                            break
                        measured_probe = compatible
                        record["euler_probe"] = measured_probe
                delta = measured_probe["coverage_delta"]
                residual = measured_probe["coverage_residual"]
                response = sum(delta.get(key, 0.0) * value for key, value in residual.items())
                physical_assessment = assess_physical_probe(measured_probe)
                record["physical_assessment"] = physical_assessment
                feature = next(iter(measured_probe["feature_delta"]))
                density_probe = feature.endswith(".P32") or feature.endswith(".mean_spacing")
                extend_density = density_probe and (
                    response == 0.0 or physical_assessment["status"] in {
                        "no_intersection_response", "no_quality_response"
                    }
                )
                qprime_repeatability_with_coverage_progress = (
                    density_probe
                    and physical_assessment["status"] == "needs_repeatability"
                    and physical_assessment.get("conflicting_metric") == "Qp_bh_mean"
                    and measured_probe["coverage_delta"].get("proximity_gain", 0.0) >= 0.0
                )
                if qprime_repeatability_with_coverage_progress:
                    record["density_reachability_reason"] = (
                        "seed-level Qprime responses conflict, but target-bin proximity did not regress; "
                        "continue reviewed density reachability without inferring an Euler direction"
                    )
                extend_density = should_extend_density_reachability(
                    measured_probe,
                    physical_assessment,
                    response,
                    probe_path,
                )
                if extend_density:
                    candidate = build_density_reachability_probe(
                        parent_path, probe_path,
                        feature_bounds=feature_bounds, round_id=iteration + 1,
                        target_region=euler_spec["target_region"],
                        screening_seed=euler_spec.get("screening_seed", args.seed_start),
                        generator_version=euler_spec.get("generator_version", "validation-v1"),
                    )
                    if candidate is None:
                        record["next_action"] = "await_wider_density_bounds"
                        record["euler_stop_reason"] = "reviewed exploration bounds reached without sufficient response"
                        append_ledger(str(ledger_path), record)
                        campaign_records.append(record)
                        break
                    record["next_action"] = "expand_density_probe"
                    parent_path = probe_path
                elif physical_assessment["status"] in {"needs_measurement", "needs_repeatability"}:
                    record["next_action"] = "await_physical_probe_response"
                    record["euler_stop_reason"] = physical_assessment["status"]
                    append_ledger(str(ledger_path), record)
                    campaign_records.append(record)
                    break
                elif response == 0.0:
                    record["next_action"] = "stop_no_observed_euler_direction"
                    record["euler_stop_reason"] = "no measured movement toward target bins"
                    append_ledger(str(ledger_path), record)
                    campaign_records.append(record)
                    break
                elif physical_assessment["status"] != "observed_local_response":
                    record["next_action"] = "await_physical_probe_response"
                    record["euler_stop_reason"] = physical_assessment["status"]
                    append_ledger(str(ledger_path), record)
                    campaign_records.append(record)
                    break
                else:
                    parent_path = measured_probe["source_case_path"]
                    probes = [measured_probe]
            else:
                parent_path = euler_spec["case_path"]
                probes = euler_spec["probes"]
            if iteration + 1 >= args.iterations:
                if record.get("next_action") == "expand_density_probe":
                    record["next_action"] = "density_probe_iteration_limit"
                    record["euler_stop_reason"] = "a wider density probe needs another iteration"
                append_ledger(str(ledger_path), record)
                campaign_records.append(record)
                break
            if not (euler_spec.get("probe_case_path") and record.get("next_action") == "expand_density_probe"):
                candidate = build_euler_update_candidate_from_probes(
                    parent_path,
                    round_id=iteration + 1,
                    target_region=euler_spec["target_region"],
                    screening_seed=euler_spec.get("screening_seed", args.seed_start),
                    feature_bounds=feature_bounds,
                    probes=probes,
                    step_size=float(euler_spec["step_size"]),
                    discrete_features=euler_spec.get("discrete_features", []),
                    generator_version=euler_spec.get("generator_version", "validation-v1"),
                )
                candidate["case"].get("tags", {}).pop("density_probe_origin_normalized", None)
            if euler_spec.get("probe_case_path") and candidate["generation_signature_hash"] == compute_generation_signature_hash(load_case_mapping(parent_path)):
                limited_features = bound_limited_features(candidate)
                record["bound_limited_features"] = limited_features
                if limited_features and all(
                    feature.endswith((".P32", ".mean_spacing"))
                    for feature in limited_features
                ):
                    record["next_action"] = "await_wider_density_bounds"
                    record["euler_stop_reason"] = (
                        "observed density direction points beyond the approved feature bounds"
                    )
                else:
                    record["next_action"] = "stop_no_observed_euler_direction"
                    record["euler_stop_reason"] = (
                        "bounded step did not change the parent signature"
                    )
                append_ledger(str(ledger_path), record)
                campaign_records.append(record)
                break
            candidate_dir = next_iteration_dir / "candidate"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            stabilize_candidate_case_name(candidate, parent_path)
            candidate_path = candidate_dir / f"{candidate['candidate_id']}.yaml"
            candidate_path.write_text(
                yaml.safe_dump(candidate["case"], sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            (candidate_dir / "candidate.json").write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            current_case_paths = [str(candidate_path)]
            record["next_candidate_path"] = str(candidate_path)
            record["next_candidate_id"] = candidate["candidate_id"]
            if euler_spec.get("probe_case_path"):
                previous_records = (previous_records or []) + csv_records
                previous_case_path = parent_path
        append_ledger(str(ledger_path), record)
        campaign_records.append(record)
        before_audit = audit

    manifest["status"] = "completed"
    manifest["records"] = campaign_records
    (workdir / "campaign_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_campaign(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
