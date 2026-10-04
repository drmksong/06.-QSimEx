# QSimEx Phase 3 Implementation Plan

- 작성일: 2026-09-25
- 단계: Phase 3. Q' 판정 기준값 탐색 엔진
- 기준 문서:
  - `Specification/DesignSpec_20260922.md`
  - `Specification/QPrimeCutoffSelectionMethod_20260924.md`
  - `Specification/ProfileExploration_20260924.md`
- 관련 코드:
  - `src/core/qprime_cutoff_search.py`
  - `src/core/profile_exploration.py`
  - `src/core/reporting.py`

> **계획 적용 상태 (2026-10-04):** 이 계획의 Phase 3 목적과 구현·실험 이력은
> 보존한다. 그러나 row-level `Qp_bh_mean` 입력과 예전 후보 생성/update 절차를 새
> geometry 기반 profile 작업의 현재 실행 명세로 사용하지 않는다. 최신 Q′ 계산, geometry,
> profile 및 round-length 계약은 [DesignSpec_20260922.md](DesignSpec_20260922.md)의
> 5.8을 따른다. Signature coverage update는 DesignSpec 5.6.9와
> [CoverageAdaptiveExecutionPlan_20260925.md](CoverageAdaptiveExecutionPlan_20260925.md)의
> 2026-10-04 addendum을 따른다. Cutoff 분석에서 longitudinal profile의 표본 단위,
> 가중 및 repeated-measure 처리 방식은 아직 미결이다. 이를 결정하기 전까지 새 profile에
> 대한 PR/TR/POST 또는 cutoff 자동 산출 task를 실행 가능한 것으로 간주하지 않는다.

## 1. 목적

가상굴착 시뮬레이션 결과를 이용하여 시추공 `Q'_BH`의 3단계 판정 후보를 탐색한다.
이 단계의 결과는 시뮬레이션 기반 잠정 가이드이며, 실제 현장 안전이나 처분 적합성을
자동으로 보증하지 않는다.

판정 구조는 다음과 같다.

```text
Q'_BH < lower_cutoff
	 -> hold: 굴착 보류·생략 후보

lower_cutoff <= Q'_BH < upper_cutoff
	 -> uncertain: 추가 조건 확인 구간

Q'_BH >= upper_cutoff
	 -> excavate: 굴착 진행 후보
```

## 2. 용어와 적용 범위

- 가상굴착: 동일한 DFN domain에 터널·굴진면 조건을 적용하여 `Q'_face`와 참조지표를
  계산하는 시뮬레이션 절차
- 실제굴착: 현장에서 암반을 실제로 굴착하고 관측·조사·계측하는 절차
- `Q'_BH`: 실제 운영 판정에 사용할 수 있는 굴착 전 시추공 입력
- `Q'_face`: 운영 판정 입력이 아닌 가상굴착 참조 결과
- `PR/TR/POST`: 프로파일의 변화 전·변화·변화 후 안정 상태
- 처분 적합·부적합: EFPC 또는 향후 독립 평가 adapter가 제공하는 별도 공학적 결과

`Qp_face_mean`을 단일 threshold로 잘라 적합·부적합 라벨을 만들지 않는다. EFPC 또는
독립 평가 결과가 연결되기 전에는 `suitable`, `unsuitable`, false-safe,
false-reject, sensitivity, specificity를 생성하거나 주장하지 않는다.

## 3. 입력 계약

### 3.1 Phase 3 필수 입력

시추공 관측 단위의 각 행에 다음 값을 사용한다.

- `Qp_bh_mean`
- `Qp_face_mean`
- `case_name`
- `seed`
- 독립 DFN domain을 식별할 수 있는 domain 정보
- 절리 교차·밀도·방향성·크기 등 참조 프로파일 지표

`Qp_bh_mean`이 결측이면 `0.0`으로 대체하지 않고 탐색에서 제외한다. 관측 단위는
face row가 아니라 borehole row로 고정한다.

### 3.2 선택 입력

EFPC 또는 독립 평가 adapter가 연결된 경우에만 별도 결과를 입력한다. 이 결과는
Phase 3의 가상굴착 프로파일 탐색을 위해 필수로 요구하지 않으며, 성능·위험도·기대
손실 평가를 수행할 때만 명시적으로 연결한다.

## 4. 탐색 절차

1. 설정 파일에서 Q' 후보값을 생성한다.

- 현재 범위: `[0, 400]`
- `[0.1, 400]` 기존 로그 10구간의 첫 경계 `0.1`을 `0`으로 교체해 총 10 bins
- 11개 primary bin, 12개 경계값

2. 각 `Q'_BH` 후보 구간별로 표본 수와 참조 프로파일 분포를 계산한다.
3. `Q'_face`, 절리 교차, 밀도, 방향성, 크기 관련 프로파일을 개별적으로 유지한다.
4. 프로파일별 인접 구간 변화량, 분포 범위, domain 반복성을 계산한다.
5. 각 프로파일을 `PR`, `TR`, `POST` 상태로 표시한다.
6. 모든 핵심 프로파일의 공통 `PR` 영역과 공통 `POST` 영역을 교집합으로 계산한다.
7. 공통 PR의 끝을 lower 후보, 공통 POST의 시작을 upper 후보로 제안한다.
8. 공통 영역 부재, 상태 충돌, 표본 부족, `lower >= upper`이면 숫자를 확정하지 않고
   `not_identifiable`을 반환한다.

프로파일을 가중합하거나 새 종합지수로 합치지 않는다. 정책 허용치나 임의의 단일
`4.0` 기준도 도입하지 않는다.

## 5. 산출물

### 5.1 기계 판독 결과

`results/qprime_cutoff_search_<timestamp>.json` 또는 parquet에 다음을 저장한다.

- 후보 cutoff 목록
- cutoff별 구간 표본 수
- 프로파일별 분포와 상태
- domain별 반복성 및 변동성
- 공통 PR/POST 영역
- `lower_cutoff`, `upper_cutoff`
- `status`: `identified` 또는 `not_identifiable`
- 표본 부족·상태 충돌·결측 등 경고 목록
- EFPC 또는 독립 평가 결과 미연결 상태

비유한 수치와 계산 불가 값은 JSON `null`로 저장한다.

### 5.2 보고서 원칙

EFPC가 없는 Phase 3 보고서에는 다음만 포함한다.

- Q' 구간별 노출량과 분포
- 가상굴착 참조 프로파일 변화
- PR/TR/POST 상태
- lower/upper 후보 또는 `not_identifiable`
- 적용 범위와 표본 부족 경고

처분 적합성 성능이나 안전성 보증을 의미하는 표와 문구는 출력하지 않는다.

## 6. 구현 순서

1. `qprime_cutoff_search.py`의 Phase 3 입력·출력 계약을 정리한다.
2. `profile_exploration.py`와 연결하여 borehole row 기반 구간 프로파일을 계산한다.
3. 프로파일 상태와 공통 PR/POST 교집합 결과를 저장한다.
4. `lower_cutoff`, `upper_cutoff`와 `not_identifiable` 조건을 연결한다.
5. `ResearchReporter`가 단일 `Best threshold`나 임시 `4.0` 라벨을 출력하지 않고
   Phase 3 결과 JSON/CSV를 보고하도록 연결한다.
6. EFPC 또는 독립 평가 adapter 연결 지점은 별도 인터페이스로 남기되, 현재 단계에서
   실제 적합성 라벨을 생성하지 않는다.

## 7. 테스트 계획

모든 테스트는 현재 프로젝트 표준인 `unittest`로 작성·실행한다.

- cutoff 생성 범위와 로그 간격 검증
- borehole row 단위 집계 검증
- 결측 `Qp_bh_mean` 제외 검증
- `Qp_face_mean` 단일 threshold 라벨이 생성되지 않는지 검증
- PR/TR/POST 상태 검증
- 공통 PR/POST 교집합 검증
- 상태 충돌 시 `not_identifiable` 검증
- `lower >= upper` 검증
- EFPC 입력이 없을 때 false-safe/false-reject가 생성되지 않는지 검증
- 결과 JSON의 `null` 직렬화 검증

검증 명령:

```bash
conda run -n dlo-cq python -m unittest discover -s src/test -p 'test_*.py' -v
```

## 8. 완료 기준

- 동일한 borehole row 입력으로 동일한 후보 구간과 프로파일 상태를 재현할 수 있음
- `Qp_face_mean`을 단일 threshold로 적합·부적합 라벨화하지 않음
- lower와 upper가 서로 독립적으로 기록됨
- 공통 변화점 또는 안정 구간이 없으면 `not_identifiable` 반환
- EFPC 없이도 가상굴착 참조 프로파일과 구간 노출량을 산출할 수 있음
- EFPC 없이 false-safe, false-reject, sensitivity, specificity를 계산하지 않음
- 활성 보고서에 임시 `Best threshold` 또는 `4.0` 기반 판정이 재등장하지 않음
- 관련 unittest가 모두 통과함

## 9. 오늘의 작업 순서

- [x] 현재 `qprime_cutoff_search.py`와 `profile_exploration.py`의 입력·출력 계약 대조
- [x] borehole row 기반 프로파일 집계 테스트 작성
- [x] PR/TR/POST 상태 산정 및 공통 교집합 테스트 보강
- [x] lower/upper 후보와 `not_identifiable` 결과 스키마 확정
- [x] Phase 3 전용 보고서 연결
- [x] 전체 unittest 실행 및 결과 기록

실제 저장 결과 4개 케이스와 통합 1,200행을 새 탐색기에 적용한 결과는 현재
`not_identifiable`이었다. 초기 로그 구간 중 실제 표본이 있는 구간이 제한되고
공통 PR/POST 영역이 형성되지 않았기 때문이며, 숫자를 임의로 확정하지 않고 이
사유를 결과에 기록한다.

