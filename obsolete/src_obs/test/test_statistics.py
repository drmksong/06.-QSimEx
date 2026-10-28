import unittest

from src.core.statistics import cluster_bootstrap, run_bootstrap_schedule


class TestDomainClusterBootstrap(unittest.TestCase):
    def _records(self):
        records = []
        values = [
            (0.2, 1.0, 0.1, 1.0, 0.1),
            (2.0, 1.0, 0.1, 1.0, 0.1),
            (20.0, 5.0, 0.5, 0.5, 0.5),
            (200.0, 5.1, 0.5, 0.5, 0.5),
        ]
        for domain_index in range(4):
            for row_index, (qprime, face, risk, density, orientation) in enumerate(values):
                records.append(
                    {
                        "domain_id": f"D{domain_index}",
                        "case_name": "A",
                        "seed": domain_index,
                        "Qp_bh_mean": qprime,
                        "Qp_face_mean": face,
                        "miss_ratio": risk,
                        "face_fracture_density": density,
                        "orientation_bias_gap_to_face": orientation,
                    }
                )
        return records

    def test_resamples_complete_domains_and_reports_statuses(self):
        result = cluster_bootstrap(
            self._records(),
            cutoffs=[0.1, 1.0, 10.0, 100.0, 1000.0],
            iterations=50,
            random_state=7,
        )

        self.assertEqual(result["method"], "domain_cluster_bootstrap")
        self.assertEqual(result["n_domains"], 4)
        self.assertEqual(result["n_records"], 16)
        self.assertEqual(result["iterations"], 50)
        self.assertIn("identified", result["status_proportions"])
        self.assertEqual(len(result["profile_state_proportions"]["qprime_face"]), 4)

    def test_missing_domain_id_is_rejected(self):
        with self.assertRaises(KeyError):
            cluster_bootstrap([{"Qp_bh_mean": 1.0}], iterations=2)

    def test_staged_bootstrap_uses_small_to_large_budgets(self):
        results = run_bootstrap_schedule(
            self._records(),
            cutoffs=[0.1, 1.0, 10.0, 100.0, 1000.0],
            stages=[5, 10],
            random_state=11,
        )

        self.assertEqual([result["iterations"] for result in results], [5, 10])
        self.assertIsNone(results[0]["stability_against_previous"])


if __name__ == "__main__":
    unittest.main()
