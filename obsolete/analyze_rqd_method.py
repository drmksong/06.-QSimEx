"""
RQD method analysis CLI.

이 스크립트는 all_cases_face_rows.csv를 읽어서
다음 RQD 방법들을 비교한다.

Predictors:
    - RQD_borehole_direct
    - RQD_borehole_hudson

Face references:
    - RQD_face_scanline
    - RQD_face_jv
    - RQD_face_conservative

Outputs:
    - rqd_summary.csv
    - rqd_pairwise.csv
    - rqd_threshold_metrics.csv
    - rqd_threshold_sweep.csv
    - rqd_by_case.csv
    - rqd_by_density_regime.csv, 가능한 경우
    - rqd_by_orientation_regime.csv, 가능한 경우
"""

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.rqd_analysis import (
    compare_rqd_methods,
    compare_rqd_by_regime,
    rqd_threshold_metrics,
)


REQUIRED_COLUMNS = [
    "RQD_borehole_direct",
    "RQD_borehole_hudson",
    "RQD_face_scanline",
    "RQD_face_jv",
]


def _ensure_output_dir(out_dir: str) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    return out_path


def _check_columns(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]

    if missing:
        print("\n[ERROR] Missing required RQD columns:")
        for c in missing:
            print(f"  - {c}")

        print("\n현재 CSV 컬럼:")
        for c in df.columns:
            print(f"  - {c}")

        raise KeyError(
            "Required RQD columns are missing. "
            "Check tunnel.py and comparison.py export logic."
        )


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 숫자형 변환
    numeric_cols = [
        "RQD_borehole_direct",
        "RQD_borehole_hudson",
        "RQD_face_scanline",
        "RQD_face_jv",
        "RQD_face_conservative",
        "lambda_borehole",
        "lambda_face_scanline",
        "Jv_face",
        "face_fracture_density",
        "orientation_bias_gap",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # conservative 컬럼이 없으면 생성
    if "RQD_face_conservative" not in df.columns:
        if "RQD_face_scanline" in df.columns and "RQD_face_jv" in df.columns:
            df["RQD_face_conservative"] = np.minimum(
                df["RQD_face_scanline"],
                df["RQD_face_jv"],
            )

    return df


def _make_quantile_regime(
    df: pd.DataFrame,
    source_col: str,
    out_col: str,
    labels=("low", "mid", "high"),
) -> pd.DataFrame:
    """
    source_col을 분위수 기준으로 low/mid/high regime으로 나눈다.
    값이 충분하지 않으면 생성하지 않는다.
    """
    df = df.copy()

    if source_col not in df.columns:
        return df

    s = pd.to_numeric(df[source_col], errors="coerce")
    valid = s.replace([np.inf, -np.inf], np.nan).dropna()

    if len(valid) < 10:
        return df

    if valid.nunique() < 3:
        return df

    try:
        df[out_col] = pd.qcut(
            s,
            q=3,
            labels=labels,
            duplicates="drop",
        )
    except Exception:
        return df

    return df


def _run_threshold_sweep(
    df: pd.DataFrame,
    predictor_cols,
    target_cols,
    thresholds,
    cost_false_safe=10.0,
    cost_false_alarm=1.0,
) -> pd.DataFrame:
    rows = []

    for pred in predictor_cols:
        if pred not in df.columns:
            continue

        for target in target_cols:
            if target not in df.columns:
                continue

            for th in thresholds:
                rows.append(
                    rqd_threshold_metrics(
                        df=df,
                        predictor_col=pred,
                        target_col=target,
                        threshold=float(th),
                        cost_false_safe=cost_false_safe,
                        cost_false_alarm=cost_false_alarm,
                    )
                )

    return pd.DataFrame(rows)


def _canonicalize_threshold_df(df: pd.DataFrame) -> pd.DataFrame:
    """Map legacy metric column names in threshold DataFrame to canonical names if present."""
    from src.core.constants import CANONICAL

    if df is None or df.empty:
        return df

    # create a copy to avoid mutating caller
    out = df.copy()
    # rename columns if legacy keys found
    rename_map = {}
    for canon_key, canon_col in CANONICAL.items():
        # CANONICAL maps short keys to canonical column names (e.g. 'FP' -> 'FP_false_safe')
        # If the DF contains the canonical column we leave it; if it contains the short key, map it.
        if canon_key in out.columns and canon_col not in out.columns:
            rename_map[canon_key] = canon_col

    if rename_map:
        out = out.rename(columns=rename_map)

    return out


def _run_by_case_analysis(df: pd.DataFrame, out_path: Path):
    """
    case별 핵심 pairwise 분석.
    """
    if "case_name" not in df.columns:
        print("[WARN] case_name column not found. Skip by-case analysis.")
        return

    pairs = [
        ("RQD_borehole_direct", "RQD_face_scanline"),
        ("RQD_borehole_hudson", "RQD_face_scanline"),
        ("RQD_borehole_direct", "RQD_face_jv"),
        ("RQD_borehole_hudson", "RQD_face_jv"),
        ("RQD_borehole_direct", "RQD_face_conservative"),
        ("RQD_borehole_hudson", "RQD_face_conservative"),
    ]

    all_rows = []

    for pred, target in pairs:
        if pred not in df.columns or target not in df.columns:
            continue

        res = compare_rqd_by_regime(
            df=df,
            group_cols=["case_name"],
            predictor_col=pred,
            target_col=target,
        )
        all_rows.append(res)

    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)
        out.to_csv(out_path / "rqd_by_case.csv", index=False)
        print(f"[OK] Saved: {out_path / 'rqd_by_case.csv'}")


