import glob
import os
import pandas as pd

BASE = "outputs/disposal_lowfract_curated/by_case_pure"
OUT = "outputs/disposal_lowfract_curated"


def collect(pattern: str) -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(BASE, "*", pattern))):
        case = os.path.basename(os.path.dirname(path))
        df = pd.read_csv(path)
        if "case_name" not in df.columns:
            df["case_name"] = case
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    face = collect("*_face_rows.csv")
    bore = collect("*_borehole_rows.csv")
    summ = collect("*_summary_rows.csv")

    if len(face):
        face.to_csv(os.path.join(OUT, "all_cases_face_rows.csv"), index=False)
    if len(bore):
        bore.to_csv(os.path.join(OUT, "all_cases_borehole_rows.csv"), index=False)
    if len(summ):
        summ.to_csv(os.path.join(OUT, "all_cases_summary_rows.csv"), index=False)

    print("combined_face_rows", len(face))
    print("combined_borehole_rows", len(bore))
    print("combined_summary_rows", len(summ))


if __name__ == "__main__":
    main()
