from dataclasses import asdict, replace
import contextlib
import csv
import io
import json
from hashlib import sha256
from math import acos, pi, prod, sqrt
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np

from src.euler_campaign.dfn import CaseJointFactory
from src.euler_campaign.p32 import disk_box_areas, measure_domain_p32
from src.euler_campaign.generation import (
    FIXED_DOMAIN, FIXED_DOMAIN_GENERATOR_VERSION, PER_JOINT_BUFFER,
    PER_JOINT_BUFFER_GENERATOR_VERSION, radius_bin_plan,
)
from src.rqd_exploration.main_analysis import build_targets, physical_rqd_floor
from src.rqd_exploration.main_controller import MainController, reference_snapshot
from src.rqd_exploration.main_design import expected_joint_counts, input_identity
from src.rqd_exploration.main_policy import AXES, load_main_config
from src.rqd_exploration.main_store import initialize_main_store, open_run
from src.rqd_exploration.p32_store import (
    initialize_p32_store, measure_missing_p32, read_measured_p32,
)
from src.rqd_exploration.store import initialize_store
from src.test.test_euler_dfn import _case


ROOT = Path(__file__).resolve().parents[2]


class TestPerJointBuffer(unittest.TestCase):
    def test_legacy_numpy_golden_is_bit_identical(self):
        geometry = CaseJointFactory().generate(_case(), 1234)
        data = np.array([(*j.center, *j.normal, j.radius) for j in geometry.joints])
        self.assertEqual(len(geometry.joints), 136)
        self.assertEqual(sha256(data.tobytes()).hexdigest(),
                         "637d67df38a81847b579483d7be5dbe468576cb26c9041392d8886a5c2a05524")

    def test_log_bins_probabilities_and_constant_radius_cost(self):
        plan = radius_bin_plan(3, .5, 5, .2, (10, 10, 10))
        self.assertEqual(len(plan), 32)
        self.assertAlmostEqual(sum(p.probability for p in plan), 1)
        constant = radius_bin_plan(3, 1, 1, .2, (10, 10, 10))
        self.assertEqual(len(constant), 1)
        self.assertAlmostEqual(constant[0].expected_count, .2 * 12**3 / pi)

    def test_stationary_in_domain_p32_and_determinism(self):
        case = _case()
        values = []
        for seed in range(32):
            geometry = CaseJointFactory().generate(case, seed, generation_mode=PER_JOINT_BUFFER)
            values.append(measure_domain_p32(case, geometry)[""]["p32_m2_per_m3"])
        # Approximately 5,000 tiny disks over independent seeds: a 10% tolerance
        # covers Poisson sampling variation and the <0.041% 128-gon area error.
        self.assertLess(abs(np.mean(values) / .2 - 1), .10)
        first = CaseJointFactory().generate(case, 44, generation_mode=PER_JOINT_BUFFER)
        second = CaseJointFactory().generate(case, 44, generation_mode=PER_JOINT_BUFFER)
        self.assertEqual(first, second)

    def test_inside_half_plane_and_outside_disk_areas(self):
        areas = disk_box_areas(
            np.array([[5., 5., 5.], [0., 5., 5.], [-2., 5., 5.]]),
            np.array([[0., 0., 1.]] * 3), np.ones(3), (10, 10, 10))
        self.assertEqual(areas[0], pi)
        self.assertAlmostEqual(areas[1], pi / 2, delta=.0005 * pi / 2)
        self.assertEqual(areas[2], 0)
        covering = disk_box_areas(np.array([[5., 5., 5.]]), np.array([[0., 0., 1.]]),
                                 np.array([100.]), (10, 10, 10))
        self.assertAlmostEqual(covering[0], 100.)

    def test_oblique_cap_and_oversized_disk_within_point_one_percent(self):
        radius, offset = 5., 2.
        normal = np.array([[0., 1 / np.sqrt(2), 1 / np.sqrt(2)]])
        oblique_expected = pi * radius**2 - (
            radius**2 * acos(offset / radius)
            - offset * sqrt(radius**2 - offset**2)
        )
        oblique_actual = disk_box_areas(
            np.array([[offset, 50., 50.]]), normal, np.array([radius]),
            (20., 100., 100.),
        )[0]
        self.assertLessEqual(abs(oblique_actual / oblique_expected - 1), .001)

        large_actual = disk_box_areas(
            np.array([[30., 15., 15.]]), np.array([[0., 0., 1.]]),
            np.array([150.]), (60., 30., 30.),
        )[0]
        self.assertLessEqual(abs(large_actual / (60. * 30.) - 1), .001)


