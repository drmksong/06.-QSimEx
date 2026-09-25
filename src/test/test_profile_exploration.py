import unittest

from src.core.profile_exploration import (
    audit_qprime_coverage,
    classify_profile_states,
    search_profile_boundaries,
    summarize_profiles,
)


class TestProfileExploration(unittest.TestCase):
    def test_audits_internal_and_external_qprime_gaps(self):
        records = [
            {"Qp_bh_mean": value, "case_name": "A", "seed": index}
            for index, value in enumerate([2.0, 20.0])
        ]

        audit = audit_qprime_coverage(
            records,
            cutoffs=[1.0, 5.0, 10.0, 30.0, 100.0],
        )

        self.assertEqual(audit["observed_min"], 2.0)
        self.assertEqual(audit["observed_max"], 20.0)
        self.assertEqual(audit["bins"][0]["status"], "observed")
        self.assertEqual(
            audit["bins"][1]["recommendation"],
            "add configurations to fill an internal coverage gap",
        )
        self.assertEqual(
            audit["bins"][3]["recommendation"],
            "test reachability with configuration expansion",
        )

    def test_classifies_profile_change_states_without_suitability_labels(self):
        summaries = [
            {"qprime_face_median": value, "qprime_face_n": 3, "n_domains": 3}
            for value in [1.0, 1.0, 5.0, 5.1, 5.0]
        ]

        states = classify_profile_states(
            summaries,
            profile_names=["qprime_face"],
            change_tolerance=0.25,
            stability_tolerance=0.05,
        )

        self.assertEqual(states["qprime_face"], ["PR", "PR", "TR", "POST", "POST"])

    def test_empty_profile_bin_is_unobserved(self):
        summaries = [
            {"qprime_face_median": 1.0, "qprime_face_n": 3, "n_domains": 2},
            {"qprime_face_median": None, "qprime_face_n": 0, "n_domains": 0},
            {"qprime_face_median": 5.0, "qprime_face_n": 3, "n_domains": 2},
        ]

        states = classify_profile_states(summaries, profile_names=["qprime_face"])

        self.assertEqual(states["qprime_face"], ["TR", "UNOBSERVED", "TR"])

    def test_searches_simulation_boundaries_without_suitability_labels(self):
        records = [
            {
                "Qp_bh_mean": qprime,
                "Qp_face_mean": face,
                "miss_ratio": risk,
                "face_fracture_density": density,
                "orientation_bias_gap_to_face": orientation,
                "case_name": "A",
                "seed": index,
                "domain_id": f"A:{index}",
            }
            for index, (qprime, face, risk, density, orientation) in enumerate(
                [
                    (0.2, 1.0, 0.1, 1.0, 0.1),
                    (2.0, 1.0, 0.1, 1.0, 0.1),
                    (20.0, 5.0, 0.5, 0.5, 0.5),
                    (200.0, 5.1, 0.5, 0.5, 0.5),
                ]
            )
        ]

        result = search_profile_boundaries(
            records,
            cutoffs=[0.1, 1.0, 10.0, 100.0, 1000.0],
            change_tolerance=0.25,
            stability_tolerance=0.05,
        )

        self.assertEqual(result["status"], "identified")
        self.assertEqual(result["reason"], "common PR and POST profile regions identified")
        self.assertEqual(result["lower_cutoff"], 1.0)
        self.assertEqual(result["upper_cutoff"], 100.0)
        self.assertNotIn("post_excavation_label", result)

    def test_summarizes_borehole_qprime_bins_without_state_classification(self):
        records = [
            {"Qp_bh_mean": 0.2, "Qp_face_mean": 2.0, "miss_ratio": 0.8,
             "face_fracture_density": 0.4, "orientation_bias_gap_to_face": 0.2,
             "case_name": "A", "seed": 1},
            {"Qp_bh_mean": 2.0, "Qp_face_mean": 8.0, "miss_ratio": 0.2,
             "face_fracture_density": 0.1, "orientation_bias_gap_to_face": 0.1,
             "case_name": "A", "seed": 2},
            {"Qp_bh_mean": 20.0, "Qp_face_mean": 12.0, "miss_ratio": 0.1,
             "face_fracture_density": 0.05, "orientation_bias_gap_to_face": 0.05,
             "case_name": "B", "seed": 1},
        ]
        summaries = summarize_profiles(
            records,
            cutoffs=[0.1, 1.0, 10.0, 100.0],
        )

        self.assertEqual(len(summaries), 3)
        self.assertEqual([row["n_records"] for row in summaries], [1, 1, 1])
        self.assertEqual(summaries[0]["qprime_face_median"], 2.0)
        self.assertEqual(summaries[1]["qprime_face_median"], 8.0)
        self.assertEqual(summaries[2]["qprime_face_median"], 12.0)
        self.assertNotIn("state", summaries[0])

    def test_missing_profile_column_is_rejected(self):
        with self.assertRaises(KeyError):
            summarize_profiles(
                [{"Qp_bh_mean": 1.0, "Qp_face_mean": 2.0}],
                cutoffs=[0.1, 1.0, 10.0],
            )


if __name__ == "__main__":
    unittest.main()