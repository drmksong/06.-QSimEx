"""
RQD 방법 비교 분석 유틸리티.

비교 대상 예:
1. RQD_borehole_direct
2. RQD_borehole_hudson
3. RQD_face_scanline
4. RQD_face_jv

주요 분석:
- 분포 요약
- pairwise error
- bias, MAE, RMSE, correlation
- overestimation / underestimation
- RQD threshold 기반 false-safe / false-alarm
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Sequence, Tuple
from src.core.constants import standardize_metrics


def _safe_numeric_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        raise KeyError(f"Missing column: {col}")

    return pd.to_numeric(df[col], errors="coerce")


def _safe_corr(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)

    if mask.sum() < 3:
        return np.nan

    x2 = x[mask]
    y2 = y[mask]

    if np.std(x2) == 0 or np.std(y2) == 0:
        return np.nan

    return float(np.corrcoef(x2, y2)[0, 1])


def summarize_rqd_columns(
    df: pd.DataFrame,
    cols: Sequence[str],
) -> pd.DataFrame:
    """
    RQD 컬럼들의 분포 요약.

    Returns
    -------
    pd.DataFrame
        column별 count, mean, std, min, p10, p25, p50, p75, p90, max
    """
    rows = []

    for col in cols:
        if col not in df.columns:
            rows.append(
                {
                    "column": col,
                    "exists": False,
                    "count": 0,
                    "mean": np.nan,
                    "std": np.nan,
                    "min": np.nan,
                    "p10": np.nan,
                    "p25": np.nan,
                    "p50": np.nan,
                    "p75": np.nan,
                    "p90": np.nan,
                    "max": np.nan,
                }
            )
            continue

        s = _safe_numeric_series(df, col).replace([np.inf, -np.inf], np.nan).dropna()

        if len(s) == 0:
            rows.append(
                {
                    "column": col,
                    "exists": True,
                    "count": 0,
                    "mean": np.nan,
                    "std": np.nan,
                    "min": np.nan,
                    "p10": np.nan,
                    "p25": np.nan,
                    "p50": np.nan,
                    "p75": np.nan,
                    "p90": np.nan,
                    "max": np.nan,
                }
            )
            continue

        rows.append(
            {
                "column": col,
                "exists": True,
                "count": int(len(s)),
                "mean": float(s.mean()),
                "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
                "min": float(s.min()),
                "p10": float(s.quantile(0.10)),
                "p25": float(s.quantile(0.25)),
                "p50": float(s.quantile(0.50)),
                "p75": float(s.quantile(0.75)),
                "p90": float(s.quantile(0.90)),
                "max": float(s.max()),
            }
        )

    return pd.DataFrame(rows)


def rqd_pairwise_metrics(
    df: pd.DataFrame,
    predictor_col: str,
    target_col: str,
) -> Dict[str, float]:
    """
    두 RQD 방법 간 기본 비교.

    predictor - target 기준으로 bias를 계산한다.

    diff > 0:
        predictor가 target보다 RQD를 높게 평가.
        borehole predictor라면 잠재적 overestimation.

    diff < 0:
        predictor가 target보다 RQD를 낮게 평가.
    """
    pred = _safe_numeric_series(df, predictor_col)
    target = _safe_numeric_series(df, target_col)

    sub = pd.DataFrame(
        {
            "pred": pred,
            "target": target,
        }
    ).replace([np.inf, -np.inf], np.nan).dropna()

    if len(sub) == 0:
        return {
            "predictor": predictor_col,
            "target": target_col,
            "n": 0,
            "pred_mean": np.nan,
            "target_mean": np.nan,
            "bias": np.nan,
            "mae": np.nan,
            "rmse": np.nan,
            "median_abs_error": np.nan,
            "corr": np.nan,
            "overestimation_rate": np.nan,
            "underestimation_rate": np.nan,
            "equal_rate": np.nan,
        }

    x = sub["pred"].values.astype(float)
    y = sub["target"].values.astype(float)

    diff = x - y
    abs_diff = np.abs(diff)

    return {
        "predictor": predictor_col,
        "target": target_col,
        "n": int(len(sub)),
        "pred_mean": float(np.mean(x)),
        "target_mean": float(np.mean(y)),
        "bias": float(np.mean(diff)),
        "mae": float(np.mean(abs_diff)),
        "rmse": float(np.sqrt(np.mean(diff ** 2))),
        "median_abs_error": float(np.median(abs_diff)),
        "corr": _safe_corr(x, y),
        "overestimation_rate": float(np.mean(diff > 0)),
        "underestimation_rate": float(np.mean(diff < 0)),
        "equal_rate": float(np.mean(diff == 0)),
    }


def rqd_threshold_metrics(
    df: pd.DataFrame,
    predictor_col: str,
    target_col: str,
    threshold: float,
    cost_false_safe: float = 10.0,
    cost_false_alarm: float = 1.0,
) -> Dict[str, float]:
    """
    RQD threshold 기반 decision metric.

    good 조건:
        RQD >= threshold

    false-safe:
        predictor는 good이라고 판단했지만 target은 bad.
        즉, pred_good=True, target_good=False

    false-alarm:
        predictor는 bad라고 판단했지만 target은 good.
        즉, pred_good=False, target_good=True
    """
    pred = _safe_numeric_series(df, predictor_col)
    target = _safe_numeric_series(df, target_col)

    sub = pd.DataFrame(
        {
            "pred": pred,
            "target": target,
        }
    ).replace([np.inf, -np.inf], np.nan).dropna()

    if len(sub) == 0:
        return standardize_metrics(
            {
                "predictor": predictor_col,
                "target": target_col,
                "threshold": float(threshold),
                "n": 0,
                "prior_target_good_rate": np.nan,
                "TP": 0,
                "FP_false_safe": 0,
                "FN_false_alarm": 0,
                "TN": 0,
                "accuracy": np.nan,
                "balanced_accuracy": np.nan,
                "false_safe_rate": np.nan,
                "false_alarm_rate": np.nan,
                "expected_cost": np.nan,
            }
        )

    x = sub["pred"].values.astype(float)
    y = sub["target"].values.astype(float)

    pred_good = x >= threshold
    target_good = y >= threshold

    TP = int(np.sum(pred_good & target_good))
    FP = int(np.sum(pred_good & ~target_good))  # false-safe
    FN = int(np.sum(~pred_good & target_good))  # false-alarm
    TN = int(np.sum(~pred_good & ~target_good))

    n = len(sub)
    n_good = TP + FN
    n_bad = FP + TN

    sensitivity = TP / n_good if n_good > 0 else np.nan
    specificity = TN / n_bad if n_bad > 0 else np.nan

    balanced_accuracy = np.nanmean([sensitivity, specificity])
    accuracy = (TP + TN) / n if n > 0 else np.nan

    false_safe_rate = FP / n_bad if n_bad > 0 else np.nan
    false_alarm_rate = FN / n_good if n_good > 0 else np.nan

    expected_cost = (cost_false_safe * FP + cost_false_alarm * FN) / n

    # return canonical keys where possible and keep legacy names for backward compatibility
    return standardize_metrics(
        {
            "predictor": predictor_col,
            "target": target_col,
            "threshold": float(threshold),
            "n": int(n),
            "prior_target_good_rate": float(np.mean(target_good)),
            "TP": TP,
            "FP_false_safe": FP,
            "FN_false_alarm": FN,
            "TN": TN,
            "accuracy": float(accuracy),
            "balanced_accuracy": float(balanced_accuracy),
            "false_safe_rate": float(false_safe_rate),
            "false_alarm_rate": float(false_alarm_rate),
            "expected_cost": float(expected_cost),
        }
    )


def compare_rqd_methods(
    df: pd.DataFrame,
    predictor_cols: Optional[Sequence[str]] = None,
    target_cols: Optional[Sequence[str]] = None,
    thresholds: Sequence[float] = (50.0, 75.0, 90.0),
    cost_false_safe: float = 10.0,
    cost_false_alarm: float = 1.0,
) -> Dict[str, pd.DataFrame]:
    """
    RQD 방법들을 일괄 비교한다.

    기본 predictor:
        - RQD_borehole_direct
        - RQD_borehole_hudson

    기본 target:
        - RQD_face_scanline
        - RQD_face_jv
        - RQD_face_conservative, 있으면 사용 가능

    Returns
    -------
    dict
        {
            "summary": ...,
            "pairwise": ...,
            "threshold": ...
        }
    """
    if predictor_cols is None:
        predictor_cols = [
            "RQD_borehole_direct",
            "RQD_borehole_hudson",
        ]

    if target_cols is None:
        target_cols = [
            "RQD_face_scanline",
            "RQD_face_jv",
            "RQD_face_conservative",
        ]

    all_cols = list(dict.fromkeys(list(predictor_cols) + list(target_cols)))

    summary = summarize_rqd_columns(df, all_cols)

    pairwise_rows = []
    threshold_rows = []

    for pred_col in predictor_cols:
        if pred_col not in df.columns:
            continue

        for target_col in target_cols:
            if target_col not in df.columns:
                continue

            pairwise_rows.append(
                rqd_pairwise_metrics(
                    df=df,
                    predictor_col=pred_col,
                    target_col=target_col,
                )
            )

            for th in thresholds:
                threshold_rows.append(
                    rqd_threshold_metrics(
                        df=df,
                        predictor_col=pred_col,
                        target_col=target_col,
                        threshold=th,
                        cost_false_safe=cost_false_safe,
                        cost_false_alarm=cost_false_alarm,
                    )
                )

    return {
        "summary": pd.DataFrame(summary),
        "pairwise": pd.DataFrame(pairwise_rows),
        "threshold": pd.DataFrame(threshold_rows),
    }


def compare_rqd_by_regime(
    df: pd.DataFrame,
    group_cols: Sequence[str],
    predictor_col: str,
    target_col: str,
) -> pd.DataFrame:
    """
    case, density regime, orientation regime 등 그룹별 RQD 오차 비교.

    예:
        compare_rqd_by_regime(
            df,
            group_cols=["case_name"],
            predictor_col="RQD_borehole_direct",
            target_col="RQD_face_scanline",
        )
    """
    missing = [c for c in group_cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing group columns: {missing}")

    rows = []

    for keys, sub in df.groupby(list(group_cols)):
        metrics = rqd_pairwise_metrics(
            df=sub,
            predictor_col=predictor_col,
            target_col=target_col,
        )

        if not isinstance(keys, tuple):
            keys = (keys,)

        for col, val in zip(group_cols, keys):
            metrics[col] = val

        rows.append(metrics)

    out = pd.DataFrame(rows)

    ordered_cols = list(group_cols) + [
        c for c in out.columns if c not in group_cols
    ]

    return out[ordered_cols]