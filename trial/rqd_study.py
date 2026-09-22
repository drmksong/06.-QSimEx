import pandas as pd
from src.core.rqd_analysis import compare_rqd_methods

df = pd.read_csv("outputs/all_cases_face_rows.csv")

results = compare_rqd_methods(
    df,
    predictor_cols=[
        "RQD_borehole_direct",
        "RQD_borehole_hudson",
    ],
    target_cols=[
        "RQD_face_scanline",
        "RQD_face_jv",
        "RQD_face_conservative",
    ],
    thresholds=[50, 75, 90],
)

print(results["summary"])
print(results["pairwise"])
print(results["threshold"])