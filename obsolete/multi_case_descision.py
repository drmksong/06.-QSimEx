"""LEGACY_DO_NOT_USE: obsolete single-threshold decision analysis.

This module remains only for historical reference and will be removed after
the explicit lower/upper cutoff pipeline replaces it. It must not be used to
generate research results.

실행 예:
python -m src.cli.run_multicase_decision
"""

import numpy as np

from multi_batch_runner import (
    MultiCaseBatchRunner,
    MultiCaseBatchConfig,
)
import os
import pandas as pd
from src.core.hypothesis_test import BatchHypothesisTester
from src.core.decision_test import DecisionUsefulnessTester
from src.core.reporting import ResearchReporter
from src.core.bayesian_update import SiteContext, DecisionCost
from src.core.constants import standardize_metrics, CANONICAL
from src.core.qprime_cutoff_search import generate_qprime_cutoffs
import logging


def print_qp_distribution(face_rows):
    face_qp = np.array([r["Qp_face_mean"] for r in face_rows], dtype=float)
    bh_qp = np.array([r["Qp_borehole_mean"] for r in face_rows], dtype=float)

    print("\n" + "=" * 90)
    print("Qprime distribution")
    print("=" * 90)

    print("Face Qp min / p10 / p25 / p50 / p75 / p90 / max")
    print(
        np.nanmin(face_qp),
        np.nanpercentile(face_qp, [10, 25, 50, 75, 90]),
        np.nanmax(face_qp),
    )

    print("BH Qp min / p10 / p25 / p50 / p75 / p90 / max")
    print(
        np.nanmin(bh_qp),
        np.nanpercentile(bh_qp, [10, 25, 50, 75, 90]),
        np.nanmax(bh_qp),
    )


def run_case_level_decision_analysis(
    face_rows, threshold=4.0, cost_safe=10.0, cost_alarm=1.0
):
    """
    case별 decision usefulness 분석
    """
    case_names = sorted(set(r["case_name"] for r in face_rows))
    results = []

    print("\n" + "=" * 90)
    print(f"Case-level decision analysis, threshold={threshold}")
    print(f"Cost: False-Safe={cost_safe}, False-Alarm={cost_alarm}")
    print("=" * 90)

    for case_name in case_names:
        rows_case = [r for r in face_rows if r["case_name"] == case_name]

        tester = DecisionUsefulnessTester(rows_case)
        res = tester.evaluate(
            threshold=threshold,
            use_qprime=True,
            cost_false_safe=cost_safe,
            cost_false_alarm=cost_alarm,
        )

        b = res["borehole_strategy"]
        # normalize metric keys for downstream code (safe per-row canonicalization)
        try:
            b = standardize_metrics(b)
        except Exception as e:
            logging.warning("standardize_metrics failed for borehole_strategy: %s", e)
        results.append(
            {
                "case_name": case_name,
                "threshold": threshold,
                "prior_good": res["prior_face_good_rate"],
                "accuracy": b.get("accuracy"),
                # accept both canonical and legacy cost keys
                "cost": b.get("expected_cost", b.get("cost", None)),
                "nb": b.get("net_benefit", b.get("nb", None)),
            }
        )

        print(f"\n[CASE] {case_name}")
        print(f"  n={b['n']}")
        print(f"  prior face good rate={res['prior_face_good_rate']:.3f}")
        print(f"  false_safe_rate={b['false_safe_rate']}")
        print(f"  false_alarm_rate={b['false_alarm_rate']}")
        print(f"  balanced_accuracy={b['balanced_accuracy']:.3f}")
        print(f"  expected_cost={b['expected_cost']:.3f}")
        print(f"  cost_reduction_vs_majority={b['cost_reduction_vs_majority']:.3f}")

    return pd.DataFrame(results)


