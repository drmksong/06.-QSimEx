"""Manifest preparation and one-realization execution boundaries."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import platform
import sqlite3
from threading import Event, Lock, Thread
from time import monotonic
from typing import Callable, Literal

import numpy
import scipy

from src.euler_campaign.models import CaseSpec
from src.euler_campaign.ports import JointFactory
from src.euler_campaign.progress import ProgressUpdate

from .adapter import build_generation_case
from .config import NormalizedPilotInput
from .design import (
    build_frozen_manifest,
    generate_lhs_design,
)
from .fingerprint import ExecutionRuntime
from .measurement import (
    FACE_BOUNDARY_RULES_VERSION,
    MEASUREMENT_VERSION,
    MeasurementResult,
    PlannedLocationState,
    RawBHObservation,
    measure_realization,
    plan_measurement_locations,
)
from .records import ExecutionJob, FrozenManifest
from .store import (
    begin_attempt,
    checkpoint_attempt_runtime,
    complete_attempt,
    finish_attempt,
    job_attempt_statuses,
    resume_attempt,
)


@dataclass(frozen=True)
class FrozenJobRunSummary:
    completed_job_keys: tuple[tuple[str, str, str, int, int], ...]
    skipped_completed_job_keys: tuple[tuple[str, str, str, int, int], ...]
    skipped_failed_job_keys: tuple[tuple[str, str, str, int, int], ...]
    simulation_count: int
    maximum_simulations: int
    termination_reason: Literal["jobs_complete", "budget_exhausted"]


def build_mlx_pilot_manifest(
    config: NormalizedPilotInput, *, manifest_id: str,
) -> FrozenManifest:
    """Build the complete MLX pilot manifest after verifying its active GPU runtime."""
    from src.euler_campaign.mlx_backend import (
        MLX_GENERATOR_VERSION,
        require_mlx_gpu,
    )

    mlx_version, device = require_mlx_gpu()
    runtime = ExecutionRuntime(
        MLX_GENERATOR_VERSION,
        MEASUREMENT_VERSION,
        "mlx",
        (
            f"python_implementation={platform.python_implementation()}",
            f"python_version={platform.python_version()}",
            f"platform={platform.platform()}",
            f"numpy_version={numpy.__version__}",
            f"scipy_version={scipy.__version__}",
            f"mlx_version={mlx_version}",
            f"device={device}",
        ),
    )

    if not config.designs:
        raise ValueError("pilot config must contain at least one design")
    first_design = config.designs[0]
    samples = generate_lhs_design(first_design).samples
    if not samples:
        raise ValueError("pilot design must produce at least one sample")
    case = build_generation_case(
        config.geometry,
        config.measurements,
        first_design.fixed_jn,
        samples[0].joint_sets,
        case_id=first_design.design_id,
    )
    planned_locations = plan_measurement_locations(case)
    if not planned_locations:
        raise ValueError("pilot geometry produced no measurement locations")

    return build_frozen_manifest(
        config,
        manifest_id=manifest_id,
        runtime=runtime,
        boundary_rules_version=FACE_BOUNDARY_RULES_VERSION,
        planned_locations=planned_locations,
    )


def generate_and_measure(
    case: CaseSpec,
    factory: JointFactory,
    seed: int,
    *,
    progress_callback: Callable[[ProgressUpdate], None] | None = None,
) -> MeasurementResult:
    """Generate one DFN and measure it once; persistence, retry, and policy are separate."""
    if progress_callback is not None:
        progress_callback(ProgressUpdate("DFN generation", "starting DFN generation"))
    if progress_callback is None:
        joints = factory.generate(case, seed)
    else:
        joints = factory.generate(
            case,
            seed,
            progress_callback=progress_callback,
        )
    if progress_callback is not None:
        progress_callback(ProgressUpdate(
            "DFN generation",
            f"generation complete; joints={getattr(joints, 'count', 'unknown')}",
        ))
        progress_callback(ProgressUpdate(
            "Measurement",
            "starting BH interval and face station measurements",
        ))
    return measure_realization(
        case,
        joints,
        progress_callback=progress_callback,
    )


_PROGRESS_HEARTBEAT_SECONDS = 60.0


class _ProgressHeartbeat:
    def __init__(
        self,
        callback: Callable[[str], None] | None,
        context: str,
    ) -> None:
        self._callback = callback
        self._context = context
        self._stop = Event()
        self._lock = Lock()
        self._stage = "job"
        self._detail = "starting"
        self._completed: int | None = None
        self._total: int | None = None
        self._stage_started = monotonic()
        self._thread: Thread | None = None

    def __enter__(self) -> "_ProgressHeartbeat":
        if self._callback is not None:
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def update(self, update: ProgressUpdate) -> None:
        now = monotonic()
        with self._lock:
            if update.stage != self._stage:
                self._stage = update.stage
                self._stage_started = now
            self._detail = update.detail
            self._completed = update.completed
            self._total = update.total
            message = self._format(update, heartbeat=False, elapsed=0.0)
        if update.log and self._callback is not None:
            self._callback(message)

    def _run(self) -> None:
        while not self._stop.wait(_PROGRESS_HEARTBEAT_SECONDS):
            with self._lock:
                elapsed = max(0.0, monotonic() - self._stage_started)
                update = ProgressUpdate(
                    self._stage,
                    self._detail,
                    self._completed,
                    self._total,
                )
                message = self._format(update, heartbeat=True, elapsed=elapsed)
            if self._callback is not None:
                self._callback(message)

    def _format(
        self,
        update: ProgressUpdate,
        *,
        heartbeat: bool,
        elapsed: float,
    ) -> str:
        progress = (
            f" progress={update.completed}/{update.total}"
            if update.completed is not None and update.total is not None
            else ""
        )
        prefix = (
            f"heartbeat stage_elapsed={elapsed:.0f}s"
            if heartbeat
            else "progress"
        )
        return (
            f"{self._context} {prefix} stage={update.stage}"
            f"{progress}; {update.detail}"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z",
    )


def _job_identity(job: ExecutionJob) -> tuple[str, str, str, int, int]:
    return (
        job.manifest_id, job.design_id, job.block_id,
        job.sample_index, job.realization_seed,
    )


def _unpersisted_measurements(
    result: MeasurementResult,
    location_states: tuple[PlannedLocationState, ...],
) -> MeasurementResult:
    pending_keys = {
        (state.modality, state.profile_id, state.location_index)
        for state in location_states
        if state.status == "planned"
    }
    new_states = tuple(
        state for state in result.location_states
        if (state.modality, state.profile_id, state.location_index) in pending_keys
    )
    new_keys = {
        (state.modality, state.profile_id, state.location_index)
        for state in new_states
    }
    new_observations = tuple(
        observation for observation in result.observations
        if (
            "BH" if isinstance(observation, RawBHObservation) else "face",
            observation.profile_id,
            observation.location_index,
        ) in new_keys
    )
    return replace(
        result,
        location_states=new_states,
        observations=new_observations,
    )


def _case_for_job(config: NormalizedPilotInput, job: ExecutionJob) -> CaseSpec:
    case = build_generation_case(
        config.geometry,
        config.measurements,
        job.snapshot.fixed_jn,
        job.snapshot.joint_sets,
        case_id=job.design_id,
    )
    if (
        case.domain.jn != job.snapshot.fixed_jn
        or case.domain.grid_spacing != job.snapshot.geometry.grid_spacing_m
        or tuple(
            count * spacing
            for count, spacing in zip(
                case.domain.cell_counts, case.domain.grid_spacing,
            )
        ) != job.snapshot.geometry.domain_size_m
        or case.tunnel.vertices != job.snapshot.geometry.tunnel_vertices_m
        or case.tunnel.radius != job.snapshot.geometry.tunnel_radius_m
        or case.boreholes[0].start != job.snapshot.geometry.borehole_start_m
        or case.boreholes[0].direction != job.snapshot.geometry.borehole_direction_enu
        or case.boreholes[0].requested_length != job.snapshot.geometry.borehole_length_m
        or case.boreholes[0].interval_length != job.snapshot.measurements.bh_interval_m
        or config.measurements.face_advance_m != job.snapshot.measurements.face_advance_m
    ):
        raise ValueError("normalized config does not match the frozen execution snapshot")
    return case


def execute_frozen_jobs(
    connection: sqlite3.Connection,
    manifest: FrozenManifest,
    config: NormalizedPilotInput,
    factory: JointFactory,
    *,
    maximum_simulations: int,
    progress_callback: Callable[[str], None] | None = None,
) -> FrozenJobRunSummary:
    """Run pending frozen jobs and resume an interrupted attempt without repeating saved jobs."""
    if not isinstance(manifest, FrozenManifest):
        raise TypeError("manifest must be a FrozenManifest")
    if not isinstance(config, NormalizedPilotInput):
        raise TypeError("config must be a NormalizedPilotInput")
    if not callable(getattr(factory, "generate", None)):
        raise TypeError("factory must implement JointFactory")
    if isinstance(maximum_simulations, bool) or not isinstance(maximum_simulations, int):
        raise TypeError("maximum_simulations must be an integer")
    if maximum_simulations < 1:
        raise ValueError("maximum_simulations must be at least 1")

    completed: list[tuple[str, str, str, int, int]] = []
    skipped_completed: list[tuple[str, str, str, int, int]] = []
    skipped_failed: list[tuple[str, str, str, int, int]] = []
    simulation_count = 0
    termination_reason: Literal["jobs_complete", "budget_exhausted"] = "jobs_complete"

    job_total = len(manifest.jobs)
    for job_number, job in enumerate(manifest.jobs, start=1):
        identity = _job_identity(job)
        attempts = job_attempt_statuses(connection, job)
        succeeded = [index for index, status in attempts if status == "succeeded"]
        running = [(index, status) for index, status in attempts if status == "running"]
        failed = [(index, status) for index, status in attempts if status == "failed"]
        if succeeded and running:
            raise ValueError("job has both succeeded and running attempts; refusing ambiguous state")
        if succeeded:
            skipped_completed.append(identity)
            if progress_callback is not None:
                progress_callback(
                    f"[{job_number}/{job_total}] skip completed "
                    f"{job.design_id}/{job.block_id}/sample={job.sample_index}"
                )
            continue
        if running and failed:
            raise ValueError("job has both running and failed attempts; refusing ambiguous resume")
        if failed:
            skipped_failed.append(identity)
            if progress_callback is not None:
                progress_callback(
                    f"[{job_number}/{job_total}] skip failed attempt "
                    f"{job.design_id}/{job.block_id}/sample={job.sample_index}"
                )
            continue
        if simulation_count >= maximum_simulations:
            termination_reason = "budget_exhausted"
            if progress_callback is not None:
                progress_callback(
                    f"[{job_number}/{job_total}] budget exhausted; "
                    f"started {simulation_count}/{maximum_simulations} simulations"
                )
            break

        started_monotonic = monotonic()
        started_at_utc = _utc_now()
        case = _case_for_job(config, job)
        if running:
            resume_state = resume_attempt(connection, job)
            attempt_index = resume_state.attempt_index
            location_states = resume_state.location_states
            action = f"resume attempt={attempt_index}"
        else:
            attempt_index = 0
            planned_location_rows = connection.execute(
                """
                SELECT modality, profile_id, location_index
                FROM planned_locations
                WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                  AND sample_index = ? AND realization_seed = ?
                  AND execution_fingerprint_digest = ?
                ORDER BY modality, profile_id, location_index
                """,
                (
                    job.manifest_id, job.design_id, job.block_id, job.sample_index,
                    job.realization_seed, job.fingerprint.sha256_hex,
                ),
            ).fetchall()
            if not planned_location_rows:
                raise ValueError("execution job has no persisted planned locations")
            begin_attempt(connection, job, attempt_index, started_at_utc)
            location_states = tuple(
                PlannedLocationState(
                    modality, profile_id, location_index, "planned", None,
                )
                for modality, profile_id, location_index in planned_location_rows
            )
            action = f"start attempt={attempt_index}"

        simulation_count += 1
        job_started = monotonic()
        progress_context = (
            f"[{job_number}/{job_total}] {action} "
            f"{job.design_id}/{job.block_id}/sample={job.sample_index} "
            f"seed={job.realization_seed}; "
            f"simulation {simulation_count}/{maximum_simulations}"
        )
        with _ProgressHeartbeat(progress_callback, progress_context) as heartbeat:
            heartbeat.update(ProgressUpdate(
                "DFN generation",
                f"{len(location_states)} locations planned/pending",
            ))
            try:
                if progress_callback is None:
                    result = generate_and_measure(
                        case, factory, job.realization_seed,
                    )
                else:
                    result = generate_and_measure(
                        case,
                        factory,
                        job.realization_seed,
                        progress_callback=heartbeat.update,
                    )
                pending_result = _unpersisted_measurements(result, location_states)
                heartbeat.update(ProgressUpdate(
                    "Persistence",
                    f"persisting {len(pending_result.observations)} observations "
                    f"and {len(pending_result.location_states)} location states",
                ))
                complete_attempt(
                    connection,
                    job,
                    attempt_index,
                    pending_result,
                    finished_at_utc=_utc_now(),
                    runtime_seconds=max(0.0, monotonic() - started_monotonic),
                )
            except KeyboardInterrupt:
                checkpoint_attempt_runtime(
                    connection,
                    job,
                    attempt_index,
                    max(0.0, monotonic() - started_monotonic),
                )
                heartbeat.update(ProgressUpdate(
                    "Interruption",
                    f"[{job_number}/{job_total}] {job.design_id}/"
                    f"{job.block_id}/sample={job.sample_index}; "
                    "attempt checkpointed for resume",
                ))
                raise
            except Exception as error:
                try:
                    finish_attempt(
                        connection,
                        job,
                        attempt_index,
                        status="failed",
                        finished_at_utc=_utc_now(),
                        runtime_seconds=max(0.0, monotonic() - started_monotonic),
                    )
                except Exception as persistence_error:
                    raise ExceptionGroup(
                        "job execution and failure-state persistence both failed",
                        [error, persistence_error],
                    )
                heartbeat.update(ProgressUpdate(
                    "Failure",
                    f"[{job_number}/{job_total}] "
                    f"{job.design_id}/{job.block_id}/"
                    f"sample={job.sample_index}: {error}",
                ))
                raise
        completed.append(identity)
        if progress_callback is not None:
            progress_callback(
                f"[{job_number}/{job_total}] complete "
                f"{job.design_id}/{job.block_id}/sample={job.sample_index}; "
                f"elapsed={max(0.0, monotonic() - job_started):.1f}s; "
                f"observations={len(pending_result.observations)}"
            )

    return FrozenJobRunSummary(
        tuple(completed),
        tuple(skipped_completed),
        tuple(skipped_failed),
        simulation_count,
        maximum_simulations,
        termination_reason,
    )
