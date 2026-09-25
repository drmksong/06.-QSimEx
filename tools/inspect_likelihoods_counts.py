"""LEGACY_DO_NOT_USE: 4.0-based likelihood count inspection."""

import pandas as pd
import glob

paths = sorted(glob.glob("outputs/test_multicase/by_case_pure/*/*_face_rows.csv"))
for p in paths:
    df = pd.read_csv(p)
    face = pd.to_numeric(df["Qp_face_mean"], errors="coerce")
    bh = pd.to_numeric(df["Qp_borehole_mean"], errors="coerce")
    mask = face.notna() & bh.notna()
    face = face[mask]
    bh = bh[mask]
    face_good = face >= 4.0
    bh_good = bh >= 4.0
    n_face_g = int(face_good.sum())
    n_face_b = int(len(face_good) - n_face_g)
    tp = int(((face_good) & (bh_good)).sum())
    fp = int((~face_good & bh_good).sum())
    print(p)
    print("  n_face_g", n_face_g, "n_face_b", n_face_b, "tp", tp, "fp", fp)
    print("  first 10 face:", face.head(10).tolist())
    print("  first 10 bh  :", bh.head(10).tolist())
    print("")