## 10. 가정 업데이트와 coverage 보강 계획

기존 H1~H5 가설은 삭제하지 않고 `src/core/hypothesis_test.py`의 탐색적 보조
가설로 보존한다. 다만 현재 pooled row 분석의 p-value를 lower/upper 확정 근거로
사용하지 않는다. 동일 seed/domain에서 나온 여러 face row의 반복 구조를 고려하지
않았고, H5는 현재 파일럿 결과에서 지지되지 않았기 때문이다.

Phase 3의 주 가설은 다음과 같이 업데이트한다.

> 충분한 독립 DFN seed/domain을 확보하면 낮은 `Q'_BH` 구간에서 불리한 참조
> 프로파일이, 높은 `Q'_BH` 구간에서 안정된 참조 프로파일이 여러 조건군에 걸쳐
> 공통으로 반복된다.

현재 관측되지 않은 Q' 구간은 즉시 최종 `not_identifiable`로 처리하지 않는다.
먼저 다음 coverage audit을 수행한다.

- Q' 구간별 row 수, seed 수, domain 수, case 수 기록
- 빈 구간과 실제 변화가 있는 구간을 구분
- 관측 범위 안의 빈 구간을 보강 대상으로 지정
- 관측 범위 밖은 configuration으로 생성 가능한지 별도 표시
- P32, 절리군 수, 방향성, 크기 분포, 구조 배열, 터널·시추공 방향, seed를 보강
  configuration 후보로 관리
- 보강 configuration으로 GPU pilot을 실행하고 실제 Q' 이동 범위를 확인
- configuration 선택용 seed와 최종 Train/Validation seed를 분리

새로운 결과 상태는 다음 원칙을 따른다.

- `UNOBSERVED`: 해당 구간의 자료가 아직 없어 configuration 보강이 필요함
- `provisional`: 후보는 보이나 domain 수·재현성·일부 프로파일 근거가 부족함
- `identified`: 공통 PR/POST와 최소 domain·불확실성 조건을 만족함
- `not_identifiable`: coverage 보강 후에도 공통 구조가 없거나 핵심 프로파일이
  충돌함

다음 구현 작업:

- [x] Q' coverage audit 및 configuration gap report 작성
- [x] 빈 구간을 `TR`이 아닌 `UNOBSERVED`로 분리
- [ ] 관측 범위 기반 보조 binning과 고정 로그 bin 결과 비교
- [x] configuration 보강용 GPU pilot 실행 계획 작성
- [ ] seed/domain 단위 cluster bootstrap 또는 계층 모델 검토

Coverage pilot 결과:

- 기존 1,200행 관측 범위: `Qp_bh_mean=5.35~47.87`
- 저Q pilot `scenario_11_coverage_low_q`: `3.20~4.35`; 기존 최저값은 개선했으나
  `2.76` 미만 구간은 아직 미관측
- 고Q refined pilot `scenario_12_coverage_high_q`: `Qp_bh_mean=266.67`;
  기존 고Q 빈 구간 `76.15~400`의 도달 가능성을 확인함
- 저Q refined pilot `scenario_13_coverage_low_q_refined`:
  `Qp_bh_mean=1.86~2.06`; 기존 저Q 빈 구간 `0.1~2.76`의 도달 가능성을 확인함
- 두 pilot 모두 `backend=mlx` GPU로 실행했으며, coverage pilot 결과는 최종
  calibration/validation 자료에 포함하지 않음
- 다음 작업: 양쪽 reachability configuration을 독립 seed 여러 개로 확장하여
  각 빈 구간의 domain 지원을 확보하고, coverage audit과 profile search를 다시
  수행함. 이후에만 calibration/validation 자료 편입 여부를 검토함

## 11. 남은 작업

### 우선순위 1. Coverage 확장

- [ ] 저Q refined configuration을 독립 seed 여러 개로 확장
- [ ] 고Q refined configuration을 독립 seed 여러 개로 확장
- [ ] 기존 중간 Q configuration과 동일한 seed/domain 기록 체계로 통합
- [ ] coverage 확장 자료를 최종 calibration/validation 자료와 분리
- [ ] 구간별 최소 독립 domain 수를 확인한 뒤 profile search 재실행

완료 조건:

- 저Q·중간Q·고Q 각 구간의 row 수와 독립 seed/domain 수를 확인할 수 있음
- configuration 선택용 seed가 Train/Validation seed와 섞이지 않음
- coverage 확장 후에도 특정 구간이 비면 reachability 또는 적용 범위 밖 사유를 기록함

### 우선순위 2. Profile 상태 판정 보완

- [ ] 빈 bin을 `TR`이 아닌 `UNOBSERVED`로 실제 상태 계산에 반영
- [ ] 고정 로그 bin과 관측 범위 기반 adaptive binning을 비교
- [ ] `UNOBSERVED`, `provisional`, `identified`, `conflicting`,
      `not_identifiable` 상태를 결과 스키마에 반영
- [ ] 관측 범위 밖 구간과 관측 범위 내부 gap을 분리 보고

완료 조건:

- 빈 구간이 변화 구간으로 오분류되지 않음
- 후보값이 부족한 경우에도 부족 원인과 configuration 보강 방향이 기록됨

### 우선순위 3. 통계적 재현성 검증

- [ ] seed/domain 단위 cluster bootstrap 구현
- [ ] 필요 시 domain random effect를 포함한 계층 모델 검토
- [ ] profile별 변화점과 안정 구간의 불확실성 계산
- [ ] H1~H5 pooled p-value를 최종 lower/upper 근거로 사용하지 않도록 유지

완료 조건:

- face row 반복 측정이 독립 표본으로 과대계산되지 않음
- lower/upper 후보의 domain 재현성과 변동 범위를 보고할 수 있음

### 우선순위 4. Calibration과 Blind Validation

- [ ] coverage 확장 후 Train domain에서 lower/upper 후보 산출
- [ ] Validation domain을 별도로 생성하고 경계값을 고정 적용
- [ ] Validation에서 경계값 재튜닝 금지
- [ ] 적용 조건별 성능과 최악 조건을 별도 보고

완료 조건:

- Train과 Validation에 동일 seed/domain이 중복되지 않음
- Validation 결과가 잠정 후보를 지지하는지 또는 폐기하는지 명확히 기록됨

### 우선순위 5. EFPC 연계와 현장 적용

- [ ] EFPC 또는 독립 평가 adapter 인터페이스 정의
- [ ] 처분 적합·부적합 결과가 연결될 때만 false-safe·false-reject 계산
- [ ] domain of applicability와 판정 불가 조치 연결
- [ ] 외부 평가가 연결되기 전에는 안전성 보증 문구를 출력하지 않음

현재 단계에서는 EFPC 연계를 구현하지 않고 인터페이스와 적용 시점만 보존한다.

## 12. 2026-09-26 다음 작업

내일은 기존 signature의 seed를 대량으로 먼저 확장하지 않고, coverage gap을 메우는
iteration을 수행한다.

### 작업 순서

1. Round 0 결과와 coverage pilot을 provenance 기준으로 분리 확인한다.
2. 현재 보유한 scenario/signature 목록을 정리하고, 각 signature를 seed 1개씩 실행할
   Iteration 0 manifest를 확정한다.
3. 저Q `0.1~5.278`과 고Q `103.3~400` gap에 대해 신규 generation signature 후보를
   생성한다.
4. 신규 signature를 기존 목록에 추가하고, 기존 + 신규 전체를 seed 1개씩 재-sweep한다.
5. iteration 전후의 Q' 범위, 새 bin, `UNOBSERVED`, 중복도, signature/domain 수를
   `results/coverage_rounds/ledger.jsonl`에 기록한다.
6. 실제 목표 bin을 만들고 중복을 줄인 signature만 seed `5~10`개로 확장한다.
7. low/middle/high profile을 scenario/signature별로 분석하고, pooled 결과는 보조로
   분리한다.
8. 필요한 domain 수가 확보되면 `B=200` bootstrap을 실행하고 안정성에 따라 `B=500`
   으로 확장한다.

### 내일의 완료 산출물

- `iteration_001` scenario/signature 실행 manifest
- 신규 signature 후보 YAML과 후보 JSON
- iteration 전후 coverage audit
- 업데이트된 `results/coverage_rounds/ledger.jsonl`
- scenario/signature별 Q' 범위와 profile 요약
- 다음 iteration에서 추가할 gap/signature 결정 기록

### 내일의 중단 조건

- GPU backend가 확인되지 않으면 대규모 실행을 시작하지 않는다.
- 신규 signature가 기존 중앙 구간만 반복하면 해당 후보를 확장하지 않는다.
- 새 signature가 목표 gap에 도달하지 못하면 seed를 늘리지 않고 feature를 다시 조정한다.
- 최소 3회의 screening 이후에도 gap이 남고 방향성·coverage 기여가 재현되지 않으면
  `exclude_as_unreachable`, 적용 범위 밖 또는 `not_identifiable`로 기록을 검토한다.

## 13. 2026-09-26 계획 변경 및 누적 근거

### 13.1 기존 계획과의 차이

기존 계획은 전체 scenario/signature를 seed 1개씩 sweep한 뒤 coverage 결과에 따라
필요한 signature를 추가하고, 기여한 signature를 후속 seed 확장 대상으로 검토하는
구조였다. 이 원칙은 유지하되, 후보 signature의 수와 생성 규칙은 coverage 결과를
확인한 뒤 단계적으로 정한다.

