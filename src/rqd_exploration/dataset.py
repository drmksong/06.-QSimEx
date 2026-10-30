"""Immutable raw-dataset revisions loaded from the SQLite pilot store."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Literal, cast

from .analysis import (
    AnalysisLocationStatus,
    AnalysisObservation,
    Modality,
    RAW_DATASET_SCHEMA_VERSION,
    ZERO_CROSS_CONVENTION,
    build_cumulative_analysis_snapshot,
    calculate_scenario_scores,
    fingerprint_raw_dataset,
)
from .fingerprint import JsonValue, SnapshotFingerprint, fingerprint_snapshot
from .store import _require_initialized_store

_LOCATION_KEY = (
    "design_id", "block_id", "sample_index", "realization_seed",
    "modality", "profile_id", "location_index",
)
CUMULATIVE_DATASET_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RawDatasetRevision:
    manifest_id: str
    revision_index: int
    dataset_sha256: str
    dataset_snapshot: dict[str, JsonValue]
    observations: tuple[AnalysisObservation, ...]
    location_states: tuple[AnalysisLocationStatus, ...]
    source_attempt_indices: tuple[tuple[tuple[object, ...], int], ...]


@dataclass(frozen=True)
class CumulativeRawDatasetRevision:
    revision_index: int
    previous_revision_index: int | None
    dataset_sha256: str
    dataset_snapshot: dict[str, JsonValue]
    manifest_ids: tuple[str, ...]
    observations: tuple[AnalysisObservation, ...]
    location_states: tuple[AnalysisLocationStatus, ...]
    source_attempt_indices: tuple[tuple[tuple[object, ...], int], ...]
    independent_execution_fingerprints: tuple[str, ...]
    raw_attempt_count: int
    raw_observation_count: int

    @property
    def independent_realization_count(self) -> int:
        return len(self.independent_execution_fingerprints)


def _observation_source_key(observation: AnalysisObservation) -> tuple[object, ...]:
    return (
        observation.design_id,
        observation.block_id,
        observation.sample_index,
        observation.realization_seed,
        observation.execution_fingerprint_digest,
        observation.modality,
        observation.profile_id,
        observation.location_index,
    )


def _decode_json(value: bytes | str, name: str) -> object:
    try:
        return json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} must contain valid UTF-8 JSON") from error


def _required_object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a JSON object with text keys")
    return value


def _required_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return value


def _json_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _integer(value: object, name: str, *, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _modality(value: object, name: str = "modality") -> Modality:
    if value not in ("BH", "face"):
        raise ValueError(f"{name} must be 'BH' or 'face'")
    return value


LocationState = Literal["planned", "observed", "unavailable", "missing"]


def _status(value: object) -> LocationState:
    if value == "planned":
        return "planned"
    if value == "observed":
        return "observed"
    if value == "unavailable":
        return "unavailable"
    if value == "missing":
        return "missing"
    raise ValueError("raw dataset contains an invalid location status")


def _json_number_array(value: object, name: str) -> tuple[float, ...]:
    return tuple(_number(item, name) for item in _required_list(value, name))


def _key_from_snapshot(record: dict[str, object]) -> tuple[object, ...]:
    try:
        return tuple(record[name] for name in _LOCATION_KEY)
    except KeyError as error:
        raise ValueError(f"raw dataset record is missing {error.args[0]!r}") from error


def _build_current_snapshot(
    connection: sqlite3.Connection,
    manifest_id: str,
) -> tuple[dict[str, JsonValue], tuple[AnalysisLocationStatus, ...],
           tuple[AnalysisObservation, ...], tuple[tuple[tuple[object, ...], int], ...]]:
    manifest = connection.execute(
        "SELECT manifest_json FROM manifest WHERE manifest_id = ?",
        (manifest_id,),
    ).fetchone()
    if manifest is None:
        raise ValueError(f"manifest {manifest_id!r} is not present in the database")
    manifest_payload = _required_object(
        _decode_json(manifest[0], "manifest_json"),
        "manifest_json",
    )
    if manifest_payload.get("manifest_id") != manifest_id:
        raise ValueError("stored manifest payload has a mismatched manifest_id")

    sample_rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, fixed_jn
        FROM design_samples
        WHERE manifest_id = ?
        ORDER BY design_id, block_id, sample_index
        """,
        (manifest_id,),
    ).fetchall()
    fixed_jn_by_sample = {
        (row[0], row[1], row[2]): float(row[3]) for row in sample_rows
    }

    job_rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, execution_snapshot
        FROM jobs
        WHERE manifest_id = ?
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest
        """,
        (manifest_id,),
    ).fetchall()
    job_details: dict[tuple[object, ...], tuple[str, tuple[tuple[str, float], ...]]] = {}
    for row in job_rows:
        job_key = (row[0], row[1], row[2], row[3], row[4])
        payload = _required_object(
            _decode_json(row[5], "jobs.execution_snapshot"),
            "jobs.execution_snapshot",
        )
        inputs = _required_object(payload.get("inputs"), "execution_snapshot.inputs")
        dfn = _required_object(inputs.get("dfn"), "execution_snapshot.inputs.dfn")
        joint_sets = _required_list(
            dfn.get("joint_sets"),
            "execution_snapshot.inputs.dfn.joint_sets",
        )
        p32_values = tuple(sorted(
            (
                _json_text(item.get("joint_set_id"), "joint_set_id"),
                _number(item.get("p32_m2_per_m3"), "p32_m2_per_m3"),
            )
            for value in joint_sets
            for item in (_required_object(value, "joint_set"),)
        ))
        job_details[job_key] = (row[4], p32_values)

    attempt_rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, MAX(attempt_index)
        FROM attempts
        WHERE manifest_id = ? AND status = 'succeeded'
        GROUP BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest
        """,
        (manifest_id,),
    ).fetchall()
    succeeded_attempts = {
        tuple(row[:5]): int(row[5]) for row in attempt_rows
    }

    planned_rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, modality, profile_id, location_index,
               location_json
        FROM planned_locations
        WHERE manifest_id = ?
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest, modality, profile_id, location_index
        """,
        (manifest_id,),
    ).fetchall()
    statuses: list[AnalysisLocationStatus] = []
    observations: list[AnalysisObservation] = []
    source_attempt_indices: list[tuple[tuple[object, ...], int]] = []
    location_snapshot: list[JsonValue] = []
    observation_snapshot: list[JsonValue] = []
    evidence_snapshot: list[JsonValue] = []

    for row in planned_rows:
        design_id = _json_text(row[0], "planned location design_id")
        block_id = _json_text(row[1], "planned location block_id")
        sample_index = _integer(row[2], "planned location sample_index", nonnegative=True)
        seed = _integer(row[3], "planned location realization_seed")
        digest = _json_text(row[4], "planned location execution fingerprint")
        modality = _modality(row[5])
        profile = _json_text(row[6], "planned location profile_id")
        index = _integer(row[7], "planned location location_index", nonnegative=True)
        location_json = row[8]
        job_key = (design_id, block_id, sample_index, seed, digest)
        if job_key not in job_details:
            raise ValueError("planned location references a missing execution job")
        location_payload = _required_object(
            _decode_json(location_json, "planned_locations.location_json"),
            "planned_locations.location_json",
        )
        if (
            location_payload.get("manifest_id") != manifest_id
            or location_payload.get("design_id") != design_id
            or location_payload.get("block_id") != block_id
            or location_payload.get("sample_index") != sample_index
            or location_payload.get("realization_seed") != seed
            or location_payload.get("execution_fingerprint_digest") != digest
            or location_payload.get("modality") != modality
            or location_payload.get("profile_id") != profile
            or location_payload.get("location_index") != index
        ):
            raise ValueError("planned location projection does not match its stored JSON")

        attempt_index = succeeded_attempts.get(job_key)
        status_value = "planned"
        reason = None
        observation_row: tuple[object, ...] | None = None
        if attempt_index is not None:
            state = connection.execute(
                """
                SELECT status, reason FROM location_status
                WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                  AND sample_index = ? AND realization_seed = ?
                  AND execution_fingerprint_digest = ? AND attempt_index = ?
                  AND modality = ? AND profile_id = ? AND location_index = ?
                """,
                (manifest_id, design_id, block_id, sample_index, seed, digest,
                 attempt_index, modality, profile, index),
            ).fetchone()
            if state is None:
                raise ValueError(
                    "highest successful attempt is missing a planned location state"
                )
            status_value, raw_reason = state
            status_value = _status(status_value)
            if raw_reason is not None and not isinstance(raw_reason, str):
                raise ValueError("stored location-state reason must be text or NULL")
            reason = raw_reason
            if status_value == "observed":
                observation_row = connection.execute(
                    """
                    SELECT raw_rqd, method_id, method_version, is_valid,
                           exclusion_reason, zero_cross, support_length_m,
                           support_area_m2
                    FROM observations
                    WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                      AND sample_index = ? AND realization_seed = ?
                      AND execution_fingerprint_digest = ? AND attempt_index = ?
                      AND modality = ? AND profile_id = ? AND location_index = ?
                    """,
                    (manifest_id, design_id, block_id, sample_index, seed, digest,
                     attempt_index, modality, profile, index),
                ).fetchone()
                if observation_row is None:
                    raise ValueError("observed location has no raw observation row")

        location_key: dict[str, JsonValue] = {
            "design_id": design_id,
            "block_id": block_id,
            "sample_index": sample_index,
            "realization_seed": seed,
            "modality": modality,
            "profile_id": profile,
            "location_index": index,
        }
        location_snapshot.append({
            **location_key,
            "status": status_value,
            "reason": reason,
        })
        statuses.append(AnalysisLocationStatus(
            manifest_id=manifest_id,
            design_id=design_id,
            block_id=block_id,
            sample_index=sample_index,
            realization_seed=seed,
            execution_fingerprint_digest=digest,
            modality=modality,
            profile_id=profile,
            location_index=index,
            status=status_value,
            reason=reason,
        ))
        if observation_row is None:
            continue

        fixed_jn = fixed_jn_by_sample.get((design_id, block_id, sample_index))
        if fixed_jn is None:
            raise ValueError("observation design sample has no fixed Jn")
        p32_by_joint_set = job_details[job_key][1] if modality == "BH" else ()
        raw_rqd, method_id, method_version, is_valid, exclusion_reason, zero_cross, support_m, support_m2 = observation_row
        raw_rqd_value = _number(raw_rqd, "observations.raw_rqd")
        if not isinstance(method_id, str) or not method_id.strip():
            raise ValueError("observations.method_id must be non-empty text")
        if not isinstance(method_version, str) or not method_version.strip():
            raise ValueError("observations.method_version must be non-empty text")
        if is_valid not in (0, 1):
            raise ValueError("observations.is_valid must be 0 or 1")
        if zero_cross not in (0, 1):
            raise ValueError("observations.zero_cross must be 0 or 1")
        if exclusion_reason is not None and not isinstance(exclusion_reason, str):
            raise ValueError("observations.exclusion_reason must be text or NULL")
        support_length = (
            _number(support_m, "observations.support_length_m")
            if support_m is not None else None
        )
        support_area = (
            _number(support_m2, "observations.support_area_m2")
            if support_m2 is not None else None
        )
        valid_value = bool(is_valid)
        zero_cross_value = bool(zero_cross)
        observation = AnalysisObservation(
            manifest_id=manifest_id,
            design_id=design_id,
            block_id=block_id,
            sample_index=sample_index,
            realization_seed=seed,
            execution_fingerprint_digest=digest,
            modality=modality,
            profile_id=profile,
            location_index=index,
            raw_rqd=raw_rqd_value,
            fixed_jn=fixed_jn,
            is_valid=valid_value,
            exclusion_reason=exclusion_reason,
            zero_cross=zero_cross_value,
            support_length_m=support_length,
            support_area_m2=support_area,
            p32_by_joint_set=p32_by_joint_set,
        )
        observations.append(observation)
        if attempt_index is None:
            raise RuntimeError("observed location has no selected successful attempt")
        source_attempt_indices.append((_observation_source_key(observation), attempt_index))
        observation_snapshot.append({
            **location_key,
            "fixed_jn": fixed_jn,
            "raw_rqd": raw_rqd_value,
            "method_id": method_id,
            "method_version": method_version,
            "is_valid": valid_value,
            "exclusion_reason": exclusion_reason,
            "zero_cross": zero_cross_value,
            "support_length_m": support_length,
            "support_area_m2": support_area,
            "p32_by_joint_set": [
                {"joint_set_id": joint_set_id, "p32_m2_per_m3": p32}
                for joint_set_id, p32 in p32_by_joint_set
            ],
        })
        evidence_rows = connection.execute(
            """
            SELECT scanline_index, start_enu_json, direction_enu_json,
                   measured_length_m, intersection_positions_json
            FROM measurement_evidence
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
              AND modality = ? AND profile_id = ? AND location_index = ?
            ORDER BY scanline_index
            """,
            (manifest_id, design_id, block_id, sample_index, seed, digest,
             attempt_index, modality, profile, index),
        ).fetchall()
        for evidence_row in evidence_rows:
            start = _decode_json(evidence_row[1], "measurement_evidence.start_enu_json")
            direction = _decode_json(
                evidence_row[2],
                "measurement_evidence.direction_enu_json",
            )
            intersections = _decode_json(
                evidence_row[4],
                "measurement_evidence.intersection_positions_json",
            )
            start_values = _json_number_array(start, "evidence start_enu_m")
            direction_values = _json_number_array(direction, "evidence direction_enu")
            intersection_values = _json_number_array(
                intersections,
                "evidence intersection_positions_m",
            )
            evidence_snapshot.append({
                **location_key,
                "scanline_index": int(evidence_row[0]),
                "start_enu_m": start_values,
                "direction_enu": direction_values,
                "measured_length_m": float(evidence_row[3]),
                "intersection_positions_m": intersection_values,
            })

    snapshot: dict[str, JsonValue] = {
        "schema_version": RAW_DATASET_SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "location_states": location_snapshot,
        "observations": observation_snapshot,
        "measurement_evidence": evidence_snapshot,
    }
    return (
        snapshot,
        tuple(statuses),
        tuple(observations),
        tuple(source_attempt_indices),
    )


def _revision_from_snapshot(
    manifest_id: str,
    revision_index: int,
    snapshot: dict[str, JsonValue],
    dataset_sha256: str,
    location_digest_by_key: dict[tuple[object, ...], str],
    source_attempt_indices: tuple[tuple[tuple[object, ...], int], ...],
) -> RawDatasetRevision:
    if snapshot.get("schema_version") != RAW_DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported raw dataset snapshot schema version")
    if snapshot.get("manifest_id") != manifest_id:
        raise ValueError("raw dataset snapshot has a mismatched manifest_id")
    if fingerprint_raw_dataset(snapshot).sha256_hex != dataset_sha256:
        raise ValueError("raw dataset revision SHA-256 does not match its snapshot")
    state_rows = _required_list(snapshot.get("location_states"), "location_states")
    observation_rows = _required_list(snapshot.get("observations"), "observations")
    evidence_rows = _required_list(
        snapshot.get("measurement_evidence"),
        "measurement_evidence",
    )
    states: list[AnalysisLocationStatus] = []
    for raw_item in state_rows:
        item = _required_object(raw_item, "location_state")
        key = _key_from_snapshot(item)
        digest = location_digest_by_key.get(key)
        if digest is None:
            raise ValueError("raw dataset location is absent from the frozen manifest")
        state = _status(item.get("status"))
        reason = item.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("location state reason must be text or NULL")
        modality = _modality(item.get("modality"))
        states.append(AnalysisLocationStatus(
            manifest_id=manifest_id,
            design_id=_json_text(item.get("design_id"), "design_id"),
            block_id=_json_text(item.get("block_id"), "block_id"),
            sample_index=_integer(item.get("sample_index"), "sample_index", nonnegative=True),
            realization_seed=_integer(item.get("realization_seed"), "realization_seed"),
            execution_fingerprint_digest=digest,
            modality=modality,
            profile_id=_json_text(item.get("profile_id"), "profile_id"),
            location_index=_integer(item.get("location_index"), "location_index", nonnegative=True),
            status=state,
            reason=reason,
        ))

    evidence_by_location: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for raw_item in evidence_rows:
        item = _required_object(raw_item, "measurement_evidence")
        key = _key_from_snapshot(item)
        evidence_by_location.setdefault(key, []).append(item)

    observations: list[AnalysisObservation] = []
    for raw_item in observation_rows:
        item = _required_object(raw_item, "observation")
        key = _key_from_snapshot(item)
        digest = location_digest_by_key.get(key)
        if digest is None:
            raise ValueError("raw dataset observation is absent from the frozen manifest")
        modality = _modality(item.get("modality"))
        p32_rows = _required_list(item.get("p32_by_joint_set"), "p32_by_joint_set")
        p32_values: list[tuple[str, float]] = []
        for raw_p32 in p32_rows:
            p32 = _required_object(raw_p32, "p32_by_joint_set item")
            p32_values.append((
                _json_text(p32.get("joint_set_id"), "joint_set_id"),
                _number(p32.get("p32_m2_per_m3"), "p32_m2_per_m3"),
            ))
        length = item.get("support_length_m")
        area = item.get("support_area_m2")
        is_valid = item.get("is_valid")
        zero_cross = item.get("zero_cross")
        if not isinstance(is_valid, bool) or not isinstance(zero_cross, bool):
            raise ValueError("observation validity and zero_cross must be booleans")
        exclusion_reason = item.get("exclusion_reason")
        if exclusion_reason is not None and not isinstance(exclusion_reason, str):
            raise ValueError("exclusion_reason must be text or NULL")
        fixed_jn = _number(item.get("fixed_jn"), "fixed_jn")
        observations.append(AnalysisObservation(
            manifest_id=manifest_id,
            design_id=_json_text(item.get("design_id"), "design_id"),
            block_id=_json_text(item.get("block_id"), "block_id"),
            sample_index=_integer(item.get("sample_index"), "sample_index", nonnegative=True),
            realization_seed=_integer(item.get("realization_seed"), "realization_seed"),
            execution_fingerprint_digest=digest,
            modality=modality,
            profile_id=_json_text(item.get("profile_id"), "profile_id"),
            location_index=_integer(item.get("location_index"), "location_index", nonnegative=True),
            raw_rqd=_number(item.get("raw_rqd"), "raw_rqd"),
            fixed_jn=fixed_jn,
            is_valid=is_valid,
            exclusion_reason=exclusion_reason,
            zero_cross=zero_cross,
            support_length_m=(_number(length, "support_length_m") if length is not None else None),
            support_area_m2=(_number(area, "support_area_m2") if area is not None else None),
            p32_by_joint_set=tuple(p32_values),
        ))
    observation_keys = {
        _key_from_snapshot(_required_object(item, "observation"))
        for item in observation_rows
    }
    if any(key not in observation_keys for key in evidence_by_location):
        raise ValueError("measurement evidence references a missing observation")
    observation_source_keys = {
        _observation_source_key(observation) for observation in observations
    }
    provenance_keys = tuple(key for key, _ in source_attempt_indices)
    if observation_source_keys and not provenance_keys:
        raise ValueError(
            "dataset revision has no source-attempt provenance for raw observations"
        )
    if (
        len(provenance_keys) != len(set(provenance_keys))
        or observation_source_keys != set(provenance_keys)
    ):
        raise ValueError(
            "dataset revision observation provenance does not match its raw observations"
        )
    return RawDatasetRevision(
        manifest_id,
        revision_index,
        dataset_sha256,
        snapshot,
        tuple(observations),
        tuple(states),
        source_attempt_indices,
    )


def _manifest_location_digests(
    connection: sqlite3.Connection,
    manifest_id: str,
) -> dict[tuple[object, ...], str]:
    rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed, modality,
               profile_id, location_index, execution_fingerprint_digest
        FROM planned_locations
        WHERE manifest_id = ?
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 modality, profile_id, location_index
        """,
        (manifest_id,),
    ).fetchall()
    return {tuple(row[:7]): row[7] for row in rows}


