"""
Decision-Analysis Framework: Usefulness tester for geotechnical indicators.

목적:
- 고전적 암질 지표(RQD, Q' 등)를 수정하지 않고, 이를 의사결정의 입력 자료로 활용함.
- ROC/AUC 분석, Decision Curve Analysis (Net Benefit)
- Cost-sensitive expected cost 계산
- DFN 시뮬레이션 데이터를 Bayesian Likelihood로 변환하여 프레임워크에 연결.
- 연구 기여: 암반 분류 지표의 '분류 성능'을 넘어 '경제적 의사결정 가치'를 정량화하는 프레임워크 제시.
"""

from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd
from scipy import integrate, stats
from .constants import standardize_metrics
"""LEGACY_DO_NOT_USE: provisional binary single-threshold analysis.

The explicit lower/upper cutoff pipeline must replace this module before its
classification or Bayesian helpers are used for research results.
"""

import logging

# sklearn imports moved into compute_roc_analysis to avoid module-level
# possibly-unbound warnings from static analyzers.

# scipy.integrate.trapz는 향후 삭제될 예정이므로 호환성 처리
if not hasattr(integrate, "trapezoid"):
    # scipy 1.10 미만 버전에서는 trapz를 사용하도록 호환성 확보
    integrate.trapezoid = getattr(integrate, "trapz", None)


