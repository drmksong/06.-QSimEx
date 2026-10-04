from dataclasses import MISSING, FrozenInstanceError, fields
import unittest

from src.euler_campaign.models import (
    BartonCategory,
    BoreholeSpec,
    CaseSpec,
    DomainSpec,
    JointCondition,
    JointRealization,
    JointSetSpec,
    Signature,
    TunnelSpec,
    identify_domain,
    identify_signature,
    validate_case,
)


class TestEulerModels(unittest.TestCase):
    def setUp(self) -> None:
        self.jr = BartonCategory("jr_discontinuous", "Jr", "Discontinuous joints", 4.0, 4.0)
        self.ja = BartonCategory("ja_thick_clay", "Ja", "Thick clay filling", 8.0, 12.0)
        self.condition = JointCondition(self.jr, self.ja)
        self.joint_set = JointSetSpec(
            set_id=1,
            name="test-set",
            density_type="P32",
            density_value=1.0,
            size_alpha=3.0,
            size_r_min=0.5,
            size_r_max=10.0,
            mean_normal=(0.0, 0.0, 1.0),
            fisher_kappa=20.0,
            condition=self.condition,
        )
        self.case = CaseSpec(
            case_id="test-case",
            domain=DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0),
            joint_sets=(self.joint_set,),
            boreholes=(BoreholeSpec("bh-1", (0.0, 5.0, 5.0), (1.0, 0.0, 0.0), 10.0, 1.0, "face_comparison"),),
            tunnel=TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 1.0),
        )

    def test_category_preserves_original_description_and_range(self) -> None:
        self.assertEqual(self.condition.ja_category.description, "Thick clay filling")
        self.assertEqual((self.ja.lower_value, self.ja.upper_value), (8.0, 12.0))
        self.assertEqual((self.jr.lower_value, self.jr.upper_value), (4.0, 4.0))

    def test_joint_set_has_one_condition_and_no_normal_distribution_fields(self) -> None:
        names = {item.name for item in fields(JointSetSpec)}
        self.assertIn("condition", names)
        self.assertTrue(names.isdisjoint({"Jr_mean", "Jr_std", "Ja_mean", "Ja_std"}))
        joints = tuple(
            JointRealization(
                f"joint-{index}", 1, (float(index), 0.0, 0.0),
                (0.0, 0.0, 1.0), 1.0, self.joint_set.condition,
            )
            for index in range(2)
        )
        for joint in joints:
            self.assertIs(joint.condition, self.joint_set.condition)

    def test_conditions_have_no_implicit_default(self) -> None:
        for item in fields(JointCondition):
            self.assertIs(item.default, MISSING)
            self.assertIs(item.default_factory, MISSING)

    def test_category_and_nested_condition_are_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            setattr(self.jr, "lower_value", 3.0)
        with self.assertRaises(FrozenInstanceError):
            setattr(self.condition, "jr_category", self.ja)

    def test_reversed_parameters_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "jr_category"):
            JointCondition(self.ja, self.jr)
        with self.assertRaisesRegex(ValueError, "ja_category"):
            JointCondition(self.jr, self.jr)

    def test_invalid_category_values_are_rejected(self) -> None:
        for lower, upper in ((0.0, 1.0), (-1.0, 1.0), (12.0, 8.0),
                             (float("nan"), 4.0), (1.0, float("inf"))):
            with self.subTest(lower=lower, upper=upper):
                with self.assertRaises(ValueError):
                    BartonCategory("category", "Jr", "Description", lower, upper)

    def test_empty_category_provenance_is_rejected(self) -> None:
        for category_id, description in (("", "Description"), ("category", " ")):
            with self.subTest(category_id=category_id, description=description):
                with self.assertRaises(ValueError):
                    BartonCategory(category_id, "Jr", description, 4.0, 4.0)

    def test_domain_jn_is_preserved_not_derived_from_hits(self) -> None:
        self.assertEqual(self.case.domain.jn, 2.0)
        self.assertEqual(self.case.joint_sets, (self.joint_set,))

    def test_unimplemented_operations_fail_explicitly(self) -> None:
        with self.assertRaises(NotImplementedError):
            validate_case(self.case)
        with self.assertRaises(NotImplementedError):
            identify_signature(self.case)
        with self.assertRaises(NotImplementedError):
            identify_domain(Signature("test-signature", self.case), 42)


if __name__ == "__main__":
    unittest.main()
