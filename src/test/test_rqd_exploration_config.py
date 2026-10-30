import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import yaml

from src.rqd_exploration.config import load_config, parse_config_bytes


PILOT2_PATH = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
VALID_YAML = PILOT2_PATH.read_bytes()


class TestRQDExplorationConfig(unittest.TestCase):
    def test_pilot_review_yaml_matches_approved_values(self) -> None:
        path = PILOT2_PATH
        config = load_config(path)

        self.assertEqual(config.source_yaml_bytes, path.read_bytes())
        self.assertEqual(config.geometry.domain_size_m, (60.0, 30.0, 30.0))
        self.assertEqual(config.geometry.grid_spacing_m, (1.0, 1.0, 1.0))
        self.assertEqual(
            config.geometry.tunnel_vertices_m,
            ((0.0, 15.0, 15.0), (60.0, 15.0, 15.0)),
        )
        self.assertEqual(config.geometry.tunnel_radius_m, 5.0)
        self.assertEqual(config.geometry.borehole_start_m, (0.0, 15.0, 15.0))
        self.assertEqual(config.geometry.borehole_direction_enu, (1.0, 0.0, 0.0))
        self.assertEqual(config.geometry.borehole_length_m, 60.0)
        self.assertEqual(config.measurements.bh_interval_m, 1.0)
        self.assertEqual(config.measurements.face_advance_m, 1.0)
        self.assertEqual(
            [(d.fixed_jn, d.sample_count, d.design_seed, d.realization_seed,
              len(d.joint_sets)) for d in config.designs],
            [(2.0, 5, 39, 43, 1), (4.0, 5, 36, 43, 2)],
        )
        for design in config.designs:
            self.assertEqual((design.mean_dip_deg.lower, design.mean_dip_deg.upper), (0, 90))
            self.assertEqual(
                (design.mean_dip_dir_deg.lower, design.mean_dip_dir_deg.upper,
                 design.mean_dip_dir_deg.upper_inclusive),
                (0, 360, False),
            )
            self.assertEqual(
                (design.size_alpha.bounds.lower, design.size_alpha.bounds.upper),
                (2.5, 4),
            )
            self.assertEqual(
                (design.fisher_kappa.bounds.lower, design.fisher_kappa.bounds.upper),
                (0, 50),
            )
            for joint_set in design.joint_sets:
                self.assertEqual((joint_set.p32.lower, joint_set.p32.upper), (0.01, 100))
                for bounds in (joint_set.size_r_min_m, joint_set.size_r_max_m):
                    self.assertEqual((bounds.lower, bounds.upper), (0.05, 150))

    def test_normalizes_values_and_preserves_exact_source_bytes(self) -> None:
        config = parse_config_bytes(VALID_YAML, "pilot.yml")

        self.assertEqual(config.schema_version, 1)
        self.assertEqual(config.source_yaml_bytes, VALID_YAML)
        self.assertEqual(config.source_yaml_sha256, hashlib.sha256(VALID_YAML).hexdigest())
        self.assertEqual(config.source_reference, "pilot.yml")
        self.assertEqual(config.geometry.cell_counts, (60, 30, 30))
        self.assertEqual(config.geometry.borehole_direction_enu, (1.0, 0.0, 0.0))
        self.assertEqual(config.measurements.bh_interval_m, 1.0)
        self.assertEqual(config.designs[0].design_seed, 39)
        self.assertEqual(config.designs[0].joint_sets[0].p32.coordinate, "log")
        self.assertFalse(config.designs[0].mean_dip_dir_deg.upper_inclusive)
        self.assertEqual([len(d.joint_sets) for d in config.designs], [1, 2])

    def test_loads_exact_bytes_from_a_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.yml"
            path.write_bytes(VALID_YAML)
            config = load_config(path)

        self.assertEqual(config.source_yaml_bytes, VALID_YAML)
        self.assertEqual(config.source_reference, str(path))

    def test_rejects_comment_only_placeholder(self) -> None:
        with self.assertRaisesRegex(TypeError, "configuration must be a mapping"):
            parse_config_bytes(b"# placeholder only\n")

    def test_rejects_invalid_utf8_and_invalid_yaml(self) -> None:
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            parse_config_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "invalid YAML"):
            parse_config_bytes(b"schema_version: [")

    def test_rejects_duplicate_and_unknown_fields(self) -> None:
        duplicate = VALID_YAML.replace(
            b"schema_version: 1\n",
            b"schema_version: 1\nschema_version: 1\n",
            1,
        )
        with self.assertRaisesRegex(ValueError, "invalid YAML"):
            parse_config_bytes(duplicate)
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            parse_config_bytes(VALID_YAML.replace(
                b"schema_version: 1\n",
                b"schema_version: 1\nunexpected: true\n",
                1,
            ))

    def test_rejects_missing_required_field(self) -> None:
        without_seed = VALID_YAML.replace(b"    design_seed: 39\n", b"")
        with self.assertRaisesRegex(ValueError, "design_seed"):
            parse_config_bytes(without_seed)

    def test_rejects_boolean_as_integer_and_unsafe_integer(self) -> None:
        with self.assertRaisesRegex(TypeError, "sample_count must be an integer"):
            parse_config_bytes(VALID_YAML.replace(
                b"    sample_count: 5\n",
                b"    sample_count: true\n",
                1,
            ))
        with self.assertRaisesRegex(ValueError, "safe integer range"):
            parse_config_bytes(VALID_YAML.replace(
                b"    design_seed: 39\n",
                b"    design_seed: 9007199254740992\n",
                1,
            ))

    def test_rejects_non_finite_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            parse_config_bytes(VALID_YAML.replace(
                b"  tunnel_radius_m: 5\n",
                b"  tunnel_radius_m: .inf\n",
                1,
            ))
        with self.assertRaisesRegex(ValueError, "finite"):
            parse_config_bytes(VALID_YAML.replace(
                b"          upper: 100\n",
                b"          upper: .nan\n",
                1,
            ))

    def test_rejects_wrong_units_and_coordinate_transforms(self) -> None:
        with self.assertRaisesRegex(ValueError, "unit"):
            parse_config_bytes(VALID_YAML.replace(
                b"          unit: m^2/m^3\n",
                b"          unit: m\n",
                1,
            ))
        with self.assertRaisesRegex(ValueError, "coordinate"):
            parse_config_bytes(VALID_YAML.replace(
                b"          coordinate: log\n",
                b"          coordinate: linear\n",
                1,
            ))

    def test_rejects_out_of_range_bounds_and_radius_order(self) -> None:
        with self.assertRaisesRegex(ValueError, "0.01 <= lower"):
            parse_config_bytes(VALID_YAML.replace(
                b"          lower: 0.01\n",
                b"          lower: 0\n",
                1,
            ))
        bad_order = VALID_YAML.replace(
            b"        size_r_max_m:\n          lower: 0.05\n          upper: 150\n",
            b"        size_r_max_m:\n          lower: 150\n          upper: 150.1\n",
        )
        with self.assertRaisesRegex(ValueError, "150.0"):
            parse_config_bytes(bad_order)

    def test_rejects_invalid_geometry_and_measurement_step(self) -> None:
        with self.assertRaisesRegex(ValueError, "integer multiple"):
            parse_config_bytes(VALID_YAML.replace(
                b"  grid_spacing_m: [1, 1, 1]\n",
                b"  grid_spacing_m: [7, 1, 1]\n",
                1,
            ))
        with self.assertRaisesRegex(ValueError, "zero-length"):
            parse_config_bytes(VALID_YAML.replace(
                b"  tunnel_vertices_m: [[0, 15, 15], [60, 15, 15]]\n",
                b"  tunnel_vertices_m: [[0, 15, 15], [0, 15, 15]]\n",
                1,
            ))
        with self.assertRaisesRegex(ValueError, "must be 1 m"):
            parse_config_bytes(VALID_YAML.replace(
                b"  face_advance_m: 1\n",
                b"  face_advance_m: 2\n",
                1,
            ))

    def test_rejects_empty_joint_sets(self) -> None:
        data = yaml.safe_load(VALID_YAML)
        data["designs"][0]["joint_sets"] = []
        no_joint_sets = yaml.safe_dump(data).encode()
        with self.assertRaisesRegex(ValueError, "requires exactly 1 joint_sets"):
            parse_config_bytes(no_joint_sets)

    def test_rejects_deprecated_target_goals_field(self) -> None:
        deprecated_field = VALID_YAML + b"\ntarget_goals: []\n"
        with self.assertRaisesRegex(ValueError, "unknown fields.*target_goals"):
            parse_config_bytes(deprecated_field)

    def test_rejects_unapproved_jn_and_duplicate_design_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "executable Barton values"):
            parse_config_bytes(VALID_YAML.replace(
                b"    fixed_jn: 2\n",
                b"    fixed_jn: 3\n",
                1,
            ))

        duplicate_design = VALID_YAML.replace(
            b"design_id: jn-four",
            b"design_id: jn-two",
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate design_id"):
            parse_config_bytes(duplicate_design)

    def test_validates_jn_to_joint_set_count_mapping(self) -> None:
        config_data = yaml.safe_load(VALID_YAML)
        base_set = config_data["designs"][0]["joint_sets"][0]
        for fixed_jn, expected_count in ((2, 1), (4, 2), (9, 3), (15, 4), (20, 5)):
            design = dict(config_data["designs"][0])
            design["fixed_jn"] = fixed_jn
            design["joint_sets"] = [
                {**base_set, "joint_set_id": f"set-{index + 1}"}
                for index in range(expected_count)
            ]
            candidate = dict(config_data)
            candidate["designs"] = [design]
            parsed = parse_config_bytes(yaml.safe_dump(candidate).encode())
            self.assertEqual(len(parsed.designs[0].joint_sets), expected_count)

        invalid = yaml.safe_load(VALID_YAML)
        invalid["designs"][0]["fixed_jn"] = 4
        with self.assertRaisesRegex(ValueError, "requires exactly 2 joint_sets"):
            parse_config_bytes(yaml.safe_dump(invalid).encode())


if __name__ == "__main__":
    unittest.main()
