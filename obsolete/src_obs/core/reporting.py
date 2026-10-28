"""
Research Reporting Utility for QSimEx.
Provides CSV export for the five research tables (Table1..Table5).
"""

import os
from typing import List, Dict, Any

import pandas as pd
import numpy as np
from .constants import standardize_metrics
from .profile_exploration import search_profile_boundaries
import logging


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
        borehole_rows: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, pd.DataFrame]:
        """Write Tables 1..5 as CSV files and return the DataFrames.

        This function is intentionally self-contained to avoid import cycles.
        """
        os.makedirs(output_dir, exist_ok=True)

        # Normalize incoming rows to canonical metric keys for consistent CSV headers
        face_rows = face_rows or []
        summary_rows = summary_rows or []
        borehole_rows = borehole_rows or []
        import logging

        normalized_face = []
        for r in face_rows:
            try:
                normalized_face.append(standardize_metrics(dict(r)))
            except Exception as e:
                logging.warning("standardize_metrics failed for face row: %s", e)
                normalized_face.append(dict(r))

        normalized_summary = []
        for s in summary_rows:
            try:
                normalized_summary.append(standardize_metrics(dict(s)))
            except Exception as e:
                logging.warning("standardize_metrics failed for summary row: %s", e)
                normalized_summary.append(dict(s))

        face_rows = normalized_face
        summary_rows = normalized_summary

        normalized_borehole = []
        for row in borehole_rows:
            try:
                normalized_borehole.append(standardize_metrics(dict(row)))
            except Exception as e:
                logging.warning("standardize_metrics failed for borehole row: %s", e)
                normalized_borehole.append(dict(row))

        # Table 1
        t1_rows = []
        for s in summary_rows:
            t1_rows.append(
                {
                    "Scenario": s.get("case_name", s.get("case_name_meta", "Unknown")),
                    "Corr": float(s.get("Qp_correlation", s.get("Qp_corr", np.nan))),
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
        scenario_names = (
            sorted(df_faces["case_name"].dropna().unique())
            if not df_faces.empty and "case_name" in df_faces
            else []
        )

        profile_scenarios = (
            sorted({row.get("case_name") for row in normalized_borehole if row.get("case_name")})
            if normalized_borehole
            else []
        )
        boundary_by_scenario = {}
        for scenario in profile_scenarios:
            scenario_rows = [
                row for row in normalized_borehole if row.get("case_name") == scenario
            ]
            boundary_by_scenario[scenario] = search_profile_boundaries(scenario_rows)

        # Temporary binary classification is quarantined until explicit
        # post-excavation labels and independent lower/upper searches exist.
        t2_rows = []
        for scenario in scenario_names or profile_scenarios:
            boundary = boundary_by_scenario.get(scenario)
            if boundary is None:
                t2_rows.append(
                    {
                        "Scenario": scenario,
                        "Status": "not_identifiable",
                        "Lower cutoff": None,
                        "Upper cutoff": None,
                        "Reason": "borehole profile rows are unavailable",
                    }
                )
                continue
            t2_rows.append(
                {
                    "Scenario": scenario,
                    "Status": boundary["status"],
                    "Lower cutoff": boundary["lower_cutoff"],
                    "Upper cutoff": boundary["upper_cutoff"],
                    "Reason": boundary["reason"],
                }
            )
        df2 = pd.DataFrame(t2_rows)
        df2.to_csv(
            os.path.join(output_dir, f"{prefix}_table2_classification_performance.csv"),
            index=False,
        )

        # Table 3: lower/upper values are deliberately absent until the
        # explicit-label cutoff search is connected to this reporter.
        if normalized_borehole:
            combined_boundary = search_profile_boundaries(normalized_borehole)
            t3_rows = [
                {
                    "Status": combined_boundary["status"],
                    "Lower cutoff": combined_boundary["lower_cutoff"],
                    "Upper cutoff": combined_boundary["upper_cutoff"],
                    "Reason": combined_boundary["reason"],
                }
            ]
        else:
            t3_rows = [
                {
                    "Status": "not_identifiable",
                    "Lower cutoff": None,
                    "Upper cutoff": None,
                    "Reason": "borehole profile rows are unavailable",
                }
            ] if scenario_names else []
        df3 = pd.DataFrame(t3_rows)
        df3.to_csv(
            os.path.join(output_dir, f"{prefix}_table3_optimal_thresholds.csv"),
            index=False,
        )

        # Table 4: Bayesian decisions also require an independently supplied
        # outcome label; the former 4.0-based example is not reportable.
        t4_rows = [
            {
                "Status": "not_identifiable",
                "Reason": "Bayesian likelihoods require independent outcomes",
            }
        ] if scenario_names else []
        df4 = pd.DataFrame(t4_rows)
        df4.to_csv(
            os.path.join(output_dir, f"{prefix}_table4_bayesian_posterior.csv"),
            index=False,
        )

        # Table 5 cannot claim domain applicability before the boundaries are
        # identified and independently validated.
        df5 = pd.DataFrame(
            [
                {
                    "Condition": "not_identifiable",
                    "Use of borehole Q'": "do not use for operation",
                    "Reason": "lower and upper cutoffs are not connected",
                }
            ]
            if scenario_names
            else []
        )
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
