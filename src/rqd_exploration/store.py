"""SQLite schema and atomic persistence for the RQD exploration pilot."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import sqlite3
from typing import Generator

from .fingerprint import (
    EXECUTION_SCHEMA_VERSION,
    execution_snapshot_payload,
    fingerprint_execution_snapshot,
    fingerprint_snapshot,
)
from .measurement import (
    MeasurementResult,
    PlannedLocationState,
    RawBHObservation,
    RawFaceObservation,
)
from .records import ExecutionJob, FrozenManifest

STORE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ResumeAttemptState:
    attempt_index: int
    location_states: tuple[PlannedLocationState, ...]
    accumulated_runtime_seconds: float
    runtime_is_lower_bound: bool


_SCHEMA = (
    """
    CREATE TABLE manifest (
        manifest_id TEXT PRIMARY KEY NOT NULL,
        schema_version INTEGER NOT NULL CHECK (schema_version = 1),
        manifest_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE input_provenance (
        manifest_id TEXT PRIMARY KEY NOT NULL,
        yaml_bytes BLOB NOT NULL,
        yaml_sha256 TEXT NOT NULL CHECK (
            length(yaml_sha256) = 64 AND yaml_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        source_reference TEXT,
        FOREIGN KEY (manifest_id) REFERENCES manifest (manifest_id)
    )
    """,
    """
    CREATE TABLE design_samples (
        manifest_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL CHECK (sample_index >= 0),
        fixed_jn REAL NOT NULL CHECK (fixed_jn > 0),
        PRIMARY KEY (manifest_id, design_id, block_id, sample_index),
        FOREIGN KEY (manifest_id) REFERENCES manifest (manifest_id)
    )
    """,
    """
    CREATE TABLE target_goals (
        manifest_id TEXT NOT NULL,
        goal_id TEXT NOT NULL,
        target_bin_id TEXT NOT NULL,
        catalog_id TEXT NOT NULL,
        fixed_jn REAL NOT NULL CHECK (fixed_jn > 0),
        jr_scenario_id TEXT NOT NULL,
        jr_value REAL NOT NULL CHECK (jr_value > 0),
        ja_scenario_id TEXT NOT NULL,
        ja_value REAL NOT NULL CHECK (ja_value > 0),
        PRIMARY KEY (manifest_id, goal_id),
        FOREIGN KEY (manifest_id) REFERENCES manifest (manifest_id)
    )
    """,
    """
    CREATE TABLE jobs (
        manifest_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL
            CHECK (realization_seed BETWEEN -9007199254740991 AND 9007199254740991),
        execution_fingerprint_digest TEXT NOT NULL CHECK (
            length(execution_fingerprint_digest) = 64
            AND execution_fingerprint_digest NOT GLOB '*[^0-9a-f]*'
        ),
        execution_snapshot BLOB NOT NULL,
        PRIMARY KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest
        ),
        FOREIGN KEY (manifest_id, design_id, block_id, sample_index)
            REFERENCES design_samples (manifest_id, design_id, block_id, sample_index)
    )
    """,
    """
    CREATE TABLE planned_locations (
        manifest_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL,
        execution_fingerprint_digest TEXT NOT NULL,
        modality TEXT NOT NULL CHECK (modality IN ('BH', 'face')),
        profile_id TEXT NOT NULL,
        location_index INTEGER NOT NULL CHECK (location_index >= 0),
        location_json TEXT NOT NULL,
        PRIMARY KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, modality, profile_id, location_index
        ),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest
        ) REFERENCES jobs (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest
        )
    )
    """,
    """
    CREATE TABLE attempts (
        manifest_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL,
        execution_fingerprint_digest TEXT NOT NULL,
        attempt_index INTEGER NOT NULL CHECK (attempt_index >= 0),
        status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
        started_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        runtime_seconds REAL NOT NULL CHECK (
            runtime_seconds >= 0 AND runtime_seconds < 1.7976931348623157e308
        ),
        runtime_is_lower_bound INTEGER NOT NULL CHECK (runtime_is_lower_bound IN (0, 1)),
        PRIMARY KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index
        ),
        CHECK (
            (status = 'running' AND finished_at_utc IS NULL)
            OR
            (status IN ('succeeded', 'failed') AND finished_at_utc IS NOT NULL)
        ),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest
        ) REFERENCES jobs (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest
        )
    )
    """,
    """
    CREATE UNIQUE INDEX one_running_attempt_per_job
    ON attempts (
        manifest_id, design_id, block_id, sample_index, realization_seed,
        execution_fingerprint_digest
    )
    WHERE status = 'running'
    """,
    """
    CREATE TABLE location_status (
        manifest_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL,
        execution_fingerprint_digest TEXT NOT NULL,
        attempt_index INTEGER NOT NULL,
        modality TEXT NOT NULL CHECK (modality IN ('BH', 'face')),
        profile_id TEXT NOT NULL,
        location_index INTEGER NOT NULL CHECK (location_index >= 0),
        status TEXT NOT NULL CHECK (
            status IN ('planned', 'observed', 'unavailable', 'missing')
        ),
        reason TEXT,
        PRIMARY KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index
        ) REFERENCES attempts (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index
        ),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, modality, profile_id, location_index
        ) REFERENCES planned_locations (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, modality, profile_id, location_index
        )
    )
    """,
    """
    CREATE TABLE observations (
        manifest_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL,
        execution_fingerprint_digest TEXT NOT NULL,
        attempt_index INTEGER NOT NULL,
        modality TEXT NOT NULL CHECK (modality IN ('BH', 'face')),
        profile_id TEXT NOT NULL,
        location_index INTEGER NOT NULL,
        raw_rqd REAL NOT NULL CHECK (raw_rqd BETWEEN 0 AND 100),
        method_id TEXT NOT NULL,
        method_version TEXT NOT NULL,
        is_valid INTEGER NOT NULL CHECK (is_valid IN (0, 1)),
        exclusion_reason TEXT,
        zero_cross INTEGER NOT NULL CHECK (zero_cross IN (0, 1)),
        start_m REAL,
        end_m REAL,
        support_length_m REAL,
        chainage_m REAL,
        support_area_m2 REAL,
        advance_distance_m REAL,
        PRIMARY KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ),
        CHECK (
            (is_valid = 1 AND exclusion_reason IS NULL)
            OR (is_valid = 0 AND exclusion_reason IS NOT NULL)
        ),
        CHECK (
            (modality = 'BH' AND start_m IS NOT NULL AND end_m IS NOT NULL
                AND support_length_m IS NOT NULL AND support_length_m >= 0
                AND chainage_m IS NULL AND support_area_m2 IS NULL
                AND advance_distance_m IS NULL)
            OR
            (modality = 'face' AND start_m IS NULL AND end_m IS NULL
                AND support_length_m IS NULL AND chainage_m IS NOT NULL
                AND support_area_m2 IS NOT NULL AND support_area_m2 >= 0
                AND ((location_index = 0 AND advance_distance_m IS NULL)
                    OR (location_index > 0 AND advance_distance_m IS NOT NULL
                        AND advance_distance_m >= 0)))
        ),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ) REFERENCES location_status (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index
        ) REFERENCES attempts (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index
        )
    )
    """,
    """
    CREATE TABLE measurement_evidence (
        manifest_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL,
        execution_fingerprint_digest TEXT NOT NULL,
        attempt_index INTEGER NOT NULL,
        modality TEXT NOT NULL CHECK (modality IN ('BH', 'face')),
        profile_id TEXT NOT NULL,
        location_index INTEGER NOT NULL,
        scanline_index INTEGER NOT NULL CHECK (scanline_index >= 0),
        start_enu_json TEXT NOT NULL,
        direction_enu_json TEXT NOT NULL,
        measured_length_m REAL NOT NULL CHECK (measured_length_m >= 0),
        intersection_positions_json TEXT NOT NULL,
        PRIMARY KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index, scanline_index
        ),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ) REFERENCES observations (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        )
    )
    """,
    """
    CREATE TABLE dataset_revisions (
        manifest_id TEXT NOT NULL,
        revision_index INTEGER NOT NULL CHECK (revision_index > 0),
        previous_revision_index INTEGER,
        correction_reason TEXT,
        schema_version INTEGER NOT NULL CHECK (schema_version = 1),
        dataset_snapshot BLOB NOT NULL,
        dataset_sha256 TEXT NOT NULL CHECK (
            length(dataset_sha256) = 64 AND dataset_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        PRIMARY KEY (manifest_id, revision_index),
        CHECK (
            (revision_index = 1 AND previous_revision_index IS NULL
                AND correction_reason IS NULL)
            OR (revision_index > 1 AND previous_revision_index = revision_index - 1
                AND correction_reason IS NOT NULL)
        ),
        FOREIGN KEY (manifest_id) REFERENCES manifest (manifest_id),
        FOREIGN KEY (manifest_id, previous_revision_index)
            REFERENCES dataset_revisions (manifest_id, revision_index)
    )
    """,
    """
    CREATE TABLE analysis_runs (
        manifest_id TEXT NOT NULL,
        revision_index INTEGER NOT NULL,
        analysis_fingerprint_digest TEXT NOT NULL CHECK (
            length(analysis_fingerprint_digest) = 64
            AND analysis_fingerprint_digest NOT GLOB '*[^0-9a-f]*'
        ),
        schema_version INTEGER NOT NULL CHECK (schema_version = 1),
        analysis_snapshot BLOB NOT NULL,
        analysis_sha256 TEXT NOT NULL CHECK (
            length(analysis_sha256) = 64 AND analysis_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        dataset_sha256 TEXT NOT NULL CHECK (
            length(dataset_sha256) = 64 AND dataset_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        PRIMARY KEY (manifest_id, revision_index, analysis_fingerprint_digest),
        FOREIGN KEY (manifest_id, revision_index)
            REFERENCES dataset_revisions (manifest_id, revision_index)
    )
    """,
    """
    CREATE TABLE derived_scores (
        manifest_id TEXT NOT NULL,
        revision_index INTEGER NOT NULL,
        analysis_fingerprint_digest TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL,
        execution_fingerprint_digest TEXT NOT NULL,
        attempt_index INTEGER NOT NULL,
        modality TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        location_index INTEGER NOT NULL,
        jr_value REAL NOT NULL CHECK (jr_value > 0),
        ja_value REAL NOT NULL CHECK (ja_value > 0),
        fixed_jn REAL NOT NULL CHECK (fixed_jn > 0),
        calculation_rqd REAL NOT NULL CHECK (calculation_rqd BETWEEN 10 AND 100),
        qprime REAL NOT NULL CHECK (qprime >= 0),
        bin_id TEXT NOT NULL,
        zero_cross_convention TEXT NOT NULL,
        PRIMARY KEY (
            manifest_id, revision_index, analysis_fingerprint_digest, design_id,
            block_id, sample_index, realization_seed, execution_fingerprint_digest,
            attempt_index, modality, profile_id, location_index, jr_value, ja_value
        ),
        FOREIGN KEY (manifest_id, revision_index, analysis_fingerprint_digest)
            REFERENCES analysis_runs (
                manifest_id, revision_index, analysis_fingerprint_digest
            ),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ) REFERENCES observations (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        )
    )
    """,
    """
    CREATE TABLE goal_contributions (
        manifest_id TEXT NOT NULL,
        revision_index INTEGER NOT NULL,
        analysis_fingerprint_digest TEXT NOT NULL,
        goal_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        block_id TEXT NOT NULL,
        sample_index INTEGER NOT NULL,
        realization_seed INTEGER NOT NULL,
        execution_fingerprint_digest TEXT NOT NULL,
        attempt_index INTEGER NOT NULL,
        modality TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        location_index INTEGER NOT NULL,
        PRIMARY KEY (
            manifest_id, revision_index, analysis_fingerprint_digest, goal_id,
            design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ),
        FOREIGN KEY (manifest_id, revision_index, analysis_fingerprint_digest)
            REFERENCES analysis_runs (
                manifest_id, revision_index, analysis_fingerprint_digest
            ),
        FOREIGN KEY (manifest_id, goal_id)
            REFERENCES target_goals (manifest_id, goal_id),
        FOREIGN KEY (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        ) REFERENCES observations (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index
        )
    )
    """,
    """
    CREATE TRIGGER location_status_insert_observed_requires_observation
    BEFORE INSERT ON location_status
    WHEN NEW.status = 'observed'
    BEGIN
        SELECT RAISE(ABORT, 'insert observation before marking location observed');
    END
    """,
    """
    CREATE TRIGGER location_status_update_observed_requires_observation
    BEFORE UPDATE OF status ON location_status
    WHEN NEW.status = 'observed' AND NOT EXISTS (
        SELECT 1 FROM observations AS observation
        WHERE observation.manifest_id = NEW.manifest_id
          AND observation.design_id = NEW.design_id
          AND observation.block_id = NEW.block_id
          AND observation.sample_index = NEW.sample_index
          AND observation.realization_seed = NEW.realization_seed
          AND observation.execution_fingerprint_digest = NEW.execution_fingerprint_digest
          AND observation.attempt_index = NEW.attempt_index
          AND observation.modality = NEW.modality
          AND observation.profile_id = NEW.profile_id
          AND observation.location_index = NEW.location_index
    )
    BEGIN
        SELECT RAISE(ABORT, 'observed location must have a raw observation');
    END
    """,
    """
    CREATE TRIGGER location_status_update_preserves_observation
    BEFORE UPDATE OF status ON location_status
    WHEN OLD.status = 'observed' AND NEW.status <> 'observed' AND EXISTS (
        SELECT 1 FROM observations AS observation
        WHERE observation.manifest_id = OLD.manifest_id
          AND observation.design_id = OLD.design_id
          AND observation.block_id = OLD.block_id
          AND observation.sample_index = OLD.sample_index
          AND observation.realization_seed = OLD.realization_seed
          AND observation.execution_fingerprint_digest = OLD.execution_fingerprint_digest
          AND observation.attempt_index = OLD.attempt_index
          AND observation.modality = OLD.modality
          AND observation.profile_id = OLD.profile_id
          AND observation.location_index = OLD.location_index
    )
    BEGIN
        SELECT RAISE(ABORT, 'location with a raw observation must remain observed');
    END
    """,
    """
    CREATE TRIGGER observations_require_planned_status
    BEFORE INSERT ON observations
    WHEN NOT EXISTS (
        SELECT 1 FROM location_status AS status
        WHERE status.manifest_id = NEW.manifest_id
          AND status.design_id = NEW.design_id
          AND status.block_id = NEW.block_id
          AND status.sample_index = NEW.sample_index
          AND status.realization_seed = NEW.realization_seed
          AND status.execution_fingerprint_digest = NEW.execution_fingerprint_digest
          AND status.attempt_index = NEW.attempt_index
          AND status.modality = NEW.modality
          AND status.profile_id = NEW.profile_id
          AND status.location_index = NEW.location_index
          AND status.status = 'planned'
    )
    BEGIN
        SELECT RAISE(ABORT, 'insert a planned status before a raw observation');
    END
    """,
    """
    CREATE TRIGGER observations_set_location_observed
    AFTER INSERT ON observations
    BEGIN
        UPDATE location_status SET status = 'observed', reason = NULL
        WHERE manifest_id = NEW.manifest_id
          AND design_id = NEW.design_id
          AND block_id = NEW.block_id
          AND sample_index = NEW.sample_index
          AND realization_seed = NEW.realization_seed
          AND execution_fingerprint_digest = NEW.execution_fingerprint_digest
          AND attempt_index = NEW.attempt_index
          AND modality = NEW.modality
          AND profile_id = NEW.profile_id
          AND location_index = NEW.location_index
          AND status = 'planned';
    END
    """,
    """
    CREATE TRIGGER observations_delete_preserves_status
    BEFORE DELETE ON observations
    WHEN EXISTS (
        SELECT 1 FROM location_status AS status
        WHERE status.manifest_id = OLD.manifest_id
          AND status.design_id = OLD.design_id
          AND status.block_id = OLD.block_id
          AND status.sample_index = OLD.sample_index
          AND status.realization_seed = OLD.realization_seed
          AND status.execution_fingerprint_digest = OLD.execution_fingerprint_digest
          AND status.attempt_index = OLD.attempt_index
          AND status.modality = OLD.modality
          AND status.profile_id = OLD.profile_id
          AND status.location_index = OLD.location_index
          AND status.status = 'observed'
    )
    BEGIN
        SELECT RAISE(ABORT, 'delete observation only after changing its location status');
    END
    """,
)


@contextmanager
def _atomic(connection: sqlite3.Connection) -> Generator[None, None, None]:
    connection.execute("SAVEPOINT qsimex_store_write")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK TO qsimex_store_write")
        connection.execute("RELEASE qsimex_store_write")
        raise
    else:
        connection.execute("RELEASE qsimex_store_write")


def initialize_store(connection: sqlite3.Connection) -> None:
    """Create the version-1 schema on an explicitly supplied SQLite connection."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    if connection.in_transaction:
        raise RuntimeError("initialize_store requires a connection outside a transaction")
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("SQLite foreign-key enforcement is unavailable")
    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_version not in (0, STORE_SCHEMA_VERSION):
        raise ValueError(f"unsupported store schema version: {current_version}")
    if current_version == STORE_SCHEMA_VERSION:
        return
    with _atomic(connection):
        for statement in _SCHEMA:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {STORE_SCHEMA_VERSION}")


def _require_initialized_store(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("SQLite foreign-key enforcement must be enabled")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != STORE_SCHEMA_VERSION:
        raise RuntimeError(
            f"store schema version {STORE_SCHEMA_VERSION} required; found {version}"
        )


def store_manifest(connection: sqlite3.Connection, manifest: FrozenManifest) -> None:
    """Atomically persist an immutable frozen manifest and its FK projections."""
    _require_initialized_store(connection)
    if not isinstance(manifest, FrozenManifest):
        raise TypeError("manifest must be a FrozenManifest")
    try:
        payload = json.loads(manifest.manifest_json)
    except json.JSONDecodeError as error:
        raise ValueError("manifest_json is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("manifest_json must contain a JSON object")
    if fingerprint_snapshot(payload).canonical_bytes.decode("utf-8") != manifest.manifest_json:
        raise ValueError("manifest_json is not RFC 8785 canonical JSON")
    if payload.get("schema_version") != EXECUTION_SCHEMA_VERSION:
        raise ValueError("unsupported manifest payload schema version")
    if payload.get("manifest_id") != manifest.manifest_id:
        raise ValueError("manifest_id does not match the frozen payload")
    if sha256(manifest.source_yaml_bytes).hexdigest() != manifest.source_yaml_sha256:
        raise ValueError("source YAML digest does not match its exact bytes")
    provenance = payload.get("input_provenance")
    if not isinstance(provenance, dict) or (
        provenance.get("yaml_sha256") != manifest.source_yaml_sha256
        or provenance.get("source_reference") != manifest.source_reference
    ):
        raise ValueError("manifest provenance does not match the frozen payload")

    collections = (
        payload.get("design_samples"), payload.get("target_goals"),
        payload.get("jobs"), payload.get("planned_locations"),
    )
    if not all(isinstance(value, list) for value in collections):
        raise ValueError("manifest projection collections must be JSON arrays")
    samples, goals, payload_jobs, locations = collections
    typed_jobs = {
        (
            job.manifest_id, job.design_id, job.block_id, job.sample_index,
            job.realization_seed, job.fingerprint.sha256_hex,
        ): job
        for job in manifest.jobs
    }
    if len(typed_jobs) != len(manifest.jobs) or len(payload_jobs) != len(typed_jobs):
        raise ValueError("manifest jobs do not match unique typed execution jobs")
    seen_job_keys: set[tuple[str, str, str, int, int, str]] = set()
    for row in payload_jobs:
        if not isinstance(row, dict):
            raise ValueError("manifest job payload must be an object")
        key = (
            row.get("manifest_id"), row.get("design_id"), row.get("block_id"),
            row.get("sample_index"), row.get("realization_seed"),
            row.get("execution_fingerprint_digest"),
        )
        job = typed_jobs.get(key)
        if job is None or key in seen_job_keys:
            raise ValueError("manifest job key is missing, duplicated, or inconsistent")
        seen_job_keys.add(key)
        expected_snapshot = json.loads(json.dumps(
            execution_snapshot_payload(job.snapshot),
        ))
        if row.get("execution_snapshot") != expected_snapshot:
            raise ValueError("manifest execution snapshot does not match typed job")
        if fingerprint_execution_snapshot(job.snapshot) != job.fingerprint:
            raise ValueError("typed job execution fingerprint is invalid")

    with _atomic(connection):
        connection.execute(
            "INSERT INTO manifest VALUES (?, ?, ?)",
            (manifest.manifest_id, payload["schema_version"], manifest.manifest_json),
        )
        connection.execute(
            "INSERT INTO input_provenance VALUES (?, ?, ?, ?)",
            (
                manifest.manifest_id, manifest.source_yaml_bytes,
                manifest.source_yaml_sha256, manifest.source_reference,
            ),
        )
        for sample in samples:
            if not isinstance(sample, dict) or sample.get("manifest_id") != manifest.manifest_id:
                raise ValueError("design sample has an invalid manifest reference")
            connection.execute(
                "INSERT INTO design_samples VALUES (?, ?, ?, ?, ?)",
                (
                    sample["manifest_id"], sample["design_id"], sample["block_id"],
                    sample["sample_index"], sample["fixed_jn"],
                ),
            )
        for item in goals:
            if not isinstance(item, dict) or item.get("manifest_id") != manifest.manifest_id:
                raise ValueError("target goal has an invalid manifest reference")
            connection.execute(
                "INSERT INTO target_goals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["manifest_id"], item["goal_id"], item["target_bin_id"],
                    item["catalog_id"], item["fixed_jn"], item["jr_scenario_id"],
                    item["jr_value"], item["ja_scenario_id"], item["ja_value"],
                ),
            )
        for row in payload_jobs:
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row["manifest_id"], row["design_id"], row["block_id"],
                    row["sample_index"], row["realization_seed"],
                    row["execution_fingerprint_digest"],
                    fingerprint_snapshot(row["execution_snapshot"]).canonical_bytes,
                ),
            )
        for item in locations:
            if not isinstance(item, dict) or item.get("manifest_id") != manifest.manifest_id:
                raise ValueError("planned location has an invalid manifest reference")
            modality = item.get("modality")
            if modality not in ("BH", "face"):
                raise ValueError("planned location has an invalid modality")
            connection.execute(
                "INSERT INTO planned_locations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["manifest_id"], item["design_id"], item["block_id"],
                    item["sample_index"], item["realization_seed"],
                    item["execution_fingerprint_digest"], modality,
                    item["profile_id"], item["location_index"],
                    fingerprint_snapshot(item).canonical_bytes.decode("utf-8"),
                ),
            )