class DecisionUsefulnessTester:
    def __init__(self, face_rows: List[Dict[str, Any]]):
        self.face_rows = face_rows or []

    # ------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------
    def _arr(self, key: str) -> np.ndarray:
        vals = []
        for r in self.face_rows:
            try:
                vals.append(float(r.get(key, np.nan)))
            except Exception:
                vals.append(np.nan)
        return np.array(vals, dtype=float)

    @staticmethod
    def _to_bool_array(x) -> np.ndarray:
        """Coerce input (list/Series/ndarray) to a numpy boolean array."""
        # pandas objects should be converted via to_numpy to avoid ExtensionArray issues
        try:
            import pandas as _pd

            if isinstance(x, (_pd.Series, _pd.Index)):
                return x.to_numpy(dtype=bool)
        except Exception:
            pass

        return np.asarray(x, dtype=bool)

    def _valid_mask(self, *arrays):
        mask = np.ones(len(arrays[0]), dtype=bool)
        for a in arrays:
            mask &= np.isfinite(a)
        return mask

    def _bin_by_quantile(self, x, q_low=0.25, q_high=0.75):
        valid = x[np.isfinite(x)]
        if len(valid) == 0:
            return np.full(len(x), "unknown", dtype=object), np.nan, np.nan

        lo = float(np.quantile(valid, q_low))
        hi = float(np.quantile(valid, q_high))

        labels = np.full(len(x), "mid", dtype=object)
        labels[x <= lo] = "low"
        labels[x >= hi] = "high"
        labels[~np.isfinite(x)] = "unknown"
        return labels, lo, hi

    # ------------------------------------------------------------
    # core metrics
    # ------------------------------------------------------------
    @staticmethod
    def confusion_metrics(
        y_true_good: np.ndarray, y_pred_good: np.ndarray
    ) -> Dict[str, Any]:
        """
        true = face condition
        pred = borehole decision

        TP: BH good, Face good
        FP: BH good, Face bad  = false-safe
        FN: BH bad,  Face good = false-alarm
        TN: BH bad,  Face bad

        주의: 처분장 맥락에서 'good'은 처분 적합(suitable),
             'bad'는 부적합(unsuitable)을 의미함.
        """
        y_true_good = DecisionUsefulnessTester._to_bool_array(y_true_good)
        y_pred_good = DecisionUsefulnessTester._to_bool_array(y_pred_good)

        tp = int(np.sum(y_pred_good & y_true_good))
        fp = int(np.sum(y_pred_good & ~y_true_good))
        fn = int(np.sum(~y_pred_good & y_true_good))
        tn = int(np.sum(~y_pred_good & ~y_true_good))
        n = tp + fp + fn + tn

        actual_good = tp + fn
        actual_bad = fp + tn
        pred_good = tp + fp
        pred_bad = fn + tn

        sensitivity = tp / actual_good if actual_good > 0 else np.nan
        specificity = tn / actual_bad if actual_bad > 0 else np.nan

        metrics = {
            "n": n,
            "TP_correct_excavate": tp,
            "FP_false_safe": fp,
            "FN_false_alarm": fn,
            "TN_correct_reject": tn,
            "actual_good": actual_good,
            "actual_bad": actual_bad,
            "pred_good": pred_good,
            "pred_bad": pred_bad,
            "accuracy": (tp + tn) / n if n > 0 else np.nan,
            "balanced_accuracy": np.nanmean([sensitivity, specificity]),
            "sensitivity_actual_good_detected": sensitivity,
            "specificity_actual_bad_detected": specificity,
            "false_safe_rate": fp / actual_bad if actual_bad > 0 else np.nan,
            "false_alarm_rate": fn / actual_good if actual_good > 0 else np.nan,
            "R_FS_pass": fp / pred_good if pred_good > 0 else np.nan,
            "R_FN_reject": fn / pred_bad if pred_bad > 0 else np.nan,
            "PPV_when_BH_good": tp / pred_good if pred_good > 0 else np.nan,
            "NPV_when_BH_bad": tn / pred_bad if pred_bad > 0 else np.nan,
            "TPR": sensitivity,
            "FPR": fp / actual_bad if actual_bad > 0 else np.nan,
            "FNR": (
                fn / actual_good if actual_good > 0 else np.nan
            ),  # False Negative Rate
            "precision": tp / pred_good if pred_good > 0 else np.nan,  # Precision (PPV)
        }

        # Ensure returned dict contains canonical metric keys as accepted across the codebase
        try:
            metrics = standardize_metrics(metrics)
        except Exception:
            pass

        return metrics

    # ------------------------------------------------------------
    # Layer 3 & 4: Explicit Labeling and Decision Logic
    # ------------------------------------------------------------
    @staticmethod
    def assign_reference_label(
        df: pd.DataFrame, reference_col: str = "Qp_face_mean", threshold: float = 4.0
    ) -> pd.DataFrame:
        """
        Layer 3: Reference Label Generator
        처분 적합/부적합을 정의하는 기준 라벨 생성.

        핵심은 reference label이 borehole score와 분리되어야 한다는 점이다.
        """
        df = df.copy()
        val = pd.to_numeric(df[reference_col], errors="coerce")
        df["reference_q"] = val
        df["suitable"] = np.where(val >= threshold, 1, 0)
        return df

    @staticmethod
    def assign_decision_score(
        df: pd.DataFrame, score_col: str = "Qp_borehole_mean"
    ) -> pd.DataFrame:
        """
        Layer 4: Decision Score Generator
        의사결정에 사용할 시추공 score 정의.

        이 값은 reference 라벨 계산과 분리되어야 하며,
        반드시 실제 시추공 관측값(score_col)만을 반영한다.
        """
        df = df.copy()
        df["decision_score"] = pd.to_numeric(df[score_col], errors="coerce")
        return df

    @staticmethod
    def prepare_decision_frame(
        df: pd.DataFrame,
        reference_col: str = "Qp_face_mean",
        score_col: str = "Qp_borehole_mean",
        threshold: float = 4.0,
    ) -> pd.DataFrame:
        """Reference label과 decision score를 명시적으로 분리해 준비한다."""
        df = df.copy()
        df = DecisionUsefulnessTester.assign_reference_label(
            df, reference_col=reference_col, threshold=threshold
        )
        df = DecisionUsefulnessTester.assign_decision_score(df, score_col=score_col)
        return df

    @classmethod
    def evaluate_threshold_decision(
        cls,
        df: pd.DataFrame,
        threshold: float,
        score_col: str = "decision_score",
        label_col: str = "suitable",
    ) -> Dict[str, Any]:
        """
        Layer 4/5: Decision Rule Evaluator
        특정 임계값에서의 굴착(Excavate) 여부를 결정하고 성능 지표 반환
        """
        # 유효 데이터 필터링
        valid_df = df.dropna(subset=[score_col, label_col])

        # convert to numpy arrays explicitly to avoid pandas extension-dtype issues
        y_true = valid_df[label_col].to_numpy(dtype=float)
        y_score_arr = valid_df[score_col].to_numpy(dtype=float)
        y_pred = np.where(y_score_arr >= threshold, 1, 0)

        metrics = cls.confusion_metrics(y_true, y_pred)
        # Normalize legacy/canonical metric names into canonical keys
        try:
            metrics = standardize_metrics(metrics)
        except Exception:
            logging.warning("standardize_metrics failed in confusion_metrics; returning raw metrics")
        metrics["threshold"] = threshold
        # FNR 계산 추가 (기존 confusion_metrics와 통합)
        metrics["FNR"] = metrics.get("FN_false_alarm", 0) / metrics.get(
            "actual_good", 1
        )

        return metrics

    @classmethod
    def compute_cost_curve(
        cls,
        df: pd.DataFrame,
        thresholds: List[float],
        score_col: str = "decision_score",
        label_col: str = "suitable",
        cost_fp: float = 1.0,
        cost_fn: float = 5.0,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Layer 6: Cost-sensitive Threshold Evaluation
        시추공 Q' 임계값별로 TP, FP, TN, FN 및 기대 비용을 계산하고 최적 임계값을 식별함.
        """
        rows = []
        for th in thresholds:
            metrics = cls.evaluate_threshold_decision(
                df, threshold=th, score_col=score_col, label_col=label_col
            )

            # ensure metric keys are standardized before cost computation
            metrics = standardize_metrics(metrics)

            n = metrics.get("n", 0)
            fp = metrics.get("FP_false_safe", 0)
            fn = metrics.get("FN_false_alarm", 0)

            # Expected Cost = (cost_fp * FP + cost_fn * FN) / N
            expected_cost = (cost_fp * fp + cost_fn * fn) / n if n > 0 else np.nan

            # Net Benefit (DCA) = (TP/N) - (FP/N) * (cost_fp / cost_fn)
            # 이는 '무조건 굴착' 전략 대비 얼마나 효율적인지 보여주는 DCA의 표준 공식입니다.
            nb = (
                (metrics.get("TP_correct_excavate", 0) / n)
                - (fp / n) * (cost_fp / cost_fn)
                if n > 0 and cost_fn > 0
                else np.nan
            )

            metrics.update(
                {
                    "cost_fp": cost_fp,
                    "cost_fn": cost_fn,
                    "cost_ratio_FP_to_FN": (
                        cost_fp / cost_fn if cost_fn != 0 else np.inf
                    ),
                    "expected_cost": expected_cost,
                    "net_benefit": nb,
                }
            )
            # finalize canonical naming
            metrics = standardize_metrics(metrics)
            rows.append(metrics)

        cost_df = pd.DataFrame(rows)

        if cost_df.empty or cost_df["expected_cost"].isnull().all():
            return cost_df, {}

        best_idx = cost_df["expected_cost"].idxmin()
        # normalize keys to str to satisfy static type checkers (Dict[str, Any])
        best_row = {str(k): v for k, v in cost_df.loc[best_idx].to_dict().items()}

        return cost_df, best_row

    @classmethod
    def compute_net_benefit_curve(
        cls,
        df: pd.DataFrame,
        thresholds: List[float],
        score_col: str = "decision_score",
        label_col: str = "suitable",
        fp_weight: float = 1.0,
    ) -> pd.DataFrame:
        """
        Layer 6: Decision Curve Analysis (DCA) - Net Benefit Curve
        비용 분석 기법(DCA)을 적용하여 시추공 Q' 임계값별 Net Benefit을 계산함.

        Net Benefit = (TP / N) - (FP / N) * w
        여기서 w(fp_weight)는 부적합 암반 굴착(FP)의 손실과 적합 암반 확보(TP)의 가치 비율임.
        """
        rows = []
        for th in thresholds:
            metrics = cls.evaluate_threshold_decision(
                df, threshold=th, score_col=score_col, label_col=label_col
            )

            n = metrics.get("n", 0)
            tp = metrics.get("TP_correct_excavate", 0)
            fp = metrics.get("FP_false_safe", 0)

            # Net Benefit 계산: (TP/N) - (FP/N) * weight
            nb = (tp / n) - (fp / n) * fp_weight if n > 0 else np.nan

            metrics.update({"fp_weight": fp_weight, "net_benefit": nb})
            rows.append(metrics)

        return pd.DataFrame(rows)

    @staticmethod
    def compute_roc_analysis(
        df: pd.DataFrame, score_col: str = "decision_score", label_col: str = "suitable"
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Layer 5/6: ROC Analysis
        Borehole Q'을 분류기로 보고 ROC 커브와 AUC를 계산함.
        """
        # import sklearn metrics here so static analyzers don't mark symbols as possibly unbound
        try:
            from sklearn.metrics import roc_curve, roc_auc_score
        except Exception:
            # sklearn이 없을 경우를 대비한 가벼운 에러 핸들링
            print("[ERROR] scikit-learn is not installed. ROC analysis skipped.")
            return pd.DataFrame(), {"auc": np.nan, "n": len(df)}

        # 유효 데이터 필터링 (결측치 제거)
        valid_df = df.dropna(subset=[score_col, label_col])
        if len(valid_df) == 0:
            return pd.DataFrame(), {"auc": np.nan, "n": 0}

        # explicit numpy conversion to avoid typechecker complaints with pandas ExtensionArray
        y_true = valid_df[label_col].to_numpy(dtype=float)
        y_score = valid_df[score_col].to_numpy(dtype=float)

        # ROC 계산을 위해서는 최소 2개의 클래스(0, 1)가 데이터에 존재해야 함
        if len(np.unique(y_true)) < 2:
            return pd.DataFrame(), {
                "auc": np.nan,
                "n": len(valid_df),
                "n_positive": int(y_true.sum()),
                "n_negative": int(len(y_true) - y_true.sum()),
            }

        fpr, tpr, thresholds = roc_curve(y_true, y_score)
        auc_value = roc_auc_score(y_true, y_score)

        roc_df = pd.DataFrame(
            {
                "threshold": thresholds,
                "FPR": fpr,
                "TPR": tpr,
                "sensitivity": tpr,
                "specificity": 1 - fpr,
            }
        )

        summary = {
            "auc": auc_value,
            "n": len(valid_df),
            "n_positive": int(y_true.sum()),
            "n_negative": int(len(y_true) - y_true.sum()),
        }

        return roc_df, summary

    def expected_cost(
        self,
        metrics: Dict[str, Any],
        cost_false_safe: float = 1.0,
        cost_false_alarm: float = 5.0,
    ) -> float:
        n = metrics.get("n", 0)
        if n <= 0:
            return np.nan
        return (
            cost_false_safe * metrics.get("FP_false_safe", 0)
            + cost_false_alarm * metrics.get("FN_false_alarm", 0)
        ) / n

    def net_benefit(self, metrics: Dict[str, Any], exchange_rate: float) -> float:
        """
        Decision Curve Analysis (DCA) 스타일의 Net Benefit.
        NB = (TP / N) - (FP / N) * exchange_rate
        여기서 exchange_rate는 FP(불필요한 굴착) 대비 FN(적합 암반 포기)의 가중치 비.
        """
        n = metrics.get("n", 0)
        if n <= 0:
            return np.nan
        tp = metrics.get("TP_correct_excavate", 0)
        fp = metrics.get("FP_false_safe", 0)
        return (tp / n) - (fp / n) * exchange_rate

    def calculate_auc(self, fpr: np.ndarray, tpr: np.ndarray) -> float:
        if len(fpr) < 2:
            return np.nan
        return float(integrate.trapezoid(tpr, fpr))

    def find_optimal_threshold(
        self, sweep_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        주어진 비용 구조에서 expected_cost를 최소화하는 최적 임계값을 찾음.
        """
        if not sweep_results:
            return {}
        valid_results = [r for r in sweep_results if np.isfinite(r["expected_cost"])]
        return (
            min(valid_results, key=lambda x: x["expected_cost"])
            if valid_results
            else {}
        )

    # ------------------------------------------------------------
    # one analysis
    # ------------------------------------------------------------
    def evaluate(
        self,
        threshold: float,
        use_qprime: bool = True,
        cost_false_safe: float = 1.0,
        cost_false_alarm: float = 5.0,
        rows: Optional[List[Dict[str, Any]]] = None,
        predictor_key: Optional[str] = None,
        target_key: Optional[str] = None,
    ) -> Dict[str, Any]:

        original_rows = self.face_rows
        if rows is not None:
            self.face_rows = rows

        # 컬럼 유연성 확보
        p_key = predictor_key or (
            "Qp_borehole_mean" if use_qprime else "Q_borehole_mean"
        )
        t_key = target_key or ("Qp_face_mean" if use_qprime else "Q_face_mean")

        face = self._arr(t_key)
        bh = self._arr(p_key)
        metric_name = p_key

        mask = self._valid_mask(face, bh)
        face = face[mask]
        bh = bh[mask]

        face_good = face >= threshold
        bh_good = bh >= threshold

        bh_metrics = self.confusion_metrics(face_good, bh_good)

        # baselines
        always_excavate = self.confusion_metrics(
            face_good, np.ones(len(face_good), dtype=bool)
        )
        always_reject = self.confusion_metrics(
            face_good, np.zeros(len(face_good), dtype=bool)
        )

        # DCA exchange rate (cost ratio 기반)
        # 보통 p_t / (1 - p_t)로 정의되나, 여기서는 비용 구조에서 직접 도출
        exchange_rate = (
            cost_false_alarm / cost_false_safe if cost_false_safe > 0 else 1.0
        )

        # majority baseline
        prior_good_rate = float(np.mean(face_good)) if len(face_good) else np.nan
        majority_pred = (
            np.ones(len(face_good), dtype=bool)
            if prior_good_rate >= 0.5
            else np.zeros(len(face_good), dtype=bool)
        )
        majority = self.confusion_metrics(face_good, majority_pred)

        for m in [bh_metrics, always_excavate, always_reject, majority]:
            m["expected_cost"] = self.expected_cost(
                m, cost_false_safe, cost_false_alarm
            )
            m["net_benefit"] = self.net_benefit(m, exchange_rate)

        # net benefit-like cost reduction
        bh_metrics["cost_reduction_vs_always_excavate"] = (
            always_excavate["expected_cost"] - bh_metrics["expected_cost"]
        )
        bh_metrics["cost_reduction_vs_majority"] = (
            majority["expected_cost"] - bh_metrics["expected_cost"]
        )

        out = {
            "metric": metric_name,
            "threshold": threshold,
            "cost_false_safe": cost_false_safe,
            "cost_false_alarm": cost_false_alarm,
            # provide canonical cost keys for downstream consumers
            "cost_fp": cost_false_safe,
            "cost_fn": cost_false_alarm,
            "prior_face_good_rate": prior_good_rate,
            "borehole_strategy": bh_metrics,
            "baseline_always_excavate": always_excavate,
            "baseline_always_reject": always_reject,
            "baseline_majority": majority,
        }

        # ensure canonical keys are present (safe normalization)
        try:
            out = standardize_metrics(out)
        except Exception:
            pass

        self.face_rows = original_rows
        return out

    # ------------------------------------------------------------
    # conditional / regime analysis
    # ------------------------------------------------------------
    def evaluate_by_regime(
        self,
        threshold: float,
        use_qprime: bool = True,
        cost_false_safe: float = 1.0,
        cost_false_alarm: float = 5.0,
    ) -> Dict[str, Any]:

        density = self._arr("face_fracture_density")
        orient = self._arr("orientation_bias_gap")

        density_bin, d_lo, d_hi = self._bin_by_quantile(density)
        orient_bin, o_lo, o_hi = self._bin_by_quantile(orient)

        results = {
            "density_thresholds": {"q25": d_lo, "q75": d_hi},
            "orientation_thresholds": {"q25": o_lo, "q75": o_hi},
            "by_density": {},
            "by_orientation": {},
            "by_density_orientation": {},
        }

        rows = np.array(self.face_rows, dtype=object)

        for label in ["low", "mid", "high"]:
            idx = density_bin == label
            if np.sum(idx) > 0:
                results["by_density"][label] = self.evaluate(
                    threshold,
                    use_qprime,
                    cost_false_safe,
                    cost_false_alarm,
                    rows=rows[idx].tolist(),
                )["borehole_strategy"]

        for label in ["low", "mid", "high"]:
            idx = orient_bin == label
            if np.sum(idx) > 0:
                results["by_orientation"][label] = self.evaluate(
                    threshold,
                    use_qprime,
                    cost_false_safe,
                    cost_false_alarm,
                    rows=rows[idx].tolist(),
                )["borehole_strategy"]

        for dlab in ["low", "mid", "high"]:
            for olab in ["low", "mid", "high"]:
                idx = (density_bin == dlab) & (orient_bin == olab)
                if np.sum(idx) > 0:
                    key = f"density={dlab},orientation={olab}"
                    results["by_density_orientation"][key] = self.evaluate(
                        threshold,
                        use_qprime,
                        cost_false_safe,
                        cost_false_alarm,
                        rows=rows[idx].tolist(),
                    )["borehole_strategy"]

        return results

    # ------------------------------------------------------------
    # threshold sweep
    # ------------------------------------------------------------
    def sweep_thresholds(
        self,
        thresholds: List[float],
        use_qprime: bool = True,
        cost_false_safe: float = 1.0,
        cost_false_alarm: float = 5.0,
        predictor_key: Optional[str] = None,
        target_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = []
        for t in thresholds:
            res = self.evaluate(
                threshold=t,
                use_qprime=use_qprime,
                cost_false_safe=cost_false_safe,
                cost_false_alarm=cost_false_alarm,
                predictor_key=predictor_key,
                target_key=target_key,
            )
            m = res["borehole_strategy"]
            rows.append(
                {
                    "threshold": t,
                    "n": m["n"],
                    "prior_face_good_rate": res["prior_face_good_rate"],
                    "accuracy": m["accuracy"],
                    "balanced_accuracy": m["balanced_accuracy"],
                    "false_safe_rate": m["false_safe_rate"],
                    "false_alarm_rate": m["false_alarm_rate"],
                    "TPR": m["TPR"],
                    "FPR": m["FPR"],
                    "FNR": m["FNR"],  # Added FNR
                    "precision": m["precision"],  # Added Precision
                    "PPV_when_BH_good": m["PPV_when_BH_good"],
                    "NPV_when_BH_bad": m["NPV_when_BH_bad"],
                    "expected_cost": m["expected_cost"],
                    "net_benefit": m["net_benefit"],
                    "cost_reduction_vs_always_excavate": m[
                        "cost_reduction_vs_always_excavate"
                    ],
                    "cost_reduction_vs_majority": m["cost_reduction_vs_majority"],
                }
            )
        return rows

    # ------------------------------------------------------------
    # Bayesian Utility
    # ------------------------------------------------------------
    def get_bayesian_likelihoods(
        self, bh_threshold: float, face_threshold: float
    ) -> Any:  # Returns LikelihoodConfig
        """
        Bayesian updating을 위한 Likelihood (P(BH_Result | Face_State)) 계산
        이 과정은 DFN 시뮬레이션 결과가 베이지안 모델의 파라미터로 전이되는 핵심 교량 역할을 함.
        """
        from .bayesian_update import LikelihoodConfig

        # Use Laplace (pseudocount) smoothing to avoid exact 0/1 likelihoods on small samples
        # Use a smaller pseudocount by default to avoid over-shrinking small-sample estimates
        alpha = 0.1
        eps = 1e-6

        face = self._arr("Qp_face_mean")
        bh = self._arr("Qp_borehole_mean")
        mask = self._valid_mask(face, bh)
        face, bh = face[mask], bh[mask]

        face_good = face >= face_threshold
        bh_good = bh >= bh_threshold

        # counts
        n_face_g = int(np.sum(face_good))
        n_face_b = int(np.sum(~face_good))
        tp = int(np.sum(bh_good & face_good))
        fp = int(np.sum(bh_good & ~face_good))

        # Laplace smoothing for sensitivity and false-positive rate
        sens = (
            (tp + alpha) / (n_face_g + 2.0 * alpha)
            if (n_face_g + 2.0 * alpha) > 0
            else 0.5
        )
        fpr = (
            (fp + alpha) / (n_face_b + 2.0 * alpha)
            if (n_face_b + 2.0 * alpha) > 0
            else 0.5
        )

        # numerical clamping to avoid exact 0/1
        sens = float(np.clip(sens, eps, 1.0 - eps))
        spec = float(np.clip(1.0 - fpr, eps, 1.0 - eps))

        return LikelihoodConfig(sensitivity=sens, specificity=spec)

    def predict_posteriors(
        self,
        prior: float,
        bh_values: np.ndarray,
        bh_threshold: float,
        likelihoods: Dict[str, float],
    ) -> np.ndarray:
        """
        시뮬레이션에서 얻은 Likelihood를 사용하여 실제 관측 데이터의 사후 확률을 계산합니다.
        """
        from .bayesian_update import bayesian_update_binary

        sens = likelihoods["sensitivity"]
        spec = likelihoods["specificity"]

        posteriors = []
        for val in bh_values:
            # 시추공 관측치를 binary class로 변환
            obs_class = 1 if val >= bh_threshold else 0

            post = bayesian_update_binary(
                prior_suitable=prior,
                observed_borehole_class=obs_class,
                sensitivity=sens,
                specificity=spec,
            )
            posteriors.append(post)

        return np.array(posteriors)

    def predict_decisions(
        self, posteriors: np.ndarray, cost_config: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        계산된 사후 확률 배열에 대해 베이지안 의사결정을 일괄 수행합니다.
        """
        from .bayesian_update import bayesian_decision_from_posterior, DecisionCost

        if cost_config is None:
            cost_config = DecisionCost()

        results = []
        for p in posteriors:
            if not np.isfinite(p):
                results.append(
                    {
                        "posterior_suitable": np.nan,
                        "p_threshold": np.nan,
                        "expected_loss_excavate": np.nan,
                        "expected_loss_skip": np.nan,
                        "decision": "unknown",
                    }
                )
            else:
                results.append(bayesian_decision_from_posterior(p, cost_config))

        return results

    def summarize_scenario_performance(
        self,
        scenario_id: str,
        reference_threshold: float = 4.0,
        cost_fp: float = 1.0,
        cost_fn: float = 5.0,
        score_col: str = "Qp_borehole_mean",
        reference_col: str = "Qp_face_mean",
    ) -> Dict[str, Any]:
        """
        DFN 시나리오별 연구/분석용 종합 지표를 산출합니다.
        DCA(Net Benefit)와 AUC를 결합하여 실무적 가치를 판정합니다.
        """
        df = pd.DataFrame(self.face_rows)
        df = self.assign_reference_label(df, reference_col, reference_threshold)
        df = self.assign_decision_score(df, score_col)

        # 1. AUC 계산
        roc_df, roc_summary = self.compute_roc_analysis(df)
        auc_val = roc_summary.get("auc", 0.0)

        # 2. Cost Sweep (Best Threshold 탐색)
        # Use a denser, padded sweep over the decision_score range to avoid edge-only minima
        scores = df["decision_score"].dropna()
        if scores.nunique() < 2:
            center = float(scores.mean()) if len(scores) else 4.0
            sweep_thresholds = np.linspace(center - 1.0, center + 1.0, 40)
        else:
            lo = float(scores.min())
            hi = float(scores.max())
            pad = max(1.0, 0.05 * (hi - lo))
            sweep_thresholds = np.linspace(lo - pad, hi + pad, 100)
        sweep_thresholds = np.unique(sweep_thresholds)
        cost_df, best_row = self.compute_cost_curve(
            df, list(sweep_thresholds), cost_fp=cost_fp, cost_fn=cost_fn
        )

        # 3. DCA Baseline 비교 (Always Excavate)
        # 모든 부지를 다 뚫었을 때의 Net Benefit과 비교하여 이 모델의 '순수한 기여도'를 확인
        prior_good = float(df["suitable"].mean()) if len(df) > 0 else 0.0
        baseline_nb = (
            prior_good - (1.0 - prior_good) * (cost_fp / cost_fn)
            if cost_fn > 0
            else 0.0
        )
        model_nb = best_row.get("net_benefit", -1.0)
        nb_improvement = model_nb - max(0, baseline_nb)  # 0은 '아무것도 안 함' 기준

        # 4. Recommendation 로직 (AUC 및 Net Benefit Improvement 기반)
        if auc_val > 0.85:
            recommendation = "use"
        elif auc_val > 0.70:
            recommendation = "use with caution"
        else:
            recommendation = "do not use"

        # 모델을 쓰는 것이 베이스라인보다 이득이 없으면 'do not use'
        if nb_improvement <= 0:
            recommendation = "do not use"

        # 5. 물리적/지질학적 메타데이터 (Context 추출)
        avg_density = np.nanmean(self._arr("face_fracture_density"))
        avg_gap = np.nanmean(self._arr("orientation_bias_gap"))

        return {
            "scenario_id": scenario_id,
            "joint_frequency": float(avg_density),
            "orientation_case": float(avg_gap),
            "borehole_direction": "[1, 0, 0] (tunnel axis)",
            "face_direction": "[0, 1, 0] (horizontal scan)",
            "reference_col": reference_col,
            "score_col": score_col,
            "reference_threshold": reference_threshold,
            "auc": float(auc_val),
            "best_threshold": float(best_row.get("threshold", np.nan)),
            "min_expected_cost": float(best_row.get("expected_cost", np.nan)),
            "sensitivity_at_best": float(
                best_row.get("sensitivity_actual_good_detected", np.nan)
            ),
            "specificity_at_best": float(
                best_row.get("specificity_actual_bad_detected", np.nan)
            ),
            "FP_rate_at_best": float(best_row.get("FPR", np.nan)),
            "FN_rate_at_best": float(best_row.get("FNR", np.nan)),
            "recommendation": recommendation,
            # DCA 지표: 이 모델을 사용함으로써 얻는 추가적인 부지 가치 이득
            "net_benefit_at_best": float(model_nb),
            "net_benefit_improvement": float(nb_improvement),
            "n_samples": int(best_row.get("n", 0)),
        }

    # ------------------------------------------------------------
    # print
    # ------------------------------------------------------------
    def print_summary(self, res: Dict[str, Any]):
        b = res["borehole_strategy"]
        ae = res["baseline_always_excavate"]
        ar = res["baseline_always_reject"]
        maj = res["baseline_majority"]

        print("\n" + "=" * 90)
        print("Decision Usefulness Test")
        print("=" * 90)
        print(f"metric={res['metric']}, threshold={res['threshold']}")
        print(f"prior face good rate={res['prior_face_good_rate']:.3f}")
        print(
            f"cost false-safe={res['cost_false_safe']}, false-alarm={res['cost_false_alarm']}"
        )

        print("\n[Borehole strategy]")
        print(f"  n={b['n']}")
        print(
            f"  TP={b['TP_correct_excavate']}, FP(false-safe)={b['FP_false_safe']}, "
            f"FN(false-alarm)={b['FN_false_alarm']}, TN={b['TN_correct_reject']}"
        )
        print(
            f"  accuracy={b['accuracy']:.3f}, balanced_accuracy={b['balanced_accuracy']:.3f}"
        )
        print(f"  false_safe_rate={b['false_safe_rate']:.3f}")
        print(f"  false_alarm_rate={b['false_alarm_rate']:.3f}")
        print(f"  PPV_when_BH_good={b['PPV_when_BH_good']:.3f}")
        print(f"  NPV_when_BH_bad={b['NPV_when_BH_bad']:.3f}")
        print(f"  expected_cost={b['expected_cost']:.3f}")
        print(
            f"  cost reduction vs always excavate={b['cost_reduction_vs_always_excavate']:.3f}"
        )
        print(f"  cost reduction vs majority={b['cost_reduction_vs_majority']:.3f}")

        print("\n[Baselines expected cost]")
        print(f"  always excavate: {ae['expected_cost']:.3f}")
        print(f"  always reject   : {ar['expected_cost']:.3f}")
        print(f"  majority        : {maj['expected_cost']:.3f}")
        print("=" * 90)
