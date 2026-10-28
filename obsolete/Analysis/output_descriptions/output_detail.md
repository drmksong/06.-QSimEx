# Output Detail

이 문서는 프로젝트 산출물 설명이 여러 파일로 분산되어 있어 찾기 어려운 문제를 해결하기 위해 작성한 통합 안내서이다. 기존 [outputs_overview.md](outputs_overview.md), [borehole_rows.md](borehole_rows.md), [face_rows.md](face_rows.md), [summary_rows.md](summary_rows.md), [table1.md](table1.md), [table2.md](table2.md), [table3.md](table3.md), [table4.md](table4.md), [table5.md](table5.md)의 핵심 내용을 하나로 모아 정리했다.

## 1. 산출물 전체 요약

| 구분        | 산출물        | 핵심 내용                           | 주요 항목                                                                                                                                                 | 대표 생성 코드                                                                                               | 주요 용도                                   | 상세 문서                            |
| ----------- | ------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------- | ------------------------------------ |
| 로우 데이터 | borehole_rows | 보어홀 샘플 단위 측정값과 요약 통계 | case_name, seed, borehole_name, RQD_borehole_direct_mean, RQD_borehole_hudson_mean, Q_bh_mean, Qp_bh_mean, bh_fracture_count, miss_ratio, detection_ratio | src/core/tunnel.py 의 sample_borehole, src/core/comparison.py 의 comparisons_to_borehole_rows                | 로우레벨 디버깅, 보어홀 기반 검출 성능 분석 | [borehole_rows.md](borehole_rows.md) |
| 로우 데이터 | face_rows     | 면 단위 측정값과 면 통계            | case_name, seed, face_x_idx, face_x_coord, RQD_face_scanline, RQD_face_jv, RQD_face_conservative, Q_face_mean, Qp_face_mean, face_fracture_density        | src/core/tunnel.py 의 sample_face, src/core/comparison.py 의 comparisons_to_face_rows                        | 보어홀 대비 면 기준 검증, 면 분포 분석      | [face_rows.md](face_rows.md)         |
| 요약 데이터 | summary_rows  | 케이스 단위 통합 요약 통계          | case_name, seed, Q_bh_mean_case, Qp_bh_mean_case, Q_face_mean_case, RQD_mean_case, mean_detection_rate, mean_miss_ratio, false_positive_rate              | src/core/comparison.py 집계 로직, src/core/reporting.py 리포팅 루틴                                          | 시나리오 비교, 최종 보고 요약               | [summary_rows.md](summary_rows.md)   |
| 보고 표     | table1        | 전반적 요약 메트릭 표               | 케이스별 핵심 요약 지표                                                                                                                                   | src/core/reporting.py 의 ResearchReporter                                                                    | 보고서 첫 페이지 요약, 전체 성능 빠른 파악  | [table1.md](table1.md)               |
| 보고 표     | table2        | 세부 조건 분해 분석 표              | 밀도, 방향성, 임계치 구간별 집계 지표                                                                                                                     | src/core/reporting.py 또는 분석 스크립트 그룹 집계                                                           | 하위 조건별 성능 차이 분석                  | [table2.md](table2.md)               |
| 보고 표     | table3        | 종합 성능 지표 표                   | 민감도, 특이도, 정확도, AUC 유사 지표, 임계치별 비교                                                                                                      | src/core/decision_test.py 와 집계 결과 결합                                                                  | 방법 비교, 임계치 선택 근거                 | [table3.md](table3.md)               |
| 보고 표     | table4        | 베이지안 사후확률 기반 의사결정 표  | Prior, Likelihood, Posterior, expected loss, 권장 행동                                                                                                    | src/core/decision_test.py 의 get_bayesian_likelihoods, src/core/bayesian_update.py 의 bayesian_update_binary | 비용 고려 의사결정, 정책 논의 근거          | [table4.md](table4.md)               |
| 보고 표     | table5        | 임계값 및 비용 민감도 표            | Q' 판정 기준값 탐색 및 cost_fp, cost_fn 조합별 결과                                                                                                        | decision_test 기반 반복 계산 및 리포팅 집계                                                                  | 정책 민감도 점검, 안정 구간 확인            | [table5.md](table5.md)               |

## 2. table1 부터 table5까지 의미 설명

### table1 의미

table1은 전체 실험 결과를 가장 압축된 형태로 보여주는 요약 표이다. 이 표는 케이스별 핵심 지표를 한눈에 비교하도록 설계되었기 때문에 보고서 첫 부분에서 전체 경향을 빠르게 파악할 때 가장 유용하다. 연구 또는 실무 보고에서 독자가 먼저 확인해야 하는 기준선 역할을 하며, 이후의 상세 표는 table1에서 확인된 차이의 원인을 해석하는 단계로 연결된다.

