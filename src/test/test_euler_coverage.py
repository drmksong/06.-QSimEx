import unittest

from src.euler_campaign.coverage import (
    BinCoverage, CoverageGrid, CoverageResult, audit_profile, audit_simulation,
    parent_gaps, score_pair, validate_grid,
)
from src.euler_campaign.models import BoreholeSpec
from src.euler_campaign.profiles import (
    BoreholeProfile, ProfileInterval, SimulationResult, TunnelProfile,
)
from src.euler_campaign.qprime import QPrimeProvenance, QPrimeResult


class TestEulerCoverage(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = CoverageGrid("qprime-v1", (0.0, 1.0, 10.0, 100.0))
        self.provenance = QPrimeProvenance(
            "no_intersection_convention", None, None, None,
            "qsimex_no_intersection_rqd100_jr4_ja0.75",
        )

    def _interval(self, start: float, end: float, value: float) -> ProfileInterval:
        return ProfileInterval(
            start, end,
            QPrimeResult(100.0, 100.0, 4.0, 4.0, 0.75, value, self.provenance),
        )

    def _coverage(
        self,
        signature_id: str,
        observed: frozenset[int],
        proximity: tuple[float, ...],
        seed: int = 4,
    ) -> CoverageResult:
        bins = tuple(
            BinCoverage(index, 1.0 if index in observed else 0.0, value)
            for index, value in enumerate(proximity)
        )
        return CoverageResult(signature_id, seed, self.grid, bins, observed)

    def test_grid_requires_zero_then_strictly_increasing_positive_edges(self) -> None:
        validate_grid(self.grid)
        invalid_grids = (
            CoverageGrid("", (0.0, 1.0)),
            CoverageGrid("short", (0.0,)),
            CoverageGrid("no-zero", (0.1, 1.0)),
            CoverageGrid("duplicate", (0.0, 1.0, 1.0)),
            CoverageGrid("non-finite", (0.0, float("inf"))),
        )
        for grid in invalid_grids:
            with self.subTest(grid=grid):
                with self.assertRaises(ValueError):
                    validate_grid(grid)

    def test_profile_audit_uses_positive_support_and_upper_closed_bins(self) -> None:
        bins = audit_profile((
            self._interval(0.0, 2.0, 1.0),
            self._interval(2.0, 5.0, 10.0),
            self._interval(5.0, 6.0, 100.0),
        ), self.grid)

        self.assertEqual([item.observed_length for item in bins], [2.0, 3.0, 1.0])
        self.assertEqual([item.bin_index for item in bins], [0, 1, 2])

    def test_proximity_uses_log_distance_and_actual_length_weights(self) -> None:
        bins = audit_profile((
            self._interval(0.0, 1.0, 0.1),
            self._interval(1.0, 4.0, 100.0),
        ), self.grid)

        first_bin_far_weight = 10.0 ** (-2.0 / 9.0)
        second_bin_far_weight = 10.0 ** (-1.0 / 9.0)
        self.assertAlmostEqual(
            bins[0].proximity,
            (1.0 + 3.0 * first_bin_far_weight) / 4.0,
        )
        self.assertAlmostEqual(
            bins[1].proximity,
            second_bin_far_weight,
        )
        self.assertAlmostEqual(
            bins[2].proximity,
            (first_bin_far_weight + 3.0) / 4.0,
        )

    def test_profile_audit_rejects_empty_invalid_or_overlapping_support(self) -> None:
        with self.assertRaises(ValueError):
            audit_profile((), self.grid)
        with self.assertRaises(ValueError):
            audit_profile((self._interval(0.0, 0.0, 1.0),), self.grid)
        with self.assertRaises(ValueError):
            audit_profile((
                self._interval(0.0, 2.0, 1.0),
                self._interval(1.0, 3.0, 2.0),
            ), self.grid)

    def test_simulation_audit_combines_profile_support_without_chainage_collision(self) -> None:
        borehole_spec = BoreholeSpec(
            "bh", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 2.0, 1.0, "independent",
        )
        boreholes = (
            BoreholeProfile(
                borehole_spec, None, (self._interval(0.0, 2.0, 0.5),), 0.0,
            ),
            BoreholeProfile(
                borehole_spec, None, (self._interval(0.0, 2.0, 5.0),), 0.0,
            ),
        )
        tunnel = TunnelProfile(
            (), (self._interval(0.0, 4.0, 50.0),), "tunnel_end", None,
        )
        result = SimulationResult("signature", "domain", 7, boreholes, tunnel)

        coverage = audit_simulation(result, self.grid)

        self.assertEqual(coverage.signature_id, "signature")
        self.assertEqual(coverage.seed, 7)
        self.assertEqual([item.observed_length for item in coverage.bins], [2.0, 2.0, 4.0])
        self.assertEqual(coverage.observed_bins, frozenset({0, 1, 2}))

    def test_parent_gaps_are_seed_specific_and_score_is_fifty_fifty(self) -> None:
        parent = self._coverage("parent", frozenset({0}), (0.1, 0.4, 0.7))
        candidate = self._coverage("candidate", frozenset({0, 1}), (0.1, 0.8, 0.5))
        gaps = parent_gaps(parent)

        score = score_pair(parent, candidate, gaps)

        self.assertEqual(gaps, frozenset({1, 2}))
        self.assertAlmostEqual(score.proximity_delta, 0.1)
        self.assertEqual(score.new_occupancy_fraction, 0.5)
        self.assertAlmostEqual(score.delta_score, 0.3)
        self.assertEqual(score.parent_gap_bins, gaps)
        self.assertEqual(score.parent_observed_count, 1)
        self.assertEqual(score.candidate_observed_count, 2)

    def test_empty_parent_gap_has_zero_score(self) -> None:
        parent = self._coverage("parent", frozenset({0, 1, 2}), (1.0, 1.0, 1.0))
        candidate = self._coverage("candidate", frozenset({0, 1, 2}), (1.0, 1.0, 1.0))

        score = score_pair(parent, candidate, parent_gaps(parent))

        self.assertEqual(score.proximity_delta, 0.0)
        self.assertEqual(score.new_occupancy_fraction, 0.0)
        self.assertEqual(score.delta_score, 0.0)

    def test_pair_scoring_rejects_different_seed_grid_or_parent_gaps(self) -> None:
        parent = self._coverage("parent", frozenset({0}), (0.1, 0.4, 0.7))
        candidate = self._coverage("candidate", frozenset({0, 1}), (0.1, 0.8, 0.5))

        with self.assertRaises(ValueError):
            score_pair(parent, self._coverage(
                "candidate", frozenset({0, 1}), (0.1, 0.8, 0.5), seed=5,
            ), parent_gaps(parent))
        with self.assertRaises(ValueError):
            score_pair(parent, CoverageResult(
                candidate.signature_id, candidate.seed,
                CoverageGrid("different-id", self.grid.edges),
                candidate.bins, candidate.observed_bins,
            ), parent_gaps(parent))
        with self.assertRaises(ValueError):
            score_pair(parent, candidate, frozenset({2}))


if __name__ == "__main__":
    unittest.main()