어제 확보한 기존 5개 case의 500개 domain은 다시 대량 실행하지 않고 baseline으로
재사용한다. 저Q·고Q pilot은 reachability 근거로 사용하되, metadata가 부족한 pilot은
필요한 경우에만 새 runner로 provenance를 보강한다.

### 13.2 현재 실행 규칙

1. 현재 합의된 기존 signature를 screening portfolio로 구성한다.
2. 첫 sweep에서는 모든 signature에 동일한 공통 seed `S0`을 사용한다.
3. Q' 범위, 새 bin, `UNOBSERVED` 감소, 중앙부 중복도, profile 방향을 signature별로
   비교한다.
4. 다음 sweep에서는 전체 pool에 공통 seed `S1`을 사용하여 결과 반복성을 확인한다.
5. 두 sweep에서 목표 gap과 profile 방향을 모두 보인 signature만 후속 seed 확장
   대상으로 검토한다.

공통 seed를 사용하는 이유는 signature 효과와 seed 효과를 분리하기 위해서다. 후보마다
서로 다른 seed를 배정하면 signature 차이인지 domain 난수 차이인지 구분하기 어렵다.

### 13.3 변경 이력 원칙

이후 계획을 수정할 때는 기존 계획을 삭제하지 않고 다음 항목을 함께 추가한다.

- 변경 날짜와 변경된 iteration
- 이전 실행 방식과 변경된 실행 방식
- 관측된 coverage·중복·reachability 근거
- 변경이 DesignSpec의 어떤 원칙을 유지하거나 확장하는지
- 다음 검증 산출물과 되돌림 조건

이번 변경의 되돌림 조건은 신규 후보가 반복 sweep에서도 새 bin을 만들지 못하거나,
목표 gap과 무관한 중앙부만 반복하거나, signature별 profile 방향이 충돌하는 경우다.
이 경우 후보 수를 자동으로 늘리지 않고 feature 조합과 reachability 가정을 재검토하며,
최소 3회 screening 이후에도 새 coverage와 방향성이 재현되지 않을 때 적용 범위 밖 또는
`not_identifiable` 기록을 검토한다. 3회는 조정 가능한 기본값이며 절대 상한이 아니다.

signature 생성 로직, feature 변경 폭, 한 iteration에서 추가할 후보 수는 아직 미정이다.
이 항목은 별도 설계 논의와 사용자 합의 이후에만 구현 계획으로 확정한다.

## 14. 합의된 구현 전제

signature 생성 구현은 다음 전제를 먼저 만족해야 한다.

- coverage audit을 실행한 뒤에만 후보 생성을 시작한다.
- `UNOBSERVED` gap과 기존 signature의 실제 coverage 기여를 근거로 후보를 계획한다.
- 무작위 조합과 cutoff 직접 목표화를 사용하지 않는다.
- 후보마다 parent, 변경 feature, 방향, 예상 영향, 선택 이유와 provenance를 기록한다.
- 한 iteration의 후보 수는 고정하지 않는다.
- 같은 iteration에서는 공통 seed로 signature를 비교한다.
- 새 bin을 만들지 못하고 중복이 큰 후보는 반복 결과를 확인한 뒤 후순위화 또는 제거한다.

현재 구현은 `coverage audit`와 외부에서 검토된 `strategy_catalog`을 입력으로 요구하며,
고정 factor 조합이나 숨은 기본 전략을 사용하지 않는다. 세부 전략 catalog의 내용,
feature 변경 폭과 판정 기준이 합의되기 전까지는 후보 계획만 생성하고 자동 simulation
승인 경로에 연결하지 않는다.

## 15. 2026-09-26 정합화된 구현 계획

앞선 계획의 “중요 gap 우선 선택”, 고정 seed 확장 수, runtime 기반 hard exclusion 해석은
폐기한다. 현재 구현 순서는 다음과 같다.

1. canonical generation feature에서 `generation_signature_hash`를 계산하고, seed·domain
   identity·generator version을 포함한 별도 `domain_id`를 계산한다. 이름·tags·runtime·
   round metadata는 두 identity hash에서 제외한다.
2. immutable context와 mutable feature vector를 분리한다. bounded explicit-Euler-style
   update 대상은 normalized
   mutable feature뿐이며 geometry·joint-set 구조·observation window는 보존한다.
3. 모든 `UNOBSERVED` gap을 순환 portfolio에 넣고, 후보 상한 안에서 해결된 gap을 다음
   순환에서 제외한다. 이는 의미적 우선순위가 아니라 미해결 상태 기반 scheduling이다.
4. 양쪽 이웃 signature가 있으면 midpoint를 먼저 만들고, 실행 결과의 `Δx`, `ΔC`와
   coverage residual로 국소 방향을 추정한다. 이는 미분방정식 적분이 아니라
   simulation-guided 후보 갱신이다.
5. `Project_Ω`로 물리적 bounds를 적용하고, midpoint·Euler-style step·projection·parent를
   manifest와 ledger에 기록한다.
6. 시간은 soft budget으로 기록한다. 예상시간이 길다는 이유만으로 low-Q 후보를 제거하지
   않으며, 실제 시간이 반복적으로 늘고 새 coverage가 없을 때만 전략을 재검토한다.
7. 최소 3회의 공통-seed 변경 screening에서 방향성과 coverage 기여가 재현되지 않으면
   signature 또는 update 방향을 후순위화·폐기 검토한다. 3회는 조정 가능한 기본값이다.

8. feature 탐색 schedule은 기본적으로 `D(joint-set structure) -> A(density) ->
B(size distribution) -> C(orientation) -> E(seed realization)`을 사용한다.
9. 전체 schedule의 약 10%는 기록된 randomization seed로 순서만 재배열한다. 값의
   randomization이나 bounds 완화는 하지 않으며, schedule mode·순서·seed·단계별
   `Δx/ΔC`를 ledger에 기록한다.

validation harness의 `--euler-spec` 경로는 reviewed probe의 `ΔC`, residual과 normalized
feature bounds를 받아 Euler candidate를 다음 iteration에 자동 생성한다. 생성 candidate,
parent와 update metadata는 이전 iteration ledger에 기록하고, simulation과 calibration
편입은 여전히 별도 승인 단계로 유지한다.

다음 후속 구현에서는 feature schedule을 별도 설정으로 관리하되, D/A/B/C는 mutable
generation feature 탐색 단계로, E는 동일 signature의 독립 domain realization 단계로
분리한다. 90/10 비율은 초기 운영값이며 실행 결과에 따라 조정 가능하다.

## 16. 2026-09-27 정책 재확인과 검증 순서

단계별 실측 Q'·RQD·절리 교차수·실제 시추공-절리면 사잇각과 출처는
[ExperimentEvidence_20260927.md](ExperimentEvidence_20260927.md)에 분리 기록한다.
후속 update 규칙은 해당 표의 matched comparison과 seed 반복 근거를 먼저 검토한다.

9월 26일의 15절과 DesignSpec 5.6을 기준으로 유지한다. 3회는 개별 signature의
공통-seed 변경 screening 후 후순위화 검토 기준이며, campaign 전체 Euler update
횟수와 다르다. 내부 gap의 첫 시험은 양쪽 이웃의 midpoint로 하고, 그 결과를
해석할 probe는 가능한 한 feature 축 하나씩 수행한다. `Δx`는 적용한 normalized
feature 차이, `ΔC`는 동일 bin/seed 조건에서 관측한 coverage 차이로 기록한다.

10구간 주 분석과 20구간 coverage 보조 분석을 동일 simulation CSV에서 병행한다.
나머지 운영 수치는 기존 정책을 즉시 대체하지 않고 격리된 validation에서 검증한다.

1. 10구간 프로파일 결과와 20구간 audit을 별도 산출물로 저장한다. 20구간에서 빈 bin,
   signature별 bin과 공동 coverage, domain 지원을 기록한다. bin 경계를 바꾼 round의
   coverage delta는 직접 비교하지 않는다.
2. 실제로 적용한 feature별 probe 간격과 `η=0.5` 고정 step을 명시적으로 기록한다.
   P32는 정책상 상한이 없고 방향성은 추가 탐색 제약이 없지만 생성기의 유효 범위를
   지킨다. 실제 borehole-plane 사잇각은 `0~90`도이다.
3. 후보별 3회 screening 판단과는 별도로, 효과 없는 Euler update가 30회 연속되면
   이유를 보고하고 종료하는 campaign 상한을 시험한다. bin 충족은 coverage 종료
   조건 후보일 뿐 cutoff `identified`의 충분조건은 아니다.

현재 validation harness는 10구간 프로파일·Euler update 기준 audit과 20구간
signature coverage 보조 audit을 함께 저장한다. reviewed `--euler-spec`에
parent/probe case, 목표 10구간 bin,
feature bounds와 step을 명시하고 같은 seed로 두 case를 실행하면 관측 `Δx/ΔC`와
관측 bin에서 목표까지의 로그 bin 거리 residual을 자동 산출하여 Euler 후보를 생성한다.
빈 target 바로 옆에 관측이 없어도 더 먼 관측 bin의 이동을 사용하며, 더 가까운 쪽
signature를 다음 Euler 갱신의 출발점으로 삼는다. 초기 portfolio에 검토된 pair보다
가까운 다른 signature가 있으면 이를 ledger에 기록하고 기존 실행 case 중 같은 seed,
같은 immutable context에서 단일 feature만 다른 probe와 비교한다. 비교 가능한
probe가 없으면 해당 signature의 검토된 probe를 기다린다. 다음 iteration의 생성
candidate도 실제 재실행 결과로 비교하며, 관측
거리 변화가 없거나 목표 bin에 도달하면 사유를 기록하고 중단한다. 새 probe case를
audit만으로 임의 생성하거나 효과 없는 update 30회 종료를 적용하는 기능은 아직 없다.
20구간 audit의 bin 인덱스를 목표 10구간 bin 인덱스로 그대로 전달하지 않는다.

