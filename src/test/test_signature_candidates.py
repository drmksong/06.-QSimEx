import tempfile
import unittest
from pathlib import Path

import yaml

from src.core.signature_candidates import (
    build_gap_screening_pool,
    build_euler_update_candidate,
    build_euler_update_candidate_from_probes,
    build_neighbor_midpoint_candidate,
    build_selective_neighbor_candidate,
    build_simulation_manifest,
    compute_domain_id,
    compute_generation_signature_hash,
    estimate_euler_direction,
    estimate_euler_direction_from_probes,
    euler_update_feature_vector,
    apply_normalized_features,
    extract_normalized_features,
    plan_gap_candidates,
    propose_signature_candidates,
    validate_strategy_catalog,
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

    def test_generation_hash_excludes_run_metadata(self):
        case = {
            "name": "case-a",
            "seed": 1,
            "tags": {"coverage_round": 1},
            "runtime": 12.5,
            "joint_sets": [{"set_id": 1, "P32": 1.0}],
            "domain": {"nx": 10, "ny": 10, "nz": 10},
        }
        changed_metadata = dict(case)
        changed_metadata.update(
            {
                "name": "case-b",
                "seed": 99,
                "tags": {"coverage_round": 8},
                "runtime": 99.0,
            }
        )

        self.assertEqual(
            compute_generation_signature_hash(case),
            compute_generation_signature_hash(changed_metadata),
        )

    def test_domain_id_changes_only_with_domain_identity_inputs(self):
        case = {
            "name": "case-a",
            "seed": 1,
            "joint_sets": [{"set_id": 1, "P32": 1.0}],
            "domain": {"nx": 10, "ny": 10, "nz": 10},
        }

        first = compute_domain_id(case, seed=1, generator_version="v1")
        same = compute_domain_id(case, seed=1, generator_version="v1")
        different_seed = compute_domain_id(case, seed=2, generator_version="v1")
        different_generator = compute_domain_id(case, seed=1, generator_version="v2")

        self.assertEqual(first, same)
        self.assertNotEqual(first, different_seed)
        self.assertNotEqual(first, different_generator)

    def test_normalized_feature_adapter_round_trips_selected_paths(self):
        case = {
            "joint_sets": [{"P32": 5.0, "fisher_kappa": 50.0}],
            "domain": {"nx": 60},
        }
        bounds = {
            "joint_sets.0.P32": (0.0, 10.0),
            "joint_sets.0.fisher_kappa": (0.0, 100.0),
        }

        normalized = extract_normalized_features(case, bounds)
        updated = apply_normalized_features(
            case,
            {"joint_sets.0.P32": 0.8, "joint_sets.0.fisher_kappa": 0.25},
            bounds,
        )

        self.assertEqual(normalized["joint_sets.0.P32"], 0.5)
        self.assertEqual(updated["joint_sets"][0]["P32"], 8.0)
        self.assertEqual(updated["joint_sets"][0]["fisher_kappa"], 25.0)
        self.assertEqual(updated["domain"]["nx"], 60)

    def test_euler_candidate_updates_selected_case_features_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            case_path = self._case_path(directory)
            candidate = build_euler_update_candidate(
                str(case_path),
                round_id=5,
                target_region="low_q_gap",
                screening_seed=703,
                feature_bounds={
                    "joint_sets.0.P32": (0.0, 2.0),
                    "joint_sets.0.fisher_kappa": (0.0, 40.0),
                },
                feature_delta={
                    "joint_sets.0.P32": 0.1,
                    "joint_sets.0.fisher_kappa": -0.1,
                },
                coverage_delta={"new_bins": 1.0},
                coverage_residual={"new_bins": 0.5},
                step_size=1.0,
                generator_version="test-v1",
            )

        joint_set = candidate["case"]["joint_sets"][0]
        self.assertEqual(joint_set["P32"], 1.1)
        self.assertEqual(joint_set["fisher_kappa"], 18.0)
        self.assertEqual(candidate["case"]["domain"]["nx"], 10)
        self.assertEqual(candidate["seed_values"], [703])
        self.assertEqual(
            candidate["case"]["tags"]["update_method"],
            "bounded_explicit_euler_style",
        )
        self.assertNotEqual(candidate["generation_signature_hash"], "")
        self.assertNotEqual(candidate["domain_id"], "")

    def test_multi_probe_euler_update_uses_unweighted_local_direction(self):
        direction = estimate_euler_direction_from_probes(
            [
                {
                    "feature_delta": {"joint_sets.0.P32": 0.1},
                    "coverage_delta": {"new_bins": 1.0},
                    "coverage_residual": {"new_bins": 1.0},
                },
                {
                    "feature_delta": {"joint_sets.0.P32": 0.2},
                    "coverage_delta": {"new_bins": 1.0},
                    "coverage_residual": {"new_bins": -1.0},
                },
            ]
        )

        self.assertEqual(direction["joint_sets.0.P32"], -0.05)

    def test_multi_probe_euler_candidate_records_all_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_euler_update_candidate_from_probes(
                str(self._case_path(directory)),
                round_id=6,
                target_region="internal_gap",
                screening_seed=704,
                feature_bounds={"joint_sets.0.P32": (0.0, 2.0)},
                probes=[
                    {
                        "feature_delta": {"joint_sets.0.P32": 0.1},
                        "coverage_delta": {"new_bins": 1.0},
                        "coverage_residual": {"new_bins": 1.0},
                    }
                ],
                step_size=1.0,
            )

        self.assertEqual(len(candidate["probes"]), 1)
        self.assertEqual(candidate["case"]["joint_sets"][0]["P32"], 1.2)
        self.assertEqual(
            candidate["case"]["tags"]["update_method"],
            "bounded_explicit_euler_style_multi_probe",
        )

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

    def test_gap_planning_requires_explicit_strategy_catalog(self):
        audit = {
            "observed_min": 5.0,
            "observed_max": 40.0,
            "bins": [
                {
                    "bin_index": 0,
                    "qprime_bh_lower": 1.0,
                    "qprime_bh_upper": 5.0,
                    "status": "UNOBSERVED",
                }
            ],
        }

        with self.assertRaises(ValueError):
            plan_gap_candidates(audit, strategy_catalog={}, max_candidates=1)

    def test_gap_planning_uses_only_reviewed_strategies(self):
        audit = {
            "observed_min": 5.0,
            "observed_max": 40.0,
            "bins": [
                {
                    "bin_index": 0,
                    "qprime_bh_lower": 1.0,
                    "qprime_bh_upper": 5.0,
                    "status": "UNOBSERVED",
                },
                {
                    "bin_index": 1,
                    "qprime_bh_lower": 40.0,
                    "qprime_bh_upper": 100.0,
                    "status": "UNOBSERVED",
                },
            ],
        }
        catalog = {
            "low_q_gap": [
                {
                    "recipe": "density_scale",
                    "direction": "forward",
                    "factor": 1.1,
                    "reason": "reviewed low-Q probe",
                }
            ],
            "high_q_gap": [
                {
                    "recipe": "orientation_spread",
                    "direction": "reverse",
                    "factor": 1.2,
                    "reason": "reviewed high-Q probe",
                }
            ],
        }

        plans = plan_gap_candidates(
            audit,
            strategy_catalog=catalog,
            max_candidates=1,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["recipe"], "density_scale")
        self.assertEqual(plans[0]["factor"], 1.1)
        self.assertEqual(plans[0]["reason"], "reviewed low-Q probe")

    def test_changed_features_catalog_is_validated_and_planned(self):
        audit = {
            "observed_min": 5.0,
            "observed_max": 40.0,
            "bins": [
                {
                    "bin_index": 0,
                    "qprime_bh_lower": 1.0,
                    "qprime_bh_upper": 5.0,
                    "status": "UNOBSERVED",
                }
            ],
        }
        catalog = {
            "low_q_gap": [
                {
                    "strategy_id": "lowq-midpoint-01",
                    "parent_signature": "parent-lowq",
                    "changed_features": [
                        {
                            "name": "joint_sets.0.P32",
                            "direction": "increase",
                            "magnitude": 0.1,
                        }
                    ],
                    "expected_effect": "extend_low_q_coverage",
                    "selection_reason": "neighbor midpoint probe",
                    "validity_constraints": {"P32": [0.0, 10.0]},
                    "status": "approved_for_screening",
                }
            ]
        }

        validate_strategy_catalog(catalog)
        plans = plan_gap_candidates(audit, strategy_catalog=catalog, max_candidates=1)

        self.assertEqual(plans[0]["strategy_id"], "lowq-midpoint-01")
        self.assertEqual(plans[0]["changed_features"][0]["name"], "joint_sets.0.P32")

    def test_gap_planning_cycles_across_empty_bins(self):
        audit = {
            "observed_min": 5.0,
            "observed_max": 40.0,
            "bins": [
                {
                    "bin_index": 0,
                    "qprime_bh_lower": 1.0,
                    "qprime_bh_upper": 5.0,
                    "status": "UNOBSERVED",
                },
                {
                    "bin_index": 1,
                    "qprime_bh_lower": 5.0,
                    "qprime_bh_upper": 10.0,
                    "status": "UNOBSERVED",
                },
            ],
        }
        catalog = {
            "low_q_gap": [
                {"recipe": "density_scale", "factor": 1.1},
                {"recipe": "roughness_scale", "factor": 1.1},
            ],
            "internal_gap": [
                {"recipe": "orientation_spread", "factor": 1.1},
            ],
        }

        plans = plan_gap_candidates(
            audit,
            strategy_catalog=catalog,
            max_candidates=2,
        )

        self.assertEqual({plan["bin_index"] for plan in plans}, {0, 1})

    def test_gap_pool_preserves_common_seed_and_provenance(self):
        audit = {
            "observed_min": 5.0,
            "observed_max": 40.0,
            "bins": [
                {
                    "bin_index": 0,
                    "qprime_bh_lower": 1.0,
                    "qprime_bh_upper": 5.0,
                    "status": "UNOBSERVED",
                }
            ],
        }
        catalog = {
            "low_q_gap": [
                {
                    "recipe": "density_scale",
                    "direction": "forward",
                    "factor": 1.1,
                    "reason": "reviewed low-Q probe",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as directory:
            case_path = self._case_path(directory)
            pool = build_gap_screening_pool(
                audit,
                [{"case_path": str(case_path), "target_region": "low_q_gap"}],
                round_id=3,
                screening_seed=701,
                strategy_catalog=catalog,
                max_candidates=3,
            )

        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["seed_values"], [701])
        self.assertEqual(pool[0]["reason"], "reviewed low-Q probe")
        self.assertEqual(pool[0]["gap_bin_index"], 0)

    def test_neighbor_midpoint_interpolates_numeric_features(self):
        with tempfile.TemporaryDirectory() as directory:
            left_path = self._case_path(directory)
            right_path = Path(directory) / "right.yaml"
            right_data = yaml.safe_load(left_path.read_text(encoding="utf-8"))
            right_data["name"] = "right_case"
            right_data["joint_sets"][0]["P32"] = 3.0
            right_data["joint_sets"][0]["fisher_kappa"] = 40
            right_path.write_text(
                yaml.safe_dump(right_data, sort_keys=False), encoding="utf-8"
            )

            candidate = build_neighbor_midpoint_candidate(
                str(left_path),
                str(right_path),
                round_id=4,
                target_region="internal_gap",
                screening_seed=702,
            )

        joint_set = candidate["case"]["joint_sets"][0]
        self.assertEqual(joint_set["P32"], 2.0)
        self.assertEqual(joint_set["fisher_kappa"], 30.0)
        self.assertEqual(candidate["seed_values"], [702])
        self.assertEqual(len(candidate["changed_features"]), 2)

    def test_selective_neighbor_probe_changes_only_requested_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_path = self._case_path(directory)
            target_path = Path(directory) / "target.yaml"
            target = yaml.safe_load(parent_path.read_text(encoding="utf-8"))
            target["name"] = "target_case"
            target["joint_sets"][0]["P32"] = 3.0
            target["joint_sets"][0]["fisher_kappa"] = 40.0
            target_path.write_text(
                yaml.safe_dump(target, sort_keys=False), encoding="utf-8"
            )

            candidate = build_selective_neighbor_candidate(
                str(parent_path),
                str(target_path),
                ["joint_sets.0.P32"],
                round_id=6,
                target_region="low_q_gap",
                screening_seed=704,
            )

        joint_set = candidate["case"]["joint_sets"][0]
        self.assertEqual(joint_set["P32"], 3.0)
        self.assertEqual(joint_set["fisher_kappa"], 20)
        self.assertEqual(candidate["case"]["tags"]["update_method"], "selective_neighbor_probe")

    def test_euler_update_projects_feature_values_to_bounds(self):
        direction = estimate_euler_direction(
            {"P32": 0.2, "fisher_kappa": -0.1},
            {"qprime_range": 2.0, "new_bins": 1.0},
            {"qprime_range": 1.0, "new_bins": 0.5},
        )
        updated = euler_update_feature_vector(
            {"P32": 0.9, "fisher_kappa": 0.5, "joint_set_count": 3.0},
            direction,
            step_size=2.0,
            bounds={"P32": (0.0, 1.0), "fisher_kappa": (0.0, 1.0)},
            discrete_features=["joint_set_count"],
        )

        self.assertEqual(updated["P32"], 1.0)
        self.assertLess(updated["fisher_kappa"], 0.5)
        self.assertEqual(updated["joint_set_count"], 3.0)

    def test_time_budget_prefers_information_per_second(self):
        audit = {
            "observed_min": 5.0,
            "observed_max": 40.0,
            "bins": [
                {
                    "bin_index": 0,
                    "qprime_bh_lower": 1.0,
                    "qprime_bh_upper": 5.0,
                    "status": "UNOBSERVED",
                }
            ],
        }
        catalog = {
            "low_q_gap": [
                {
                    "recipe": "density_scale",
                    "direction": "forward",
                    "factor": 1.1,
                    "reason": "cheap probe",
                    "estimated_runtime_seconds": 10,
                    "expected_information_gain": 1,
                },
                {
                    "recipe": "roughness_scale",
                    "direction": "forward",
                    "factor": 1.1,
                    "reason": "high value probe",
                    "estimated_runtime_seconds": 20,
                    "expected_information_gain": 10,
                },
            ]
        }

        plans = plan_gap_candidates(
            audit,
            strategy_catalog=catalog,
            max_candidates=1,
            time_budget_seconds=20,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["reason"], "high value probe")
        self.assertEqual(plans[0]["efficiency_score"], 0.5)

    def test_per_gap_budgets_prevent_fast_regime_dominance(self):
        audit = {
            "observed_min": 5.0,
            "observed_max": 40.0,
            "bins": [
                {
                    "bin_index": 0,
                    "qprime_bh_lower": 1.0,
                    "qprime_bh_upper": 5.0,
                    "status": "UNOBSERVED",
                },
                {
                    "bin_index": 1,
                    "qprime_bh_lower": 40.0,
                    "qprime_bh_upper": 100.0,
                    "status": "UNOBSERVED",
                },
            ],
        }
        catalog = {
            "low_q_gap": [
                {
                    "recipe": "density_scale",
                    "factor": 1.1,
                    "estimated_runtime_seconds": 100,
                    "expected_information_gain": 10,
                }
            ],
            "high_q_gap": [
                {
                    "recipe": "orientation_spread",
                    "direction": "reverse",
                    "factor": 1.1,
                    "estimated_runtime_seconds": 10,
                    "expected_information_gain": 1,
                }
            ],
        }

        plans = plan_gap_candidates(
            audit,
            strategy_catalog=catalog,
            max_candidates=2,
            time_budget_by_gap={"low_q_gap": 100, "high_q_gap": 10},
        )

        self.assertEqual(
            {plan["target_region"] for plan in plans}, {"low_q_gap", "high_q_gap"}
        )


if __name__ == "__main__":
    unittest.main()
