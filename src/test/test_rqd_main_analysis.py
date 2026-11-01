import unittest

from src.rqd_exploration.analysis import BIN_EDGES
from src.rqd_exploration.main_analysis import (
    BHPoint, SeedProfile, Target, compare_groups, paired_progress,
    progress_decision, stability_history, target_complete,
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
        with self.assertRaises(ValueError):
            paired_progress(profile(43), profile(43), target)

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

    def test_group_normalizes_each_seed_before_equal_weight_average(self):
        target = Target("1", 2, .5, 20, "bh")
        a = tuple(SeedProfile(seed, (BHPoint(0, 100, 10, 10), BHPoint(100, 200, 100, 90)))
                  for seed in (44, 45))
        a += (SeedProfile(46, (BHPoint(0, 100, 10, 90), BHPoint(100, 200, 100, 10))),)
        b = tuple(SeedProfile(seed, (BHPoint(0, 100, 10, 11), BHPoint(100, 200, 100, 19)))
                  for seed in (47, 48, 49))
        comparison = compare_groups(a, b, target)
        self.assertAlmostEqual(comparison.support_fraction_a, 1.1 / 3)
        self.assertAlmostEqual(comparison.support_fraction_b, .11 / .3)
        self.assertAlmostEqual(comparison.maximum_cdf_difference, 0)
        self.assertTrue(comparison.passed)

    def test_stability_both_thresholds_positive_support_and_equal_seed_weights(self):
        target = Target("1", 2, .5, 20, "bh")
        def group(start, fraction):
            return tuple(SeedProfile(seed, (
                BHPoint(0, 100, 10, fraction * 100),
                BHPoint(100, 200, 100, (1 - fraction) * 100),
            )) for seed in range(start, start + 3))
        a, b = group(44, .5), group(47, .6)
        comparison = compare_groups(a, b, target)
        self.assertTrue(comparison.passed)
        self.assertFalse(compare_groups(a, group(47, .600001), target).passed)
        self.assertFalse(compare_groups(group(44, 0), group(47, 0), target).passed)
        history = stability_history(a + b + group(50, .5), target)
        self.assertTrue(history.stable)
        self.assertEqual(history.consecutive_passes, 2)
        self.assertFalse(stability_history(
            a + group(47, .9) + group(50, .5), target).stable)
        self.assertFalse(target_complete({"a": history, "b": history}))
        self.assertTrue(target_complete({"a": history, "b": history, "c": history}))
