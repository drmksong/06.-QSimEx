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
   - 초기 범위: `0.1~400`
   - 로그 공간 10구간
   - 양 끝점을 포함한 11개 후보
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
`Δx/ΔC`는 누적 pool이 아니라 같은 seed의 실제 비교 case로만 측정한다. ledger에는
누적 독립 domain·signature 수, 새/중복 domain 수와 audit 원본 CSV 목록을 기록한다.
기존 고Q v2 P32 10→20 case의 `target_bins=[8]` 설정은
`validation/highq_density_euler_proposed.json`에 검토용으로 두었다. `--dry-run`은
확인했으나 실제 실행은 `approved_for_screening` 명시 전까지 금지하며, 실행 결과는
생산용 기존 CSV를 입력으로 섞지 않는다.