def run_overall_decision_analysis(face_rows):
    """
    전체 통합 decision usefulness 분석
    """
    tester = DecisionUsefulnessTester(face_rows)

    print("\n" + "=" * 90)
    print("Overall decision analysis")
    print("=" * 90)

    # 1) 고정 threshold
    for threshold in [1.0, 4.0, 10.0, 40.0]:
        res = tester.evaluate(
            threshold=threshold,
            use_qprime=True,
            cost_false_safe=10,
            cost_false_alarm=3,
        )
        tester.print_summary(res)

    # 2) data-driven threshold sweep
    face_qp = np.array([r["Qp_face_mean"] for r in face_rows], dtype=float)
    thresholds = np.nanpercentile(
        face_qp, [10, 20, 30, 40, 50, 60, 70, 80, 90]
    ).tolist()

    print("\n" + "=" * 90)
    print("Data-driven threshold sweep")
    print("=" * 90)

    sweep = tester.sweep_thresholds(
        thresholds=thresholds,
        use_qprime=True,
        cost_false_safe=10,
        cost_false_alarm=3,
    )

    for r in sweep:
        print(r)

    # 3) density / orientation 조건별 분석
    print("\n" + "=" * 90)
    print("Regime analysis, threshold=4.0")
    print("=" * 90)

    regime = tester.evaluate_by_regime(
        threshold=4.0,
        use_qprime=True,
        cost_false_safe=10,
        cost_false_alarm=3,
    )

    print("\n[By density]")
    for k, v in regime["by_density"].items():
        print(k, v)

    print("\n[By orientation]")
    for k, v in regime["by_orientation"].items():
        print(k, v)

    print("\n[By density x orientation]")
    for k, v in regime["by_density_orientation"].items():
        print(k, v)


def run_hypothesis_tests(face_rows):
    """
    기존 Q' discrepancy 가설 검정
    """
    print("\n" + "=" * 90)
    print("Hypothesis tests on all cases")
    print("=" * 90)

    hyp_tester = BatchHypothesisTester(face_rows)
    hyp_results = hyp_tester.run_all()
    hyp_tester.print_report(hyp_results)


def export_tidy_decision_results(face_rows, output_dir, thresholds=None):
    """
    연구용 Tidy Dataframe 생성 및 저장.
    scenario_id, dfn_parameters, decision_metrics 등을 통합.
    """
    if thresholds is None:
        thresholds = [1.0, 4.0, 10.0, 40.0]

    scenarios = [
        {"id": "nuclear_high_risk", "cost_safe": 20.0, "cost_alarm": 1.0},
        {"id": "resource_opt", "cost_safe": 10.0, "cost_alarm": 5.0},
    ]

    all_decision_data = []
    tester = DecisionUsefulnessTester(face_rows)

    # compute case list once to avoid "possibly unbound" warnings
    case_names = sorted(set(r["case_name"] for r in face_rows))

    print(f"\n[INFO] Exporting tidy decision results to {output_dir}...")

    for scenario in scenarios:
        for th in thresholds:

            # Pooled analysis (전체 케이스 통합)
            res = tester.evaluate(
                threshold=th,
                cost_false_safe=scenario["cost_safe"],
                cost_false_alarm=scenario["cost_alarm"],
            )
            m = res["borehole_strategy"]
            try:
                m = standardize_metrics(m)
            except Exception as e:
                logging.warning("standardize_metrics failed for pooled borehole_strategy: %s", e)

            # Tidy row construction
            row = {
                "scenario_id": scenario["id"],
                "cost_fp": scenario["cost_safe"],
                "cost_fn": scenario["cost_alarm"],
                "threshold": th,
                CANONICAL["N"]: m.get("n", None),
                "prior_suitable": res["prior_face_good_rate"],
                CANONICAL["TP"]: m.get("TP_correct_excavate", m.get("TP", None)),
                CANONICAL["FP"]: m.get("FP_false_safe", m.get("FP", None)),
                CANONICAL["FN"]: m.get("FN_false_alarm", m.get("FN", None)),
                CANONICAL["TN"]: m.get("TN_correct_reject", m.get("TN", None)),
                "TPR": m.get("TPR", None),
                "FNR": m.get("FNR", None),
                "precision": m.get("precision", None),
                "FPR": m.get("FPR", None),
                CANONICAL["EXPECTED_COST"]: m.get("expected_cost", m.get("cost", None)),
                CANONICAL["NET_BENEFIT"]: m.get("net_benefit", m.get("nb", None)),
                "accuracy": m.get("accuracy", None),
                "balanced_accuracy": m.get("balanced_accuracy", None),
                "auc": tester.calculate_auc(np.array([m.get("FPR", np.nan)]), np.array([m.get("TPR", np.nan)])),
            }
            all_decision_data.append(row)

    # --- Layer 8: Domain of Applicability Summary 생성 ---
    summary_rows = []
    for scenario in scenarios:
        for case_name in case_names:
            case_subset = [r for r in face_rows if r["case_name"] == case_name]
            case_tester = DecisionUsefulnessTester(case_subset)

            # 각 케이스별 최적 임계값 탐색
            sweep = case_tester.sweep_thresholds(
                thresholds=generate_qprime_cutoffs(),
                cost_false_safe=scenario["cost_safe"],
                cost_false_alarm=scenario["cost_alarm"],
            )
            opt = case_tester.find_optimal_threshold(sweep)

            # 케이스의 물리적 특성 추출 (평균적인 특성)
            avg_density = np.nanmean(
                [r.get("face_fracture_density", 0) for r in case_subset]
            )
            avg_gap = np.nanmean(
                [r.get("orientation_bias_gap", 0) for r in case_subset]
            )

            summary_rows.append(
                {
                    "scenario_id": scenario["id"],
                    "case_name": case_name,
                    "avg_fracture_density": avg_density,
                    "avg_orientation_gap": avg_gap,
                    "optimal_threshold": opt.get("threshold"),
                    "max_net_benefit": opt.get("net_benefit"),
                    "is_applicable": opt.get("net_benefit", -1)
                    > 0,  # Net Benefit이 양수여야 사용 가치 있음
                    "reliability_index": opt.get("balanced_accuracy", 0)
                    * (1 - avg_gap),  # 예시 지표
                }
            )

    df_decision = pd.DataFrame(all_decision_data)
    csv_path = os.path.join(output_dir, "decision_analysis_tidy.csv")
    df_decision.to_csv(csv_path, index=False)

    df_doa = pd.DataFrame(summary_rows)
    doa_path = os.path.join(output_dir, "domain_of_applicability.csv")
    df_doa.to_csv(doa_path, index=False)

    print(f"[OK] Tidy decision results saved: {csv_path}")
    print(f"[OK] Domain of Applicability summary saved: {doa_path}")

    print("\n[Layer 8] Applicability Matrix (Is borehole Q' useful?):")
    print(
        df_doa[
            ["scenario_id", "case_name", "is_applicable", "max_net_benefit"]
        ].to_string()
    )


