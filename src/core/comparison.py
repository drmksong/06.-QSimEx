"""
시추공 vs 막장면 Q값 비교 분석
- DFN 직접 교차 기반 비교
- missed fracture metrics 포함
"""

import numpy as np
from typing import Dict, List, Optional
from .tunnel import Tunnel
from .constants import standardize_metrics


class ComparisonEngine:
    """시추공 데이터 vs 막장면 데이터 비교"""

    def __init__(self, tunnel: Tunnel):
        self.tunnel = tunnel
        self.domain = tunnel.domain

    def compare_at_face(self, face_x_idx: int, borehole_window: int = 5) -> Dict:
        """
        특정 굴진면 위치에서 시추공 vs 막장면 비교

        Args:
            face_x_idx: 굴진면 x 격자 인덱스
            borehole_window: 시추공에서 굴진면 주변 ±window 범위 평균
        """
        # ------------------------------------------------------------
        # 1) Face sample
        # ------------------------------------------------------------
        face = self.tunnel.sample_face(face_x_idx)

        face_joint_ids = face.get("_face_joint_ids_set", set())
        face_joint_count = len(face_joint_ids)
        face_joints = face.get('_face_joints', [])
        face_orientation_bias = self._calc_orientation_bias(face_joints)

        # ------------------------------------------------------------
        # 2) Borehole samples around the face
        # ------------------------------------------------------------
        x_start = max(0, face_x_idx - borehole_window)
        x_end = min(self.domain.nx, face_x_idx + borehole_window + 1)

        # 그 다음 geometry / density metrics 계산
        face_area = np.pi * (self.tunnel.radius ** 2)
        window_length = (x_end - x_start) * self.domain.dx
        face_fracture_density = face_joint_count / face_area if face_area > 0 else 0.0

        borehole_results = []
        borehole_joint_sets = []
        borehole_joint_objects_all = []

        for bh_idx in range(len(self.tunnel.borehole_positions)):
            bh = self.tunnel.sample_borehole(bh_idx, x_start, x_end)

            bh_joint_ids = bh.get('_joint_ids_set', set())
            bh_joint_objects = bh.get('_joint_objects', [])

            borehole_joint_sets.append(bh_joint_ids)
            borehole_joint_objects_all.extend(bh_joint_objects)

            common_ids = face_joint_ids & bh_joint_ids
            missed_ids = face_joint_ids - bh_joint_ids

            bh_orientation_bias = self._calc_orientation_bias(bh_joint_objects)

            bh_summary = {
                'name': bh['borehole_name'],

                # 기존 Q/Q' 요약
                'Q_mean': float(np.mean(bh['Q'])) if len(bh['Q']) > 0 else np.nan,
                'Q_median': float(np.median(bh['Q'])) if len(bh['Q']) > 0 else np.nan,
                'Qprime_mean': float(np.mean(bh['Qprime'])) if len(bh['Qprime']) > 0 else np.nan,
                'Qprime_median': float(np.median(bh['Qprime'])) if len(bh['Qprime']) > 0 else np.nan,

                # ============================================================
                # RQD 방법 비교용 borehole 요약
                # ------------------------------------------------------------
                # RQD_borehole_direct:
                #   자연 DFN 절리 교차점만 사용한 borehole Deere 직접법 RQD
                #
                # RQD_borehole_hudson:
                #   같은 borehole window에서 lambda = N/L 기반 Hudson RQD
                # ============================================================
                'RQD_borehole_direct_mean': (
                    float(np.mean(bh.get('RQD_borehole_direct', [])))
                    if len(bh.get('RQD_borehole_direct', [])) > 0 else 0.0
                ),
                'RQD_borehole_direct_median': (
                    float(np.median(bh.get('RQD_borehole_direct', [])))
                    if len(bh.get('RQD_borehole_direct', [])) > 0 else 0.0
                ),
                'RQD_borehole_hudson_mean': (
                    float(np.mean(bh.get('RQD_borehole_hudson', [])))
                    if len(bh.get('RQD_borehole_hudson', [])) > 0 else 0.0
                ),
                'RQD_borehole_hudson_median': (
                    float(np.median(bh.get('RQD_borehole_hudson', [])))
                    if len(bh.get('RQD_borehole_hudson', [])) > 0 else 0.0
                ),
                'lambda_borehole_mean': (
                    float(np.mean(bh.get('lambda_borehole', [])))
                    if len(bh.get('lambda_borehole', [])) > 0 else 0.0
                ),
                'borehole_n_intersections_sum': (
                    int(np.sum(bh.get('borehole_n_intersections', [])))
                    if len(bh.get('borehole_n_intersections', [])) > 0 else 0
                ),

                'face_fracture_count': face_joint_count,
                'bh_fracture_count': len(bh_joint_ids),
                'common_fracture_count': len(common_ids),
                'missed_fracture_count': len(missed_ids),
                'miss_ratio': float(len(missed_ids) / face_joint_count) if face_joint_count > 0 else 0.0,
                'detection_ratio': float(len(common_ids) / face_joint_count) if face_joint_count > 0 else 0.0,

                'bh_window_length': window_length,
                'bh_fracture_frequency': float(len(bh_joint_ids) / window_length) if window_length > 0 else 0.0,
                'orientation_bias_bh': bh_orientation_bias,
            }

            for param in ['RQD', 'Jn', 'Jr', 'Ja', 'Jw', 'SRF']:
                arr = bh[param]
                bh_summary[f'{param}_mean'] = float(np.mean(arr)) if len(arr) > 0 else 0.0

            borehole_results.append(bh_summary)

        # loop 후: 3개 시추공 전체가 관측한 unique joint objects
        unique_bh_union_joint_objects = list(
            {id(j): j for j in borehole_joint_objects_all}.values()
        )

        # orientation bias 계산
        face_joints = face.get('_face_joints', [])
        face_orientation_bias = self._calc_orientation_bias(face_joints)
        bh_union_orientation_bias = self._calc_orientation_bias(unique_bh_union_joint_objects)
        orientation_bias_gap = face_orientation_bias - bh_union_orientation_bias

        # ------------------------------------------------------------
        # 3) Aggregate borehole stats
        # ------------------------------------------------------------
        bh_Q_means = [b["Q_mean"] for b in borehole_results if np.isfinite(b["Q_mean"])]
        bh_Qp_means = [b["Qprime_mean"] for b in borehole_results if np.isfinite(b["Qprime_mean"])]

        face_Q_mean = face["stats"]["Q"]["mean"]
        face_Qp_mean = face["stats"]["Qprime"]["mean"]

        # ------------------------------------------------------------
        # RQD method aggregate stats
        # ------------------------------------------------------------
        bh_RQD_direct_means = [
            b["RQD_borehole_direct_mean"] for b in borehole_results
        ]

        bh_RQD_hudson_means = [
            b["RQD_borehole_hudson_mean"] for b in borehole_results
        ]

        bh_lambda_means = [
            b["lambda_borehole_mean"] for b in borehole_results
        ]

        bh_n_intersections_sums = [
            b["borehole_n_intersections_sum"] for b in borehole_results
        ]

        RQD_borehole_direct_mean = (
            float(np.mean(bh_RQD_direct_means)) if bh_RQD_direct_means else 0.0
        )

        RQD_borehole_hudson_mean = (
            float(np.mean(bh_RQD_hudson_means)) if bh_RQD_hudson_means else 0.0
        )

        lambda_borehole_mean = (
            float(np.mean(bh_lambda_means)) if bh_lambda_means else 0.0
        )

        borehole_n_intersections_total = (
            int(np.sum(bh_n_intersections_sums)) if bh_n_intersections_sums else 0
        )

        # Face-side RQD methods from sample_face()
        RQD_face_scanline = face.get("RQD_face_scanline", face.get("_RQD_face_scanline", 0.0))
        lambda_face_scanline = face.get("lambda_face_scanline", face.get("_lambda_face_scanline", 0.0))
        RQD_face_scanline_hudson = face.get(
            "RQD_face_scanline_hudson",
            face.get("_RQD_face_scanline_hudson", 0.0),
        )
        face_scanline_n_intersections = face.get(
            "face_scanline_n_intersections",
            face.get("_face_scanline_n_intersections", 0),
        )

        Jv_face = face.get("Jv_face", face.get("_Jv_face", 0.0))
        Jv_method = face.get("Jv_method", face.get("_Jv_method", None))
        RQD_face_jv = face.get("RQD_face_jv", face.get("_RQD_face_jv", 0.0))
        RQD_face_conservative = face.get(
            "RQD_face_conservative",
            face.get("_RQD_face_conservative", min(RQD_face_scanline, RQD_face_jv)),
        )


        # 3개 시추공의 절리 검출 합집합
        bh_union_ids = (
            set().union(*borehole_joint_sets) if borehole_joint_sets else set()
        )
        common_union_ids = face_joint_ids & bh_union_ids
        missed_union_ids = face_joint_ids - bh_union_ids
        bh_union_fracture_frequency = (
            float(len(bh_union_ids) / window_length) if window_length > 0 else 0.0
        )
        common_fracture_density = (
            float(len(common_union_ids) / face_area) if face_area > 0 else 0.0
        )
        missed_fracture_density = (
            float(len(missed_union_ids) / face_area) if face_area > 0 else 0.0
        )

        bh_fracture_frequency_mean = (
            float(np.mean([b["bh_fracture_frequency"] for b in borehole_results]))
            if borehole_results
            else 0.0
        )

        bh_union_joint_objects = {}
        for bh_idx in range(len(self.tunnel.borehole_positions)):
            pass        

        # ------------------------------------------------------------
        # 4) Build comparison dict
        # ------------------------------------------------------------
        comparison = {
            "face_x": face_x_idx,
            "face_x_coord": face["x_coord"],
            "face_stats": face["stats"],
            "boreholes": borehole_results,
            # Q comparison
            "Q_face_mean": face_Q_mean,
            "Q_face_median": face["stats"]["Q"]["median"],
            "Q_borehole_mean": float(np.mean(bh_Q_means)) if bh_Q_means else 0.0,
            "Q_borehole_each": bh_Q_means,
            "Q_ratio": (
                float(np.mean(bh_Q_means) / max(face_Q_mean, 1e-10))
                if bh_Q_means
                else 0.0
            ),
            "Q_difference": (
                float(np.mean(bh_Q_means) - face_Q_mean) if bh_Q_means else 0.0
            ),
            "Q_log_ratio": (
                float(
                    np.log10(max(np.mean(bh_Q_means), 1e-10))
                    - np.log10(max(face_Q_mean, 1e-10))
                )
                if bh_Q_means
                else 0.0
            ),
            # Q' comparison
            "Qp_face_mean": face_Qp_mean,
            "Qp_face_median": face["stats"]["Qprime"]["median"],
            "Qp_borehole_mean": float(np.mean(bh_Qp_means)) if bh_Qp_means else np.nan,
            "Qp_borehole_each": bh_Qp_means,
            "Qp_ratio": (
                float(np.mean(bh_Qp_means) / max(face_Qp_mean, 1e-10))
                if bh_Qp_means and np.isfinite(face_Qp_mean) and face_Qp_mean != 0
                else np.nan
            ),
            "Qp_difference": (
                float(np.mean(bh_Qp_means) - face_Qp_mean)
                if bh_Qp_means and np.isfinite(face_Qp_mean)
                else np.nan
            ),
            # face diagnostic info
            # 주의:
            #   수정 후 _face_rqd_mean, _face_rqd_practical, _face_rqd_min_dir는
            #   더 이상 multi-direction face RQD가 아니다.
            #   모두 중앙 수평 단일 face scanline RQD와 호환되도록 유지하는 값이다.
            "_face_joints_count": face.get("_face_joints_count", 0),
            "_face_rqd_practical": face.get("_rqd_practical", RQD_face_scanline),
            "_face_rqd_mean": face.get("_rqd_mean", RQD_face_scanline),
            "_face_rqd_min_dir": face.get("_rqd_min_direction", RQD_face_scanline),
            # ========================================================
            # RQD method comparison
            # ========================================================
            "RQD_borehole_direct_mean": RQD_borehole_direct_mean,
            "RQD_borehole_direct_each": bh_RQD_direct_means,

            "RQD_borehole_hudson_mean": RQD_borehole_hudson_mean,
            "RQD_borehole_hudson_each": bh_RQD_hudson_means,

            "lambda_borehole_mean": lambda_borehole_mean,
            "lambda_borehole_each": bh_lambda_means,
            "borehole_n_intersections_total": borehole_n_intersections_total,

            "RQD_face_scanline": float(RQD_face_scanline),
            "lambda_face_scanline": float(lambda_face_scanline),
            "RQD_face_scanline_hudson": float(RQD_face_scanline_hudson),
            "face_scanline_n_intersections": int(face_scanline_n_intersections),

            "Jv_face": float(Jv_face),
            "Jv_method": Jv_method,
            "RQD_face_jv": float(RQD_face_jv),
            "RQD_face_conservative": float(RQD_face_conservative),

            # Pairwise RQD differences: predictor - target
            "RQD_diff_bh_direct_minus_face_scanline": (
                float(RQD_borehole_direct_mean - RQD_face_scanline)
            ),
            "RQD_diff_bh_hudson_minus_face_scanline": (
                float(RQD_borehole_hudson_mean - RQD_face_scanline)
            ),
            "RQD_diff_bh_direct_minus_face_jv": (
                float(RQD_borehole_direct_mean - RQD_face_jv)
            ),
            "RQD_diff_bh_hudson_minus_face_jv": (
                float(RQD_borehole_hudson_mean - RQD_face_jv)
            ),

            "RQD_absdiff_bh_direct_face_scanline": (
                float(abs(RQD_borehole_direct_mean - RQD_face_scanline))
            ),
            "RQD_absdiff_bh_hudson_face_scanline": (
                float(abs(RQD_borehole_hudson_mean - RQD_face_scanline))
            ),
            "RQD_absdiff_bh_direct_face_jv": (
                float(abs(RQD_borehole_direct_mean - RQD_face_jv))
            ),
            "RQD_absdiff_bh_hudson_face_jv": (
                float(abs(RQD_borehole_hudson_mean - RQD_face_jv))
            ),

            # missed fracture metrics (union across boreholes)
            "_face_joint_count": face_joint_count,
            "_bh_union_fracture_count": len(bh_union_ids),
            "_common_union_fracture_count": len(common_union_ids),
            "_missed_union_fracture_count": len(missed_union_ids),
            "_miss_ratio_union": (
                float(len(missed_union_ids) / face_joint_count)
                if face_joint_count > 0
                else 0.0
            ),
            "_detection_ratio_union": (
                float(len(common_union_ids) / face_joint_count)
                if face_joint_count > 0
                else 0.0
            ),
            # per borehole comparisons
            "per_borehole": [],
            # fracture density metrics
            "_face_area": face_area,
            "_window_length": window_length,
            "_face_fracture_density": face_fracture_density,
            "_bh_fracture_frequency_mean": bh_fracture_frequency_mean,
            "_bh_union_fracture_frequency": bh_union_fracture_frequency,
            "_common_fracture_density": common_fracture_density,
            "_missed_fracture_density": missed_fracture_density,
            # orientation bias metrics
            "_face_orientation_bias": face_orientation_bias,
            "_bh_union_orientation_bias": bh_union_orientation_bias,
            "_orientation_bias_gap": orientation_bias_gap,            
        }

        for bh in borehole_results:
            comparison["per_borehole"].append(
                {
                    "name": bh["name"],

                    "Q_ratio": float(bh["Q_mean"] / max(face_Q_mean, 1e-10)),
                    "Qp_ratio": float(bh["Qprime_mean"] / max(face_Qp_mean, 1e-10)),

                    # RQD ratios against face scanline
                    "RQD_direct_ratio_to_face_scanline": float(
                        bh["RQD_borehole_direct_mean"] / max(RQD_face_scanline, 1e-10)
                    ),
                    "RQD_hudson_ratio_to_face_scanline": float(
                        bh["RQD_borehole_hudson_mean"] / max(RQD_face_scanline, 1e-10)
                    ),

                    # RQD differences
                    "RQD_direct_diff_to_face_scanline": float(
                        bh["RQD_borehole_direct_mean"] - RQD_face_scanline
                    ),
                    "RQD_hudson_diff_to_face_scanline": float(
                        bh["RQD_borehole_hudson_mean"] - RQD_face_scanline
                    ),

                    "miss_ratio": bh["miss_ratio"],
                    "detection_ratio": bh["detection_ratio"],
                }
            )

        import logging

        try:
            comparison = standardize_metrics(comparison)
        except Exception as e:
            logging.warning("standardize_metrics failed for comparison dict at face %s: %s", face_x_idx, e)

        return comparison

    def progressive_comparison(
        self, face_positions: List[int] = None, borehole_window: int = 3
    ) -> List[Dict]:
        """
        터널 굴진에 따른 연속 비교
        """
        if face_positions is None:
            step = max(1, int(10 / self.domain.dx))
            face_positions = list(range(step, self.domain.nx - step, step))

        results = []
        for i, x_idx in enumerate(face_positions):
            if i % max(1, len(face_positions) // 10) == 0:
                print(
                    f"  비교 진행: {i+1}/{len(face_positions)} "
                    f"(x={x_idx * self.domain.dx:.0f}m)"
                )
            comp = self.compare_at_face(x_idx, borehole_window)
            results.append(comp)

        return results

    def summary_statistics(self, comparisons: List[Dict]) -> Dict:
        """비교 결과 종합 통계"""
        if not comparisons:
            return {}

        Q_ratios = [c["Q_ratio"] for c in comparisons]
        Qp_ratios = [c["Qp_ratio"] for c in comparisons]
        Q_log_ratios = [c["Q_log_ratio"] for c in comparisons]

        face_Q = [c["Q_face_mean"] for c in comparisons]
        bh_Q = [c["Q_borehole_mean"] for c in comparisons]
        face_Qp = [c["Qp_face_mean"] for c in comparisons]
        bh_Qp = [c["Qp_borehole_mean"] for c in comparisons]

        face_density = [c.get("_face_fracture_density", 0.0) for c in comparisons]
        bh_freq_mean = [c.get("_bh_fracture_frequency_mean", 0.0) for c in comparisons]
        bh_union_freq = [
            c.get("_bh_union_fracture_frequency", 0.0) for c in comparisons
        ]

        def _safe_corr(a, b):
            if len(a) <= 2:
                return np.nan
            aa = np.asarray(a, dtype=float)
            bb = np.asarray(b, dtype=float)
            if np.nanstd(aa) == 0 or np.nanstd(bb) == 0:
                return np.nan
            c = np.corrcoef(aa, bb)[0, 1]
            return float(c) if np.isfinite(c) else np.nan

        corr_Q = _safe_corr(bh_Q, face_Q)
        corr_Qp = _safe_corr(bh_Qp, face_Qp)

        def match_rate(ratios, lo, hi):
            return sum(1 for r in ratios if lo <= r <= hi) / len(ratios) * 100

        miss_ratio_union = [c.get("_miss_ratio_union", 0.0) for c in comparisons]
        detection_ratio_union = [
            c.get("_detection_ratio_union", 0.0) for c in comparisons
        ]

        # orientation bias metrics
        face_obi = [c.get('_face_orientation_bias', 0.0) for c in comparisons]
        bh_union_obi = [c.get('_bh_union_orientation_bias', 0.0) for c in comparisons]
        obi_gap = [c.get('_orientation_bias_gap', 0.0) for c in comparisons]                


        summary = {
            "n_faces": len(comparisons),
            "Q_ratio_mean": float(np.mean(Q_ratios)),
            "Q_ratio_std": float(np.std(Q_ratios)),
            "Q_ratio_median": float(np.median(Q_ratios)),
            "Q_log_ratio_mean": float(np.mean(Q_log_ratios)),
            "Q_log_ratio_std": float(np.std(Q_log_ratios)),
            "Q_correlation": corr_Q,
            "Q_match_strict": match_rate(Q_ratios, 0.8, 1.25),
            "Q_match_normal": match_rate(Q_ratios, 0.67, 1.5),
            "Q_match_loose": match_rate(Q_ratios, 0.5, 2.0),
            "Qp_ratio_mean": float(np.mean(Qp_ratios)),
            "Qp_ratio_std": float(np.std(Qp_ratios)),
            "Qp_ratio_median": float(np.median(Qp_ratios)),
            "Qp_correlation": corr_Qp,
            "Qp_match_strict": match_rate(Qp_ratios, 0.8, 1.25),
            "Qp_match_normal": match_rate(Qp_ratios, 0.67, 1.5),
            "Qp_match_loose": match_rate(Qp_ratios, 0.5, 2.0),
            "Q_log_RMSE": float(np.sqrt(np.mean(np.array(Q_log_ratios) ** 2))),
            "diagnostic": {
                "face_rqd_mean": float(
                    np.mean([c.get("_face_rqd_mean", c.get("RQD_face_scanline", 0)) for c in comparisons])
                ),
                "face_rqd_min_dir": float(
                    np.mean([c.get("_face_rqd_min_dir", c.get("RQD_face_scanline", 0)) for c in comparisons])
                ),
                "bh_rqd_mean": float(
                    np.mean(
                        [
                            np.mean([b["RQD_mean"] for b in c["boreholes"]])
                            for c in comparisons
                        ]
                    )
                ),                

                "face_rqd_scanline_mean": float(
                    np.mean([c.get("RQD_face_scanline", 0) for c in comparisons])
                ),
                "face_rqd_jv_mean": float(
                    np.mean([c.get("RQD_face_jv", 0) for c in comparisons])
                ),
                "face_rqd_conservative_mean": float(
                    np.mean([c.get("RQD_face_conservative", 0) for c in comparisons])
                ),
                "bh_rqd_direct_mean": float(
                    np.mean([c.get("RQD_borehole_direct_mean", 0) for c in comparisons])
                ),
                "bh_rqd_hudson_mean": float(
                    np.mean([c.get("RQD_borehole_hudson_mean", 0) for c in comparisons])
                ),
                "lambda_borehole_mean": float(
                    np.mean([c.get("lambda_borehole_mean", 0) for c in comparisons])
                ),
                "lambda_face_scanline_mean": float(
                    np.mean([c.get("lambda_face_scanline", 0) for c in comparisons])
                ),

                "face_joints_mean": float(
                    np.mean([c.get("_face_joints_count", 0) for c in comparisons])
                ),
                # missed fracture metrics
                "miss_ratio_union_mean": float(np.mean(miss_ratio_union)),
                "miss_ratio_union_std": float(np.std(miss_ratio_union)),
                "detection_ratio_union_mean": float(np.mean(detection_ratio_union)),
                "detection_ratio_union_std": float(np.std(detection_ratio_union)),
                # fracture density metrics
                "face_fracture_density_mean": float(np.mean(face_density)),
                "face_fracture_density_std": float(np.std(face_density)),
                "bh_fracture_frequency_mean": float(np.mean(bh_freq_mean)),
                "bh_fracture_frequency_std": float(np.std(bh_freq_mean)),
                "bh_union_fracture_frequency_mean": float(np.mean(bh_union_freq)),
                "bh_union_fracture_frequency_std": float(np.std(bh_union_freq)),
                # orientation bias metrics
                'face_orientation_bias_mean': float(np.mean(face_obi)),
                'face_orientation_bias_std': float(np.std(face_obi)),
                'bh_union_orientation_bias_mean': float(np.mean(bh_union_obi)),
                'bh_union_orientation_bias_std': float(np.std(bh_union_obi)),
                'orientation_bias_gap_mean': float(np.mean(obi_gap)),
                'orientation_bias_gap_std': float(np.std(obi_gap)),
            },
        }

        import logging

        try:
            summary = standardize_metrics(summary)
        except Exception as e:
            logging.warning("standardize_metrics failed for comparison.summary: %s", e)

        return summary

    def print_report(self, comparisons: List[Dict], summary: Dict = None):
        """텍스트 비교 리포트 출력"""
        if summary is None:
            summary = self.summary_statistics(comparisons)

        print("\n" + "=" * 120)
        print(
            "  시추공 vs 막장면 Q값 비교 분석 보고서 (DFN 직접 교차 + Missed Fractures)"
        )
        print("=" * 120)

        print(
            f"\n{'Chainage':>10} │ {'Q_Face':>10} │ {'Q_BH':>10} │ "
            f"{'Q_Ratio':>10} │ {'Qp_Face':>10} │ {'Qp_BH':>10} │ "
            f"{'Qp_Ratio':>10} │ {'Miss_U':>8} │ {'Detect_U':>8}"
        )
        print("─" * 120)

        for c in comparisons:
            print(
                f"{c['face_x_coord']:>10.1f} │ "
                f"{c['Q_face_mean']:>10.3f} │ "
                f"{c['Q_borehole_mean']:>10.3f} │ "
                f"{c['Q_ratio']:>10.3f} │ "
                f"{c['Qp_face_mean']:>10.3f} │ "
                f"{c['Qp_borehole_mean']:>10.3f} │ "
                f"{c['Qp_ratio']:>10.3f} │ "
                f"{c.get('_miss_ratio_union', 0.0):>8.3f} │ "
                f"{c.get('_detection_ratio_union', 0.0):>8.3f}"
            )

        print("\n" + "─" * 80)
        print("  📊 종합 통계")
        print("─" * 80)
        print(f"  비교 단면 수:              {summary['n_faces']}")
        print(
            f"  Q  비율 평균:              {summary['Q_ratio_mean']:.3f} ± {summary['Q_ratio_std']:.3f}"
        )
        print(
            f"  Q' 비율 평균:              {summary['Qp_ratio_mean']:.3f} ± {summary['Qp_ratio_std']:.3f}"
        )
        print(f"  Q  상관계수 (r):           {summary['Q_correlation']:.4f}")
        print(f"  Q' 상관계수 (r):           {summary['Qp_correlation']:.4f}")
        print(f"  Q  log-RMSE:               {summary['Q_log_RMSE']:.4f}")

        print(f"\n  📏 일치율")
        print(
            f"  Strict (±25%)   Q={summary['Q_match_strict']:.1f}%   Q'={summary['Qp_match_strict']:.1f}%"
        )
        print(
            f"  Normal (±50%)   Q={summary['Q_match_normal']:.1f}%   Q'={summary['Qp_match_normal']:.1f}%"
        )
        print(
            f"  Loose  (±100%)  Q={summary['Q_match_loose']:.1f}%   Q'={summary['Qp_match_loose']:.1f}%"
        )

        diag = summary.get("diagnostic", {})
        print(f"\n  📋 진단 정보")

        print(f"  Face RQD scanline 평균:    {diag.get('face_rqd_scanline_mean', diag.get('face_rqd_mean', 0)):.1f}")
        print(f"  Face RQD Jv 평균:          {diag.get('face_rqd_jv_mean', 0):.1f}")
        print(f"  BH RQD direct 평균:        {diag.get('bh_rqd_direct_mean', diag.get('bh_rqd_mean', 0)):.1f}")
        print(f"  BH RQD Hudson 평균:        {diag.get('bh_rqd_hudson_mean', 0):.1f}")        

        print(f"  막장면 교차절리 (평균):    {diag.get('face_joints_mean', 0):.1f}")
        print(
            f"  Miss ratio union (평균):   {diag.get('miss_ratio_union_mean', 0):.3f} ± {diag.get('miss_ratio_union_std', 0):.3f}"
        )
        print(
            f"  Detect ratio union (평균): {diag.get('detection_ratio_union_mean', 0):.3f} ± {diag.get('detection_ratio_union_std', 0):.3f}"
        )

        print("=" * 120)

    def comparisons_to_face_rows(
        self, comparisons: List[Dict], case_name: str, seed: int
    ) -> List[Dict]:
        """
        comparison 결과 → face-level row list
        1 row = 1 face position
        """
        rows = []

        for c in comparisons:
            row = {
                "case_name": case_name,
                "seed": seed,
                "face_x_idx": c.get("face_x"),
                "face_x_coord": c.get("face_x_coord"),
                # face summary
                "Q_face_mean": c.get("Q_face_mean"),
                "Q_face_median": c.get("Q_face_median"),
                "Qp_face_mean": c.get("Qp_face_mean"),
                "Qp_face_median": c.get("Qp_face_median"),
                # borehole aggregated summary
                "Q_borehole_mean": c.get("Q_borehole_mean"),
                "Qp_borehole_mean": c.get("Qp_borehole_mean"),
                # agreement metrics
                "Q_ratio": c.get("Q_ratio"),
                "Q_difference": c.get("Q_difference"),
                "Q_log_ratio": c.get("Q_log_ratio"),
                "Qp_ratio": c.get("Qp_ratio"),
                "Qp_difference": c.get("Qp_difference"),
                # diagnostics
                "face_joints_count": c.get("_face_joints_count"),
                "face_rqd_practical": c.get("_face_rqd_practical"),
                "face_rqd_mean": c.get("_face_rqd_mean"),
                "face_rqd_min_dir": c.get("_face_rqd_min_dir"),

                # ====================================================
                # RQD method comparison columns
                # ====================================================
                "RQD_borehole_direct": c.get("RQD_borehole_direct_mean"),
                "RQD_borehole_hudson": c.get("RQD_borehole_hudson_mean"),
                "lambda_borehole": c.get("lambda_borehole_mean"),
                "borehole_n_intersections_total": c.get("borehole_n_intersections_total"),

                "RQD_face_scanline": c.get("RQD_face_scanline"),
                "lambda_face_scanline": c.get("lambda_face_scanline"),
                "RQD_face_scanline_hudson": c.get("RQD_face_scanline_hudson"),
                "face_scanline_n_intersections": c.get("face_scanline_n_intersections"),

                "Jv_face": c.get("Jv_face"),
                "Jv_method": c.get("Jv_method"),
                "RQD_face_jv": c.get("RQD_face_jv"),
                "RQD_face_conservative": c.get("RQD_face_conservative"),

                "RQD_diff_bh_direct_minus_face_scanline": c.get(
                    "RQD_diff_bh_direct_minus_face_scanline"
                ),
                "RQD_diff_bh_hudson_minus_face_scanline": c.get(
                    "RQD_diff_bh_hudson_minus_face_scanline"
                ),
                "RQD_diff_bh_direct_minus_face_jv": c.get(
                    "RQD_diff_bh_direct_minus_face_jv"
                ),
                "RQD_diff_bh_hudson_minus_face_jv": c.get(
                    "RQD_diff_bh_hudson_minus_face_jv"
                ),

                "RQD_absdiff_bh_direct_face_scanline": c.get(
                    "RQD_absdiff_bh_direct_face_scanline"
                ),
                "RQD_absdiff_bh_hudson_face_scanline": c.get(
                    "RQD_absdiff_bh_hudson_face_scanline"
                ),
                "RQD_absdiff_bh_direct_face_jv": c.get(
                    "RQD_absdiff_bh_direct_face_jv"
                ),
                "RQD_absdiff_bh_hudson_face_jv": c.get(
                    "RQD_absdiff_bh_hudson_face_jv"
                ),

                # missed fracture metrics
                "face_joint_count": c.get("_face_joint_count"),
                "bh_union_fracture_count": c.get("_bh_union_fracture_count"),
                "common_union_fracture_count": c.get("_common_union_fracture_count"),
                "missed_union_fracture_count": c.get("_missed_union_fracture_count"),
                "miss_ratio_union": c.get("_miss_ratio_union"),
                "detection_ratio_union": c.get("_detection_ratio_union"),
                # fracture density metrics
                "face_area": c.get("_face_area"),
                "window_length": c.get("_window_length"),
                "face_fracture_density": c.get("_face_fracture_density"),
                "bh_fracture_frequency_mean": c.get("_bh_fracture_frequency_mean"),
                "bh_union_fracture_frequency": c.get("_bh_union_fracture_frequency"),
                "common_fracture_density": c.get("_common_fracture_density"),
                "missed_fracture_density": c.get("_missed_fracture_density"),
                "face_orientation_bias": c.get("_face_orientation_bias"),
                "bh_union_orientation_bias": c.get("_bh_union_orientation_bias"),
                "orientation_bias_gap": c.get("_orientation_bias_gap"),                
            }

            q_ratio = c.get("Q_ratio", None)
            qp_ratio = c.get("Qp_ratio", None)

            row["Q_match_strict"] = int(q_ratio is not None and 0.8 <= q_ratio <= 1.25)
            row["Q_match_normal"] = int(q_ratio is not None and 0.67 <= q_ratio <= 1.5)
            row["Q_match_loose"] = int(q_ratio is not None and 0.5 <= q_ratio <= 2.0)

            row["Qp_match_strict"] = int(
                qp_ratio is not None and 0.8 <= qp_ratio <= 1.25
            )
            row["Qp_match_normal"] = int(
                qp_ratio is not None and 0.67 <= qp_ratio <= 1.5
            )
            row["Qp_match_loose"] = int(qp_ratio is not None and 0.5 <= qp_ratio <= 2.0)

            # face_stats flatten
            face_stats = c.get("face_stats", {})
            for param, stats in face_stats.items():
                for stat_name, stat_val in stats.items():
                    row[f"face_{param}_{stat_name}"] = stat_val

            rows.append(row)

        return rows

    def comparisons_to_borehole_rows(
        self, comparisons: List[Dict], case_name: str, seed: int
    ) -> List[Dict]:
        """
        comparison 결과 → borehole-level row list
        1 row = 1 face position × 1 borehole
        """
        rows = []

        for c in comparisons:
            face_x = c.get("face_x")
            face_x_coord = c.get("face_x_coord")
            q_face_mean = c.get("Q_face_mean")
            qp_face_mean = c.get("Qp_face_mean")

            boreholes = c.get("boreholes", [])
            per_bh = c.get("per_borehole", [])
            per_bh_map = {b["name"]: b for b in per_bh}

            for bh in boreholes:
                name = bh.get("name")
                bh_ratio_info = per_bh_map.get(name, {})

                row = {
                    "case_name": case_name,
                    "seed": seed,
                    "face_x_idx": face_x,
                    "face_x_coord": face_x_coord,
                    "borehole_name": name,
                    # face reference
                    "Q_face_mean": q_face_mean,
                    "Qp_face_mean": qp_face_mean,
                    # borehole values
                    "Q_bh_mean": bh.get("Q_mean"),
                    "Q_bh_median": bh.get("Q_median"),
                    "Qp_bh_mean": bh.get("Qprime_mean"),
                    "Qp_bh_median": bh.get("Qprime_median"),
                    "RQD_bh_mean": bh.get("RQD_mean"),
                    "Jn_bh_mean": bh.get("Jn_mean"),

                    # RQD method columns per borehole
                    "RQD_borehole_direct_mean": bh.get("RQD_borehole_direct_mean"),
                    "RQD_borehole_direct_median": bh.get("RQD_borehole_direct_median"),
                    "RQD_borehole_hudson_mean": bh.get("RQD_borehole_hudson_mean"),
                    "RQD_borehole_hudson_median": bh.get("RQD_borehole_hudson_median"),
                    "lambda_borehole_mean": bh.get("lambda_borehole_mean"),
                    "borehole_n_intersections_sum": bh.get("borehole_n_intersections_sum"),

                    # Face RQD references copied to each borehole row
                    "RQD_face_scanline": c.get("RQD_face_scanline"),
                    "RQD_face_jv": c.get("RQD_face_jv"),
                    "RQD_face_conservative": c.get("RQD_face_conservative"),
                    "lambda_face_scanline": c.get("lambda_face_scanline"),
                    "face_scanline_n_intersections": c.get("face_scanline_n_intersections"),
                    "Jv_face": c.get("Jv_face"),
                    "Jv_method": c.get("Jv_method"),

                    "Jr_bh_mean": bh.get("Jr_mean"),
                    "Ja_bh_mean": bh.get("Ja_mean"),
                    "Jw_bh_mean": bh.get("Jw_mean"),
                    "SRF_bh_mean": bh.get("SRF_mean"),
                    # per-borehole ratios
                    "Q_ratio_bh_to_face": bh_ratio_info.get("Q_ratio"),
                    "Qp_ratio_bh_to_face": bh_ratio_info.get("Qp_ratio"),
                    # missed fracture metrics
                    "face_fracture_count": bh.get("face_fracture_count"),
                    "bh_fracture_count": bh.get("bh_fracture_count"),
                    "common_fracture_count": bh.get("common_fracture_count"),
                    "missed_fracture_count": bh.get("missed_fracture_count"),
                    "miss_ratio": bh.get("miss_ratio"),
                    "detection_ratio": bh.get("detection_ratio"),
                    "bh_window_length": bh.get("bh_window_length"),
                    "bh_fracture_frequency": bh.get("bh_fracture_frequency"),
                    "face_fracture_density": c.get("_face_fracture_density"),
                    "bh_union_fracture_frequency": c.get(
                        "_bh_union_fracture_frequency"
                    ),
                    "common_fracture_density": c.get("_common_fracture_density"),
                    "missed_fracture_density": c.get("_missed_fracture_density"),
                    "orientation_bias_bh": bh.get("orientation_bias_bh"),
                    "face_orientation_bias": c.get("_face_orientation_bias"),
                    "orientation_bias_gap_to_face": (
                        c.get("_face_orientation_bias") - bh.get("orientation_bias_bh")
                        if bh.get("orientation_bias_bh") is not None and c.get("_face_orientation_bias") is not None
                        else None
                    ),                    
                }

                q_ratio = row["Q_ratio_bh_to_face"]
                qp_ratio = row["Qp_ratio_bh_to_face"]

                row["Q_match_strict"] = int(
                    q_ratio is not None and 0.8 <= q_ratio <= 1.25
                )
                row["Q_match_normal"] = int(
                    q_ratio is not None and 0.67 <= q_ratio <= 1.5
                )
                row["Q_match_loose"] = int(
                    q_ratio is not None and 0.5 <= q_ratio <= 2.0
                )

                row["Qp_match_strict"] = int(
                    qp_ratio is not None and 0.8 <= qp_ratio <= 1.25
                )
                row["Qp_match_normal"] = int(
                    qp_ratio is not None and 0.67 <= qp_ratio <= 1.5
                )
                row["Qp_match_loose"] = int(
                    qp_ratio is not None and 0.5 <= qp_ratio <= 2.0
                )

                rows.append(row)

        return rows

    def _calc_orientation_bias(self, joints, borehole_dir=np.array([1.0, 0.0, 0.0])) -> float:
        """
        절리 집합에 대한 borehole orientation bias 계산

        OBI = 1 - mean(|n · d_bh|)
        """
        if not joints:
            return 0.0

        d = borehole_dir / np.linalg.norm(borehole_dir)
        vals = []

        for j in joints:
            n = j.normal / np.linalg.norm(j.normal)
            vals.append(abs(np.dot(n, d)))

        return float(1.0 - np.mean(vals))