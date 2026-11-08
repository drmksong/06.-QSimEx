"""Additive, immutable measured-P32 results and geometry-only backfill."""

from dataclasses import asdict
import json

from src.euler_campaign.generation import LEGACY, generation_mode_for_version
from src.euler_campaign.p32 import P32_METHOD_ID, P32_METHOD_VERSION, measure_domain_p32
from .adapter import build_generation_case
from .config import GeometryInput, MeasurementInput
from .fingerprint import fingerprint_execution_snapshot
from .measurement import RawBHObservation, measure_realization
from .store import STORE_SCHEMA_VERSION, _atomic, _job_key

_MEASURED_FIELDS = ("joint_count", "intersecting_joint_count", "area_m2",
                    "domain_volume_m3", "p32_m2_per_m3")


def initialize_p32_store(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != STORE_SCHEMA_VERSION:
        raise ValueError("measured P32 requires raw schema4; no migration")
    with _atomic(connection):
        connection.execute("""
            CREATE TABLE IF NOT EXISTS realization_p32 (
                execution_fingerprint_digest TEXT NOT NULL,
                joint_set_id TEXT NOT NULL, method_id TEXT NOT NULL, method_version TEXT NOT NULL,
                source_job_key TEXT NOT NULL,
                joint_count INTEGER NOT NULL CHECK(joint_count>=0),
                intersecting_joint_count INTEGER NOT NULL CHECK(
                    intersecting_joint_count>=0 AND intersecting_joint_count<=joint_count),
                area_m2 REAL NOT NULL CHECK(area_m2>=0),
                domain_volume_m3 REAL NOT NULL CHECK(domain_volume_m3>0),
                p32_m2_per_m3 REAL NOT NULL CHECK(p32_m2_per_m3>=0),
                PRIMARY KEY(execution_fingerprint_digest,joint_set_id,method_id,method_version))
        """)
        for action in ("UPDATE", "DELETE"):
            connection.execute(f"""
                CREATE TRIGGER IF NOT EXISTS realization_p32_no_{action.lower()}
                BEFORE {action} ON realization_p32
                BEGIN SELECT RAISE(ABORT, 'measured P32 is immutable'); END
            """)


def read_measured_p32(connection):
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='realization_p32'").fetchone():
        return {}
    result = {}
    for row in connection.execute(
        "SELECT execution_fingerprint_digest,joint_set_id,joint_count,intersecting_joint_count,"
        "area_m2,domain_volume_m3,p32_m2_per_m3 FROM realization_p32 "
        "WHERE method_id=? AND method_version=? ORDER BY execution_fingerprint_digest,joint_set_id",
        (P32_METHOD_ID, P32_METHOD_VERSION)):
        result.setdefault(row[0], {})[row[1]] = {
            **dict(zip(_MEASURED_FIELDS, row[2:])),
            "method_id": P32_METHOD_ID, "method_version": P32_METHOD_VERSION}
    return result


def store_measured_p32(connection, job, records):
    from math import isclose, isfinite, prod
    expected_sets = {s.joint_set_id for s in job.snapshot.joint_sets} | {""}
    if set(records) != expected_sets:
        raise ValueError("measured P32 must include every set and the total")
    if fingerprint_execution_snapshot(job.snapshot).sha256_hex != job.fingerprint.sha256_hex:
        raise ValueError("measured P32 job fingerprint mismatch")
    if not connection.execute(
        "SELECT 1 FROM jobs WHERE manifest_id=? AND design_id=? AND block_id=? AND sample_index=? "
        "AND realization_seed=? AND execution_fingerprint_digest=?", _job_key(job)).fetchone():
        raise ValueError("measured P32 requires a persisted execution job")
    for name in ("joint_count", "intersecting_joint_count", "area_m2"):
        total = sum(records[s][name] for s in expected_sets if s)
        agrees = (isclose(records[""][name], total, rel_tol=1e-12, abs_tol=1e-9)
                  if name == "area_m2" else records[""][name] == total)
        if not agrees:
            raise ValueError("measured P32 total disagrees with per-set results")
    with _atomic(connection):
        for set_id, record in records.items():
            if (record["method_id"] != P32_METHOD_ID or record["method_version"] != P32_METHOD_VERSION
                or any(not isfinite(record[name]) or record[name] < 0
                       for name in ("area_m2", "p32_m2_per_m3", "domain_volume_m3"))
                or record["domain_volume_m3"] <= 0
                or record["domain_volume_m3"] != prod(job.snapshot.geometry.domain_size_m)
                or record["p32_m2_per_m3"] != record["area_m2"] / record["domain_volume_m3"]
                or any(type(record[name]) is not int or record[name] < 0
                       for name in ("joint_count", "intersecting_joint_count"))
                or record["intersecting_joint_count"] > record["joint_count"]):
                raise ValueError("invalid measured P32 result")
            values = tuple(record[name] for name in _MEASURED_FIELDS)
            key = (job.fingerprint.sha256_hex, set_id, P32_METHOD_ID, P32_METHOD_VERSION)
            saved = connection.execute(
                "SELECT joint_count,intersecting_joint_count,area_m2,domain_volume_m3,p32_m2_per_m3 "
                "FROM realization_p32 WHERE execution_fingerprint_digest=? "
                "AND joint_set_id=? AND method_id=? AND method_version=?", key).fetchone()
            if saved is not None and saved != values:
                raise ValueError("regenerated measured P32 conflicts with saved geometry")
            connection.execute("INSERT OR IGNORE INTO realization_p32 VALUES (?,?,?,?,?,?,?,?,?,?)",
                (*key, json.dumps(_job_key(job)), *values))


def generate_frozen_geometry(factory, case, seed, runtime, progress_callback=None):
    kwargs = {}
    mode = generation_mode_for_version(runtime.generator_version)
    if mode != LEGACY:
        kwargs["generation_mode"] = mode
    if progress_callback is not None:
        kwargs["progress_callback"] = progress_callback
    return factory.generate(case, seed, **kwargs)


class P32RecordingFactory:
    def __init__(self, factory, runtime, *, record_p32=True):
        self.factory, self.runtime, self.records = factory, runtime, None
        self.record_p32 = record_p32

    def generate(self, case, seed, *, progress_callback=None):
        from src.euler_campaign.progress import ProgressUpdate
        geometry = generate_frozen_geometry(self.factory, case, seed, self.runtime, progress_callback)
        if self.record_p32:
            if progress_callback is not None:
                progress_callback(ProgressUpdate("Measured P32", "clipping disk areas to domain"))
            self.records = measure_domain_p32(case, geometry)
        return geometry


def case_for_snapshot(snapshot, case_id):
    fields = asdict(snapshot.geometry)
    fields["cell_counts"] = tuple(int(size / spacing)
        for size, spacing in zip(snapshot.geometry.domain_size_m, snapshot.geometry.grid_spacing_m))
    geometry = GeometryInput(**fields)
    measurements = MeasurementInput(snapshot.measurements.bh_interval_m,
                                    snapshot.measurements.face_advance_m)
    return build_generation_case(geometry, measurements, snapshot.fixed_jn,
        snapshot.joint_sets, case_id=case_id, allow_constant_radius=True)


def verify_job_rqd(connection, job, case, geometry):
    result = measure_realization(case, geometry)
    actual = {}
    for observation in result.observations:
        bh = isinstance(observation, RawBHObservation)
        key = ("BH" if bh else "face", observation.profile_id, observation.location_index)
        actual[key] = (observation.raw_rqd, observation.method_id, observation.method_version,
            int(observation.is_valid), observation.exclusion_reason, int(observation.zero_cross),
            observation.start_m if bh else None, observation.end_m if bh else None,
            observation.support_length_m if bh else None, None if bh else observation.chainage_m,
            None if bh else observation.support_area_m2,
            None if bh else observation.advance_distance_m)
    key = _job_key(job)
    attempt = connection.execute(
        "SELECT MAX(attempt_index) FROM attempts WHERE manifest_id=? AND design_id=? AND block_id=? "
        "AND sample_index=? AND realization_seed=? AND execution_fingerprint_digest=? AND status='succeeded'",
        key).fetchone()[0]
    rows = connection.execute(
        "SELECT modality,profile_id,location_index,raw_rqd,method_id,method_version,is_valid,"
        "exclusion_reason,zero_cross,start_m,end_m,support_length_m,chainage_m,support_area_m2,"
        "advance_distance_m FROM observations WHERE manifest_id=? AND design_id=? AND block_id=? "
        "AND sample_index=? AND realization_seed=? AND execution_fingerprint_digest=? AND attempt_index=?",
        (*key, attempt)).fetchall()
    expected = {tuple(row[:3]): tuple(row[3:]) for row in rows}
    if not expected or actual != expected:
        raise ValueError(f"regeneration RQD fidelity verification failed: {job.fingerprint.sha256_hex}")


def _case_ids_for_manifest(connection, manifest_id):
    row = connection.execute(
        "SELECT manifest_json FROM manifest WHERE manifest_id=?", (manifest_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"manifest {manifest_id!r} is not present in the database")
    payload = json.loads(row[0])
    if not isinstance(payload, dict) or payload.get("manifest_id") != manifest_id:
        raise ValueError("stored manifest payload has a mismatched manifest_id")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("stored manifest jobs must be a JSON array")
    result = {}
    for item in jobs:
        if not isinstance(item, dict):
            raise ValueError("stored manifest job must be a JSON object")
        key = (
            item.get("manifest_id"), item.get("design_id"), item.get("block_id"),
            item.get("sample_index"), item.get("realization_seed"),
            item.get("execution_fingerprint_digest"),
        )
        design_id = item.get("design_id")
        case_id = item.get("case_id", design_id)
        if (
            key[0] != manifest_id
            or not isinstance(design_id, str)
            or not isinstance(case_id, str)
            or not case_id.strip()
            or key in result
        ):
            raise ValueError("stored manifest job has an invalid case identifier")
        result[key] = case_id
    return result


def measure_missing_p32(connection, factory_for_runtime, *, verify_job=None, progress_callback=None):
    from .main_controller import _snapshot_from_payload
    from .records import ExecutionJob
    initialize_p32_store(connection)
    rows = connection.execute(
        "SELECT j.manifest_id,j.design_id,j.block_id,j.sample_index,j.realization_seed,"
        "j.execution_fingerprint_digest,j.execution_snapshot FROM jobs j "
        "WHERE EXISTS (SELECT 1 FROM attempts a WHERE a.manifest_id=j.manifest_id "
        "AND a.design_id=j.design_id AND a.block_id=j.block_id AND a.sample_index=j.sample_index "
        "AND a.realization_seed=j.realization_seed "
        "AND a.execution_fingerprint_digest=j.execution_fingerprint_digest AND a.status='succeeded') "
        "ORDER BY j.manifest_id,j.design_id,j.block_id,j.sample_index,j.realization_seed").fetchall()
    if verify_job is not None and verify_job not in {row[5] for row in rows}:
        raise ValueError("--verify-job must identify an existing succeeded execution fingerprint")
    if verify_job is not None:
        rows = [row for row in rows if row[5] == verify_job]
    done = read_measured_p32(connection)
    measured, skipped, verified = 0, 0, set()
    case_ids_by_manifest = {}
    for row in rows:
        snapshot = _snapshot_from_payload(json.loads(row[6]))
        fingerprint = fingerprint_execution_snapshot(snapshot)
        if fingerprint.sha256_hex != row[5]:
            raise ValueError("saved execution snapshot fingerprint mismatch")
        manifest_id = row[0]
        if manifest_id not in case_ids_by_manifest:
            case_ids_by_manifest[manifest_id] = _case_ids_for_manifest(
                connection, manifest_id)
        case_id = case_ids_by_manifest[manifest_id].get(tuple(row[:6]))
        if case_id is None:
            raise ValueError("stored manifest is missing the P32 job case_id")
        job = ExecutionJob(*row[:5], snapshot, fingerprint, case_id)
        needs_verification = row[5] == verify_job and row[5] not in verified
        if row[5] in done and not needs_verification:
            skipped += 1
            continue
        case = case_for_snapshot(snapshot, case_id)
        factory = factory_for_runtime(snapshot.runtime)
        geometry = generate_frozen_geometry(factory, case, snapshot.realization_seed,
                                             snapshot.runtime, progress_callback)
        if needs_verification:
            verify_job_rqd(connection, job, case, geometry)
            verified.add(row[5])
        records = measure_domain_p32(case, geometry)
        store_measured_p32(connection, job, records)
        if row[5] not in done:
            measured += 1
        done[row[5]] = records
    return {"measured_realizations": measured, "skipped_jobs": skipped,
            "verified_execution_fingerprints": sorted(verified),
            "raw_observations_modified": False, "rqd_measured": bool(verified)}
