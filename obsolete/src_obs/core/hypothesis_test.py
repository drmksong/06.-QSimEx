"""
Monte Carlo batch 결과 기반 가설 검정 모듈

입력:
- face_rows: List[Dict]
- summary_rows: List[Dict] (optional)

가설:
H1: borehole Q'은 face Q'을 정확히 대표하지 않는다.
H2: 절리 밀도가 증가할수록 borehole-face Q' 일치도는 향상된다.
H3: 희소 절리망에서는 missed fracture 영향으로 discrepancy가 커진다.
H4: density 효과는 orientation에 의해 조절된다.
H5: 희소 + 불리한 방향 조건에서 borehole Q'의 체계적 과대평가가 발생한다.
"""

from typing import List, Dict, Any, Optional
import numpy as np

try:
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class BatchHypothesisTester:
    def __init__(self,
                 face_rows: List[Dict[str, Any]],
                 summary_rows: Optional[List[Dict[str, Any]]] = None):
        self.face_rows = face_rows or []
        self.summary_rows = summary_rows or []

    # ============================================================
    # basic helpers
    # ============================================================
    def _get_array(self, rows: List[Dict[str, Any]], key: str) -> np.ndarray:
        vals = []
        for r in rows:
            v = r.get(key, None)
            if v is None:
                vals.append(np.nan)
            else:
                try:
                    vals.append(float(v))
                except Exception:
                    vals.append(np.nan)
        return np.array(vals, dtype=float)

    def _valid(self, *arrays):
        if not arrays:
            return tuple()
        mask = np.ones(len(arrays[0]), dtype=bool)
        for arr in arrays:
            mask &= np.isfinite(arr)
        return tuple(arr[mask] for arr in arrays)

    def _one_sample_ttest(self, x: np.ndarray, mu: float = 0.0,
                          alternative: str = "two-sided") -> Dict[str, Any]:
        x = x[np.isfinite(x)]
        n = len(x)
        if n < 2:
            return {"n": n, "mean": np.nan, "sd": np.nan, "t": np.nan, "p": np.nan}

        mean = float(np.mean(x))
        sd = float(np.std(x, ddof=1)) if n > 1 else 0.0

        if sd <= 0:
            return {"n": n, "mean": mean, "sd": sd, "t": np.nan, "p": np.nan}

        t = (mean - mu) / (sd / np.sqrt(n))

        p = np.nan
        if SCIPY_AVAILABLE:
            df = n - 1
            if alternative == "two-sided":
                p = float(2 * stats.t.sf(abs(t), df=df))
            elif alternative == "greater":
                p = float(stats.t.sf(t, df=df))
            elif alternative == "less":
                p = float(stats.t.cdf(t, df=df))

        return {"n": n, "mean": mean, "sd": sd, "t": float(t), "p": p}

    def _welch_ttest(self, x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
        x = x[np.isfinite(x)]
        y = y[np.isfinite(y)]

        if len(x) < 2 or len(y) < 2:
            return {
                "n1": len(x), "n2": len(y),
                "mean1": np.nan, "mean2": np.nan,
                "t": np.nan, "p": np.nan
            }

        mean1, mean2 = float(np.mean(x)), float(np.mean(y))
        out = {
            "n1": len(x), "n2": len(y),
            "mean1": mean1, "mean2": mean2,
            "t": np.nan, "p": np.nan
        }

        if SCIPY_AVAILABLE:
            res = stats.ttest_ind(x, y, equal_var=False)
            out["t"] = float(res.statistic)
            out["p"] = float(res.pvalue)

        return out

    def _spearman(self, x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
        x, y = self._valid(x, y)
        if len(x) < 3:
            return {"n": len(x), "rho": np.nan, "p": np.nan}

        if SCIPY_AVAILABLE:
            rho, p = stats.spearmanr(x, y)
            return {"n": len(x), "rho": float(rho), "p": float(p)}

        # scipy 없으면 rank corr 미제공
        return {"n": len(x), "rho": np.nan, "p": np.nan}

    def _safe_corr(self, x: np.ndarray, y: np.ndarray) -> float:
        """Return Pearson correlation or np.nan if undefined (zero-variance)."""
        try:
            xv, yv = self._valid(x, y)
        except Exception:
            return float('nan')
        if len(xv) == 0:
            return float('nan')
        # if either has zero variance, correlation undefined
        if np.nanstd(xv) == 0 or np.nanstd(yv) == 0:
            return float('nan')
        try:
            return float(np.corrcoef(xv, yv)[0, 1])
        except Exception:
            return float('nan')

    def _linear_regression(self, x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
        x, y = self._valid(x, y)
        n = len(x)

        if n < 3:
            return {
                "n": n,
                "intercept": np.nan,
                "slope": np.nan,
                "r2": np.nan,
                "t_slope": np.nan,
                "p": np.nan
            }

        x_mean = np.mean(x)
        y_mean = np.mean(y)

        sxx = np.sum((x - x_mean) ** 2)
        sxy = np.sum((x - x_mean) * (y - y_mean))
        syy = np.sum((y - y_mean) ** 2)

        if sxx <= 0:
            return {
                "n": n,
                "intercept": float(y_mean),
                "slope": np.nan,
                "r2": np.nan,
                "t_slope": np.nan,
                "p": np.nan
            }

        slope = sxy / sxx
        intercept = y_mean - slope * x_mean

        yhat = intercept + slope * x
        resid = y - yhat
        ss_res = np.sum(resid ** 2)
        r2 = 1.0 - ss_res / syy if syy > 0 else np.nan

        dof = n - 2
        t_slope = np.nan
        p = np.nan

        if dof > 0:
            mse = ss_res / dof
            se_slope = np.sqrt(mse / sxx) if sxx > 0 else np.nan
            if np.isfinite(se_slope) and se_slope > 0:
                t_slope = slope / se_slope
                if SCIPY_AVAILABLE:
                    p = float(2 * stats.t.sf(abs(t_slope), df=dof))

        return {
            "n": n,
            "intercept": float(intercept),
            "slope": float(slope),
            "r2": float(r2) if np.isfinite(r2) else np.nan,
            "t_slope": float(t_slope) if np.isfinite(t_slope) else np.nan,
            "p": p
        }

    def _multiple_regression(self,
                             y: np.ndarray,
                             x_cols: List[np.ndarray],
                             coef_names: List[str]) -> Dict[str, Any]:
        arrays = [y] + x_cols
        mask = np.ones(len(y), dtype=bool)
        for arr in arrays:
            mask &= np.isfinite(arr)

        yv = y[mask]
        xv = [arr[mask] for arr in x_cols]
        n = len(yv)

        if n < len(x_cols) + 3:
            return {
                "n": n,
                "coef_names": ["intercept"] + coef_names,
                "beta": [np.nan] * (len(x_cols) + 1),
                "p": [np.nan] * (len(x_cols) + 1),
                "r2": np.nan
            }

        X = np.column_stack([np.ones(n)] + xv)

        try:
            beta = np.linalg.lstsq(X, yv, rcond=None)[0]
            yhat = X @ beta
            resid = yv - yhat

            ss_res = np.sum(resid ** 2)
            ss_tot = np.sum((yv - np.mean(yv)) ** 2)
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

            dof = n - X.shape[1]
            pvals = np.full(X.shape[1], np.nan, dtype=float)

            if dof > 0:
                mse = ss_res / dof
                xtx_inv = np.linalg.inv(X.T @ X)
                se = np.sqrt(np.diag(mse * xtx_inv))
                tvals = beta / se
                if SCIPY_AVAILABLE:
                    pvals = 2 * stats.t.sf(np.abs(tvals), df=dof)

            return {
                "n": n,
                "coef_names": ["intercept"] + coef_names,
                "beta": [float(v) for v in beta],
                "p": [float(v) for v in pvals],
                "r2": float(r2) if np.isfinite(r2) else np.nan
            }
        except Exception:
            return {
                "n": n,
                "coef_names": ["intercept"] + coef_names,
                "beta": [np.nan] * (len(x_cols) + 1),
                "p": [np.nan] * (len(x_cols) + 1),
                "r2": np.nan
            }

    # ============================================================
    # derived variables
    # ============================================================
    def _face_qp_diff(self) -> np.ndarray:
        return self._get_array(self.face_rows, "Qp_difference")

    def _face_qp_ratio(self) -> np.ndarray:
        return self._get_array(self.face_rows, "Qp_ratio")

    def _face_abs_log_qp_error(self) -> np.ndarray:
        ratio = self._face_qp_ratio()
        out = np.full_like(ratio, np.nan, dtype=float)
        mask = np.isfinite(ratio) & (ratio > 0)
        out[mask] = np.abs(np.log10(ratio[mask]))
        return out

    def _face_density(self) -> np.ndarray:
        return self._get_array(self.face_rows, "face_fracture_density")

    def _face_miss_ratio(self) -> np.ndarray:
        return self._get_array(self.face_rows, "miss_ratio_union")

    def _face_miss_count(self) -> np.ndarray:
        return self._get_array(self.face_rows, "missed_union_fracture_count")

    def _face_missed_density(self) -> np.ndarray:
        return self._get_array(self.face_rows, "missed_fracture_density")

    def _face_orientation_gap(self) -> np.ndarray:
        return self._get_array(self.face_rows, "orientation_bias_gap")

    def _sparse_mask(self, q: float = 0.25) -> Dict[str, Any]:
        density = self._face_density()
        valid = density[np.isfinite(density)]
        if len(valid) == 0:
            return {"mask": np.zeros(len(density), dtype=bool), "threshold": np.nan}

        thr = float(np.quantile(valid, q))
        return {"mask": density <= thr, "threshold": thr}

    def _unfavorable_mask(self, q: float = 0.75) -> Dict[str, Any]:
        gap = self._face_orientation_gap()
        valid = gap[np.isfinite(gap)]
        if len(valid) == 0:
            return {"mask": np.zeros(len(gap), dtype=bool), "threshold": np.nan}

        thr = float(np.quantile(valid, q))
        return {"mask": gap >= thr, "threshold": thr}

    # ============================================================
    # hypothesis tests
    # ============================================================
    def test_h1(self) -> Dict[str, Any]:
        """
        H1: borehole Q'은 face Q'을 정확히 대표하지 않는다.
        operational test:
          mean(Qp_difference) != 0
        """
        diff = self._face_qp_diff()
        test = self._one_sample_ttest(diff, mu=0.0, alternative="two-sided")
        abs_log_err = self._face_abs_log_qp_error()
        mean_abs_log_err = float(np.nanmean(abs_log_err)) if len(abs_log_err) else np.nan
        # also provide Qp correlation (borehole vs face) with safe handling
        qp_corr = self._safe_corr(self._get_array(self.face_rows, 'Qp_face_mean'),
                      self._get_array(self.face_rows, 'Qp_borehole_mean'))

        return {
            "hypothesis": "H1",
            "metric": "Qp_difference",
            "test": test,
            "mean_abs_log10_error": mean_abs_log_err,
            "Qp_correlation": qp_corr,
        }

    def test_h2(self) -> Dict[str, Any]:
        """
        H2: 절리 밀도 증가 -> borehole-face Q' 일치도 향상
        operational test:
          abs(log10(Qp_ratio)) ~ face_fracture_density, expected negative slope
        """
        x = self._face_density()
        y = self._face_abs_log_qp_error()

        reg = self._linear_regression(x, y)
        sp = self._spearman(x, y)

        return {
            "hypothesis": "H2",
            "x": "face_fracture_density",
            "y": "abs(log10(Qp_ratio))",
            "expected_direction": "negative",
            "linear_regression": reg,
            "spearman": sp,
        }

    def test_h3(self) -> Dict[str, Any]:
        """
        H3: 희소 절리망에서 소수 핵심 절리의 누락/교차 여부에 민감 -> discrepancy 증가
        operational tests:
          1) sparse vs dense group error comparison
          2) sparse subset 내 missed fracture metrics ~ error
        """
        sparse_info = self._sparse_mask(q=0.25)
        sparse_mask = sparse_info["mask"]

        y = self._face_abs_log_qp_error()
        miss_ratio = self._face_miss_ratio()
        miss_count = self._face_miss_count()
        miss_density = self._face_missed_density()
        density = self._face_density()

        group = self._welch_ttest(y[sparse_mask], y[~sparse_mask])

        reg_ratio = self._linear_regression(miss_ratio[sparse_mask], y[sparse_mask])
        reg_count = self._linear_regression(miss_count[sparse_mask], y[sparse_mask])
        reg_density = self._linear_regression(miss_density[sparse_mask], y[sparse_mask])

        density_c = density - np.nanmean(density)
        miss_ratio_c = miss_ratio - np.nanmean(miss_ratio)
        interaction = density_c * miss_ratio_c
        multi = self._multiple_regression(
            y=y,
            x_cols=[density_c, miss_ratio_c, interaction],
            coef_names=["density_c", "miss_ratio_c", "density_x_missratio"]
        )

        return {
            "hypothesis": "H3",
            "sparse_threshold_q25": sparse_info["threshold"],
            "group_comparison_sparse_vs_dense": group,
            "sparse_regression_miss_ratio": reg_ratio,
            "sparse_regression_miss_count": reg_count,
            "sparse_regression_missed_density": reg_density,
            "interaction_model": multi,
        }

    def test_h4(self) -> Dict[str, Any]:
        """
        H4: density 효과는 orientation에 의해 조절된다.
        operational test:
          error ~ density + orientation_gap + density*orientation_gap
        """
        y = self._face_abs_log_qp_error()
        density = self._face_density()
        orient = self._face_orientation_gap()

        density_c = density - np.nanmean(density)
        orient_c = orient - np.nanmean(orient)
        interaction = density_c * orient_c

        multi = self._multiple_regression(
            y=y,
            x_cols=[density_c, orient_c, interaction],
            coef_names=["density_c", "orientation_gap_c", "density_x_orientation"]
        )

        return {
            "hypothesis": "H4",
            "formula": "abs(log10(Qp_ratio)) ~ density_c + orientation_gap_c + density*orientation",
            "result": multi,
        }

    def test_h5(self) -> Dict[str, Any]:
        """
        H5: 희소 + 불리한 방향 조건에서 borehole Q' 과대평가 발생
        operational test:
          sparse & unfavorable subset에서 mean(Qp_difference) > 0
        """
        sparse_info = self._sparse_mask(q=0.25)
        unfav_info = self._unfavorable_mask(q=0.75)

        subset = sparse_info["mask"] & unfav_info["mask"]
        diff = self._face_qp_diff()[subset]

        test = self._one_sample_ttest(diff, mu=0.0, alternative="greater")

        over_rate = np.nan
        if len(diff) > 0:
            valid = diff[np.isfinite(diff)]
            if len(valid) > 0:
                over_rate = float(np.mean(valid > 0))

        return {
            "hypothesis": "H5",
            "subset_n": int(np.sum(subset)),
            "sparse_threshold_q25": sparse_info["threshold"],
            "unfavorable_threshold_q75": unfav_info["threshold"],
            "overestimation_rate": over_rate,
            "test": test,
        }

    # ============================================================
    # run all / report
    # ============================================================
    def run_all(self) -> Dict[str, Any]:
        return {
            "meta": {
                "n_face_rows": len(self.face_rows),
                "n_summary_rows": len(self.summary_rows),
                "scipy_available": SCIPY_AVAILABLE,
            },
            "H1": self.test_h1(),
            "H2": self.test_h2(),
            "H3": self.test_h3(),
            "H4": self.test_h4(),
            "H5": self.test_h5(),
        }

    def print_report(self, results: Optional[Dict[str, Any]] = None):
        if results is None:
            results = self.run_all()

        print("\n" + "=" * 110)
        print("Hypothesis Test Report")
        print("=" * 110)

        meta = results.get("meta", {})
        print(f"face rows={meta.get('n_face_rows', 0)}, "
              f"summary rows={meta.get('n_summary_rows', 0)}, "
              f"scipy={meta.get('scipy_available', False)}")

        h1 = results["H1"]
        print("\n[H1] Borehole-derived Q' differs from face Q'")
        print(f"  n={h1['test']['n']}, "
              f"mean diff={h1['test']['mean']:.6f}, "
              f"sd={h1['test']['sd']:.6f}, "
              f"t={h1['test']['t']:.6f}, "
              f"p={h1['test']['p']:.6g}, "
              f"mean abs log10 error={h1['mean_abs_log10_error']:.6f}")

        h2 = results["H2"]
        lr2 = h2["linear_regression"]
        sp2 = h2["spearman"]
        print("\n[H2] Higher fracture density improves agreement")
        print(f"  slope={lr2['slope']:.6f}, p={lr2['p']:.6g}, R2={lr2['r2']:.6f}")
        print(f"  spearman rho={sp2['rho']:.6f}, p={sp2['p']:.6g}")

        h3 = results["H3"]
        gc = h3["group_comparison_sparse_vs_dense"]
        print("\n[H3] Sparse networks show larger discrepancy and stronger omission effect")
        print(f"  sparse threshold (q25) = {h3['sparse_threshold_q25']:.6f}")
        print(f"  sparse vs dense: mean1={gc['mean1']:.6f}, mean2={gc['mean2']:.6f}, p={gc['p']:.6g}")
        print(f"  sparse miss_ratio slope={h3['sparse_regression_miss_ratio']['slope']:.6f}, "
              f"p={h3['sparse_regression_miss_ratio']['p']:.6g}")
        print(f"  sparse miss_count slope={h3['sparse_regression_miss_count']['slope']:.6f}, "
              f"p={h3['sparse_regression_miss_count']['p']:.6g}")

        h4 = results["H4"]
        res4 = h4["result"]
        print("\n[H4] Density effect is moderated by orientation")
        for name, beta, p in zip(res4["coef_names"], res4["beta"], res4["p"]):
            print(f"  {name}: beta={beta:.6f}, p={p:.6g}")
        print(f"  R2={res4['r2']:.6f}")

        h5 = results["H5"]
        print("\n[H5] Sparse + unfavorable orientation leads to systematic overestimation")
        print(f"  subset n={h5['subset_n']}, "
              f"sparse thr={h5['sparse_threshold_q25']:.6f}, "
              f"unfavorable thr={h5['unfavorable_threshold_q75']:.6f}")
        print(f"  overestimation rate={h5['overestimation_rate']:.6f}")
        print(f"  mean diff={h5['test']['mean']:.6f}, "
              f"t={h5['test']['t']:.6f}, "
              f"one-sided p={h5['test']['p']:.6g}")

        print("=" * 110)