실험 근거표의 A/C 결과를 반영하여 실제 same-seed probe의 Q'·RQD·시추공 교차
반응을 갱신 전 확인한다. 밀도 변경 후 교차 반응이 없거나 Q'·RQD가 모두 그대로면
관측되지 않은 Euler 기울기를 만들지 않는다. 대신 같은 seed·단일 feature·검토된
방향에서 원래 parent와의 probe 거리를 두 배씩 늘려 밀도 도달성 실험을 계속한다.
검토된 수치 탐색 범위가 끝나면 범위 확대 검토를 요청할 뿐 P32의 물리 상한이나
해당 Q'의 도달 불가를 선언하지 않는다. 실제 변화가 보이면 실측 finite difference로
Euler 갱신에 복귀한다. 방향성 변경은 설정 dip이 아니라 생성된 실제 borehole-plane
angle의 변화를 요구한다. seed별 Q' 및 관련 교차·사잇각 반응의 부호가 충돌하면
반복 검증을 기다린다. 반응이 확인되면 feature별 국소 민감도와 사잇각당 Q' 변화를
ledger에 남긴다. D의 절리군 구조는 density probe로 대체하지 않으며 B의 작은
size 반응도 무효로 단정하지 않는다. 정량 결과를 보편 물리 임계값, 통계적 유의성,
Euler step 자동 조절 규칙으로 승격하지 않고 step은 reviewed spec의 값으로 유지한다.
밀도 probe의 배증 간격은 미지의 기울기 추정값이 아닌 reachability 탐색 간격이다.

검증 campaign의 iteration 0은 검토한 parent/probe portfolio를 실행하고, 이후에는
새 후보만 실행한다. 그러나 10-bin update audit·20-bin 보조 audit·profile search는
같은 campaign의 누적 관측행에서 기존 `domain_id` 재실행을 제외해 계산한다. probe

## 17. 2026-10-01 실행 재개 및 반복 coverage 작업

### 확인된 중단 원인

`validation/campaign_003`은 `--iterations 3`으로 시작했지만, iteration 0에서
same-bin seed별 Q' 변화 부호가 충돌하여 `needs_repeatability`가 되었고, 기존
분기에서 `await_physical_probe_response`를 기록한 뒤 campaign을 종료했다. 이는
안전한 Euler 방향을 추정할 수 없다는 의미이지, density 도달성 실험까지 중단해야
한다는 의미는 아니다. 같은 10-bin에 머문 P32/spacing probe는 Euler slope를 만들지
않고 검토된 feature 범위 안에서 reachability probe를 넓혀 실행한다.

### 구현 및 실행 계약

- [x] same-bin Q' repeatability 충돌을 기록하고 wider density probe로 계속
- [x] 완료된 iteration 0 CSV를 새 campaign에서 재사용하는 `--initial-csv` 추가
- [x] 기본적으로 기존 workdir 실행 거부, `--force-overwrite` 시 기존 isolated campaign을 timestamp backup으로 보존
- [x] 기존 campaign과 신규 resume 경로의 회귀 테스트 통과
- [x] campaign_003 CSV를 재사용하여 campaign_004 screening 실행
- [x] 후보별 Q' coverage 증가, domain/signature 중복도, profile 변화 분석
- [ ] 중복 signature는 원자료 삭제 없이 active screening 목록에서 보류/축소하는 규칙 정의
- [x] `min_domains=1`의 `identified` 결과만으로 campaign 반복을 조기 종료하지 않도록 변경
      `identified`만으로는 기본 조기 종료하지 않으며, 필요한 경우에만 명시적
      `--stop-on-identified` 옵션을 사용한다.

### campaign_004 관측 결과 (2026-10-01)

- 총 4 iteration 중 iteration 0은 기존 CSV 재사용, iteration 1~3은 신규 density probe를 실행했다.
- 누적 20 domain, 5 generation signature에서 `Qp_bh_mean`은 206.25~266.60이었다.
- 10-bin profile은 bin 9만 관측했고 target bin 8 (76.15~174.52)은 비어 있어
  `profile_search_status=not_identifiable`이다.
- density probe P32는 30 -> 50 -> 90으로 커졌다. 마지막 paired probe에서 Q' 평균은
  17.31 감소하고 시추공 교차수는 15.33 증가했지만, 새 Q' bin은 관측되지 않았다.
- 20-bin audit에서는 bin 18에 5개 signature가 겹치고 bin 19에는 1개 signature가
  추가로 관측됐다. 4개 signature는 coverage bin 관점에서 bin 18만 덮으며,
  각 signature는 서로 다른 4개 domain을 제공한다. 따라서 중복 coverage는 높지만
  동일 signature 복제나 domain 중복으로 간주하지 않는다.
- 마지막 `next_action=density_probe_iteration_limit`은 요청한 반복 예산 소진을 뜻한다.
  다음 더 넓은 후보(P32 약 170)는 아직 생성·실행되지 않았다. 이는 doubling 규칙의
  다음 후보 예상값이며 실제 입력은 후속 후보 산출 후 확인해야 한다.
- 다음 회차는 P32 50 -> 90의 paired same-seed 결과와 campaign 누적 관측을 함께
  유지해야 한다. 현재 실행기는 campaign 중간 재개를 지원하지 않으므로,
  누적 CSV와 paired probe를 안전하게 넘기는 재개 경로를 먼저 마련한다.

### 2026-10-01 zero-inclusive Q′ grid 전환

- 초기 zero-bin 추가 해석은 bin 수를 11/21로 늘리므로 superseded 처리한다.
- 확정 규칙은 기존 `geomspace(0.1, 400, intervals + 1)` 경계 배열의 첫 값만 `0`으로
  교체하는 것이다. `intervals=10` primary는 계속 10 bins/11 boundaries이고,
  `intervals=20` 보조 audit은 계속 20 bins/21 boundaries다.
- 기본 primary edges는 `[0, 0.229195..., 0.525305..., ..., 400]`이다. 즉 첫 bin은
  `[0, 0.229195...)`이며 별도 `[0, 0.1)` bin을 추가하지 않는다.
- high-Q target `[76.146, 174.524)`는 기존과 같이 primary index 8이다.
- 과거 0.1 시작 campaign 자료는 `[0, 400]`의 새 coverage로 재감사하기 전까지
  새 grid index와 직접 합산하지 않는다.

### 2026-10-01 재실행 및 target-bin 종료 조건 정정

- 최신 fresh run은 `initial_results_reused=false`, `iterations_requested=40`,
  `seed_range=[1001, 1004]`로 실행됐다. seed는 끝값 포함 4개이며, 40은 바깥
  signature-update iteration의 최대 횟수다.
- 실제 run은 6 iteration 후 기존 `stop_target_bins_reached` 분기로 끝났다.
  당시 10-bin grid에서는 bin 8과 9만, 20-bin 보조 audit에서는 bin 17~19만 관측됐고,
  profile search는 `not_identifiable`이었다. 따라서 이 종료는 전체 coverage나 cutoff
  확인을 뜻하지 않았다.
- 원인은 spec의 단일 `target_bins=[8]`에 도달한 즉시 campaign을 종료한 로직이다.
  이를 수정해 target이 관측되면 가장 가까운 미관측 **10-bin profile 구간**으로
  목표를 이동시키고, 전체 10개 primary bin이 관측됐을 때만 coverage 완료를 기록한다.
  20-bin audit은 종료 판정이 아니라 보조 진단으로 유지한다.
- `all_profile_bins_observed`도 cutoff 확정을 뜻하지 않는다. ledger에는
  `profile_cutoff_identified`를 별도로 남기며, 공통 PR/POST profile 상태가 없으면
  cutoff는 계속 `not_identifiable`이다.
- target 진행과 전체 10-bin coverage 종료 단위 테스트를 추가했다. 이전 11-bin 시도 당시
  전체 unittest 90개가 통과했으며, 현재 edge-replacement 규칙으로 관련 테스트를 갱신했다.
- 다음 fresh run은 P32=200 상한에 도달하면 `await_wider_density_bounds`로 기록한다.
  상한은 승인된 탐색 범위이므로 자동 확대하지 않는다. 더 낮은 Q' 구간을 계속
  탐색하려면 수치 탐색 범위를 검토·승인한 뒤 새 campaign으로 실행한다.
- 상한을 `P32=1,000,000`으로 확장한 다음 실행은 iteration 6에서 case별 CSV 저장 중
  `OSError: [Errno 63] File name too long`으로 실패했다. 계산 batch는 완료됐으나 CSV가
  저장되지 않아 iteration 6은 coverage/ledger에 포함되지 않았고, manifest는
  `status=planned`, `record_count=0`으로 남았다. iteration 0~5와 candidate/config 산출물은
  현재 workdir에 보존돼 있다.
- 실패 manifest의 `iterations_requested=4000`, `seed_range=[1001, 1004]`다. 즉 4 paired
  seed를 signature별로 사용하고 최대 4000 outer iterations를 요청한 실행이었다.
- 원인은 candidate name에 이전 parent 전체 이름을 매 iteration 덧붙여 case 이름이
  무한히 길어진 것이다. runner는 이후 후보 YAML의 이름을 root case명 + 현재 candidate ID로
  고정하고 parent provenance는 기존 metadata에 보존한다. 재실행은 기존 workdir resume가
  아니므로 새 workdir 또는 `--force-overwrite` backup을 사용해야 한다.
