import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from src.euler_campaign.dfn import DiskJointGeometry
from src.rqd_exploration import cli
from src.rqd_exploration.config import load_config
from src.rqd_exploration.dataset import load_latest_cumulative_dataset_revision
from src.rqd_exploration.measurement import RawFaceObservation, measure_realization
from src.rqd_exploration.runner import build_mlx_pilot_manifest, execute_frozen_job
from src.rqd_exploration.store import initialize_store, store_manifest
from src.test.test_rqd_main_policy import jn20_config_path, load_main_config


ROOT = Path(__file__).resolve().parents[2]


class TestMainWorkflow(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "main.sqlite"
        self.output = Path(self.directory.name) / "reports"
        self.jn20_config = jn20_config_path(self.directory.name)
        self.factory = Mock()
        self.factory.generate.return_value = DiskJointGeometry(())
        backend = ModuleType("src.euler_campaign.mlx_backend")
        from src.euler_campaign.generation import FIXED_DOMAIN_GENERATOR_VERSION
        backend.MLX_GENERATOR_VERSION = FIXED_DOMAIN_GENERATOR_VERSION
        backend.require_mlx_gpu = lambda: ("test-version", "test-device")
        backend.MlxCaseJointFactory = lambda: self.factory
        patcher = patch.dict(sys.modules, {"src.euler_campaign.mlx_backend": backend})
        patcher.start()
        self.addCleanup(patcher.stop)
        cost = patch("src.rqd_exploration.main_controller.expected_joint_counts",
                     return_value={"test-set": 1.})
        cost.start()
        self.addCleanup(cost.stop)

    def command(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(args))
        payload = json.loads(stdout.getvalue()) if stdout.getvalue().strip() else None
        return code, payload, stderr.getvalue()

    def run_args(self):
        return ("run-main", "--database", str(self.database), "--output-dir", str(self.output),
                "--config", str(self.jn20_config), "--confirm-execution")

    def test_confirmation_validate_and_preview_write_generate_nothing(self):
        code, _, _ = self.command("run-main", "--database", str(self.database),
                                  "--config", "nonexistent-config")
        self.assertEqual(code, 2)
        self.assertFalse(self.database.exists())
        code, payload, _ = self.command("validate-main")
        self.assertEqual(code, 0)
        self.assertEqual(payload["policy"]["maximum_starts"], 20_000)
        self.assertEqual(payload["policy"]["review_checkpoint_starts"], 10_000)
        code, payload, _ = self.command("preview-main")
        self.assertEqual(code, 0)
        self.assertEqual(payload["initial_jobs"], [])
        self.assertFalse(payload["database_written"])
        self.assertFalse(self.database.exists())
        with sqlite3.connect(self.database) as connection:
            initialize_store(connection)
        before = self.database.read_bytes()
        code, payload, stderr = self.command("preview-main", "--database", str(self.database))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(payload["existing_raw_observations"], 0)
        with sqlite3.connect(self.database) as connection:
            self.assertFalse(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='main_control_runs'").fetchone())
        self.factory.generate.assert_not_called()

    def test_recover_incomparable_flag_is_forwarded_to_main_executor(self):
        with patch(
            "src.rqd_exploration.main_controller.execute_main",
            return_value={"reason": "review_checkpoint"},
        ) as execute:
            code, _, stderr = self.command(
                *self.run_args(), "--recover-incomparable",
            )

        self.assertEqual(code, 0, stderr)
        self.assertTrue(execute.call_args.kwargs["recover_incomparable"])
        self.factory.generate.assert_not_called()

    def test_default_without_jn20_starts_exploration_and_resumes_without_jn20(self):
        self.factory.generate.side_effect = KeyboardInterrupt
        args = ("run-main", "--database", str(self.database),
                "--output-dir", str(self.output), "--confirm-execution")
        for expected_starts in (1, 2):
            with self.assertRaises(KeyboardInterrupt):
                self.command(*args)
            case, seed = self.factory.generate.call_args.args
            self.assertEqual((case.domain.jn, len(case.joint_sets), seed), (2, 1, 43))
            with sqlite3.connect(self.database) as connection:
                state = json.loads(connection.execute(
                    "SELECT state_json FROM main_control_runs").fetchone()[0])
                self.assertEqual((state["phase"], state["reason"], state["resume_phase"]),
                                 ("paused", "user_interruption", "exploration"))
                self.assertTrue(state["inputs"])
                self.assertTrue(all(s["fixed_jn"] != 20 for s in state["inputs"].values()))
                self.assertTrue(all(t["role"] != "initial" for t in state["queue"]))
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM main_control_starts").fetchone()[0], expected_starts)

    def test_default_excludes_saved_jn20_from_active_ledger_without_removing_raw_data(self):
        from src.rqd_exploration.main_controller import MainController, initial_manifest
        from src.rqd_exploration.main_policy import load_main_config
        from src.rqd_exploration.main_store import initialize_main_store
        enabled = load_main_config(self.jn20_config)
        manifest = initial_manifest(enabled)
        with sqlite3.connect(self.database) as connection:
            initialize_store(connection)
            store_manifest(connection, manifest)
            execute_frozen_job(connection, replace(manifest, jobs=(manifest.jobs[0],)),
                               enabled.reference_input, self.factory)
            before = connection.execute("SELECT * FROM observations").fetchall()
            self.assertTrue(before)
            initialize_main_store(connection)
            controller = MainController(
                connection, load_main_config(ROOT / "config/rqd_exploration_main.yml"),
                self.factory, manifest.jobs[0].snapshot.runtime, output_dir=self.output)
            self.assertEqual(controller.state["phase"], "exploration")
            self.assertEqual(controller.state["queue"], [])
            self.assertEqual(controller.state["inputs"], {})
            self.assertEqual(controller.profiles, {})
            self.assertTrue(all(t.fixed_jn != 20 for t in controller.targets))
            self.assertEqual(connection.execute("SELECT * FROM observations").fetchall(), before)

    def test_main_excludes_legacy_generator_evidence_without_deleting_observations(self):
        from src.euler_campaign.generation import FIXED_DOMAIN_GENERATOR_VERSION
        from src.rqd_exploration.main_controller import MainController
        from src.rqd_exploration.main_policy import load_main_config
        from src.rqd_exploration.main_store import initialize_main_store

        config = load_main_config(ROOT / "config/rqd_exploration_main.yml")
        source = replace(config.reference_input,
                         designs=(config.reference_input.designs[0],))
        backend = sys.modules["src.euler_campaign.mlx_backend"]
        with patch.object(backend, "MLX_GENERATOR_VERSION", "qsimex-mlx-generation-v1"):
            manifest = build_mlx_pilot_manifest(source, manifest_id="legacy-main-input")
        legacy_job = manifest.jobs[0]
        self.assertEqual(legacy_job.snapshot.runtime.generator_version,
                         "qsimex-mlx-generation-v1")
        self.assertNotEqual(legacy_job.snapshot.runtime.generator_version,
                            FIXED_DOMAIN_GENERATOR_VERSION)

        with sqlite3.connect(self.database) as connection:
            initialize_store(connection)
            store_manifest(connection, manifest)
            execute_frozen_job(connection, replace(manifest, jobs=(legacy_job,)),
                               source, self.factory)
            before = connection.execute("SELECT * FROM observations").fetchall()
            self.assertTrue(before)
            initialize_main_store(connection)
            controller = MainController(
                connection, config, self.factory, legacy_job.snapshot.runtime,
                output_dir=self.output)
            self.assertEqual(controller.state["inputs"], {})
            self.assertEqual(controller.profiles, {})
            self.assertEqual(controller.snapshot_by_digest, {})
            self.assertEqual(connection.execute(
                "SELECT * FROM observations").fetchall(), before)

    def test_real_raw_measurement_provenance_cumulative_resume_and_face_observational(self):
        calls = []
        def generate(case, seed, **kwargs):
            calls.append((case.domain.jn, len(case.joint_sets), seed))
            if len(calls) == 2:
                raise KeyboardInterrupt
            return DiskJointGeometry(())
        self.factory.generate.side_effect = generate
        def measure(case, joints, **kwargs):
            result = measure_realization(case, joints, **kwargs)
            return replace(result, observations=tuple(
                replace(o, is_valid=False, exclusion_reason="test: invalid face observation")
                if isinstance(o, RawFaceObservation) else o for o in result.observations))
        with patch("src.rqd_exploration.runner.measure_realization", side_effect=measure):
            with self.assertRaises(KeyboardInterrupt):
                self.command(*self.run_args())
            with sqlite3.connect(self.database) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                self.assertEqual(connection.execute(
                    "SELECT status FROM attempts ORDER BY sample_index,realization_seed,manifest_id").fetchall().count(
                        ("succeeded",)), 1)
                observations = connection.execute("SELECT * FROM observations").fetchall()
                evidence = connection.execute("SELECT * FROM measurement_evidence").fetchall()
                old_revision = load_latest_cumulative_dataset_revision(connection)
                self.assertEqual(old_revision.raw_observation_count, 121)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM main_control_starts").fetchone()[0], 2)
            def cost(snapshot):
                return {"test-set": 1. if len(calls) < 3 else 10_000_001.}
            with patch("src.rqd_exploration.main_controller.expected_joint_counts", side_effect=cost):
                code, payload, stderr = self.command(*self.run_args())
            self.assertEqual(code, 1, stderr)
            summary = payload["main_summary"]
            self.assertEqual(summary["reason"], "high_cost_review")
            self.assertEqual(summary["starts_consumed"], 3)
            self.assertEqual(calls, [(20., 5, 43)] * 3)
            with sqlite3.connect(self.database) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                current = load_latest_cumulative_dataset_revision(connection)
                self.assertEqual(current.raw_observation_count, 242)
                self.assertGreater(current.revision_index, old_revision.revision_index)
                saved_old = load_latest_cumulative_dataset_revision(connection, old_revision.revision_index)
                self.assertEqual(saved_old.dataset_sha256, old_revision.dataset_sha256)
                new_observations = connection.execute("SELECT * FROM observations").fetchall()
                self.assertTrue(all(o in new_observations for o in observations))
                self.assertTrue(all(e in connection.execute(
                    "SELECT * FROM measurement_evidence").fetchall() for e in evidence))
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM input_provenance").fetchone()[0], 3)
                self.assertEqual(connection.execute(
                    "SELECT event_index FROM main_control_events ORDER BY event_index").fetchall(),
                                 [(1,), (2,)])
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM observations WHERE modality='face' AND is_valid=0").fetchone()[0], 122)
            self.assertEqual(len(list(self.output.glob("main-*/event-*/summary.json"))), 2)
            calls_before = len(calls)
            code, payload, _ = self.command(*self.run_args())
            self.assertEqual(code, 1)
            self.assertEqual(payload["main_summary"]["reason"], "high_cost_review")
            self.assertEqual(len(calls), calls_before)

    def test_main_error_is_paused_reported_and_no_retry(self):
        self.factory.generate.side_effect = RuntimeError("deliberate factory error")
        code, payload, progress = self.command(*self.run_args())
        self.assertEqual(code, 1)
        self.assertEqual(payload["main_summary"]["reason"], "execution_error")
        self.assertEqual(payload["main_summary"]["starts_consumed"], 1)
        self.assertEqual(payload["main_summary"]["starts_maximum"], 20_000)
        self.assertEqual(payload["main_summary"]["starts_remaining"], 19_999)
        self.assertIn("verification_seeds", payload["main_summary"]["target_pass_rule"])
        self.assertIn("starts=1/20000 remaining=19999", progress)
        self.assertIn("job_stage=starting", progress)
        self.assertIn("progress stage=DFN generation", progress)
        code, payload, _ = self.command(*self.run_args())
        self.assertEqual(code, 1)
        self.assertEqual(self.factory.generate.call_count, 1)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT status FROM attempts").fetchall(), [("failed",)])
            state = json.loads(connection.execute("SELECT state_json FROM main_control_runs").fetchone()[0])
            self.assertIn("deliberate factory error", state["detail"])

    def test_existing_pilot_inputs_enter_main_ledger_without_regeneration(self):
        config = load_config(ROOT / "config/rqd_exploration_pilot.yml")
        manifest = build_mlx_pilot_manifest(config, manifest_id="saved-pilot")
        with sqlite3.connect(self.database) as connection:
            initialize_store(connection)
            store_manifest(connection, manifest)
            for job in (manifest.jobs[0], manifest.jobs[5]):
                execute_frozen_job(connection, replace(manifest, jobs=(job,)), config, self.factory)
        self.factory.generate.reset_mock()
        self.factory.generate.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.command(*self.run_args())
        self.assertEqual(self.factory.generate.call_count, 1)
        case, seed = self.factory.generate.call_args.args
        self.assertEqual((case.domain.jn, len(case.joint_sets), seed), (20, 5, 43))
        with sqlite3.connect(self.database) as connection:
            state = json.loads(connection.execute("SELECT state_json FROM main_control_runs").fetchone()[0])
            self.assertEqual(sorted(s["fixed_jn"] for s in state["inputs"].values()),
                             [2] * 5 + [4] * 5 + [20] * 5)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 242)

    def test_raw_commit_before_control_checkpoint_reopen_reuses_without_charge(self):
        from src.rqd_exploration.main_controller import MainController
        refresh = MainController._refresh
        count = [0]
        def refresh_then_interrupt(controller):
            refresh(controller)
            if controller.connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE status='succeeded'").fetchone()[0] == 1:
                count[0] += 1
                if count[0] == 1:
                    raise KeyboardInterrupt
        with patch.object(MainController, "_refresh", refresh_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.command(*self.run_args())
        self.assertEqual(self.factory.generate.call_count, 1)
        with patch("src.rqd_exploration.main_controller.expected_joint_counts",
                   return_value={"set": 10_000_001.}):
            code, payload, _ = self.command(*self.run_args())
        self.assertEqual(code, 1)
        self.assertEqual(payload["main_summary"]["reason"], "high_cost_review")
        self.assertEqual(payload["main_summary"]["starts_consumed"], 1)
        self.assertEqual(self.factory.generate.call_count, 1)
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute(
                "SELECT status FROM main_control_starts").fetchall(), [("succeeded",)])

    def test_full_main_initial_bin_transition_uses_persisted_nine_seed_inputs(self):
        config = load_config(ROOT / "config/rqd_exploration_pilot.yml")
        policy = load_main_config(self.jn20_config).policy
        seed_values = [policy.initial_seed, *range(
            policy.verification_seed, policy.verification_seed + 3)]
        next_seed = max(seed_values) + 1
        while len(seed_values) < 10:
            if next_seed not in seed_values:
                seed_values.append(next_seed)
            next_seed += 1
        with sqlite3.connect(self.database) as connection:
            initialize_store(connection)
            for seed in seed_values:
                design = replace(config.designs[0], realization_seed=seed)
                normalized = replace(config, designs=(design,))
                manifest = build_mlx_pilot_manifest(normalized, manifest_id=f"preexisting-seed-{seed}")
                store_manifest(connection, manifest)
                for job in manifest.jobs[:3]:
                    execute_frozen_job(connection, replace(manifest, jobs=(job,)), normalized, self.factory)
            before = connection.execute("SELECT * FROM observations").fetchall()
            prior = load_latest_cumulative_dataset_revision(connection)
        self.factory.generate.reset_mock()
        calls = []
        def generate(case, seed, **kwargs):
            calls.append((case.domain.jn, seed))
            if len(calls) == 6:
                raise KeyboardInterrupt
            return DiskJointGeometry(())
        self.factory.generate.side_effect = generate
        progress = io.StringIO()
        with self.assertRaises(KeyboardInterrupt):
            with contextlib.redirect_stderr(progress):
                cli.main(list(self.run_args()))
        progress_lines = progress.getvalue().splitlines()
        completion_line = next(line for line in progress_lines if "job_stage=completed" in line)
        self.assertIn("bin=10 targets_passed=", completion_line)
        transition_line = next(line for line in progress_lines if "event=bin_transition" in line)
        self.assertIn("completed_bin=10 completed_targets_passed=3/3", transition_line)
        self.assertIn("bin=9 targets_passed=0/", transition_line)
        pause_line = next(line for line in progress_lines if "event=paused" in line)
        self.assertIn("reason=user_interruption", pause_line)
        self.assertRegex(pause_line, r"bin=9 targets_passed=\d+/\d+")
        self.assertEqual(calls[:5], [(20., policy.initial_seed)] * 5)
        with sqlite3.connect(self.database) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            events = connection.execute(
                "SELECT kind,payload FROM main_control_events ORDER BY event_index").fetchall()
            self.assertEqual(events[0][0], "bin_transition")
            transition = json.loads(events[0][1])
            self.assertEqual(transition["bin"], 10)
            histories = transition["target_evidence"]
            bin10 = [h for key, h in histories.items() if key.startswith("10/")]
            self.assertTrue(bin10)
            self.assertTrue(all(any(item["passed"] for item in h.values()) for h in bin10))
            state = json.loads(connection.execute("SELECT state_json FROM main_control_runs").fetchone()[0])
            self.assertEqual(state["bin"], 9)
            self.assertEqual(state["reason"], "user_interruption")
            self.assertEqual(transition["starts_consumed"], 5)
            observations = connection.execute("SELECT * FROM observations").fetchall()
            self.assertTrue(all(o in observations for o in before))
            self.assertEqual(load_latest_cumulative_dataset_revision(
                connection, prior.revision_index).dataset_sha256, prior.dataset_sha256)
            # The same valid seed observations can fail another target without being
            # removed from the cumulative dataset.
            from src.rqd_exploration.main_analysis import (
                BHPoint, SeedProfile, build_targets, seed_pass_result,
            )
            target = next(t for t in build_targets("bh", jn_values=(2,))
                          if t.reachable and not t.contains(100))
            self.assertTrue(target.reachable)
            failed = seed_pass_result(
                tuple(SeedProfile(seed, (BHPoint(0, 1, 100, 1),))
                      for seed in (policy.initial_seed,
                                   *range(policy.verification_seed,
                                          policy.verification_seed + 3))),
                target, initial_seed=policy.initial_seed,
                verification_seed=policy.verification_seed)
            self.assertFalse(failed.passed)
            current = load_latest_cumulative_dataset_revision(connection)
            self.assertEqual(current.raw_observation_count, 35 * 121)
        self.assertTrue(list(self.output.glob("cumulative/revision-*/reports/report_summary.json")))
