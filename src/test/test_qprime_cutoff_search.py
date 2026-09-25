import unittest
import json
import tempfile
from pathlib import Path

import numpy as np

from src.core.qprime_cutoff_search import (
    DEFAULT_MAX_CUTOFF,
    DEFAULT_MIN_CUTOFF,
    DEFAULT_INTERVALS,
    classify_qprime,
    build_search_records,
    combine_profile_states,
    evaluate_lower_cutoff,
    evaluate_upper_cutoff,
    generate_qprime_cutoffs,
    load_cutoff_config,
    run_cutoff_search,
    save_cutoff_search_results,
    search_lower_cutoffs,
    search_cutoffs_from_records,
    search_upper_cutoffs,
    summarize_cutoff_regions,
    validate_borehole_records,
)


class TestQPrimeCutoffSearch(unittest.TestCase):
    def test_default_cutoffs_use_logarithmic_intervals(self):
        cutoffs = generate_qprime_cutoffs()

        self.assertEqual(len(cutoffs), DEFAULT_INTERVALS + 1)
        self.assertAlmostEqual(cutoffs[0], DEFAULT_MIN_CUTOFF)
        self.assertAlmostEqual(cutoffs[-1], DEFAULT_MAX_CUTOFF)
        ratios = np.asarray(cutoffs[1:]) / np.asarray(cutoffs[:-1])
        self.assertTrue(np.allclose(ratios, ratios[0]))

    def test_custom_interval_count(self):
        cutoffs = generate_qprime_cutoffs(0.1, 400.0, intervals=2)

        self.assertEqual(len(cutoffs), 3)
        self.assertTrue(np.allclose(cutoffs, [0.1, np.sqrt(40.0), 400.0]))

    def test_profile_states_use_common_bad_and_good_regions(self):
        result = combine_profile_states(
            [0.1, 1.0, 10.0, 100.0],
            {
                "face": ["PR", "PR", "TR", "POST"],
                "intersection": ["PR", "TR", "TR", "POST"],
                "orientation": ["PR", "PR", "TR", "POST"],
            },
        )

        self.assertEqual(result["status"], "identified")
        self.assertEqual(result["lower_cutoff"], 0.1)
        self.assertEqual(result["upper_cutoff"], 100.0)
        self.assertEqual(result["common_states"], ["PR", "TR", "TR", "POST"])

    def test_profile_state_conflict_returns_not_identifiable(self):
        result = combine_profile_states(
            [0.1, 1.0, 10.0],
            {"face": ["PR", "TR", "POST"], "intersection": ["TR", "TR", "PR"]},
        )

        self.assertEqual(result["status"], "not_identifiable")
        self.assertIsNone(result["lower_cutoff"])
        self.assertIsNone(result["upper_cutoff"])

    def test_invalid_range_or_interval_count(self):
        with self.assertRaises(ValueError):
            generate_qprime_cutoffs(0.0, 400.0)
        with self.assertRaises(ValueError):
            generate_qprime_cutoffs(0.1, 400.0, intervals=0)

    def test_classification_uses_borehole_qprime_only(self):
        self.assertEqual(classify_qprime(0.1, 1.0, 10.0), "hold")
        self.assertEqual(classify_qprime(1.0, 1.0, 10.0), "uncertain")
        self.assertEqual(classify_qprime(10.0, 1.0, 10.0), "excavate")
        self.assertEqual(classify_qprime(float("nan"), 1.0, 10.0), "unknown")

    def test_lower_cutoff_is_evaluated_independently(self):
        result = evaluate_lower_cutoff(
            [0.05, 0.5, 2.0, 10.0],
            [1, 1, 0, 0],
            lower_cutoff=0.1,
        )

        self.assertEqual(result["n_hold"], 1)
        self.assertEqual(result["suitable_hold"], 1)
        self.assertEqual(result["false_reject_rate"], 1.0)

    def test_upper_cutoff_is_evaluated_independently(self):
        result = evaluate_upper_cutoff(
            [0.05, 0.5, 2.0, 10.0],
            [1, 1, 0, 0],
            upper_cutoff=5.0,
        )

        self.assertEqual(result["n_excavate"], 1)
        self.assertEqual(result["unsuitable_excavate"], 1)
        self.assertEqual(result["false_safe_rate"], 1.0)

    def test_lower_and_upper_searches_are_independent(self):
        qprime_bh = (value for value in [0.05, 0.5, 2.0, 10.0])
        labels = (value for value in [1, 1, 0, 0])
        lower_results = search_lower_cutoffs(qprime_bh, labels, [0.1, 1.0, 10.0])
        upper_results = search_upper_cutoffs(
            [0.05, 0.5, 2.0, 10.0], [1, 1, 0, 0], [0.1, 1.0, 10.0]
        )

        self.assertEqual(len(lower_results), 3)
        self.assertEqual(len(upper_results), 3)
        self.assertTrue(all("lower_cutoff" not in row for row in lower_results))
        self.assertTrue(all("upper_cutoff" not in row for row in upper_results))

    def test_yaml_config_and_json_result_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "cutoff.yml"
            result_path = Path(temp_dir) / "cutoff.json"
            config_path.write_text(
                "qprime_cutoff_search:\n"
                "  minimum: 0.1\n"
                "  maximum: 400\n"
                "  intervals: 2\n"
                "  scale: logarithmic\n",
                encoding="utf-8",
            )

            config = load_cutoff_config(str(config_path))
            self.assertEqual(config["intervals"], 2)
            save_cutoff_search_results(
                str(result_path),
                [{"cutoff": 0.1, "false_reject_rate": float("nan")}],
                [{"cutoff": 400.0, "false_safe_rate": 0.0}],
                metadata={"config": config},
            )
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertIsNone(payload["lower_cutoff_results"][0]["false_reject_rate"])
            self.assertEqual(payload["metadata"]["config"]["scale"], "logarithmic")

    def test_record_search_requires_explicit_post_excavation_label(self):
        records = [
            {"Qp_bh_mean": 0.5, "Qp_face_mean": 2.0},
            {"Qp_bh_mean": 20.0, "Qp_face_mean": 30.0},
        ]
        with self.assertRaises(KeyError):
            search_cutoffs_from_records(records, {"intervals": 2})

    def test_borehole_record_validation_reports_missing_qprime(self):
        summary = validate_borehole_records(
            [
                {"Qp_bh_mean": 1.0, "post_excavation_label": 1},
                {"Qp_bh_mean": float("nan"), "post_excavation_label": 0},
            ]
        )

        self.assertEqual(summary["n_records"], 2)
        self.assertEqual(summary["n_finite_qprime_bh"], 1)
        self.assertEqual(summary["n_missing_qprime_bh"], 1)

    def test_region_summary_does_not_require_post_excavation_label(self):
        summary = summarize_cutoff_regions(
            [{"Qp_bh_mean": 0.5}, {"Qp_bh_mean": 5.0}, {"Qp_bh_mean": 20.0}],
            lower_cutoff=1.0,
            upper_cutoff=10.0,
        )

        self.assertEqual(summary["n_hold"], 1)
        self.assertEqual(summary["n_uncertain"], 1)
        self.assertEqual(summary["n_excavate"], 1)

    def test_record_search_uses_explicit_label_without_face_threshold(self):
        records = [
            {"Qp_bh_mean": 0.5, "Qp_face_mean": 2.0, "post_excavation_label": 1},
            {"Qp_bh_mean": 20.0, "Qp_face_mean": 30.0, "post_excavation_label": 0},
        ]
        result = search_cutoffs_from_records(records, {"intervals": 2})

        self.assertEqual(result["n_records"], 2)
        self.assertEqual(len(result["lower_cutoff_results"]), 3)
        self.assertEqual(len(result["upper_cutoff_results"]), 3)

    def test_build_search_records_preserves_face_value_and_attaches_label(self):
        rows = [{"Qp_bh_mean": 2.0, "Qp_face_mean": 7.0, "domain": "D1"}]
        records = build_search_records(rows, [0])

        self.assertEqual(records[0]["Qp_bh_mean"], 2.0)
        self.assertEqual(records[0]["Qp_face_mean"], 7.0)
        self.assertEqual(records[0]["post_excavation_label"], 0)

    def test_build_search_records_rejects_misaligned_labels(self):
        with self.assertRaises(ValueError):
            build_search_records([{"Qp_bh_mean": 2.0}], [])

    def test_csv_runner_writes_json_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            input_path = temp_dir / "records.csv"
            config_path = temp_dir / "config.yml"
            output_path = temp_dir / "results.json"
            input_path.write_text(
                "Qp_bh_mean,post_excavation_label,Qp_face_mean\n"
                "0.5,1,2.0\n"
                "20.0,0,30.0\n",
                encoding="utf-8",
            )
            config_path.write_text(
                "qprime_cutoff_search:\n  minimum: 0.1\n  maximum: 400\n  intervals: 2\n",
                encoding="utf-8",
            )

            result = run_cutoff_search(
                str(input_path), str(config_path), str(output_path)
            )

            self.assertEqual(result["n_records"], 2)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["metadata"]["n_records"], 2)


if __name__ == "__main__":
    unittest.main()