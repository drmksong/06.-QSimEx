from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
import yaml

from src.rqd_exploration.main_policy import MainPolicy, load_main_config
from src.rqd_exploration.main_controller import initial_snapshots, preview_main


ROOT = Path(__file__).resolve().parents[2]


def main_config_with_seeds(directory, initial_seed, verification_seed):
    payload = yaml.safe_load((ROOT / "config/rqd_exploration_main.yml").read_text())
    payload["baseline_inputs"] = [
        str(ROOT / "config" / name) for name in payload["baseline_inputs"]]
    payload["policy"]["initial_seed"] = initial_seed
    payload["policy"]["verification_seed"] = verification_seed
    path = Path(directory) / "main-with-custom-seeds.yml"
    path.write_text(yaml.safe_dump(payload))
    return load_main_config(path)


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

    def test_seed_values_are_parameters_and_change_the_policy_fingerprint(self):
        baseline = load_main_config(ROOT / "config/rqd_exploration_main.yml")
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            changed = main_config_with_seeds(directory, 107, 311)
        self.assertEqual((changed.policy.initial_seed, changed.policy.verification_seed), (107, 311))
        self.assertNotEqual(changed.fingerprint, baseline.fingerprint)
        self.assertEqual((replace(MainPolicy(), initial_seed=107, verification_seed=311).initial_seed,
                          replace(MainPolicy(), initial_seed=107, verification_seed=311).verification_seed),
                         (107, 311))

    def test_policy_is_not_an_unapproved_tuning_surface(self):
        for field, value in (("maximum_starts", 19_999), ("review_checkpoint_starts", 9_999),
                             ("automatic_retries", 1), ("initial_seed", True),
                             ("verification_seed", 2**53 - 4),
                             ("verification_seed", 2**53 - 2)):
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                replace(MainPolicy(), **{field: value})
        self.assertEqual(asdict(MainPolicy())["initial_seed"], 43)