- iteration 8 실행은 CSV 결합 후 `probe must generate a distinct signature`에서
  실패했다. iteration 8의 P32는 591.33이지만 CSV hash는 parent r007의 hash
  `6f4869...`로 기록됐다. density-probe builder가 top-level candidate JSON의 새 identity는
  계산했으나 nested YAML tags의 `generation_signature_hash`/`domain_id`는 갱신하지 않았고,
  `MultiCaseBatchRunner._attach_metadata()`가 그 stale tags로 BatchRunner 계산값을
  덮어썼다. iteration 8 결과의 수치는 남아 있지만 provenance가 잘못돼 paired signature
  분석에는 사용할 수 없다.
- density candidate tags를 새 hash/domain으로 갱신하고, batch metadata merge에서는
  계산된 row provenance를 우선 보존하도록 수정했다. stale-tag overwrite, candidate tag
  동기화, paired-probe 회귀 테스트를 통과했다. 실패 campaign은 중간 재개를 지원하지 않아
  새 실행에서는 다시 계산해야 한다.
- 이후 fresh run은 iteration 9에서 `needs_repeatability`로 멈췄다. seed별 Q′ 반응은
  `+10.50, -4.68, -1.74, +10.11`로 부호가 충돌했지만 target-bin proximity gain은
  `+0.5`였다. 기존 runner는 Q′ 부호 충돌을 coverage 진행 여부와 무관하게 중단 조건으로
  처리했다.
- 수정: density probe에서 Q′ 부호가 충돌해도 proximity가 같거나 개선되면 Euler slope는
  사용하지 않고 reviewed density reachability probe를 이어간다. proximity가 악화되면
  `await_physical_probe_response`로 대기한다. 이에 맞춘 regression fixture와 기존 campaign
  테스트 3개가 통과했다.
- 위 변경 후에도 round 9에서 멈춘 이유는 별도 guard였다. repeatability continuation은
  `extend_density`를 true로 만들었지만, 이어지는 density builder 조건이
  `response == 0` 또는 `source_case_path == probe_path`만 허용했다. 이번 round는
  proximity gain `+0.5`, response `0.875`였고 source가 parent라 조건에서 빠졌다.
- 추가 수정: Q′ repeatability 충돌과 non-regressing proximity가 확인된 density probe는
  source가 parent여도 Euler 방향을 추론하지 않은 채 승인된 density reachability를 계속한다.
  proximity가 음수면 계속하지 않는다. 해당 실제 분기 조합의 단위 테스트를 추가했다.
- 현재 관측 결과는 iteration budget 40 중 10 rounds에서 중단, seed 1001–1004다.
  10-bin grid에서 bin 5~9만 관측됐고 bin 0~4는 비어 있다. 누적 132 rows,
  44 domains, 11 signatures, `Qp_bh_mean=7.73~266.60`; profile result는
  `not_identifiable`이다. 이 결과는 위 source-path guard 수정 전 campaign 기록이므로
  새 코드 실행 결과로 간주하지 않는다.

반복 실행을 처음부터 다시 시작할 때는 `--force-overwrite`로 기존 campaign 폴더를
삭제하지 않고 sibling backup으로 옮긴다. 다음 실행은 삭제된 campaign_003 CSV를
사용하지 않고, campaign_004의 partial result를 이어받지도 않는다.

다음 fresh run은 `validation/README.md`의 2026-10-01 실행 예시를 따른다.
`--iterations 4000`은 넉넉한 상한이며 요구 실행량이 아니다. 모든 primary bin
coverage 또는 다른 명시적 stop condition에 도달하면 더 일찍 끝날 수 있다.
`--seed-start 1001 --seed-stop 1004`는 각 signature당 4개 paired seed다.
iteration별 `active_target_bins`, `remaining_profile_bins`,
`next_action`, profile search 상태와 coverage를 함께 확인한다. 전체 bin coverage도
cutoff 확인이나 calibration 승인으로 간주하지 않는다.

### 2026-10-01 Q′ lower-domain 확장

- 이전 변경은 별도 zero-bin을 추가해 bin을 11/21로 늘렸고, 이를 2026-10-01 correction에서
  superseded 처리했다.
- 현재 규칙은 양수 로그 경계 `geomspace(0.1, 400, intervals + 1)`의 첫 edge만 `0`으로
  교체한다. primary 10 bins, 보조 audit 20 bins, high-Q target index 8을 유지한다.
- 따라서 Q′=0을 포함해도 경계 수와 기존 positive log 간격은 복잡해지지 않으며, 첫 bin만
  `[0, 0.229195...)`로 확장된다. 과거 실행 산출물은 해당 실행 당시 grid 기준 기록으로 보존한다.

### 시그니처 중복 처리 원칙

중복 시그니처와 과거 simulation 결과는 삭제하지 않는다. 먼저 Q' bin별
signature/domain 교차표와 신규 coverage 기여를 보고하고, 후속 iteration에 넣을
active portfolio만 비파괴적으로 de-prioritize한다. 보류 여부는 새 bin 기여,
독립 domain 지원, profile 변화와 중복도를 함께 근거로 기록하며, 기준은 screening
결과를 검토한 뒤 별도 합의한다.
`Δx/ΔC`는 누적 pool이 아니라 같은 seed의 실제 비교 case로만 측정한다. ledger에는
누적 독립 domain·signature 수, 새/중복 domain 수와 audit 원본 CSV 목록을 기록한다.
기존 고Q v2 P32 10→20 case의 `target_bins=[8]` 설정은
`validation/highq_density_euler_proposed.json`에 검토용으로 두었다. `--dry-run`은
확인했으나 실제 실행은 `approved_for_screening` 명시 전까지 금지하며, 실행 결과는
생산용 기존 CSV를 입력으로 섞지 않는다.

## 18. 2026-10-01 Main campaign signature-scheduler contract (Stage 2)

### Goal and boundary

The main campaign must turn cumulative coverage gaps into reviewed D/A/B/C
signature candidates, execute only approved candidates, append their results to
the campaign's cumulative domain-deduplicated pool, and plan the next iteration
from that updated pool. E is an independent-domain repeatability phase, not a
generation-signature feature family. This section defines the scheduler contract;
it does not authorize or start a large-scale simulation.

### Candidate catalog contract

The catalog remains keyed by `low_q_gap`, `internal_gap`, and `high_q_gap` and
uses the existing explicit approval states. Each strategy must include:

- `strategy_id`, `feature_family` (`D`, `A`, `B`, or `C`), `target_gap`, and
  `status`
- parent signature hash and source case path, plus immutable-context identity
- a `changed_features` list with feature path, old/new value or explicit
  direction/magnitude, normalized delta where applicable, and approved bounds
- expected Q' coverage/profile effect, selection rationale, and validity constraints
- common screening seed policy and optional runtime/information estimates

Feature-family rules:

- **D, joint-set structure:** discrete reviewed cases only. Do not interpolate
  joint-set count or topology with Euler arithmetic.
- **A, density:** one continuous feature per probe, either P32 or mean spacing;
  do not change both in one causal probe.
- **B, size:** one of `size_alpha`, `size_r_min`, or `size_r_max` per matched probe.
- **C, orientation:** one orientation feature per matched probe. Measure the
  realized borehole-plane-angle response; input angle alone is not evidence.
- **E, seed realization:** hold generation signature fixed and change seed/domain
  only for repeatability assessment.

For continuous one-feature probes, retain the reviewed same-seed parent/probe
contract. Euler updates may use measured `Δx/ΔC` only after a qualifying response;
mixed seed signs do not supply an Euler slope. A non-regressing coverage response
may continue a reviewed reachability step, while a regressing response waits for
repeatability evidence. Every proposal records its source evidence and is kept
separate from approval to execute.

### Per-iteration orchestration

1. Audit the cumulative, deduplicated campaign pool on the 10-bin primary grid;
   use the 20-bin grid only for signature-overlap diagnostics.
2. Build the set of unobserved bins and bins below the approved independent-domain
   support. Give every remaining gap a round-robin opportunity; do not infer a
   cutoff from a filled-bin count.
3. For each selected gap, choose a parent from the nearest observed signature or
   reviewed internal-gap neighbors, then join only compatible approved catalog
   strategies for that gap and feature family.
4. Write candidate plan, manifest, provenance, and dry-run output first. Execute
   only candidates explicitly approved for screening, using a common seed set
   within each matched comparison.
5. Append completed rows and source CSV references, deduplicate by domain
   identity, compute new/overlap coverage, profile summaries, and status, then
   save the next iteration checkpoint before planning more candidates.
6. Stop on full primary-bin coverage, iteration budget, reviewed bounds exhaustion,
   a failed/ambiguous paired probe, or another explicit stop action. Record
   remaining gaps and the reason; full coverage alone does not identify cutoffs.

### Current implementation boundary

`run_campaign.py` retains the Stage 3 plan-only path and now has a separate
Stage 4 execution path for approved catalog entries. The regular Euler campaign
still follows its reviewed `--euler-spec` pair. Catalog execution does not infer
missing bounds, target values, approvals, or new strategies. It also does not
claim cutoff identification when all primary bins are merely observed.

### Stage 3 result: main-campaign plan-only integration

- `run_campaign.py` now accepts `--strategy-catalog` and
  `--max-candidates-per-iteration` as a separate mode from `--euler-spec`.
- Catalog mode requires `--dry-run` plus `--initial-csv`; it audits that supplied
  CSV on the primary grid, selects only `approved_for_screening` strategies for
  remaining gaps, and writes `iteration_000/strategy_candidate_plans.json` with
  source CSVs, missing/planned bins, provenance and `execution_started=false`.
