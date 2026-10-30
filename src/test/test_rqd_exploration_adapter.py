from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from src.rqd_exploration.adapter import build_generation_case
from src.rqd_exploration.config import load_config
from src.rqd_exploration.fingerprint import ExecutionJointSet


class TestGenerationAdapter(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
        self.config = load_config(path)
        self.joint_set = ExecutionJointSet("set-1", 1.5, 3.0, 0.5, 10.0, 45.0, 120.0, 20.0)

    def test_preserves_sampled_values_geometry_and_fixed_jn_without_generation(self) -> None:
        with patch("src.euler_campaign.dfn.CaseJointFactory.generate") as generate:
            for design in self.config.designs:
                case = build_generation_case(
                    self.config.geometry, self.config.measurements,
                    design.fixed_jn, (self.joint_set,), case_id=design.design_id,
                )
                self.assertEqual(case.domain.jn, design.fixed_jn)
                self.assertEqual(case.domain.cell_counts, (60, 30, 30))
                self.assertEqual(case.domain.grid_spacing, (1.0, 1.0, 1.0))
                self.assertEqual(case.tunnel.vertices, self.config.geometry.tunnel_vertices_m)
                self.assertEqual(case.tunnel.radius, 5.0)
                self.assertEqual(case.boreholes[0].start, (0.0, 15.0, 15.0))
                self.assertEqual(case.boreholes[0].direction, (1.0, 0.0, 0.0))
                self.assertEqual(case.boreholes[0].requested_length, 60.0)
                self.assertEqual(case.boreholes[0].interval_length, 1.0)
                joint = case.joint_sets[0]
                self.assertEqual(
                    (joint.density_type, joint.density_value, joint.size_alpha,
                     joint.size_r_min, joint.size_r_max, joint.mean_dip,
                     joint.mean_dip_dir, joint.fisher_kappa),
                    ("P32", 1.5, 3.0, 0.5, 10.0, 45.0, 120.0, 20.0),
                )
                self.assertEqual(joint.condition.jr_category.category_id, "generation-only-jr")
                self.assertEqual(joint.condition.ja_category.category_id, "generation-only-ja")
                self.assertEqual(joint.condition.jr_category.lower_value, 1.0)
                self.assertEqual(joint.condition.ja_category.lower_value, 1.0)
            generate.assert_not_called()

    def test_assigns_integer_ids_in_input_order(self) -> None:
        sets = (replace(self.joint_set, joint_set_id="z"), self.joint_set)
        case = build_generation_case(
            self.config.geometry, self.config.measurements, 0.5, sets, case_id="ordered",
        )
        self.assertEqual([(s.set_id, s.name) for s in case.joint_sets], [(1, "z"), (2, "set-1")])

    def test_rejects_missing_duplicate_or_invalid_sampled_sets(self) -> None:
        for sets, message in (
            ((), "between 1 and 5"),
            ((self.joint_set,) * 2, "unique"),
            ((replace(self.joint_set, size_r_min_m=10.0),), "sampled radii"),
            ((replace(self.joint_set, p32_m2_per_m3=float("nan")),), "density_value"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                build_generation_case(
                    self.config.geometry, self.config.measurements, 0.5, sets,
                    case_id="invalid",
                )


if __name__ == "__main__":
    unittest.main()