def _source_attempt_indices(
    connection: sqlite3.Connection,
    manifest_id: str,
    revision_index: int,
) -> tuple[tuple[tuple[object, ...], int], ...]:
    rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, modality, profile_id, location_index,
               attempt_index
        FROM dataset_revision_observations
        WHERE manifest_id = ? AND revision_index = ?
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest, modality, profile_id, location_index
        """,
        (manifest_id, revision_index),
    ).fetchall()
    return tuple(
        (
            tuple(row[:8]),
            _integer(row[8], "dataset revision source attempt_index", nonnegative=True),
        )
        for row in rows
    )


def _load_revision(
    connection: sqlite3.Connection,
    manifest_id: str,
    revision_index: int,
) -> RawDatasetRevision:
    row = connection.execute(
        """
        SELECT schema_version, dataset_snapshot, dataset_sha256
        FROM dataset_revisions
        WHERE manifest_id = ? AND revision_index = ?
        """,
        (manifest_id, revision_index),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"dataset revision {revision_index} is not present for manifest {manifest_id!r}"
        )
    schema_version, snapshot_bytes, digest = row
    if schema_version != RAW_DATASET_SCHEMA_VERSION:
        raise ValueError(f"unsupported dataset revision schema version: {schema_version}")
    parsed = _required_object(
        _decode_json(snapshot_bytes, "dataset_revisions.dataset_snapshot"),
        "dataset_snapshot",
    )
    canonical_bytes = fingerprint_snapshot(cast(dict[str, JsonValue], parsed)).canonical_bytes
    if canonical_bytes != bytes(snapshot_bytes):
        raise ValueError("stored dataset revision is not canonical RFC 8785 JSON")
    return _revision_from_snapshot(
        manifest_id,
        revision_index,
        cast(dict[str, JsonValue], parsed),
        digest,
        _manifest_location_digests(connection, manifest_id),
        _source_attempt_indices(connection, manifest_id, revision_index),
    )


def load_latest_dataset_revision(
    connection: sqlite3.Connection,
    manifest_id: str,
    revision_index: int | None = None,
) -> RawDatasetRevision:
    """Load a chosen immutable revision or create the initial revision once."""
    _require_initialized_store(connection)
    if not isinstance(manifest_id, str) or not manifest_id.strip():
        raise ValueError("manifest_id must be non-empty text")
    if revision_index is not None:
        if isinstance(revision_index, bool) or not isinstance(revision_index, int) or revision_index < 1:
            raise ValueError("revision_index must be a positive integer")
        return _load_revision(connection, manifest_id, revision_index)

    latest = connection.execute(
        "SELECT MAX(revision_index) FROM dataset_revisions WHERE manifest_id = ?",
        (manifest_id,),
    ).fetchone()[0]
    if latest is not None:
        return _load_revision(connection, manifest_id, int(latest))

    (
        snapshot,
        _,
        _,
        source_attempt_indices,
    ) = _build_current_snapshot(connection, manifest_id)
    fingerprint = fingerprint_raw_dataset(snapshot)
    canonical = fingerprint.canonical_bytes
    try:
        with connection:
            connection.executemany(
                """
                INSERT INTO dataset_revision_observations (
                    manifest_id, revision_index, design_id, block_id, sample_index,
                    realization_seed, execution_fingerprint_digest, attempt_index,
                    modality, profile_id, location_index
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        manifest_id,
                        *key[:5],
                        attempt_index,
                        *key[5:],
                    )
                    for key, attempt_index in source_attempt_indices
                ),
            )
            connection.execute(
                """
                INSERT INTO dataset_revisions (
                    manifest_id, revision_index, previous_revision_index,
                    correction_reason, schema_version, dataset_snapshot,
                    dataset_sha256
                ) VALUES (?, 1, NULL, NULL, ?, ?, ?)
                """,
                (
                    manifest_id,
                    RAW_DATASET_SCHEMA_VERSION,
                    canonical,
                    fingerprint.sha256_hex,
                ),
            )
    except sqlite3.IntegrityError as error:
        raise RuntimeError("failed to persist initial immutable dataset revision") from error
    return _revision_from_snapshot(
        manifest_id,
        1,
        snapshot,
        fingerprint.sha256_hex,
        _manifest_location_digests(connection, manifest_id),
        source_attempt_indices,
    )