- Strategy parents must match their declared signature hash. A/B/C plans change
  exactly one in-family feature. D strategies point to a reviewed discrete case
  with a distinct signature. Unapproved strategies are retained in the source
  catalog but excluded from the plan. This path does not run simulation or
  materialize A/B/C candidate YAMLs.
- Full suite at integration: 97 tests passed. Next gated stage: materialize reviewed candidate
  cases, show a dry-run manifest, then connect explicit approval to main-campaign
  execution. Do not start large-scale simulation as part of catalog planning.

### Stage 4 result: resumable catalog execution

- Non-dry-run catalog mode materializes approved A/B/C one-feature candidates
  and reviewed D cases, executes one candidate per outer iteration with the
  common inclusive seed range, and re-plans from the cumulative audit.
- Every completed candidate records parent and changed feature, normalized
  `delta_x`, `delta_C`, intended/measured signature hash, domain IDs, source CSV,
  primary/auxiliary coverage, overlap counts, and stop state in the atomic
  checkpoint and ledger snapshot.
- A completed per-case CSV is reused only when case name, complete seed set,
  domain IDs, and generation signatures validate. Failed or incomplete attempts
  remain recorded and resume writes a new attempt without replaying valid jobs.
- Exhausted approved candidates, invalid review metadata, and the iteration
  ceiling preserve remaining gaps as `awaiting_review` or `iteration_limit`;
  neither is reported as coverage completion. `coverage_complete` and
  `profile_cutoff_identified` remain distinct fields.
- C mean dip/direction candidates record realized unoriented plane-normal angle.
  E uses only explicit independent `--repeatability-seed` values, holds the
  signature fixed, and is excluded from coverage accumulation.
- Mock integration covers interruption after one completed candidate, pending
  candidate resume, completed-CSV reuse, and separate E jobs. No large-scale
  simulation was launched during implementation.

### 2026-10-01 Stage 4 handoff

Implementation state, the one-seed real A/B/C smoke, canonical provenance
corrections, stale-artifact warning, exact continuation command, and remaining
large-campaign gates are recorded in
[`Stage4_Handoff_20261001.md`](Stage4_Handoff_20261001.md). At handoff, 105 tests
pass; the smoke is `awaiting_review`, primary bins 0-8 remain unobserved, and no
cutoff is identified. Continue with the documented fresh four-seed paired smoke,
not by treating the old smoke checkpoint as production evidence.

## 19. 2026-10-04 후속 정합성 경계

이 계획서의 이전 구현 단계와 실행 evidence는 작성 당시 상태의 기록으로 유지한다.
2026-10-04 이후 새 implementation task를 만들거나 재개할 때는 다음 순서를 적용한다.

1. Q′ 계산 입력과 provenance를 DesignSpec 5.8.1에 맞춘다. Barton category, RQD 하한,
   `Jn` case/domain 정의, no-intersection fallback convention을 기존 legacy column과
   혼동하지 않는다.
2. 시추공·터널 geometry 및 clipping을 DesignSpec 5.8.2~5.8.3에 맞춘다. 기존 offset-only,
   `+x` 고정축, scalar face-window 입력은 새 geometry contract로 간주하지 않는다.
3. `Q′BH` 전체 profile과 station 순서의 `Q′Face`를 저장하고, 실제 overlap과 길이 metadata를
   보존한다. Q′Face를 tunnel 전체 scalar 평균으로 축약하지 않는다.
4. Coverage update는 profile observed-bin과 positive-length support, parent별 gap,
   길이 가중 proximity 및 50:50 score를 사용한다. 동일 cutoff grid가 아닌 결과끼리
   coverage delta를 직접 비교하지 않는다.
5. Update는 중앙차분 score 민감도 기반, 양수 값의 내부 로그 좌표, 약 5% update,
   orientation 상대각 β의 ±5° probe 및 최대 5° update로 제한한다. Round-robin은 밀도 →
   크기 → 방향이며 `fisher_kappa`는 이 campaign에서 고정한다.
6. 탐색 seed 외 추가 seed 3개에서 paired 검증하고, 2개 이상에서 score 엄격 증가 및
   observed-bin 비감소가 있어야 update 방향을 채택한다. 모든 주 파라미터가 유효 경계에
   도달하면 campaign을 멈추며 자동으로 κ/다른 조건으로 전환하지 않는다.
7. Coverage score는 cutoff 산출과 분리한다. Cutoff method의 longitudinal 표본 단위와
   가중 정책이 추가 합의되기 전에는 새 profile 기반 cutoff 추정은 미결/blocked다.

이 기록은 문서 정합성 경계이며 코드 변경, 기존 campaign checkpoint 재작성 또는 새
simulation 실행을 승인하지 않는다.

## 20. 2026-10-04 Q′ profile 및 coverage 코드 리팩토링 계획

### 20.1 목적과 제한

이 계획은 DesignSpec 5.6.9 및 5.8에 기록된 Q′ 계산, 물리 geometry, longitudinal
profile, coverage 기반 signature update 계약을 코드에 반영하기 위한 실행 순서다.
이 절은 계획 기록이며 코드 수정, 테스트 실행, campaign 승인 또는 cutoff 정책 확정을
승인하지 않는다. 이전 절의 실행 결과와 Stage handoff는 당시 기록으로 보존한다.

구현은 아래 단계 순서로 진행한다. 각 단계는 해당 단계의 결정사항과 검증을 마친 뒤
다음 단계로 넘어간다. 진행 중 기존 결정으로 해소되지 않는 설계 선택을 만나면 그 지점에서
멈추고 사용자 결정을 받은 뒤 계획 또는 구현을 갱신한다.

### 20.2 단계별 구현 범위

#### 단계 1 — Q′ 입력 모델, 계산 및 provenance

대상 파일:

- `src/core/domain.py`
- `src/core/joint_models.py`
- `src/core/q_calculator.py`
- `src/core/dfn_generator.py`
- 관련 case YAML 및 Q′ 계산 테스트

작업:

1. Q′ 계산에 RQD 하한 10을 적용한다. Q′용 입력 보정이 full Q의 `Jw/SRF` 처리와
   혼동되지 않도록 계산 경로를 분리한다.
2. `Jn`은 case/domain의 절리군 정의에서 가져오고 profile 구간의 교차 개수로 대체하지
   않는다.
3. Barton Q-system의 discrete `Jr/Ja` 범주를 joint 입력으로 표현하고, 범위형 category의
   중간값과 category 원문을 모두 보존한다.
4. 교차 joint 집계는 최소 `Jr/Ja` 비율을 가진 동일 joint의 한 쌍을 사용한다.
5. 교차가 없을 때 `RQD=100, Jr=4, Ja=0.75` fallback을 관측값과 구별되는 계산
   convention으로 provenance에 기록한다.
6. `QCalculator.ROCK_CLASSES`를 승인된 Q 등급 경계와 대조하고 등급 경계·명칭의 차이를
   명시적으로 처리한다.

**결정 gate:** `Jr/Ja` category를 case의 joint-set 설정에 둘지 개별 joint realization
입력으로 둘지, 그리고 category 선택이 set 내부에서 결정적인지 seed별로 변할 수 있는지
확정한다. 이는 기존 `Jr_mean/Jr_std`, `Ja_mean/Ja_std`의 대체 schema를 결정하므로 임의로
선택하지 않는다.

완료 검증: RQD 0/10/10 초과 경계, Barton category 및 range midpoint, fallback provenance,
동일 joint pair 선택, `Jn` 독립성, 등급 경계 테스트를 추가·통과한다.

#### 단계 2 — 물리 시추공 geometry와 tunnel polyline

대상 파일:

- `src/core/domain.py`
- `src/core/case_library.py`
- `cases/*.yaml`
- `src/core/tunnel.py`
- geometry 관련 테스트

작업:

1. 시추공을 물리 좌표계의 시작점·방향·요청 길이로 정의하고 시작점-끝점 표현은 같은
   canonical geometry로 변환한다.
2. 방향 벡터 정규화와 입력 유효성 검증을 수행하고, domain clipping 뒤 계산 길이를
   기록한다.
3. Tunnel을 순서 있는 직선 polyline segment들로 표현하고 연결성과 각 segment 길이를
   검증한다.
4. YAML loader/saver 및 case schema를 새 geometry로 이전하고 `borehole_offsets` 전용
   활성 입력 경로를 제거한다.
5. sampling과 plane-angle 계산에서 동일한 물리 시추공 축을 사용하도록 전달 경로를
   연결한다.

완료 검증: geometry 정규화, 시작점-끝점 변환, 잘못된 입력, clipping, polyline 연결/불연속,
YAML 왕복 및 기존 case 이전 테스트를 추가·통과한다.

#### 단계 3 — Q′BH/Q′Face longitudinal profile과 비교

대상 파일:

- `src/core/tunnel.py`
- `src/core/comparison.py`
- 결과 serialization 및 batch output schema
- `src/core/profile_exploration.py`
- profile/comparison 테스트

작업:

1. Q′BH를 `dx′` 기본 1m, 설정 가능 간격으로 산출한다. Domain clipping 후 완전한
   구간만 계산하고 마지막 불완전 구간은 제외하며, 계산 길이와 profile 전체를 보존한다.
2. Q′Face를 station 순서와 chainage가 있는 sequence로 저장한다. 터널 전체 평균 하나로
   축약하지 않는다.
3. Face와 borehole profile의 대응은 물리 geometry가 겹치는 실제 overlap 구간에 한정하고,
   overlap 외 시추공 profile은 독립 자료로 유지한다.
4. 비교는 비짝지음 분포 비교로 구성하고 원 profile/station 정보를 보존하면서
   Wasserstein-1 거리와 기술통계를 산출한다.