class TestFixedDomainCenters(unittest.TestCase):
    def test_centers_stay_in_fixed_domain_and_p32_is_measured(self):
        from src.euler_campaign.dfn import _domain_extents

        case = _case()
        geometry = CaseJointFactory().generate(case, 44, generation_mode=FIXED_DOMAIN)
        extents = _domain_extents(case.domain)
        self.assertTrue(all(
            0 <= coordinate <= extent
            for joint in geometry.joints
            for coordinate, extent in zip(joint.center, extents)
        ))
        measured = measure_domain_p32(case, geometry)
        self.assertGreaterEqual(measured[""]["p32_m2_per_m3"], 0)


class TestNewMainPolicy(unittest.TestCase):
    def setUp(self):
        self.config = load_main_config(ROOT / "config/rqd_exploration_main.yml")

    def test_bounds_steps_floors_and_650_targets(self):
        self.assertEqual(AXES[0][1:5], (.1, 1., .01, 10.))
        for jn, floor in ((2, 73.6), (4, 40.6), (9, 19.9), (15, 10.)):
            self.assertAlmostEqual(physical_rqd_floor(jn), floor, delta=.05)
        targets = build_targets("bh", jn_values=(2, 4, 9, 15))
        counts = [sum(t.reachable for t in targets if int(t.bin_id) == b)
                  for b in range(10, 0, -1)]
        self.assertEqual(counts, [3, 10, 33, 54, 84, 113, 119, 106, 80, 48])
        self.assertEqual(sum(counts), 650)

    def test_main_uses_fixed_domain_mode_and_nominal_p32_cost(self):
        snapshot = reference_snapshot(self.config)
        joint = replace(snapshot.joint_sets[0], p32_m2_per_m3=.2,
                        size_r_min_m=1., size_r_max_m=1.)
        new = replace(snapshot, joint_sets=(joint,))
        legacy = replace(new, runtime=replace(new.runtime, generator_version="old-generator"))
        self.assertEqual(new.runtime.generator_version, FIXED_DOMAIN_GENERATOR_VERSION)
        self.assertNotEqual(input_identity(new), input_identity(legacy))
        expected = .2 * prod(new.geometry.domain_size_m) / pi
        self.assertAlmostEqual(expected_joint_counts(new)[joint.joint_set_id],
                               expected)
        self.assertAlmostEqual(expected_joint_counts(legacy)[joint.joint_set_id],
                               expected)

    def test_new_run_preserves_old_run_and_excludes_only_mutation_reference(self):
        from src.rqd_exploration.main_analysis import BHPoint, SeedProfile
        from src.rqd_exploration.fingerprint import fingerprint_execution_snapshot
        from src.rqd_exploration.main_store import reserve_start, starts_consumed
        from src.rqd_exploration.records import ExecutionJob
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, sqlite3.connect(":memory:") as connection:
            initialize_store(connection)
            initialize_main_store(connection)
            old = replace(self.config, fingerprint="old-approved-policy")
            old_id, _ = open_run(connection, old, {}, {"phase": "paused", "reason": "high_cost_review"})
            snapshot = reference_snapshot(self.config)
            job = ExecutionJob("control-only", "design", "block", 0, 43, snapshot,
                               fingerprint_execution_snapshot(snapshot))
            for _ in range(168):
                reserve_start(connection, old_id, job, input_id=input_identity(snapshot),
                              role="reference", resuming=False, expected_counts={"set": 1.},
                              policy=old.policy)
            before = connection.execute("SELECT * FROM main_control_runs").fetchall()
            before_starts = connection.execute("SELECT * FROM main_control_starts").fetchall()
            controller = MainController(connection, self.config, Mock(), snapshot.runtime,
                                        output_dir=directory)
            self.assertNotEqual(controller.run_id, old_id)
            self.assertEqual(starts_consumed(connection, controller.run_id), 0)
            self.assertEqual(controller.config.policy.maximum_starts, 20_000)
            self.assertEqual(starts_consumed(connection, old_id), 168)
            self.assertEqual(connection.execute("SELECT * FROM main_control_starts").fetchall(), before_starts)
            self.assertEqual(connection.execute(
                "SELECT * FROM main_control_runs WHERE run_id=?", (old_id,)).fetchall(), before)
            outside = replace(snapshot, joint_sets=(replace(snapshot.joint_sets[0],
                              p32_m2_per_m3=24.),))
            identity = input_identity(outside)
            controller.state["inputs"][identity] = asdict(outside)
            controller.profiles[identity] = {controller.profile_id: {
                43: SeedProfile(43, (BHPoint(0, 1, 100, 1),))}}
            verify_start = self.config.policy.verification_seed
            for seed in range(verify_start, verify_start + 3):
                controller.profiles[identity][controller.profile_id][seed] = SeedProfile(
                    seed, (BHPoint(0, 1, 100, 1),))
            target = next(t for t in controller.targets
                          if t.reachable and t.fixed_jn == 2 and t.contains(100))
            self.assertIn(identity, controller._suitable(target))
            self.assertEqual(controller._references(target), [])
            controller._plan_round(target)
            self.assertEqual(len(controller.state["round"]["candidates"]), 12)
            self.assertTrue(all(c["role"] == "lhs" for c in controller.state["round"]["candidates"]))
            self.assertTrue(controller.state["round"]["reference_skips"])