def _run_regime_analysis(df: pd.DataFrame, out_path: Path):
    """
    density/orientation regime별 분석.

    현재 별도 orientation tendency는 채택하지 않았으므로,
    기존에 CSV에 있는 face_fracture_density, orientation_bias_gap만 사용한다.
    """
    df2 = df.copy()

    df2 = _make_quantile_regime(
        df2,
        source_col="face_fracture_density",
        out_col="density_regime",
        labels=("low_density", "mid_density", "high_density"),
    )

    df2 = _make_quantile_regime(
        df2,
        source_col="orientation_bias_gap",
        out_col="orientation_gap_regime",
        labels=("low_gap", "mid_gap", "high_gap"),
    )

    pairs = [
        ("RQD_borehole_direct", "RQD_face_scanline"),
        ("RQD_borehole_hudson", "RQD_face_scanline"),
        ("RQD_borehole_direct", "RQD_face_jv"),
        ("RQD_borehole_hudson", "RQD_face_jv"),
    ]

    if "density_regime" in df2.columns:
        density_rows = []

        for pred, target in pairs:
            if pred not in df2.columns or target not in df2.columns:
                continue

            res = compare_rqd_by_regime(
                df=df2,
                group_cols=["density_regime"],
                predictor_col=pred,
                target_col=target,
            )
            density_rows.append(res)

        if density_rows:
            out = pd.concat(density_rows, ignore_index=True)
            out.to_csv(out_path / "rqd_by_density_regime.csv", index=False)
            print(f"[OK] Saved: {out_path / 'rqd_by_density_regime.csv'}")

    if "orientation_gap_regime" in df2.columns:
        orientation_rows = []

        for pred, target in pairs:
            if pred not in df2.columns or target not in df2.columns:
                continue

            res = compare_rqd_by_regime(
                df=df2,
                group_cols=["orientation_gap_regime"],
                predictor_col=pred,
                target_col=target,
            )
            orientation_rows.append(res)

        if orientation_rows:
            out = pd.concat(orientation_rows, ignore_index=True)
            out.to_csv(out_path / "rqd_by_orientation_regime.csv", index=False)
            print(f"[OK] Saved: {out_path / 'rqd_by_orientation_regime.csv'}")


