import tempfile
import unittest
from pathlib import Path

import yaml

from src.core.signature_candidates import (
    build_simulation_manifest,
    propose_signature_candidates,
    write_candidate_cases,
)


class TestSignatureCandidates(unittest.TestCase):
    def _case_path(self, directory):
        path = Path(directory) / "case.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "name": "coverage_case",
                    "domain": {"nx": 10, "ny": 10, "nz": 10},
                    "joint_sets": [
                        {
                            "set_id": 1,
                            "P32": 1.0,
                            "mean_spacing": 1.0,
                            "fisher_kappa": 20,
                            "size_r_min": 0.5,
                            "size_r_max": 5.0,
                            "Jr_mean": 1.0,
                            "Ja_mean": 2.0,
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_proposes_distinct_reviewable_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            candidates = propose_signature_candidates(
                str(self._case_path(directory)),
                round_id=1,
                target_region="low_q_gap",
                seed_values=[300, 301],
                recipes=["density_scale"],
                factors=[1.5],
            )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["seed_values"], [300, 301])
        self.assertEqual(candidate["target_region"], "low_q_gap")
        self.assertNotEqual(candidate["generation_signature_hash"], "")
        self.assertIn("coverage_target", candidate["case"]["tags"])

    def test_writes_yaml_and_manifest_requires_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            case_path = self._case_path(directory)
            candidates = propose_signature_candidates(
                str(case_path),
                round_id=1,
                target_region="high_q_gap",
                seed_values=[400],
                recipes=["orientation_spread"],
                factors=[1.25],
            )
            output_dir = Path(directory) / "candidates"
            paths = write_candidate_cases(candidates, str(output_dir))
            manifest = build_simulation_manifest(
                candidates,
                round_id=1,
                output_dir="results/round_001",
            )
            self.assertTrue(Path(paths[0]).exists())
            self.assertTrue(manifest["approval_required"])
            self.assertEqual(manifest["candidates"][0]["seed_values"], [400])

        self.assertEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main()
