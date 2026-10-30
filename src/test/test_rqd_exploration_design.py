from dataclasses import replace
from math import exp, floor, log
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from scipy.stats import qmc

from src.rqd_exploration.adapter import build_generation_case
from src.rqd_exploration.config import load_config
from src.rqd_exploration.design import generate_lhs_design


class TestExecutableJnMapping(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
        self.config = load_config(path)

    def test_configs_use_fixed_jn_to_set_count_mapping(self) -> None:
        self.assertEqual(
            [(design.fixed_jn, len(design.joint_sets)) for design in self.config.designs],
            [(2.0, 1), (4.0, 2)],
        )


class TestPilotLHS(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
        self.config = load_config(path)
        self.design = self.config.designs[0]

    def test_pilot_count_reproducibility_and_exact_lhs_configuration(self) -> None:
        designs = tuple(generate_lhs_design(d) for d in self.config.designs)
        self.assertEqual([len(d.samples) for d in designs], [5, 5])
        self.assertEqual(sum(len(d.samples) for d in designs), 10)
        for result in designs:
            self.assertEqual(result, generate_lhs_design(result.design))
            self.assertEqual([s.sample_index for s in result.samples], list(range(5)))
            expected = qmc.LatinHypercube(
                d=len(result.axes), scramble=True, strength=1, optimization=None,
                rng=np.random.default_rng(result.design.design_seed),
            ).random(5)
            np.testing.assert_array_equal(
                [s.unit_coordinates for s in result.samples], expected,
            )
            for column in range(len(result.axes)):
                self.assertEqual(
                    sorted(floor(s.unit_coordinates[column] * 5) for s in result.samples),
                    list(range(5)),
                )
            self.assertEqual(result.numpy_version, np.__version__)
            self.assertTrue(result.scipy_version)
            self.assertIn("PCG64", result.rng_scheme)
            self.assertEqual(result.radius_transform, "ordered_log_pair")

    def test_transforms_raw_coordinates_and_preserves_every_sample(self) -> None:
        result = generate_lhs_design(self.design)
        self.assertEqual(
            [a.parameter for a in result.axes],
            ["p32_m2_per_m3", "log_radius_a_m", "log_radius_b_m",
             "mean_dip_deg", "mean_dip_dir_deg"],
        )
        for sample in result.samples:
            u = sample.unit_coordinates
            joint = sample.joint_sets[0]
            self.assertAlmostEqual(joint.p32_m2_per_m3, exp(log(0.01) + u[0] * log(10000)))
            radii = sorted(exp(log(0.05) + x * log(3000)) for x in u[1:3])
            self.assertAlmostEqual(joint.size_r_min_m, radii[0])
            self.assertAlmostEqual(joint.size_r_max_m, radii[1])
            self.assertLess(joint.size_r_min_m, joint.size_r_max_m)
            self.assertAlmostEqual(joint.mean_dip_deg, u[3] * 90)
            self.assertAlmostEqual(joint.mean_dip_dir_deg, u[4] * 360)
            self.assertLess(joint.mean_dip_dir_deg, 360)
            case = build_generation_case(
                self.config.geometry, self.config.measurements, self.design.fixed_jn,
                sample.joint_sets, case_id=f"sample-{sample.sample_index}",
            )
            self.assertEqual(case.joint_sets[0].density_value, joint.p32_m2_per_m3)

    def test_shape_streams_are_independent_of_lhs_and_each_other(self) -> None:
        result = generate_lhs_design(self.design)
        expected_alpha = np.random.default_rng(
            np.random.SeedSequence(39, spawn_key=(1,)),
        ).uniform(2.5, 4, size=5)
        expected_kappa = np.random.default_rng(
            np.random.SeedSequence(39, spawn_key=(2,)),
        ).uniform(0, 50, size=5)
        self.assertEqual([s.joint_sets[0].size_alpha for s in result.samples],
                         list(expected_alpha))
        self.assertEqual([s.joint_sets[0].fisher_kappa for s in result.samples],
                         list(expected_kappa))
        changed = generate_lhs_design(replace(
            self.design,
            size_alpha=replace(
                self.design.size_alpha,
                bounds=replace(self.design.size_alpha.bounds, lower=2.75, upper=3.5),
            ),
        ))
        self.assertEqual([s.unit_coordinates for s in result.samples],
                         [s.unit_coordinates for s in changed.samples])
        self.assertEqual([s.joint_sets[0].fisher_kappa for s in result.samples],
                         [s.joint_sets[0].fisher_kappa for s in changed.samples])
        self.assertNotEqual([s.joint_sets[0].size_alpha for s in result.samples],
                            [s.joint_sets[0].size_alpha for s in changed.samples])

    def test_multiple_sets_keep_order_and_share_only_shape_values(self) -> None:
        extra = replace(self.design.joint_sets[0], joint_set_id="second")
        design = replace(
            self.design, fixed_jn=4, joint_sets=(*self.design.joint_sets, extra),
        )
        result = generate_lhs_design(design)
        self.assertEqual(len(result.axes), 10)
        self.assertEqual([a.joint_set_id for a in result.axes],
                         ["set-1"] * 5 + ["second"] * 5)
        for column in range(10):
            self.assertEqual(
                sorted(floor(s.unit_coordinates[column] * 5) for s in result.samples),
                list(range(5)),
            )
        for sample in result.samples:
            first, second = sample.joint_sets
            self.assertEqual((first.size_alpha, first.fisher_kappa),
                             (second.size_alpha, second.fisher_kappa))
            self.assertNotEqual(first.mean_dip_deg, second.mean_dip_deg)
            self.assertNotEqual(first.p32_m2_per_m3, second.p32_m2_per_m3)
        base = generate_lhs_design(self.design)
        self.assertEqual([s.joint_sets[0].size_alpha for s in base.samples],
                         [s.joint_sets[0].size_alpha for s in result.samples])

    def test_only_design_inputs_drive_samples_not_realization_or_goal_metadata(self) -> None:
        original = generate_lhs_design(self.design)
        same = generate_lhs_design(replace(
            self.design, realization_seed=44, design_id="renamed", block_id="renamed",
        ))
        changed = generate_lhs_design(replace(self.design, design_seed=40))
        self.assertEqual(original.samples, same.samples)
        self.assertNotEqual(original.samples, changed.samples)
        smaller = generate_lhs_design(replace(self.design, sample_count=3))
        self.assertEqual(len(smaller.samples), 3)
        for column in range(5):
            self.assertEqual(
                sorted(floor(s.unit_coordinates[column] * 3) for s in smaller.samples),
                [0, 1, 2],
            )

    def test_radius_collision_is_an_error_not_resampling_or_clamping(self) -> None:
        with patch("src.rqd_exploration.design.qmc.LatinHypercube") as factory:
            factory.return_value.random.return_value = np.full((5, 5), 0.5)
            with self.assertRaisesRegex(ValueError, "ordered radii are equal"):
                generate_lhs_design(self.design)
            factory.return_value.random.assert_called_once_with(n=5)

    def test_radius_order_statistics_do_not_claim_post_sort_lhs_marginals(self) -> None:
        rows = np.array([
            [0.1, 0.1, 0.91, 0.1, 0.1],
            [0.3, 0.3, 0.71, 0.3, 0.3],
            [0.5, 0.5, 0.51, 0.5, 0.5],
            [0.7, 0.7, 0.31, 0.7, 0.7],
            [0.9, 0.9, 0.11, 0.9, 0.9],
        ])
        with patch("src.rqd_exploration.design.qmc.LatinHypercube") as factory:
            factory.return_value.random.return_value = rows
            result = generate_lhs_design(self.design)
        lower_strata = []
        for sample in result.samples:
            radius = sample.joint_sets[0].size_r_min_m
            unit = (log(radius) - log(0.05)) / (log(150) - log(0.05))
            lower_strata.append(floor(unit * 5))
        self.assertEqual(lower_strata, [0, 1, 2, 1, 0])
        self.assertEqual(len(result.samples), 5)

    def test_invalid_inputs_are_explicit_errors(self) -> None:
        for changed, message in (
            (replace(self.design, design_seed=-1), "design_seed"),
            (replace(self.design, sample_count=0), "sample_count"),
            (replace(self.design, joint_sets=()), "requires exactly 1 joint_sets"),
            (replace(self.design, size_alpha=replace(
                self.design.size_alpha, distribution="normal",
            )), "uniform"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                generate_lhs_design(changed)

    def test_invalid_unit_coordinates_stop_without_sample_replacement(self) -> None:
        for invalid in (-0.01, 1.0, float("nan"), float("inf")):
            with self.subTest(coordinate=invalid):
                rows = np.array([
                    [0.1, 0.2, 0.8, 0.3, 0.4],
                    [0.5, 0.6, 0.7, 0.8, 0.9],
                ])
                rows[1, 0] = invalid
                with patch("src.rqd_exploration.design.qmc.LatinHypercube") as factory:
                    factory.return_value.random.return_value = rows
                    with self.assertRaisesRegex(ValueError, "coordinate must be finite"):
                        generate_lhs_design(replace(self.design, sample_count=2))
                    factory.return_value.random.assert_called_once_with(n=2)

    def test_unit_coordinates_unchanged_when_physical_bounds_change(self) -> None:
        original = generate_lhs_design(self.design)
        joint_set = self.design.joint_sets[0]
        changed = generate_lhs_design(replace(
            self.design, joint_sets=(replace(
                joint_set, p32=replace(joint_set.p32, lower=0.02, upper=50),
            ),),
        ))
        self.assertEqual([s.unit_coordinates for s in original.samples],
                         [s.unit_coordinates for s in changed.samples])
        for before, after in zip(original.samples, changed.samples):
            first, second = before.joint_sets[0], after.joint_sets[0]
            self.assertNotEqual(first.p32_m2_per_m3, second.p32_m2_per_m3)
            self.assertEqual(replace(first, p32_m2_per_m3=second.p32_m2_per_m3), second)


if __name__ == "__main__":
    unittest.main()
