# `summary_rows` — 의미와 용도

의미

- 케이스(또는 멀티케이스 집계) 수준의 요약 통계 행입니다. 여러 보어홀·면 샘플을 통합해 케이스별 평균, 중앙값, 검출률, miss/false 비율, Q/Q'의 전반적 분포 요약 등을 제공합니다.

주요 컬럼(일반적)

- 식별자: `case_name`, `seed`, (멀티케이스일 경우 집계 키)
- 집계 통계: `Q_bh_mean_case`, `Qp_bh_mean_case`, `Q_face_mean_case`, `RQD_mean_case`
- 검출/오류 지표: `mean_detection_rate`, `mean_miss_ratio`, `false_positive_rate`
- 의사결정 지표(선택적): 비용 기반 기대손실의 케이스 평균 등

생성 코드(대표)

- 요약 집계: `src/core/comparison.py` + 리포터(`src/core/reporting.py`) 내부 집계 루틴

용도

- 실험/시나리오 간 비교, 파라미터 민감도 분석, 최종 리포트용 케이스 요약 제공.