def _successful_attempt_rows(
    connection: sqlite3.Connection,
    manifest_id: str,
) -> tuple[tuple[str, str, int, int, str, int], ...]:
    rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, MAX(attempt_index)
        FROM attempts
        WHERE manifest_id = ? AND status = 'succeeded'
        GROUP BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest
        """,
        (manifest_id,),
    ).fetchall()
    return tuple(
        (
            _json_text(row[0], "attempt.design_id"),
            _json_text(row[1], "attempt.block_id"),
            _integer(row[2], "attempt.sample_index", nonnegative=True),
            _integer(row[3], "attempt.realization_seed"),
            _json_text(row[4], "attempt.execution_fingerprint_digest"),
            _integer(row[5], "attempt.attempt_index", nonnegative=True),
        )
        for row in rows
    )


def _observation_attempt_payload(
    source_attempt_indices: tuple[tuple[tuple[object, ...], int], ...],
) -> list[JsonValue]:
    fields = (
        "design_id", "block_id", "sample_index", "realization_seed",
        "execution_fingerprint_digest", "modality", "profile_id", "location_index",
    )
    return [
        {
            **dict(zip(fields, cast(tuple[JsonValue, ...], key))),
            "attempt_index": attempt_index,
        }
        for key, attempt_index in source_attempt_indices
    ]


def _parse_observation_attempt_payload(
    value: object,
) -> tuple[tuple[tuple[object, ...], int], ...]:
    rows = _required_list(value, "observation_attempts")
    fields = (
        "design_id", "block_id", "sample_index", "realization_seed",
        "execution_fingerprint_digest", "modality", "profile_id", "location_index",
    )
    result: list[tuple[tuple[object, ...], int]] = []
    for raw_row in rows:
        row = _required_object(raw_row, "observation_attempt")
        key: tuple[object, ...] = (
            _json_text(row.get("design_id"), "observation_attempt.design_id"),
            _json_text(row.get("block_id"), "observation_attempt.block_id"),
            _integer(row.get("sample_index"), "observation_attempt.sample_index",
                     nonnegative=True),
            _integer(row.get("realization_seed"), "observation_attempt.realization_seed"),
            _json_text(
                row.get("execution_fingerprint_digest"),
                "observation_attempt.execution_fingerprint_digest",
            ),
            _modality(row.get("modality"), "observation_attempt.modality"),
            _json_text(row.get("profile_id"), "observation_attempt.profile_id"),
            _integer(row.get("location_index"), "observation_attempt.location_index",
                     nonnegative=True),
        )
        if any(field not in row for field in fields):
            raise ValueError("observation_attempt is missing a source key field")
        result.append((
            key,
            _integer(row.get("attempt_index"), "observation_attempt.attempt_index",
                     nonnegative=True),
        ))
    if len(result) != len({key for key, _ in result}):
        raise ValueError("cumulative revision contains duplicate observation provenance")
    return tuple(result)


def _successful_attempt_payload(
    rows: tuple[tuple[str, str, int, int, str, int], ...],
) -> list[JsonValue]:
    return [
        {
            "design_id": design_id,
            "block_id": block_id,
            "sample_index": sample_index,
            "realization_seed": seed,
            "execution_fingerprint_digest": digest,
            "attempt_index": attempt_index,
        }
        for design_id, block_id, sample_index, seed, digest, attempt_index in rows
    ]


def _attempt_history_payload(
    connection: sqlite3.Connection,
    manifest_id: str,
    selected_attempts: tuple[tuple[str, str, int, int, str, int], ...],
) -> list[JsonValue]:
    selected_by_job = {row[:5]: row[5] for row in selected_attempts}
    attempt_rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, attempt_index, status, started_at_utc,
               finished_at_utc, runtime_seconds, runtime_is_lower_bound
        FROM attempts
        WHERE manifest_id = ?
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest, attempt_index
        """,
        (manifest_id,),
    ).fetchall()
    history: list[JsonValue] = []
    for attempt in attempt_rows:
        design_id = _json_text(attempt[0], "attempt.design_id")
        block_id = _json_text(attempt[1], "attempt.block_id")
        sample_index = _integer(attempt[2], "attempt.sample_index", nonnegative=True)
        seed = _integer(attempt[3], "attempt.realization_seed")
        digest = _json_text(attempt[4], "attempt.execution_fingerprint_digest")
        attempt_index = _integer(attempt[5], "attempt.attempt_index", nonnegative=True)
        status = attempt[6]
        if status not in ("running", "succeeded", "failed"):
            raise ValueError("attempt history contains an invalid attempt status")
        started_at = _json_text(attempt[7], "attempt.started_at_utc")
        finished_at = attempt[8]
        if finished_at is not None and not isinstance(finished_at, str):
            raise ValueError("attempt.finished_at_utc must be text or NULL")
        runtime_seconds = _number(attempt[9], "attempt.runtime_seconds")
        runtime_is_lower_bound = attempt[10]
        if runtime_is_lower_bound not in (0, 1):
            raise ValueError("attempt.runtime_is_lower_bound must be 0 or 1")
        job_key = (design_id, block_id, sample_index, seed, digest)
        selected_for_analysis = (
            status == "succeeded"
            and selected_by_job.get(job_key) == attempt_index
        )
        key_parameters = (
            manifest_id, design_id, block_id, sample_index, seed, digest, attempt_index,
        )
        states = connection.execute(
            """
            SELECT modality, profile_id, location_index, status, reason
            FROM location_status
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
            ORDER BY modality, profile_id, location_index
            """,
            key_parameters,
        ).fetchall()
        state_payload: list[JsonValue] = []
        for state in states:
            modality = _modality(state[0])
            profile_id = _json_text(state[1], "location_status.profile_id")
            location_index = _integer(
                state[2], "location_status.location_index", nonnegative=True,
            )
            status_value = _status(state[3])
            reason = state[4]
            if reason is not None and not isinstance(reason, str):
                raise ValueError("location_status.reason must be text or NULL")
            state_payload.append({
                "modality": modality,
                "profile_id": profile_id,
                "location_index": location_index,
                "status": status_value,
                "reason": reason,
            })

        observation_rows = connection.execute(
            """
            SELECT modality, profile_id, location_index, raw_rqd, method_id,
                   method_version, is_valid, exclusion_reason, zero_cross, start_m,
                   end_m, support_length_m, chainage_m, support_area_m2,
                   advance_distance_m
            FROM observations
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = ?
            ORDER BY modality, profile_id, location_index
            """,
            key_parameters,
        ).fetchall()
        observation_payload: list[JsonValue] = []
        for observation in observation_rows:
            modality = _modality(observation[0])
            profile_id = _json_text(observation[1], "observation.profile_id")
            location_index = _integer(
                observation[2], "observation.location_index", nonnegative=True,
            )
            is_valid = observation[6]
            zero_cross = observation[8]
            if is_valid not in (0, 1) or zero_cross not in (0, 1):
                raise ValueError("observation boolean columns must be 0 or 1")
            exclusion_reason = observation[7]
            if exclusion_reason is not None and not isinstance(exclusion_reason, str):
                raise ValueError("observation.exclusion_reason must be text or NULL")
            method_id = _json_text(observation[4], "observation.method_id")
            method_version = _json_text(observation[5], "observation.method_version")
            measurement_evidence = connection.execute(
                """
                SELECT scanline_index, start_enu_json, direction_enu_json,
                       measured_length_m, intersection_positions_json
                FROM measurement_evidence
                WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                  AND sample_index = ? AND realization_seed = ?
                  AND execution_fingerprint_digest = ? AND attempt_index = ?
                  AND modality = ? AND profile_id = ? AND location_index = ?
                ORDER BY scanline_index
                """,
                (*key_parameters, modality, profile_id, location_index),
            ).fetchall()
            evidence_payload: list[JsonValue] = []
            for evidence in measurement_evidence:
                start = _json_number_array(
                    _decode_json(
                        evidence[1],
                        "measurement_evidence.start_enu_json",
                    ),
                    "measurement_evidence.start_enu_m",
                )
                direction = _json_number_array(
                    _decode_json(
                        evidence[2],
                        "measurement_evidence.direction_enu_json",
                    ),
                    "measurement_evidence.direction_enu",
                )
                intersections = _json_number_array(
                    _decode_json(
                        evidence[4],
                        "measurement_evidence.intersection_positions_json",
                    ),
                    "measurement_evidence.intersection_positions_m",
                )
                evidence_payload.append({
                    "scanline_index": _integer(
                        evidence[0], "measurement_evidence.scanline_index",
                        nonnegative=True,
                    ),
                    "start_enu_m": start,
                    "direction_enu": direction,
                    "measured_length_m": _number(
                        evidence[3], "measurement_evidence.measured_length_m",
                    ),
                    "intersection_positions_m": intersections,
                })
            observation_payload.append({
                "modality": modality,
                "profile_id": profile_id,
                "location_index": location_index,
                "raw_rqd": _number(observation[3], "observation.raw_rqd"),
                "method_id": method_id,
                "method_version": method_version,
                "is_valid": bool(is_valid),
                "exclusion_reason": exclusion_reason,
                "zero_cross": bool(zero_cross),
                "start_m": (
                    _number(observation[9], "observation.start_m")
                    if observation[9] is not None else None
                ),
                "end_m": (
                    _number(observation[10], "observation.end_m")
                    if observation[10] is not None else None
                ),
                "support_length_m": (
                    _number(observation[11], "observation.support_length_m")
                    if observation[11] is not None else None
                ),
                "chainage_m": (
                    _number(observation[12], "observation.chainage_m")
                    if observation[12] is not None else None
                ),
                "support_area_m2": (
                    _number(observation[13], "observation.support_area_m2")
                    if observation[13] is not None else None
                ),
                "advance_distance_m": (
                    _number(observation[14], "observation.advance_distance_m")
                    if observation[14] is not None else None
                ),
                "selected_for_analysis": selected_for_analysis,
                "measurement_evidence": evidence_payload,
            })
        history.append({
            "design_id": design_id,
            "block_id": block_id,
            "sample_index": sample_index,
            "realization_seed": seed,
            "execution_fingerprint_digest": digest,
            "attempt_index": attempt_index,
            "status": status,
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "runtime_seconds": runtime_seconds,
            "runtime_is_lower_bound": bool(runtime_is_lower_bound),
            "selected_for_analysis": selected_for_analysis,
            "location_states": state_payload,
            "observations": observation_payload,
        })
    return history