def main():
    raise RuntimeError(
        "LEGACY_DO_NOT_USE: multi_case_descision.py contains provisional "
        "single-threshold analysis and is intentionally disabled."
    )

    # case_paths = [
    #     "cases/granite_good_dense.yaml",
    #     "cases/granite_medium.yaml",
    #     "cases/granite_sparse.yaml",
    #     "cases/granite_dense_unfavorable.yaml",
    #     "cases/granite_sparse_unfavorable.yaml",
    #     "cases/granite_sparse_favorable.yaml",
    # ]

    case_paths = [
        "cases/granite_rqd_p32_rot_05.yaml",
        "cases/granite_rqd_p32_rot_10.yaml",
        "cases/granite_rqd_p32_rot_20.yaml",
    ]

    config = MultiCaseBatchConfig(
        case_paths=case_paths,
        seeds=list(range(42, 47)),  # seed 수 확장
        face_positions=[10, 20, 30, 40, 50, 60, 70, 80],
        borehole_window=3,
        backend="mlx",
        batch_size=500,
        verbose=True,
        output_dir="legacy_results/outputs/nuclear_waste_decision",
        save_each_case=True,
        save_combined=True,
        correction_mode="pure",
    )

    runner = MultiCaseBatchRunner(config)
    result = runner.run()

    print_qp_distribution(result.face_rows)

    # 1. 처분장 시나리오: False Safe(부적합 암반에 굴착) 비용이 훨씬 큼
    print("\n[Scenario 1] High Risk of Unsuitable Rock (False Safe Cost = 20)")
    df_s1 = run_case_level_decision_analysis(
        result.face_rows, threshold=4.0, cost_safe=20.0, cost_alarm=1.0
    )

    # 2. 자원 최적화 시나리오: False Alarm(좋은 암반 포기) 비용도 무시할 수 없음
    print("\n[Scenario 2] Resource Optimization (False Safe=10, False Alarm=5)")
    df_s2 = run_case_level_decision_analysis(
        result.face_rows, threshold=4.0, cost_safe=10.0, cost_alarm=5.0
    )

    # 3. Bayesian Likelihood 추출 (첫 번째 케이스 예시)
    tester = DecisionUsefulnessTester(result.face_rows)
    likelihoods = tester.get_bayesian_likelihoods(bh_threshold=4.0, face_threshold=4.0)

    # --- 연구 보고용 테이블 출력 시작 (단일 비용 기준으로 통일) ---
    # Use the batch config's cost_fp/cost_fn so Table 3 and Table 4 are consistent.
    reporter = ResearchReporter()
    ResearchReporter.save_all_tables_as_csv(
        face_rows=result.face_rows,
        summary_rows=result.summary_rows,
        output_dir=config.output_dir,
        prefix="nuclear_decision",
        cost_fp=getattr(config, "cost_fp", 10.0),
        cost_fn=getattr(config, "cost_fn", 1.0),
    )

    # 4. Tidy Dataframe 내보내기
    export_tidy_decision_results(result.face_rows, config.output_dir)


if __name__ == "__main__":
    main()
