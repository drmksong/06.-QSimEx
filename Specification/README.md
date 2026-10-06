# QSimEx 작업 기록

이 폴더는 날짜별 작업 메모, 검토용 PDF, 아직 정리되지 않은 연구 기록을 보관하는 작업 영역입니다.

## 문서 역할과 최신성

문서 간 충돌이 있으면 날짜가 붙은 최신 결정과 그 결정이 지정한 현재 적용 상태를 따른다.
오래된 계획·분석은 역사적 근거로 보존하되, 실행 규칙으로 오인될 위험이 있으면 문서 상단의
현재 적용 상태와 후속 결정 기록을 먼저 확인한다. 기존 결과나 과거 결정을 최신 규칙으로
소급 변환하지 않는다.

| 문서 | 역할 / 현재 사용 |
|---|---|
| [DesignSpec_20260922.md](DesignSpec_20260922.md) | 현재 QSimEx 설계 계약의 기준. 날짜별 후속 결정과 논문 평가 항목 포함 |
| [20261006.md](20261006.md) | Euler campaign 파라미터 탐색 후속 결정과 구현 전 미결 사항 |
| [20261005.md](20261005.md) | `src/core`와 새 Euler campaign의 중복 검토 기록 및 다음 구현 단계의 재사용 검토 절차 |
| [CoverageAdaptiveExecutionPlan_20260925.md](CoverageAdaptiveExecutionPlan_20260925.md) | Adaptive campaign의 작업·실행 계획. 2026-10-04 현재 계약 요약 및 후속 실행 규칙 포함 |
| [QPrimeCutoffSelectionMethod_20260924.md](QPrimeCutoffSelectionMethod_20260924.md) | Q′ cutoff 방법론 초안. Legacy row-level 방법과 새 longitudinal profile 연결 미결 사항을 구분 |
| [ImplementationPlan_20260925.md](ImplementationPlan_20260925.md) | Phase 3 구현 및 Stage handoff 이력. 2026-10-04 후속 정합성 경계 포함 |
| [ImplementationPlan_20260924.md](ImplementationPlan_20260924.md) | 초기 기준값 구현 계획의 역사적 기록 |
| [ProfileExploration_20260924.md](ProfileExploration_20260924.md) | Legacy row-level 1차 profile 탐색의 불변 결과 기록 |
| [ExperimentEvidence_20260927.md](ExperimentEvidence_20260927.md) | 당시 signature 실험의 관측 근거. 최신 profile score로 재해석하지 않음 |

Cutoff method의 미결 선택(새 longitudinal profile의 표본 단위, 길이 가중, 반복측정
의존성 등)은 합의 전까지 자동 추정·구현하지 않는다. Signature coverage score는 Q′
cutoff selector와 별개의 운영 지표다.

## 규칙

- 확정된 사양과 재사용할 보고서는 `../docs/`로 옮깁니다.
- 날짜별 메모는 `YYYYMMDD.md` 형식을 사용합니다.
- PDF 원본은 검토 이력을 보존하기 위해 이 폴더에 둘 수 있지만, 핵심 결론은 Markdown 기술서에도 기록합니다.
- 이 폴더의 문서는 실행 코드가 직접 참조하는 공식 입력이 아닙니다.
