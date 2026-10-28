"""LEGACY_DO_NOT_USE: provisional 4.0-based partial-run analysis."""

import glob
import os
import pandas as pd

BASE = "outputs/disposal_lowfract_curated/by_case_pure"


def main() -> None:
    case_rows = []
    all_face = []

    for case_dir in sorted(glob.glob(os.path.join(BASE, "*"))):
        case = os.path.basename(case_dir)
        summary_path = os.path.join(case_dir, f"{case}_summary_rows.csv")
        face_path = os.path.join(case_dir, f"{case}_face_rows.csv")

        if not os.path.exists(summary_path):
            continue

        ds = pd.read_csv(summary_path)
        row = {
            "case": case,
            "n_summary": int(len(ds)),
            "Qp_corr_mean": float(ds["Qp_correlation"].mean()) if "Qp_correlation" in ds else None,
            "Qp_ratio_mean": float(ds["Qp_ratio_mean"].mean()) if "Qp_ratio_mean" in ds else None,
            "Qp_match_normal_mean": float(ds["Qp_match_normal"].mean()) if "Qp_match_normal" in ds else None,
            "Qp_match_loose_mean": float(ds["Qp_match_loose"].mean()) if "Qp_match_loose" in ds else None,
            "RQD_bh_direct_mean": float(ds["diagnostic_bh_rqd_direct_mean"].mean()) if "diagnostic_bh_rqd_direct_mean" in ds else None,
            "RQD_face_scan_mean": float(ds["diagnostic_face_rqd_scanline_mean"].mean()) if "diagnostic_face_rqd_scanline_mean" in ds else None,
        }

        if os.path.exists(face_path):
            df = pd.read_csv(face_path)
            df["case_name"] = case
            all_face.append(df)

            row["face_rows"] = int(len(df))
            row["corr_facelevel"] = float(df["Qp_borehole_mean"].corr(df["Qp_face_mean"]))

            th = 4.0
            bh = df["Qp_borehole_mean"] >= th
            fc = df["Qp_face_mean"] >= th
            row["tp"] = int((bh & fc).sum())
            row["fp"] = int((bh & ~fc).sum())
            row["fn"] = int((~bh & fc).sum())
            row["tn"] = int((~bh & ~fc).sum())

        case_rows.append(row)

    out = pd.DataFrame(case_rows)
    if out.empty:
        print("No completed case outputs found.")
        return

    print("[Per-case summary]\n")
    print(out.to_string(index=False))

    print("\n[Overall mean over completed cases]")
    for col in [
        "Qp_corr_mean",
        "Qp_ratio_mean",
        "Qp_match_normal_mean",
        "Qp_match_loose_mean",
        "RQD_bh_direct_mean",
        "RQD_face_scan_mean",
        "corr_facelevel",
    ]:
        if col in out:
            print(f"{col}: {out[col].mean():.6f}")

    if all_face:
        allf = pd.concat(all_face, ignore_index=True)
        bins = pd.qcut(allf["Qp_borehole_mean"], q=5, duplicates="drop")
        cond = allf.groupby(bins, observed=False)["Qp_face_mean"].agg(["count", "mean", "std", "median"])

        print("\n[Qp_face | binned Qp_borehole over completed cases]")
        print(cond.to_string())
        print(f"\nPearson corr (face-level overall): {allf['Qp_borehole_mean'].corr(allf['Qp_face_mean']):.6f}")


if __name__ == "__main__":
    main()
