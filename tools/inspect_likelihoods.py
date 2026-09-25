"""LEGACY_DO_NOT_USE: 4.0-based likelihood inspection."""

import pandas as pd
from src.core.decision_test import DecisionUsefulnessTester

import glob

paths = glob.glob("outputs/test_multicase/by_case_pure/*/*_face_rows.csv")
paths = sorted(paths)
for p in paths:
    df = pd.read_csv(p)
    rows = df.to_dict(orient="records")
    tester = DecisionUsefulnessTester(rows)
    lik = tester.get_bayesian_likelihoods(bh_threshold=4.0, face_threshold=4.0)
    # print path and likelihood
    print(p)
    print("  sensitivity:", lik.sensitivity)
    print("  specificity:", lik.specificity)
