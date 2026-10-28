# Q' 채택 의사결정 진단 보고서 (초안)

- 작성일: 2026-07-08
- 범위: QSimEx 전체 코드 진단 + 대표 케이스 실행 결과 기반
- 독자: 기술자/정책자 조언 의사결정자
- 의사결정 축: 안전 우선, 경제성 후순위

## 1) 의사결정 질문

본 보고서의 1차 의사결정 질문은 다음과 같다.

- Q'을 처분터널 사전 판단 체계에 채택할 것인가?
- 채택 시 권고 수준은 권고/비권고/비확정 중 어디인가?

2차 현장 적용 질문(채택 이후)은 "해당 구간 굴착 권고/비권고/비확정"으로 분리한다.

## 2) 기술적 목적과 분석 방법

### 2.1 코드상 목적

프로젝트는 시추공 기반 값과 굴진면 값을 비교해 Q'의 설명력/예측 유용성을 평가하도록 구성되어 있다.

- 메인 실행 진입: [run_cli.py](../run_cli.py), [run_gui.py](../run_gui.py)
- 비교 엔진: [src/core/comparison.py](../src/core/comparison.py)
- 의사결정 평가(ROC/Cost/Net Benefit): [src/core/decision_test.py](../src/core/decision_test.py)
- Bayesian 업데이트: [src/core/bayesian_update.py](../src/core/bayesian_update.py)
- 리서치 테이블 생성: [src/core/reporting.py](../src/core/reporting.py)

### 2.2 이번 진단에서 사용한 실증 방법

- 대표 케이스 데이터셋: outputs/disposal_lowfract_curated/all_cases_face_rows.csv (5케이스, 300행)
- 유효성 지표: Qp_borehole_mean vs Qp_face_mean 상관계수, 오차(RMSE, MAE, bias)
- 편익 지표(생략 대비):
  - 베이스라인(생략): 케이스별 다수결 상수 판정
  - Q' 전략: 케이스별 판정 기준값 탐색 후 판정
  - 통계검정: paired McNemar exact p-value
- 판정 레벨:
  - 권고: uplift >= 0.10 and p < 0.05
  - 비권고: uplift <= -0.05 and p < 0.05
  - 비확정: 그 외

## 3) 실행 근거

### 3.1 대표 케이스 재실행

- 실행: scenario_07_isotropic 단일 재실행
- 결과: 파이프라인 정상 수행(DFN 생성, Q/Q' 계산, face 비교, 보고서 출력)
- 근거 스크립트: [run_cli.py](../run_cli.py)

### 3.2 분석 산출물 생성

이번 진단에서 아래 분석 파일을 신규 생성했다.

- 케이스별 권고 레벨: [outputs/disposal_lowfract_curated/analysis/qprime_case_recommendation.csv](../outputs/disposal_lowfract_curated/analysis/qprime_case_recommendation.csv)
- Q' 판정 기준값 탐색 전체: [outputs/disposal_lowfract_curated/analysis/qprime_threshold_sweep_case.csv](../outputs/disposal_lowfract_curated/analysis/qprime_threshold_sweep_case.csv)
- 집계 요약: [outputs/disposal_lowfract_curated/analysis/qprime_analysis_summary.json](../outputs/disposal_lowfract_curated/analysis/qprime_analysis_summary.json)

## 4) 핵심 결과

### 4.1 Q' 유효성(설명력) 관찰

- 전체(300행) 기준 Pearson r = 0.9508, p = 9.58e-154로 매우 강한 연관
- 그러나 케이스별 상관은 불안정(약하거나 음수 케이스 존재)
- 해석: 전체 풀링에서는 강하지만, 케이스 단위 의사결정 신뢰성은 균질하지 않음

### 4.2 Q' 절차 생략 대비 편익

케이스별 권고 결과:

- 권고: 0
- 비권고: 1 (scenario_06_layered_density)
- 비확정: 4

요약 통계:

- mean accuracy uplift = -0.0433
- 현재 대표 케이스 범위에서, Q' 절차가 생략 대비 일관된 우위를 보였다고 결론내리기 어려움

## 5) 문제점 진단 (코드+결과 관점)

1. 임계값 민감도 높음

- 케이스별 최적 임계값이 분산되어 공통 운영 기준으로 고정하기 어려움

2. 케이스별 성능 비균질

- 일부 케이스에서는 개선이 없거나 악화되어 안전 우선 정책에서 즉시 일반화가 곤란

3. 지표 간 신호 불일치 가능성

- 비교 엔진에서 fracture miss/detection 등 구조적 진단치를 산출하나, Q' 판정 성능과 단순 선형적으로 연결되지 않음

4. 의사결정 기준의 제도화 미완성

- 코드상 ROC/비용 프레임은 존재하나, 국가사업 적용 수준의 공식 임계값/절차 표준은 아직 연구 단계

## 6) 권고안 (진단/권고만)

### 6.1 1차 결론: Q' 채택 여부

- 현재 판정: 비확정
- 이유: 대표 케이스 범위에서 통계적으로 일관된 생략 대비 우위 미확인

### 6.2 조건부 운영 권고

- 전면 채택/폐기 결정보다는 "조건부 파일럿"이 타당
- 케이스 군별 임계값 정책(단일값 대신 범위 정책)으로 재평가 필요

### 6.3 비권고 케이스 처리

- scenario_06_layered_density 유형에서는 현재 Q' 단독 판정 비권고
- 해당 유형은 보조 지표(예: 방향성/밀도 진단치) 결합 규칙이 필요

## 7) 최종 의사결정 제안 (3레벨)

- 권고: 아직 해당 없음
- 비권고: layered_density 유사 조건
- 비확정: 현재 대표 케이스 전체 수준의 일반 정책

정리하면, 현 시점에서 Q'는 유망한 신호이지만 "정책 채택 확정" 단계에는 부족하다. 안전 우선 원칙상 현재 결론은 비확정이 타당하다.

## 8) 다음 단계 TODO (실행 백로그)

1. 케이스군 확장(경계/불리 조건 포함)
2. 케이스 단위 임계값 안정성 분석(bootstrap CI)
3. Q' + 구조 진단치 결합 판정기 설계
4. 비확정 조건의 정량 규칙화
5. 파일럿 운영 프로토콜 초안 수립

---

부록 상세는 [docs/qprime_adoption_appendix_2026-07-08.md](qprime_adoption_appendix_2026-07-08.md) 참조.