5. Domain 경계의 원형 face는 내부 영역만 계산한다. 내부 면적이 전체의 50% 미만이면
   그 station을 무효 처리하고 진행을 멈추며 마지막 유효 face와 사유를 결과에 남긴다.

완료 검증: 완전/불완전 마지막 profile 구간, overlap clipping, station 순서 보존,
분포 비교, face 유효 면적 50% 경계 및 중단 metadata 테스트를 추가·통과한다.

#### 단계 4 — 암질 기반 round length와 polyline 진행

대상 파일:

- `src/core/tunnel.py`
- face profile 및 round metadata serialization
- tunnel round 테스트

작업:

1. `face_step`을 고정 sampling 간격이 아니라 현재 face Q′로 다음 굴진 round 길이를
   결정하는 값으로 변경한다. 자동 굴진장 선택에서만 `Jw=SRF=1` convention을 사용한다.
2. 지정된 Q′ 구간별 대표 길이 정책을 적용한다. 유한 범위는 중간값, `Q′>10`은 4.0m,
   `Q′≤0.1`은 0.75m로 계산한다.
3. Round가 polyline segment 끝을 넘지 않게 자르고 segment 방향 변경점에서 다음 round를
   새로 시작한다. Vertex face 방향은 직전 segment 방향으로 처리한다.
4. 시작 face는 첫 round 결정에 사용하고 미래 face 비교 profile에서는 제외한다.
5. 불균등 station 통계는 실제 대표 round 길이로 가중하고 길이 metadata를 저장한다.

완료 검증: 각 Q′ 경계의 round length, segment 끝 절단, vertex 방향, 시작 face 처리,
길이 가중 통계 테스트를 추가·통과한다.

#### 단계 5 — Profile 기반 coverage score

대상 파일:

- `src/core/profile_exploration.py`
- `src/core/coverage_rounds.py`
- `src/core/qprime_cutoff_search.py`의 coverage audit 연동부
- `validation/run_campaign.py`
- coverage/profile 테스트

작업:

1. Coverage bin 점유는 실제 profile 값이 들어간 bin만 인정한다. 양의 길이 support가
   있으면 observed로 보고 min/max 또는 분위수 envelope만 닿는 bin은 점유시키지 않는다.
2. 각 paired seed에서 parent가 미관측한 bin 집합을 parent/candidate 공통 gap으로 고정한다.
3. Gap별 `P_b`는 profile segment/round 길이로 가중한 proximity로 계산한다.
4. 동일 cutoff grid에서 `D=mean(P_candidate-P_parent)`,
   `C=newly_occupied_bins/parent_gap_bins`, `ΔS=0.5D+0.5C`를 산출한다.
5. Grid 식별자/경계가 다른 coverage 결과의 delta 비교를 거부하고, profile 요약 통계와
   observed-bin 집합을 별도로 보존한다.
6. 이 score는 signature coverage/update 용도에만 연결한다. Cutoff selector의 PR/TR/POST
   추정에 재사용하지 않는다.

**보류 gate:** Longitudinal profile을 Q′ cutoff 상태/경계 추정에 넣을 표본 단위, 길이
가중, domain/borehole/station 반복 측정 의존성 정책은 별도 결정 전까지 구현하지 않는다.
Coverage score를 이 미결 결정을 대신하는 것으로 사용하지 않는다.

완료 검증: empty gap, positive-length 여부, candidate 새 bin, 50:50 score 수치, 첫 bin 거리,
다른 grid 거부, parent/candidate 동일 gap 사용에 대한 테스트를 추가·통과한다.

#### 단계 6 — Sensitivity update와 paired seed 검증

대상 파일:

- `src/core/signature_candidates.py`
- `src/core/coverage_rounds.py`
- `validation/run_campaign.py`
- campaign ledger/provenance 및 update 테스트

작업:

1. 탐색 순서를 밀도 → 크기 → 방향으로 round-robin 구성하고 probe별로 한 block만 바꾼다.
   `fisher_kappa`는 이 update 범위에서 고정한다.
2. 양수 feature의 민감도는 내부 로그 좌표에서 계산하되, 입력·저장값은 실제 물리값으로
   유지한다. 기존 ×/÷1.1은 probe 시작 간격으로 사용한다.
3. Coverage score의 중앙차분 민감도를 이용해 score 증가 방향 candidate를 생성한다.
4. 양수 파라미터 1회 update를 약 5%로 제한하고 방향은 상대각
   `β=asin(|n·d|)`를 사용한다. 방향 probe 및 update의 1회 변화는 최대 5°로 제한하며,
   법선 변화는 최소 대원 회전으로 dip/dip direction 후보에 변환한다.
5. `size_r_max > size_r_min > 0` 및 각 파라미터의 승인된 유효 bounds를 적용한다.
6. 탐색에서 효과가 관측되면 탐색에 사용하지 않은 사전 고정 seed 3개에서 paired
   parent/candidate 검증을 한다. 2개 이상에서 `ΔS>0`이고 observed-bin 수가 감소하지
   않으면 update 방향을 채택한다. 별도 1% 개선 threshold는 적용하지 않는다.
7. 경계에 도달한 파라미터는 더 진행할 수 없는 방향에서 고정하고 나머지를 계속 탐색한다.
   주 파라미터 모두 더 진행할 수 없으면 campaign을 중단하며 κ나 다른 조건을 자동으로
   바꾸지 않는다.

**결정 gate:** “약 5%” 변화는 기준에 포함됐으나, 다변수 gradient로부터 정규화된
update vector를 산출하는 구체적 식은 아직 확정되지 않았다. 구현 전에 약 5%를 각 활성
양수 파라미터별 변화 상한으로 둘지, block vector 전체의 정규화 step 상한으로 둘지
사용자와 확정한다. 이 결정 전에는 update 크기 산출 코드를 구현하지 않는다.

완료 검증: 로그 좌표의 중앙차분, 0/비정상 민감도, 5% 및 5° 상한, 크기 경계 투영,
방향 퇴화 후보 제외, paired seed 2/3 합격·불합격, 경계 포화 후 중단 테스트를 추가·통과한다.

#### 단계 7 — 모든 실행 표면과 legacy 보정 경로 정합화

대상 파일:

- `batch_runner.py`
- `multi_batch_runner.py`
- `run_profile_mc.py`
- `src/core/tunnel.py`
- case config, output schema 및 관련 문서

작업:

1. 새 geometry, profile schema, provenance, seed 및 계산 설정을 모든 실행 경로에 전달한다.
2. `correction_mode`가 연결된 모든 호출부와 설정을 찾아 practice realism 보정을 활성
   계산 경로/API에서 제거한다. Mechanical break, microfracture, core recovery, `Jr/Ja`
   scale, conservative face estimator가 일부 실행기에서만 남지 않도록 확인한다.
3. legacy 결과는 당시 schema/provenance를 유지하고 새 profile 결과와 암묵적으로 혼합하지
   않는다.
4. 결과에 geometry/clipping, `dx′`, round length, fallback convention, Barton category,
   profile overlap 및 계산 provenance를 기록한다.

완료 검증: CLI/batch/profile MC 실행에서 동일 case 입력이 같은 새 schema 계약을 따르는지
통합 smoke 및 schema regression으로 확인한다. Legacy reader가 필요하면 입력 출처와
legacy status가 유지되는지 확인한다.

#### 단계 8 — 통합 회귀 검증 및 문서 정합화

대상 파일:

- 관련 `src/test/` 테스트
- `Specification/DesignSpec_20260922.md`
- cutoff/adaptive/implementation 문서의 해당 날짜 후속 기록

작업:

1. 위 단계별 테스트를 실행하고 기존 기능의 의도된 동작과 새 계약을 분리 검증한다.
2. Q′ 계산부터 geometry sampling, profile serialization, coverage audit, candidate update까지
   최소 통합 경로를 검증한다.
3. 미결 cutoff 표본 단위나 약 5% update vector 결정이 완료되지 않은 상태라면 해당
   경로는 blocked로 남기고, 임시 default를 추가하지 않는다.
4. 결과와 논문 평가 항목은 설계 기록과 별도의 evidence로 작성한다. 설계 선택 자체를
   실험 결과나 학술적 근거로 서술하지 않는다.

### 20.3 의존 관계와 중단 조건

```text
1 Q′ data/calculation
  -> 2 geometry/schema
  -> 3 longitudinal profile/comparison
  -> 4 round-length profile
  -> 5 profile coverage score
  -> 6 sensitivity/update campaign
  -> 7 execution surfaces/legacy corrections
  -> 8 integrated verification and documentation
```

단계 1의 Barton category 입력 모델이 정해지지 않으면 해당 모델에 의존하는 계산기·DFN
변경을 시작하지 않는다. 단계 5에서 cutoff용 표본 단위 미결은 signature coverage 작업을
막지 않지만 cutoff 연결은 차단한다. 단계 6의 약 5% update vector 규칙이 결정되지 않으면
score·민감도 측정까지와 candidate update를 분리하고 update 실행은 차단한다. 기존 데이터,
checkpoint, ledger를 새 schema로 소급 덮어쓰지 않는다.

### 20.4 계획과 실행 승인 구분

이 계획은 코드 리팩토링의 작업 범위·순서·검증 기준을 기록한다. 실제 코드 수정과 테스트
실행은 사용자의 별도 요청 또는 승인을 받은 뒤 시작한다. 대규모 simulation/campaign 실행,
기존 결과 승격, cutoff 수치 확정은 각각 별도 승인과 미결 방법론 결정을 요구한다.

## 21. 2026-10-04 작업 종료 로그 — 새 오일러 시그니처 갱신 campaign

