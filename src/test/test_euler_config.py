import tempfile
import unittest
from pathlib import Path
import shutil

import yaml

from src.euler_campaign.config import (
    load_barton_categories,
    load_campaign_project,
    load_case,
    save_campaign_project,
    save_case,
)
from src.euler_campaign.models import (
    BartonCategory,
    BoreholeSpec,
    CaseSpec,
    DomainSpec,
    JointCondition,
    JointSetSpec,
    TunnelSpec,
)


class TestEulerConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.categories = (
            BartonCategory("jr-rough", "Jr", "Rough joints", 3.0, 4.0),
            BartonCategory("ja-clay", "Ja", "Clay filling", 8.0, 12.0),
        )
        self.case = CaseSpec(
            "case-1",
            DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0),
            (
                JointSetSpec(
                    1, "set-a", "P32", 1.0, 3.0, 0.5, 10.0,
                    0.0, 0.0, 20.0, JointCondition(*self.categories),
                ),
            ),
            (
                BoreholeSpec(
                    "bh-1", (0.0, 5.0, 5.0), (1.0, 0.0, 0.0),
                    10.0, 1.0, "face_comparison",
                ),
            ),
            TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 1.0),
        )

    def _category_catalog(self) -> dict[str, list[dict[str, object]]]:
        return {
            "categories": [
                {
                    "category_id": category.category_id,
                    "parameter": category.parameter,
                    "description": category.description,
                    "lower_value": category.lower_value,
                    "upper_value": category.upper_value,
                }
                for category in self.categories
            ],
        }

    def _case_mapping(self) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.yaml"
            save_case(path, self.case)
            return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_category_catalog_loads_explicit_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "categories.yaml"
            path.write_text(
                yaml.safe_dump(self._category_catalog(), sort_keys=False),
                encoding="utf-8",
            )

            loaded = load_barton_categories(path)

        self.assertEqual(loaded, self.categories)

    def test_case_round_trip_resolves_category_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            categories_path = root / "categories.yaml"
            case_path = root / "case.yaml"
            categories_path.write_text(
                yaml.safe_dump(self._category_catalog(), sort_keys=False),
                encoding="utf-8",
            )
            save_case(case_path, self.case)

            categories = load_barton_categories(categories_path)
            loaded = load_case(case_path, categories)

        self.assertEqual(loaded, self.case)
        self.assertIs(loaded.joint_sets[0].condition.jr_category, categories[0])
        self.assertIs(loaded.joint_sets[0].condition.ja_category, categories[1])

    def test_case_orientation_uses_dip_and_direction_fields(self) -> None:
        mapping = self._case_mapping()
        joint_sets = mapping["joint_sets"]
        assert isinstance(joint_sets, list)
        joint_set = joint_sets[0]
        self.assertEqual(joint_set["mean_dip"], 0.0)
        self.assertEqual(joint_set["mean_dip_dir"], 0.0)
        self.assertNotIn("mean_normal", joint_set)

        joint_set["mean_normal"] = [0.0, 0.0, 1.0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.yaml"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown fields.*mean_normal"):
                load_case(path, self.categories)

    def test_case_orientation_angles_derive_the_internal_normal(self) -> None:
        mapping = self._case_mapping()
        joint_sets = mapping["joint_sets"]
        assert isinstance(joint_sets, list)
        joint_set = joint_sets[0]
        joint_set["mean_dip"] = 60.0
        joint_set["mean_dip_dir"] = 90.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.yaml"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            loaded = load_case(path, self.categories)

        normal = loaded.joint_sets[0].mean_normal
        self.assertAlmostEqual(normal[0], -0.8660254037844386)
        self.assertAlmostEqual(normal[1], 0.0)
        self.assertAlmostEqual(normal[2], 0.5)

    def test_case_rejects_missing_or_wrong_category_references(self) -> None:
        mapping = self._case_mapping()
        joint_sets = mapping["joint_sets"]
        assert isinstance(joint_sets, list)
        condition = joint_sets[0]["condition"]
        del condition["jr_category"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.yaml"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required fields"):
                load_case(path, self.categories)

        condition["jr_category"] = "missing"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.yaml"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown Jr category"):
                load_case(path, self.categories)

            condition["jr_category"] = "ja-clay"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must reference a Jr"):
                load_case(path, self.categories)

    def test_case_rejects_legacy_normal_distribution_fields(self) -> None:
        mapping = self._case_mapping()
        joint_sets = mapping["joint_sets"]
        assert isinstance(joint_sets, list)
        joint_sets[0]["Jr_mean"] = 1.5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-case.yaml"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "legacy field"):
                load_case(path, self.categories)

    def test_category_catalog_rejects_duplicate_ids_and_empty_catalog(self) -> None:
        for catalog, message in (
            ({"categories": []}, "at least one"),
            (
                {
                    "categories": [
                        {
                            "category_id": "duplicate",
                            "parameter": "Jr",
                            "description": "first",
                            "lower_value": 1.0,
                            "upper_value": 1.0,
                        },
                        {
                            "category_id": "duplicate",
                            "parameter": "Ja",
                            "description": "second",
                            "lower_value": 1.0,
                            "upper_value": 1.0,
                        },
                    ],
                },
                "duplicate",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "categories.yaml"
                path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    load_barton_categories(path)


class TestCampaignProjectConfig(unittest.TestCase):
    campaign_path = (
        Path(__file__).resolve().parents[2]
        / "cases"
        / "euler"
        / "highq_euler_multistart_campaign_gap_v2.yaml"
    )

    def _prepare_project_dir(
        self,
        directory: Path,
        mapping: dict[str, object] | None = None,
    ) -> Path:
        source_mapping = yaml.safe_load(
            self.campaign_path.read_text(encoding="utf-8"),
        )
        for key in ("base_case", "category_catalog"):
            filename = source_mapping[key]
            shutil.copyfile(
                self.campaign_path.parent / filename,
                directory / filename,
            )
        project_mapping = source_mapping if mapping is None else mapping
        project_path = directory / self.campaign_path.name
        project_path.write_text(
            yaml.safe_dump(project_mapping, sort_keys=False),
            encoding="utf-8",
        )
        return project_path

    def test_approved_campaign_manifest_loads_all_reproducibility_inputs(self) -> None:
        project = load_campaign_project(self.campaign_path)

        self.assertEqual(project.plan.campaign_id, "highq-euler-multistart-gap-v2")
        self.assertEqual(project.plan_revision, 1)
        self.assertIsNone(project.parent_revision)
        self.assertIsNone(project.parent_plan_fingerprint)
        self.assertEqual(project.base_case, "highq_euler_d20000_case_draft.yaml")
        self.assertEqual(project.category_catalog, "barton_categories.yaml")
        self.assertEqual(project.plan.update_rule_id, "normalized-gradient-gap-v2")
        self.assertEqual(project.plan.exploration_seed, 1001)
        self.assertEqual(project.plan.verification_seeds, (1002, 1003, 1004))
        self.assertEqual(
            tuple(
                signature.case.joint_sets[0].density_value
                for signature in project.plan.start_signatures
            ),
            (200.0, 100.0, 50.0),
        )
        self.assertEqual(project.plan.grid.grid_id, "primary_profile_10bin_v1")
        self.assertEqual(len(project.plan.grid.edges), 11)
        self.assertEqual(project.plan.grid.edges[0], 0.0)
        self.assertEqual(project.plan.grid.edges[-1], 400.0)
        self.assertEqual(project.round_budget, None)
        self.assertEqual(
            project.output_path_template,
            "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
        )

    def test_campaign_project_round_trip_preserves_plan_and_project_metadata(self) -> None:
        original = load_campaign_project(self.campaign_path)

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            self._prepare_project_dir(project_dir)
            saved_path = project_dir / "round_trip_campaign.yaml"
            save_campaign_project(saved_path, original)
            loaded = load_campaign_project(saved_path)

        self.assertEqual(loaded, original)

    def test_campaign_project_rejects_unknown_fields(self) -> None:
        mapping = yaml.safe_load(self.campaign_path.read_text(encoding="utf-8"))
        mapping["unexpected"] = True
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_path = self._prepare_project_dir(Path(temporary_directory), mapping)
            with self.assertRaisesRegex(ValueError, "unknown fields.*unexpected"):
                load_campaign_project(project_path)

    def test_campaign_project_rejects_unsafe_references_and_output_paths(self) -> None:
        for key, value, message in (
            ("base_case", "../outside.yaml", "normalized relative project path"),
            (
                "execution",
                {
                    "backend": "mlx",
                    "gpu_required": True,
                    "cpu_fallback": False,
                    "device_policy": "apple_silicon_mlx_gpu",
                    "record_actual_device_and_runtime_fingerprint": True,
                    "output_path_template": "../{campaign_id}/{run_generation_id}",
                    "result_role": "coverage_exploration_only",
                    "include_in_calibration": False,
                    "include_in_validation": False,
                },
                "must stay within the project",
            ),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary_directory:
                mapping = yaml.safe_load(
                    self.campaign_path.read_text(encoding="utf-8"),
                )
                mapping[key] = value
                project_path = self._prepare_project_dir(
                    Path(temporary_directory),
                    mapping,
                )
                with self.assertRaisesRegex(ValueError, message):
                    load_campaign_project(project_path)

    def test_campaign_project_rejects_invalid_revision_lineage(self) -> None:
        mapping = yaml.safe_load(self.campaign_path.read_text(encoding="utf-8"))
        mapping["plan_revision"] = 2
        mapping["parent_revision"] = 1
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_path = self._prepare_project_dir(
                Path(temporary_directory),
                mapping,
            )
            with self.assertRaisesRegex(ValueError, "parent_plan_fingerprint"):
                load_campaign_project(project_path)


if __name__ == "__main__":
    unittest.main()
