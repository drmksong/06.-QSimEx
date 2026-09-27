import csv
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import yaml

from validation.run_campaign import (
    assess_physical_probe, build_density_reachability_probe,
    nearest_observed_signatures, observed_euler_probe, run_campaign,
)

from src.core.coverage_rounds import (
    append_ledger,
    audit_borehole_csv,
    build_euler_update_record,
    build_round_record,
    build_screening_round_record,
    coverage_delta,
    deduplicate_domain_records,
    record_screening_round_from_csv,
)


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
            record = json.loads((workdir / "ledger.jsonl").read_text().strip())
            self.assertEqual(len(audit_10["bins"]), 10)
            self.assertEqual(len(audit_20["bins"]), 20)
            self.assertEqual(len(search.call_args.kwargs["cutoffs"]), 11)
            self.assertEqual(audit_20["bins"][1]["signature_hashes"], ["s1", "s2"])
            self.assertEqual(audit_20["signature_bins"], {"s1": [1], "s2": [1]})
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
            self.assertEqual(final_audit["bins"][0]["n_domains"], 1)
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
                "status": "not_identifiable", "reason": "insufficient coverage",
                "lower_cutoff": None, "upper_cutoff": None,
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
            self.assertEqual(records[0]["euler_probe"]["coverage_delta"]["bin_1"], 1.0)
            self.assertEqual(records[0]["euler_probe"]["nearest_observed_bin"], 1)
            self.assertEqual(Path(records[0]["euler_probe"]["source_case_path"]), probe_path.resolve())
            self.assertEqual(records[1]["euler_probe"]["nearest_observed_bin"], 2)
            self.assertTrue(Path(records[0]["next_candidate_path"]).is_file())
            self.assertTrue(Path(records[1]["next_candidate_path"]).is_file())
            cumulative_audit = json.loads((workdir / "iteration_001" / "coverage_audit.json").read_text())
            self.assertEqual(cumulative_audit["bins"][0]["status"], "observed")
            self.assertEqual(cumulative_audit["bins"][2]["status"], "observed")
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
