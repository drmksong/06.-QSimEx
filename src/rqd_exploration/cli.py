"""Command-line entry points for the RQD exploration pilot."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from typing import Sequence
from uuid import uuid4

from .config import NormalizedPilotInput, load_config
from . import analysis
from .dataset import (
    load_latest_cumulative_dataset_revision,
    load_latest_dataset_revision,
    persist_cumulative_analysis_run,
    persist_cumulative_derived_scores,
    persist_analysis_run,
    persist_derived_scores,
)
from .cumulative_reporting import export_cumulative_coverage_report
from .records import FrozenManifest
from .reporting import export_reference_profile_report, preflight_reference_profile_report
from .runner import build_mlx_pilot_manifest, execute_frozen_jobs
from .store import STORE_SCHEMA_VERSION, initialize_store, store_manifest

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
_DEFAULT_REPORTS_ROOT = Path(__file__).resolve().parents[2] / "results/rqd_exploration"
_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_CONFIRMATION_REQUIRED = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_rqd_exploration.py",
        description="Validate, preview, or explicitly execute the RQD exploration pilot.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate pilot YAML without MLX preflight")
    validate.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)

    preview = commands.add_parser("preview", help="build an in-memory MLX manifest preview")
    preview.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)

    analyze = commands.add_parser(
        "analyze",
        help="analyze a persisted dataset revision and export deterministic reports",
    )
    analyze.add_argument("--database", type=Path, required=True)
    analyze.add_argument("--manifest-id", required=True)
    analyze.add_argument("--revision-index", type=int)
    analyze.add_argument("--output-dir", type=Path)

    analyze_cumulative = commands.add_parser(
        "analyze-cumulative",
        help="re-score and persist an immutable cumulative dataset revision",
    )
    analyze_cumulative.add_argument("--database", type=Path, required=True)
    analyze_cumulative.add_argument("--revision-index", type=int)
    analyze_cumulative.add_argument(
        "--jr-values",
        type=float,
        nargs="+",
        help="selected Jr values; defaults to the complete approved Jr catalog",
    )
    analyze_cumulative.add_argument(
        "--ja-values",
        type=float,
        nargs="+",
        help="selected Ja values; defaults to the complete approved Ja catalog",
    )

    report_cumulative = commands.add_parser(
        "report-cumulative",
        help="export cumulative coverage without modifying the database",
    )
    report_cumulative.add_argument("--database", type=Path, required=True)
    report_cumulative.add_argument("--revision-index", type=int)
    report_cumulative.add_argument(
        "--jr-values",
        type=float,
        nargs="+",
        help="selected Jr values; defaults to the complete approved Jr catalog",
    )
    report_cumulative.add_argument(
        "--ja-values",
        type=float,
        nargs="+",
        help="selected Ja values; defaults to the complete approved Ja catalog",
    )
    report_cumulative.add_argument("--output-dir", type=Path)

    run = commands.add_parser(
        "run",
        help="append a new batch or automatically resume a matching unfinished batch",
    )
    run.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--maximum-simulations", type=int, required=True)
    run.add_argument(
        "--confirm-execution",
        action="store_true",
        help="confirm the displayed config, database, and simulation cap",
    )
    return parser


def _config_summary(config: NormalizedPilotInput) -> dict[str, int | str]:
    return {
        "yaml_sha256": config.source_yaml_sha256,
        "designs": len(config.designs),
        "samples": sum(design.sample_count for design in config.designs),
    }


def _manifest_summary(manifest: FrozenManifest) -> dict[str, int | str]:
    payload = json.loads(manifest.manifest_json)
    locations = payload["planned_locations"]
    return {
        "manifest_id": manifest.manifest_id,
        "manifest_sha256": sha256(manifest.manifest_json.encode("utf-8")).hexdigest(),
        "jobs": len(manifest.jobs),
        "planned_locations": len(locations),
        "bh_locations": sum(item["modality"] == "BH" for item in locations),
        "face_locations": sum(item["modality"] == "face" for item in locations),
    }


def _print_payload(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


def _print_progress(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{timestamp} {message}", file=sys.stderr, flush=True)


def _analysis_output_directory(args: argparse.Namespace) -> Path:
    if args.output_dir is not None:
        return args.output_dir
    root = _DEFAULT_REPORTS_ROOT.resolve()
    candidate = (root / args.manifest_id / "reports").resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("manifest_id resolves outside the default report directory")
    return candidate


def _cumulative_report_output_directory(
    args: argparse.Namespace,
    revision_index: int,
) -> Path:
    if args.output_dir is not None:
        return args.output_dir
    root = _DEFAULT_REPORTS_ROOT.resolve()
    return root / "cumulative" / f"revision-{revision_index}" / "reports"


def _initialize_existing_store(connection: sqlite3.Connection, purpose: str) -> None:
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if not 1 <= user_version <= STORE_SCHEMA_VERSION:
        raise ValueError(
            f"{purpose} database schema version {STORE_SCHEMA_VERSION} required; "
            f"found {user_version}"
        )
    initialize_store(connection)


def _normalized_frozen_payload(manifest_json: str) -> str:
    payload = json.loads(manifest_json)
    if not isinstance(payload, dict):
        raise ValueError("manifest_json must contain a JSON object")
    payload.pop("manifest_id", None)
    provenance = payload.get("input_provenance")
    if isinstance(provenance, dict):
        provenance.pop("source_reference", None)

    def remove_nested_ids(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: remove_nested_ids(item)
                for key, item in value.items()
                if key != "manifest_id"
            }
        if isinstance(value, list):
            return [remove_nested_ids(item) for item in value]
        return value

    return json.dumps(
        remove_nested_ids(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _runtime_identity(manifest_json: str) -> tuple[str, ...]:
    payload = json.loads(manifest_json)
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("manifest_json must contain a jobs list")
    runtimes = {
        json.dumps(
            job["execution_snapshot"]["inputs"]["runtime"],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for job in payload["jobs"]
        if isinstance(job, dict)
        and isinstance(job.get("execution_snapshot"), dict)
        and isinstance(job["execution_snapshot"].get("inputs"), dict)
        and isinstance(job["execution_snapshot"]["inputs"].get("runtime"), dict)
    }
    if not runtimes:
        raise ValueError("manifest_json has no execution runtime snapshots")
    return tuple(sorted(runtimes))


def _find_exact_batch(
    connection: sqlite3.Connection,
    manifest: FrozenManifest,
) -> tuple[str, str, bytes, str | None] | None:
    rows = connection.execute(
        """
        SELECT manifest.manifest_id, manifest.manifest_json,
               input_provenance.yaml_bytes, input_provenance.source_reference
        FROM manifest
        JOIN input_provenance USING (manifest_id)
        WHERE input_provenance.yaml_sha256 = ?
        ORDER BY manifest.manifest_id
        """,
        (manifest.source_yaml_sha256,),
    ).fetchall()
    exact_matches: list[tuple[str, str, bytes, str | None]] = []
    candidate_runtime = _runtime_identity(manifest.manifest_json)
    candidate_payload = _normalized_frozen_payload(manifest.manifest_json)
    for manifest_id, manifest_json, yaml_bytes, source_reference in rows:
        if yaml_bytes != manifest.source_yaml_bytes:
            raise ValueError(
                f"stored YAML bytes do not match their SHA-256 for batch {manifest_id!r}"
            )
        if _runtime_identity(manifest_json) != candidate_runtime:
            continue
        if _normalized_frozen_payload(manifest_json) != candidate_payload:
            raise ValueError(
                "exact YAML bytes and runtime match a persisted batch, but its frozen "
                "execution payload differs; refusing an unsafe automatic resume"
            )
        exact_matches.append((manifest_id, manifest_json, yaml_bytes, source_reference))
    if len(exact_matches) > 1:
        raise ValueError(
            "multiple unfinished or completed batches match the exact config/runtime; "
            "refusing an ambiguous automatic resume"
        )
    return exact_matches[0] if exact_matches else None


def _manifest_is_complete(
    connection: sqlite3.Connection,
    manifest: FrozenManifest,
) -> bool:
    from .store import job_attempt_statuses

    return all(
        any(status == "succeeded" for _, status in job_attempt_statuses(connection, job))
        for job in manifest.jobs
    )


def _reuse_persisted_manifest(
    candidate: FrozenManifest,
    persisted: tuple[str, str, bytes, str | None],
) -> FrozenManifest:
    manifest_id, manifest_json, yaml_bytes, source_reference = persisted
    return FrozenManifest(
        manifest_id,
        manifest_json,
        yaml_bytes,
        candidate.source_yaml_sha256,
        source_reference,
        tuple(replace(job, manifest_id=manifest_id) for job in candidate.jobs),
    )


def _run_analysis(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        raise FileNotFoundError(f"analysis database does not exist: {args.database}")
    connection = sqlite3.connect(
        f"{args.database.resolve().as_uri()}?mode=rw",
        uri=True,
    )
    try:
        _initialize_existing_store(connection, "analysis")
        revision = load_latest_dataset_revision(
            connection,
            args.manifest_id,
            args.revision_index,
        )
        result = analysis.analyze_reference_profiles(
            revision.observations,
            revision.location_states,
        )
        preflight = preflight_reference_profile_report(
            revision.manifest_id,
            revision.revision_index,
            revision.dataset_sha256,
            revision.observations,
            revision.location_states,
            result,
        )
        analysis_snapshot = analysis.build_analysis_snapshot(
            revision.revision_index,
            revision.dataset_sha256,
        )
        analysis_fingerprint = persist_analysis_run(
            connection,
            revision,
            analysis_snapshot,
        )
        derived_score_rows = persist_derived_scores(
            connection,
            revision,
            analysis_fingerprint,
        )
        report = export_reference_profile_report(
            _analysis_output_directory(args),
            revision.manifest_id,
            revision.revision_index,
            revision.dataset_sha256,
            revision.observations,
            revision.location_states,
            result,
        )
        _print_payload({
            "command": "analyze",
            "manifest_id": revision.manifest_id,
            "dataset_revision_index": revision.revision_index,
            "dataset_sha256": revision.dataset_sha256,
            "analysis_fingerprint_sha256": analysis_fingerprint,
            "derived_score_rows": derived_score_rows,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "output_directory": str(report.output_directory),
            "report_summary_sha256": report.summary_sha256,
            "file_rows": {
                item.file_name: item.expected_rows
                for item in preflight.files
            },
            "simulation_started": False,
            "raw_observations_modified": False,
        })
    finally:
        connection.close()
    return _EXIT_OK


def _run_cumulative_analysis(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        raise FileNotFoundError(f"analysis database does not exist: {args.database}")
    connection = sqlite3.connect(
        f"{args.database.resolve().as_uri()}?mode=rw",
        uri=True,
    )
    try:
        _initialize_existing_store(connection, "cumulative analysis")
        revision = load_latest_cumulative_dataset_revision(
            connection,
            args.revision_index,
        )
        jr_values = None if args.jr_values is None else tuple(args.jr_values)
        ja_values = None if args.ja_values is None else tuple(args.ja_values)
        result = analysis.analyze_reference_profiles(
            revision.observations,
            revision.location_states,
            jr_values=jr_values,
            ja_values=ja_values,
        )
        analysis_snapshot = analysis.build_cumulative_analysis_snapshot(
            revision.revision_index,
            revision.dataset_sha256,
            jr_values=jr_values,
            ja_values=ja_values,
        )
        analysis_fingerprint = persist_cumulative_analysis_run(
            connection,
            revision,
            analysis_snapshot,
        )
        derived_score_rows = persist_cumulative_derived_scores(
            connection,
            revision,
            analysis_fingerprint,
        )
        _print_payload({
            "command": "analyze-cumulative",
            "dataset_revision_index": revision.revision_index,
            "dataset_sha256": revision.dataset_sha256,
            "manifest_ids": revision.manifest_ids,
            "raw_attempt_count": revision.raw_attempt_count,
            "raw_observation_count": revision.raw_observation_count,
            "selected_observation_count": len(revision.observations),
            "independent_realization_count": revision.independent_realization_count,
            "scenario_evaluation_count": result.scenario_evaluation_count,
            "analysis_fingerprint_sha256": analysis_fingerprint,
            "derived_score_rows": derived_score_rows,
            "simulation_started": False,
            "raw_observations_modified": False,
        })
    finally:
        connection.close()
    return _EXIT_OK


def _run_cumulative_report(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        raise FileNotFoundError(f"report database does not exist: {args.database}")
    connection = sqlite3.connect(
        f"{args.database.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if user_version != STORE_SCHEMA_VERSION:
            raise ValueError(
                f"cumulative report requires read-only schema version "
                f"{STORE_SCHEMA_VERSION}; found {user_version}"
            )
        revision_index = args.revision_index
        if revision_index is None:
            row = connection.execute(
                "SELECT MAX(revision_index) FROM cumulative_dataset_revisions",
            ).fetchone()
            revision_index = None if row is None else row[0]
        if revision_index is None:
            raise ValueError(
                "no persisted cumulative dataset revision; run analyze-cumulative first"
            )
        revision = load_latest_cumulative_dataset_revision(
            connection,
            revision_index,
        )
        jr_values = None if args.jr_values is None else tuple(args.jr_values)
        ja_values = None if args.ja_values is None else tuple(args.ja_values)
        report = export_cumulative_coverage_report(
            _cumulative_report_output_directory(args, revision.revision_index),
            revision,
            jr_values=jr_values,
            ja_values=ja_values,
        )
        _print_payload({
            "command": "report-cumulative",
            "dataset_revision_index": revision.revision_index,
            "dataset_sha256": revision.dataset_sha256,
            "manifest_ids": revision.manifest_ids,
            "source_observation_count": report.preflight.source_observation_count,
            "unique_observation_count": report.preflight.unique_observation_count,
            "source_execution_fingerprint_count": (
                report.preflight.source_execution_fingerprint_count
            ),
            "eligible_execution_fingerprint_count": (
                report.preflight.eligible_execution_fingerprint_count
            ),
            "conflicted_fingerprint_count": (
                report.preflight.conflicted_fingerprint_count
            ),
            "analysis_fingerprint_sha256": (
                report.preflight.analysis_fingerprint_sha256
            ),
            "output_directory": str(report.output_directory),
            "report_summary_sha256": report.summary_sha256,
            "file_rows": {
                item.file_name: item.expected_rows
                for item in report.preflight.files
            },
            "simulation_started": False,
            "database_modified": False,
        })
    finally:
        connection.close()
    return _EXIT_OK


def _run_execution(args: argparse.Namespace, config: NormalizedPilotInput) -> int:
    if not args.confirm_execution:
        print(
            "Execution not confirmed. Review the config and manifest with "
            "`preview`, then pass --confirm-execution to run. "
            "No database was opened and no simulation was started.",
            file=sys.stderr,
        )
        return _EXIT_CONFIRMATION_REQUIRED
    if args.maximum_simulations < 1:
        raise ValueError("--maximum-simulations must be at least 1")
    database_exists = args.database.exists()
    if database_exists and not args.database.is_file():
        raise ValueError(f"database path is not a file: {args.database}")
    if database_exists and args.database.stat().st_size == 0:
        raise ValueError(f"existing database file is empty: {args.database}")

    manifest = build_mlx_pilot_manifest(config, manifest_id=f"batch-{uuid4().hex}")
    from src.euler_campaign.mlx_backend import MlxCaseJointFactory
    factory = MlxCaseJointFactory()

    if database_exists:
        connection = sqlite3.connect(
            f"{args.database.resolve().as_uri()}?mode=rw", uri=True,
        )
    else:
        args.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(args.database)

    try:
        if database_exists:
            _initialize_existing_store(connection, "execution")
        else:
            initialize_store(connection)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            persisted = _find_exact_batch(connection, manifest)
            if persisted is None:
                store_manifest(connection, manifest)
                batch_action = "added"
            else:
                manifest = _reuse_persisted_manifest(manifest, persisted)
                if _manifest_is_complete(connection, manifest):
                    raise ValueError(
                        "completed exact duplicate batch already exists; "
                        "no simulation was started"
                    )
                batch_action = "resumed"
            connection.commit()

            _print_payload({
                "command": "run",
                "batch_action": batch_action,
                "database": str(args.database.resolve()),
                "config": _config_summary(config),
                "manifest": _manifest_summary(manifest),
                "maximum_simulations": args.maximum_simulations,
            })
            summary = execute_frozen_jobs(
                connection,
                manifest,
                config,
                factory,
                maximum_simulations=args.maximum_simulations,
                progress_callback=_print_progress,
            )
    finally:
        connection.close()

    _print_payload({"run_summary": asdict(summary)})
    return _EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return _run_analysis(args)
        if args.command == "analyze-cumulative":
            return _run_cumulative_analysis(args)
        if args.command == "report-cumulative":
            return _run_cumulative_report(args)
        config = load_config(args.config)
        if args.command == "validate":
            _print_payload({"valid": True, "config": _config_summary(config)})
            return _EXIT_OK
        if args.command == "preview":
            manifest = build_mlx_pilot_manifest(config, manifest_id="preview")
            _print_payload({
                "config": _config_summary(config),
                "manifest": _manifest_summary(manifest),
                "manifest_id_is_persisted": False,
                "simulation_started": False,
                "database_written": False,
            })
            return _EXIT_OK
        return _run_execution(args, config)
    except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as error:
        print(f"RQD exploration {args.command} failed: {error}", file=sys.stderr)
        return _EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
