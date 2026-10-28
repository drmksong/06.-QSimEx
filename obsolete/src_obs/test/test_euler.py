from dataclasses import replace
from math import log
import unittest
from typing import cast

from src.euler_campaign.coverage import (
    BinCoverage,
    CoverageGrid,
    CoverageResult,
    PairedScore,
)
from src.euler_campaign.euler import (
    DensityExplorationUpdateRule,
    DensitySweepCursor,
    FeatureBound,
    GapSeekingNormalizedGradientUpdateRule,
    OrientationSweepCursor,
    ProbeEvidence,
    RepeatabilityResult,
    Sensitivity,
    UpdateProposal,
    assess_repeatability,
    build_probes,
    estimate_sensitivity,
    next_feature_block,
    next_density_feature_id,
    orientation_beta,
    propose_update,
    validate_size_sampling_bounds,
)
from src.euler_campaign.models import (
    BartonCategory,
    BoreholeSpec,
    CaseSpec,
    DomainSpec,
    FeatureBlock,
    JointCondition,
    JointSetSpec,
    Signature,
    TunnelSpec,
    identify_signature,
)


def _signature(
    *,
    density: float = 1.0,
    size_min: float = 0.5,
    size_max: float = 5.0,
    kappa: float = 20.0,
) -> Signature:
    condition = JointCondition(
        BartonCategory("jr", "Jr", "Good", 3.0, 4.0),
        BartonCategory("ja", "Ja", "Slight", 1.0, 2.0),
    )
    case = CaseSpec(
        "euler-test",
        DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0),
        (
            JointSetSpec(
                1, "set-1", "P32", density, 3.0, size_min, size_max,
                0.0, 0.0, kappa, condition,
            ),
        ),
        (
            BoreholeSpec(
                "bh-1", (0.0, 5.0, 5.0), (1.0, 0.0, 0.0), 10.0, 1.0,
                "face_comparison",
            ),
        ),
        TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 1.0),
    )
    return identify_signature(case)


def _coverage(
    signature_id: str,
    seed: int,
    observed: frozenset[int] = frozenset({0}),
    second_proximity: float = 0.2,
) -> CoverageResult:
    grid = CoverageGrid("grid-v1", (0.0, 1.0, 10.0))
    bins = (
        BinCoverage(0, 1.0 if 0 in observed else 0.0, 1.0),
        BinCoverage(1, 1.0 if 1 in observed else 0.0, second_proximity),
    )
    return CoverageResult(signature_id, seed, grid, bins, observed)


def _required_signature(signature: Signature | None) -> Signature:
    if signature is None:
        raise AssertionError("expected a valid probe candidate")
    return signature


def _score(
    parent: Signature,
    candidate: Signature | None,
    seed: int,
    delta_score: float,
    *,
    parent_count: int = 1,
    candidate_count: int = 1,
    new_occupancy_fraction: float = 0.0,
) -> PairedScore:
    if candidate is None:
        raise AssertionError("a paired score requires a probe candidate")
    return PairedScore(
        seed,
        parent.signature_id,
        candidate.signature_id,
        "grid-v1",
        frozenset({1}),
        delta_score,
        new_occupancy_fraction,
        delta_score,
        parent_count,
        candidate_count,
    )