def _parse_successful_attempt_payload(
    value: object,
) -> tuple[tuple[str, str, int, int, str, int], ...]:
    rows = _required_list(value, "selected_successful_attempts")
    parsed: list[tuple[str, str, int, int, str, int]] = []
    for raw_row in rows:
        row = _required_object(raw_row, "selected_successful_attempt")
        parsed.append((
            _json_text(row.get("design_id"), "selected_attempt.design_id"),
            _json_text(row.get("block_id"), "selected_attempt.block_id"),
            _integer(row.get("sample_index"), "selected_attempt.sample_index",
                     nonnegative=True),
            _integer(row.get("realization_seed"), "selected_attempt.realization_seed"),
            _json_text(
                row.get("execution_fingerprint_digest"),
                "selected_attempt.execution_fingerprint_digest",
            ),
            _integer(row.get("attempt_index"), "selected_attempt.attempt_index",
                     nonnegative=True),
        ))
    if len(parsed) != len({row[:5] for row in parsed}):
        raise ValueError("cumulative revision contains duplicate selected attempts")
    return tuple(parsed)


def _build_current_cumulative_snapshot(
    connection: sqlite3.Connection,
) -> tuple[
    dict[str, JsonValue],
    tuple[str, ...],
    tuple[AnalysisObservation, ...],
    tuple[AnalysisLocationStatus, ...],
    tuple[tuple[tuple[object, ...], int], ...],
    tuple[str, ...],
]:
    manifests = tuple(
        row[0] for row in connection.execute(
            "SELECT manifest_id FROM manifest ORDER BY manifest_id",
        ).fetchall()
    )
    if not manifests:
        raise ValueError("cannot create a cumulative dataset revision without batches")

    batches: list[JsonValue] = []
    observations: list[AnalysisObservation] = []
    location_states: list[AnalysisLocationStatus] = []
    source_attempt_indices: list[tuple[tuple[object, ...], int]] = []
    independent_fingerprints: set[str] = set()
    for manifest_id in manifests:
        provenance = connection.execute(
            """
            SELECT yaml_sha256, source_reference
            FROM input_provenance WHERE manifest_id = ?
            """,
            (manifest_id,),
        ).fetchone()
        if provenance is None:
            raise ValueError(f"batch {manifest_id!r} has no input provenance")
        yaml_sha256, source_reference = provenance
        if (
            not isinstance(yaml_sha256, str)
            or len(yaml_sha256) != 64
            or any(character not in "0123456789abcdef" for character in yaml_sha256)
        ):
            raise ValueError(f"batch {manifest_id!r} has invalid YAML provenance")
        if source_reference is not None and not isinstance(source_reference, str):
            raise ValueError(f"batch {manifest_id!r} has invalid source reference")

        (
            raw_snapshot,
            batch_states,
            batch_observations,
            batch_source_attempt_indices,
        ) = _build_current_snapshot(connection, manifest_id)
        raw_fingerprint = fingerprint_raw_dataset(raw_snapshot)
        successful_attempts = _successful_attempt_rows(connection, manifest_id)
        attempt_history = _attempt_history_payload(
            connection,
            manifest_id,
            successful_attempts,
        )
        batches.append({
            "manifest_id": manifest_id,
            "yaml_sha256": yaml_sha256,
            "source_reference": source_reference,
            "dataset_sha256": raw_fingerprint.sha256_hex,
            "dataset_snapshot": raw_snapshot,
            "selected_successful_attempts": _successful_attempt_payload(
                successful_attempts,
            ),
            "observation_attempts": _observation_attempt_payload(
                batch_source_attempt_indices,
            ),
            "attempt_history": attempt_history,
        })
        observations.extend(batch_observations)
        location_states.extend(batch_states)
        source_attempt_indices.extend(
            ((manifest_id, *key), attempt_index)
            for key, attempt_index in batch_source_attempt_indices
        )
        independent_fingerprints.update(row[4] for row in successful_attempts)

    snapshot: dict[str, JsonValue] = {
        "schema_version": CUMULATIVE_DATASET_SCHEMA_VERSION,
        "batches": batches,
    }
    return (
        snapshot,
        manifests,
        tuple(observations),
        tuple(location_states),
        tuple(source_attempt_indices),
        tuple(sorted(independent_fingerprints)),
    )