class TestMeasuredStore(unittest.TestCase):
    def test_additive_store_does_not_change_raw_schema(self):
        with sqlite3.connect(":memory:") as connection:
            initialize_store(connection)
            initialize_p32_store(connection)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(read_measured_p32(connection), {})


class TestP32Workflow(unittest.TestCase):
    def setUp(self):
        from src.rqd_exploration.adapter import build_generation_case
        from src.rqd_exploration.config import GeometryInput, MeasurementInput, load_config
        from src.rqd_exploration.design import DesignSample, build_frozen_manifest
        from src.rqd_exploration.fingerprint import ExecutionJointSet, ExecutionRuntime
        from src.rqd_exploration.measurement import (
            FACE_BOUNDARY_RULES_VERSION, MEASUREMENT_VERSION, plan_measurement_locations,
        )
        from src.rqd_exploration.runner import execute_frozen_job
        from src.rqd_exploration.store import store_manifest
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "synthetic.sqlite"
        self.connection = sqlite3.connect(self.path)
        self.addCleanup(self.connection.close)
        config = load_config(ROOT / "config/rqd_exploration_pilot.yml")
        design = replace(config.designs[0], sample_count=1)
        geometry = GeometryInput("ENU", (10., 10., 10.), (1., 1., 1.), (10, 10, 10),
            ((3., 5., 5.), (7., 5., 5.)), 1., (3., 5., 5.), (1., 0., 0.), 4.)
        self.config = replace(config, designs=(design,), geometry=geometry,
                              measurements=MeasurementInput(1., 1.))
        joint = ExecutionJointSet("set-1", .2, 3., .5, 1., 90., 270., 10.)
        case = build_generation_case(geometry, self.config.measurements, 2., (joint,), case_id="cheap")
        self.manifest = build_frozen_manifest(self.config, manifest_id="cheap-synthetic",
            runtime=ExecutionRuntime("numpy-legacy-test", MEASUREMENT_VERSION, "numpy", ("synthetic",)),
            boundary_rules_version=FACE_BOUNDARY_RULES_VERSION,
            planned_locations=plan_measurement_locations(case),
            samples_by_design={design.design_id: (DesignSample(0, (), (joint,)),)})
        self.job = self.manifest.jobs[0]
        initialize_store(self.connection)
        store_manifest(self.connection, self.manifest)
        execute_frozen_job(self.connection, self.manifest, self.config, CaseJointFactory())
        self.raw_before = self.connection.execute("SELECT * FROM observations").fetchall()

    def command(self, *args):
        from src.rqd_exploration.cli import main
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, json.loads(stdout.getvalue()) if stdout.getvalue().strip() else None, stderr.getvalue()

    def test_cli_backfill_idempotency_confirmation_and_exact_rqd_fidelity(self):
        code, _, _ = self.command("measure-p32", "--database", str(self.path))
        self.assertEqual(code, 2)
        for expected in (1, 0):
            code, payload, error = self.command("measure-p32", "--database", str(self.path),
                                               "--confirm-execution")
            self.assertEqual(code, 0, error)
            self.assertEqual(payload["measured_realizations"], expected)
            self.assertFalse(payload["rqd_measured"])
        code, payload, error = self.command("measure-p32", "--database", str(self.path),
            "--confirm-execution", "--verify-job", self.job.fingerprint.sha256_hex)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["verified_execution_fingerprints"], [self.job.fingerprint.sha256_hex])
        self.assertEqual(self.connection.execute("SELECT * FROM observations").fetchall(), self.raw_before)
        self.assertEqual(self.connection.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertEqual(len(read_measured_p32(self.connection)[self.job.fingerprint.sha256_hex]), 2)

    def test_failed_fidelity_does_not_store_or_alter_raw(self):
        from src.euler_campaign.dfn import DiskJointGeometry
        wrong = Mock()
        wrong.generate.return_value = DiskJointGeometry(())
        with self.assertRaisesRegex(ValueError, "fidelity"):
            measure_missing_p32(self.connection, lambda _runtime: wrong,
                                verify_job=self.job.fingerprint.sha256_hex)
        self.assertEqual(read_measured_p32(self.connection), {})
        self.assertEqual(self.connection.execute("SELECT * FROM observations").fetchall(), self.raw_before)

    def test_measured_columns_and_report_identity(self):
        from src.rqd_exploration.dataset import load_latest_cumulative_dataset_revision
        from src.rqd_exploration.cumulative_reporting import export_cumulative_coverage_report
        measure_missing_p32(self.connection, lambda _runtime: CaseJointFactory())
        output = Path(self.directory.name) / "reports"
        export_cumulative_coverage_report(output, load_latest_cumulative_dataset_revision(self.connection),
                                         measured_p32=read_measured_p32(self.connection))
        with (output / "qprime_p32.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue(rows)
        self.assertIn("p32_m2_per_m3", rows[0])
        self.assertGreater(float(rows[0]["measured_p32_m2_per_m3"]), 0)
        self.assertEqual(rows[0]["p32_method_version"], "v1-128")
        summary = json.loads((output / "report_summary.json").read_text())
        self.assertEqual(summary["report_schema_version"], "rqd_exploration_cumulative_coverage_v2")
        self.assertTrue(summary["measured_p32_sha256"])

    def test_main_automatic_measurement_and_paused_report_reuse(self):
        from src.euler_campaign.dfn import DiskJointGeometry
        from src.test.test_rqd_main_workflow import TestMainWorkflow
        fixture = TestMainWorkflow()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.factory.generate.side_effect = [DiskJointGeometry(()), RuntimeError("review")]
        code, _, error = fixture.command(*fixture.run_args())
        self.assertEqual(code, 1, error)
        self.assertEqual(fixture.factory.generate.call_args_list[0].kwargs["generation_mode"], FIXED_DOMAIN)
        with sqlite3.connect(fixture.database) as connection:
            records = read_measured_p32(connection)
            self.assertEqual(len(records), 1)
            main_config = load_main_config(fixture.main_config)
            configured_set_count = len(main_config.templates[2].joint_sets)
            self.assertEqual(len(next(iter(records.values()))), configured_set_count + 1)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
        path = next(fixture.output.glob("cumulative/revision-*/reports/qprime_p32.csv"))
        with path.open() as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(float(row["measured_p32_m2_per_m3"]), 0.)
        self.assertEqual(float(row["measured_total_p32_m2_per_m3"]), 0.)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        self.assertEqual(fixture.command(*fixture.run_args())[0], 1)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(fixture.factory.generate.call_count, 2)

    def test_backfill_interruption_is_resumable_and_complete_records_are_reused(self):
        from src.rqd_exploration.runner import execute_frozen_job
        from src.rqd_exploration.store import store_manifest
        from src.rqd_exploration.design import build_frozen_manifest, DesignSample
        from src.rqd_exploration.measurement import FACE_BOUNDARY_RULES_VERSION, plan_measurement_locations
        from src.rqd_exploration.p32_store import case_for_snapshot
        snapshot = self.job.snapshot
        design = replace(self.config.designs[0], realization_seed=44)
        config = replace(self.config, designs=(design,))
        case = case_for_snapshot(snapshot, "second")
        second = build_frozen_manifest(config, manifest_id="second-synthetic",
            runtime=snapshot.runtime, boundary_rules_version=FACE_BOUNDARY_RULES_VERSION,
            planned_locations=plan_measurement_locations(case),
            samples_by_design={design.design_id: (DesignSample(0, (), snapshot.joint_sets),)})
        store_manifest(self.connection, second)
        execute_frozen_job(self.connection, second, config, CaseJointFactory())
        factory = Mock()
        factory.generate.side_effect = [CaseJointFactory().generate(case, 43), KeyboardInterrupt]
        with self.assertRaises(KeyboardInterrupt):
            measure_missing_p32(self.connection, lambda _runtime: factory)
        self.assertEqual(len(read_measured_p32(self.connection)), 1)
        result = measure_missing_p32(self.connection, lambda _runtime: CaseJointFactory())
        self.assertEqual(result["measured_realizations"], 1)
        self.assertEqual(result["skipped_jobs"], 1)
        self.assertEqual(len(read_measured_p32(self.connection)), 2)

    def test_recorded_new_mlx_mode_regenerates_exact_stored_rqd(self):
        from src.euler_campaign.mlx_backend import MlxCaseJointFactory, require_mlx_gpu
        from src.rqd_exploration.runner import execute_frozen_job
        from src.rqd_exploration.store import store_manifest
        from src.rqd_exploration.design import build_frozen_manifest, DesignSample
        from src.rqd_exploration.measurement import FACE_BOUNDARY_RULES_VERSION, plan_measurement_locations
        from src.rqd_exploration.p32_store import case_for_snapshot
        require_mlx_gpu()
        runtime = replace(self.job.snapshot.runtime, backend="mlx",
                          generator_version=PER_JOINT_BUFFER_GENERATOR_VERSION)
        design = replace(self.config.designs[0], realization_seed=44)
        config = replace(self.config, designs=(design,))
        snapshot = replace(self.job.snapshot, runtime=runtime)
        case = case_for_snapshot(snapshot, "mlx-cheap")
        manifest = build_frozen_manifest(config, manifest_id="mlx-cheap", runtime=runtime,
            boundary_rules_version=FACE_BOUNDARY_RULES_VERSION,
            planned_locations=plan_measurement_locations(case),
            samples_by_design={design.design_id: (DesignSample(0, (), snapshot.joint_sets),)})
        store_manifest(self.connection, manifest)
        execute_frozen_job(self.connection, manifest, config, MlxCaseJointFactory())
        before = self.connection.execute("SELECT * FROM observations").fetchall()
        result = measure_missing_p32(self.connection,
            lambda recorded: MlxCaseJointFactory() if recorded.backend == "mlx" else CaseJointFactory(),
            verify_job=manifest.jobs[0].fingerprint.sha256_hex)
        self.assertEqual(result["verified_execution_fingerprints"], [manifest.jobs[0].fingerprint.sha256_hex])
        self.assertEqual(result["measured_realizations"], 1)
        self.assertEqual(set(read_measured_p32(self.connection)), {manifest.jobs[0].fingerprint.sha256_hex})
        self.assertEqual(self.connection.execute("SELECT * FROM observations").fetchall(), before)
