from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.rqd_exploration.config import load_config
from src.rqd_exploration.fingerprint import (
    execution_snapshot_payload,
    fingerprint_snapshot,
)
from src.rqd_exploration.measurement import (
    FACE_BOUNDARY_RULES_VERSION,
    MEASUREMENT_VERSION,
    MeasurementResult,
    PlannedLocationState,
    PlannedBHInterval,
)
from src.rqd_exploration.runner import (
    build_mlx_pilot_manifest,
    execute_frozen_jobs,
)
from src.rqd_exploration.store import (
    begin_attempt,
    initialize_store,
    job_attempt_statuses,
    record_measurement_result,
    store_manifest,
)


class TestPilotManifestProducer(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot.yml"
        self.config = load_config(path)

    def build_manifest(self):
        mlx_backend = SimpleNamespace(
            MLX_GENERATOR_VERSION="qsimex-mlx-generation-v1",
            require_mlx_gpu=lambda: ("0.31.1", "Device(gpu, 0)"),
        )
        with patch.dict(sys.modules, {
            "src.euler_campaign.mlx_backend": mlx_backend,
        }):
            return build_mlx_pilot_manifest(
                self.config, manifest_id="pilot-mlx-fixture",
            )

    def test_builds_mlx_manifest_with_complete_geometry_plan_without_simulation(self) -> None:
        manifest = self.build_manifest()
        payload = json.loads(manifest.manifest_json)
        canonical = fingerprint_snapshot(payload)
        self.assertEqual(
            manifest.manifest_json.encode("utf-8"), canonical.canonical_bytes,
        )
        self.assertEqual(
            payload["input_provenance"]["yaml_sha256"],
            manifest.source_yaml_sha256,
        )
        self.assertEqual(manifest.source_yaml_bytes, self.config.source_yaml_bytes)
        self.assertEqual(payload["manifest_id"], manifest.manifest_id)
        self.assertEqual(len(manifest.jobs), 10)
        self.assertEqual(len(payload["planned_locations"]), 1210)
        self.assertEqual(len(payload["design_samples"]), 10)
        self.assertEqual(len(payload["jobs"]), 10)
        self.assertEqual(len(payload["target_goals"]), 6)
        self.assertEqual(
            sum(item["modality"] == "BH" for item in payload["planned_locations"]),
            600,
        )
        self.assertEqual(
            sum(item["modality"] == "face" for item in payload["planned_locations"]),
            610,
        )
        self.assertEqual(
            len({job.fingerprint.sha256_hex for job in manifest.jobs}), 10,
        )
        self.assertTrue(all(
            count * spacing == size
            for count, spacing, size in zip(
                self.config.geometry.cell_counts,
                self.config.geometry.grid_spacing_m,
                self.config.geometry.domain_size_m,
            )
        ))

        location_groups: dict[tuple[str, str, int], list[dict]] = {}
        job_by_sample = {
            (job.design_id, job.block_id, job.sample_index): job
            for job in manifest.jobs
        }
        self.assertEqual(len(job_by_sample), 10)
        for item in payload["planned_locations"]:
            key = (item["design_id"], item["block_id"], item["sample_index"])
            location_groups.setdefault(key, []).append(item)
            job = job_by_sample[key]
            self.assertEqual(item["manifest_id"], manifest.manifest_id)
            self.assertEqual(
                item["execution_fingerprint_digest"], job.fingerprint.sha256_hex,
            )
            self.assertEqual(item["realization_seed"], job.realization_seed)
            self.assertNotIn("raw_rqd", item)
            self.assertNotIn("support_area_m2", item)
            self.assertNotIn("support_length_m", item)
        self.assertEqual(set(location_groups), set(job_by_sample))

        payload_jobs = {
            (item["design_id"], item["block_id"], item["sample_index"]): item
            for item in payload["jobs"]
        }
        self.assertEqual(set(payload_jobs), set(job_by_sample))
        for key, job in job_by_sample.items():
            serialized_job = payload_jobs[key]
            self.assertEqual(
                serialized_job["execution_fingerprint_digest"],
                job.fingerprint.sha256_hex,
            )
            self.assertEqual(
                serialized_job["execution_snapshot"],
                json.loads(json.dumps(execution_snapshot_payload(job.snapshot))),
            )
            snapshot_hash = fingerprint_snapshot(serialized_job["execution_snapshot"])
            self.assertEqual(snapshot_hash, job.fingerprint)

        for locations in location_groups.values():
            boreholes = [item for item in locations if item["modality"] == "BH"]
            faces = [item for item in locations if item["modality"] == "face"]
            self.assertEqual(len(boreholes), 60)
            self.assertEqual(len(faces), 61)
            self.assertEqual([item["profile_id"] for item in boreholes], ["pilot-bh"] * 60)
            self.assertEqual([item["location_index"] for item in boreholes], list(range(60)))
            self.assertEqual(
                [(item["start_m"], item["end_m"]) for item in boreholes],
                [(float(index), float(index + 1)) for index in range(60)],
            )
            self.assertEqual(
                [item["planned_support_length_m"] for item in boreholes],
                [1.0] * 60,
            )
            self.assertEqual(
                [item["start_enu_m"] for item in boreholes],
                [[float(index), 15.0, 15.0] for index in range(60)],
            )
            self.assertTrue(all(
                item["direction_enu"] == [1.0, 0.0, 0.0]
                for item in boreholes
            ))

            self.assertEqual([item["profile_id"] for item in faces], ["tunnel-face"] * 61)
            self.assertEqual([item["location_index"] for item in faces], list(range(61)))
            self.assertEqual(
                [item["chainage_m"] for item in faces],
                list(map(float, range(61))),
            )
            self.assertEqual(
                [item["center_enu_m"] for item in faces],
                [[float(index), 15.0, 15.0] for index in range(61)],
            )
            self.assertTrue(all(
                item["normal_enu"] == [1.0, 0.0, 0.0]
                for item in faces
            ))
            self.assertEqual(faces[0]["advance_distance_m"], None)
            self.assertTrue(all(item["advance_distance_m"] == 1.0 for item in faces[1:]))
            self.assertTrue(all(
                math.isclose(
                    item["planned_support_area_m2"],
                    math.pi * self.config.geometry.tunnel_radius_m ** 2,
                )
                for item in faces
            ))
            for face in faces:
                self.assertEqual(len(face["scanlines"]), 1)
                self.assertEqual(
                    face["scanlines"][0]["scanline_index"], 0,
                )
                self.assertEqual(
                    face["scanlines"][0]["start_enu_m"],
                    [face["chainage_m"], 10.0, 15.0],
                )
                self.assertEqual(
                    face["scanlines"][0]["direction_enu"], [0.0, 1.0, 0.0],
                )
                self.assertEqual(face["scanlines"][0]["planned_length_m"], 10.0)

        for job in manifest.jobs:
            runtime = job.snapshot.runtime
            design = next(
                item for item in self.config.designs
                if item.design_id == job.design_id
            )
            self.assertEqual(runtime.generator_version, "qsimex-mlx-generation-v1")
            self.assertEqual(runtime.measurement_version, MEASUREMENT_VERSION)
            self.assertEqual(runtime.backend, "mlx")
            self.assertIn("mlx_version=0.31.1", runtime.device_runtime)
            self.assertIn("device=Device(gpu, 0)", runtime.device_runtime)
            self.assertEqual(
                job.snapshot.measurements.boundary_rules_version,
                FACE_BOUNDARY_RULES_VERSION,
            )
            self.assertEqual(job.snapshot.geometry.domain_size_m, (60.0, 30.0, 30.0))
            self.assertEqual(job.snapshot.geometry.grid_spacing_m, (1.0, 1.0, 1.0))
            self.assertEqual(
                job.snapshot.geometry.tunnel_vertices_m,
                self.config.geometry.tunnel_vertices_m,
            )
            self.assertEqual(
                job.snapshot.geometry.tunnel_radius_m,
                self.config.geometry.tunnel_radius_m,
            )
            self.assertEqual(
                job.snapshot.geometry.borehole_start_m,
                self.config.geometry.borehole_start_m,
            )
            self.assertEqual(
                job.snapshot.geometry.borehole_direction_enu,
                self.config.geometry.borehole_direction_enu,
            )
            self.assertEqual(job.snapshot.geometry.borehole_length_m, 60.0)
            self.assertEqual(job.snapshot.measurements.bh_interval_m, 1.0)
            self.assertEqual(job.snapshot.measurements.face_advance_m, 1.0)
            self.assertEqual(job.snapshot.fixed_jn, design.fixed_jn)

    def test_mlx_preflight_failure_is_not_replaced_by_a_cpu_fallback(self) -> None:
        def fail_preflight():
            raise RuntimeError("no MLX GPU available")

        mlx_backend = SimpleNamespace(
            MLX_GENERATOR_VERSION="qsimex-mlx-generation-v1",
            require_mlx_gpu=fail_preflight,
        )
        with patch.dict(sys.modules, {
            "src.euler_campaign.mlx_backend": mlx_backend,
        }), self.assertRaisesRegex(RuntimeError, "no MLX GPU"):
            build_mlx_pilot_manifest(self.config, manifest_id="pilot-mlx-fixture")


class TestFrozenJobExecution(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot.yml"
        self.config = load_config(path)
        mlx_backend = SimpleNamespace(
            MLX_GENERATOR_VERSION="qsimex-mlx-generation-v1",
            require_mlx_gpu=lambda: ("0.31.1", "Device(gpu, 0)"),
        )
        with patch.dict(sys.modules, {
            "src.euler_campaign.mlx_backend": mlx_backend,
        }):
            self.manifest = build_mlx_pilot_manifest(
                self.config, manifest_id="pilot-runner-fixture",
            )
        self.fake_factory = SimpleNamespace(generate=lambda case, seed: (case, seed))

    @staticmethod
    def _measurement_result(case, *, reason: str) -> MeasurementResult:
        from src.rqd_exploration.measurement import plan_measurement_locations

        locations = plan_measurement_locations(case)
        states = tuple(
            PlannedLocationState(
                "BH" if isinstance(location, PlannedBHInterval) else "face",
                location.profile_id,
                location.location_index,
                "unavailable",
                reason,
            )
            for location in locations
        )
        return MeasurementResult(
            planned_locations=locations,
            location_states=states,
            observations=(),
            excluded_bh_tail_lengths_m=(),
            face_stop_reason="tunnel_end",
        )

    def test_interrupted_run_reopens_skips_completed_jobs_and_resumes_same_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "pilot-test.sqlite"
            connection = sqlite3.connect(database_path)
            initialize_store(connection)
            store_manifest(connection, self.manifest)

            first_calls: list[int] = []
            interrupted_job = self.manifest.jobs[1]

            def interrupt_on_second_job(case, factory, seed):
                self.assertTrue(callable(factory.generate))
                first_calls.append(seed)
                if len(first_calls) == 2:
                    raise KeyboardInterrupt
                return self._measurement_result(case, reason="completed before interruption")

            with patch(
                "src.rqd_exploration.runner.generate_and_measure",
                side_effect=interrupt_on_second_job,
            ), self.assertRaises(KeyboardInterrupt):
                execute_frozen_jobs(
                    connection, self.manifest, self.config, self.fake_factory,
                    maximum_simulations=10,
                )

            self.assertEqual(len(first_calls), 2)
            self.assertEqual(
                job_attempt_statuses(connection, self.manifest.jobs[0]),
                ((0, "succeeded"),),
            )
            self.assertEqual(
                job_attempt_statuses(connection, interrupted_job),
                ((0, "running"),),
            )
            record_measurement_result(
                connection,
                interrupted_job,
                0,
                MeasurementResult(
                    planned_locations=(),
                    location_states=(
                        PlannedLocationState(
                            "BH", "pilot-bh", 0, "unavailable",
                            "persisted before process interruption",
                        ),
                    ),
                    observations=(),
                    excluded_bh_tail_lengths_m=(),
                    face_stop_reason="tunnel_end",
                ),
            )
            connection.close()

            reopened = sqlite3.connect(database_path)
            initialize_store(reopened)
            resumed_calls: list[int] = []

            def finish_resumed_job(case, factory, seed):
                self.assertTrue(callable(factory.generate))
                resumed_calls.append(seed)
                return self._measurement_result(case, reason="measured after resume")

            with patch(
                "src.rqd_exploration.runner.generate_and_measure",
                side_effect=finish_resumed_job,
            ):
                summary = execute_frozen_jobs(
                    reopened, self.manifest, self.config, self.fake_factory,
                    maximum_simulations=len(self.manifest.jobs) - 1,
                )

            self.assertEqual(len(summary.skipped_completed_job_keys), 1)
            self.assertEqual(summary.skipped_completed_job_keys[0][3], 0)
            self.assertEqual(len(summary.completed_job_keys), len(self.manifest.jobs) - 1)
            self.assertEqual(summary.simulation_count, len(self.manifest.jobs) - 1)
            self.assertEqual(
                summary.maximum_simulations, len(self.manifest.jobs) - 1,
            )
            self.assertEqual(summary.termination_reason, "jobs_complete")
            self.assertEqual(summary.goal_statuses, ())
            self.assertEqual(len(resumed_calls), len(self.manifest.jobs) - 1)
            self.assertEqual(
                job_attempt_statuses(reopened, self.manifest.jobs[0]),
                ((0, "succeeded"),),
            )
            self.assertEqual(
                job_attempt_statuses(reopened, interrupted_job),
                ((0, "succeeded"),),
            )
            self.assertEqual(
                reopened.execute(
                    """
                    SELECT reason FROM location_status
                    WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                      AND sample_index = ? AND realization_seed = ?
                      AND execution_fingerprint_digest = ? AND attempt_index = 0
                      AND modality = 'BH' AND profile_id = 'pilot-bh'
                      AND location_index = 0
                    """,
                    (
                        interrupted_job.manifest_id, interrupted_job.design_id,
                        interrupted_job.block_id, interrupted_job.sample_index,
                        interrupted_job.realization_seed,
                        interrupted_job.fingerprint.sha256_hex,
                    ),
                ).fetchone()[0],
                "persisted before process interruption",
            )
            self.assertEqual(
                reopened.execute(
                    "SELECT COUNT(*) FROM attempts WHERE status = 'succeeded'"
                ).fetchone()[0],
                len(self.manifest.jobs),
            )
            self.assertEqual(
                reopened.execute(
                    """
                    SELECT runtime_is_lower_bound FROM attempts
                    WHERE manifest_id = ? AND design_id = ? AND block_id = ?
                      AND sample_index = ? AND realization_seed = ?
                      AND execution_fingerprint_digest = ? AND attempt_index = 0
                    """,
                    (
                        interrupted_job.manifest_id, interrupted_job.design_id,
                        interrupted_job.block_id, interrupted_job.sample_index,
                        interrupted_job.realization_seed,
                        interrupted_job.fingerprint.sha256_hex,
                    ),
                ).fetchone()[0],
                1,
            )
            reopened.close()

    def test_failed_attempt_is_not_retried_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = sqlite3.connect(Path(temp_dir) / "failed.sqlite")
            initialize_store(connection)
            store_manifest(connection, self.manifest)
            job = self.manifest.jobs[0]
            begin_attempt(connection, job, 0, "2026-10-29T12:00:00Z")
            from src.rqd_exploration.store import finish_attempt

            finish_attempt(
                connection,
                job,
                0,
                status="failed",
                finished_at_utc="2026-10-29T12:00:01Z",
                runtime_seconds=1.0,
            )
            calls: list[int] = []

            def measure_pending_job(case, factory, seed):
                self.assertTrue(callable(factory.generate))
                calls.append(seed)
                return self._measurement_result(case, reason="completed in remaining batch")

            with patch(
                "src.rqd_exploration.runner.generate_and_measure",
                side_effect=measure_pending_job,
            ):
                summary = execute_frozen_jobs(
                    connection, self.manifest, self.config, self.fake_factory,
                    maximum_simulations=len(self.manifest.jobs),
                )
            self.assertEqual(summary.skipped_failed_job_keys, ((
                job.manifest_id, job.design_id, job.block_id,
                job.sample_index, job.realization_seed,
            ),))
            self.assertEqual(len(summary.completed_job_keys), len(self.manifest.jobs) - 1)
            self.assertEqual(len(calls), len(self.manifest.jobs) - 1)
            self.assertEqual(summary.simulation_count, len(self.manifest.jobs) - 1)
            self.assertEqual(summary.termination_reason, "jobs_complete")
            self.assertEqual(job_attempt_statuses(connection, job), ((0, "failed"),))
            connection.close()

    def test_budget_stops_between_jobs_and_marks_every_goal_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = sqlite3.connect(Path(temp_dir) / "budget.sqlite")
            initialize_store(connection)
            store_manifest(connection, self.manifest)
            calls: list[int] = []

            def measure_one_job(case, factory, seed):
                self.assertTrue(callable(factory.generate))
                calls.append(seed)
                return self._measurement_result(case, reason="within budget")

            with patch(
                "src.rqd_exploration.runner.generate_and_measure",
                side_effect=measure_one_job,
            ):
                summary = execute_frozen_jobs(
                    connection,
                    self.manifest,
                    self.config,
                    self.fake_factory,
                    maximum_simulations=1,
                )

            self.assertEqual(len(calls), 1)
            self.assertEqual(summary.simulation_count, 1)
            self.assertEqual(summary.maximum_simulations, 1)
            self.assertEqual(summary.termination_reason, "budget_exhausted")
            self.assertEqual(len(summary.completed_job_keys), 1)
            self.assertEqual(
                summary.goal_statuses,
                tuple(
                    (goal.goal_id, "unresolved_at_budget")
                    for goal in self.config.target_goals
                ),
            )
            self.assertEqual(
                job_attempt_statuses(connection, self.manifest.jobs[0]),
                ((0, "succeeded"),),
            )
            self.assertEqual(
                job_attempt_statuses(connection, self.manifest.jobs[1]),
                (),
            )
            connection.close()

    def test_invalid_budget_is_rejected_before_creating_attempts(self) -> None:
        for invalid_budget, error_type in (
            (0, ValueError),
            (-1, ValueError),
            (True, TypeError),
            (1.5, TypeError),
        ):
            with self.subTest(maximum_simulations=invalid_budget):
                with tempfile.TemporaryDirectory() as temp_dir:
                    connection = sqlite3.connect(Path(temp_dir) / "invalid-budget.sqlite")
                    initialize_store(connection)
                    store_manifest(connection, self.manifest)
                    calls: list[int] = []
                    with patch(
                        "src.rqd_exploration.runner.generate_and_measure",
                        side_effect=lambda *args: calls.append(args[-1]),
                    ), self.assertRaises(error_type):
                        execute_frozen_jobs(
                            connection,
                            self.manifest,
                            self.config,
                            self.fake_factory,
                            maximum_simulations=invalid_budget,
                        )
                    self.assertEqual(calls, [])
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
                        0,
                    )
                    connection.close()


if __name__ == "__main__":
    unittest.main()