### 21.1 진행 방향 변경과 작업 원칙

20절은 당시 리팩토링 계획으로 보존한다. 이후 사용자는 기존 계산·실행 경로를 계속
수정하는 대신, 얽힘을 줄이고 읽기 쉬운 새 구조를 작성하는 방향을 선택했다.
궁극적인 목적은 오일러 방식 같은 시그니처 업데이트를 뜻하는 **오일러 시그니처
갱신법**을 새 campaign에 연결하는 것이다. 특정 수치해석 구현식까지 확정됐다는
의미는 아니다.

- 새 작업 위치: `src/euler_campaign/`. 먼저 `.pyi` 선언 골격을 작성하고 승인받은
  범위만 `.py`로 순차 구현한다.
- 기존 코드 재사용은 의무가 아니다. 얽힘을 늘리면 새로 투명하게 구현한다. 현재
  새 구현은 기존 `src/core` 또는 기존 campaign을 import하지 않는다.
- 기존 `validation/run_campaign.py`, 전용 모듈, case, 결과는 기존 자리에 유지한다.
  새 campaign 완성·검증 확인 후 별도 요청을 받아 아카이브한다.
- 각 단계 완료 후 사용자가 확인하고 다음 단계를 요청할 때만 진행한다. 미결 정책은
  임의로 가정하지 않고 멈춰 협의한다.
- 테스트 실행은 사용자가 직접 진행했다. Git 조회·stage·commit·push는 수행하지 않는다.

### 21.2 오늘 확인된 후속 결정

1. Q′ 계산의 RQD 하한 10을 사용자가 명시적으로 유지하기로 했다. 원 RQD와 계산용
   RQD를 구별한다. Full Q 계산 변경으로 확대하지 않는다.
2. Q 암질 등급의 경계는 아래 등급의 상한에 포함한다. 예: `4 < Q <= 10`은 보통 암반.
   Q′에 Q 등급표를 적용하거나 등급명을 변경하는 결정은 아니다.
3. 각 절리군은 Barton `Jr/Ja` 범주 한 쌍을 고정한다. 기존 정규분포 입력 방식은 새
   campaign에서 유지하지 않는다. 범주 미지정 case는 차단하며 기존 평균값으로 범주를
   자동 추정하지 않는다. Case loader와 joint 생성의 실제 차단·전달 구현은 아직 남았다.
4. 비교용 시추공은 터널 방향과 동일하게 단순화하고, 요청 경로 전체가 굴착 예정 체적
   안에 있어야 한다. 천공 시작점이 터널 밖이면 용도와 무관하게 오류다.
5. 터널 내부에서 시작해 외부로 돌출되는 시추공은 비교용이면 오류다. 독립 Q′BH 조사용으로
   명시하면 허용하지만 Face 비교 overlap을 생성하지 않는다. `BoreholeSpec.purpose`는
   `face_comparison` 또는 `independent`의 필수 입력이다.
6. 시추공 RQD는 실제 교차 위치를 사용하는 Deere 직접법, Face RQD는 Priest–Hudson법이다.
   일반 Face는 중앙 수평 scanline을 사용한다. 수직 터널은 x·y 직교 scanline에서 각각
   RQD를 계산한 후 두 RQD를 산술평균한다. 절리 빈도를 먼저 평균하지 않는다.
7. Face 계산과 굴진장 정책을 분리한다. Face 결과에 미정 굴진장을 임시값으로 넣지 않는다.
   유효 면적 50% 미만인 Face는 Q′ 없이 명시적인 무효 결과를 반환한다.

### 21.3 구현 및 검증 상태

| 파일 | 오늘 구현된 범위 | 검증 상태 |
|---|---|---|
| `src/euler_campaign/models.py` | 불변 입력 자료구조, 범주 원문·범위 보존, 범주 기본 유효성 검사, 고정 범주 쌍, 시추공 용도 | 사용자 실행에서 models/geometry 묶음 테스트 통과 보고 |
| `src/euler_campaign/qprime.py` | 범주 중간값, 최소 비율 joint의 동일 쌍, 계산용 RQD 하한, 무교차 convention 및 provenance, domain Jn 유지 | 사용자 Q′ 테스트 전체 통과 보고 |
| `src/euler_campaign/geometry.py` | 방향·시추공 변환, domain clipping, polyline station, Face 면적, 비교용 체적 검사, overlap | 반원 면적 오류 수정 후 사용자 테스트 전체 통과 보고 |
| `src/euler_campaign/profiles.py` | 완전 구간 BH profile 및 Deere RQD, Face Priest–Hudson RQD, 수직 Face 방향별 RQD 평균, scanline metadata, 무효 Face 처리 | 사용자 profile 테스트 전체 통과 보고; 마지막 확인 20:23 |

대응 테스트는 `src/test/test_euler_models.py`, `test_euler_qprime.py`,
`test_euler_geometry.py`, `test_euler_profiles.py`다. 편집기 오류 확인에서는 오류가
보고되지 않았다. 테스트 통과는 사용자가 실행해 보고한 결과이며 assistant가 실행한
결과로 기록하지 않는다. 실제 DFN backend와 연결한 통합 simulation은 아직 검증하지 않았다.

Geometry 반원 면적 실패는 원에 접하는 선분의 중점을 원 내부로 취급한 오류였다.
접선 구간을 원호 면적으로 처리하도록 수정하고 네 방향 경계 회귀 테스트를 추가했다.
이 실패·수정 이력도 보존한다.

### 21.4 남은 구현 작업과 재개 지점

아래는 남은 작업 목록이며, 일괄 실행 승인이 아니다. 다음 재개 시에는 굴진장 정책과
터널 진행을 한 단계씩 검토하고 사용자 요청 범위만 구현한다.

- [ ] **굴진장 정책 확정 및 구현:** `profiles.py`의 `next_round_length`.
  `Q′>10`은 4.0m, `Q′<=0.1`은 0.75m, 유한 범위는 중간값이라는 기존 결정은 유지한다.
  중간 Q′ 구간별 길이 표는 현재 확인된 문서에 구체 수치가 없으므로 사용자와 확인한다.
- [ ] **Tunnel profile 진행:** `sample_tunnel`. 시작 Face는 첫 굴진장 결정에만 사용,
  미래 Face 값에 직전 실제 굴진장 support 부여, segment 끝에서 round 절단, vertex 직전
  방향, 무효 경계 Face에서 중단 및 마지막 유효 결과 보존.
- [ ] **분포 비교:** `compare_profiles`. 실제 overlap으로 길이 support를 자르고
  비짝지음 길이 가중 기술통계 및 Wasserstein-1 산출. 독립 조사용 시추공은 비교에서 제외.
- [ ] **Case 검증과 identity:** `models.py`의 `validate_case`, `identify_signature`,
  `identify_domain`은 현재 명시적으로 `NotImplementedError`다. 범주·geometry·절리군
  일관성 검증과 signature/domain identity 계약을 검토한 뒤 구현한다.
- [ ] **범주·case 설정 입출력:** `config.pyi`의 실제 구현. 승인된 범주표와 새 schema,
  범주 미지정 오류, 기존 평균·표준편차 입력 거부, 왕복 저장. 기존 case의 범주는 사용자가
  지정하며 자동 변환하지 않는다.
- [ ] **DFN 생성과 실제 교차 계산:** `ports.pyi`의 `JointFactory`, `Simulator`,
  `profiles.pyi`의 `JointGeometry` 구현체. 절리군 고정 조건을 joint에 전달하고 Face의
  domain 내부 부분만 교차 대상으로 반환한다. 지금까지 테스트는 통제된 교차 입력이다.
- [ ] **Profile coverage:** `coverage.pyi` 구현. 양의 실제 길이 bin 점유, seed별 parent gap,
  길이 가중 proximity, 동일 grid 비교 및 `ΔS=0.5D+0.5C`. Cutoff selector와 분리한다.
- [ ] **오일러 시그니처 갱신:** `euler.pyi` 구현. 밀도→크기→방향, 로그 좌표 probe,
  중앙차분, 약 5%/최대 5° 갱신, bounds, κ 고정, 독립 seed 3개 중 2개 이상 채택 기준.
  민감도를 약 5% 갱신 vector에 연결하는 정확한 정규화 식은 협의 전 구현하지 않는다.
- [ ] **새 campaign orchestration:** `campaign.pyi`를 구현. Parent→probe→민감도→후보→
  paired 검증→채택/비채택→다음 block, 경계 고정·전체 포화 중단, 명시적 실패 상태.
- [ ] **저장·재개 구현체:** `CampaignStore` 구현. Profile·seed·signature·grid·결정
  provenance 및 round/state의 일관된 저장, 중단 후 재개, 기존 결과와 혼합 방지.
- [ ] **실행 진입점:** 새 CLI와 simulation/store/update-rule 연결. 기존
  `validation/run_campaign.py`는 아직 교체하지 않는다.
- [ ] **통합 검증과 문서 정합화:** 실제 backend의 최소 end-to-end 경로, 재현성,
  중단·재개·seed 채택 검증을 단계별 승인 후 수행. 검증된 새 campaign만 전환 대상으로
  삼고 기존 파일 아카이브는 별도 승인 후 진행한다.

파일 수는 고정하지 않는다. 현재 선언 골격은 핵심 책임 분리이며, simulation·저장소
구현체와 실행 진입점이 빠져 있다. 선언 파일 존재를 구현 완료로 간주하지 않는다.
Longitudinal cutoff 표본 단위·가중·반복 측정 정책은 별도 미결 방법론으로 남으며,
오일러 갱신 구현에 암묵적으로 포함하지 않는다.
