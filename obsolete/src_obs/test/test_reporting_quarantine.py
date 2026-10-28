import csv
import tempfile
import unittest
from pathlib import Path

from src.core.reporting import ResearchReporter


class TestReportingQuarantine(unittest.TestCase):
    def test_provisional_binary_reports_are_not_generated(self):
        face_rows = [
            {
                "case_name": "fixture",
                "Qp_face_mean": 12.0,
                "Qp_borehole_mean": 8.0,
                "face_fracture_density": 1.0,
                "orientation_bias_gap": 0.1,
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            ResearchReporter.save_all_tables_as_csv(
                face_rows=face_rows,
                summary_rows=[],
                output_dir=temp_dir,
                prefix="fixture",
            )

            table2 = self._read_rows(Path(temp_dir) / "fixture_table2_classification_performance.csv")
            table3 = self._read_rows(Path(temp_dir) / "fixture_table3_optimal_thresholds.csv")
            table4 = self._read_rows(Path(temp_dir) / "fixture_table4_bayesian_posterior.csv")
            table5 = self._read_rows(Path(temp_dir) / "fixture_table5_domain_of_applicability.csv")

        self.assertEqual(table2[0]["Status"], "not_identifiable")
        self.assertNotIn("Best threshold", table2[0])
        self.assertEqual(table3[0]["Status"], "not_identifiable")
        self.assertEqual(table3[0]["Lower cutoff"], "")
        self.assertEqual(table3[0]["Upper cutoff"], "")
        self.assertEqual(table4[0]["Status"], "not_identifiable")
        self.assertEqual(table5[0]["Condition"], "not_identifiable")

    @staticmethod
    def _read_rows(path: Path):
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()