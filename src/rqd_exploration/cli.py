"""Command-line entry points for the RQD exploration pilot."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from typing import Sequence

from .config import NormalizedPilotInput, load_config
from .records import FrozenManifest
from .runner import build_mlx_pilot_manifest, execute_frozen_jobs
from .store import STORE_SCHEMA_VERSION, initialize_store, store_manifest

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot.yml"
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
    preview.add_argument("--manifest-id", required=True)

    for name in ("run", "resume"):
        command = commands.add_parser(
            name,
            help=(
                "execute frozen jobs"
                if name == "run"
                else "resume a persisted frozen manifest"
            ),
        )
        command.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
        command.add_argument("--manifest-id", required=True)
        command.add_argument("--database", type=Path, required=True)
        command.add_argument("--maximum-simulations", type=int, required=True)
        command.add_argument(
            "--confirm-execution",
            action="store_true",
            help="confirm the displayed config, manifest, database, and simulation cap",
        )
    return parser


def _config_summary(config: NormalizedPilotInput) -> dict[str, int | str]:
    return {
        "yaml_sha256": config.source_yaml_sha256,
        "designs": len(config.designs),
        "target_goals": len(config.target_goals),
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
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _run_execution(args: argparse.Namespace, config: NormalizedPilotInput) -> int:
    if not args.confirm_execution:
        print(
            "Execution not confirmed. Review the config and manifest with "
            "`preview`, then pass --confirm-execution to run or resume. "
            "No database was opened and no simulation was started.",
            file=sys.stderr,
        )
        return _EXIT_CONFIRMATION_REQUIRED
    if args.maximum_simulations < 1:
        raise ValueError("--maximum-simulations must be at least 1")
    if args.database.exists() and args.command == "run":
        raise FileExistsError(
            f"database already exists; use resume or choose another path: {args.database}"
        )
    if args.command == "resume" and not args.database.is_file():
        raise FileNotFoundError(f"resume database does not exist: {args.database}")

    manifest = build_mlx_pilot_manifest(config, manifest_id=args.manifest_id)
    manifest_summary = _manifest_summary(manifest)
    _print_payload({
        "command": args.command,
        "config": _config_summary(config),
        "manifest": manifest_summary,
        "maximum_simulations": args.maximum_simulations,
    })

    from src.euler_campaign.mlx_backend import MlxCaseJointFactory, require_mlx_gpu

    require_mlx_gpu()
    factory = MlxCaseJointFactory()

    if args.command == "run":
        args.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(args.database)
        try:
            initialize_store(connection)
            store_manifest(connection, manifest)
            summary = execute_frozen_jobs(
                connection,
                manifest,
                config,
                factory,
                maximum_simulations=args.maximum_simulations,
            )
        finally:
            connection.close()
    else:
        connection = sqlite3.connect(
            f"{args.database.resolve().as_uri()}?mode=rw", uri=True,
        )
        try:
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if user_version != STORE_SCHEMA_VERSION:
                raise ValueError(
                    f"resume database schema version {STORE_SCHEMA_VERSION} required; "
                    f"found {user_version}"
                )
            initialize_store(connection)
            persisted = connection.execute(
                "SELECT manifest_json FROM manifest WHERE manifest_id = ?",
                (args.manifest_id,),
            ).fetchone()
            if persisted is None:
                raise ValueError(
                    f"manifest {args.manifest_id!r} is not present in the resume database"
                )
            if persisted[0] != manifest.manifest_json:
                raise ValueError(
                    "current config/runtime manifest does not match the persisted manifest"
                )
            summary = execute_frozen_jobs(
                connection,
                manifest,
                config,
                factory,
                maximum_simulations=args.maximum_simulations,
            )
        finally:
            connection.close()

    _print_payload({"run_summary": asdict(summary)})
    return _EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "validate":
            _print_payload({"valid": True, "config": _config_summary(config)})
            return _EXIT_OK
        if args.command == "preview":
            manifest = build_mlx_pilot_manifest(config, manifest_id=args.manifest_id)
            _print_payload({
                "config": _config_summary(config),
                "manifest": _manifest_summary(manifest),
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