def _print_key_results(summary_df: pd.DataFrame, pairwise_df: pd.DataFrame):
    print("\n" + "=" * 100)
    print("RQD METHOD SUMMARY")
    print("=" * 100)

    if len(summary_df) > 0:
        cols = [
            "column",
            "count",
            "mean",
            "std",
            "min",
            "p10",
            "p25",
            "p50",
            "p75",
            "p90",
            "max",
        ]
        cols = [c for c in cols if c in summary_df.columns]
        print(summary_df[cols].to_string(index=False))

    print("\n" + "=" * 100)
    print("RQD PAIRWISE COMPARISON")
    print("=" * 100)

    if len(pairwise_df) > 0:
        cols = [
            "predictor",
            "target",
            "n",
            "pred_mean",
            "target_mean",
            "bias",
            "mae",
            "rmse",
            "corr",
            "overestimation_rate",
            "underestimation_rate",
        ]
        cols = [c for c in cols if c in pairwise_df.columns]
        print(pairwise_df[cols].to_string(index=False))


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--csv",
        type=str,
        required=True,
        help="Path to all_cases_face_rows.csv",
    )

    parser.add_argument(
        "--out",
        type=str,
        default="legacy_results/outputs/rqd_analysis",
        help="Output directory for RQD analysis results",
    )

    parser.add_argument(
        "--thresholds",
        type=float,
        nargs="*",
        default=[50.0, 75.0, 90.0],
        help="RQD thresholds for decision metrics",
    )

    parser.add_argument(
        "--cost-false-safe",
        type=float,
        default=10.0,
        help="Cost assigned to false-safe error",
    )

    parser.add_argument(
        "--cost-false-alarm",
        type=float,
        default=1.0,
        help="Cost assigned to false-alarm error",
    )

    args = parser.parse_args()

    out_path = _ensure_output_dir(args.out)

    print(f"[INFO] Loading CSV: {args.csv}")
    df = pd.read_csv(args.csv)

    df = _prepare_dataframe(df)
    _check_columns(df)

    predictor_cols = [
        "RQD_borehole_direct",
        "RQD_borehole_hudson",
    ]

    target_cols = [
        "RQD_face_scanline",
        "RQD_face_jv",
        "RQD_face_conservative",
    ]

    # 존재하는 target만 사용
    target_cols = [c for c in target_cols if c in df.columns]

    results = compare_rqd_methods(
        df=df,
        predictor_cols=predictor_cols,
        target_cols=target_cols,
        thresholds=args.thresholds,
        cost_false_safe=args.cost_false_safe,
        cost_false_alarm=args.cost_false_alarm,
    )

    summary_df = results["summary"]
    pairwise_df = results["pairwise"]
    threshold_df = results["threshold"]

    summary_df.to_csv(out_path / "rqd_summary.csv", index=False)
    pairwise_df.to_csv(out_path / "rqd_pairwise.csv", index=False)
    # canonicalize threshold metrics column names before saving
    threshold_df = _canonicalize_threshold_df(threshold_df)
    threshold_df.to_csv(out_path / "rqd_threshold_metrics.csv", index=False)

    print(f"[OK] Saved: {out_path / 'rqd_summary.csv'}")
    print(f"[OK] Saved: {out_path / 'rqd_pairwise.csv'}")
    print(f"[OK] Saved: {out_path / 'rqd_threshold_metrics.csv'}")

    # Threshold sweep
    sweep_thresholds = np.arange(10.0, 100.1, 5.0)

    sweep_df = _run_threshold_sweep(
        df=df,
        predictor_cols=predictor_cols,
        target_cols=target_cols,
        thresholds=sweep_thresholds,
        cost_false_safe=args.cost_false_safe,
        cost_false_alarm=args.cost_false_alarm,
    )

    # canonicalize sweep results columns as well
    sweep_df = _canonicalize_threshold_df(sweep_df)
    sweep_df.to_csv(out_path / "rqd_threshold_sweep.csv", index=False)
    print(f"[OK] Saved: {out_path / 'rqd_threshold_sweep.csv'}")

    # Group analyses
    _run_by_case_analysis(df, out_path)
    _run_regime_analysis(df, out_path)

    _print_key_results(summary_df, pairwise_df)

    print("\n[DONE] RQD analysis completed.")
    print(f"Output directory: {out_path}")


if __name__ == "__main__":
    main()