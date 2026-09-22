import sys
import os
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.case_library import CaseLibrary
from batch_runner import BatchRunner, BatchConfig
from src.core.hypothesis_test import BatchHypothesisTester
from src.core.decision_test import DecisionUsefulnessTester

# YAML 또는 이름으로 로드
case = CaseLibrary.load_case("../cases/granite_2sets.yaml")
# 또는:
# case = CaseLibrary.load_case("granite_2sets")

print("CASE:", case.name)
print("DESC:", case.description)
for js in case.joint_config.joint_sets:
    print(f"  {js.name}: P32={js.P32}")

config = BatchConfig(
    seeds=[42, 43, 44],
    face_positions=[10, 20, 30, 40, 50, 60, 70, 80],
    borehole_window=3,
    backend="mlx",
    batch_size=500,
    verbose=True,
    output_dir="outputs",
)

runner = BatchRunner(case, config)
result = runner.run()

print(len(result.face_rows))
print(len(result.borehole_rows))
print(len(result.summary_rows))

hyp_tester = BatchHypothesisTester(result.face_rows)
test_results = hyp_tester.run_all()
hyp_tester.print_report(test_results)


# Decision usefulness
dec_tester = DecisionUsefulnessTester(result.face_rows)

res = dec_tester.evaluate(
    threshold=4.0, use_qprime=True, cost_false_safe=10, cost_false_alarm=3
)
dec_tester.print_summary(res)

# Threshold sweep도 같이 추천
sweep = dec_tester.sweep_thresholds(
    thresholds=[0.1, 1.0, 4.0, 10.0, 40.0],
    use_qprime=True,
    cost_false_safe=10,
    cost_false_alarm=3,
)

print("\nThreshold sweep")
for r in sweep:
    print(r)

# 조건별 분석
regime = dec_tester.evaluate_by_regime(
    threshold=4.0, use_qprime=True, cost_false_safe=10, cost_false_alarm=3
)

print("\nBy density")
for k, v in regime["by_density"].items():
    print(k, v)

print("\nBy orientation")
for k, v in regime["by_orientation"].items():
    print(k, v)

print("\nBy density x orientation")
for k, v in regime["by_density_orientation"].items():
    print(k, v)



face_qp = np.array([r["Qp_face_mean"] for r in result.face_rows], dtype=float)
bh_qp = np.array([r["Qp_borehole_mean"] for r in result.face_rows], dtype=float)

print("Face Qp min/p10/p25/p50/p75/p90/max:")
print(np.min(face_qp), np.percentile(face_qp, [10,25,50,75,90]), np.max(face_qp))

print("BH Qp min/p10/p25/p50/p75/p90/max:")
print(np.min(bh_qp), np.percentile(bh_qp, [10,25,50,75,90]), np.max(bh_qp))

thresholds = np.percentile(face_qp, [10,20,30,40,50,60,70,80,90]).tolist()

print("\nData-driven threshold sweep")
sweep = dec_tester.sweep_thresholds(
    thresholds=thresholds,
    use_qprime=True,
    cost_false_safe=10,
    cost_false_alarm=3
)

for r in sweep:
    print(r)