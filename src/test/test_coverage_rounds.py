import csv
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import yaml

from validation.run_campaign import (
    assess_physical_probe, bound_limited_features, build_density_reachability_probe,
    load_main_strategy_catalog, nearest_observed_signatures, next_unobserved_profile_target,
    observed_euler_probe, run_campaign, should_extend_density_reachability,
    stabilize_candidate_case_name,
)
from multi_batch_runner import MultiCaseBatchConfig, MultiCaseBatchRunner

from src.core.coverage_rounds import (
    append_ledger,
    audit_borehole_csv,
    build_signature_overlap_report,
    build_euler_update_record,
    build_round_record,
    build_screening_round_record,
    coverage_delta,
    deduplicate_domain_records,
    record_screening_round_from_csv,
)
from src.core.qprime_cutoff_search import generate_qprime_cutoffs


class TestCoverageRounds(unittest.TestCase):
    def _audit(self, minimum, maximum, statuses):
        return {
            "observed_min": minimum,
            "observed_max": maximum,
            "bins": [
                {"bin_index": index, "status": status}
                for index, status in enumerate(statuses)
            ],
        }

    def test_highq_catalog_approves_one_feature_density_size_and_orientation(self):
        from src.core.signature_candidates import build_reviewed_strategy_candidate

        catalog_path = Path(__file__).resolve().parents[2] / "validation" / "highq_strategy_catalog.yml"

        catalog, settings = load_main_strategy_catalog(str(catalog_path))

        strategies = catalog["high_q_gap"]
        self.assertEqual(settings["max_candidates_per_iteration"], 4)
        self.assertEqual(
            {strategy["feature_family"] for strategy in strategies},
            {"A", "B", "C"},
        )
        self.assertEqual(
            {strategy["changed_features"][0]["name"] for strategy in strategies},
            {
                "joint_sets.0.P32",
                "joint_sets.0.size_r_max",
                "joint_sets.0.fisher_kappa",
                "joint_sets.0.mean_dip_dir",
            },
        )
        self.assertTrue(all(
            strategy["status"] == "approved_for_screening"
            and len(strategy["changed_features"]) == 1
            and strategy.get("response_update")
            for strategy in strategies
        ))
        direction_strategy = next(
            strategy for strategy in strategies
            if strategy["changed_features"][0]["name"].endswith(".mean_dip_dir")
        )
        direction_candidate = build_reviewed_strategy_candidate(
            dict(direction_strategy, target_region="high_q_gap", bin_index=8),
            round_id=0,
            screening_seed=1001,
        )
        self.assertGreater(
            direction_candidate["orientation_validation"]["realized_plane_angle_degrees"],
            0.0,
        )

    def test_profile_target_advances_to_nearest_unobserved_bin(self):
        audit = {
            "bins": [
                {
                    "bin_index": index,
                    "status": "observed" if index in {8, 9} else "UNOBSERVED",
                    "n_records": 1 if index in {8, 9} else 0,
                }
                for index in range(10)
            ]
        }

        target_bins, remaining = next_unobserved_profile_target(audit, [8])

        self.assertEqual(target_bins, [7])
        self.assertEqual(remaining, list(range(8)))

    def test_profile_target_reports_complete_only_when_all_primary_bins_observed(self):
        audit = {
            "bins": [
                {"bin_index": index, "status": "observed", "n_records": 1}
                for index in range(10)
            ]
        }

        target_bins, remaining = next_unobserved_profile_target(audit, [8])

        self.assertEqual(target_bins, [])
        self.assertEqual(remaining, [])

    def test_bound_limited_euler_move_is_not_misreported_as_no_direction(self):
        candidate = {
            "normalized_features_before": {"joint_sets.0.P32": 1.0},
            "normalized_features_after": {"joint_sets.0.P32": 1.0},
            "direction": {"joint_sets.0.P32": 0.15},
        }

        self.assertEqual(
            bound_limited_features(candidate), ["joint_sets.0.P32"]
        )

    def test_conflicted_qprime_with_nonregressing_proximity_continues_from_parent(self):
        probe = {
            "feature_delta": {"joint_sets.0.P32": 0.1},
            "coverage_delta": {"proximity_gain": 0.5},
            "source_case_path": "/cases/nearer-parent.yaml",
        }
        physical_assessment = {
            "status": "needs_repeatability",
            "conflicting_metric": "Qp_bh_mean",
        }

        self.assertTrue(should_extend_density_reachability(
            probe, physical_assessment, response=0.875,
            probe_path="/cases/farther-probe.yaml",
        ))
        probe["coverage_delta"]["proximity_gain"] = -0.1
        self.assertFalse(should_extend_density_reachability(
            probe, physical_assessment, response=0.875,
            probe_path="/cases/farther-probe.yaml",
        ))

    def test_candidate_case_name_does_not_accumulate_parent_suffixes(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_path = Path(directory) / "nested.yaml"
            parent_path.write_text(
                "name: base_case__r001-density__r002-euler\njoint_sets:\n- P32: 10\n",
                encoding="utf-8",
            )
            candidate = {
                "candidate_id": "r003-euler-probes-abcd1234",
                "case": {"name": "nested_parent__r003-euler-probes-abcd1234"},
            }

            name = stabilize_candidate_case_name(candidate, str(parent_path))

        self.assertEqual(name, "base_case__r003-euler-probes-abcd1234")
        self.assertEqual(candidate["case"]["name"], name)
        self.assertLess(len(name), 100)

    def test_computed_provenance_is_not_overwritten_by_stale_case_tags(self):
        runner = MultiCaseBatchRunner(MultiCaseBatchConfig(case_paths=[], seeds=[]))
        rows = [{
            "domain_id": "computed-domain",
            "generation_signature_hash": "computed-signature",
            "generation_features_json": "computed-features",
            "generator_version": "computed-generator",
        }]
        metadata = {
            "domain_id": "stale-domain",
            "generation_signature_hash": "stale-signature",
            "generation_features_json": "stale-features",
            "generator_version": "stale-generator",
            "coverage_target": "high_q_gap",
        }

        runner._attach_metadata(rows, metadata)

        self.assertEqual(rows[0]["domain_id"], "computed-domain")
        self.assertEqual(rows[0]["generation_signature_hash"], "computed-signature")
        self.assertEqual(rows[0]["generation_features_json"], "computed-features")
        self.assertEqual(rows[0]["generator_version"], "computed-generator")
        self.assertEqual(rows[0]["coverage_target"], "high_q_gap")

    def test_nonempty_campaign_workdir_requires_force_option(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "case.yaml"
            case_path.write_text("joint_sets: []\n", encoding="utf-8")
            workdir = root / "campaign"
            workdir.mkdir()
            sentinel = workdir / "keep.txt"
            sentinel.write_text("preserve", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                run_campaign(Namespace(
                    workdir=str(workdir), case=[str(case_path)], seed_start=1,
                    seed_stop=1, iterations=1, backend="mlx", dry_run=True,
                    euler_spec=None,
                ))

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_force_overwrite_archives_existing_isolated_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "case.yaml"
            case_path.write_text("joint_sets: []\n", encoding="utf-8")
            workdir = root / "campaign"
            workdir.mkdir()
            (workdir / "campaign_manifest.json").write_text(
                json.dumps({"campaign_type": "isolated_validation"}),
                encoding="utf-8",
            )
            sentinel = workdir / "old_result.csv"
            sentinel.write_text("old results", encoding="utf-8")

            manifest = run_campaign(Namespace(
                workdir=str(workdir), case=[str(case_path)], seed_start=1,
                seed_stop=1, iterations=1, backend="mlx", dry_run=True,
                euler_spec=None, force_overwrite=True,
            ))

            backup = Path(manifest["previous_workdir_backup"])
            self.assertNotEqual(backup, workdir)
            self.assertEqual((backup / "old_result.csv").read_text(encoding="utf-8"), "old results")
            self.assertEqual(
                json.loads((workdir / "campaign_manifest.json").read_text())[
                    "previous_workdir_backup"
                ],
                str(backup),
            )

    def test_force_overwrite_refuses_unowned_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "case.yaml"
            case_path.write_text("joint_sets: []\n", encoding="utf-8")
            workdir = root / "not_campaign"
            workdir.mkdir()
            sentinel = workdir / "keep.txt"
            sentinel.write_text("preserve", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                run_campaign(Namespace(
                    workdir=str(workdir), case=[str(case_path)], seed_start=1,
                    seed_stop=1, iterations=1, backend="mlx", dry_run=True,
                    euler_spec=None, force_overwrite=True,
                ))

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_main_campaign_strategy_catalog_plans_from_csv_without_simulation(self):
        from src.core.signature_candidates import compute_generation_signature_hash

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "parent.yaml"
            case_path.write_text(
                "name: parent\njoint_sets:\n- P32: 10.0\n",
                encoding="utf-8",
            )
            parent_signature = compute_generation_signature_hash(
                yaml.safe_load(case_path.read_text(encoding="utf-8"))
            )
            csv_path = root / "existing_rows.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Qp_bh_mean", "case_name", "seed", "domain_id",
                        "generation_signature_hash",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "Qp_bh_mean": 200.0,
                    "case_name": "parent",
                    "seed": 1001,
                    "domain_id": "parent-domain-1001",
                    "generation_signature_hash": parent_signature,
                })
            catalog_path = root / "catalog.yml"
            catalog_path.write_text(yaml.safe_dump({
                "max_candidates_per_iteration": 1,
                "strategy_catalog": {
                    "low_q_gap": [
                        {
                            "strategy_id": "lowq-p32-probe-01",
                            "status": "approved_for_screening",
                            "feature_family": "A",
                            "parent_signature": parent_signature,
                            "parent_case_path": str(case_path),
                            "changed_features": [{
                                "name": "joint_sets.0.P32",
                                "direction": "increase",
                                "magnitude": 0.1,
                                "target_value": 12.0,
                                "bounds": [0.01, 20000.0],
                            }],
                            "step_size": 0.5,
                            "expected_effect": "probe_low_q_gap",
                            "selection_reason": "explicit test strategy",
                            "validity_constraints": {"P32": [0.0, 20000.0]},
                        },
                        {
                            "strategy_id": "unapproved-p32-probe",
                            "status": "proposed",
                            "feature_family": "A",
                            "parent_signature": parent_signature,
                            "parent_case_path": str(case_path),
                            "changed_features": [{
                                "name": "joint_sets.0.P32",
                                "direction": "increase",
                                "magnitude": 0.2,
                                "target_value": 14.0,
                                "bounds": [0.01, 20000.0],
                            }],
                            "step_size": 0.5,
                            "expected_effect": "probe_low_q_gap",
                            "selection_reason": "not approved yet",
                            "validity_constraints": {"P32": [0.0, 20000.0]},
                        },
                    ],
                },
            }, sort_keys=False), encoding="utf-8")
            workdir = root / "plan_only_campaign"

            with patch("validation.run_campaign.subprocess.run") as simulation_run:
                manifest = run_campaign(Namespace(
                    workdir=str(workdir), case=[str(case_path)],
                    seed_start=1001, seed_stop=1004, iterations=40,
                    backend="mlx", dry_run=True, euler_spec=None,
                    initial_csv=str(csv_path), force_overwrite=False,
                    stop_on_identified=False, strategy_catalog=str(catalog_path),
                    max_candidates_per_iteration=None,
                ))

            plan_path = Path(manifest["strategy_plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "strategy_plan_review_required")
            self.assertFalse(plan["execution_started"])
            self.assertEqual(plan["candidate_plans"][0]["strategy_id"], "lowq-p32-probe-01")
            self.assertEqual(len(plan["candidate_plans"]), 1)
            self.assertEqual(plan["candidate_plans"][0]["bin_index"], 0)
            self.assertEqual(plan["remaining_unobserved_bins"], list(range(9)))
            simulation_run.assert_not_called()

            self.assertFalse((workdir / "campaign_checkpoint.json").exists())

    def test_catalog_campaign_resumes_without_repeating_completed_candidate(self):
        from src.core.signature_candidates import compute_generation_signature_hash

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent_path = root / "parent.yaml"
            parent_path.write_text(
                "name: parent\njoint_sets:\n- P32: 10.0\n",
                encoding="utf-8",
            )
            parent = yaml.safe_load(parent_path.read_text(encoding="utf-8"))
            parent_signature = compute_generation_signature_hash(parent)
            initial_csv = root / "initial.csv"
            with initial_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "Qp_bh_mean", "case_name", "seed", "domain_id",
                    "generation_signature_hash", "Qp_face_mean", "miss_ratio",
                    "face_fracture_density", "orientation_bias_gap_to_face",
                ])
                writer.writeheader()
                writer.writerow({
                    "Qp_bh_mean": 200.0,
                    "case_name": "parent",
                    "seed": 1001,
                    "domain_id": "parent-1001",
                    "generation_signature_hash": parent_signature,
                    "Qp_face_mean": 200.0,
                    "miss_ratio": 0.1,
                    "face_fracture_density": 1.0,
                    "orientation_bias_gap_to_face": 0.1,
                })
            strategies = []
            for index, target in enumerate((12.0, 14.0), start=1):
                strategies.append({
                    "strategy_id": f"lowq-p32-{index}",
                    "status": "approved_for_screening",
                    "feature_family": "A",
                    "parent_signature": parent_signature,
                    "parent_case_path": str(parent_path),
                    "changed_features": [{
                        "name": "joint_sets.0.P32",
                        "target_value": target,
                        "bounds": [0.01, 20000.0],
                    }],
                    "step_size": 0.5,
                    "expected_effect": "probe lower Qprime reachability",
                    "selection_reason": "mock resume test",
                    "validity_constraints": {"P32": [0.01, 20000.0]},
                })
            catalog_path = root / "catalog.yml"
            catalog_path.write_text(yaml.safe_dump({
                "strategy_catalog": {"low_q_gap": strategies},
            }, sort_keys=False), encoding="utf-8")
            workdir = root / "campaign"
            args = Namespace(
                workdir=str(workdir), case=[str(parent_path)], seed_start=1001,
                seed_stop=1001, iterations=2, backend="mlx", dry_run=False,
                euler_spec=None, initial_csv=str(initial_csv), force_overwrite=False,
                resume=False, stop_on_identified=False,
                strategy_catalog=str(catalog_path), max_candidates_per_iteration=None,
                repeatability_seed=[2001],
            )

            successful_csvs = []

            def write_candidate(command, cwd, check):
                config_path = Path(command[command.index("--config") + 1])
                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))[
                    "profile_mc_exploration"
                ]
                case_path = Path(config["case_paths"][0])
                case = yaml.safe_load(case_path.read_text(encoding="utf-8"))
                signature = compute_generation_signature_hash(case)
                seed = config["seed_range"]["start"]
                output = Path(config["output_dir"]) / "all_cases_borehole_rows.csv"
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "Qp_bh_mean", "case_name", "seed", "domain_id",
                        "generation_signature_hash", "Qp_face_mean", "miss_ratio",
                        "face_fracture_density", "orientation_bias_gap_to_face",
                    ])
                    writer.writeheader()
                    writer.writerow({
                        "Qp_bh_mean": 100.0,
                        "case_name": case["name"],
                        "seed": seed,
                        "domain_id": f"{signature}-{seed}",
                        "generation_signature_hash": signature,
                        "Qp_face_mean": 100.0,
                        "miss_ratio": 0.1,
                        "face_fracture_density": 1.0,
                        "orientation_bias_gap_to_face": 0.1,
                    })
                successful_csvs.append(str(output))

            call_count = 0

            def interrupt_second(command, cwd, check):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RuntimeError("mock interruption")
                write_candidate(command, cwd, check)

            with patch(
                "validation.run_campaign.subprocess.run", side_effect=interrupt_second
            ):
                with self.assertRaisesRegex(RuntimeError, "mock interruption"):
                    run_campaign(args)

            checkpoint_path = workdir / "campaign_checkpoint.json"
            interrupted = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            completed_before = {
                key: value["csv_path"] for key, value in interrupted["completed_jobs"].items()
                if value["status"] == "completed"
            }
            self.assertEqual(len(completed_before), 1)
            self.assertEqual(interrupted["status"], "interrupted")

            args.resume = True
            with patch(
                "validation.run_campaign.subprocess.run", side_effect=write_candidate
            ) as resumed_run:
                manifest = run_campaign(args)

            resumed = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(resumed_run.call_count, 4)
            self.assertEqual(len([
                value for value in resumed["completed_jobs"].values()
                if value["status"] == "completed"
                and value["phase"] == "signature_screening"
            ]), 2)
            self.assertEqual(len([
                value for value in resumed["completed_jobs"].values()
                if value["status"] == "completed"
                and value["phase"] == "repeatability_E"
            ]), 3)
            self.assertEqual(len([
                record for record in resumed["ledger_records"]
                if record["round_type"] == "repeatability_E"
            ]), 3)
            self.assertEqual(
                [Path(path).resolve() for path in resumed["source_csvs"]],
                [initial_csv.resolve()],
            )
            self.assertEqual(resumed["repeatability_status"], "completed")
            self.assertTrue(set(completed_before.values()).issubset(successful_csvs))
            self.assertEqual(manifest["status"], "iteration_limit")
            self.assertFalse(manifest["coverage_complete"])
            self.assertTrue(manifest["remaining_unobserved_bins"])
            self.assertFalse(manifest["cutoff_identified"])

    def test_coverage_delta_tracks_new_and_remaining_gaps(self):
        before = self._audit(5.0, 40.0, ["observed", "UNOBSERVED", "UNOBSERVED"])
        after = self._audit(2.0, 80.0, ["observed", "observed", "UNOBSERVED"])

        delta = coverage_delta(before, after)

        self.assertEqual(delta["observed_qprime_range_after"], [2.0, 80.0])
        self.assertEqual(delta["newly_observed_bins"], [1])
        self.assertEqual(delta["remaining_gap_bins"], [2])
        self.assertEqual(delta["unobserved_bin_delta"], -1)

    def test_deduplicates_domain_and_signature_pairs(self):
        result = deduplicate_domain_records(
            [
                {"domain_id": "D1", "generation_signature_hash": "S1"},
                {"domain_id": "D1", "generation_signature_hash": "S1"},
                {"domain_id": "D1", "generation_signature_hash": "S2"},
            ]
        )

        self.assertEqual(result["n_unique"], 2)
        self.assertEqual(result["n_duplicates"], 1)
        self.assertEqual(result["duplicate_domain_ids"], ["D1"])

    def test_signature_overlap_report_preserves_and_ranks_coverage(self):
        report = build_signature_overlap_report(
            [
                {"domain_id": "d1", "generation_signature_hash": "s1", "Qp_bh_mean": 1.2},
                {"domain_id": "d2", "generation_signature_hash": "s1", "Qp_bh_mean": 2.2},
                {"domain_id": "d3", "generation_signature_hash": "s2", "Qp_bh_mean": 1.4},
                {"domain_id": "d4", "generation_signature_hash": "s2", "Qp_bh_mean": 2.4},
                {"domain_id": "d5", "generation_signature_hash": "s3", "Qp_bh_mean": 4.5},
            ],
            cutoffs=[1.0, 2.0, 4.0, 8.0],
        )

        self.assertEqual(report["n_signatures"], 3)
        self.assertEqual(report["n_overlap_only_signatures"], 2)
        self.assertEqual(report["n_unique_coverage_signatures"], 1)
        self.assertEqual(
            report["exact_coverage_footprint_groups"],
            [{"covered_bins": [0, 1], "generation_signature_hashes": ["s1", "s2"]}],
        )
        self.assertEqual(report["source_data_policy"], "preserve_all_signatures_and_rows")

    def test_round_record_and_jsonl_ledger(self):
        before = self._audit(5.0, 40.0, ["observed", "UNOBSERVED"])
        after = self._audit(2.0, 80.0, ["observed", "observed"])
        record = build_round_record(
            round_id=1,
            run_id="r001",
            round_type="coverage_expansion",
            before_audit=before,
            after_audit=after,
            n_domains=10,
            n_signatures=3,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            append_ledger(str(path), record)
            saved = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(saved["round_id"], 1)
        self.assertEqual(saved["newly_observed_bins"], [1])

    def test_euler_update_record_connects_coverage_residual_to_next_features(self):
        record = build_euler_update_record(
            feature_vector={"P32": 0.5, "fisher_kappa": 0.5},
            feature_delta={"P32": 0.1, "fisher_kappa": -0.1},
            coverage_delta_record={"new_bins": 1.0, "qprime_range": 2.0},
            coverage_residual={"new_bins": 0.5, "qprime_range": 1.0},
            step_size=1.0,
            bounds={"P32": (0.0, 1.0), "fisher_kappa": (0.0, 1.0)},
        )

        self.assertEqual(record["update_method"], "bounded_explicit_euler_style")
        self.assertEqual(record["feature_vector_after"]["P32"], 0.55)
        self.assertEqual(record["feature_vector_after"]["fisher_kappa"], 0.45)
        self.assertEqual(record["coverage_residual"]["new_bins"], 0.5)

    def test_screening_round_record_connects_candidates_and_coverage_delta(self):
        before = self._audit(5.0, 40.0, ["UNOBSERVED", "observed"])
        after = self._audit(2.0, 40.0, ["observed", "observed"])
        record = build_screening_round_record(
            round_id=2,
            run_id="r002",
            before_audit=before,
            after_audit=after,
            candidates=[
                {
                    "candidate_id": "c1",
                    "generation_signature_hash": "S1",
                    "domain_id": "D1",
                },
                {
                    "candidate_id": "c2",
                    "generation_signature_hash": "S2",
                    "domain_id": "D2",
                },
            ],
            runtime_status="completed",
            actual_runtime_seconds=12.5,
        )

        self.assertEqual(record["candidate_count"], 2)
        self.assertEqual(record["n_domains"], 2)
        self.assertEqual(record["n_signatures"], 2)
        self.assertEqual(record["newly_observed_bins"], [0])
        self.assertEqual(record["runtime_status"], "completed")

    def test_audit_borehole_csv_tracks_provenance_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "borehole_rows.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Qp_bh_mean",
                        "case_name",
                        "seed",
                        "domain_id",
                        "generation_signature_hash",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Qp_bh_mean": "2.0",
                        "case_name": "case-a",
                        "seed": "1",
                        "domain_id": "D1",
                        "generation_signature_hash": "S1",
                    }
                )

            audit = audit_borehole_csv(str(path), cutoffs=[1.0, 5.0, 10.0])

        self.assertEqual(audit["provenance_status"], "complete")
        self.assertEqual(audit["domain_keys"], ["domain_id"])
        self.assertEqual(audit["n_records_with_domain_id"], 1)

    def test_campaign_writes_ten_bin_profile_and_twenty_bin_signature_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "case.yaml"
            case_path.write_text("joint_sets: []\n", encoding="utf-8")
            workdir = root / "campaign"

            def write_simulation(*args, **kwargs):
                csv_path = workdir / "iteration_000" / "simulation" / "all_cases_borehole_rows.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                with csv_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "Qp_bh_mean", "case_name", "seed", "domain_id",
                        "generation_signature_hash",
                    ])
                    writer.writeheader()
                    writer.writerows([
                        {"Qp_bh_mean": "0.2", "case_name": "A", "seed": 1,
                         "domain_id": "d1", "generation_signature_hash": "s1"},
                        {"Qp_bh_mean": "0.22", "case_name": "B", "seed": 1,
                         "domain_id": "d2", "generation_signature_hash": "s2"},
                    ])

            profile_result = {
                "status": "not_identifiable", "reason": "insufficient coverage",
                "lower_cutoff": None, "upper_cutoff": None,
            }
            with patch("validation.run_campaign.subprocess.run", side_effect=write_simulation), \
                 patch("validation.run_campaign.search_profile_boundaries", return_value=profile_result) as search:
                run_campaign(Namespace(
                    workdir=str(workdir), case=[str(case_path)], seed_start=1,
                    seed_stop=1, iterations=1, backend="mlx", dry_run=False,
                    euler_spec=None,
                ))

            iteration_dir = workdir / "iteration_000"
            audit_10 = json.loads((iteration_dir / "coverage_audit.json").read_text())
            audit_20 = json.loads((iteration_dir / "coverage_audit_20.json").read_text())
            overlap = json.loads((iteration_dir / "signature_overlap_20.json").read_text())
            record = json.loads((workdir / "ledger.jsonl").read_text().strip())
            self.assertEqual(len(audit_10["bins"]), 10)
            self.assertEqual(len(audit_20["bins"]), 20)
            self.assertEqual(len(search.call_args.kwargs["cutoffs"]), 11)
            self.assertEqual(audit_20["bins"][0]["signature_hashes"], [])
            self.assertEqual(audit_20["bins"][1]["signature_hashes"], ["s1", "s2"])
            self.assertEqual(audit_20["signature_bins"], {"s1": [1], "s2": [1]})
            self.assertEqual(overlap["bins"][1]["n_signatures"], 2)
            self.assertEqual(record["signature_overlap_only_count"], 2)
            self.assertEqual(record["coverage_20_unobserved_bins"], 19)

    def test_campaign_does_not_count_rerun_domain_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "case.yaml"
            case_path.write_text("joint_sets: []\n", encoding="utf-8")
            workdir = root / "campaign"

            def write_simulation(command, **kwargs):
                config_path = Path(command[-1])
                csv_path = config_path.parent / "simulation" / "all_cases_borehole_rows.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                with csv_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "Qp_bh_mean", "case_name", "seed", "domain_id",
                        "generation_signature_hash",
                    ])
                    writer.writeheader()
                    for value in (0.11, 0.3):
                        writer.writerow({
                            "Qp_bh_mean": value, "case_name": "A", "seed": 1001,
                            "domain_id": "domain-1", "generation_signature_hash": "signature-1",
                        })

            profile_result = {
                "status": "not_identifiable", "reason": "insufficient coverage",
                "lower_cutoff": None, "upper_cutoff": None,
            }
            with patch("validation.run_campaign.subprocess.run", side_effect=write_simulation), \
                 patch("validation.run_campaign.search_profile_boundaries", return_value=profile_result) as search:
                manifest = run_campaign(Namespace(
                    workdir=str(workdir), case=[str(case_path)], seed_start=1001,
                    seed_stop=1001, iterations=2, backend="mlx", dry_run=False,
                    euler_spec=None,
                ))

            final_audit = json.loads((workdir / "iteration_001" / "coverage_audit.json").read_text())
            self.assertEqual(final_audit["n_records"], 2)
            self.assertEqual(final_audit["bins"][1]["n_domains"], 1)
            self.assertEqual(manifest["records"][1]["new_domain_count"], 0)
            self.assertEqual(manifest["records"][1]["duplicate_domain_count"], 1)
            self.assertEqual(manifest["records"][1]["n_domains"], 1)
            self.assertEqual(manifest["records"][1]["n_signatures"], 1)
            self.assertEqual(len(final_audit["source_csvs"]), 2)
            self.assertEqual(len(search.call_args_list[1].args[0]), 2)

    def test_proposed_euler_spec_never_starts_simulation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent.yaml"
            probe = root / "probe.yaml"
            for path in (parent, probe):
                path.write_text("joint_sets: []\n", encoding="utf-8")
            spec_path = root / "euler.json"
            spec_path.write_text(json.dumps({
                "approval_status": "proposed_review_before_execution",
                "case_path": str(parent), "probe_case_path": str(probe),
                "target_bins": [8],
            }), encoding="utf-8")
            args = Namespace(
                workdir=str(root / "campaign"), case=[str(parent), str(probe)],
                seed_start=1001, seed_stop=1004, iterations=2, backend="mlx",
                dry_run=False, euler_spec=str(spec_path),
            )
            with patch("validation.run_campaign.subprocess.run") as subprocess_run:
                with self.assertRaisesRegex(ValueError, "approved_for_screening"):
                    run_campaign(args)
                subprocess_run.assert_not_called()
            self.assertFalse(Path(args.workdir).exists())
            args.dry_run = True
            self.assertEqual(run_campaign(args)["status"], "dry_run")

    def test_observed_euler_probe_uses_paired_bin_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_path = Path(directory) / "parent.yaml"
            probe_path = Path(directory) / "probe.yaml"
            for path, name, density in (
                (parent_path, "parent", 1.0), (probe_path, "probe", 1.2)
            ):
                path.write_text(yaml.safe_dump({
                    "name": name, "joint_sets": [{"P32": density}]
                }), encoding="utf-8")
            records = [
                {"case_name": "parent", "seed": "1001", "Qp_bh_mean": "0.11",
                 "generation_signature_hash": "s1"},
                {"case_name": "probe", "seed": "1001", "Qp_bh_mean": "0.2",
                 "generation_signature_hash": "s2"},
            ]
            spec = dict(
                parent_path=str(parent_path), probe_path=str(probe_path),
                feature_bounds={"joint_sets.0.P32": (0.0, 2.0)},
                target_bins=[2], cutoffs=[0.1, 0.15, 0.25, 0.4],
            )
            result = observed_euler_probe(records, **spec)
            self.assertAlmostEqual(result["feature_delta"]["joint_sets.0.P32"], 0.1)
            self.assertEqual(result["coverage_delta"]["bin_1"], 1.0)
            self.assertEqual(result["coverage_delta"]["proximity_gain"], 1.0)
            self.assertEqual(result["coverage_residual"]["proximity_gain"], 1.0)
            self.assertEqual(result["nearest_observed_bin"], 1)
            self.assertEqual(result["source_case_path"], str(probe_path))
            with self.assertRaisesRegex(ValueError, "same seed set"):
                observed_euler_probe([
                    records[0], {**records[1], "seed": "1002"}
                ], **spec)
            reversed_response = observed_euler_probe([
                {**records[0], "Qp_bh_mean": "0.2"},
                {**records[1], "Qp_bh_mean": "0.11"},
            ], **spec)
            self.assertEqual(reversed_response["source_case_path"], str(parent_path))
            self.assertAlmostEqual(reversed_response["feature_delta"]["joint_sets.0.P32"], -0.1)

    def test_observed_probe_tolerates_normalized_forward_rounding(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_path = Path(directory) / "parent.yaml"
            probe_path = Path(directory) / "probe.yaml"
            parent_path.write_text(
                "name: parent\njoint_sets:\n- P32: 10.0\n", encoding="utf-8"
            )
            probe_path.write_text(
                "name: probe\njoint_sets:\n- P32: 20.0\n", encoding="utf-8"
            )
            records = [
                {"case_name": "parent", "seed": "1001", "Qp_bh_mean": "250", "generation_signature_hash": "s1"},
                {"case_name": "probe", "seed": "1001", "Qp_bh_mean": "240", "generation_signature_hash": "s2"},
            ]

            result = observed_euler_probe(
                records,
                parent_path=str(parent_path),
                probe_path=str(probe_path),
                feature_bounds={"joint_sets.0.P32": (0.01, 20000.0)},
                target_bins=[8],
                cutoffs=generate_qprime_cutoffs(intervals=10),
            )

            self.assertEqual(list(result["feature_delta"]), ["joint_sets.0.P32"])

    def test_orientation_probe_requires_realized_borehole_plane_angle(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_path = Path(directory) / "parent.yaml"
            probe_path = Path(directory) / "probe.yaml"
            for path, name, direction in (
                (parent_path, "parent", 0.0), (probe_path, "probe", 30.0)
            ):
                path.write_text(yaml.safe_dump({
                    "name": name, "joint_sets": [{"mean_dip_dir": direction}]
                }), encoding="utf-8")
            records = [
                {"case_name": name, "seed": "1001", "Qp_bh_mean": qprime,
                 "RQD_bh_mean": rqd, "borehole_n_intersections_sum": count,
                 "generation_signature_hash": signature}
                for name, qprime, rqd, count, signature in (
                    ("parent", "1", "70", "40", "s1"),
                    ("probe", "2", "90", "20", "s2"),
                )
            ]
            params = dict(
                parent_path=str(parent_path), probe_path=str(probe_path),
                feature_bounds={"joint_sets.0.mean_dip_dir": (0.0, 90.0)},
                target_bins=[2], cutoffs=[0.1, 1.5, 2.5, 4.0],
            )
            with self.assertRaisesRegex(ValueError, "borehole-plane angle"):
                observed_euler_probe(records, **params)
            records[0]["borehole_plane_angle_mean_deg"] = "25"
            records[1]["borehole_plane_angle_mean_deg"] = "40"
            measured = observed_euler_probe(records, **params)
            self.assertEqual(measured["physical_response"]["borehole_plane_angle_mean_deg"], 15.0)
            self.assertEqual(measured["physical_response"]["borehole_n_intersections_sum"], -20.0)

    def test_physical_probe_uses_density_and_realized_angle_responses(self):
        density = {
            "feature_delta": {"joint_sets.0.P32": 0.1},
            "physical_response": {
                "Qp_bh_mean": -0.8, "RQD_bh_mean": -24.2,
                "borehole_n_intersections_sum": 40.17,
            },
        }
        observed = assess_physical_probe(density)
        self.assertEqual(observed["status"], "observed_local_response")
        self.assertAlmostEqual(
            observed["sensitivity_per_normalized_feature"]["RQD_bh_mean"], -242.0
        )
        self.assertNotIn(
            "Qp_bh_mean_per_plane_angle_deg", observed["sensitivity_per_normalized_feature"]
        )
        density["physical_response"]["borehole_n_intersections_sum"] = 0.0
        self.assertEqual(assess_physical_probe(density)["status"], "no_intersection_response")
        density["physical_response"].update({
            "borehole_n_intersections_sum": 40.17,
            "Qp_bh_mean": 0.0, "RQD_bh_mean": 0.0,
        })
        self.assertEqual(assess_physical_probe(density)["status"], "no_quality_response")

        orientation = {
            "feature_delta": {"joint_sets.0.mean_dip_dir": 0.1},
            "physical_response": {
                "Qp_bh_mean": -0.9, "RQD_bh_mean": -24.0,
                "borehole_n_intersections_sum": 50.0,
                "borehole_plane_angle_mean_deg": 10.0,
            },
        }
        assessment = assess_physical_probe(orientation)
        self.assertEqual(assessment["status"], "observed_local_response")
        self.assertAlmostEqual(
            assessment["sensitivity_per_normalized_feature"]["Qp_bh_mean_per_plane_angle_deg"],
            -0.09,
        )
        orientation["seed_physical_responses"] = {
            "317": {"Qp_bh_mean": -1.1, "borehole_plane_angle_mean_deg": 9.0},
            "318": {"Qp_bh_mean": 0.2, "borehole_plane_angle_mean_deg": 11.0},
        }
        conflicted = assess_physical_probe(orientation)
        self.assertEqual(conflicted["status"], "needs_repeatability")
        self.assertEqual(conflicted["conflicting_metric"], "Qp_bh_mean")

    def test_density_reachability_respects_reviewed_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_path = Path(directory) / "parent.yaml"
            probe_path = Path(directory) / "probe.yaml"
            for path, name, density in (
                (parent_path, "parent", 1.0), (probe_path, "probe", 1.2)
            ):
                path.write_text(yaml.safe_dump({
                    "name": name, "joint_sets": [{"P32": density}]
                }), encoding="utf-8")
            options = dict(
                round_id=1, target_region="internal_gap", screening_seed=1001,
                generator_version="test-v1",
            )
            self.assertIsNone(build_density_reachability_probe(
                str(parent_path), str(probe_path),
                feature_bounds={"joint_sets.0.P32": (0.0, 1.2)}, **options,
            ))
            candidate = build_density_reachability_probe(
                str(parent_path), str(probe_path),
                feature_bounds={"joint_sets.0.P32": (0.0, 2.0)}, **options,
            )
            self.assertEqual(candidate["case"]["joint_sets"][0]["P32"], 1.4)
            self.assertEqual(candidate["case"]["tags"]["update_method"], "density_reachability_probe")
            self.assertEqual(
                candidate["case"]["tags"]["generation_signature_hash"],
                candidate["generation_signature_hash"],
            )
            self.assertEqual(
                candidate["case"]["tags"]["domain_id"], candidate["domain_id"]
            )
            next_path = Path(directory) / "next.yaml"
            next_path.write_text(yaml.safe_dump(candidate["case"]), encoding="utf-8")
            wider = build_density_reachability_probe(
                str(probe_path), str(next_path),
                feature_bounds={"joint_sets.0.P32": (0.0, 2.0)}, **options,
            )
            self.assertAlmostEqual(wider["case"]["joint_sets"][0]["P32"], 1.8)

    def test_nearest_observed_signatures_skips_empty_neighbor_bins(self):
        audit = {"bins": [
            {"bin_index": index, "signature_hashes": signatures}
            for index, signatures in enumerate([
                ["distant"], [], [], ["nearest"], [], [], [], [], [], []
            ])
        ]}
        self.assertEqual(nearest_observed_signatures(audit, [8]), {
            "bin_indices": [3], "signature_hashes": ["nearest"],
        })

    def test_campaign_uses_closest_compatible_portfolio_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workdir = root / "campaign"
            paths = {}
            for name, density in (("parent", 1.0), ("probe", 1.2), ("closer", 1.4)):
                paths[name] = root / f"{name}.yaml"
                paths[name].write_text(yaml.safe_dump({
                    "name": name, "joint_sets": [{"P32": density}]
                }), encoding="utf-8")
            spec_path = root / "euler.json"
            spec_path.write_text(json.dumps({
                "case_path": str(paths["parent"]),
                "probe_case_path": str(paths["probe"]),
                "approval_status": "approved_for_screening",
                "target_region": "internal_gap", "target_bins": [4],
                "feature_bounds": {"joint_sets.0.P32": [0.0, 2.0]},
                "step_size": 0.5,
            }), encoding="utf-8")

            def write_simulation(command, **kwargs):
                config_path = Path(command[-1])
                case_paths = yaml.safe_load(config_path.read_text())["profile_mc_exploration"]["case_paths"]
                csv_path = config_path.parent / "simulation" / "all_cases_borehole_rows.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                with csv_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "case_name", "seed", "Qp_bh_mean", "RQD_bh_mean",
                        "borehole_n_intersections_sum", "domain_id",
                        "generation_signature_hash",
                    ])
                    writer.writeheader()
                    for case_path in case_paths:
                        name = yaml.safe_load(Path(case_path).read_text())["name"]
                        qprime = {"parent": 0.11, "probe": 0.3}.get(name, 0.7)
                        writer.writerow({
                            "case_name": name, "seed": 1001, "Qp_bh_mean": qprime,
                            "RQD_bh_mean": 90 - qprime * 10,
                            "borehole_n_intersections_sum": qprime * 10,
                            "domain_id": f"d{name}",
                            "generation_signature_hash": f"h{name}",
                        })

            profile_result = {
                "status": "not_identifiable", "reason": "insufficient coverage",
                "lower_cutoff": None, "upper_cutoff": None,
            }
            with patch("validation.run_campaign.subprocess.run", side_effect=write_simulation), \
                 patch("validation.run_campaign.search_profile_boundaries", return_value=profile_result):
                manifest = run_campaign(Namespace(
                    workdir=str(workdir), case=[str(path) for path in paths.values()],
                    seed_start=1001, seed_stop=1001, iterations=2, backend="mlx",
                    dry_run=False, euler_spec=str(spec_path),
                ))
            first, second = manifest["records"]
            self.assertEqual(first["nearest_observed_signatures"]["signature_hashes"], ["hcloser"])
            self.assertEqual(first["nearest_observed_signatures"]["bin_indices"], [2])
            self.assertEqual(first["euler_probe"]["source_case_path"], str(paths["closer"].resolve()))
            self.assertTrue(Path(first["next_candidate_path"]).is_file())
            self.assertEqual(second["next_action"], "density_probe_iteration_limit")

            paths["closer"].write_text(yaml.safe_dump({
                "name": "closer", "joint_sets": [{"P32": 1.4, "fisher_kappa": 5.0}]
            }), encoding="utf-8")
            with patch("validation.run_campaign.subprocess.run", side_effect=write_simulation), \
                 patch("validation.run_campaign.search_profile_boundaries", return_value=profile_result):
                incompatible = run_campaign(Namespace(
                    workdir=str(root / "incompatible"),
                    case=[str(path) for path in paths.values()], seed_start=1001,
                    seed_stop=1001, iterations=2, backend="mlx", dry_run=False,
                    euler_spec=str(spec_path),
                ))
            self.assertEqual(incompatible["records"][0]["next_action"], "await_nearest_signature_probe")
            self.assertNotIn("next_candidate_path", incompatible["records"][0])

    def test_campaign_euler_updates_from_newly_simulated_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workdir = root / "campaign"
            parent_path = root / "parent.yaml"
            probe_path = root / "probe.yaml"
            for path, name, density in (
                (parent_path, "parent", 1.0), (probe_path, "probe", 1.2)
            ):
                path.write_text(yaml.safe_dump({
                    "name": name, "joint_sets": [{"P32": density}]
                }), encoding="utf-8")
            spec_path = root / "euler.json"
            spec_path.write_text(json.dumps({
                "case_path": str(parent_path), "probe_case_path": str(probe_path),
                "approval_status": "approved_for_screening",
                "target_region": "internal_gap", "target_bins": [4],
                "feature_bounds": {"joint_sets.0.P32": [0.0, 2.0]},
                "step_size": 0.5,
            }), encoding="utf-8")

            def write_simulation(command, **kwargs):
                config_path = Path(command[-1])
                case_paths = yaml.safe_load(config_path.read_text())["profile_mc_exploration"]["case_paths"]
                csv_path = config_path.parent / "simulation" / "all_cases_borehole_rows.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                with csv_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "case_name", "seed", "Qp_bh_mean", "RQD_bh_mean",
                        "borehole_n_intersections_sum", "domain_id",
                        "generation_signature_hash",
                    ])
                    writer.writeheader()
                    for index, case_path in enumerate(case_paths):
                        case = yaml.safe_load(Path(case_path).read_text())
                        writer.writerow({
                            "case_name": case["name"], "seed": 1001,
                            "Qp_bh_mean": (0.11 if case["name"] == "parent" else
                                           0.3 if config_path.parent.name == "iteration_000" else 0.7),
                            "RQD_bh_mean": (90 if case["name"] == "parent" else
                                            80 if config_path.parent.name == "iteration_000" else 70),
                            "borehole_n_intersections_sum": (1 if case["name"] == "parent" else
                                                             2 if config_path.parent.name == "iteration_000" else 3),
                            "domain_id": f"d{config_path.parent.name}-{index}",
                            "generation_signature_hash": f"s{config_path.parent.name}-{index}",
                        })

            profile_result = {
                "status": "identified", "reason": "screening signal only",
                "lower_cutoff": 1.0, "upper_cutoff": 10.0,
            }
            profile_input_sizes = []

            def capture_profile(records, **kwargs):
                profile_input_sizes.append(len(records))
                return profile_result

            with patch("validation.run_campaign.subprocess.run", side_effect=write_simulation), \
                  patch("validation.run_campaign.search_profile_boundaries", side_effect=capture_profile):
                manifest = run_campaign(Namespace(
                    workdir=str(workdir), case=[str(parent_path), str(probe_path)],
                    seed_start=1001, seed_stop=1001, iterations=3, backend="mlx",
                    dry_run=False, euler_spec=str(spec_path),
                ))

            records = manifest["records"]
            self.assertEqual(len(records), 3)
            self.assertEqual(records[0]["euler_probe"]["coverage_delta"]["bin_0"], -1.0)
            self.assertEqual(records[0]["euler_probe"]["coverage_delta"]["bin_1"], 1.0)
            self.assertEqual(records[0]["euler_probe"]["nearest_observed_bin"], 1)
            self.assertEqual(Path(records[0]["euler_probe"]["source_case_path"]), probe_path.resolve())
            self.assertEqual(records[1]["euler_probe"]["nearest_observed_bin"], 2)
            self.assertTrue(Path(records[0]["next_candidate_path"]).is_file())
            self.assertTrue(Path(records[1]["next_candidate_path"]).is_file())
            cumulative_audit = json.loads((workdir / "iteration_001" / "coverage_audit.json").read_text())
            self.assertEqual(cumulative_audit["bins"][0]["status"], "observed")
            self.assertEqual(cumulative_audit["bins"][1]["status"], "observed")
            self.assertEqual(profile_input_sizes, [2, 3, 4])
            self.assertEqual(records[2]["next_action"], "density_probe_iteration_limit")
            self.assertNotIn("next_candidate_path", records[2])

    def test_campaign_expands_density_probe_until_intersections_respond(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent_path = root / "parent.yaml"
            probe_path = root / "probe.yaml"
            for path, name, density in (
                (parent_path, "parent", 1.0), (probe_path, "probe", 1.2)
            ):
                path.write_text(yaml.safe_dump({
                    "name": name, "joint_sets": [{"P32": density}]
                }), encoding="utf-8")
            spec_path = root / "euler.json"
            spec_path.write_text(json.dumps({
                "case_path": str(parent_path), "probe_case_path": str(probe_path),
                "approval_status": "approved_for_screening",
                "target_region": "internal_gap", "target_bins": [4],
                "feature_bounds": {"joint_sets.0.P32": [0.0, 2.0]},
                "step_size": 0.5,
            }), encoding="utf-8")

            def write_simulation(command, **kwargs):
                config_path = Path(command[-1])
                case_paths = yaml.safe_load(config_path.read_text())["profile_mc_exploration"]["case_paths"]
                csv_path = config_path.parent / "simulation" / "all_cases_borehole_rows.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                with csv_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "case_name", "seed", "Qp_bh_mean", "RQD_bh_mean",
                        "borehole_n_intersections_sum", "domain_id",
                        "generation_signature_hash",
                    ])
                    writer.writeheader()
                    for case_path in case_paths:
                        case = yaml.safe_load(Path(case_path).read_text())
                        density = round(case["joint_sets"][0]["P32"], 6)
                        name = case["name"]
                        writer.writerow({
                            "case_name": name, "seed": 1001,
                            "Qp_bh_mean": 0.11 if density < 1.8 else 0.3,
                            "RQD_bh_mean": 90 if density < 1.8 else 80,
                            "borehole_n_intersections_sum": 0 if density < 1.8 else 5,
                            "domain_id": f"d{name}",
                            "generation_signature_hash": f"s{density}",
                        })

            profile_result = {
                "status": "not_identifiable", "reason": "insufficient coverage",
                "lower_cutoff": None, "upper_cutoff": None,
            }
            with patch("validation.run_campaign.subprocess.run", side_effect=write_simulation), \
                 patch("validation.run_campaign.search_profile_boundaries", return_value=profile_result):
                manifest = run_campaign(Namespace(
                    workdir=str(root / "campaign"), case=[str(parent_path), str(probe_path)],
                    seed_start=1001, seed_stop=1001, iterations=3, backend="mlx",
                    dry_run=False, euler_spec=str(spec_path),
                ))

            first, second, third = manifest["records"]
            self.assertEqual(first["physical_assessment"]["status"], "no_intersection_response")
            self.assertEqual(first["next_action"], "expand_density_probe")
            candidate_path = Path(first["next_candidate_path"])
            self.assertEqual(yaml.safe_load(candidate_path.read_text())["joint_sets"][0]["P32"], 1.4)
            self.assertEqual(second["next_action"], "expand_density_probe")
            self.assertAlmostEqual(
                yaml.safe_load(Path(second["next_candidate_path"]).read_text())["joint_sets"][0]["P32"],
                1.8,
            )
            self.assertEqual(third["physical_assessment"]["status"], "observed_local_response")

            spec_path.write_text(json.dumps({
                "case_path": str(parent_path), "probe_case_path": str(probe_path),
                "approval_status": "approved_for_screening",
                "target_region": "internal_gap", "target_bins": [4],
                "feature_bounds": {"joint_sets.0.P32": [0.0, 1.2]},
                "step_size": 0.5,
            }), encoding="utf-8")
            with patch("validation.run_campaign.subprocess.run", side_effect=write_simulation), \
                 patch("validation.run_campaign.search_profile_boundaries", return_value=profile_result):
                bounded = run_campaign(Namespace(
                    workdir=str(root / "bounded"), case=[str(parent_path), str(probe_path)],
                    seed_start=1001, seed_stop=1001, iterations=3, backend="mlx",
                    dry_run=False, euler_spec=str(spec_path),
                ))
            self.assertEqual(bounded["records"][0]["next_action"], "await_wider_density_bounds")
            self.assertNotIn("next_candidate_path", bounded["records"][0])

    def test_campaign_reuses_initial_csv_and_expands_without_qprime_slope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent_path = root / "parent.yaml"
            probe_path = root / "probe.yaml"
            for path, name, density in (
                (parent_path, "parent", 1.0), (probe_path, "probe", 1.2)
            ):
                path.write_text(yaml.safe_dump({
                    "name": name, "joint_sets": [{"P32": density}]
                }), encoding="utf-8")
            initial_csv = root / "completed_round.csv"
            fields = [
                "case_name", "seed", "Qp_bh_mean", "RQD_bh_mean",
                "borehole_n_intersections_sum", "domain_id",
                "generation_signature_hash",
            ]
            with initial_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for case_name, signature, qprime_values in (
                    ("parent", "s-parent", (180.0, 190.0)),
                    ("probe", "s-probe", (160.0, 200.0)),
                ):
                    for seed, qprime in zip((1001, 1002), qprime_values):
                        writer.writerow({
                            "case_name": case_name, "seed": seed,
                            "Qp_bh_mean": qprime, "RQD_bh_mean": 90.0,
                            "borehole_n_intersections_sum": (
                                5.0 if case_name == "parent" else 6.0
                            ),
                            "domain_id": f"{signature}-{seed}",
                            "generation_signature_hash": signature,
                        })
            original_csv = initial_csv.read_bytes()
            spec_path = root / "euler.json"
            spec_path.write_text(json.dumps({
                "case_path": str(parent_path), "probe_case_path": str(probe_path),
                "approval_status": "approved_for_screening",
                "target_region": "high_q_gap", "target_bins": [8],
                "feature_bounds": {"joint_sets.0.P32": [0.0, 2.0]},
                "step_size": 0.5,
            }), encoding="utf-8")

            def write_candidate_simulation(command, **kwargs):
                config_path = Path(command[-1])
                case_paths = yaml.safe_load(config_path.read_text())[
                    "profile_mc_exploration"
                ]["case_paths"]
                csv_path = config_path.parent / "simulation" / "all_cases_borehole_rows.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                with csv_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    for case_path in case_paths:
                        case = yaml.safe_load(Path(case_path).read_text())
                        for seed in (1001, 1002):
                            writer.writerow({
                                "case_name": case["name"], "seed": seed,
                                "Qp_bh_mean": 250.0, "RQD_bh_mean": 90.0,
                                "borehole_n_intersections_sum": 6.0,
                                "domain_id": f"d-{case['name']}-{seed}",
                                "generation_signature_hash": f"s-{case['name']}",
                            })

            with patch(
                "validation.run_campaign.subprocess.run",
                side_effect=write_candidate_simulation,
            ) as simulation_run, patch(
                "validation.run_campaign.search_profile_boundaries",
                return_value={
                    "status": "not_identifiable", "reason": "insufficient coverage",
                    "lower_cutoff": None, "upper_cutoff": None,
                },
            ):
                manifest = run_campaign(Namespace(
                    workdir=str(root / "campaign"),
                    case=[str(parent_path), str(probe_path)],
                    seed_start=1001, seed_stop=1002, iterations=2, backend="mlx",
                    dry_run=False, euler_spec=str(spec_path),
                    initial_csv=str(initial_csv),
                ))

            first = manifest["records"][0]
            self.assertTrue(manifest["initial_results_reused"])
            self.assertEqual(first["physical_assessment"]["status"], "needs_repeatability")
            self.assertEqual(first["next_action"], "expand_density_probe")
            self.assertIn("without inferring an Euler direction", first["density_reachability_reason"])
            self.assertTrue(Path(first["next_candidate_path"]).is_file())
            self.assertEqual(simulation_run.call_count, 1)
            self.assertEqual(initial_csv.read_bytes(), original_csv)

    def test_record_screening_round_from_csv_appends_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "borehole_rows.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["Qp_bh_mean", "case_name", "seed"],
                )
                writer.writeheader()
                writer.writerow({"Qp_bh_mean": "2.0", "case_name": "A", "seed": "1"})
            ledger_path = Path(directory) / "ledger.jsonl"

            result = record_screening_round_from_csv(
                after_csv=str(csv_path),
                candidates=[
                    {
                        "candidate_id": "c1",
                        "generation_signature_hash": "S1",
                        "domain_id": "D1",
                    }
                ],
                round_id=3,
                run_id="r003",
                ledger_path=str(ledger_path),
                cutoffs=[1.0, 5.0, 10.0],
            )

            saved = json.loads(ledger_path.read_text(encoding="utf-8").strip())

        self.assertEqual(result["audit"]["provenance_status"], "incomplete")
        self.assertEqual(saved["run_id"], "r003")
        self.assertEqual(saved["candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