### table2 의미

table2는 전체 평균만 보면 보이지 않는 조건별 차이를 드러내는 분해 분석 표이다. 예를 들어 절리 밀도나 방향성 조건이 달라질 때 성능이 어떻게 변하는지를 보여주는 데 적합하다. 따라서 table2는 특정 조건에서 결과가 갑자기 악화되거나 개선되는 이유를 설명하는 근거로 사용된다. 정책이나 기술 권고를 할 때는 평균보다 조건별 안정성이 더 중요하기 때문에 table2의 해석이 필수적이다.

### table3 의미

table3는 분류 성능을 정량적으로 판단하는 표이다. 민감도, 특이도, 정확도, AUC 유사 지표 같은 성능 값이 포함되므로 어떤 방법이 실제 의사결정에 더 유리한지 비교할 수 있다. 임계치가 달라질 때 성능이 어떻게 이동하는지도 함께 확인할 수 있어, 운영 기준값을 정할 때 핵심 자료로 쓰인다. 쉽게 말해 table3는 좋다 나쁘다를 느낌이 아니라 수치로 말해주는 표이다.

### table4 의미

table4는 관측값을 보고 바로 행동 결정을 내려야 하는 상황에 맞춘 의사결정 표이다. 이 표는 베이지안 업데이트를 사용해 사전정보와 관측정보를 결합하고, 행동별 기대손실을 계산해 최종 권장 행동을 제시한다. 여기서 베이지안 업데이트는 기존 믿음과 새 관측을 결합해 판단 확률을 갱신하는 절차이다. 따라서 table4는 단순 성능 비교를 넘어, 현장에서 굴착을 진행할지 보류할지 같은 실행 결정을 비용까지 반영해 설명하는 역할을 한다.

### table5 의미

table5는 임계값과 비용 가정을 바꿨을 때 결론이 얼마나 흔들리는지 보여주는 민감도 표이다. 특정 임계값에서만 좋아 보이는 결과인지, 가정이 달라도 비슷한 결론이 유지되는지를 확인할 수 있다. 의사결정은 단일 숫자에 과도하게 의존하면 위험해지므로, table5는 결론의 강건성을 점검하는 안전장치 역할을 한다. 정책 설계 단계에서는 table5를 통해 보수적 운영 구간을 먼저 찾는 것이 바람직하다.

## 3. 읽는 순서 안내

| 순서 | 먼저 볼 표 | 확인할 질문                                               | 다음 연결 표 |
| ---- | ---------- | --------------------------------------------------------- | ------------ |
| 1    | table1     | 전체적으로 어떤 케이스가 좋고 나쁜가                      | table2       |
| 2    | table2     | 어떤 조건에서 성능이 흔들리는가                           | table3       |
| 3    | table3     | 정량 성능과 임계치 선택 근거가 충분한가                   | table5       |
| 4    | table5     | 가정이 바뀌어도 결론이 유지되는가                         | table4       |
| 5    | table4     | 실제 행동 결정에서 기대손실이 최소가 되는 선택은 무엇인가 | summary_rows |

## 4. 산출물 사용 목적 정리

| 목적          | 우선 확인 산출물             | 이유                                      |
| ------------- | ---------------------------- | ----------------------------------------- |
| 코드 디버깅   | borehole_rows, face_rows     | 샘플 단위 추적이 가능해 원인 분석이 빠름  |
| 케이스 비교   | summary_rows, table1         | 케이스 단위 성능 차이를 빠르게 확인 가능  |
| 임계치 결정   | table3, table5               | 성능과 민감도를 함께 검토 가능            |
| 정책 의사결정 | table4, table5, summary_rows | 기대손실과 결론 안정성을 동시에 검토 가능 |

## 5. 관련 코드 위치

| 기능                      | 파일                                                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 데이터 생성 및 비교       | [src/core/tunnel.py](../../src/core/tunnel.py), [src/core/comparison.py](../../src/core/comparison.py)                         |
| RQD 및 Q 계산             | [src/core/rqd_calculator.py](../../src/core/rqd_calculator.py), [src/core/q_calculator.py](../../src/core/q_calculator.py)     |
| 의사결정 및 베이지안 갱신 | [src/core/decision_test.py](../../src/core/decision_test.py), [src/core/bayesian_update.py](../../src/core/bayesian_update.py) |
| 리포팅                    | [src/core/reporting.py](../../src/core/reporting.py)                                                                           |

## 6. 마무리

이 문서는 기존 분산 문서의 내용을 검색 없이 한 번에 확인할 수 있도록 통합한 기준 문서이다. 향후 컬럼별 정의를 더 세분화하려면 각 산출물의 실제 CSV 헤더를 기준으로 열 사전을 추가하는 방식으로 확장하면 된다.
