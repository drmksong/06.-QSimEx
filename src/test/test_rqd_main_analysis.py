import unittest

from src.rqd_exploration.analysis import BIN_EDGES
from src.rqd_exploration.main_analysis import (
    BHPoint, SeedProfile, Target, paired_progress, progress_decision,
    seed_pass_result, target_passed,
)


def profile(seed, raw=80., support=1., offset=0.):
    return SeedProfile(seed, (BHPoint(offset, offset + 1., raw, support),))


class TestMainAnalysis(unittest.TestCase):
    def test_inverse_exact_open_lower_and_reachability(self):
        lower = BIN_EDGES[9]
        target = Target("10", 2, 4, .75, "bh")
        self.assertTrue(target.reachable)
        self.assertFalse(Target("10", 20, .5, 20, "bh").reachable)
        self.assertEqual(target.rqd_lower, lower * 2 * .75 / 4)
        self.assertFalse(target.contains(target.rqd_lower))
        self.assertTrue(target.contains(100))

    def test_three_to_five_and_no_seed_replacement(self):
        self.assertEqual(progress_decision(("progress",) * 2 + ("adverse",)), "progress")
        self.assertEqual(progress_decision(("progress", "same", "same")), "extend")
        self.assertEqual(progress_decision(("same",) * 3), "no_progress")
        self.assertEqual(progress_decision(
            ("progress", "adverse", "same", "progress", "progress")), "progress")
        self.assertEqual(progress_decision(
            ("progress", "adverse", "same", "progress", "same")), "no_progress")
        with self.assertRaises(ValueError):
            progress_decision(("progress", "progress"))

    def test_floor_common_support_and_face_not_in_api(self):
        target = Target("1", 2, .5, 20, "bh")
        self.assertEqual(paired_progress(profile(44, 5), profile(44, 0), target).status,
                         "same")
        self.assertEqual(paired_progress(profile(44), profile(44, offset=.5),
                                         target).status, "incomparable")
        self.assertEqual(paired_progress(profile(44), profile(44, support=0),
                                         target).status, "incomparable")
        self.assertEqual(paired_progress(profile(44), profile(44, support=.99),
                                         target).status, "incomparable")
        self.assertEqual(paired_progress(profile(311, 5), profile(311, 0), target).status,
                         "same")
        with self.assertRaises(ValueError):
            paired_progress(profile(311), profile(312), target)

    def test_per_seed_progress_requires_nonadverse_other_metric(self):
        target = Target("1", 2, .5, 20, "bh")
        self.assertEqual(paired_progress(profile(44, 80), profile(44, 79), target).status,
                         "progress")
        self.assertEqual(paired_progress(profile(44, 80), profile(44, 79.001), target).status,
                         "same")
        reference = SeedProfile(44, (BHPoint(0, 100, 30, 50), BHPoint(100, 200, 30, 50)))
        candidate = SeedProfile(44, (BHPoint(0, 100, 10, 50), BHPoint(100, 200, 100, 50)))
        effect = paired_progress(reference, candidate, target)
        self.assertGreaterEqual(effect.delta_support_fraction, .01)
        self.assertGreaterEqual(effect.delta_distance_rqd, 1)
        self.assertEqual(effect.status, "conflict")
        shortened = paired_progress(
            SeedProfile(44, (BHPoint(0, 2, 10, 2),)), profile(44, 10), target)
        self.assertEqual(shortened.status, "same")
        self.assertEqual(shortened.common_reference_fraction, .5)

    def test_seed_pass_requires_initial_and_two_of_three_verification_seeds(self):
        target = Target("10", 2, 4, .75, "bh")
        passing = lambda seed: profile(seed, raw=100)
        failing = lambda seed: profile(seed, raw=target.rqd_lower)
        initial_seed, verification_seed = 107, 108
        evaluate = lambda *profiles: seed_pass_result(
            profiles, target, initial_seed=initial_seed, verification_seed=verification_seed)

        zero = evaluate(passing(initial_seed), *(failing(seed) for seed in range(108, 111)))
        one = evaluate(passing(initial_seed), passing(108), failing(109), failing(110))
        two = evaluate(passing(initial_seed), passing(108), passing(109), failing(110))
        three = evaluate(*(passing(seed) for seed in range(107, 111)))
        initial_failure = evaluate(failing(initial_seed), *(passing(seed) for seed in range(108, 111)))
        missing_initial = evaluate(*(passing(seed) for seed in range(108, 111)))
        one_a = evaluate(passing(initial_seed), passing(108), failing(109), failing(110))
        one_b = evaluate(passing(initial_seed), failing(108), passing(109), failing(110))

        self.assertTrue(zero.complete)
        self.assertEqual(zero.initial_seed, initial_seed)
        self.assertEqual(zero.verification_seeds, (108, 109, 110))
        self.assertEqual(zero.positive_verification_count, 0)
        self.assertFalse(zero.passed)
        self.assertEqual(one.positive_verification_count, 1)
        self.assertFalse(one.passed)
        self.assertEqual(two.positive_verification_count, 2)
        self.assertTrue(two.passed)
        self.assertTrue(three.passed)
        self.assertFalse(initial_failure.passed)
        self.assertFalse(missing_initial.complete)
        self.assertIsNone(missing_initial.initial_positive_support)
        self.assertFalse(missing_initial.passed)
        self.assertFalse(target_passed({"input-a": zero, "input-b": one}))
        self.assertTrue(target_passed({"input-a": zero, "input-b": two}))
        self.assertFalse(target_passed({"input-a": one_a, "input-b": one_b}))

    def test_seed_pass_requires_all_four_results_and_rejects_duplicate_seeds(self):
        target = Target("10", 2, 4, .75, "bh")
        initial_seed, verification_seed = 311, 504
        incomplete = seed_pass_result(
            (profile(initial_seed, raw=100), profile(verification_seed, raw=100),
             profile(verification_seed + 1, raw=100)),
            target, initial_seed=initial_seed, verification_seed=verification_seed)
        self.assertFalse(incomplete.complete)
        self.assertFalse(incomplete.passed)
        self.assertIsNone(incomplete.verification_positive_support[2])
        self.assertTrue(target_passed({"input-a": seed_pass_result(
            tuple(profile(seed, raw=100)
                  for seed in (initial_seed, verification_seed,
                               verification_seed + 1, verification_seed + 2)),
            target, initial_seed=initial_seed, verification_seed=verification_seed)}))
        with self.assertRaises(ValueError):
            seed_pass_result(
                (profile(initial_seed), profile(initial_seed, raw=100)), target,
                initial_seed=initial_seed, verification_seed=verification_seed)
        with self.assertRaises(ValueError):
            seed_pass_result((), target, initial_seed=True, verification_seed=verification_seed)
        with self.assertRaises(ValueError):
            seed_pass_result((), target, initial_seed=initial_seed,
                             verification_seed=2**53 - 2)
        with self.assertRaises(TypeError):
            target_passed({"input-a": object()})
