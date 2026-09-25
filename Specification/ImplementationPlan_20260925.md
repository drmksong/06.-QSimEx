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
- 최대 iteration 3회 이후에도 gap이 남으면 `exclude_as_unreachable`, 적용 범위 밖 또는
  `not_identifiable`로 기록한다.
