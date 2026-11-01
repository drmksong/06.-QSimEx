from dataclasses import asdict, replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.rqd_exploration.main_analysis import BHPoint, SeedProfile, Target
from src.rqd_exploration.main_controller import MainController, initial_snapshots
from src.rqd_exploration.main_design import input_identity
from src.test.test_rqd_main_policy import load_jn20_config
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
                43: SeedProfile(43, (BHPoint(0, 1, 100, 1),))}}

    def test_three_suitable_prioritizes_full_verification_not_new_search(self):
        self.controller._plan_round(self.target)
        self.assertEqual(self.controller.state["round"]["phase"], "stability")
        self.assertFalse(self.controller.state["round"]["candidates"])
        self.assertTrue(self.controller._plan_stability(self.target))
        queue = self.controller.state["queue"]
        self.assertEqual([t["seed"] for t in queue], [44, 45, 46])
        selected = self.controller.state["round"]["stability_input"]
        self.controller.state["stagnant_rounds"] = 2
        for seed in range(44, 53):
            self.controller.profiles[selected][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 100, 1),))
        self.controller.state["queue"] = []
        self.assertFalse(self.controller._plan_stability(self.target))
        self.controller._complete_round(self.target)
        self.assertEqual(self.controller.state["stagnant_rounds"], 0)

    def test_review_checkpoint_stops_at_10000_starts_until_released(self):
        with patch("src.rqd_exploration.main_controller.starts_consumed", return_value=10_000):
            with self.assertRaises(MainPause) as caught:
                self.controller._check_review_checkpoint()
        self.assertEqual(caught.exception.reason, "review_checkpoint")
        self.controller.state["review_checkpoint_released"] = True
        with patch("src.rqd_exploration.main_controller.starts_consumed", return_value=10_000):
            self.controller._check_review_checkpoint()

    def test_incomparable_pause_requires_explicit_recovery(self):
        identity, seed = self.identities[0], 67
        self.controller.state.update(
            phase="paused",
            reason="incomparable",
            resume_phase="exploration",
            detail=f"no valid BH support for {identity}/{seed}",
            queue=[{"input_id": identity, "seed": seed, "role": "stability"}],
            round={
                "phase": "stability",
                "stability_input": identity,
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
        identity, seed = self.identities[0], 67
        task = {"input_id": identity, "seed": seed, "role": "stability"}
        self.controller.state.update(
            phase="paused",
            reason="incomparable",
            resume_phase="exploration",
            detail=f"no valid BH support for {identity}/{seed}",
            queue=[task],
            round={
                "phase": "stability",
                "stability_input": identity,
                "target": self.target.key,
            },
        )
        self.controller.profiles[identity][self.controller.profile_id][seed] = SeedProfile(
            seed, (BHPoint(0, 1, 80, 1),))
        self.connection.execute(
            "INSERT INTO main_control_starts VALUES (?, 1, ?, ?, '{}', 'stability', 0, "
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
        identity, seed = self.identities[0], 67
        self.controller.state.update(
            phase="paused",
            reason="incomparable",
            resume_phase="exploration",
            detail=f"no valid BH support for {identity}/{seed}",
            queue=[{"input_id": identity, "seed": seed, "role": "stability"}],
            round={
                "phase": "stability",
                "stability_input": identity,
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

    def test_stability_failed_observations_retained_and_block_not_cut_by_stagnation(self):
        self.controller._plan_round(self.target)
        self.controller._plan_stability(self.target)
        selected = self.controller.state["round"]["stability_input"]
        seeds = self.controller.profiles[selected][self.controller.profile_id]
        for seed in range(44, 50):
            seeds[seed] = SeedProfile(seed, (BHPoint(0, 1, 100 if seed < 47 else 10, 1),))
        self.controller.state["queue"] = []
        self.controller.state["stagnant_rounds"] = 2
        self.assertTrue(self.controller._plan_stability(self.target))
        self.assertEqual([t["seed"] for t in self.controller.state["queue"]], [50, 51, 52])
        self.assertEqual(len(seeds), 7)
        self.assertEqual(self.controller.state["stagnant_rounds"], 2)

    def test_co_best_refs_all_preserved_proposed_and_rotated_finite(self):
        self.assertEqual(len(self.controller._references(self.target)), 3)
        # Fewer than three suitable triggers 8/2/2 search from every co-best reference.
        for identity in self.identities:
            self.controller.profiles[identity][self.controller.profile_id][43] = SeedProfile(
                43, (BHPoint(0, 1, 10, 1),))
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
        for identity in self.identities:
            for seed in range(44, 53):
                self.controller.profiles[identity][self.controller.profile_id][seed] = SeedProfile(
                    seed, (BHPoint(0, 1, 100, 1),))
        target_b = Target("10", 2, 4, 1, self.controller.profile_id)
        a, b = self.controller._histories(self.target), self.controller._histories(target_b)
        self.assertEqual(sum(h.stable for h in a.values()), 3)
        self.assertEqual(sum(h.stable for h in b.values()), 3)
        self.assertEqual(len(self.controller.state["inputs"]), 8)
        self.controller.factory.generate.assert_not_called()

    def test_conditional_five_seed_progress_does_not_reset_stagnation_before_round_done(self):
        reference, candidate = self.identities[:2]
        target = Target("1", 2, .5, 20, self.controller.profile_id)
        for seed, raw in ((44, 79), (45, 80), (46, 80)):
            self.controller.profiles[reference][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 80, 1),))
            self.controller.profiles[candidate][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, raw, 1),))
        self.controller.state["round"] = {"phase": "progress", "progress": False,
                                         "progress_pairs": [{
                                             "reference": reference, "candidate": candidate,
                                             "seeds": [44, 45, 46], "effects": [], "decision": None}]}
        self.controller.state["stagnant_rounds"] = 2
        self.controller._finish_progress(target)
        self.assertEqual(self.controller.state["round"]["progress_pairs"][0]["seeds"],
                         [44, 45, 46, 47, 48])
        self.assertEqual(len(self.controller.state["queue"]), 4)
        self.assertEqual(self.controller.state["stagnant_rounds"], 2)
        for seed in (47, 48):
            self.controller.profiles[reference][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 80, 1),))
            self.controller.profiles[candidate][self.controller.profile_id][seed] = SeedProfile(
                seed, (BHPoint(0, 1, 79, 1),))
        self.controller.state["queue"] = []
        self.controller._finish_progress(target)
        self.assertTrue(self.controller.state["round"]["progress"])
        self.assertEqual(self.controller.state["round"]["phase"], "stability")
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
                    for seed in range(43, 53)}}
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