class TestEulerUpdater(unittest.TestCase):
    def test_next_feature_block_follows_density_size_orientation_cycle(self) -> None:
        self.assertEqual(next_feature_block("density"), "size")
        self.assertEqual(next_feature_block("size"), "orientation")
        self.assertEqual(next_feature_block("orientation"), "density")
        with self.assertRaises(ValueError):
            next_feature_block(cast(FeatureBlock, "other"))

    def test_orientation_beta_uses_normalized_vectors_and_plane_symmetry(self) -> None:
        self.assertAlmostEqual(orientation_beta(
            (0.0, 0.0, 4.0), (3.0, 0.0, 0.0),
        ), 0.0)
        self.assertAlmostEqual(orientation_beta(
            (1.0, 0.0, 0.0), (1.0, 0.0, 0.0),
        ), 90.0)
        self.assertAlmostEqual(orientation_beta(
            (0.0, 0.0, -1.0), (1.0, 0.0, 0.0),
        ), 0.0)
        with self.assertRaises(ValueError):
            orientation_beta((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))

    def test_density_probes_use_log_ten_percent_steps_and_bounds(self) -> None:
        parent = _signature()
        probes = build_probes(
            parent,
            "density",
            (FeatureBound("joint_sets.1.density_value", 0.5, 2.0),),
        )

        self.assertEqual(len(probes), 1)
        probe = probes[0]
        self.assertIsNotNone(probe.minus)
        self.assertIsNotNone(probe.plus)
        self.assertAlmostEqual(probe.minus.case.joint_sets[0].density_value, 1.0 / 1.1)
        self.assertAlmostEqual(probe.plus.case.joint_sets[0].density_value, 1.1)
        self.assertAlmostEqual(
            probe.plus_coordinate - probe.minus_coordinate,
            2 * log(1.1),
        )

    def test_probe_at_bound_uses_one_sided_candidate_and_records_block(self) -> None:
        parent = _signature(density=0.5)
        probe, = build_probes(
            parent,
            "density",
            (FeatureBound("joint_sets.1.density_value", 0.5, 2.0),),
        )

        self.assertIsNone(probe.minus)
        self.assertIsNotNone(probe.plus)
        self.assertAlmostEqual(probe.minus_coordinate, log(0.5))
        self.assertIsNotNone(probe.blocked_reason)

    def test_size_probes_keep_the_other_size_coordinate_unchanged(self) -> None:
        parent = _signature()
        probes = build_probes(
            parent,
            "size",
            (
                FeatureBound("joint_sets.1.size_r_max", 0.5, 6.0),
                FeatureBound("joint_sets.1.size_r_min", 0.1, 1.0),
            ),
        )

        self.assertEqual(
            [probe.feature_id for probe in probes],
            ["joint_sets.1.size_r_max", "joint_sets.1.size_r_min"],
        )
        minimum_probe = probes[1]
        self.assertAlmostEqual(minimum_probe.plus.case.joint_sets[0].size_r_min, 0.55)
        self.assertEqual(minimum_probe.plus.case.joint_sets[0].size_r_max, 5.0)
        maximum_probe = probes[0]
        self.assertAlmostEqual(maximum_probe.plus.case.joint_sets[0].size_r_max, 5.5)
        self.assertEqual(maximum_probe.plus.case.joint_sets[0].size_r_min, 0.5)

    def test_orientation_probe_changes_mean_normal_but_preserves_kappa(self) -> None:
        parent = _signature()
        probe, = build_probes(
            parent,
            "orientation",
            (FeatureBound("joint_sets.1.orientation_beta@bh-1", 0.0, 90.0),),
        )

        self.assertIsNone(probe.minus)
        self.assertIsNotNone(probe.plus)
        updated_set = _required_signature(probe.plus).case.joint_sets[0]
        self.assertAlmostEqual(
            orientation_beta(updated_set.mean_normal, (1.0, 0.0, 0.0)),
            5.0,
        )
        self.assertEqual(updated_set.fisher_kappa, 20.0)

    def test_sensitivity_uses_paired_central_difference(self) -> None:
        parent = _signature()
        probe, = build_probes(
            parent,
            "density",
            (FeatureBound("joint_sets.1.density_value", 0.5, 2.0),),
        )
        parent_coverage = _coverage(parent.signature_id, 17)
        evidence = ProbeEvidence(
            probe,
            17,
            parent_coverage,
            _score(parent, _required_signature(probe.minus), 17, -0.1),
            _score(parent, _required_signature(probe.plus), 17, 0.3),
        )

        result = estimate_sensitivity(evidence)

        expected = 0.4 / (probe.plus_coordinate - probe.minus_coordinate)
        self.assertAlmostEqual(result.derivative, expected)
        self.assertIsNone(result.unavailable_reason)

    def test_sensitivity_uses_one_sided_difference_when_bound_blocks_probe(self) -> None:
        parent = _signature(density=0.5)
        probe, = build_probes(
            parent,
            "density",
            (FeatureBound("joint_sets.1.density_value", 0.5, 2.0),),
        )
        evidence = ProbeEvidence(
            probe,
            18,
            _coverage(parent.signature_id, 18),
            None,
            _score(parent, _required_signature(probe.plus), 18, 0.2),
        )

        result = estimate_sensitivity(evidence)

        self.assertGreater(result.derivative, 0.0)
        self.assertIsNone(result.unavailable_reason)

    def test_sensitivity_requires_paired_score_identity_and_seed(self) -> None:
        parent = _signature()
        probe, = build_probes(
            parent,
            "density",
            (FeatureBound("joint_sets.1.density_value", 0.5, 2.0),),
        )
        wrong_seed_score = _score(parent, _required_signature(probe.plus), 20, 0.3)

        with self.assertRaises(ValueError):
            estimate_sensitivity(ProbeEvidence(
                probe, 19, _coverage(parent.signature_id, 19),
                _score(parent, _required_signature(probe.minus), 19, 0.1),
                wrong_seed_score,
            ))

    def test_default_rule_normalizes_the_largest_positive_feature_step(self) -> None:
        parent = _signature()
        bounds = (FeatureBound("joint_sets.1.density_value", 0.5, 2.0),)
        sensitivity = Sensitivity(bounds[0].feature_id, "density", 3.0, None)

        proposal = propose_update(parent, "density", (sensitivity,), bounds)

        self.assertEqual(proposal.status, "candidate")
        self.assertAlmostEqual(
            log(proposal.candidate.case.joint_sets[0].density_value),
            log(1.0) + 0.05,
        )

    def test_default_size_rule_preserves_gradient_ratio_in_log_coordinates(self) -> None:
        parent = _signature()
        bounds = (
            FeatureBound("joint_sets.1.size_r_min", 0.1, 1.0),
            FeatureBound("joint_sets.1.size_r_max", 1.0, 10.0),
        )
        sensitivities = (
            Sensitivity(bounds[0].feature_id, "size", 4.0, None),
            Sensitivity(bounds[1].feature_id, "size", -2.0, None),
        )

        proposal = propose_update(parent, "size", sensitivities, bounds)

        joint_set = proposal.candidate.case.joint_sets[0]
        self.assertAlmostEqual(log(joint_set.size_r_min / 0.5), 0.05)
        self.assertAlmostEqual(log(joint_set.size_r_max / 5.0), -0.025)
        self.assertLess(joint_set.size_r_min, joint_set.size_r_max)

    def test_default_orientation_rule_caps_beta_step_at_five_degrees(self) -> None:
        parent = _signature()
        bound = FeatureBound("joint_sets.1.orientation_beta@bh-1", 0.0, 90.0)
        sensitivity = Sensitivity(bound.feature_id, "orientation", 1.0, None)

        proposal = propose_update(parent, "orientation", (sensitivity,), (bound,))

        candidate_set = proposal.candidate.case.joint_sets[0]
        self.assertAlmostEqual(
            orientation_beta(candidate_set.mean_normal, (1.0, 0.0, 0.0)),
            5.0,
        )
        self.assertEqual(candidate_set.fisher_kappa, 20.0)

    def test_default_rule_reports_a_bound_limited_feature_without_candidate(self) -> None:
        parent = _signature(density=2.0)
        bound = FeatureBound("joint_sets.1.density_value", 0.5, 2.0)
        sensitivity = Sensitivity(bound.feature_id, "density", 1.0, None)

        proposal = propose_update(parent, "density", (sensitivity,), (bound,))

        self.assertEqual(proposal.status, "bound_limited")
        self.assertIsNone(proposal.candidate)
        self.assertEqual(proposal.bound_limited_features, (bound.feature_id,))

    def test_outward_bound_sensitivity_does_not_reduce_feasible_density_step(self) -> None:
        parent = _signature()
        second_set = replace(
            parent.case.joint_sets[0],
            set_id=2,
            name="set-2",
            density_value=2.0,
        )
        parent = identify_signature(replace(
            parent.case,
            joint_sets=(*parent.case.joint_sets, second_set),
        ))
        first_bound = FeatureBound("joint_sets.1.density_value", 0.5, 2.0)
        second_bound = FeatureBound("joint_sets.2.density_value", 0.5, 2.0)
        sensitivities = (
            Sensitivity(first_bound.feature_id, "density", 1.0, None),
            Sensitivity(second_bound.feature_id, "density", 100.0, None),
        )

        proposal = propose_update(
            parent, "density", sensitivities, (first_bound, second_bound),
        )

        self.assertEqual(proposal.status, "candidate")
        if proposal.candidate is None:
            self.fail("feasible density sensitivity must produce a candidate")
        updated_sets = proposal.candidate.case.joint_sets
        self.assertAlmostEqual(log(updated_sets[0].density_value), 0.05)
        self.assertEqual(updated_sets[1].density_value, 2.0)
        self.assertEqual(proposal.bound_limited_features, (second_bound.feature_id,))

    def test_all_outward_bound_sensitivities_report_bound_limited(self) -> None:
        parent = _signature(density=2.0)
        bound = FeatureBound("joint_sets.1.density_value", 0.5, 2.0)
        sensitivity = Sensitivity(bound.feature_id, "density", 1.0, None)

        proposal = propose_update(parent, "density", (sensitivity,), (bound,))

        self.assertEqual(proposal.status, "bound_limited")
        self.assertIsNone(proposal.candidate)
        self.assertEqual(proposal.bound_limited_features, (bound.feature_id,))

    def test_default_rule_accepts_parent_exactly_at_log_coordinate_lower_bound(self) -> None:
        parent = _signature(density=2000.0)
        bound = FeatureBound("joint_sets.1.density_value", 2000.0, 10000.0)
        sensitivity = Sensitivity(bound.feature_id, "density", 1.0, None)

        proposal = propose_update(parent, "density", (sensitivity,), (bound,))

        self.assertEqual(proposal.status, "candidate")
        self.assertIsNotNone(proposal.candidate)
        self.assertGreater(
            proposal.candidate.case.joint_sets[0].density_value,
            bound.lower,
        )

    def test_default_rule_clamps_log_candidate_to_exact_physical_bound(self) -> None:
        parent = _signature(density=1000.1)
        bound = FeatureBound("joint_sets.1.density_value", 1000.0, 10000.0)
        sensitivity = Sensitivity(bound.feature_id, "density", -1.0, None)

        proposal = propose_update(parent, "density", (sensitivity,), (bound,))

        self.assertEqual(proposal.status, "candidate")
        self.assertIsNotNone(proposal.candidate)
        self.assertEqual(
            proposal.candidate.case.joint_sets[0].density_value,
            bound.lower,
        )

    def test_default_orientation_rule_requires_one_axis_per_joint_set(self) -> None:
        parent = _signature()
        second_borehole = BoreholeSpec(
            "bh-2", (0.0, 4.0, 5.0), (0.0, 1.0, 0.0), 8.0, 1.0,
            "independent",
        )
        parent = identify_signature(replace(
            parent.case,
            boreholes=parent.case.boreholes + (second_borehole,),
        ))
        bounds = (
            FeatureBound("joint_sets.1.orientation_beta@bh-1", 0.0, 90.0),
            FeatureBound("joint_sets.1.orientation_beta@bh-2", 0.0, 90.0),
        )
        sensitivities = tuple(
            Sensitivity(bound.feature_id, "orientation", derivative, None)
            for bound, derivative in zip(bounds, (1.0, 0.5))
        )

        proposal = propose_update(parent, "orientation", sensitivities, bounds)

        self.assertEqual(proposal.status, "decision_required")
        self.assertIsNone(proposal.candidate)

    def test_gap_seeking_update_rule_has_distinct_stable_id(self) -> None:
        self.assertEqual(
            GapSeekingNormalizedGradientUpdateRule().rule_id,
            "normalized-gradient-gap-v2",
        )

    def test_density_exploration_rule_scales_log_step(self) -> None:
        parent = _signature(density=1.0)
        bound = FeatureBound("joint_sets.1.density_value", 0.5, 2.0)
        sensitivity = Sensitivity(bound.feature_id, "density", 1.0, None)

        proposal = propose_update(
            parent,
            "density",
            (sensitivity,),
            (bound,),
            DensityExplorationUpdateRule(),
            step_scale=2.0,
        )

        self.assertEqual(proposal.status, "candidate")
        self.assertAlmostEqual(
            log(proposal.candidate.case.joint_sets[0].density_value),
            log(1.0) + 0.20,
        )

    def test_density_sweep_latches_direction_and_advances_set_in_order(self) -> None:
        parent = _signature()
        second_joint_set = replace(
            parent.case.joint_sets[0],
            set_id=2,
            name="set-2",
            density_value=1.5,
        )
        parent = identify_signature(replace(
            parent.case,
            joint_sets=(*parent.case.joint_sets, second_joint_set),
        ))
        first_id = "joint_sets.1.density_value"
        second_id = "joint_sets.2.density_value"
        bounds = (
            FeatureBound(first_id, 0.5, 2.0),
            FeatureBound(second_id, 0.5, 2.0),
        )
        rule = DensityExplorationUpdateRule()

        first = propose_update(
            parent,
            "density",
            (Sensitivity(first_id, "density", -1.0, None),),
            bounds,
            rule,
        )

        self.assertEqual(first.status, "candidate")
        self.assertEqual(
            first.density_cursor_updates,
            (DensitySweepCursor(first_id, -1, False),),
        )
        if first.candidate is None:
            self.fail("density sweep must propose a candidate")
        self.assertLess(
            first.candidate.case.joint_sets[0].density_value,
            parent.case.joint_sets[0].density_value,
        )
        self.assertEqual(
            first.candidate.case.joint_sets[1].density_value,
            parent.case.joint_sets[1].density_value,
        )

        second = propose_update(
            first.candidate,
            "density",
            (Sensitivity(first_id, "density", 1.0, None),),
            bounds,
            rule,
            step_scale=10.0,
            density_cursors=first.density_cursor_updates,
        )

        self.assertEqual(second.status, "candidate")
        self.assertEqual(
            second.density_cursor_updates,
            (DensitySweepCursor(first_id, -1, True),),
        )
        self.assertEqual(
            next_density_feature_id(bounds, second.density_cursor_updates),
            second_id,
        )
        if second.candidate is None:
            self.fail("density sweep must reach the selected bound")
        self.assertAlmostEqual(
            second.candidate.case.joint_sets[0].density_value, 0.5,
        )

    def test_density_sweep_defaults_to_upper_direction_without_sensitivity(self) -> None:
        parent = _signature()
        feature_id = "joint_sets.1.density_value"
        proposal = propose_update(
            parent,
            "density",
            (Sensitivity(feature_id, "density", None, "probe unavailable"),),
            (FeatureBound(feature_id, 0.5, 2.0),),
            DensityExplorationUpdateRule(),
        )

        self.assertEqual(proposal.density_cursor_updates[0].direction, 1)
        if proposal.candidate is None:
            self.fail("density sweep must proceed without sensitivity evidence")
        self.assertGreater(
            proposal.candidate.case.joint_sets[0].density_value,
            parent.case.joint_sets[0].density_value,
        )

    def test_density_exploration_samples_reproducible_bounded_size_pairs(self) -> None:
        parent = _signature()
        bounds = (
            FeatureBound("joint_sets.1.size_r_min", 0.1, 1.0),
            FeatureBound("joint_sets.1.size_r_max", 1.0, 100.0),
        )

        first = propose_update(
            parent, "size", (), bounds, DensityExplorationUpdateRule(),
            size_seed=53,
        )
        second = propose_update(
            parent, "size", (), bounds, DensityExplorationUpdateRule(),
            size_seed=53,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.status, "candidate")
        self.assertEqual(
            first.randomized_feature_ids,
            ("joint_sets.1.size_r_max", "joint_sets.1.size_r_min"),
        )
        if first.candidate is None:
            self.fail("seeded size sampling must produce a candidate")
        sampled_set = first.candidate.case.joint_sets[0]
        self.assertGreater(sampled_set.size_r_min, 0.0)
        self.assertLessEqual(sampled_set.size_r_min, 1.0)
        self.assertGreaterEqual(sampled_set.size_r_max, 1.0)
        self.assertLessEqual(sampled_set.size_r_max, 100.0)
        self.assertLess(sampled_set.size_r_min, sampled_set.size_r_max)

    def test_size_sampling_supports_radius_up_to_100m(self) -> None:
        parent = _signature()
        bounds = (
            FeatureBound("joint_sets.1.size_r_min", 60.0, 80.0),
            FeatureBound("joint_sets.1.size_r_max", 80.0, 100.0),
        )
        proposal = propose_update(
            parent, "size", (), bounds, DensityExplorationUpdateRule(),
            size_seed=61,
        )

        self.assertEqual(proposal.status, "candidate")
        if proposal.candidate is None:
            self.fail("size sampling must support radii above 50m")
        sampled_set = proposal.candidate.case.joint_sets[0]
        self.assertGreaterEqual(sampled_set.size_r_min, 60.0)
        self.assertLessEqual(sampled_set.size_r_min, 80.0)
        self.assertGreaterEqual(sampled_set.size_r_max, 80.0)
        self.assertLessEqual(sampled_set.size_r_max, 100.0)
        self.assertLess(sampled_set.size_r_min, sampled_set.size_r_max)

    def test_size_sampling_covers_each_joint_set_and_rejects_impossible_bounds(self) -> None:
        parent = _signature()
        second_joint_set = replace(
            parent.case.joint_sets[0],
            set_id=2,
            name="set-2",
            size_r_min=0.75,
            size_r_max=6.0,
        )
        parent = identify_signature(replace(
            parent.case,
            joint_sets=(*parent.case.joint_sets, second_joint_set),
        ))
        bounds = (
            FeatureBound("joint_sets.1.size_r_min", 0.1, 1.0),
            FeatureBound("joint_sets.1.size_r_max", 1.0, 10.0),
            FeatureBound("joint_sets.2.size_r_min", 0.1, 1.0),
            FeatureBound("joint_sets.2.size_r_max", 1.0, 10.0),
        )

        validate_size_sampling_bounds(parent, bounds)
        proposal = propose_update(
            parent, "size", (), bounds, DensityExplorationUpdateRule(),
            size_seed=59,
        )

        self.assertEqual(len(proposal.randomized_feature_ids), 4)
        if proposal.candidate is None:
            self.fail("all joint sets must receive sampled size pairs")
        for joint_set in proposal.candidate.case.joint_sets:
            self.assertLess(joint_set.size_r_min, joint_set.size_r_max)

        impossible_bounds = (
            FeatureBound("joint_sets.1.size_r_min", 20.0, 30.0),
            FeatureBound("joint_sets.1.size_r_max", 10.0, 15.0),
            FeatureBound("joint_sets.2.size_r_min", 0.1, 1.0),
            FeatureBound("joint_sets.2.size_r_max", 1.0, 10.0),
        )
        with self.assertRaisesRegex(ValueError, "cannot produce"):
            validate_size_sampling_bounds(parent, impossible_bounds)

    def test_orientation_sweep_starts_with_sensitivity_direction(self) -> None:
        rule = DensityExplorationUpdateRule()
        parent = _signature()
        joint_set = replace(
            parent.case.joint_sets[0], mean_dip=30.0, mean_dip_dir=90.0,
        )
        parent = identify_signature(replace(
            parent.case, joint_sets=(joint_set,),
        ))
        bound = FeatureBound(
            "joint_sets.1.orientation_beta@bh-1", 0.0, 90.0,
        )
        sensitivity = Sensitivity(bound.feature_id, "orientation", -1.0, None)

        proposal = propose_update(
            parent, "orientation", (sensitivity,), (bound,), rule,
        )

        self.assertEqual(proposal.status, "candidate")
        if proposal.candidate is None:
            self.fail("orientation sweep must propose an in-range candidate")
        candidate_set = proposal.candidate.case.joint_sets[0]
        self.assertAlmostEqual(
            orientation_beta(candidate_set.mean_normal, (1.0, 0.0, 0.0)),
            20.0,
        )
        self.assertEqual(len(proposal.orientation_cursor_updates), 1)
        cursor = proposal.orientation_cursor_updates[0]
        self.assertEqual(cursor.feature_id, bound.feature_id)
        self.assertAlmostEqual(cursor.beta, 20.0)
        self.assertEqual(cursor.direction, -1)

    def test_orientation_sweep_defaults_to_positive_and_advances_after_rejection(self) -> None:
        rule = DensityExplorationUpdateRule()
        parent = _signature()
        bound = FeatureBound(
            "joint_sets.1.orientation_beta@bh-1", 0.0, 90.0,
        )
        unavailable = Sensitivity(
            bound.feature_id, "orientation", None, "probe unavailable",
        )

        first = propose_update(
            parent, "orientation", (unavailable,), (bound,), rule,
        )
        second = propose_update(
            parent,
            "orientation",
            (unavailable,),
            (bound,),
            rule,
            orientation_cursors=first.orientation_cursor_updates,
        )

        self.assertEqual(first.orientation_cursor_updates[0].beta, 10.0)
        self.assertEqual(second.orientation_cursor_updates[0].beta, 20.0)
        if second.candidate is None:
            self.fail("rejected orientation attempt must advance to a new point")
        candidate_set = second.candidate.case.joint_sets[0]
        self.assertAlmostEqual(
            orientation_beta(candidate_set.mean_normal, (1.0, 0.0, 0.0)),
            20.0,
        )

    def test_orientation_sweep_reverses_at_upper_bound(self) -> None:
        rule = DensityExplorationUpdateRule()
        parent = _signature()
        bound = FeatureBound(
            "joint_sets.1.orientation_beta@bh-1", 0.0, 90.0,
        )
        sensitivity = Sensitivity(bound.feature_id, "orientation", 1.0, None)
        cursor = OrientationSweepCursor(bound.feature_id, 90.0, 1)

        proposal = propose_update(
            parent,
            "orientation",
            (sensitivity,),
            (bound,),
            rule,
            orientation_cursors=(cursor,),
        )

        self.assertEqual(proposal.orientation_cursor_updates[0].beta, 80.0)
        self.assertEqual(proposal.orientation_cursor_updates[0].direction, -1)
        if proposal.candidate is None:
            self.fail("orientation sweep must reverse into the bounded range")
        candidate_set = proposal.candidate.case.joint_sets[0]
        self.assertAlmostEqual(
            orientation_beta(candidate_set.mean_normal, (1.0, 0.0, 0.0)),
            80.0,
        )

    def test_gap_seeking_update_rule_uses_ten_percent_and_ten_degree_steps(self) -> None:
        rule = GapSeekingNormalizedGradientUpdateRule()
        density_parent = _signature(density=1.0)
        density_bound = FeatureBound("joint_sets.1.density_value", 0.5, 2.0)
        density_proposal = propose_update(
            density_parent,
            "density",
            (Sensitivity(density_bound.feature_id, "density", 1.0, None),),
            (density_bound,),
            rule,
        )
        self.assertIsNotNone(density_proposal.candidate)
        self.assertAlmostEqual(
            log(density_proposal.candidate.case.joint_sets[0].density_value)
            - log(density_parent.case.joint_sets[0].density_value),
            0.10,
        )

        orientation_parent = _signature()
        orientation_bound = FeatureBound(
            "joint_sets.1.orientation_beta@bh-1", 0.0, 90.0,
        )
        orientation_proposal = propose_update(
            orientation_parent,
            "orientation",
            (Sensitivity(orientation_bound.feature_id, "orientation", 1.0, None),),
            (orientation_bound,),
            rule,
        )
        self.assertIsNotNone(orientation_proposal.candidate)
        updated_joint_set = orientation_proposal.candidate.case.joint_sets[0]
        borehole = orientation_parent.case.boreholes[0]
        self.assertAlmostEqual(
            orientation_beta(updated_joint_set.mean_normal, borehole.direction),
            10.0,
        )

    def test_injected_update_rule_is_checked_against_block_and_bounds(self) -> None:
        parent = _signature()
        candidate = _signature(density=1.05)
        bound = FeatureBound("joint_sets.1.density_value", 0.5, 2.0)
        sensitivity = Sensitivity(bound.feature_id, "density", 1.0, None)

        class Rule:
            def propose(self, rule_parent, block, sensitivities, bounds):
                return UpdateProposal(
                    rule_parent, candidate, block, sensitivities, (),
                    "candidate", "positive density sensitivity",
                )

        result = propose_update(parent, "density", (sensitivity,), (bound,), Rule())
        self.assertIs(result.candidate, candidate)

        forbidden_candidate = identify_signature(replace(
            candidate.case,
            joint_sets=(
                replace(candidate.case.joint_sets[0], fisher_kappa=21.0),
            ),
        ))

        class UnsafeRule:
            def propose(self, rule_parent, block, sensitivities, bounds):
                return UpdateProposal(
                    rule_parent, forbidden_candidate, block, sensitivities, (),
                    "candidate", "invalid cross-feature update",
                )

        with self.assertRaisesRegex(ValueError, "immutable/out-of-block"):
            propose_update(parent, "density", (sensitivity,), (bound,), UnsafeRule())

    def test_repeatability_requires_two_of_three_paired_seed_successes(self) -> None:
        parent = _signature()
        candidate = _signature(density=1.05)
        proposal = UpdateProposal(
            parent,
            candidate,
            "density",
            (Sensitivity("joint_sets.1.density_value", "density", 1.0, None),),
            (),
            "candidate",
            "positive density sensitivity",
        )
        scores = (
            _score(parent, candidate, 101, 0.1, candidate_count=2),
            _score(parent, candidate, 102, 0.2, candidate_count=1),
            _score(parent, candidate, 103, -0.1, candidate_count=2),
        )

        result = assess_repeatability(proposal, scores)

        self.assertIsInstance(result, RepeatabilityResult)
        self.assertTrue(result.accepted)
        self.assertIn("2/3", result.reason)
        with self.assertRaises(ValueError):
            assess_repeatability(proposal, (scores[0], scores[1], scores[1]))

    def test_gap_seeking_repeatability_requires_new_bin_in_two_of_three(self) -> None:
        parent = _signature()
        candidate = _signature(density=1.05)
        proposal = UpdateProposal(
            parent,
            candidate,
            "density",
            (Sensitivity("joint_sets.1.density_value", "density", 1.0, None),),
            (),
            "candidate",
            "positive density sensitivity",
        )
        scores = (
            _score(
                parent, candidate, 101, 0.1, candidate_count=2,
                new_occupancy_fraction=0.25,
            ),
            _score(
                parent, candidate, 102, 0.2, candidate_count=2,
                new_occupancy_fraction=0.0,
            ),
            _score(
                parent, candidate, 103, 0.1, candidate_count=2,
                new_occupancy_fraction=0.5,
            ),
        )

        result = assess_repeatability(proposal, scores, require_new_bin=True)

        self.assertTrue(result.accepted)
        self.assertIn("2/3", result.reason)
        self.assertIn("new-bin", result.reason)
        proximity_only_scores = (
            _score(parent, candidate, 201, 0.1, candidate_count=2),
            _score(parent, candidate, 202, 0.1, candidate_count=2),
            _score(parent, candidate, 203, 0.1, candidate_count=2),
        )
        proximity_only_result = assess_repeatability(
            proposal,
            proximity_only_scores,
            require_new_bin=True,
        )
        self.assertFalse(proximity_only_result.accepted)
        self.assertIn("0/3", proximity_only_result.reason)


if __name__ == "__main__":
    unittest.main()