def _cumulative_revision_from_snapshot(
    connection: sqlite3.Connection,
    revision_index: int,
    previous_revision_index: int | None,
    snapshot: dict[str, JsonValue],
    dataset_sha256: str,
) -> CumulativeRawDatasetRevision:
    if snapshot.get("schema_version") != CUMULATIVE_DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported cumulative dataset snapshot schema version")
    if fingerprint_snapshot(snapshot).sha256_hex != dataset_sha256:
        raise ValueError("cumulative dataset revision SHA-256 does not match its snapshot")
    raw_batches = _required_list(snapshot.get("batches"), "cumulative batches")
    if not raw_batches:
        raise ValueError("cumulative dataset revision contains no batches")

    manifest_ids: list[str] = []
    observations: list[AnalysisObservation] = []
    location_states: list[AnalysisLocationStatus] = []
    source_attempt_indices: list[tuple[tuple[object, ...], int]] = []
    independent_fingerprints: set[str] = set()
    expected_manifest_rows: list[tuple[int, str]] = []
    expected_attempt_rows: list[tuple[object, ...]] = []
    expected_observation_rows: list[tuple[object, ...]] = []

    for raw_batch in raw_batches:
        batch = _required_object(raw_batch, "cumulative batch")
        manifest_id = _json_text(batch.get("manifest_id"), "cumulative batch.manifest_id")
        if manifest_id in manifest_ids:
            raise ValueError("cumulative dataset snapshot contains duplicate batches")
        manifest_ids.append(manifest_id)
        yaml_sha256 = _json_text(batch.get("yaml_sha256"), "cumulative batch.yaml_sha256")
        if len(yaml_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in yaml_sha256
        ):
            raise ValueError("cumulative batch has invalid YAML provenance digest")
        source_reference = batch.get("source_reference")
        if source_reference is not None and not isinstance(source_reference, str):
            raise ValueError("cumulative batch source_reference must be text or NULL")
        stored_provenance = connection.execute(
            """
            SELECT yaml_sha256, source_reference
            FROM input_provenance WHERE manifest_id = ?
            """,
            (manifest_id,),
        ).fetchone()
        if stored_provenance != (yaml_sha256, source_reference):
            raise ValueError("cumulative batch provenance does not match the store")

        raw_snapshot = cast(
            dict[str, JsonValue],
            _required_object(batch.get("dataset_snapshot"), "batch.dataset_snapshot"),
        )
        raw_digest = _json_text(batch.get("dataset_sha256"), "batch.dataset_sha256")
        raw_canonical = fingerprint_snapshot(raw_snapshot)
        if raw_canonical.sha256_hex != raw_digest:
            raise ValueError("cumulative batch dataset digest does not match its snapshot")
        if raw_canonical.canonical_bytes != fingerprint_raw_dataset(raw_snapshot).canonical_bytes:
            raise ValueError("cumulative batch dataset snapshot is not canonical")
        if raw_snapshot.get("manifest_id") != manifest_id:
            raise ValueError("cumulative batch snapshot has a mismatched manifest_id")

        batch_source_attempt_indices = _parse_observation_attempt_payload(
            batch.get("observation_attempts"),
        )
        batch_attempts = _parse_successful_attempt_payload(
            batch.get("selected_successful_attempts"),
        )
        attempt_history = _required_list(batch.get("attempt_history"), "attempt_history")
        selected_attempt_keys: set[tuple[str, str, int, int, str, int]] = set()
        selected_observation_keys: set[tuple[tuple[object, ...], int]] = set()
        raw_attempt_keys: set[tuple[str, str, int, int, str, int]] = set()
        for raw_attempt in attempt_history:
            attempt = _required_object(raw_attempt, "attempt_history item")
            job_attempt = (
                _json_text(attempt.get("design_id"), "attempt.design_id"),
                _json_text(attempt.get("block_id"), "attempt.block_id"),
                _integer(attempt.get("sample_index"), "attempt.sample_index",
                         nonnegative=True),
                _integer(attempt.get("realization_seed"), "attempt.realization_seed"),
                _json_text(
                    attempt.get("execution_fingerprint_digest"),
                    "attempt.execution_fingerprint_digest",
                ),
                _integer(attempt.get("attempt_index"), "attempt.attempt_index",
                         nonnegative=True),
            )
            status = attempt.get("status")
            selected = attempt.get("selected_for_analysis")
            if status not in ("running", "succeeded", "failed"):
                raise ValueError("attempt_history contains an invalid attempt status")
            if not isinstance(selected, bool):
                raise ValueError("attempt_history selected_for_analysis must be boolean")
            if selected and status != "succeeded":
                raise ValueError("only a successful attempt can be selected for analysis")
            if job_attempt in raw_attempt_keys:
                raise ValueError("cumulative dataset snapshot contains duplicate attempts")
            raw_attempt_keys.add(job_attempt)
            if selected:
                selected_attempt_keys.add(job_attempt)

            for raw_observation in _required_list(
                attempt.get("observations"), "attempt.observations",
            ):
                observation = _required_object(
                    raw_observation, "attempt.observation",
                )
                observation_key: tuple[object, ...] = (
                    *job_attempt[:5],
                    _modality(observation.get("modality")),
                    _json_text(observation.get("profile_id"), "observation.profile_id"),
                    _integer(observation.get("location_index"), "observation.location_index",
                             nonnegative=True),
                )
                selected_observation = observation.get("selected_for_analysis")
                if not isinstance(selected_observation, bool):
                    raise ValueError(
                        "attempt observation selected_for_analysis must be boolean"
                    )
                if selected_observation != selected:
                    raise ValueError(
                        "attempt observation selection does not match its attempt"
                    )
                if selected:
                    selected_observation_keys.add((observation_key, job_attempt[5]))

                expected_observation_rows.append((
                    revision_index,
                    manifest_id,
                    *job_attempt[:5],
                    job_attempt[5],
                    *observation_key[5:],
                    int(selected),
                ))
            expected_attempt_rows.append((
                revision_index,
                manifest_id,
                *job_attempt[:5],
                job_attempt[5],
                status,
                int(selected),
            ))
        if selected_attempt_keys != set(batch_attempts):
            raise ValueError(
                "selected successful attempts do not match cumulative attempt history"
            )
        raw_revision = _revision_from_snapshot(
            manifest_id,
            revision_index,
            raw_snapshot,
            raw_digest,
            _manifest_location_digests(connection, manifest_id),
            batch_source_attempt_indices,
        )
        if selected_observation_keys != set(batch_source_attempt_indices):
            raise ValueError(
                "selected observation provenance does not match cumulative attempt history"
            )
        observations.extend(raw_revision.observations)
        location_states.extend(raw_revision.location_states)
        source_attempt_indices.extend(
            ((manifest_id, *key), attempt_index)
            for key, attempt_index in batch_source_attempt_indices
        )
        independent_fingerprints.update(row[4] for row in batch_attempts)
        expected_manifest_rows.append((revision_index, manifest_id))

    if manifest_ids != sorted(manifest_ids):
        raise ValueError("cumulative dataset batches are not deterministically ordered")
    stored_manifest_rows = connection.execute(
        """
        SELECT revision_index, manifest_id FROM cumulative_revision_manifests
        WHERE revision_index = ? ORDER BY manifest_id
        """,
        (revision_index,),
    ).fetchall()
    if tuple(stored_manifest_rows) != tuple(expected_manifest_rows):
        raise ValueError("cumulative revision batch provenance does not match its snapshot")
    stored_attempt_rows = connection.execute(
        """
        SELECT revision_index, manifest_id, design_id, block_id, sample_index,
               realization_seed, execution_fingerprint_digest, attempt_index,
               status, selected_for_analysis
        FROM cumulative_revision_attempts
        WHERE revision_index = ?
        ORDER BY manifest_id, design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest, attempt_index
        """,
        (revision_index,),
    ).fetchall()
    if tuple(stored_attempt_rows) != tuple(expected_attempt_rows):
        raise ValueError("cumulative revision attempt provenance does not match its snapshot")
    stored_observation_rows = connection.execute(
        """
        SELECT revision_index, manifest_id, design_id, block_id, sample_index,
               realization_seed, execution_fingerprint_digest, attempt_index,
               modality, profile_id, location_index, selected_for_analysis
        FROM cumulative_revision_observations
        WHERE revision_index = ?
        ORDER BY manifest_id, design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest, modality, profile_id, location_index
        """,
        (revision_index,),
    ).fetchall()
    if tuple(stored_observation_rows) != tuple(expected_observation_rows):
        raise ValueError(
            "cumulative revision observation provenance does not match its snapshot"
        )

    raw_attempt_count = len(raw_attempt_keys) if manifest_ids else 0
    raw_observation_count = sum(
        len(_required_list(
            _required_object(raw_attempt, "attempt_history item").get("observations"),
            "attempt.observations",
        ))
        for raw_batch in raw_batches
        for raw_attempt in _required_list(
            _required_object(raw_batch, "cumulative batch").get("attempt_history"),
            "attempt_history",
        )
    )
    return CumulativeRawDatasetRevision(
        revision_index,
        previous_revision_index,
        dataset_sha256,
        snapshot,
        tuple(manifest_ids),
        tuple(observations),
        tuple(location_states),
        tuple(source_attempt_indices),
        tuple(sorted(independent_fingerprints)),
        raw_attempt_count,
        raw_observation_count,
    )


