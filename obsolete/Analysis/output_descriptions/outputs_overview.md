# Outputs Overview

이 문서는 프로젝트에서 생성되는 주요 출력물 유형들의 의미와 용도를 간단히 정리합니다. 각 항목은 별도 문서로 링크되어 있습니다.

- `borehole_rows`: 개별 보어홀(시료) 수준의 측정값과 집계(분포 통계, RQD/Q/Q', 절리 검출 통계 등). 상세: `borehole_rows.md`.
- `face_rows`: 개별 면(face) 수준의 측정값과 집계(면 스캔라인 RQD, 면 Q/Q' 통계, 면 절리 목록 등). 상세: `face_rows.md`.
- `summary_rows`: 케이스(시나리오) 또는 멀티케이스 실행의 요약 통계(케이스별 평균/중앙값, 검출률, miss/false rates 등). 상세: `summary_rows.md`.
- `table1`..`table5`: 리포트용 표들. 각 표는 보고 목적(예: 전반적 요약, 민감도/특이도 분석, 의사결정 기대손실, 베이지안 의사결정 표, 임계치 민감도)별로 구성됩니다.
  - `table1`: 전체적 요약 메트릭(케이스별 주요 지표 모음). 상세: `table1.md`.
  - `table2`: 비교/민감도 관련 집계(예: 분포별 세부분석). 상세: `table2.md`.
  - `table3`: 검출·오류율 및 성능 지표(종합). 상세: `table3.md`.
  - `table4`: 베이지안 후행 확률 기반 의사결정 표 — 관찰별 사후확률, 기대손실, 권장 행동(Excavate/Skip). 상세: `table4.md`.
  - `table5`: Q' 판정 기준값·비용 민감도 분석. 상세: `table5.md`.

관련 코드(대표)

- 데이터 생성·비교: `src/core/tunnel.py`, `src/core/comparison.py`
- RQD/Q 계산: `src/core/rqd_calculator.py`, `src/core/q_calculator.py`
- 의사결정/베이지안 갱신: `src/core/decision_test.py`, `src/core/bayesian_update.py`
- 리포팅: `src/core/reporting.py` (예: `ResearchReporter.save_all_tables_as_csv()`)

용도 안내

- 개발/디버그: `borehole_rows`/`face_rows`는 로우레벨 디버깅 및 단일 샘플 추적용.
- 분석·논문 도표: `table1`~`table5`는 논문/보고서용 표를 자동 생성하기 위해 설계됨.
- 의사결정 점검: `table4`는 관찰 기반 의사결정(비용 고려)의 결과를 보여줘 문제 의료/토목 의사결정 논의에 사용.

다음 단계 제안

- 각 형식의 상세 컬럼 설명(예: 어떤 컬럼이 어디서 유래하는지)을 원하면 각 항목별 MD로 더 확장 가능합니다.
