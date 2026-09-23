import unittest

import numpy as np

from src.core.constants import standardize_metrics


class TestStandardizeMetrics(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(standardize_metrics(None), {})

    def test_keeps_existing_canonical(self):
        inp = {"n": 10, "FP_false_safe": 2, "FN_false_alarm": 1}
        out = standardize_metrics(inp)
        self.assertIn("n", out)
        self.assertIn("FP_false_safe", out)
        self.assertIn("FN_false_alarm", out)

    def test_rqd_invalid_direction_is_safe(self):
        from src.core.rqd_calculator import DirectionalRQDCalculator
        dfn = type("DFN", (), {"get_joints_intersecting_line": lambda *args, **kwargs: []})()
        calc = DirectionalRQDCalculator(dfn)
        result = calc.rqd_on_line(
            origin=np.array([0.0, 0.0, 0.0]),
            direction=np.array([0.0, 0.0, 0.0]),
            length=10.0,
            threshold=0.1,
            label="invalid",
        )
        self.assertEqual(result["n_intersections"], 0)
        self.assertEqual(result["rqd_direct"], 100.0)

    def test_invalid_powerlaw_defaults_are_safe(self):
        from src.core.joint_models import PowerLawSampler
        sampler = PowerLawSampler(alpha=0.0, r_min=0.0, r_max=0.5)
        self.assertGreater(sampler.alpha, 0.0)
        self.assertGreater(sampler.r_min, 0.0)
        self.assertGreater(sampler.r_max, sampler.r_min)


if __name__ == "__main__":
    unittest.main()
