import numpy as np
import pandas as pd

csv_path = "outputs/multicase_rqd/all_cases_face_rows.csv"
df = pd.read_csv(csv_path)

cols = [
    "lambda_borehole",
    "lambda_face_scanline",
    "borehole_n_intersections_total",
    "face_scanline_n_intersections",
    "Jv_face",
]

print("\n=== Available columns check ===")
for c in cols:
    print(c, c in df.columns)

print("\n=== Lambda / count summary ===")
print(
    df[cols].describe(
        percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]
    )
)

# apparent spacing = 1 / lambda
# lambda = 0이면 spacing은 infinity로 둔다.
df["spacing_borehole_apparent"] = np.where(
    df["lambda_borehole"] > 0,
    1.0 / df["lambda_borehole"],
    np.inf,
)

df["spacing_face_scanline_apparent"] = np.where(
    df["lambda_face_scanline"] > 0,
    1.0 / df["lambda_face_scanline"],
    np.inf,
)

print("\n=== Apparent spacing summary ===")
spacing_cols = [
    "spacing_borehole_apparent",
    "spacing_face_scanline_apparent",
]

print(
    df[spacing_cols].replace([np.inf, -np.inf], np.nan).describe(
        percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]
    )
)

print("\n=== Proportion of apparent spacing below 0.1 m ===")
print(
    "BH spacing < 0.1 m:",
    np.mean(df["spacing_borehole_apparent"] < 0.1),
)

print(
    "Face scanline spacing < 0.1 m:",
    np.mean(df["spacing_face_scanline_apparent"] < 0.1),
)

print("\n=== Proportion of lambda above 10 /m ===")
print(
    "BH lambda > 10 /m:",
    np.mean(df["lambda_borehole"] > 10.0),
)

print(
    "Face lambda > 10 /m:",
    np.mean(df["lambda_face_scanline"] > 10.0),
)