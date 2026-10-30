import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.rqd_exploration.config import load_config, parse_config_bytes


VALID_YAML = b"""\
schema_version: 1
geometry:
  coordinate_frame: ENU
  domain_size_m: [60, 30, 30]
  grid_spacing_m: [1, 1, 1]
  tunnel_vertices_m: [[0, 15, 15], [60, 15, 15]]
  tunnel_radius_m: 5
  borehole:
    start_m: [0, 15, 15]
    direction_enu: [2, 0, 0]
    length_m: 60
measurements:
  bh_interval_m: 1
  face_advance_m: 1
designs:
  - design_id: jn-half
    block_id: block-half
    fixed_jn: 0.5
    sample_count: 5
    design_seed: 39
    realization_seed: 43
    orientation_bounds:
      mean_dip_deg:
        lower: 0
        upper: 90
        unit: degree
        coordinate: linear
        upper_inclusive: true
      mean_dip_dir_deg:
        lower: 0
        upper: 360
        unit: degree
        coordinate: linear
        upper_inclusive: false
    shape_randomization:
      size_alpha:
        bounds: [2.5, 4]
        unit: "1"
        distribution: uniform
        rng_stream: separate_from_lhs
      fisher_kappa:
        bounds: [0, 50]
        unit: "1"
        distribution: uniform
        rng_stream: separate_from_lhs
    joint_sets:
      - joint_set_id: set-1
        p32:
          lower: 0.01
          upper: 100
          unit: m^2/m^3
          coordinate: log
          upper_inclusive: true
        size_r_min_m:
          lower: 0.05
          upper: 150
          unit: m
          coordinate: log
          upper_inclusive: true
        size_r_max_m:
          lower: 0.05
          upper: 150
          unit: m
          coordinate: log
          upper_inclusive: true
        size_radius_transform: ordered_log_pair
target_goals:
  - goal_id: high-jn-half-jr-4-ja-075
    target_bin_id: qprime_gt_400
    catalog_id: primary_profile_10bin_v1
    fixed_jn: 0.5
    jr_scenario_id: jr-4
    jr_value: 4
    ja_scenario_id: ja-075
    ja_value: 0.75
  - goal_id: high-jn-half-jr-4-ja-1
    target_bin_id: qprime_gt_400
    catalog_id: primary_profile_10bin_v1
    fixed_jn: 0.5
    jr_scenario_id: jr-4
    jr_value: 4
    ja_scenario_id: ja-1
    ja_value: 1
  - goal_id: high-jn-half-jr-3-ja-075
    target_bin_id: qprime_gt_400
    catalog_id: primary_profile_10bin_v1
    fixed_jn: 0.5
    jr_scenario_id: jr-3
    jr_value: 3
    ja_scenario_id: ja-075
    ja_value: 0.75
  - goal_id: high-jn-half-jr-3-ja-1
    target_bin_id: qprime_gt_400
    catalog_id: primary_profile_10bin_v1
    fixed_jn: 0.5
    jr_scenario_id: jr-3
    jr_value: 3
    ja_scenario_id: ja-1
    ja_value: 1
  - goal_id: high-jn-half-jr-2-ja-075
    target_bin_id: qprime_gt_400
    catalog_id: primary_profile_10bin_v1
    fixed_jn: 0.5
    jr_scenario_id: jr-2
    jr_value: 2
    ja_scenario_id: ja-075
    ja_value: 0.75
  - goal_id: high-jn-1-jr-4-ja-075
    target_bin_id: qprime_gt_400
    catalog_id: primary_profile_10bin_v1
    fixed_jn: 1
    jr_scenario_id: jr-4
    jr_value: 4
    ja_scenario_id: ja-075
    ja_value: 0.75
"""

_pilot_input, _goal_input = VALID_YAML.split(b"target_goals:\n", 1)
_first_design = _pilot_input.split(b"designs:\n", 1)[1]
_second_design = (
    _first_design
    .replace(b"jn-half", b"jn-one", 1)
    .replace(b"block-half", b"block-one", 1)
    .replace(b"fixed_jn: 0.5", b"fixed_jn: 1", 1)
    .replace(b"design_seed: 39", b"design_seed: 36", 1)
)
VALID_YAML = _pilot_input + _second_design + b"target_goals:\n" + _goal_input


class TestRQDExplorationConfig(unittest.TestCase):
    def test_pilot_review_yaml_matches_approved_values(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot.yml"
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
            [(0.5, 5, 39, 43, 1), (1.0, 5, 36, 43, 1)],
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
            joint_set = design.joint_sets[0]
            self.assertEqual((joint_set.p32.lower, joint_set.p32.upper), (0.01, 100))
            for bounds in (joint_set.size_r_min_m, joint_set.size_r_max_m):
                self.assertEqual((bounds.lower, bounds.upper), (0.05, 150))
        self.assertEqual(len(config.target_goals), 6)

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
        self.assertEqual(len(config.target_goals), 6)

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
        before_joint_sets, after_joint_sets = VALID_YAML.split(
            b"    joint_sets:\n", 1,
        )
        _, target_goals = after_joint_sets.split(b"target_goals:\n", 1)
        no_joint_sets = (
            before_joint_sets
            + b"    joint_sets: []\n"
            + b"target_goals:\n"
            + target_goals
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 5"):
            parse_config_bytes(no_joint_sets)

    def test_requires_explicit_complete_target_goal_list(self) -> None:
        without_goals = VALID_YAML.split(b"target_goals:\n", 1)[0]
        with self.assertRaisesRegex(ValueError, "missing required fields.*target_goals"):
            parse_config_bytes(without_goals)

        unsupported_goal = VALID_YAML.replace(
            b"    ja_scenario_id: ja-1\n",
            b"    ja_scenario_id: ja-2\n",
            1,
        ).replace(
            b"    ja_value: 1\n",
            b"    ja_value: 2\n",
            1,
        )
        with self.assertRaisesRegex(ValueError, "six approved reachable"):
            parse_config_bytes(unsupported_goal)

        duplicate_goal_id = VALID_YAML.replace(
            b"  - goal_id: high-jn-half-jr-4-ja-1\n",
            b"  - goal_id: high-jn-half-jr-4-ja-075\n",
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate goal_id"):
            parse_config_bytes(duplicate_goal_id)

        missing_goal_design = VALID_YAML.replace(
            b"    fixed_jn: 1\n",
            b"    fixed_jn: 0.5\n",
            1,
        )
        with self.assertRaisesRegex(ValueError, "without a design block"):
            parse_config_bytes(missing_goal_design)

    def test_rejects_unapproved_jn_and_duplicate_design_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixed_jn must be one of"):
            parse_config_bytes(VALID_YAML.replace(
                b"    fixed_jn: 0.5\n",
                b"    fixed_jn: 0.75\n",
                1,
            ))

        anchored = VALID_YAML.replace(
            b"  - design_id: jn-half\n",
            b"  - &first_design\n    design_id: jn-half\n",
            1,
        ).replace(
            b"target_goals:\n",
            b"  - *first_design\ntarget_goals:\n",
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate design_id"):
            parse_config_bytes(anchored)


if __name__ == "__main__":
    unittest.main()
