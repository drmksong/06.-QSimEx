"""Command-line entry point for the durable Euler signature campaign."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .campaign import CampaignResult, RevisionCampaignStore, run_campaign_project
from .campaign_store import SQLiteCampaignStore
from .config import CampaignProject, load_campaign_project
from .coverage import CoverageGrid, CoverageResult
from .euler import (
    GapSeekingNormalizedGradientUpdateRule,
    NormalizedGradientUpdateRule,
)
from .models import Signature
from .profiles import SimulationResult
from .simulator import EulerSimulator

_GENERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_LOGGER = logging.getLogger("qsimex.euler_campaign")


class _ProgressSimulator:
    """Log simulation requests and cumulative coverage without changing the contract."""

    def __init__(self, simulator: EulerSimulator, grid: CoverageGrid) -> None:
        self._simulator = simulator
        self._grid_id = grid.grid_id
        self._total_bins = len(grid.edges) - 1
        self._covered_bins: set[int] = set()
        self._simulation_count = 0

    def initialize_coverage(self, covered_bins: frozenset[int]) -> None:
        self._covered_bins = set(covered_bins)
        self._log_coverage_state("at invocation start")

    def report_coverage(self, coverage: CoverageResult) -> None:
        self._covered_bins.update(coverage.observed_bins)
        self._log_coverage_state(
            f"after signature_id={coverage.signature_id[:12]}... seed={coverage.seed}"
        )

    def _log_coverage_state(self, context: str) -> None:
        empty_bins = [
            index + 1
            for index in range(self._total_bins)
            if index not in self._covered_bins
        ]
        _LOGGER.info(
            "coverage state %s grid=%s covered_bins=%d/%d empty_bins_1based=%s",
            context,
            self._grid_id,
            len(self._covered_bins),
            self._total_bins,
            empty_bins,
        )

    @property
    def backend(self) -> str:
        return self._simulator.backend

    @property
    def runtime_info(self) -> tuple[str, ...]:
        return self._simulator.runtime_info

    @property
    def execution_fingerprint(self) -> str:
        return self._simulator.execution_fingerprint

    def evaluate(self, signature: Signature, seed: int) -> SimulationResult:
        self._simulation_count += 1
        _LOGGER.info(
            "simulation #%d started signature_id=%s seed=%d",
            self._simulation_count,
            f"{signature.signature_id[:12]}...",
            seed,
        )
        result = self._simulator.evaluate(signature, seed)
        _LOGGER.info(
            "simulation #%d completed signature_id=%s seed=%d domain_id=%s",
            self._simulation_count,
            f"{result.signature_id[:12]}...",
            result.seed,
            f"{result.domain_id[:12]}...",
        )
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run or resume the MLX-GPU Euler campaign described by a "
            "CampaignProject YAML file."
        ),
        epilog=(
            "Normal invocations resume the latest run generation automatically. "
            "Use --force-from-scratch to start a new generation without reusing "
            "previous results.\n\n"
            "Examples:\n"
            "  python run_euler_campaign.py --project "
            "cases/euler/highq_euler_multistart_campaign_draft.yaml\n"
            "  python run_euler_campaign.py --project <campaign.yaml> "
            "--force-from-scratch"
        ),
    )
    parser.add_argument(
        "--project",
        required=True,
        type=Path,
        help="CampaignProject YAML file",
    )
    parser.add_argument(
        "--run-generation-id",
        help="Resume this existing run generation, or name the initial generation",
    )
    parser.add_argument(
        "--source-generation-id",
        help="Predecessor generation to use when applying a new plan revision",
    )
    parser.add_argument(
        "--force-from-scratch",
        action="store_true",
        help="Start a new generation and do not reuse prior simulation results",
    )
    return parser


def _validate_generation_id(value: str, name: str) -> str:
    if not isinstance(value, str) or not _GENERATION_ID.fullmatch(value):
        raise ValueError(
            f"{name} must be a path-safe ID of 1 to 128 ASCII letters, digits, "
            "periods, underscores, or hyphens"
        )
    return value


def _resolve_run_ids(
    store: RevisionCampaignStore,
    project: CampaignProject,
    requested_generation_id: str | None,
    requested_source_generation_id: str | None,
    force_from_scratch: bool,
) -> tuple[str, str | None]:
    campaign_id = project.plan.campaign_id
    revision = project.plan_revision
    source_generation_id = requested_source_generation_id
    if source_generation_id is not None:
        _validate_generation_id(source_generation_id, "source_generation_id")

    if revision == 1 and source_generation_id is not None:
        raise ValueError("the initial campaign revision cannot have a source generation")

    current_revision_generation = store.latest_generation(campaign_id, revision)
    if (
        current_revision_generation is not None
        and store.load_generation_state(
            campaign_id, current_revision_generation, revision,
        ) is None
    ):
        raise ValueError(
            "the latest run generation has no state for the current plan revision"
        )

    if revision > 1 and source_generation_id is None:
        if (
            requested_generation_id is not None
            and store.generation_exists(campaign_id, requested_generation_id)
        ):
            source_generation_id = requested_generation_id
        elif current_revision_generation is not None:
            source_generation_id = current_revision_generation
        else:
            source_generation_id = store.latest_generation(campaign_id, revision - 1)
        if source_generation_id is None:
            raise ValueError(
                f"revision {revision} requires a stored predecessor generation"
            )

    if force_from_scratch:
        generation_id = requested_generation_id or uuid4().hex
        _validate_generation_id(generation_id, "run_generation_id")
        if store.generation_exists(campaign_id, generation_id):
            raise ValueError(
                "--force-from-scratch requires a new run-generation ID"
            )
        return generation_id, source_generation_id

    if requested_generation_id is not None:
        generation_id = _validate_generation_id(
            requested_generation_id, "run_generation_id",
        )
        if store.load_generation_state(campaign_id, generation_id, revision) is not None:
            return generation_id, source_generation_id
        if revision > 1 and generation_id == source_generation_id:
            return generation_id, source_generation_id
        if revision == 1 and current_revision_generation is None:
            if store.generation_exists(campaign_id, generation_id):
                raise ValueError(
                    "the requested generation exists but has no state for revision 1"
                )
            return generation_id, source_generation_id
        raise ValueError(
            "starting another run generation requires --force-from-scratch"
        )

    if current_revision_generation is not None:
        return current_revision_generation, source_generation_id
    if source_generation_id is not None:
        return source_generation_id, source_generation_id
    return uuid4().hex, None


def _project_relative_path(project_file: Path, relative_path: str) -> Path:
    project_root = project_file.parent.resolve()
    path = (project_root / relative_path).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as error:
        raise ValueError("campaign output path resolves outside the project folder") from error
    return path


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                summary,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _result_summary(
    project: CampaignProject,
    result: CampaignResult,
    simulator: _ProgressSimulator,
    execution_fingerprint: str,
    database_path: Path,
    output_directory: Path,
    total_rounds: int,
    covered_bins: frozenset[int],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "campaign_id": project.plan.campaign_id,
        "plan_revision": project.plan_revision,
        "parent_revision": project.parent_revision,
        "plan_fingerprint": result.state.plan_fingerprint,
        "run_generation_id": result.run_generation_id,
        "inputs": {
            "base_case": project.base_case,
            "category_catalog": project.category_catalog,
            "start_signature_ids": [
                signature.signature_id
                for signature in project.plan.start_signatures
            ],
            "coverage_grid_id": project.plan.grid.grid_id,
            "exploration_seed": project.plan.exploration_seed,
            "verification_seeds": list(project.plan.verification_seeds),
            "update_rule_id": project.plan.update_rule_id,
            "round_budget": project.round_budget,
            "result_role": "coverage_exploration_only",
            "include_in_calibration": False,
            "include_in_validation": False,
        },
        "simulation_fingerprint": sha256(
            execution_fingerprint.encode("utf-8"),
        ).hexdigest(),
        "execution": {
            "backend": simulator.backend,
            "device_runtime": list(simulator.runtime_info),
            "execution_fingerprint": execution_fingerprint,
        },
        "status": result.state.status,
        "reason": result.state.reason,
        "rounds_executed_this_invocation": len(result.rounds),
        "rounds_completed_in_generation": total_rounds,
        "coverage": {
            "grid_id": project.plan.grid.grid_id,
            "covered_bins": sorted(covered_bins),
            "total_bins": len(project.plan.grid.edges) - 1,
        },
        "lineages": [
            {
                "start_signature_id": lineage.start_signature_id,
                "parent_signature_id": lineage.parent.signature_id,
                "status": lineage.status,
                "next_round_index": lineage.next_round_index,
                "blocked_features": list(lineage.blocked_features),
                "reason": lineage.reason,
            }
            for lineage in result.state.lineages
        ],
        "storage": {
            "database": str(database_path),
            "run_directory": str(output_directory),
        },
    }


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = build_parser().parse_args(argv)
    store: SQLiteCampaignStore | None = None
    try:
        project_file = args.project.expanduser().resolve(strict=True)
        project = load_campaign_project(project_file)
        normalized_rule = NormalizedGradientUpdateRule()
        gap_seeking_rule = GapSeekingNormalizedGradientUpdateRule()
        if project.plan.update_rule_id == normalized_rule.rule_id:
            update_rule = normalized_rule
        elif project.plan.update_rule_id == gap_seeking_rule.rule_id:
            update_rule = gap_seeking_rule
        else:
            raise ValueError(
                f"unsupported update rule: {project.plan.update_rule_id}"
            )

        # The approved campaign execution policy requires MLX GPU; there is no
        # CPU fallback or command-line override.
        progress_simulator = _ProgressSimulator(
            EulerSimulator(backend="mlx"), project.plan.grid,
        )
        execution_fingerprint = progress_simulator.execution_fingerprint

        campaign_directory = _project_relative_path(
            project_file,
            f"results/euler_campaigns/{project.plan.campaign_id}",
        )
        database_path = campaign_directory / "campaign.sqlite3"
        store = SQLiteCampaignStore(database_path)
        run_generation_id, source_generation_id = _resolve_run_ids(
            store,
            project,
            args.run_generation_id,
            args.source_generation_id,
            args.force_from_scratch,
        )
        progress_simulator.initialize_coverage(
            store.generation_covered_bins(
                project.plan.campaign_id,
                run_generation_id,
                project.plan.grid,
            )
        )
        output_directory = _project_relative_path(
            project_file,
            project.output_path_template.format(
                campaign_id=project.plan.campaign_id,
                run_generation_id=run_generation_id,
            ),
        )
        output_directory.mkdir(parents=True, exist_ok=True)

        _LOGGER.info(
            "campaign start project=%s campaign_id=%s revision=%d run_generation_id=%s "
            "start_lineages=%d backend=%s device_runtime=%s",
            project_file,
            project.plan.campaign_id,
            project.plan_revision,
            run_generation_id,
            len(project.plan.start_signatures),
            progress_simulator.backend,
            ",".join(progress_simulator.runtime_info),
        )
        _LOGGER.info(
            "execution_fingerprint=%s database=%s output_directory=%s",
            execution_fingerprint,
            database_path,
            output_directory,
        )

        result = run_campaign_project(
            project,
            progress_simulator,
            update_rule,
            store,
            execution_fingerprint,
            source_generation_id=source_generation_id,
            run_generation_id=run_generation_id,
            force_from_scratch=args.force_from_scratch,
        )
        total_rounds = store.generation_round_count(
            project.plan.campaign_id, run_generation_id,
        )
        covered_bins = store.generation_covered_bins(
            project.plan.campaign_id, run_generation_id, project.plan.grid,
        )
        summary_path = output_directory / "run_summary.json"
        _write_summary(
            summary_path,
            _result_summary(
                project,
                result,
                progress_simulator,
                execution_fingerprint,
                database_path,
                output_directory,
                total_rounds,
                covered_bins,
            ),
        )
        finish_log = (
            _LOGGER.error
            if result.state.status in ("failed", "decision_required")
            else _LOGGER.info
        )
        finish_log(
            "campaign finished status=%s rounds_this_invocation=%d "
            "rounds_in_generation=%d covered_bins=%d/%d reason=%s summary=%s",
            result.state.status,
            len(result.rounds),
            total_rounds,
            len(covered_bins),
            len(project.plan.grid.edges) - 1,
            result.state.reason or "none",
            summary_path,
        )
        if result.state.status == "failed":
            return 1
        if result.state.status == "decision_required":
            return 2
        return 0
    except KeyboardInterrupt:
        _LOGGER.warning("campaign interrupted; completed checkpoints are retained")
        return 130
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
