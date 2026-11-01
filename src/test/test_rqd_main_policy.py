from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
import yaml

from src.rqd_exploration.main_policy import MainPolicy, load_main_config
from src.rqd_exploration.main_controller import initial_snapshots, preview_main


ROOT = Path(__file__).resolve().parents[2]


def jn20_config_path(directory):
    payload = yaml.safe_load((ROOT / "config/rqd_exploration_main.yml").read_text())
    payload["initial_input"] = str(ROOT / "config/rqd_exploration_jn20.yml")
    payload["baseline_inputs"] = [str(ROOT / "config" / name)
                                 for name in payload["baseline_inputs"]]
    path = Path(directory) / "main-with-jn20.yml"
    path.write_text(yaml.safe_dump(payload))
    return path


def load_jn20_config():
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        return load_main_config(jn20_config_path(directory))


class TestMainPolicy(unittest.TestCase):
    def test_default_excludes_jn20_initialization_and_targets_but_covers_all_bins(self):
        config = load_main_config(ROOT / "config/rqd_exploration_main.yml")
        self.assertIsNone(config.initial)
        self.assertEqual(set(config.templates), {2, 4, 9, 15})
        self.assertEqual(initial_snapshots(config), ())
        preview = preview_main(config)
        self.assertEqual(preview["initial_jobs"], [])
        self.assertEqual(len(preview["targets"]), 10 * 4 * 66)
        self.assertTrue(all(float(t["key"].split("/")[1]) != 20
                            for t in preview["targets"]))
        self.assertEqual({t["key"].split("/")[0] for t in preview["targets"]
                          if t["reachable"]}, {str(i) for i in range(1, 11)})
        self.assertFalse(preview["database_written"])
        self.assertFalse(preview["simulation_started"])

    def test_approved_policy_and_jn20(self):
        config = load_jn20_config()
        policy = config.policy
        self.assertEqual((policy.group_size, policy.consecutive_passes,
                          policy.stability_tolerance, policy.required_inputs),
                         (3, 2, .10, 3))
        self.assertEqual((policy.maximum_starts, policy.review_checkpoint_starts,
                          policy.maximum_expected_joints, policy.stagnant_rounds),
                         (20_000, 10_000, 10_000_000, 3))
        self.assertIsNotNone(config.initial)
        design = config.reference_input.designs[0]
        self.assertEqual((design.fixed_jn, len(design.joint_sets), design.sample_count,
                          design.design_seed, design.realization_seed),
                         (20, 5, 5, 40, 43))
        self.assertEqual(set(config.templates), {2, 4, 9, 15, 20})
        self.assertEqual(config.fingerprint, load_jn20_config().fingerprint)
        self.assertNotEqual(config.fingerprint, load_main_config(
            ROOT / "config/rqd_exploration_main.yml").fingerprint)

    def test_policy_is_not_an_unapproved_tuning_surface(self):
        for field, value in (("maximum_starts", 19_999), ("review_checkpoint_starts", 9_999),
                             ("group_size", 4),
                             ("stability_tolerance", .10001),
                             ("automatic_retries", 1), ("required_inputs", True)):
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                replace(MainPolicy(), **{field: value})
        self.assertEqual(asdict(MainPolicy())["initial_seed"], 43)
