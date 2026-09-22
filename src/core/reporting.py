"""
Research Reporting Utility for QSimEx.
Provides CSV export for the five research tables (Table1..Table5).
"""

import os
from typing import List, Dict, Any

import pandas as pd
import numpy as np

from .bayesian_update import SiteContext, DecisionCost


class ResearchReporter:
    @staticmethod
    def save_all_tables_as_csv(
        face_rows: List[Dict[str, Any]],
        summary_rows: List[Dict[str, Any]],
        output_dir: str,
        prefix: str = "results",
        # Central defaults: cost_fp=1.0, cost_fn=5.0
        cost_fp: float = 1.0,
        cost_fn: float = 5.0,
    ) -> Dict[str, pd.DataFrame]:
        """Write Tables 1..5 as CSV files and return the DataFrames.

        This function is intentionally self-contained to avoid import cycles.
        """
        from .decision_test import DecisionUsefulnessTester

        os.makedirs(output_dir, exist_ok=True)

        # Table 1
        t1_rows = []
        for s in summary_rows:
            t1_rows.append(
                {
                    "Scenario": s.get("case_name", "Unknown"),
                    "Corr": float(s.get("Qp_correlation", np.nan)),
                    "Bias": float(s.get("Q_log_ratio_mean", np.nan)),
                    "RMSE": float(s.get("Q_log_RMSE", np.nan)),
                    "RQD dependency": (
                        "High" if s.get("face_rqd_mean", 0) > 80 else "Normal"
                    ),
                }
            )
        df1 = pd.DataFrame(t1_rows)
        df1.to_csv(
            os.path.join(output_dir, f"{prefix}_table1_proxy_performance.csv"),
            index=False,
        )

        # Faces
        df_faces = pd.DataFrame(face_rows) if face_rows else pd.DataFrame()

        # Table 2
        scen_summaries = []
        if not df_faces.empty:
            for scen in sorted(df_faces["case_name"].unique()):
                rows = df_faces[df_faces["case_name"] == scen].to_dict(orient="records")
                tester = DecisionUsefulnessTester(rows)
                scen_summaries.append(
                    tester.summarize_scenario_performance(scenario_id=scen)
                )
        t2_rows = [
            {
                "Scenario": s.get("scenario_id"),
                "AUC": s.get("auc"),
                "Best threshold": s.get("best_threshold"),
                "Sensitivity": s.get("sensitivity_at_best"),
                "Specificity": s.get("specificity_at_best"),
                "FP rate": s.get("FP_rate_at_best"),
                "FN rate": s.get("FN_rate_at_best"),
            }
            for s in scen_summaries
        ]
        df2 = pd.DataFrame(t2_rows)
        df2.to_csv(
            os.path.join(output_dir, f"{prefix}_table2_classification_performance.csv"),
            index=False,
        )

        # Table 3
        t3_rows = []
        if not df_faces.empty:
            overall_tester = DecisionUsefulnessTester(
                df_faces.to_dict(orient="records")
            )
            df_proc = DecisionUsefulnessTester.assign_reference_label(
                df_faces, reference_col="Qp_face_mean", threshold=4.0
            )
            df_proc = DecisionUsefulnessTester.assign_decision_score(
                df_proc, score_col="Qp_borehole_mean"
            )
            sweep_th = np.linspace(1, 40, 20).tolist()
            # Use the provided single cost pair (cost_fp, cost_fn) for consistency
            _, best = overall_tester.compute_cost_curve(
                df_proc, sweep_th, cost_fp=cost_fp, cost_fn=cost_fn
            )
            t3_rows.append(
                {
                    "Cost ratio FP:FN": f"{cost_fp}:{cost_fn}",
                    "Best Q' threshold": best.get("threshold", np.nan),
                    "Expected cost": best.get("expected_cost", np.nan),
                    "FP": int(best.get("FP_false_safe", 0)),
                    "FN": int(best.get("FN_false_alarm", 0)),
                }
            )
        df3 = pd.DataFrame(t3_rows)
        df3.to_csv(
            os.path.join(output_dir, f"{prefix}_table3_optimal_thresholds.csv"),
            index=False,
        )

        # Table 4
        t4_rows = []
        if not df_faces.empty:
            overall_tester = DecisionUsefulnessTester(
                df_faces.to_dict(orient="records")
            )
            lik = overall_tester.get_bayesian_likelihoods(
                bh_threshold=4.0, face_threshold=4.0
            )
            ctx = SiteContext(
                prior_suitable=0.5,
                likelihood=lik,
                costs=DecisionCost(cost_fp, cost_fn),
                borehole_threshold=4.0,
            )
            for prior in [0.3, 0.5, 0.7]:
                ctx.prior_suitable = prior
                for obs in [2.5, 4.0, 6.0]:
                    res = ctx.update_with_observation(obs)
                    bh_class = 1 if obs >= ctx.borehole_threshold else 0
                    expected_exc = res.get("expected_loss_excavate", float("nan"))
                    expected_skip = res.get("expected_loss_skip", float("nan"))
                    t4_rows.append(
                        {
                            "Prior suitable": prior,
                            "Borehole class": bh_class,
                            "Posterior suitable": res["posterior_suitable"],
                            "Decision": res["decision"],
                            "Expected loss excavate": expected_exc,
                            "Expected loss skip": expected_skip,
                            "Expected loss (min)": min(expected_exc, expected_skip),
                        }
                    )
        df4 = pd.DataFrame(t4_rows)
        df4.to_csv(
            os.path.join(output_dir, f"{prefix}_table4_bayesian_posterior.csv"),
            index=False,
        )

        # Table 5
        t5_rows = []
        for s in scen_summaries:
            auc = s.get("auc", 0)
            density = s.get("joint_frequency", 0)
            gap = s.get("orientation_case", 0)
            use_of_q = s.get("recommendation", "unknown")
            condition = "Standard favorable"
            reason = "Standard"

            if auc is None:
                auc = 0
            if auc < 0.7 and density > 2.0:
                condition = "RQD saturated"
                use_of_q = "Do not use alone"
                reason = "low discriminability"
            elif gap > 0.3:
                condition = "strong directional bias"
                use_of_q = "use with correction"
                reason = "high FP/FN sensitivity"
            elif 0.7 <= auc <= 0.85:
                condition = "stable intermediate condition"
                use_of_q = "screening possible"
                reason = "acceptable AUC/cost"
            elif density < 0.5:
                condition = "unknown orientation"
                use_of_q = "Bayesian evidence only"
                reason = "high uncertainty"
            else:
                condition = "Standard favorable"
                use_of_q = "use"
                reason = "reliable classification"

            t5_rows.append(
                {
                    "Condition": condition,
                    "Use of borehole Q'": use_of_q,
                    "Reason": reason,
                }
            )

        df5 = pd.DataFrame(t5_rows).drop_duplicates()
        df5.to_csv(
            os.path.join(output_dir, f"{prefix}_table5_domain_of_applicability.csv"),
            index=False,
        )

        return {
            "table1": df1,
            "table2": df2,
            "table3": df3,
            "table4": df4,
            "table5": df5,
        }
