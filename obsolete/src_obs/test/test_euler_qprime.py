import unittest

from src.euler_campaign.models import BartonCategory, JointCondition, JointRealization
from src.euler_campaign.qprime import (
    calculate_qprime,
    category_midpoint,
    select_weakest_joint,
)


def make_joint(joint_id: str, jr: float, ja: float) -> JointRealization:
    return JointRealization(
        joint_id=joint_id,
        set_id=1,
        center=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        radius=1.0,
        condition=JointCondition(
            BartonCategory(f"{joint_id}-jr", "Jr", "Test Jr category", jr, jr),
            BartonCategory(f"{joint_id}-ja", "Ja", "Test Ja category", ja, ja),
        ),
    )


class TestEulerQPrime(unittest.TestCase):
    def test_midpoint_preserves_category_range(self) -> None:
        category = BartonCategory("thick-clay", "Ja", "Thick clay", 8.0, 12.0)
        self.assertEqual(category_midpoint(category), 10.0)
        self.assertEqual((category.lower_value, category.upper_value), (8.0, 12.0))

    def test_rqd_floor_preserves_raw_input(self) -> None:
        joint = make_joint("joint", 3.0, 2.0)
        for raw, effective in ((0.0, 10.0), (9.0, 10.0), (10.0, 10.0),
                               (10.5, 10.5), (100.0, 100.0)):
            with self.subTest(raw=raw):
                result = calculate_qprime(raw, 4.0, (joint,))
                self.assertEqual(result.raw_rqd, raw)
                self.assertEqual(result.calculation_rqd, effective)
                self.assertEqual(result.value, effective / 4.0 * 1.5)

    def test_minimum_ratio_uses_one_joint_pair(self) -> None:
        stronger = make_joint("stronger", 1.0, 0.75)
        weaker = make_joint("weaker", 3.0, 8.0)
        self.assertIs(select_weakest_joint((stronger, weaker)), weaker)
        result = calculate_qprime(80.0, 9.0, (stronger, weaker))
        self.assertEqual((result.jr, result.ja), (3.0, 8.0))
        self.assertEqual(result.provenance.selected_joint_id, "weaker")
        self.assertIs(result.provenance.jr_category, weaker.condition.jr_category)
        self.assertIs(result.provenance.ja_category, weaker.condition.ja_category)
        self.assertIsNone(result.provenance.convention_id)

    def test_range_midpoint_is_used_for_selection_and_calculation(self) -> None:
        fixed = make_joint("fixed", 3.0, 8.0)
        ranged = JointRealization(
            "ranged", 2, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0,
            JointCondition(
                fixed.condition.jr_category,
                BartonCategory("thick-clay", "Ja", "Thick clay", 8.0, 12.0),
            ),
        )
        result = calculate_qprime(80.0, 4.0, (fixed, ranged))
        self.assertEqual(result.provenance.selected_joint_id, "ranged")
        self.assertEqual(result.ja, 10.0)
        self.assertEqual(result.value, 6.0)

    def test_no_intersections_are_explicit_convention(self) -> None:
        self.assertIsNone(select_weakest_joint(()))
        result = calculate_qprime(0.0, 4.0, ())
        self.assertEqual(result.raw_rqd, 0.0)
        self.assertEqual((result.calculation_rqd, result.jr, result.ja), (100.0, 4.0, 0.75))
        self.assertAlmostEqual(result.value, 100.0 / 4.0 * (4.0 / 0.75))
        self.assertEqual(result.provenance.source, "no_intersection_convention")
        self.assertIsNotNone(result.provenance.convention_id)
        self.assertIsNone(result.provenance.selected_joint_id)
        self.assertIsNone(result.provenance.jr_category)
        self.assertIsNone(result.provenance.ja_category)

    def test_jn_does_not_depend_on_intersection_count(self) -> None:
        joint = make_joint("joint", 3.0, 2.0)
        one = calculate_qprime(80.0, 9.0, (joint,))
        many = calculate_qprime(80.0, 9.0, (joint, joint, joint))
        self.assertEqual(one.jn, 9.0)
        self.assertEqual(one.value, many.value)

    def test_invalid_inputs_raise_instead_of_being_clamped(self) -> None:
        joint = make_joint("joint", 3.0, 2.0)
        for raw in (-1.0, 101.0, float("nan"), float("inf")):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    calculate_qprime(raw, 4.0, (joint,))
        for jn in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(jn=jn):
                with self.assertRaises(ValueError):
                    calculate_qprime(80.0, jn, (joint,))


if __name__ == "__main__":
    unittest.main()
