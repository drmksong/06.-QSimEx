import unittest

import numpy as np

from src.core import constants


class TestNomenclatureNormalization(unittest.TestCase):
    def test_standardize_empty(self):
        self.assertEqual(constants.standardize_metrics(None), {})

    def test_standardize_basic(self):
        legacy = {
            "FP_false_safe": 3,
            "FN_false_alarm": 5,
            "TP_correct_excavate": 10,
            "TN_correct_reject": 2,
            "expected_cost": 1.23,
        }
        std = constants.standardize_metrics(legacy)
        # canonical keys should be present
        self.assertIn(constants.CANONICAL["FP"], std)
        self.assertIn(constants.CANONICAL["FN"], std)
        self.assertEqual(std[constants.CANONICAL["FP"]], 3)
        self.assertEqual(std[constants.CANONICAL["FN"]], 5)

    def test_conditional_risk_and_cost_aliases_are_canonical(self):
        legacy = {
            "cost_safe": 2.0,
            "cost_alarm": 7.0,
            "R_FS_pass": 0.12,
            "R_FN_reject": 0.08,
        }
        std = constants.standardize_metrics(legacy)
        self.assertEqual(std["cost_false_safe"], 2.0)
        self.assertEqual(std["cost_false_alarm"], 7.0)
        self.assertEqual(std["R_FS_pass"], 0.12)
        self.assertEqual(std["R_FN_reject"], 0.08)

    def test_confusion_metrics_reports_conditional_risks(self):
        from src.core.decision_test import DecisionUsefulnessTester

        metrics = DecisionUsefulnessTester.confusion_metrics(
            np.array([0, 1, 1, 0]),
            np.array([1, 1, 0, 0]),
        )
        self.assertAlmostEqual(metrics["R_FS_pass"], 0.5)
        self.assertAlmostEqual(metrics["R_FN_reject"], 0.5)

    def test_reference_label_and_decision_score_are_separate(self):
        import pandas as pd
        from src.core.decision_test import DecisionUsefulnessTester

        df = pd.DataFrame(
            {
                "Qp_face_mean": [2.0, 5.0, 3.0, 8.0],
                "Qp_borehole_mean": [1.0, 9.0, 1.0, 9.0],
            }
        )
        prepared = DecisionUsefulnessTester.prepare_decision_frame(
            df, reference_col="Qp_face_mean", score_col="Qp_borehole_mean", threshold=4.0
        )

        self.assertListEqual(prepared["suitable"].tolist(), [0, 1, 0, 1])
        self.assertListEqual(prepared["reference_q"].tolist(), [2.0, 5.0, 3.0, 8.0])
        self.assertListEqual(prepared["decision_score"].tolist(), [1.0, 9.0, 1.0, 9.0])
        self.assertNotEqual(prepared["reference_q"].iloc[0], prepared["decision_score"].iloc[0])


if __name__ == "__main__":
    unittest.main()
