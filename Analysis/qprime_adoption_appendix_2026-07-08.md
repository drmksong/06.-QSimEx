# 부록 A. 실행 및 통계 근거

## A1. 데이터 소스

- face-level 통합: [outputs/disposal_lowfract_curated/all_cases_face_rows.csv](../outputs/disposal_lowfract_curated/all_cases_face_rows.csv)
- summary 통합: [outputs/disposal_lowfract_curated/all_cases_summary_rows.csv](../outputs/disposal_lowfract_curated/all_cases_summary_rows.csv)

표본 요약:

- 총 행수: 300
- 케이스 수: 5
- 케이스별 60행

## A2. 대표 재실행 증빙

- 실행 명령(환경): conda run -n dlo-cq python run_cli.py --case scenario_07_isotropic --face-positions 10 20 30 --backend auto --batch-size 100
- 상태: 정상 완료
- 핵심 관찰: DFN 생성, Q/Q' 계산, 비교 리포트까지 end-to-end 수행됨

## A3. 유효성 기본 통계

전체 기준(300행):

- Pearson r(Qp_borehole_mean, Qp_face_mean) = 0.950838
- p-value = 9.58e-154
- RMSE = 3.1002
- MAE = 1.6337
- Bias = -0.1219

주의:

- 케이스별 상관은 일관되지 않으며, 일부는 약한 양/음의 상관으로 변동함

## A4. 임계값 탐색 및 생략 대비 검정

생성 파일:

- 전체 스윕: [outputs/disposal_lowfract_curated/analysis/qprime_threshold_sweep_case.csv](../outputs/disposal_lowfract_curated/analysis/qprime_threshold_sweep_case.csv)
- 케이스별 최종 판정: [outputs/disposal_lowfract_curated/analysis/qprime_case_recommendation.csv](../outputs/disposal_lowfract_curated/analysis/qprime_case_recommendation.csv)
- 요약 JSON: [outputs/disposal_lowfract_curated/analysis/qprime_analysis_summary.json](../outputs/disposal_lowfract_curated/analysis/qprime_analysis_summary.json)

판정 규칙:

- 권고: uplift >= 0.10 and p < 0.05
- 비권고: uplift <= -0.05 and p < 0.05
- 비확정: 나머지

결과:

- 권고 0, 비권고 1, 비확정 4
- mean uplift = -0.0433

## A5. 코드 진단 근거 위치

- 비교 로직/진단 변수: [src/core/comparison.py](../src/core/comparison.py)
- 의사결정 성능/비용/ROC: [src/core/decision_test.py](../src/core/decision_test.py)
- Bayesian 업데이트: [src/core/bayesian_update.py](../src/core/bayesian_update.py)
- 리서치 테이블 생성: [src/core/reporting.py](../src/core/reporting.py)

## A6. 해석 시 제한사항

1. 임계값은 본 연구에서 탐색 중이며 고정 표준 아님
2. 현재 대표 케이스는 확장 예정이며, 정책 일반화를 위한 표본이 충분하다고 단정하기 어려움
3. 케이스 단위 의사결정에 필요한 추가 보조 신호 결합 검증이 필요함
