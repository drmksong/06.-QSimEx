from dataclasses import MISSING, FrozenInstanceError, fields, replace
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
    dip_direction_from_mean_normal,
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
            mean_dip=0.0,
            mean_dip_dir=0.0,
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
        self.assertIn("mean_dip", names)
        self.assertIn("mean_dip_dir", names)
        self.assertNotIn("mean_normal", names)
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

    def test_dip_and_direction_are_canonical_and_normal_is_derived(self) -> None:
        joint_set = replace(self.joint_set, mean_dip=60.0, mean_dip_dir=90.0)
        for actual, expected in zip(
            joint_set.mean_normal,
            (-0.8660254037844386, 0.0, 0.5),
        ):
            self.assertAlmostEqual(actual, expected)

        dip, dip_dir = dip_direction_from_mean_normal(joint_set.mean_normal)
        self.assertAlmostEqual(dip, 60.0)
        self.assertAlmostEqual(dip_dir, 90.0)
        self.assertEqual(
            dip_direction_from_mean_normal((0.0, 0.0, 1.0), 123.0),
            (0.0, 123.0),
        )

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

    def test_case_validation_accepts_consistent_inputs(self) -> None:
        self.assertIsNone(validate_case(self.case))

    def test_case_validation_rejects_invalid_domain_and_joint_set(self) -> None:
        invalid_domain = replace(
            self.case,
            domain=DomainSpec((10, 0, 10), (1.0, 1.0, 1.0), 2.0),
        )
        with self.assertRaisesRegex(ValueError, "cell counts"):
            validate_case(invalid_domain)

        invalid_joint_set = replace(self.joint_set, size_r_min=11.0)
        invalid_case = replace(self.case, joint_sets=(invalid_joint_set,))
        with self.assertRaisesRegex(ValueError, "size_r_min"):
            validate_case(invalid_case)

        invalid_dip = replace(self.joint_set, mean_dip=90.1)
        with self.assertRaisesRegex(ValueError, "mean_dip"):
            validate_case(replace(self.case, joint_sets=(invalid_dip,)))

        invalid_dip_dir = replace(self.joint_set, mean_dip_dir=360.1)
        with self.assertRaisesRegex(ValueError, "mean_dip_dir"):
            validate_case(replace(self.case, joint_sets=(invalid_dip_dir,)))

    def test_case_validation_rejects_duplicate_ids(self) -> None:
        duplicate_borehole = replace(self.case.boreholes[0], requested_length=5.0)
        duplicate_case = replace(
            self.case,
            boreholes=(self.case.boreholes[0], duplicate_borehole),
        )
        with self.assertRaisesRegex(ValueError, "duplicate borehole ID"):
            validate_case(duplicate_case)

    def test_signature_identity_uses_generation_features_not_case_metadata(self) -> None:
        signature = identify_signature(self.case)
        renamed = replace(self.case, case_id="renamed-case")
        self.assertEqual(signature.signature_id, identify_signature(renamed).signature_id)
        self.assertIs(signature.case, self.case)

        renamed_joint_set = replace(self.joint_set, name="renamed-set")
        metadata_case = replace(self.case, joint_sets=(renamed_joint_set,))
        self.assertEqual(signature.signature_id, identify_signature(metadata_case).signature_id)

        changed_joint_set = replace(self.joint_set, density_value=2.0)
        changed_case = replace(self.case, joint_sets=(changed_joint_set,))
        self.assertNotEqual(signature.signature_id, identify_signature(changed_case).signature_id)

        changed_condition = JointCondition(
            self.jr,
            BartonCategory("ja_changed", "Ja", "Changed", 9.0, 13.0),
        )
        condition_case = replace(
            self.case,
            joint_sets=(replace(self.joint_set, condition=changed_condition),),
        )
        self.assertNotEqual(signature.signature_id, identify_signature(condition_case).signature_id)

    def test_domain_identity_includes_seed_and_domain(self) -> None:
        signature = identify_signature(self.case)
        domain_id = identify_domain(signature, 42)

        self.assertEqual(domain_id, identify_domain(signature, 42))
        self.assertNotEqual(domain_id, identify_domain(signature, 43))
        self.assertNotEqual(
            domain_id,
            identify_domain(
                signature, 42, generator_version="qsimex-mlx-generation-v1",
            ),
        )

        changed_domain_case = replace(
            self.case,
            domain=DomainSpec((20, 10, 10), (1.0, 1.0, 1.0), 2.0),
        )
        changed_domain_signature = identify_signature(changed_domain_case)
        self.assertEqual(signature.signature_id, changed_domain_signature.signature_id)
        self.assertNotEqual(domain_id, identify_domain(changed_domain_signature, 42))

    def test_domain_identity_rejects_invalid_seed_or_stale_signature(self) -> None:
        signature = identify_signature(self.case)
        for seed in (-1, True):
            with self.subTest(seed=seed), self.assertRaisesRegex(ValueError, "seed"):
                identify_domain(signature, seed)

        with self.assertRaisesRegex(ValueError, "does not match"):
            identify_domain(Signature("stale-signature", self.case), 42)
        with self.assertRaisesRegex(ValueError, "generator_version"):
            identify_domain(signature, 42, generator_version="")


if __name__ == "__main__":
    unittest.main()
