from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.rqd_exploration.analysis import (
    build_analysis_snapshot,
    build_cumulative_analysis_snapshot,
    fingerprint_raw_dataset,
)
from src.rqd_exploration.config import load_config
from src.rqd_exploration.dataset import (
    load_latest_cumulative_dataset_revision,
    load_latest_dataset_revision,
    persist_cumulative_analysis_run,
    persist_cumulative_derived_scores,
    persist_analysis_run,
    persist_derived_scores,
)
from src.rqd_exploration.design import build_frozen_manifest
from src.rqd_exploration.fingerprint import ExecutionRuntime
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
    begin_attempt,
    finish_attempt,
    initialize_store,
    record_measurement_result,
    store_manifest,
)


class TestRawDatasetRevisionLoader(unittest.TestCase):
    def setUp(self) -> None:
        config_path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
        self.config = load_config(config_path)
        runtime = ExecutionRuntime(
            "fixture-generator-v1",
            "fixture-measurement-v1",
            "fixture-backend",
            ("fixture-device", "fixture-runtime"),
        )
        self.manifest = build_frozen_manifest(
            self.config,
            manifest_id="dataset-fixture",
            runtime=runtime,
            boundary_rules_version="fixture-boundary-v1",
            planned_locations=(
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
            ),
        )
        self.connection = sqlite3.connect(":memory:")
        initialize_store(self.connection)
        store_manifest(self.connection, self.manifest)

    def tearDown(self) -> None:
        self.connection.close()

    def _bh_observation(self, raw_rqd: float) -> RawBHObservation:
        return RawBHObservation(
            profile_id="fixture-bh",
            location_index=0,
            start_m=0.0,
            end_m=1.0,
            raw_rqd=raw_rqd,
            support_length_m=1.0,
            method_id="deere_direct_rqd",
            method_version="qsimex-fixed-rqd-v1",
            is_valid=True,
            exclusion_reason=None,
            zero_cross=True,
            evidence=MeasurementEvidence(
                0, (0.0, 15.0, 15.0), (1.0, 0.0, 0.0), 1.0, (0.25, 0.75),
            ),
        )

    def _write_failed_attempt(self) -> None:
        job = self.manifest.jobs[0]
        begin_attempt(self.connection, job, 0, "2026-10-30T00:00:00Z")
        record_measurement_result(
            self.connection,
            job,
            0,
            MeasurementResult(
                planned_locations=(),
                location_states=(
                    PlannedLocationState("BH", "fixture-bh", 0, "observed", None),
                ),
                observations=(self._bh_observation(40.0),),
                excluded_bh_tail_lengths_m=(),
                face_stop_reason="tunnel_end",
            ),
        )
        finish_attempt(
            self.connection,
            job,
            0,
            status="failed",
            finished_at_utc="2026-10-30T00:00:01Z",
            runtime_seconds=1.0,
        )

    def _write_successful_attempt(
        self,
        manifest=None,
        *,
        connection: sqlite3.Connection | None = None,
        attempt_index: int = 1,
        raw_rqd: float = 80.0,
    ) -> None:
        target_connection = connection or self.connection
        selected_manifest = manifest or self.manifest
        job = selected_manifest.jobs[0]
        begin_attempt(
            target_connection,
            job,
            attempt_index,
            f"2026-10-30T00:01:{attempt_index:02d}Z",
        )
        record_measurement_result(
            target_connection,
            job,
            attempt_index,
            MeasurementResult(
                planned_locations=(),
                location_states=(
                    PlannedLocationState("BH", "fixture-bh", 0, "observed", None),
                    PlannedLocationState(
                        "face", "fixture-face", 0, "unavailable",
                        "boundary support unavailable",
                    ),
                ),
                observations=(self._bh_observation(raw_rqd),),
                excluded_bh_tail_lengths_m=(),
                face_stop_reason="invalid_boundary_face",
            ),
        )
        finish_attempt(
            target_connection,
            job,
            attempt_index,
            status="succeeded",
            finished_at_utc=f"2026-10-30T00:01:{attempt_index + 2:02d}Z",
            runtime_seconds=2.0,
        )

    def test_selects_highest_successful_attempt_and_persists_revision_once(self) -> None:
        self._write_failed_attempt()
        self._write_successful_attempt()

        revision = load_latest_dataset_revision(
            self.connection,
            self.manifest.manifest_id,
        )

        self.assertEqual(revision.revision_index, 1)
        self.assertEqual(len(revision.observations), 1)
        self.assertEqual(revision.observations[0].raw_rqd, 80.0)
        self.assertEqual(revision.observations[0].execution_fingerprint_digest,
                         self.manifest.jobs[0].fingerprint.sha256_hex)
        selected_job = self.manifest.jobs[0]
        selected_states = [
            item for item in revision.location_states
            if (
                item.design_id == selected_job.design_id
                and item.block_id == selected_job.block_id
                and item.sample_index == selected_job.sample_index
                and item.realization_seed == selected_job.realization_seed
                and item.execution_fingerprint_digest
                == selected_job.fingerprint.sha256_hex
            )
        ]
        self.assertEqual(
            [(item.status, item.reason) for item in selected_states],
            [("observed", None), ("unavailable", "boundary support unavailable")],
        )
        self.assertTrue(all(
            item.status == "planned" and item.reason is None
            for item in revision.location_states
            if item not in selected_states
        ))
        snapshot_bytes = self.connection.execute(
            """
            SELECT dataset_snapshot, dataset_sha256 FROM dataset_revisions
            WHERE manifest_id = ? AND revision_index = 1
            """,
            (self.manifest.manifest_id,),
        ).fetchone()
        snapshot = json.loads(snapshot_bytes[0])
        self.assertEqual(snapshot_bytes[1], fingerprint_raw_dataset(snapshot).sha256_hex)
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertNotIn("attempt_index", snapshot["observations"][0])
        self.assertNotIn(
            "execution_fingerprint_digest",
            snapshot["observations"][0],
        )
        self.assertEqual(len(snapshot["measurement_evidence"]), 1)
        self.assertEqual(
            snapshot["measurement_evidence"][0]["intersection_positions_m"],
            [0.25, 0.75],
        )

        second = load_latest_dataset_revision(
            self.connection,
            self.manifest.manifest_id,
        )
        self.assertEqual(second.dataset_sha256, revision.dataset_sha256)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM dataset_revisions WHERE manifest_id = ?",
                (self.manifest.manifest_id,),
            ).fetchone()[0],
            1,
        )

    def test_no_successful_attempt_preserves_planned_locations_without_observations(self) -> None:
        revision = load_latest_dataset_revision(
            self.connection,
            self.manifest.manifest_id,
        )

        self.assertEqual(revision.observations, ())
        self.assertEqual(len(revision.location_states), 20)
        self.assertTrue(all(item.status == "planned" for item in revision.location_states))

    def test_rejects_legacy_store_without_schema_migration(self) -> None:
        self._write_successful_attempt()
        load_latest_dataset_revision(self.connection, self.manifest.manifest_id)
        self.connection.execute("DROP TABLE dataset_revision_observations")
        self.connection.execute("PRAGMA user_version = 1")

        with self.assertRaisesRegex(ValueError, "unsupported store schema version: 1"):
            initialize_store(self.connection)

    def test_cumulative_revision_appends_batches_and_counts_duplicate_realization_once(
        self,
    ) -> None:
        self._write_successful_attempt()
        first = load_latest_cumulative_dataset_revision(self.connection)

        self.assertEqual(first.revision_index, 1)
        self.assertIsNone(first.previous_revision_index)
        self.assertEqual(first.manifest_ids, (self.manifest.manifest_id,))
        self.assertEqual(len(first.observations), 1)
        self.assertEqual(first.independent_realization_count, 1)
        self.assertEqual(len(first.source_attempt_indices), 1)

        second_manifest = build_frozen_manifest(
            self.config,
            manifest_id="dataset-fixture-copy",
            runtime=self.manifest.jobs[0].snapshot.runtime,
            boundary_rules_version="fixture-boundary-v1",
            planned_locations=(
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
            ),
        )
        self.assertEqual(
            second_manifest.jobs[0].fingerprint.sha256_hex,
            self.manifest.jobs[0].fingerprint.sha256_hex,
        )
        store_manifest(self.connection, second_manifest)
        self._write_successful_attempt(second_manifest, attempt_index=0)

        second = load_latest_cumulative_dataset_revision(self.connection)
        self.assertEqual(second.revision_index, 2)
        self.assertEqual(second.previous_revision_index, 1)
        self.assertEqual(
            second.manifest_ids,
            tuple(sorted((self.manifest.manifest_id, second_manifest.manifest_id))),
        )
        self.assertEqual(len(second.observations), 2)
        self.assertEqual(len(second.source_attempt_indices), 2)
        self.assertEqual(second.independent_realization_count, 1)
        self.assertEqual(len(second.location_states), 40)
        self.assertEqual(second.raw_attempt_count, 1)
        self.assertEqual(second.raw_observation_count, 2)
        self.assertEqual(
            second.dataset_sha256,
            fingerprint_raw_dataset(second.dataset_snapshot).sha256_hex,
        )

        old_revision = load_latest_cumulative_dataset_revision(self.connection, 1)
        self.assertEqual(old_revision.dataset_sha256, first.dataset_sha256)
        self.assertEqual(len(old_revision.observations), 1)
        repeated = load_latest_cumulative_dataset_revision(self.connection)
        self.assertEqual(repeated.revision_index, 2)
        self.assertEqual(repeated.dataset_sha256, second.dataset_sha256)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM cumulative_dataset_revisions",
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM cumulative_revision_observations
                WHERE revision_index = 2
                """,
            ).fetchone()[0],
            2,
        )

    def test_cumulative_scores_are_reproducible_without_mutating_raw_data(self) -> None:
        self._write_successful_attempt()
        second_manifest = build_frozen_manifest(
            self.config,
            manifest_id="dataset-analysis-copy",
            runtime=self.manifest.jobs[0].snapshot.runtime,
            boundary_rules_version="fixture-boundary-v1",
            planned_locations=(
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
            ),
        )
        store_manifest(self.connection, second_manifest)
        self._write_successful_attempt(
            second_manifest,
            attempt_index=0,
            raw_rqd=60.0,
        )
        revision = load_latest_cumulative_dataset_revision(self.connection)
        raw_rows_before = self.connection.execute(
            """
            SELECT manifest_id, raw_rqd, attempt_index
            FROM observations ORDER BY manifest_id, attempt_index
            """
        ).fetchall()
        self.assertEqual(len(revision.observations), 2)

        first_snapshot = build_cumulative_analysis_snapshot(
            revision.revision_index,
            revision.dataset_sha256,
            jr_values=(0.5, 2.0),
            ja_values=(1.0,),
        )
        first_fingerprint = persist_cumulative_analysis_run(
            self.connection,
            revision,
            first_snapshot,
        )
        self.assertEqual(
            persist_cumulative_derived_scores(
                self.connection,
                revision,
                first_fingerprint,
            ),
            4,
        )
        self.assertEqual(
            persist_cumulative_derived_scores(
                self.connection,
                revision,
                first_fingerprint,
            ),
            4,
        )

        second_snapshot = build_cumulative_analysis_snapshot(
            revision.revision_index,
            revision.dataset_sha256,
            jr_values=(1.0,),
            ja_values=(2.0, 4.0),
        )
        second_fingerprint = persist_cumulative_analysis_run(
            self.connection,
            revision,
            second_snapshot,
        )
        self.assertNotEqual(first_fingerprint, second_fingerprint)
        self.assertEqual(
            persist_cumulative_derived_scores(
                self.connection,
                revision,
                second_fingerprint,
            ),
            4,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM cumulative_analysis_runs"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM cumulative_derived_scores"
            ).fetchone()[0],
            8,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM cumulative_revision_observations"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT manifest_id, raw_rqd, attempt_index
                FROM observations ORDER BY manifest_id, attempt_index
                """
            ).fetchall(),
            raw_rows_before,
        )

    def test_cumulative_revision_preserves_planned_state_without_successful_attempt(
        self,
    ) -> None:
        revision = load_latest_cumulative_dataset_revision(self.connection)
        self.assertEqual(revision.observations, ())
        self.assertEqual(len(revision.location_states), 20)
        self.assertTrue(all(
            item.status == "planned" for item in revision.location_states
        ))
        self.assertEqual(revision.independent_realization_count, 0)
        self._write_successful_attempt()
        completed_revision = load_latest_cumulative_dataset_revision(self.connection)
        self.assertEqual(completed_revision.revision_index, 2)
        self.assertEqual(completed_revision.previous_revision_index, 1)
        self.assertTrue(any(
            item.status == "observed" for item in completed_revision.location_states
        ))
        self.assertTrue(all(
            item.status == "planned" for item in revision.location_states
        ))

    def test_cumulative_revision_and_provenance_are_immutable(self) -> None:
        self._write_successful_attempt()
        revision = load_latest_cumulative_dataset_revision(self.connection)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.connection.execute(
                """
                UPDATE cumulative_dataset_revisions
                SET dataset_sha256 = ? WHERE revision_index = ?
                """,
                ("0" * 64, revision.revision_index),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.connection.execute(
                """
                DELETE FROM cumulative_revision_observations
                WHERE revision_index = ?
                """,
                (revision.revision_index,),
            )

    def test_cumulative_revision_survives_database_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "cumulative.sqlite"
            connection = sqlite3.connect(database)
            initialize_store(connection)
            store_manifest(connection, self.manifest)
            self._write_successful_attempt(connection=connection)
            created = load_latest_cumulative_dataset_revision(connection)
            connection.close()

            reopened = sqlite3.connect(database)
            initialize_store(reopened)
            loaded = load_latest_cumulative_dataset_revision(reopened, 1)
            self.assertEqual(loaded.dataset_sha256, created.dataset_sha256)
            self.assertEqual(loaded.manifest_ids, created.manifest_ids)
            self.assertEqual(loaded.raw_attempt_count, created.raw_attempt_count)
            self.assertEqual(loaded.raw_observation_count, created.raw_observation_count)
            self.assertEqual(loaded.observations, created.observations)
            self.assertEqual(loaded.location_states, created.location_states)
            reopened.close()

    def test_analysis_run_registration_is_idempotent_and_revision_is_verified(self) -> None:
        self._write_failed_attempt()
        self._write_successful_attempt()
        revision = load_latest_dataset_revision(
            self.connection,
            self.manifest.manifest_id,
        )
        analysis_snapshot = build_analysis_snapshot(
            revision.revision_index,
            revision.dataset_sha256,
        )

        first = persist_analysis_run(self.connection, revision, analysis_snapshot)
        second = persist_analysis_run(self.connection, revision, analysis_snapshot)
        first_score_count = persist_derived_scores(self.connection, revision, first)
        second_score_count = persist_derived_scores(self.connection, revision, second)

        self.assertEqual(first, second)
        self.assertEqual(first_score_count, 66)
        self.assertEqual(second_score_count, 66)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM derived_scores").fetchone()[0],
            66,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM dataset_revision_observations"
            ).fetchone()[0],
            1,
        )
        source_key, attempt_index = revision.source_attempt_indices[0]
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.connection.execute(
                """
                INSERT INTO dataset_revision_observations (
                    manifest_id, revision_index, design_id, block_id, sample_index,
                    realization_seed, execution_fingerprint_digest, attempt_index,
                    modality, profile_id, location_index
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.manifest.manifest_id,
                    *source_key[:5],
                    attempt_index,
                    *source_key[5:],
                ),
            )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
            1,
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.connection.execute(
                """
                UPDATE dataset_revisions SET dataset_sha256 = ?
                WHERE manifest_id = ? AND revision_index = 1
                """,
                ("0" * 64, self.manifest.manifest_id),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.connection.execute(
                "DELETE FROM dataset_revisions WHERE manifest_id = ?",
                (self.manifest.manifest_id,),
            )
        verified = load_latest_dataset_revision(
            self.connection,
            self.manifest.manifest_id,
        )
        self.assertEqual(verified.dataset_sha256, revision.dataset_sha256)

        cumulative = load_latest_cumulative_dataset_revision(self.connection)
        batch = cumulative.dataset_snapshot["batches"][0]
        self.assertEqual(cumulative.raw_attempt_count, 2)
        self.assertEqual(cumulative.raw_observation_count, 2)
        self.assertEqual(len(cumulative.observations), 1)
        self.assertEqual(
            [
                (item["status"], item["selected_for_analysis"])
                for item in batch["attempt_history"]
            ],
            [("failed", False), ("succeeded", True)],
        )
        self.assertEqual(
            [
                item["observations"][0]["raw_rqd"]
                for item in batch["attempt_history"]
            ],
            [40.0, 80.0],
        )
        self.assertEqual(
            batch["attempt_history"][0]["location_states"][0]["status"],
            "observed",
        )
        self.assertEqual(
            len(batch["attempt_history"][0]["observations"][0]["measurement_evidence"]),
            1,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM cumulative_revision_observations",
            ).fetchone()[0],
            2,
        )
        self.assertEqual(
            self.connection.execute(
                """
                SELECT status, selected_for_analysis
                FROM cumulative_revision_attempts ORDER BY attempt_index
                """,
            ).fetchall(),
            [("failed", 0), ("succeeded", 1)],
        )


if __name__ == "__main__":
    unittest.main()