def _load_cumulative_revision(
    connection: sqlite3.Connection,
    revision_index: int,
) -> CumulativeRawDatasetRevision:
    row = connection.execute(
        """
        SELECT previous_revision_index, schema_version, dataset_snapshot, dataset_sha256
        FROM cumulative_dataset_revisions WHERE revision_index = ?
        """,
        (revision_index,),
    ).fetchone()
    if row is None:
        raise ValueError(f"cumulative dataset revision {revision_index} is not present")
    previous_revision_index, schema_version, snapshot_bytes, dataset_sha256 = row
    if schema_version != CUMULATIVE_DATASET_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported cumulative dataset revision schema version: {schema_version}"
        )
    if previous_revision_index is not None and previous_revision_index != revision_index - 1:
        raise ValueError("cumulative revision chain is invalid")
    snapshot = cast(
        dict[str, JsonValue],
        _required_object(
            _decode_json(snapshot_bytes, "cumulative_dataset_revisions.dataset_snapshot"),
            "cumulative_dataset_snapshot",
        ),
    )
    canonical = fingerprint_snapshot(snapshot)
    if canonical.canonical_bytes != bytes(snapshot_bytes):
        raise ValueError("cumulative dataset revision is not canonical RFC 8785 JSON")
    return _cumulative_revision_from_snapshot(
        connection,
        revision_index,
        previous_revision_index,
        snapshot,
        dataset_sha256,
    )


