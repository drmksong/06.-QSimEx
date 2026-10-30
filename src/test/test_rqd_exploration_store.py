from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.rqd_exploration.config import load_config
from src.rqd_exploration.design import build_frozen_manifest
from src.rqd_exploration.fingerprint import (
    ExecutionRuntime,
    fingerprint_execution_snapshot,
    fingerprint_snapshot,
)
from src.rqd_exploration.measurement import (
    MeasurementEvidence,
    MeasurementResult,
    PlannedLocationState,
    RawBHObservation,
)
from src.rqd_exploration.records import (
    PlannedBHInterval,
    PlannedFaceStation,
    PlannedScanline,
)
from src.rqd_exploration.store import (
    STORE_SCHEMA_VERSION,
    begin_attempt,
    checkpoint_attempt_runtime,
    complete_attempt,
    finish_attempt,
    initialize_store,
    record_measurement_result,
    resume_attempt,
    store_manifest,
)


class TestExplorationStoreSchema(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        initialize_store(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_initialization_is_versioned_idempotent_and_enables_foreign_keys(self) -> None:
        self.assertEqual(
            self.connection.execute("PRAGMA user_version").fetchone()[0],
            STORE_SCHEMA_VERSION,
        )
        self.assertEqual(
            self.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1,
        )
        before = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        initialize_store(self.connection)
        after = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        self.assertEqual(before, after)
        self.assertEqual(len(before), 14)

    def test_rejects_unknown_schema_version_without_creating_tables(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA user_version = 999")
        with self.assertRaisesRegex(ValueError, "unsupported store schema version"):
            initialize_store(connection)
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        self.assertEqual(tables, [])
        connection.close()


class TestFrozenManifestPersistence(unittest.TestCase):
    def setUp(self) -> None:
        config_path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot.yml"
        config = load_config(config_path)
        locations = (
            PlannedBHInterval(
                "fixture-bh", 0, 0.0, 1.0, (0.0, 15.0, 15.0),
                (1.0, 0.0, 0.0), 1.0,
            ),
            PlannedFaceStation(
                "fixture-face", 0, 0.0, (0.0, 15.0, 15.0),
                (1.0, 0.0, 0.0), 78.53981633974483, None,
                (PlannedScanline(
                    0, (0.0, 10.0, 15.0), (0.0, 1.0, 0.0), 10.0,
                ),),
            ),
        )
        runtime = ExecutionRuntime(
            "fixture-generator-v1", "fixture-measurement-v1",
            "fixture-backend", ("fixture-device", "fixture-runtime"),
        )
        self.manifest = build_frozen_manifest(
            config,
            manifest_id="store-fixture",
            runtime=runtime,
            boundary_rules_version="fixture-boundary-v1",
            planned_locations=locations,
        )
        self.connection = sqlite3.connect(":memory:")
        initialize_store(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_persists_manifest_provenance_and_all_composite_key_projections(self) -> None:
        store_manifest(self.connection, self.manifest)

        payload = json.loads(self.manifest.manifest_json)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0], 1,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM input_provenance").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM design_samples").fetchone()[0],
            len(payload["design_samples"]),
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM target_goals").fetchone()[0],
            len(payload["target_goals"]),
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            len(payload["jobs"]),
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM planned_locations").fetchone()[0],
            len(payload["planned_locations"]),
        )

        stored_json = self.connection.execute(
            "SELECT manifest_json FROM manifest WHERE manifest_id = ?",
            (self.manifest.manifest_id,),
        ).fetchone()[0]
        self.assertEqual(stored_json, self.manifest.manifest_json)
        stored_yaml, stored_digest = self.connection.execute(
            "SELECT yaml_bytes, yaml_sha256 FROM input_provenance WHERE manifest_id = ?",
            (self.manifest.manifest_id,),
        ).fetchone()
        self.assertEqual(stored_yaml, self.manifest.source_yaml_bytes)
        self.assertEqual(stored_digest, self.manifest.source_yaml_sha256)

        expected_job = payload["jobs"][0]
        snapshot_bytes, = self.connection.execute(
            """
            SELECT execution_snapshot FROM jobs
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ?
            """,
            (
                expected_job["manifest_id"], expected_job["design_id"],
                expected_job["block_id"], expected_job["sample_index"],
                expected_job["realization_seed"],
                expected_job["execution_fingerprint_digest"],
            ),
        ).fetchone()
        self.assertEqual(
            json.loads(snapshot_bytes),
            expected_job["execution_snapshot"],
        )
        self.assertEqual(
            fingerprint_snapshot(json.loads(snapshot_bytes)).canonical_bytes,
            snapshot_bytes,
        )

    def test_projection_foreign_key_failure_rolls_back_whole_manifest(self) -> None:
        payload = json.loads(self.manifest.manifest_json)
        payload["planned_locations"][-1]["design_id"] = "missing-design"
        broken = replace(
            self.manifest,
            manifest_json=fingerprint_snapshot(payload).canonical_bytes.decode("utf-8"),
        )

        with self.assertRaises(sqlite3.IntegrityError):
            store_manifest(self.connection, broken)

        for table in (
            "manifest", "input_provenance", "design_samples", "target_goals",
            "jobs", "planned_locations",
        ):
            with self.subTest(table=table):
                count = self.connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                self.assertEqual(count, 0)

    def test_rejects_mismatched_payload_and_yaml_provenance_before_write(self) -> None:
        broken = replace(self.manifest, source_yaml_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "source YAML digest"):
            store_manifest(self.connection, broken)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0], 0,
        )

    def test_composite_foreign_keys_and_attempt_state_checks_are_enforced(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO attempts (
                    manifest_id, design_id, block_id, sample_index, realization_seed,
                    execution_fingerprint_digest, attempt_index, status, started_at_utc,
                    finished_at_utc, runtime_seconds, runtime_is_lower_bound
                ) VALUES ('absent', 'd', 'b', 0, 1, ?, 0, 'running',
                          '2026-01-01T00:00:00Z', NULL, 0, 0)
                """,
                ("a" * 64,),
            )

    def _bh_observation(self) -> RawBHObservation:
        return RawBHObservation(
            profile_id="fixture-bh",
            location_index=0,
            start_m=0.0,
            end_m=1.0,
            raw_rqd=100.0,
            support_length_m=1.0,
            method_id="deere_direct_rqd",
            method_version="qsimex-fixed-rqd-v1",
            is_valid=True,
            exclusion_reason=None,
            zero_cross=True,
            evidence=MeasurementEvidence(
                0, (0.0, 15.0, 15.0), (1.0, 0.0, 0.0), 1.0, (),
            ),
        )

    def _partial_bh_result(self) -> MeasurementResult:
        return MeasurementResult(
            planned_locations=(),
            location_states=(
                PlannedLocationState("BH", "fixture-bh", 0, "observed", None),
            ),
            observations=(self._bh_observation(),),
            excluded_bh_tail_lengths_m=(),
            face_stop_reason="tunnel_end",
        )

    def _complete_result(self) -> MeasurementResult:
        return MeasurementResult(
            planned_locations=(),
            location_states=(
                PlannedLocationState("BH", "fixture-bh", 0, "observed", None),
                PlannedLocationState(
                    "face", "fixture-face", 0, "unavailable",
                    "boundary support unavailable",
                ),
            ),
            observations=(self._bh_observation(),),
            excluded_bh_tail_lengths_m=(),
            face_stop_reason="invalid_boundary_face",
        )

    def test_resume_reopens_partial_attempt_and_preserves_known_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "resume.sqlite"
            connection = sqlite3.connect(database_path)
            initialize_store(connection)
            store_manifest(connection, self.manifest)
            job = self.manifest.jobs[0]
            begin_attempt(connection, job, 0, "2026-10-29T11:00:00Z")
            record_measurement_result(
                connection, job, 0, self._partial_bh_result(),
            )
            checkpoint_attempt_runtime(connection, job, 0, 2.0)
            connection.close()

            reopened = sqlite3.connect(database_path)
            initialize_store(reopened)
            state = resume_attempt(reopened, job)
            self.assertEqual(state.attempt_index, 0)
            self.assertEqual(state.accumulated_runtime_seconds, 2.0)
            self.assertTrue(state.runtime_is_lower_bound)
            self.assertEqual(
                [(item.modality, item.profile_id, item.status) for item in state.location_states],
                [("BH", "fixture-bh", "observed"), ("face", "fixture-face", "planned")],
            )

            record_measurement_result(
                reopened,
                job,
                0,
                MeasurementResult(
                    planned_locations=(),
                    location_states=(
                        PlannedLocationState(
                            "face", "fixture-face", 0, "unavailable",
                            "boundary support unavailable",
                        ),
                    ),
                    observations=(),
                    excluded_bh_tail_lengths_m=(),
                    face_stop_reason="invalid_boundary_face",
                ),
            )
            finish_attempt(
                reopened,
                job,
                0,
                status="failed",
                finished_at_utc="2026-10-29T11:00:03Z",
                runtime_seconds=1.5,
            )
            self.assertEqual(
                reopened.execute(
                    """
                    SELECT status, runtime_seconds, runtime_is_lower_bound
                    FROM attempts WHERE attempt_index = 0
                    """
                ).fetchone(),
                ("failed", 3.5, 1),
            )
            self.assertEqual(
                reopened.execute(
                    "SELECT COUNT(*) FROM observations WHERE modality = 'BH'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                reopened.execute(
                    """
                    SELECT modality, status FROM location_status
                    WHERE attempt_index = 0 ORDER BY modality
                    """
                ).fetchall(),
                [("BH", "observed"), ("face", "unavailable")],
            )
            reopened.close()

    def test_complete_attempt_is_atomic_and_rejects_duplicate_completion(self) -> None:
        store_manifest(self.connection, self.manifest)
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")

        with self.assertRaisesRegex(ValueError, "planned locations"):
            complete_attempt(
                self.connection,
                job,
                0,
                self._partial_bh_result(),
                finished_at_utc="2026-10-29T11:00:01Z",
                runtime_seconds=1.0,
            )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM attempts WHERE attempt_index = 0"
            ).fetchone()[0],
            "running",
        )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT status FROM location_status
                WHERE modality = 'BH' AND attempt_index = 0
                """
            ).fetchone()[0],
            "planned",
        )

        complete_attempt(
            self.connection,
            job,
            0,
            self._complete_result(),
            finished_at_utc="2026-10-29T11:00:02Z",
            runtime_seconds=2.0,
        )
        with self.assertRaisesRegex(ValueError, "running attempt"):
            complete_attempt(
                self.connection,
                job,
                0,
                self._complete_result(),
                finished_at_utc="2026-10-29T11:00:03Z",
                runtime_seconds=1.0,
            )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT status, runtime_seconds, runtime_is_lower_bound
                FROM attempts WHERE attempt_index = 0
                """
            ).fetchone(),
            ("succeeded", 2.0, 0),
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM location_status
                WHERE modality = 'face' AND status = 'unavailable'
                """
            ).fetchone()[0],
            1,
        )

    def test_resume_rejects_fingerprint_mismatch_without_mutation(self) -> None:
        store_manifest(self.connection, self.manifest)
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")
        changed_snapshot = replace(
            job.snapshot,
            runtime=replace(
                job.snapshot.runtime,
                generator_version="different-generator-version",
            ),
        )
        changed_job = replace(
            job,
            snapshot=changed_snapshot,
            fingerprint=fingerprint_execution_snapshot(changed_snapshot),
        )

        with self.assertRaisesRegex(ValueError, "fingerprint"):
            resume_attempt(self.connection, changed_job)
        self.assertEqual(
            self.connection.execute(
                """
                SELECT status, runtime_seconds, runtime_is_lower_bound
                FROM attempts WHERE attempt_index = 0
                """
            ).fetchone(),
            ("running", 0.0, 0),
        )

    def test_resume_rejects_corrupt_location_checkpoint_without_mutation(self) -> None:
        store_manifest(self.connection, self.manifest)
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")
        self.connection.execute(
            """
            DELETE FROM location_status
            WHERE attempt_index = 0 AND modality = 'face'
            """
        )

        with self.assertRaisesRegex(ValueError, "does not match the frozen plan"):
            resume_attempt(self.connection, job)
        self.assertEqual(
            self.connection.execute(
                """
                SELECT runtime_is_lower_bound FROM attempts WHERE attempt_index = 0
                """
            ).fetchone()[0],
            0,
        )

    def test_only_one_running_attempt_can_exist_per_job(self) -> None:
        store_manifest(self.connection, self.manifest)
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")

        with self.assertRaises(sqlite3.IntegrityError):
            begin_attempt(self.connection, job, 1, "2026-10-29T11:00:01Z")
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE status = 'running'"
            ).fetchone()[0],
            1,
        )

    def test_attempt_observation_and_evidence_are_written_atomically(self) -> None:
        store_manifest(self.connection, self.manifest)
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")
        planned_bh = PlannedLocationState("BH", "fixture-bh", 0, "observed", None)
        unavailable_face = PlannedLocationState(
            "face", "fixture-face", 0, "unavailable", "boundary support unavailable",
        )
        observation = RawBHObservation(
            profile_id="fixture-bh",
            location_index=0,
            start_m=0.0,
            end_m=1.0,
            raw_rqd=100.0,
            support_length_m=1.0,
            method_id="deere_direct_rqd",
            method_version="qsimex-fixed-rqd-v1",
            is_valid=True,
            exclusion_reason=None,
            zero_cross=True,
            evidence=MeasurementEvidence(
                0, (0.0, 15.0, 15.0), (1.0, 0.0, 0.0), 1.0, (),
            ),
        )
        result = MeasurementResult(
            planned_locations=(),
            location_states=(planned_bh, unavailable_face),
            observations=(observation,),
            excluded_bh_tail_lengths_m=(),
            face_stop_reason="invalid_boundary_face",
        )
        record_measurement_result(self.connection, job, 0, result)
        finish_attempt(
            self.connection,
            job,
            0,
            status="failed",
            finished_at_utc="2026-10-29T11:00:01Z",
            runtime_seconds=1.0,
        )

        status_rows = self.connection.execute(
            """
            SELECT modality, status FROM location_status
            WHERE manifest_id = ? AND design_id = ? AND block_id = ?
              AND sample_index = ? AND realization_seed = ?
              AND execution_fingerprint_digest = ? AND attempt_index = 0
            ORDER BY modality
            """,
            (
                job.manifest_id, job.design_id, job.block_id, job.sample_index,
                job.realization_seed, job.fingerprint.sha256_hex,
            ),
        ).fetchall()
        self.assertEqual(status_rows, [("BH", "observed"), ("face", "unavailable")])
        self.assertEqual(
            self.connection.execute(
                "SELECT raw_rqd, support_length_m FROM observations"
            ).fetchone(),
            (100.0, 1.0),
        )
        evidence = self.connection.execute(
            "SELECT intersection_positions_json FROM measurement_evidence"
        ).fetchone()[0]
        self.assertEqual(json.loads(evidence), [])
        self.assertEqual(
            self.connection.execute(
                "SELECT status, runtime_seconds FROM attempts"
            ).fetchone(),
            ("failed", 1.0),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                UPDATE location_status SET status = 'unavailable'
                WHERE modality = 'BH' AND profile_id = 'fixture-bh'
                """
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "DELETE FROM observations WHERE modality = 'BH'"
            )

    def test_attempt_duplicate_and_invalid_measurement_rollback_without_partial_rows(self) -> None:
        store_manifest(self.connection, self.manifest)
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")
        with self.assertRaises(sqlite3.IntegrityError):
            begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM location_status WHERE attempt_index = 0"
            ).fetchone()[0],
            2,
        )
        with self.assertRaises(ValueError):
            finish_attempt(
                self.connection,
                job,
                0,
                status="running",
                finished_at_utc="2026-10-29T11:00:01Z",
                runtime_seconds=1.0,
            )
        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM attempts WHERE attempt_index = 0"
            ).fetchone()[0],
            "running",
        )

    def test_non_finite_measurement_values_are_rejected_atomically(self) -> None:
        store_manifest(self.connection, self.manifest)
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-29T11:00:00Z")
        state = PlannedLocationState("BH", "fixture-bh", 0, "observed", None)
        observation = RawBHObservation(
            profile_id="fixture-bh",
            location_index=0,
            start_m=0.0,
            end_m=1.0,
            raw_rqd=100.0,
            support_length_m=float("inf"),
            method_id="deere_direct_rqd",
            method_version="qsimex-fixed-rqd-v1",
            is_valid=True,
            exclusion_reason=None,
            zero_cross=True,
            evidence=MeasurementEvidence(
                0, (0.0, 15.0, 15.0), (1.0, 0.0, 0.0), 1.0, (),
            ),
        )
        result = MeasurementResult(
            planned_locations=(),
            location_states=(state,),
            observations=(observation,),
            excluded_bh_tail_lengths_m=(),
            face_stop_reason="tunnel_end",
        )
        with self.assertRaisesRegex(ValueError, "support_length_m must be finite"):
            record_measurement_result(self.connection, job, 0, result)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM location_status WHERE modality = 'BH'"
            ).fetchone()[0],
            "planned",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO attempts (
                    manifest_id, design_id, block_id, sample_index, realization_seed,
                    execution_fingerprint_digest, attempt_index, status, started_at_utc,
                    finished_at_utc, runtime_seconds, runtime_is_lower_bound
                ) VALUES ('absent', 'd', 'b', 0, 1, ?, 0, 'succeeded',
                          '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', 0, 0)
                """,
                ("a" * 64,),
            )
