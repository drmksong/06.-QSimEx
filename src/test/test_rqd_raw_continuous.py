from __future__ import annotations

from dataclasses import asdict, replace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from src.euler_campaign.dfn import DiskJointGeometry
from src.rqd_exploration.main_analysis import BHPoint, SeedProfile
from src.rqd_exploration.main_controller import PREVIEW_RUNTIME, reference_snapshot
from src.rqd_exploration.main_design import input_identity
from src.rqd_exploration.main_store import MainPause, initialize_main_store
from src.rqd_exploration.raw_rqd_search import RawRqdController, load_raw_rqd_config, main
from src.rqd_exploration.store import initialize_store


class TestRawRqdContinuous(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.config = load_raw_rqd_config(
            root / "config/rqd_exploration_main_baseline3.yml")
        self.connection = sqlite3.connect(":memory:")
        initialize_store(self.connection)
        initialize_main_store(self.connection)
        self.output = TemporaryDirectory()
        self.profiles = {}
        self.performed = []
        self.interrupt = False
        self.fail = False
        self.response = 50.0
        parent = self

        class Controller(RawRqdController):
            def __init__(self):
                super().__init__(parent.connection, parent.config, None, PREVIEW_RUNTIME,
                                 output_dir=Path(parent.output.name))
                self.profiles = parent.profiles

            def _perform(self, task):
                identity, seed = task["input_id"], task["seed"]
                if self._profile(identity, seed) is not None:
                    return
                if parent.fail:
                    raise MainPause("execution_error", "synthetic failure")
                parent.performed.append(identity)
                self.profiles[identity] = {
                    self.profile_id: {
                        seed: SeedProfile(seed, tuple(
                            BHPoint(float(i), float(i + 1), parent.response, 1.0)
                            for i in range(30)))
                    }
                }
                if parent.interrupt:
                    parent.interrupt = False
                    raise KeyboardInterrupt

        self.Controller = Controller
        self.controller = Controller()
        self.controller.run()

    def tearDown(self) -> None:
        self.connection.close()
        self.output.cleanup()

    def test_ten_batches_are_cumulative_and_stop_at_limit(self) -> None:
        initial = set(self.profiles)
        review = self.controller.run(continue_from_review=True)
        self.assertEqual(review["reason"], "continuation_batch_review")
        self.assertEqual(review["followup_batch_index"], 1)
        result = self.controller.run(continue_from_review=True, continuous=True)
        self.assertEqual(result["reason"], "continuous_batch_limit")
        self.assertEqual(result["detail"]["completed_batches"], 10)
        self.assertEqual(result["followup_batch_index"], 11)
        self.assertEqual(len(self.profiles), 230)
        self.assertTrue(initial <= set(self.profiles))
        self.assertEqual(len(self.performed), len(set(self.performed)))
        self.assertTrue(result["probe_response_history"])
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM main_control_events WHERE kind='followup_batch_complete'"
        ).fetchone()[0], 10)
        self.assertIsNone(self.controller.state["continuous_batch_run"])

    def test_interruption_restores_budget_and_reuses_completed_job(self) -> None:
        self.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.controller.run(continue_from_review=True, continuous=True)
        self.assertEqual(self.controller.state["reason"], "user_interruption")
        self.assertEqual(len(self.performed), 11)
        restarted = self.Controller()
        self.assertEqual(restarted.state["continuous_batch_run"]["start_batch_index"], 0)
        with self.assertRaisesRegex(ValueError, "requires --continuous"):
            restarted.run()
        result = restarted.run(continuous=True)
        self.assertEqual(result["reason"], "continuous_batch_limit")
        self.assertEqual(result["detail"]["completed_batches"], 10)
        self.assertEqual(len(self.performed), 210)
        self.assertEqual(len(self.performed), len(set(self.performed)))

    def test_error_stops_without_consuming_another_batch(self) -> None:
        self.fail = True
        result = self.controller.run(continue_from_review=True, continuous=True)
        self.assertEqual(result["reason"], "execution_error")
        self.assertEqual(result["followup_batch_index"], 1)
        self.assertEqual(len(result["continuous_batch_run"]), 2)
        self.assertEqual(len(self.performed), 10)
        self.assertEqual(len(self.controller.state["queue"]), 20)
        with self.assertRaisesRegex(ValueError, "requires a paused"):
            self.controller.run(continue_from_review=True, continuous=True)

    def populate_coverage(self):
        base = reference_snapshot(self.controller.config, self.controller.runtime)
        last_identity = None
        for target in self.controller.targets:
            design = self.controller.config.templates[target.fixed_jn]
            sample = replace(base, fixed_jn=target.fixed_jn,
                             joint_sets=tuple(
                                 replace(base.joint_sets[0], joint_set_id=joint.joint_set_id)
                                 for joint in design.joint_sets))
            for index in range(30):
                first = replace(sample.joint_sets[0], p32_m2_per_m3=1.0 + index)
                snapshot = replace(sample, joint_sets=(first, *sample.joint_sets[1:]))
                identity = input_identity(snapshot)
                self.controller.state["inputs"][identity] = asdict(snapshot)
                value = 100.0 if index == 29 else (index // 3) * 10.0 + 5.0
                self.profiles[identity] = {
                    self.controller.profile_id: {design.realization_seed: SeedProfile(
                        design.realization_seed, tuple(
                            BHPoint(float(i), float(i + 1), value, 1.0) for i in range(30)))}
                }
                if target.fixed_jn == 15.0 and index == 29:
                    last_identity = identity
        return last_identity

    def test_exact_coverage_stops_before_new_batch(self) -> None:
        self.populate_coverage()
        result = self.controller.run(continue_from_review=True, continuous=True)
        self.assertEqual(result["reason"], "raw_rqd_coverage_complete")
        self.assertEqual(result["detail"]["completed_batches"], 0)
        self.assertEqual(result["followup_batch_index"], 0)

    def test_partial_profile_is_not_counted_and_completion_stops_after_batch(self) -> None:
        identity = self.populate_coverage()
        profile = self.profiles[identity][self.controller.profile_id][43]
        self.profiles[identity][self.controller.profile_id][43] = replace(
            profile, points=profile.points[:-1])
        target = next(item for item in self.controller.targets if item.fixed_jn == 15.0)
        deficits = self.controller._probe_targets(target)
        self.assertEqual(
            [(item.bin_index, item.signature_count) for item in deficits], [(9, 2)])
        self.response = 95.0
        result = self.controller.run(continue_from_review=True, continuous=True)
        self.assertEqual(result["reason"], "raw_rqd_coverage_complete")
        self.assertEqual(result["detail"]["completed_batches"], 1)

    def test_process_exit_after_batch_checkpoint_does_not_repeat_batch(self) -> None:
        def stop_after_batch(message):
            if "continuous batches=" in message:
                raise SystemExit("synthetic process exit")

        self.controller.progress_callback = stop_after_batch
        with self.assertRaises(SystemExit):
            self.controller.run(continue_from_review=True, continuous=True)
        restarted = self.Controller()
        self.assertEqual(restarted._continuous_completed(), 1)
        self.assertIsNone(restarted.state["active_followup_batch"])
        self.fail = True
        result = restarted.run(continuous=True)
        self.assertEqual(result["reason"], "execution_error")
        self.assertEqual(result["followup_batch_index"], 2)
        self.assertEqual(restarted._continuous_completed(), 1)
        self.assertEqual(len(self.performed), 30)
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM main_control_events WHERE kind='followup_batch_complete'"
        ).fetchone()[0], 1)

    def test_batch_journal_failure_does_not_mark_batch_complete(self) -> None:
        from src.rqd_exploration import raw_rqd_search

        append = raw_rqd_search.append_event

        def fail_batch_event(connection, run_id, kind, payload):
            if kind == "followup_batch_complete":
                raise RuntimeError("synthetic journal failure")
            return append(connection, run_id, kind, payload)

        with patch.object(raw_rqd_search, "append_event", side_effect=fail_batch_event):
            result = self.controller.run(continue_from_review=True, continuous=True)
        self.assertEqual(result["reason"], "execution_error")
        self.assertIn("synthetic journal failure", result["detail"])
        self.assertIsNotNone(self.controller.state["active_followup_batch"])
        self.assertEqual(self.controller._continuous_completed(), 0)
        self.assertEqual(self.controller.state["probe_response_history"], [])
        restarted = self.Controller()
        self.assertIsNotNone(restarted.state["active_followup_batch"])
        self.assertEqual(restarted._continuous_completed(), 0)

    def test_restart_reuses_actual_stored_observations(self) -> None:
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)
        factory = Mock()
        factory.generate.return_value = DiskJointGeometry(())
        with TemporaryDirectory() as output:
            controller = RawRqdController(
                connection, self.config, factory, PREVIEW_RUNTIME, output_dir=Path(output))
            self.assertEqual(controller.run()["reason"], "initial_cohort_review")

            def interrupt_after_result(message):
                if "result=generated" in message:
                    raise KeyboardInterrupt

            controller.progress_callback = interrupt_after_result
            with self.assertRaises(KeyboardInterrupt):
                controller.run(continue_from_review=True, continuous=True)
            queued = controller.state["queue"][0]
            attempts = connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            restarted = RawRqdController(
                connection, self.config, factory, PREVIEW_RUNTIME, output_dir=Path(output))
            self.assertEqual(restarted.state["queue"][0]["input_id"], queued["input_id"])
            self.assertEqual(restarted._continuous_completed(), 0)
            profile = restarted._profile(queued["input_id"], queued["seed"])
            self.assertIsNotNone(profile)
            self.assertEqual(len(profile.points), 30)
            restarted._perform(restarted.state["queue"][0])
            self.assertEqual(restarted.state["queue"][0]["result"], "reused")
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], attempts)
        connection.close()

    def test_cli_passes_continuous_flags_and_maps_stop_status(self) -> None:
        manifest = SimpleNamespace(
            jobs=[SimpleNamespace(snapshot=SimpleNamespace(runtime=PREVIEW_RUNTIME))])
        with TemporaryDirectory() as output:
            with patch("src.rqd_exploration.raw_rqd_search.build_mlx_pilot_manifest",
                       return_value=manifest), patch(
                    "src.euler_campaign.mlx_backend.MlxCaseJointFactory"), patch(
                    "src.rqd_exploration.raw_rqd_search.execute_raw_rqd") as execute:
                for reason, expected in (("continuous_batch_limit", 0),
                                         ("raw_rqd_coverage_complete", 0),
                                         ("execution_error", 1)):
                    argv = [
                        "run", "--database", str(Path(output) / f"{reason}.sqlite"),
                        "--output-dir", output, "--confirm-execution",
                        "--continue-from-review", "--continuous",
                    ]
                    execute.return_value = {"reason": reason}
                    with redirect_stdout(StringIO()):
                        self.assertEqual(main(argv), expected)
                    self.assertTrue(execute.call_args.kwargs["continuous"])
                    self.assertTrue(execute.call_args.kwargs["continue_from_review"])


if __name__ == "__main__":
    unittest.main()
