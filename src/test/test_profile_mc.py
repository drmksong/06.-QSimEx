import tempfile
import unittest
from pathlib import Path

from run_profile_mc import build_runner_config, expand_seeds, load_config


class TestProfileMonteCarloConfig(unittest.TestCase):
    def test_seed_range_is_inclusive_and_reproducible(self):
        config = {
            "seed_range": {"start": 40, "stop": 42, "step": 1},
            "case_paths": ["cases/scenario_03_sparse_large.yaml"],
        }
        self.assertEqual(expand_seeds(config), [40, 41, 42])

    def test_runner_config_uses_profile_output_directory(self):
        config = {
            "seed_range": {"start": 40, "stop": 40},
            "case_paths": ["cases/scenario_03_sparse_large.yaml"],
            "output_dir": "results/profile_mc_exploration",
            "backend": "cpu",
        }
        runner_config = build_runner_config(config)
        self.assertEqual(runner_config.output_dir, "results/profile_mc_exploration")
        self.assertEqual(runner_config.seeds, [40])

    def test_yaml_config_loads(self):
        config_path = Path("config/profile_mc_exploration.yml")
        config = load_config(str(config_path))
        self.assertEqual(config["seed_range"]["start"], 40)
        self.assertEqual(config["seed_range"]["stop"], 139)


if __name__ == "__main__":
    unittest.main()
