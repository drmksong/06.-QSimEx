from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from src.rqd_exploration.main_analysis import BHPoint, SeedProfile
from src.rqd_exploration.main_controller import PREVIEW_RUNTIME, reference_snapshot
from src.rqd_exploration.main_design import input_identity
from src.rqd_exploration.main_store import initialize_main_store
from src.rqd_exploration.raw_rqd_search import RawRqdController, load_raw_rqd_config
from src.rqd_exploration.store import initialize_store


class TestRawRqdProbePreparation(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.config = load_raw_rqd_config(
            root / "config/rqd_exploration_main_baseline3.yml")
        self.connection = sqlite3.connect(":memory:")
        initialize_store(self.connection)
        initialize_main_store(self.connection)
        self.output = TemporaryDirectory()
        self.controller = RawRqdController(
            self.connection, self.config, None, PREVIEW_RUNTIME,
            output_dir=Path(self.output.name))
        self.target = self.controller.targets[0]
        self.snapshot = reference_snapshot(self.controller.config, self.controller.runtime)

    def tearDown(self) -> None:
        self.connection.close()
        self.output.cleanup()

    def add_profile(self, p32: float, mean: float, *, count: int = 30,
                    points: tuple[BHPoint, ...] | None = None) -> str:
        joint_set = replace(self.snapshot.joint_sets[0], p32_m2_per_m3=p32)
        snapshot = replace(
            self.snapshot, joint_sets=(joint_set, *self.snapshot.joint_sets[1:]))
        identity = input_identity(snapshot)
        self.controller.state["inputs"][identity] = asdict(snapshot)
        if points is None:
            points = tuple(BHPoint(float(i), float(i + 1), mean, 1.0)
                           for i in range(count))
        seed = self.config.designs[0].realization_seed
        self.controller.profiles[identity] = {
            self.controller.profile_id: {seed: SeedProfile(seed, points)}}
        return identity

    def test_complete_counts_target_selection_and_tie_break(self) -> None:
        for p32 in (1.0, 2.0, 3.0):
            self.add_profile(p32, 5.0)
        left = self.add_profile(4.0, 14.0)
        right = self.add_profile(5.0, 16.0)
        self.add_profile(6.0, 15.0, count=29)
        duplicate = tuple(BHPoint(float(i), float(i + 1), 15.0, 1.0)
                          for i in range(29)) + (BHPoint(28.0, 29.0, 15.0, 1.0),)
        self.add_profile(7.0, 15.0, points=duplicate)

        targets = {item.bin_index: item for item in
                   self.controller._probe_targets(self.target)}

        self.assertNotIn(0, targets)
        self.assertEqual(targets[1].signature_count, 2)
        self.assertEqual(targets[1].reference_id, min(left, right))
        self.assertEqual(len(targets), 9)

    def test_probe_steps_boundaries_reuse_and_no_side_effects(self) -> None:
        original_set = replace(
            self.snapshot.joint_sets[0], p32_m2_per_m3=1.0,
            size_r_min_m=10.0, size_r_max_m=10.0,
            mean_dip_deg=0.0, mean_dip_dir_deg=359.0)
        self.snapshot = replace(
            self.snapshot, joint_sets=(original_set, *self.snapshot.joint_sets[1:]))
        reference = self.add_profile(1.0, 25.0)
        before_state = asdict(self.snapshot)

        probes = self.controller._prepare_probes(self.target, 2)
        first = {(probe.parameter, probe.direction): probe for probe in probes
                 if probe.joint_set_id == original_set.joint_set_id}

        self.assertEqual(len(probes), 40)
        self.assertTrue(all(item.reference_id == reference for item in probes))
        for item in probes:
            if item.snapshot is not None:
                self.controller._validate_generating_input(item.snapshot)
                changed = [
                    (old.joint_set_id, parameter)
                    for old, new in zip(self.snapshot.joint_sets, item.snapshot.joint_sets)
                    for parameter in (
                        "p32_m2_per_m3", "size_r_min_m", "size_r_max_m",
                        "mean_dip_deg", "mean_dip_dir_deg", "size_alpha", "fisher_kappa")
                    if getattr(old, parameter) != getattr(new, parameter)
                ]
                self.assertEqual(changed, [(item.joint_set_id, item.parameter)])
        self.assertEqual(first["p32_m2_per_m3", -1].reason, "unchanged_at_boundary")
        self.assertAlmostEqual(first["p32_m2_per_m3", 1].candidate_value, 1.1)
        self.assertEqual(first["size_r_min_m", 1].reason, "radius_order_violation")
        self.assertEqual(first["size_r_max_m", -1].reason, "radius_order_violation")
        self.assertEqual(first["mean_dip_deg", -1].reason, "unchanged_at_boundary")
        self.assertEqual(first["mean_dip_deg", 1].candidate_value, 5.0)
        self.assertEqual(first["mean_dip_dir_deg", 1].candidate_value, 4.0)
        self.assertEqual(first["mean_dip_dir_deg", -1].candidate_value, 354.0)
        self.assertEqual(self.controller.state["inputs"][reference], before_state)
        self.assertEqual(self.controller.state["queue"], [])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0], 0)
        candidate = first["p32_m2_per_m3", 1]
        self.assertEqual(candidate.status, "new")
        self.assertIsNotNone(candidate.snapshot)
        self.controller.state["inputs"][candidate.candidate_id] = asdict(candidate.snapshot)
        repeated = self.controller._prepare_probes(self.target, 2)
        self.assertEqual(
            next(item.status for item in repeated
                 if item.candidate_id == candidate.candidate_id), "existing")

    def test_exact_bin_edges_and_incomplete_support(self) -> None:
        self.add_profile(1.0, 0.0)
        self.add_profile(2.0, 10.0)
        self.add_profile(3.0, 100.0)
        incomplete = tuple(
            BHPoint(float(i), float(i + 1), 50.0, 0.5 if i == 7 else 1.0)
            for i in range(30))
        self.add_profile(4.0, 50.0, points=incomplete)
        counts = {item.bin_index: item.signature_count
                  for item in self.controller._probe_targets(self.target)}
        self.assertEqual((counts[0], counts[1], counts[5], counts[9]), (1, 1, 0, 1))

    def test_missing_reference_and_filled_target_fail_explicitly(self) -> None:
        targets = self.controller._probe_targets(self.target)
        self.assertEqual(len(targets), 10)
        self.assertTrue(all(item.reference_id is None for item in targets))
        with self.assertRaisesRegex(ValueError, "no complete reference"):
            self.controller._prepare_probes(self.target, 0)
        for p32 in (1.0, 2.0, 3.0):
            self.add_profile(p32, 5.0)
        with self.assertRaisesRegex(ValueError, "underfilled"):
            self.controller._prepare_probes(self.target, 0)

    def test_existing_probe_response_is_reused_and_guides_new_candidate(self) -> None:
        reference = self.add_profile(10.0, 25.0)
        probes = self.controller._prepare_probes(self.target, 0)
        probe = next(
            item for item in probes
            if item.reference_id == reference and item.parameter == "p32_m2_per_m3"
            and item.joint_set_id == self.snapshot.joint_sets[0].joint_set_id
            and item.direction == -1)
        self.assertIsNotNone(probe.snapshot)
        self.controller.state["inputs"][probe.candidate_id] = asdict(probe.snapshot)
        seed = self.config.designs[0].realization_seed
        self.controller.profiles[probe.candidate_id] = {
            self.controller.profile_id: {
                seed: SeedProfile(seed, tuple(
                    BHPoint(float(i), float(i + 1), 20.0, 1.0) for i in range(30)))
            }
        }
        previous = {
            "fixed_jn": 15.0, "input_id": probe.candidate_id,
            "reference_id": reference, "target_response_bin": 0,
            "joint_set_id": probe.joint_set_id, "parameter": probe.parameter,
            "direction": probe.direction, "reference_value": probe.reference_value,
            "candidate_value": probe.candidate_value, "role": "probe",
        }
        response = self.controller._probe_response(
            previous, self.controller._complete_response_means(self.target))
        self.controller.state["last_followup_batch"] = {"probe_responses": [response]}

        candidates, evidence = self.controller._adaptive_candidates(
            self.target, 6, set(self.controller.state["inputs"]))

        reused = next(item for item in evidence if item["input_id"] == probe.candidate_id
                      and item["target_response_bin"] == 0 and item["reference_id"] == reference)
        self.assertTrue(reused["improved"])
        self.assertEqual(reused["response_delta"], -5.0)
        guided = next(item for item in candidates if item["role"] == "response_guided"
                      and item["reference_id"] == probe.candidate_id)
        self.assertEqual(guided["direction"], -1)
        self.assertAlmostEqual(guided["candidate_value"], 10.0 / 1.1 / 1.1)
        self.assertNotIn(probe.candidate_id, [item["input_id"] for item in candidates])


if __name__ == "__main__":
    unittest.main()
