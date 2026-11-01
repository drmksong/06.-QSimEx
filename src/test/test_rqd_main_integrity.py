from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from src.euler_campaign.dfn import DiskJointGeometry
from src.rqd_exploration.adapter import build_generation_case
from src.rqd_exploration.main_analysis import (
    BHPoint, SeedProfile, Target, paired_progress, progress_decision,
)
from src.rqd_exploration.main_controller import MainController, initial_snapshots
from src.rqd_exploration.main_design import input_identity, propose_candidates
from src.test import test_rqd_main_controller as controller_fixtures
from src.test import test_rqd_main_workflow as workflow_fixtures


class TestMainIntegrity(unittest.TestCase):
    def controller_fixture(self):
        fixture = controller_fixtures.TestMainController()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        connection = sqlite3.connect(Path(fixture.directory.name) / "control.sqlite")
        fixture.connection.backup(connection)
        fixture.connection.close()
        connection.execute("PRAGMA foreign_keys = ON")
        fixture.connection = connection
        fixture.controller.connection = connection
        fixture.addCleanup(connection.close)
        return fixture

    def reopen(self, fixture, controller):
        path = controller.connection.execute("PRAGMA database_list").fetchone()[2]
        controller.connection.close()
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        fixture.addCleanup(connection.close)
        fixture.connection = connection
        return MainController(connection, fixture.config, controller.factory,
                              controller.runtime, output_dir=fixture.directory.name)

    def workflow_fixture(self):
        fixture = workflow_fixtures.TestMainWorkflow()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_progress_requires_true_nonadverse_other_metric(self):
        target = Target("1", 2, .5, 20, "bh")
        reference = SeedProfile(44, tuple(BHPoint(i, i + 1, 20, 1) for i in range(60)))
        candidate = SeedProfile(44, tuple(
            BHPoint(i, i + 1, 10 if i == 0 else 20.1, 1) for i in range(60)))
        effect = paired_progress(reference, candidate, target)
        self.assertGreater(effect.delta_distance_rqd, 0)
        self.assertLess(effect.delta_distance_rqd, 1)
        self.assertGreater(effect.delta_support_fraction, .01)
        self.assertEqual(effect.status, "conflict")
        self.assertEqual(progress_decision((effect.status,) * 3), "no_progress")
        ref = SeedProfile(44, tuple(
            BHPoint(i, i + 1, 10 if i == 0 else 100, 1) for i in range(200)))
        cand = SeedProfile(44, tuple(
            BHPoint(i, i + 1, 20 if i == 0 else 98, 1) for i in range(200)))
        effect = paired_progress(ref, cand, target)
        self.assertLess(effect.delta_distance_rqd, -1)
        self.assertEqual(effect.delta_support_fraction, -.005)
        self.assertEqual(effect.status, "conflict")

    def test_exact_nonworsening_metrics_allow_progress(self):
        target = Target("1", 2, .5, 20, "bh")
        effect = paired_progress(
            SeedProfile(44, (BHPoint(0, 1, 100, 1),)),
            SeedProfile(44, (BHPoint(0, 1, 98, 1),)), target)
        self.assertEqual(effect.delta_support_fraction, 0)
        self.assertEqual(effect.status, "progress")
        target = Target("2", 2, .5, 20, "bh")
        self.assertFalse(target.contains(target.rqd_lower))
        effect = paired_progress(
            SeedProfile(44, (BHPoint(0, 1, target.rqd_lower, 1),)),
            SeedProfile(44, (BHPoint(0, 1, 20, 1),)), target)
        self.assertEqual(effect.delta_distance_rqd, 0)
        self.assertEqual(effect.status, "progress")

    def test_five_co_best_refs_preserve_two_full_axis_step_blocks_on_reopen(self):
        fixture = self.controller_fixture()
        controller = fixture.controller
        base = initial_snapshots(fixture.config)[0]
        controller.profiles = {}
        references = []
        for index in range(5):
            joint = replace(base.joint_sets[0], p32_m2_per_m3=3 + .1231 * index,
                            size_r_min_m=50, size_r_max_m=100,
                            mean_dip_deg=45, mean_dip_dir_deg=180)
            snapshot = replace(base, fixed_jn=2, joint_sets=(joint,))
            identity = input_identity(snapshot)
            references.append(identity)
            controller.state["inputs"][identity] = asdict(snapshot)
            controller.profiles[identity] = {controller.profile_id: {
                43: SeedProfile(43, (BHPoint(0, 1, 10, 1),))}}
        profiles = controller.profiles
        used_refs = []
        used_axes = []
        for round_index in range(6):
            controller.state["round"] = None
            controller.state["queue"] = []
            controller._plan_round(fixture.target)
            round_state = controller.state["round"]
            self.assertEqual(set(round_state["references"]), set(references))
            singles = [c for c in round_state["candidates"] if c["role"] == "single_axis"]
            self.assertEqual(len(singles), 8)
            actual = [reason.split("/") for c in singles for reason in c["reasons"]]
            self.assertEqual(len({(p[0], p[1]) for p in actual}), 2)
            used_axes.append({(p[0], p[1]) for p in actual})
            for axis in {(p[0], p[1]) for p in actual}:
                self.assertEqual({(p[2], p[3]) for p in actual if (p[0], p[1]) == axis},
                                 {("small", "-1"), ("small", "1"), ("large", "-1"), ("large", "1")})
            selected_ref = singles[0]["references"][0]
            self.assertTrue(all(selected_ref in c["references"] for c in singles))
            used_refs.append(selected_ref)
            controller.profiles = dict(profiles)
            for candidate in round_state["candidates"]:
                controller.profiles[candidate["input_id"]] = {controller.profile_id: {
                    43: SeedProfile(43, (BHPoint(0, 1, 10, 1),))}}
            controller.state["queue"] = []
            controller._plan_progress(fixture.target)
            controller.profiles = profiles
            controller._save()
            reopened = self.reopen(fixture, controller)
            self.assertEqual(reopened.state["round"], controller.state["round"])
            reopened.profiles = profiles
            controller = reopened
        self.assertEqual(len(set(used_refs[:5])), 5)
        self.assertEqual(used_refs[:5], sorted(references))
        self.assertEqual(used_refs[5], used_refs[0])
        self.assertNotEqual(used_axes[5], used_axes[0])

    def test_crash_after_third_completed_round_commit_resumes_without_extra_starts(self):
        fixture = self.controller_fixture()
        controller = fixture.controller
        controller.state["stagnant_rounds"] = 2
        controller.state["round_index"] = 3
        controller.state["round"] = {
            "round_index": 3, "target": fixture.target.key, "phase": "stability",
            "before_suitable": fixture.identities, "progress": False, "proposals": []}
        # The pause exception is constructed after the completed-round checkpoint commits.
        with patch("src.rqd_exploration.main_controller.MainPause", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                controller._complete_round(fixture.target)
        reopened = self.reopen(fixture, controller)
        with patch.object(reopened, "_plan_round", side_effect=AssertionError("must not plan more work")):
            summary = reopened.run()
        self.assertEqual(summary["reason"], "stagnation")
        self.assertEqual(summary["starts_consumed"], 0)
        controller.factory.generate.assert_not_called()

    def test_completed_round_journal_is_immutable_atomic_and_survives_reopen(self):
        fixture = self.controller_fixture()
        controller = fixture.controller
        expected = []
        for index in (1, 2):
            controller.state["round_index"] = index
            completed = {
                "round_index": index, "target": fixture.target.key, "phase": "stability",
                "before_suitable": fixture.identities, "progress": False,
                "references": [fixture.identities[index - 1]],
                "proposals": [{"status": "skipped", "skip_reason": f"bounds-{index}"}],
                "progress_pairs": [{"reference": fixture.identities[0], "candidate": fixture.identities[1],
                                    "seeds": [44, 45, 46], "decision": "no_progress"}]}
            expected.append(completed)
            controller.state["round"] = completed
            controller._complete_round(fixture.target)
        rows = fixture.connection.execute(
            "SELECT payload FROM main_control_events WHERE kind='round_complete' ORDER BY event_index").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([json.loads(r[0])["completed_round"] for r in rows], expected)
        reopened = self.reopen(fixture, controller)
        reopened.state["phase"] = "paused"
        reopened.state["reason"] = "high_cost_review"
        reopened._save(status="paused", reason="high_cost_review")
        reopened.run()
        reopened._complete_round(fixture.target)
        self.assertEqual(fixture.connection.execute(
            "SELECT payload FROM main_control_events WHERE kind='round_complete' ORDER BY event_index").fetchall(),
                         rows)
        with self.assertRaises(sqlite3.IntegrityError):
            fixture.connection.execute(
                "UPDATE main_control_events SET payload='{}' WHERE kind='round_complete'")

    def test_failed_round_checkpoint_rolls_back_history_and_retains_pending_round(self):
        fixture = self.controller_fixture()
        controller = fixture.controller
        completed = {"round_index": 1, "target": fixture.target.key,
                     "before_suitable": fixture.identities, "progress": False,
                     "proposals": [{"skip_reason": "radius order"}]}
        controller.state["round_index"] = 1
        controller.state["round"] = completed
        controller._save()
        with patch.object(controller, "_save", side_effect=RuntimeError("checkpoint failure")):
            with self.assertRaisesRegex(RuntimeError, "checkpoint failure"):
                controller._complete_round(fixture.target)
        self.assertEqual(controller.state["round"], completed)
        self.assertEqual(fixture.connection.execute(
            "SELECT COUNT(*) FROM main_control_events WHERE kind='round_complete'").fetchone()[0], 0)
        reopened = self.reopen(fixture, controller)
        self.assertEqual(reopened.state["round"], completed)
        self.assertEqual(reopened.state["stagnant_rounds"], 0)
        reopened._complete_round(fixture.target)
        reopened._complete_round(fixture.target)
        self.assertEqual(fixture.connection.execute(
            "SELECT COUNT(*) FROM main_control_events WHERE kind='round_complete'").fetchone()[0], 1)

    def test_resume_stagnation_guard_does_not_cut_an_active_verification_block(self):
        fixture = self.controller_fixture()
        controller = fixture.controller
        controller._plan_round(fixture.target)
        controller._plan_stability(fixture.target)
        controller.state["stagnant_rounds"] = 3
        with patch.object(controller, "_perform", side_effect=SystemExit("verification continues")) as perform:
            with self.assertRaisesRegex(SystemExit, "verification continues"):
                controller.run()
        self.assertEqual(perform.call_args.args[0]["role"], "stability")

    def test_paused_reopen_reuses_reports_without_rewriting_bytes_or_mtimes(self):
        fixture = self.workflow_fixture()
        fixture.factory.generate.side_effect = RuntimeError("pause")
        self.assertEqual(fixture.command(*fixture.run_args())[0], 1)
        files = list(fixture.output.glob("cumulative/**/*"))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files if p.is_file()}
        self.assertTrue(before)
        self.assertEqual(fixture.command(*fixture.run_args())[0], 1)
        for p, (data, mtime) in before.items():
            self.assertTrue(p.read_bytes() == data, str(p))
            self.assertEqual(p.stat().st_mtime_ns, mtime, str(p))
        self.assertEqual(fixture.factory.generate.call_count, 1)

    def test_main_full_catalog_export_preserves_legacy_subset_report(self):
        fixture = self.workflow_fixture()
        fixture.factory.generate.side_effect = [DiskJointGeometry(()), RuntimeError("pause")]
        code, _, stderr = fixture.command(*fixture.run_args())
        self.assertEqual(code, 1, stderr)
        shared = next(fixture.output.glob("cumulative/revision-*/reports"))
        code, payload, stderr = fixture.command(
            "report-cumulative", "--database", str(fixture.database),
            "--jr-values", "1", "--ja-values", "1", "--output-dir", str(shared))
        self.assertEqual(code, 0, stderr)
        subset_identity = payload["analysis_fingerprint_sha256"]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in shared.iterdir() if p.is_file()}
        self.assertEqual(fixture.command(*fixture.run_args())[0], 1)
        for p, (data, mtime) in before.items():
            self.assertTrue(p.read_bytes() == data, str(p))
            self.assertEqual(p.stat().st_mtime_ns, mtime, str(p))
        summaries = [json.loads(p.read_text()) for p in fixture.output.glob(
            "cumulative/revision-*/analysis-*/reports/report_summary.json")]
        self.assertTrue(any(s["analysis_fingerprint_sha256"] != subset_identity for s in summaries))

    def test_constant_radius_main_candidate_reaches_factory_measurement_and_raw_store(self):
        fixture = self.controller_fixture()
        controller = fixture.controller
        base = initial_snapshots(fixture.config)[0]
        snapshot = replace(base, fixed_jn=2, joint_sets=(replace(
            base.joint_sets[0], p32_m2_per_m3=1., size_r_min_m=1., size_r_max_m=2.),))
        batch = propose_candidates(snapshot, fixture.config.templates[2],
                                   round_index=1, cursor=1, rng_seed=40)
        candidate = next(c for c in batch.candidates
                         if "0/size_r_min_m/large/1" in c.reasons)
        self.assertEqual((candidate.snapshot.joint_sets[0].size_r_min_m,
                          candidate.snapshot.joint_sets[0].size_r_max_m), (2., 2.))
        controller.state["inputs"][candidate.input_id] = asdict(candidate.snapshot)
        controller.factory.generate.return_value = DiskJointGeometry(())
        controller._perform({"input_id": candidate.input_id, "seed": 43, "role": "single_axis"})
        case = controller.factory.generate.call_args.args[0]
        self.assertEqual((case.joint_sets[0].size_r_min, case.joint_sets[0].size_r_max), (2., 2.))
        self.assertEqual(fixture.connection.execute("SELECT status FROM attempts").fetchall(), [("succeeded",)])
        self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 121)
        with self.assertRaisesRegex(ValueError, "sampled radii"):
            build_generation_case(fixture.config.reference_input.geometry, fixture.config.reference_input.measurements,
                                  2., candidate.snapshot.joint_sets, case_id="strict-pilot")
