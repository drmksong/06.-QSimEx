from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.rqd_exploration.main_analysis import BHPoint, SeedProfile, Target
from src.rqd_exploration.main_controller import MainController, initial_snapshots
from src.rqd_exploration.main_design import input_identity
from src.test.test_rqd_main_policy import (
    load_jn20_config, load_main_config, main_config_with_seeds,
)
from src.rqd_exploration.main_store import MainPause, initialize_main_store
from src.rqd_exploration.store import initialize_store


ROOT = Path(__file__).resolve().parents[2]


class TestMainController(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        initialize_store(self.connection)
        initialize_main_store(self.connection)
        self.config = load_jn20_config()
        snapshot = initial_snapshots(self.config)[0]
        self.controller = MainController(self.connection, self.config, Mock(), snapshot.runtime,
                                         output_dir=Path(self.directory.name))
        self.controller.state["queue"] = []
        self.controller.state["phase"] = "exploration"
        self.target = Target("10", 2, 4, .75, self.controller.profile_id)
        base = replace(snapshot, fixed_jn=2, joint_sets=(snapshot.joint_sets[0],))
        self.identities = []
        for index in range(3):
            current = replace(base, joint_sets=(
                replace(base.joint_sets[0], p32_m2_per_m3=1. + index),))
            identity = input_identity(current)
            self.identities.append(identity)
            self.controller.state["inputs"][identity] = asdict(current)
            self.controller.profiles[identity] = {self.controller.profile_id: {
                self.config.policy.initial_seed: SeedProfile(
                    self.config.policy.initial_seed, (BHPoint(0, 1, 100, 1),))}}

    def test_policy_change_creates_separate_run_and_preserves_prior_state(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        initialize_store(connection)
        initialize_main_store(connection)
        baseline = load_main_config(ROOT / "config/rqd_exploration_main.yml")
        changed = main_config_with_seeds(self.directory.name, 107, 311)
        runtime = self.controller.runtime

        original = MainController(
            connection, baseline, Mock(), runtime, output_dir=Path(self.directory.name))
        original.state["round_index"] = 7
        original._save(status="paused", reason="user_interruption")
        updated = MainController(
            connection, changed, Mock(), runtime, output_dir=Path(self.directory.name))

        self.assertNotEqual(original.run_id, updated.run_id)
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM main_control_runs").fetchone()[0], 2)
        prior = connection.execute(
            "SELECT state_json,status,reason FROM main_control_runs WHERE run_id=?",
            (original.run_id,)).fetchone()
        self.assertEqual(json.loads(prior[0])["round_index"], 7)
        self.assertEqual(prior[1:], ("paused", "user_interruption"))

    def test_initial_support_queues_configured_verification_seeds(self):
        self.controller._plan_round(self.target)
        self.assertEqual(self.controller.state["round"]["phase"], "verification")
        self.assertFalse(self.controller.state["round"]["candidates"])
        self.assertTrue(self.controller._plan_target_verification(self.target))
        queue = self.controller.state["queue"]
        verify_start = self.config.policy.verification_seed
        expected_seeds = list(range(verify_start, verify_start + 3))
        self.assertEqual([t["seed"] for t in queue], expected_seeds)
        self.assertTrue(all(t["role"] == "target_verification" for t in queue))
        selected = self.controller.state["round"]["verification_input"]
        for seed in expected_seeds[:2]:
            self.controller.profiles[selected][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 100, 1),))
        self.controller.profiles[selected][self.controller.profile_id][expected_seeds[2]] = SeedProfile(
            expected_seeds[2], (BHPoint(0, 1, self.target.rqd_lower, 1),))
        self.controller.state["queue"] = []
        self.assertFalse(self.controller._plan_target_verification(self.target))
        self.assertTrue(self.controller._histories(self.target)[selected].passed)

    def test_controller_schedules_nondefault_seed_values(self):
        config = main_config_with_seeds(self.directory.name, 107, 311)
        controller = MainController(
            self.connection, config, Mock(), self.controller.runtime,
            output_dir=Path(self.directory.name))
        identity = self.identities[0]
        controller.state["inputs"][identity] = self.controller.state["inputs"][identity]
        controller.profiles[identity] = {controller.profile_id: {
            107: SeedProfile(107, (BHPoint(0, 1, 100, 1),))}}
        controller.state["round"] = {
            "phase": "verification", "verification_input": identity}
        target = Target("10", 2, 4, .75, controller.profile_id)

        self.assertTrue(controller._plan_target_verification(target))
        self.assertEqual([task["seed"] for task in controller.state["queue"]],
                         [311, 312, 313])
        self.assertTrue(all(task["role"] == "target_verification"
                            for task in controller.state["queue"]))

    def test_summary_reports_configured_seed_evidence_and_global_progress(self):
        config = main_config_with_seeds(self.directory.name, 107, 311)
        controller = MainController(
            self.connection, config, Mock(), self.controller.runtime,
            output_dir=Path(self.directory.name))
        identity = self.identities[0]
        controller.state["inputs"][identity] = self.controller.state["inputs"][identity]
        target = Target("10", 2, 4, .75, controller.profile_id)
        controller.profiles[identity] = {controller.profile_id: {
            107: SeedProfile(107, (BHPoint(0, 1, 100, 1),)),
            311: SeedProfile(311, (BHPoint(0, 1, 100, 1),)),
            312: SeedProfile(312, (BHPoint(0, 1, 100, 1),)),
            313: SeedProfile(313, (BHPoint(0, 1, target.rqd_lower, 1),)),
            314: SeedProfile(314, (BHPoint(0, 1, 100, 1),)),
        }}
        controller._histories(target)
        task = {"input_id": identity, "seed": 313, "role": "target_verification"}
        controller.state["round"] = {
            "phase": "verification", "target": target.key, "verification_input": identity}
        controller.state["queue"] = [task]

        summary = controller.summary()
        bin_progress = summary["current_bin_progress"]
        target_progress = bin_progress["targets"][target.key]
        input_progress = target_progress["input_progress"][identity]

        self.assertEqual(summary["target_pass_rule"], {
            "initial_seed": 107,
            "initial_positive_support_required": True,
            "verification_seeds": [311, 312, 313],
            "required_verification_passes": 2,
        })
        self.assertEqual(summary["starts_consumed"], 0)
        self.assertEqual(summary["starts_maximum"], config.policy.maximum_starts)
        self.assertEqual(summary["starts_remaining"], config.policy.maximum_starts)
        self.assertEqual(summary["passed_target_count"], 1)
        self.assertEqual(bin_progress["passed_target_count"], 1)
        self.assertEqual(bin_progress["evaluated_target_count"], 1)
        self.assertEqual(target_progress["status"], "passed")
        self.assertEqual(input_progress["positive_verification_count"], 2)
        self.assertEqual(summary["verification_seeds_by_input"][identity], [311, 312, 313])
        self.assertEqual(summary["current_work"]["job_stage"], "queued")

        log_context = controller._format_progress_context(task, 4)
        self.assertIn("starts=4/20000 remaining=19996", log_context)
        self.assertIn("targets_passed=1/", log_context)
        self.assertIn("phase=exploration/verification", log_context)
        self.assertIn(f"input={identity} seed=313", log_context)
        self.assertIn("initial_support=true verification_positive=2/3 required=2", log_context)

    def test_review_checkpoint_stops_at_10000_starts_until_released(self):
        with patch("src.rqd_exploration.main_controller.starts_consumed", return_value=10_000):
            with self.assertRaises(MainPause) as caught:
                self.controller._check_review_checkpoint()
        self.assertEqual(caught.exception.reason, "review_checkpoint")
        self.controller.state["review_checkpoint_released"] = True
        with patch("src.rqd_exploration.main_controller.starts_consumed", return_value=10_000):
            self.controller._check_review_checkpoint()

    def test_incomparable_pause_requires_explicit_recovery(self):
        identity = self.identities[0]
        seed = self.config.policy.verification_seed
        self.controller.state.update(
            phase="paused",
            reason="incomparable",
            resume_phase="exploration",
            detail=f"no valid BH support for {identity}/{seed}",
            queue=[{"input_id": identity, "seed": seed, "role": "target_verification"}],
            round={
                "phase": "verification",
                "verification_input": identity,
                "target": self.target.key,
            },
        )
        self.controller._save(status="paused", reason="incomparable")

        with patch("src.rqd_exploration.main_controller.reconcile_starts"):
            summary = self.controller.run()

        self.assertEqual(summary["reason"], "incomparable")
        self.assertEqual(self.controller.state["phase"], "paused")
        self.controller.factory.generate.assert_not_called()

    def test_guarded_incomparable_recovery_reuses_saved_sample_without_new_start(self):
        identity = self.identities[0]
        seed = self.config.policy.verification_seed
        task = {"input_id": identity, "seed": seed, "role": "target_verification"}
        self.controller.state.update(
            phase="paused",
            reason="incomparable",
            resume_phase="exploration",
            detail=f"no valid BH support for {identity}/{seed}",
            queue=[task],
            round={
                "phase": "verification",
                "verification_input": identity,
                "target": self.target.key,
            },
        )
        self.controller.profiles[identity][self.controller.profile_id][seed] = SeedProfile(
            seed, (BHPoint(0, 1, 80, 1),))
        self.connection.execute(
            "INSERT INTO main_control_starts VALUES (?, 1, ?, ?, '{}', 'target_verification', 0, "
            "'succeeded', '{}')",
            (self.controller.run_id, identity, seed),
        )
        self.controller._save(status="paused", reason="incomparable")
        perform = self.controller._perform

        def perform_then_stop(queued_task):
            perform(queued_task)
            raise SystemExit("stopped after validating the recovered queue item")

        with patch("src.rqd_exploration.main_controller.reconcile_starts"):
            with patch.object(self.controller, "_perform", side_effect=perform_then_stop):
                with self.assertRaisesRegex(SystemExit, "stopped after validating"):
                    self.controller.run(recover_incomparable=True)

        self.assertEqual(task["result"], "reused")
        self.assertEqual(self.controller.state["phase"], "exploration")
        self.assertIsNone(self.controller.state["reason"])
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM main_control_starts WHERE run_id=?",
            (self.controller.run_id,),
        ).fetchone()[0], 1)
        self.controller.factory.generate.assert_not_called()

    def test_guarded_incomparable_recovery_refuses_without_restored_support(self):
        identity = self.identities[0]
        seed = self.config.policy.verification_seed
        self.controller.state.update(
            phase="paused",
            reason="incomparable",
            resume_phase="exploration",
            detail=f"no valid BH support for {identity}/{seed}",
            queue=[{"input_id": identity, "seed": seed, "role": "target_verification"}],
            round={
                "phase": "verification",
                "verification_input": identity,
                "target": self.target.key,
            },
        )
        self.controller._save(status="paused", reason="incomparable")

        with patch("src.rqd_exploration.main_controller.reconcile_starts"):
            with self.assertRaisesRegex(ValueError, "still has no valid BH support"):
                self.controller.run(recover_incomparable=True)

        self.assertEqual(self.controller.state["phase"], "paused")
        self.assertEqual(self.controller.state["reason"], "incomparable")
        self.controller.factory.generate.assert_not_called()

    def test_guarded_incomparable_recovery_rejects_nonverification_seed(self):
        identity = self.identities[0]
        seed = self.config.policy.verification_seed + 3
        self.controller.state.update(
            phase="paused",
            reason="incomparable",
            resume_phase="exploration",
            detail=f"no valid BH support for {identity}/{seed}",
            queue=[{"input_id": identity, "seed": seed, "role": "target_verification"}],
            round={
                "phase": "verification",
                "verification_input": identity,
                "target": self.target.key,
            },
        )
        self.controller.profiles[identity][self.controller.profile_id][seed] = SeedProfile(
            seed, (BHPoint(0, 1, 80, 1),))
        self.controller._save(status="paused", reason="incomparable")

        with patch("src.rqd_exploration.main_controller.reconcile_starts"):
            with self.assertRaisesRegex(ValueError, "outside configured verification seeds"):
                self.controller.run(recover_incomparable=True)

        self.assertEqual(self.controller.state["phase"], "paused")
        self.assertEqual(self.controller.state["reason"], "incomparable")
        self.controller.factory.generate.assert_not_called()

    def test_failed_seed_pass_keeps_observations_and_only_queues_missing_seed(self):
        self.controller._plan_round(self.target)
        self.controller._plan_target_verification(self.target)
        selected = self.controller.state["round"]["verification_input"]
        seeds = self.controller.profiles[selected][self.controller.profile_id]
        verify_start = self.config.policy.verification_seed
        for seed in range(verify_start, verify_start + 2):
            seeds[seed] = SeedProfile(
                seed, (BHPoint(0, 1, 100 if seed == verify_start else 10, 1),))
        self.controller.state["queue"] = []
        self.assertTrue(self.controller._plan_target_verification(self.target))
        self.assertEqual(
            [t["seed"] for t in self.controller.state["queue"]], [verify_start + 2])
        self.assertEqual(len(seeds), 3)

    def test_co_best_refs_all_preserved_proposed_and_rotated_finite(self):
        self.assertEqual(len(self.controller._references(self.target)), 3)
        # Fewer than three suitable triggers 8/2/2 search from every co-best reference.
        for identity in self.identities:
            seed = self.config.policy.initial_seed
            self.controller.profiles[identity][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 10, 1),))
        self.controller._plan_round(self.target)
        round_state = self.controller.state["round"]
        self.assertEqual(len(round_state["references"]), 3)
        self.assertEqual(len(round_state["proposals"]), 36)
        self.assertLessEqual(len(round_state["candidates"]), 12)
        for role, limit in (("single_axis", 8), ("multi_axis", 2), ("lhs", 2)):
            self.assertLessEqual(sum(c["role"] == role for c in round_state["candidates"]), limit)
        self.assertEqual(len(self.controller.state["axis_cursors"]), 3)

    def test_completed_rounds_only_stagnate_three_and_new_input_resets(self):
        for index in range(3):
            self.controller.state["round"] = {
                "before_suitable": self.identities, "progress": False}
            if index == 2:
                with self.assertRaises(MainPause) as raised:
                    self.controller._complete_round(self.target)
                self.assertEqual(raised.exception.reason, "stagnation")
            else:
                self.controller._complete_round(self.target)
        self.assertEqual(self.controller.state["stagnant_rounds"], 3)

    def test_same_verification_results_reused_across_targets(self):
        verify_start = self.config.policy.verification_seed
        for identity in self.identities:
            for seed in range(verify_start, verify_start + 3):
                self.controller.profiles[identity][self.controller.profile_id][seed] = SeedProfile(
                    seed, (BHPoint(0, 1, 100, 1),))
        target_b = Target("10", 2, 4, 1, self.controller.profile_id)
        a, b = self.controller._histories(self.target), self.controller._histories(target_b)
        self.assertEqual(sum(h.passed for h in a.values()), 3)
        self.assertEqual(sum(h.passed for h in b.values()), 3)
        self.assertEqual(len(self.controller.state["inputs"]), 8)
        self.controller.factory.generate.assert_not_called()

    def test_conditional_five_seed_progress_does_not_reset_stagnation_before_round_done(self):
        reference, candidate = self.identities[:2]
        target = Target("1", 2, .5, 20, self.controller.profile_id)
        verify_start = self.config.policy.verification_seed
        verification_seeds = list(range(verify_start, verify_start + 3))
        for seed, raw in zip(verification_seeds, (79, 80, 80)):
            self.controller.profiles[reference][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 80, 1),))
            self.controller.profiles[candidate][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, raw, 1),))
        self.controller.state["round"] = {"phase": "progress", "progress": False,
                                         "progress_pairs": [{
                                             "reference": reference, "candidate": candidate,
                                             "seeds": list(verification_seeds),
                                             "effects": [], "decision": None}]}
        self.controller.state["stagnant_rounds"] = 2
        self.controller._finish_progress(target)
        self.assertEqual(self.controller.state["round"]["progress_pairs"][0]["seeds"],
                         verification_seeds + [verify_start + 3, verify_start + 4])
        self.assertEqual(len(self.controller.state["queue"]), 4)
        self.assertEqual(self.controller.state["stagnant_rounds"], 2)
        for seed in (verify_start + 3, verify_start + 4):
            self.controller.profiles[reference][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 80, 1),))
            self.controller.profiles[candidate][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 79, 1),))
        self.controller.state["queue"] = []
        self.controller._finish_progress(target)
        self.assertTrue(self.controller.state["round"]["progress"])
        self.assertEqual(self.controller.state["round"]["phase"], "verification")
        self.assertEqual(len(self.controller.state["round"]["progress_pairs"][0]["effects"]), 5)

    def test_no_measured_reference_lhs_counts_inside_round_limit(self):
        self.controller.profiles = {}
        self.controller._plan_round(self.target)
        candidates = self.controller.state["round"]["candidates"]
        self.assertEqual(len(candidates), 12)
        self.assertTrue(all(c["role"] == "lhs" for c in candidates))
        self.assertEqual(len(self.controller.state["queue"]), len(candidates))
        self.controller.factory.generate.assert_not_called()

    def test_last_bin_completion_requires_all_reachable_targets_and_no_new_generation(self):
        base = initial_snapshots(self.config)[0]
        self.controller.profiles = {}
        for jn, count in ((2, 1), (4, 2), (9, 3), (15, 4), (20, 5)):
            for index in range(3):
                snapshot = replace(base, fixed_jn=jn, joint_sets=tuple(
                    replace(s, p32_m2_per_m3=1. + index) for s in base.joint_sets[:count]))
                identity = input_identity(snapshot)
                self.controller.state["inputs"][identity] = asdict(snapshot)
                self.controller.profiles[identity] = {self.controller.profile_id: {
                    seed: SeedProfile(seed, (BHPoint(0, 1, 10, 1),))
                    for seed in (self.config.policy.initial_seed,
                                 *range(self.config.policy.verification_seed,
                                        self.config.policy.verification_seed + 3))}}
        self.controller.state["bin"] = 1
        self.controller.state["queue"] = []
        summary = self.controller.run()
        self.assertEqual(summary["reason"], "targets_complete")
        self.assertEqual(summary["phase"], "complete")
        self.assertEqual(summary["starts_consumed"], 0)
        self.assertEqual(summary["bin"], 0)
        self.controller.factory.generate.assert_not_called()
        self.assertEqual(self.connection.execute(
            "SELECT kind FROM main_control_events ORDER BY event_index").fetchall(),
                         [("bin_transition",), ("complete",)])

    def test_direct_confirmation_and_cpu_rejection_before_control_ddl(self):
        from src.rqd_exploration.main_controller import execute_main
        with sqlite3.connect(":memory:") as connection:
            with self.assertRaises(PermissionError):
                execute_main(connection, self.config, self.controller.factory,
                             self.controller.runtime, output_dir=self.directory.name)
            with self.assertRaisesRegex(ValueError, "MLX"):
                execute_main(connection, self.config, self.controller.factory,
                             replace(self.controller.runtime, backend="cpu"), confirmed=True,
                             output_dir=self.directory.name)
            with self.assertRaisesRegex(ValueError, "existing schema4 database"):
                execute_main(connection, self.config, self.controller.factory,
                             self.controller.runtime, confirmed=True,
                             output_dir=self.directory.name, recover_incomparable=True)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0], 0)
        self.controller.factory.generate.assert_not_called()
