from dataclasses import replace
import unittest
from unittest.mock import patch

from src.rqd_exploration.design import generate_lhs_design
from src.rqd_exploration.main_design import (
    expected_joint_counts, input_identity, propose_candidates,
)
from src.test.test_rqd_main_policy import load_jn20_config


class TestMainDesign(unittest.TestCase):
    def setUp(self):
        self.config = load_jn20_config()
        from src.rqd_exploration.main_controller import initial_snapshots
        self.snapshot = initial_snapshots(self.config)[0]

    def test_identity_ignores_seed_runtime_not_generation(self):
        self.assertEqual(input_identity(self.snapshot),
                         input_identity(replace(self.snapshot, realization_seed=100)))
        changed = replace(self.snapshot.joint_sets[0], p32_m2_per_m3=.02)
        self.assertNotEqual(input_identity(self.snapshot), input_identity(
            replace(self.snapshot, joint_sets=(changed,) + self.snapshot.joint_sets[1:])))

    def test_finite_rotating_deterministic_8_2_2_and_frozen_shapes(self):
        a = propose_candidates(self.snapshot, self.config.templates[20],
                               round_index=1, cursor=0, rng_seed=40)
        b = propose_candidates(self.snapshot, self.config.templates[20],
                               round_index=1, cursor=0, rng_seed=40)
        self.assertEqual(a, b)
        self.assertLessEqual(len(a.candidates), 12)
        self.assertEqual(len(a.proposals), 12)
        for candidate in a.candidates:
            if candidate.role != "lhs":
                self.assertEqual([(s.size_alpha, s.fisher_kappa)
                                  for s in candidate.snapshot.joint_sets],
                                 [(s.size_alpha, s.fisher_kappa)
                                  for s in self.snapshot.joint_sets])
        rotated = propose_candidates(self.snapshot, self.config.templates[20],
                                     round_index=2, cursor=a.next_cursor, rng_seed=40)
        self.assertNotEqual(a.proposals[:8], rotated.proposals[:8])

    def test_expected_area_shared_scalar_no_generation(self):
        from math import prod
        with patch("src.euler_campaign.dfn._expected_joint_area", return_value=1):
            result = expected_joint_counts(self.snapshot)
            expected = sum(s.p32_m2_per_m3 * prod(self.snapshot.geometry.domain_size_m)
                           for s in self.snapshot.joint_sets)
        self.assertAlmostEqual(sum(result.values()),
                               expected)

    def test_bounds_skip_no_clamp_or_radius_swap_and_duplicates_finite(self):
        joint = replace(self.snapshot.joint_sets[0], size_r_min_m=1., size_r_max_m=1.)
        reference = replace(self.snapshot, joint_sets=(joint,) + self.snapshot.joint_sets[1:])
        batch = propose_candidates(reference, self.config.templates[20],
                                   round_index=1, cursor=1, rng_seed=40)
        reasons = [p.get("skip_reason", "") for p in batch.proposals]
        self.assertTrue(any("outside bounds" in r for r in reasons))
        self.assertTrue(any("radius order" in r for r in reasons))
        self.assertEqual((joint.size_r_min_m, joint.size_r_max_m), (1., 1.))
        seen = [c.input_id for c in batch.candidates]
        duplicate = propose_candidates(reference, self.config.templates[20],
                                       round_index=1, cursor=1, rng_seed=40, seen=seen)
        self.assertFalse(duplicate.candidates)
        self.assertEqual(len(duplicate.proposals), 12)