def load_latest_cumulative_dataset_revision(
    connection: sqlite3.Connection,
    revision_index: int | None = None,
) -> CumulativeRawDatasetRevision:
    """Load a chosen cumulative revision or append a new immutable store-wide revision."""
    _require_initialized_store(connection)
    if revision_index is not None:
        if (
            isinstance(revision_index, bool)
            or not isinstance(revision_index, int)
            or revision_index < 1
        ):
            raise ValueError("revision_index must be a positive integer")
        return _load_cumulative_revision(connection, revision_index)

    snapshot, manifest_ids, *_ = _build_current_cumulative_snapshot(connection)
    fingerprint = fingerprint_snapshot(snapshot)
    latest_row = connection.execute(
        """
        SELECT revision_index, dataset_sha256 FROM cumulative_dataset_revisions
        ORDER BY revision_index DESC LIMIT 1
        """
    ).fetchone()
    if latest_row is not None and latest_row[1] == fingerprint.sha256_hex:
        return _load_cumulative_revision(connection, int(latest_row[0]))

    revision_index = 1 if latest_row is None else int(latest_row[0]) + 1
    previous_revision_index = None if latest_row is None else int(latest_row[0])
    attempt_rows: list[tuple[object, ...]] = []
    observation_rows: list[tuple[object, ...]] = []
    for raw_batch in _required_list(snapshot.get("batches"), "cumulative batches"):
        batch = _required_object(raw_batch, "cumulative batch")
        manifest_id = _json_text(batch.get("manifest_id"), "cumulative batch.manifest_id")
        for raw_attempt in _required_list(
            batch.get("attempt_history"), "attempt_history",
        ):
            attempt = _required_object(raw_attempt, "attempt_history item")
            job_key = (
                _json_text(attempt.get("design_id"), "attempt.design_id"),
                _json_text(attempt.get("block_id"), "attempt.block_id"),
                _integer(attempt.get("sample_index"), "attempt.sample_index",
                         nonnegative=True),
                _integer(attempt.get("realization_seed"), "attempt.realization_seed"),
                _json_text(
                    attempt.get("execution_fingerprint_digest"),
                    "attempt.execution_fingerprint_digest",
                ),
                _integer(attempt.get("attempt_index"), "attempt.attempt_index",
                         nonnegative=True),
            )
            status = _json_text(attempt.get("status"), "attempt.status")
            selected = attempt.get("selected_for_analysis")
            if not isinstance(selected, bool):
                raise ValueError("attempt selected_for_analysis must be boolean")
            attempt_rows.append((
                revision_index,
                manifest_id,
                *job_key,
                status,
                int(selected),
            ))
            for raw_observation in _required_list(
                attempt.get("observations"), "attempt.observations",
            ):
                observation = _required_object(raw_observation, "attempt.observation")
                observation_rows.append((
                    revision_index,
                    manifest_id,
                    *job_key,
                    _modality(observation.get("modality")),
                    _json_text(observation.get("profile_id"), "observation.profile_id"),
                    _integer(observation.get("location_index"), "observation.location_index",
                             nonnegative=True),
                    int(selected),
                ))
    try:
        with connection:
            connection.executemany(
                """
                INSERT INTO cumulative_revision_manifests (revision_index, manifest_id)
                VALUES (?, ?)
                """,
                ((revision_index, manifest_id) for manifest_id in manifest_ids),
            )
            connection.executemany(
                """
                INSERT INTO cumulative_revision_attempts (
                    revision_index, manifest_id, design_id, block_id, sample_index,
                    realization_seed, execution_fingerprint_digest, attempt_index,
                    status, selected_for_analysis
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                attempt_rows,
            )
            connection.executemany(
                """
                INSERT INTO cumulative_revision_observations (
                    revision_index, manifest_id, design_id, block_id, sample_index,
                    realization_seed, execution_fingerprint_digest, attempt_index,
                    modality, profile_id, location_index, selected_for_analysis
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                observation_rows,
            )
            connection.execute(
                """
                INSERT INTO cumulative_dataset_revisions (
                    revision_index, previous_revision_index, schema_version,
                    dataset_snapshot, dataset_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    revision_index,
                    previous_revision_index,
                    CUMULATIVE_DATASET_SCHEMA_VERSION,
                    fingerprint.canonical_bytes,
                    fingerprint.sha256_hex,
                ),
            )
    except sqlite3.IntegrityError as error:
        raise RuntimeError("failed to persist cumulative dataset revision atomically") from error
    return _load_cumulative_revision(connection, revision_index)


def persist_analysis_run(
    connection: sqlite3.Connection,
    revision: RawDatasetRevision,
    analysis_snapshot: dict[str, JsonValue],
) -> str:
    """Register one immutable analysis fingerprint idempotently."""
    _require_initialized_store(connection)
    analysis_fingerprint = fingerprint_snapshot(analysis_snapshot)
    with connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO analysis_runs (
                manifest_id, revision_index, analysis_fingerprint_digest,
                schema_version, analysis_snapshot, analysis_sha256, dataset_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.manifest_id,
                revision.revision_index,
                analysis_fingerprint.sha256_hex,
                analysis_snapshot["schema_version"],
                analysis_fingerprint.canonical_bytes,
                analysis_fingerprint.sha256_hex,
                revision.dataset_sha256,
            ),
        )
    stored = connection.execute(
        """
        SELECT analysis_snapshot, analysis_sha256, dataset_sha256
        FROM analysis_runs
        WHERE manifest_id = ? AND revision_index = ?
          AND analysis_fingerprint_digest = ?
        """,
        (
            revision.manifest_id,
            revision.revision_index,
            analysis_fingerprint.sha256_hex,
        ),
    ).fetchone()
    if stored != (
        analysis_fingerprint.canonical_bytes,
        analysis_fingerprint.sha256_hex,
        revision.dataset_sha256,
    ):
        raise ValueError("stored analysis run conflicts with its fingerprint")
    return analysis_fingerprint.sha256_hex


def persist_derived_scores(
    connection: sqlite3.Connection,
    revision: RawDatasetRevision,
    analysis_fingerprint_digest: str,
) -> int:
    """Persist all observation/scenario scores once and verify exact reuse."""
    _require_initialized_store(connection)
    if (
        not isinstance(analysis_fingerprint_digest, str)
        or len(analysis_fingerprint_digest) != 64
        or any(character not in "0123456789abcdef"
               for character in analysis_fingerprint_digest)
    ):
        raise ValueError("analysis_fingerprint_digest must be lowercase SHA-256")

    source_attempt_by_key = dict(revision.source_attempt_indices)
    observation_keys = {
        _observation_source_key(observation) for observation in revision.observations
    }
    if observation_keys != set(source_attempt_by_key):
        raise ValueError("dataset revision lacks complete observation attempt provenance")

    expected_rows: list[tuple[object, ...]] = []
    for observation in revision.observations:
        source_key = _observation_source_key(observation)
        attempt_index = source_attempt_by_key[source_key]
        for score in calculate_scenario_scores(
            observation.raw_rqd,
            observation.fixed_jn,
            zero_cross=observation.zero_cross,
        ):
            expected_rows.append((
                *source_key[:5],
                attempt_index,
                *source_key[5:],
                score.jr_value,
                score.ja_value,
                score.fixed_jn,
                score.calculation_rqd,
                score.qprime,
                score.bin_id,
                ZERO_CROSS_CONVENTION,
            ))
    expected_rows.sort()
    with connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO derived_scores (
                manifest_id, revision_index, analysis_fingerprint_digest,
                design_id, block_id, sample_index, realization_seed,
                execution_fingerprint_digest, attempt_index, modality, profile_id,
                location_index, jr_value, ja_value, fixed_jn, calculation_rqd,
                qprime, bin_id, zero_cross_convention
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    revision.manifest_id,
                    revision.revision_index,
                    analysis_fingerprint_digest,
                    *row,
                )
                for row in expected_rows
            ),
        )
    stored_rows = connection.execute(
        """
        SELECT design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, attempt_index, modality, profile_id,
               location_index, jr_value, ja_value, fixed_jn, calculation_rqd,
               qprime, bin_id, zero_cross_convention
        FROM derived_scores
        WHERE manifest_id = ? AND revision_index = ?
          AND analysis_fingerprint_digest = ?
        ORDER BY design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest, attempt_index, modality, profile_id,
                 location_index, jr_value, ja_value
        """,
        (
            revision.manifest_id,
            revision.revision_index,
            analysis_fingerprint_digest,
        ),
    ).fetchall()
    if tuple(stored_rows) != tuple(expected_rows):
        raise ValueError("stored derived scores conflict with the analysis result")
    return len(expected_rows)


def _cumulative_observation_source_key(
    observation: AnalysisObservation,
) -> tuple[object, ...]:
    return (
        observation.manifest_id,
        observation.design_id,
        observation.block_id,
        observation.sample_index,
        observation.realization_seed,
        observation.execution_fingerprint_digest,
        observation.modality,
        observation.profile_id,
        observation.location_index,
    )


def _validate_cumulative_analysis_snapshot(
    revision: CumulativeRawDatasetRevision,
    analysis_snapshot: dict[str, JsonValue],
) -> tuple[SnapshotFingerprint, tuple[float, ...], tuple[float, ...]]:
    if not isinstance(revision, CumulativeRawDatasetRevision):
        raise TypeError("revision must be a CumulativeRawDatasetRevision")
    if not isinstance(analysis_snapshot, dict):
        raise TypeError("analysis_snapshot must be a dictionary")
    fingerprint = fingerprint_snapshot(analysis_snapshot)
    normalized_snapshot = _required_object(
        _decode_json(fingerprint.canonical_bytes, "analysis snapshot"),
        "analysis snapshot",
    )
    dataset = _required_object(normalized_snapshot.get("dataset"), "analysis dataset")
    if dataset.get("kind") != "cumulative":
        raise ValueError("analysis snapshot must identify a cumulative dataset")
    if _integer(dataset.get("revision_index"), "analysis revision_index") \
            != revision.revision_index:
        raise ValueError("analysis snapshot references a different cumulative revision")
    if _json_text(dataset.get("sha256"), "analysis dataset sha256") \
            != revision.dataset_sha256:
        raise ValueError("analysis snapshot references a different cumulative dataset")
    rules = _required_object(normalized_snapshot.get("rules"), "analysis rules")
    jr_values = _json_number_array(rules.get("jr_values"), "analysis rules jr_values")
    ja_values = _json_number_array(rules.get("ja_values"), "analysis rules ja_values")
    if not jr_values or not ja_values:
        raise ValueError("analysis snapshot must select at least one Jr and Ja value")
    expected_snapshot = build_cumulative_analysis_snapshot(
        revision.revision_index,
        revision.dataset_sha256,
        jr_values=jr_values,
        ja_values=ja_values,
    )
    if (
        fingerprint_snapshot(expected_snapshot).canonical_bytes
        != fingerprint.canonical_bytes
    ):
        raise ValueError("analysis snapshot does not match the approved analysis rules")
    return fingerprint, jr_values, ja_values


def persist_cumulative_analysis_run(
    connection: sqlite3.Connection,
    revision: CumulativeRawDatasetRevision,
    analysis_snapshot: dict[str, JsonValue],
) -> str:
    """Register one immutable analysis fingerprint for a cumulative revision."""
    _require_initialized_store(connection)
    analysis_fingerprint, _, _ = _validate_cumulative_analysis_snapshot(
        revision,
        analysis_snapshot,
    )
    with connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO cumulative_analysis_runs (
                revision_index, analysis_fingerprint_digest, schema_version,
                analysis_snapshot, analysis_sha256, dataset_sha256
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                revision.revision_index,
                analysis_fingerprint.sha256_hex,
                analysis_snapshot.get("schema_version"),
                analysis_fingerprint.canonical_bytes,
                analysis_fingerprint.sha256_hex,
                revision.dataset_sha256,
            ),
        )
    stored = connection.execute(
        """
        SELECT analysis_snapshot, analysis_sha256, dataset_sha256
        FROM cumulative_analysis_runs
        WHERE revision_index = ? AND analysis_fingerprint_digest = ?
        """,
        (revision.revision_index, analysis_fingerprint.sha256_hex),
    ).fetchone()
    if stored != (
        analysis_fingerprint.canonical_bytes,
        analysis_fingerprint.sha256_hex,
        revision.dataset_sha256,
    ):
        raise ValueError("stored cumulative analysis conflicts with its fingerprint")
    return analysis_fingerprint.sha256_hex


def persist_cumulative_derived_scores(
    connection: sqlite3.Connection,
    revision: CumulativeRawDatasetRevision,
    analysis_fingerprint_digest: str,
) -> int:
    """Persist and verify selected scenario scores for a cumulative revision."""
    _require_initialized_store(connection)
    if (
        not isinstance(analysis_fingerprint_digest, str)
        or len(analysis_fingerprint_digest) != 64
        or any(character not in "0123456789abcdef"
               for character in analysis_fingerprint_digest)
    ):
        raise ValueError("analysis_fingerprint_digest must be lowercase SHA-256")
    run = connection.execute(
        """
        SELECT analysis_snapshot, analysis_sha256, dataset_sha256
        FROM cumulative_analysis_runs
        WHERE revision_index = ? AND analysis_fingerprint_digest = ?
        """,
        (revision.revision_index, analysis_fingerprint_digest),
    ).fetchone()
    if run is None:
        raise ValueError("cumulative analysis run must be registered before scoring")
    snapshot = cast(
        dict[str, JsonValue],
        _required_object(
            _decode_json(run[0], "cumulative_analysis_runs.analysis_snapshot"),
            "cumulative analysis snapshot",
        ),
    )
    analysis_fingerprint, jr_values, ja_values = _validate_cumulative_analysis_snapshot(
        revision,
        snapshot,
    )
    if (
        analysis_fingerprint.sha256_hex != analysis_fingerprint_digest
        or run[1] != analysis_fingerprint_digest
        or run[2] != revision.dataset_sha256
    ):
        raise ValueError("stored cumulative analysis metadata does not match its fingerprint")

    source_attempt_by_key = dict(revision.source_attempt_indices)
    observation_keys = {
        _cumulative_observation_source_key(observation)
        for observation in revision.observations
    }
    if (
        len(source_attempt_by_key) != len(revision.source_attempt_indices)
        or observation_keys != set(source_attempt_by_key)
    ):
        raise ValueError("cumulative revision lacks complete observation attempt provenance")

    expected_rows: list[tuple[object, ...]] = []
    for observation in revision.observations:
        source_key = _cumulative_observation_source_key(observation)
        attempt_index = source_attempt_by_key[source_key]
        for score in calculate_scenario_scores(
            observation.raw_rqd,
            observation.fixed_jn,
            zero_cross=observation.zero_cross,
            jr_values=jr_values,
            ja_values=ja_values,
        ):
            expected_rows.append((
                revision.revision_index,
                analysis_fingerprint_digest,
                *source_key[:6],
                attempt_index,
                *source_key[6:],
                score.jr_value,
                score.ja_value,
                score.fixed_jn,
                score.calculation_rqd,
                score.qprime,
                score.bin_id,
                ZERO_CROSS_CONVENTION,
            ))
    expected_rows.sort()
    with connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO cumulative_derived_scores (
                revision_index, analysis_fingerprint_digest, manifest_id,
                design_id, block_id, sample_index, realization_seed,
                execution_fingerprint_digest, attempt_index, modality, profile_id,
                location_index, jr_value, ja_value, fixed_jn, calculation_rqd,
                qprime, bin_id, zero_cross_convention
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            expected_rows,
        )
    stored_rows = connection.execute(
        """
        SELECT revision_index, analysis_fingerprint_digest, manifest_id,
               design_id, block_id, sample_index, realization_seed,
               execution_fingerprint_digest, attempt_index, modality, profile_id,
               location_index, jr_value, ja_value, fixed_jn, calculation_rqd,
               qprime, bin_id, zero_cross_convention
        FROM cumulative_derived_scores
        WHERE revision_index = ? AND analysis_fingerprint_digest = ?
        ORDER BY manifest_id, design_id, block_id, sample_index, realization_seed,
                 execution_fingerprint_digest, attempt_index, modality, profile_id,
                 location_index, jr_value, ja_value
        """,
        (revision.revision_index, analysis_fingerprint_digest),
    ).fetchall()
    if tuple(stored_rows) != tuple(expected_rows):
        raise ValueError("stored cumulative derived scores conflict with the analysis result")
    return len(expected_rows)