def _job_key(job: ExecutionJob) -> tuple[str, str, str, int, int, str]:
    if not isinstance(job, ExecutionJob):
        raise TypeError("job must be an ExecutionJob")
    if job.fingerprint != fingerprint_execution_snapshot(job.snapshot):
        raise ValueError("execution job fingerprint does not match its snapshot")
    return (
        job.manifest_id, job.design_id, job.block_id, job.sample_index,
        job.realization_seed, job.fingerprint.sha256_hex,
    )


def _validate_utc_timestamp(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{name} must be an RFC 3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{name} must be an RFC 3339 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{name} must use UTC")


def begin_attempt(
    connection: sqlite3.Connection,
    job: ExecutionJob,
    attempt_index: int,
    started_at_utc: str,
) -> None:
    """Create a running attempt and its per-location planned states atomically."""
    _require_initialized_store(connection)
    if isinstance(attempt_index, bool) or not isinstance(attempt_index, int) or attempt_index < 0:
        raise ValueError("attempt_index must be a non-negative integer")
    _validate_utc_timestamp(started_at_utc, "started_at_utc")
    job_key = _job_key(job)
    with _atomic(connection):
        connection.execute(
            """
            INSERT INTO attempts (
                manifest_id, design_id, block_id, sample_index, realization_seed,
                execution_fingerprint_digest, attempt_index, status, started_at_utc,
                finished_at_utc, runtime_seconds, runtime_is_lower_bound
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, NULL, 0, 0)
            """,
            (*job_key, attempt_index, started_at_utc),
        )
        connection.execute(
            """
            INSERT INTO location_status (
                manifest_id, design_id, block_id, sample_index, realization_seed,
                execution_fingerprint_digest, attempt_index, modality, profile_id,
                location_index, status, reason
            )
            SELECT manifest_id, design_id, block_id, sample_index, realization_seed,
                   execution_fingerprint_digest, ?, modality, profile_id,
                   location_index, 'planned', NULL
            FROM planned_locations
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ?
            """,
            (attempt_index, *job_key),
        )
        if connection.execute("SELECT changes()").fetchone()[0] == 0:
            raise ValueError("execution job has no persisted planned locations")


def resume_attempt(
    connection: sqlite3.Connection,
    job: ExecutionJob,
) -> ResumeAttemptState:
    """Recover the one running attempt after verifying its frozen execution fingerprint."""
    _require_initialized_store(connection)
    job_key = _job_key(job)
    base_key = job_key[:5]
    expected_snapshot = job.fingerprint.canonical_bytes
    with _atomic(connection):
        persisted_jobs = connection.execute(
            """
            SELECT execution_fingerprint_digest, execution_snapshot FROM jobs
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
            """,
            base_key,
        ).fetchall()
        if len(persisted_jobs) != 1:
            raise ValueError("persisted execution job is missing or ambiguous")
        persisted_digest, persisted_snapshot = persisted_jobs[0]
        if (
            persisted_digest != job_key[-1]
            or persisted_snapshot != expected_snapshot
        ):
            raise ValueError("execution fingerprint does not match the persisted job")

        running_attempts = connection.execute(
            """
            SELECT attempt_index, runtime_seconds
            FROM attempts
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND status = 'running'
            ORDER BY attempt_index
            """,
            job_key,
        ).fetchall()
        if len(running_attempts) != 1:
            raise ValueError("exactly one running attempt is required to resume")
        attempt_index, runtime_seconds = running_attempts[0]

        planned_locations = connection.execute(
            """
            SELECT modality, profile_id, location_index FROM planned_locations
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ?
            ORDER BY modality, profile_id, location_index
            """,
            job_key,
        ).fetchall()
        stored_locations = connection.execute(
            """
            SELECT modality, profile_id, location_index, status, reason
            FROM location_status
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
            ORDER BY modality, profile_id, location_index
            """,
            (*job_key, attempt_index),
        ).fetchall()
        if len(planned_locations) != len(stored_locations) or {
            row[:3] for row in planned_locations
        } != {row[:3] for row in stored_locations}:
            raise ValueError("attempt location state does not match the frozen plan")

        location_states: list[PlannedLocationState] = []
        for modality, profile_id, location_index, status, reason in stored_locations:
            if modality not in ("BH", "face"):
                raise ValueError("attempt contains an invalid location modality")
            if status not in ("planned", "observed", "unavailable", "missing"):
                raise ValueError("attempt contains an invalid location status")
            location_states.append(PlannedLocationState(
                modality, profile_id, location_index, status, reason,
            ))

        connection.execute(
            """
            UPDATE attempts SET runtime_is_lower_bound = 1
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
              AND status = 'running'
            """,
            (*job_key, attempt_index),
        )

    return ResumeAttemptState(
        attempt_index=attempt_index,
        location_states=tuple(location_states),
        accumulated_runtime_seconds=runtime_seconds,
        runtime_is_lower_bound=True,
    )


def job_attempt_statuses(
    connection: sqlite3.Connection,
    job: ExecutionJob,
) -> tuple[tuple[int, str], ...]:
    """Return attempts for one persisted job after validating its exact frozen snapshot."""
    _require_initialized_store(connection)
    job_key = _job_key(job)
    persisted_jobs = connection.execute(
        """
        SELECT execution_fingerprint_digest, execution_snapshot FROM jobs
        WHERE manifest_id = ? AND design_id = ? AND block_id = ?
          AND sample_index = ? AND realization_seed = ?
        """,
        job_key[:5],
    ).fetchall()
    if len(persisted_jobs) != 1:
        raise ValueError("persisted execution job is missing or ambiguous")
    persisted_digest, persisted_snapshot = persisted_jobs[0]
    if (
        persisted_digest != job_key[-1]
        or persisted_snapshot != job.fingerprint.canonical_bytes
    ):
        raise ValueError("execution fingerprint does not match the persisted job")
    attempts = connection.execute(
        """
        SELECT attempt_index, status FROM attempts
        WHERE manifest_id = ? AND design_id = ? AND block_id = ?
          AND sample_index = ? AND realization_seed = ?
          AND execution_fingerprint_digest = ?
        ORDER BY attempt_index
        """,
        job_key,
    ).fetchall()
    return tuple((attempt_index, status) for attempt_index, status in attempts)


def _json_text(value: object, name: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be finite JSON data") from error


def _finite_number(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def record_measurement_result(
    connection: sqlite3.Connection,
    job: ExecutionJob,
    attempt_index: int,
    result: MeasurementResult,
) -> None:
    """Persist a measurement batch without discarding earlier committed batches."""
    _require_initialized_store(connection)
    if not isinstance(result, MeasurementResult):
        raise TypeError("result must be a MeasurementResult")
    job_key = _job_key(job)
    if (
        isinstance(attempt_index, bool)
        or not isinstance(attempt_index, int)
        or attempt_index < 0
    ):
        raise ValueError("attempt_index must be a non-negative integer")
    states = {
        (state.modality, state.profile_id, state.location_index): state
        for state in result.location_states
    }
    if len(states) != len(result.location_states):
        raise ValueError("measurement result contains duplicate location states")
    observations: dict[
        tuple[str, str, int], RawBHObservation | RawFaceObservation
    ] = {}
    for observation in result.observations:
        modality = "BH" if isinstance(observation, RawBHObservation) else "face"
        key = (modality, observation.profile_id, observation.location_index)
        if key in observations:
            raise ValueError("measurement result contains duplicate observations")
        if states.get(key) is None or states[key].status != "observed":
            raise ValueError("each observation must have a matching observed status")
        observations[key] = observation
    for key, state in states.items():
        if state.status == "observed" and key not in observations:
            raise ValueError("observed location status has no raw observation")
        if state.status not in ("observed", "unavailable", "missing"):
            raise ValueError(f"unsupported measurement result status: {state.status}")

    with _atomic(connection):
        attempt = connection.execute(
            """
            SELECT status FROM attempts
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
            """,
            (*job_key, attempt_index),
        ).fetchone()
        if attempt is None:
            raise ValueError("attempt does not exist")
        if attempt[0] != "running":
            raise ValueError(
                "measurement results can only be recorded for a running attempt"
            )
        for key, state in states.items():
            modality, profile_id, location_index = key
            observation = observations.get(key)
            if observation is not None:
                status = connection.execute(
                    """
                    SELECT status FROM location_status
                    WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                      AND sample_index = ? AND realization_seed = ?
                      AND execution_fingerprint_digest = ? AND attempt_index = ?
                      AND modality = ? AND profile_id = ? AND location_index = ?
                    """,
                    (*job_key, attempt_index, modality, profile_id, location_index),
                ).fetchone()
                if status is None or status[0] != "planned":
                    raise ValueError(
                        "planned location state is missing or already finalized"
                    )
                _insert_observation(
                    connection, job_key, attempt_index, modality, observation,
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE location_status SET status = ?, reason = ?
                    WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                      AND sample_index = ? AND realization_seed = ?
                      AND execution_fingerprint_digest = ? AND attempt_index = ?
                      AND modality = ? AND profile_id = ? AND location_index = ?
                      AND status = 'planned'
                    """,
                    (
                        state.status, state.reason, *job_key, attempt_index,
                        modality, profile_id, location_index,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "planned location state is missing or already finalized"
                    )


def _insert_observation(
    connection: sqlite3.Connection,
    job_key: tuple[str, str, str, int, int, str],
    attempt_index: int,
    modality: str,
    observation: RawBHObservation | RawFaceObservation,
) -> None:
    for name, value in (
        ("raw_rqd", observation.raw_rqd),
        ("support_length_m", observation.support_length_m)
        if isinstance(observation, RawBHObservation)
        else ("support_area_m2", observation.support_area_m2),
    ):
        _finite_number(value, name)
    if isinstance(observation, RawBHObservation):
        _finite_number(observation.start_m, "start_m")
        _finite_number(observation.end_m, "end_m")
        fields = (
            observation.start_m, observation.end_m, observation.support_length_m,
            None, None, None,
        )
        evidence = (observation.evidence,)
    else:
        _finite_number(observation.chainage_m, "chainage_m")
        if observation.advance_distance_m is not None:
            _finite_number(observation.advance_distance_m, "advance_distance_m")
        fields = (
            None, None, None, observation.chainage_m, observation.support_area_m2,
            observation.advance_distance_m,
        )
        evidence = observation.evidence
    connection.execute(
        """
        INSERT INTO observations (
            manifest_id, design_id, block_id, sample_index, realization_seed,
            execution_fingerprint_digest, attempt_index, modality, profile_id,
            location_index, raw_rqd, method_id, method_version, is_valid,
            exclusion_reason, zero_cross, start_m, end_m, support_length_m,
            chainage_m, support_area_m2, advance_distance_m
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            *job_key, attempt_index, modality, observation.profile_id,
            observation.location_index, observation.raw_rqd, observation.method_id,
            observation.method_version, int(observation.is_valid),
            observation.exclusion_reason, int(observation.zero_cross), *fields,
        ),
    )
    for item in evidence:
        _finite_number(item.length_m, "evidence length")
        if tuple(sorted(item.intersection_positions_m)) != item.intersection_positions_m:
            raise ValueError("evidence intersections must be sorted")
        connection.execute(
            """
            INSERT INTO measurement_evidence (
                manifest_id, design_id, block_id, sample_index, realization_seed,
                execution_fingerprint_digest, attempt_index, modality, profile_id,
                location_index, scanline_index, start_enu_json, direction_enu_json,
                measured_length_m, intersection_positions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                *job_key, attempt_index, modality, observation.profile_id,
                observation.location_index, item.scanline_index,
                _json_text(item.start_enu_m, "evidence start"),
                _json_text(item.direction_enu, "evidence direction"),
                item.length_m,
                _json_text(item.intersection_positions_m, "evidence intersections"),
            ),
        )


def _validated_runtime_seconds(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite non-negative number")
    if not math.isfinite(value) or not 0 <= value < 1.7976931348623157e308:
        raise ValueError(f"{name} must be finite, non-negative, and in range")
    return float(value)


def checkpoint_attempt_runtime(
    connection: sqlite3.Connection,
    job: ExecutionJob,
    attempt_index: int,
    elapsed_seconds: float,
) -> None:
    """Add one measured active-time segment to a running attempt's durable lower bound."""
    _require_initialized_store(connection)
    if isinstance(attempt_index, bool) or not isinstance(attempt_index, int) or attempt_index < 0:
        raise ValueError("attempt_index must be a non-negative integer")
    elapsed = _validated_runtime_seconds(elapsed_seconds, "elapsed_seconds")
    job_key = _job_key(job)
    with _atomic(connection):
        attempt = connection.execute(
            """
            SELECT runtime_seconds FROM attempts
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
              AND status = 'running'
            """,
            (*job_key, attempt_index),
        ).fetchone()
        if attempt is None:
            raise ValueError("running attempt does not exist")
        total_runtime = float(attempt[0]) + elapsed
        if not math.isfinite(total_runtime):
            raise ValueError("accumulated runtime must be finite")
        connection.execute(
            """
            UPDATE attempts SET runtime_seconds = ?
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
              AND status = 'running'
            """,
            (total_runtime, *job_key, attempt_index),
        )


def finish_attempt(
    connection: sqlite3.Connection,
    job: ExecutionJob,
    attempt_index: int,
    *,
    status: str,
    finished_at_utc: str,
    runtime_seconds: float,
) -> None:
    """Set a terminal state and add the final measured active-time segment."""
    _require_initialized_store(connection)
    if status not in ("succeeded", "failed"):
        raise ValueError("terminal attempt status must be succeeded or failed")
    _validate_utc_timestamp(finished_at_utc, "finished_at_utc")
    if isinstance(attempt_index, bool) or not isinstance(attempt_index, int) or attempt_index < 0:
        raise ValueError("attempt_index must be a non-negative integer")
    final_segment_seconds = _validated_runtime_seconds(
        runtime_seconds, "runtime_seconds",
    )
    job_key = _job_key(job)
    with _atomic(connection):
        attempt = connection.execute(
            """
            SELECT runtime_seconds FROM attempts
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
              AND status = 'running'
            """,
            (*job_key, attempt_index),
        ).fetchone()
        if attempt is None:
            raise ValueError("running attempt does not exist or is already terminal")
        total_runtime = float(attempt[0]) + final_segment_seconds
        if not math.isfinite(total_runtime):
            raise ValueError("accumulated runtime must be finite")
        if status == "succeeded":
            planned_count = connection.execute(
                """
                SELECT COUNT(*) FROM planned_locations
                WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                  AND sample_index = ? AND realization_seed = ?
                  AND execution_fingerprint_digest = ?
                """,
                job_key,
            ).fetchone()[0]
            state_count = connection.execute(
                """
                SELECT COUNT(*) FROM location_status
                WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                  AND sample_index = ? AND realization_seed = ?
                  AND execution_fingerprint_digest = ? AND attempt_index = ?
                """,
                (*job_key, attempt_index),
            ).fetchone()[0]
            pending_count = connection.execute(
                """
                SELECT COUNT(*) FROM location_status
                WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                  AND sample_index = ? AND realization_seed = ?
                  AND execution_fingerprint_digest = ? AND attempt_index = ?
                  AND status = 'planned'
                """,
                (*job_key, attempt_index),
            ).fetchone()[0]
            if planned_count != state_count:
                raise ValueError("attempt location state does not match the frozen plan")
            if pending_count:
                raise ValueError("succeeded attempt cannot contain planned locations")
        cursor = connection.execute(
            """
            UPDATE attempts SET status = ?, finished_at_utc = ?, runtime_seconds = ?
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
              AND status = 'running'
            """,
            (
                status, finished_at_utc, total_runtime, *job_key,
                attempt_index,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("running attempt does not exist or is already terminal")


def complete_attempt(
    connection: sqlite3.Connection,
    job: ExecutionJob,
    attempt_index: int,
    result: MeasurementResult,
    *,
    finished_at_utc: str,
    runtime_seconds: float,
) -> None:
    """Atomically persist the final result batch and mark the attempt succeeded."""
    _require_initialized_store(connection)
    with _atomic(connection):
        record_measurement_result(connection, job, attempt_index, result)
        finish_attempt(
            connection,
            job,
            attempt_index,
            status="succeeded",
            finished_at_utc=finished_at_utc,
            runtime_seconds=runtime_seconds,
        )
