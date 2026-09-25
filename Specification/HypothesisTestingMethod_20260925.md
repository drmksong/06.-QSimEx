# QSimEx 가설 검정 방법 정의서

- 작성일: 2026-09-25
- 적용 단계: Phase 3 Q' 판정 기준값 탐색 및 Phase 4 통계적 재현성 검증
- 상태: 검정 방법 초안 확정본
- 기준 문서:
  - `DesignSpec_20260922.md`
  - `ImplementationPlan_20260925.md`
  - `QPrimeCutoffSelectionMethod_20260924.md`
  - `ProfileExploration_20260924.md`

## 1. 목적

이 문서는 시뮬레이션 결과에서 새 Phase 3 가설이 반복적으로 관찰되는지를 검정하는
방법을 정의한다. 검정의 목적은 단일 p-value로 Q' 기준값을 확정하는 것이 아니라,
낮은 Q'\_BH 구간의 불리한 프로파일과 높은 Q'\_BH 구간의 안정 프로파일이 독립 DFN
domain과 주요 configuration에서 재현되는지 확인하는 것이다.

이 문서는 가상굴착 참조 프로파일을 이용한 Q' lower/upper cutoff 후보의 통계적
검정에 적용한다. cutoff 후보 산출 자체에는 EFPC가 필요하지 않다. 실제 현장 안전성,
처분 적합성, 적합·부적합 라벨에 대한 후속 성능 검증만 EFPC 또는 독립 평가 adapter가
연결된 이후에 수행한다.

## 2. 검정 대상 가설

### 2.1 주 가설

충분한 독립 DFN seed/domain을 확보하면 낮은 `Q'_BH` 구간에서 불리한 가상굴착
참조 프로파일이 나타나고, 높은 `Q'_BH` 구간에서 안정된 참조 프로파일이 나타나며,
이 방향성이 여러 configuration에서 반복된다.

### 2.2 세부 가설

- H1: `Q'_BH` 구간에 따라 `Q'_face` 프로파일이 변화 전, 변화, 변화 후 안정 상태로
  구분된다.
- H2: 절리 교차·누락·밀도 관련 프로파일이 `Q'_BH` 구간 변화와 함께 반복 가능한
  패턴을 보인다.
- H3: 방향성 또는 교차각 관련 프로파일이 독립 domain에서 같은 방향의 변화 또는
  안정화를 보인다.
- H4: 공통 PR 영역과 공통 POST 영역이 configuration 간에 일정하게 재현된다.
- H5: 공통 PR/POST 영역으로부터 제안한 lower/upper 후보가 domain 재표본화에서도
  크게 변하지 않는다.

기존 H1~H5의 pooled row p-value는 탐색적 보조 결과로만 보존하며, lower/upper
확정의 단독 근거로 사용하지 않는다.

## 3. 분석 단위와 독립성

### 3.1 관측 단위

- 기본 관측 단위: borehole row
- 설명 변수: `Qp_bh_mean`
- 가상굴착 참조 프로파일: `Qp_face_mean`, 절리 교차·누락, 밀도, 방향성·교차각,
  크기 관련 지표

### 3.2 독립 단위

- 통계적 독립 단위: `domain_id`
- `domain_id`는 최소한 `case_name`, seed, DFN generation signature를 포함해야 한다.
- 동일 domain에서 생성된 여러 face 위치, borehole 위치, 반복 row는 하나의 cluster로
  묶는다.
- 동일 domain의 row를 독립 표본으로 취급하여 표본 수나 유의성을 과대평가하지 않는다.

### 3.3 필수 생성 메타데이터

각 결과 row와 별도 manifest에 다음을 기록한다.

- `domain_id`
- `case_name`
- `seed`
- configuration 또는 case 경로
- DFN generation signature 및 안정적인 signature hash
- joint set별 P32, 방향성, 크기 범위·분포, 절리군 수
- domain 크기·격자·터널·시추공 설정
- backend, correction mode, simulation 실행 식별자
- Train/Validation/coverage-pilot 구분

## 4. 분석 자료 분리

자료는 다음 세 종류로 분리한다.

1. `coverage_pilot`
   - Q' reachability와 빈 구간 보강 가능성을 확인하는 자료
   - 최종 calibration/validation 근거에 편입하지 않음
2. `calibration_train`
   - lower/upper 후보를 탐색하고 검정 방법을 적용하는 자료
   - domain 단위로 Validation과 분리
3. `blind_validation`
   - Train에서 고정한 후보를 재튜닝 없이 적용하는 자료
   - Train과 seed/domain이 겹치지 않음

중단된 과거 실행 결과는 재개 실행과 섞지 않는다. 재개 시 동일한 configuration,
seed, domain_id, 실행 식별자를 기록하고 이미 완료된 domain은 명시적으로 deduplicate한다.

## 5. 1차 검정: domain cluster bootstrap

### 5.1 기본 절차

각 bootstrap 반복에서 다음 절차를 수행한다.

1. 독립 `domain_id`를 복원추출한다.
2. 선택된 domain에 속한 모든 borehole/face row를 함께 가져온다.
3. 사전 고정한 Q' 후보 구간에 따라 각 profile의 분포를 계산한다.
4. 각 bin의 중앙값, Q1, Q3, 유효 표본 수, domain 수를 계산한다.
5. 인접 bin 변화량과 안정 구간을 계산한다.
6. profile별 `PR`, `TR`, `POST` 상태를 부여한다.
7. 핵심 profile의 공통 PR/POST 교집합을 계산한다.
8. lower/upper 후보와 식별 상태를 저장한다.

기본 bootstrap 단위는 domain이다. 한 domain 안의 row 수가 많더라도 domain을 여러
번 복제하여 가중하지 않는다. 필요하면 domain 내부에서는 row를 추가로 재표본화할
수 있으나, 이는 민감도 분석으로만 보고한다.

### 5.2 권장 기본 설정

- bootstrap 반복 수는 고정값이 아니라 단계적으로 증가시킨다.
  - pilot: `B = 200`
  - intermediate: `B = 500`
  - final default: `B = 1000`
  - sensitivity 확인이 필요한 경우에만 `B = 2000`
- 재현 가능한 bootstrap seed 저장
- 양측 95% percentile interval
- domain 수가 적은 경우 BCa interval을 자동으로 주장하지 않음
- `B`를 늘릴 때 lower/upper 중앙값, 구간 폭, 상태 비율이 안정되는지 확인

`B` 값은 계산 비용과 안정성에 따라 조정할 수 있으나, 조정한 경우 설정과 이유를
결과에 기록한다. 다음 조건을 만족하면 더 큰 `B`로 진행하지 않아도 된다.

- lower/upper 후보 중앙값의 변화가 사전 허용 범위 이내
- 95% 구간 폭의 변화가 사전 허용 범위 이내
- `identified`, `provisional`, `conflicting`, `not_identifiable` 비율이 안정됨
- 다음 bootstrap 단계가 최종 상태나 해석을 바꾸지 않음

Bootstrap은 기존 simulation row를 재표본화하는 후처리이며 DFN을 다시 생성하지
않는다. 따라서 대규모 simulation의 실행 시간과 bootstrap 반복 수를 곱하지 않는다.

### 5.3 bootstrap 산출물

- bin별 profile 중앙값과 95% 구간
- bin별 변화량과 95% 구간
- profile별 상태 출현 비율
- 공통 PR/POST 영역 출현 비율
- lower/upper 후보 분포와 95% 구간
- `identified`, `provisional`, `conflicting`, `UNOBSERVED`,
  `not_identifiable` 출현 비율
- configuration별 domain 재현성

## 6. 빈 구간과 상태 판정

빈 bin은 변화가 없는 `TR`이 아니다. 다음 규칙을 적용한다.

- 표본 또는 최소 독립 domain 수가 부족한 bin: `UNOBSERVED`
- 관측 범위 내부의 빈 bin: 내부 coverage gap으로 기록하고 configuration 보강 대상으로 지정
- 관측 범위 바깥의 빈 bin: reachability 미확인으로 기록
- 일부 profile만 유효한 bin: 해당 profile은 `UNOBSERVED`, 전체 결과는 `provisional`
- 핵심 profile의 상태 방향이 서로 충돌: `conflicting`
- coverage 보강 후에도 공통 PR/POST가 없거나 lower >= upper: `not_identifiable`
- 충분한 domain 수, profile 공통성, 불확실성 조건을 모두 만족: `identified`

`UNOBSERVED` bin은 PR/TR/POST 교집합 계산에서 관측된 상태로 취급하지 않는다.
빈 구간을 TR로 대체하여 변화점이 생긴 것처럼 보고하지 않는다.

## 7. 상태 및 식별 판정 기준

최종 최소 기준은 분석 시작 전에 configuration으로 고정한다.

- bin별 최소 독립 domain 수
- configuration별 최소 domain 수
- bin별 최소 유효 row 수
- bootstrap에서 상태가 재현되어야 하는 최소 비율
- lower/upper 후보의 허용 불확실성 폭
- configuration 간 경향 충돌을 판정하는 규칙

정책 허용치나 임의의 Q' 단일 기준값은 사용하지 않는다. 최소 domain 수와 불확실성
기준을 정하지 못한 경우 결과 상태는 `provisional` 또는 `not_identifiable`로 남긴다.

## 7.1 Coverage-adaptive 반복 검정

가설 검정은 한 번의 대규모 실행으로 종료하지 않는다. 각 검정 라운드의 coverage
결과를 다음 simulation round의 configuration 설계에 반영하는 반복 절차를 사용한다.

```text
Iteration k
  -> 현재 scenario/signature 전체를 seed 1개씩 sweep
  -> coverage audit
  -> 과밀/공백 구간 진단
  -> 빈 구간을 메울 신규 generation signature 추가
  -> 기존 + 신규 scenario/signature 전체를 Iteration k+1에서 재-sweep
  -> coverage 기여 signature만 독립 seed/domain 확장
  -> profile search 및 domain cluster bootstrap
  -> 상태·coverage·불확실성 판정
  -> 다음 iteration 또는 종료
```

기존 signature의 seed를 먼저 대량 확장하지 않는다. coverage gap이 확인되면 gap을
메울 수 있는 신규 signature를 추가하고, 다음 iteration에서 기존 signature와 신규
signature 전체를 다시 실행한다. seed 확장은 새 signature가 목표 bin을 만들고 profile
방향을 재현하는지 확인한 뒤 수행한다.

### 7.1.1 구간 진단

각 Q' bin에 대해 row 수만 보지 않고 다음을 함께 기록한다.

- 유효 row 수
- 독립 `domain_id` 수
- configuration signature 수
- case 수와 seed 수
- profile별 유효값 수와 결측 수
- bootstrap에서 해당 bin이 관측되는 비율
- 인접 bin과의 Q' 분포 중첩도

Q' 값이 많이 겹치는 구간은 즉시 자료를 삭제하거나 하나의 domain으로 합치지 않는다.
다음 두 경우를 구분한다.

1. 여러 독립 domain과 configuration에서 같은 구간이 반복됨: 해당 구간의 재현성이
   높다는 뜻이므로 domain 수와 profile 안정성을 우선 확인한다.
2. 소수 configuration 또는 동일 domain의 row가 같은 구간에 집중됨: 실질적인
   coverage 다양성이 부족하므로 configuration을 분리하고 독립 domain을 추가한다.

필요하면 중첩이 과도한 구간에 관측 범위 기반 adaptive bin을 적용하여 고정 log bin과
비교한다. adaptive bin은 자료를 삭제하기 위한 것이 아니라 profile 변화와 domain
재현성을 더 잘 분리하기 위한 민감도 분석이다.

### 7.1.2 빈 구간의 generation signature 보강

`UNOBSERVED` bin은 최종 판정 불가로 즉시 종료하지 않는다. 해당 bin이 다음 중 어느
경우인지 구분한다.

- 기존 관측 범위 내부의 gap: 기존 configuration 사이의 조합을 보간하거나 인접
  configuration을 조정하여 보강한다.
- 관측 범위 바깥의 gap: reachability pilot을 통해 생성 가능한 방향인지 확인한다.
- pilot에서도 도달하지 못한 gap: 적용 범위 밖 또는 추가 configuration 가정이
  필요한 영역으로 기록한다.

보강 후보는 이전 실행의 generation signature를 기준으로 만들며, 다음 feature를
명시적으로 조정·기록한다.

- joint set별 P32와 평균 spacing
- 절리 방향, Fisher 집중도, 방향성 및 이방성
- 절리 크기 분포와 최소·최대 크기
- 절리군 수와 구조 배열
- 터널·시추공 방향 및 상대 교차각
- domain 크기, 관측 window, seed

후보 signature는 기존 signature와의 차이, 예상 Q' 이동 방향, 선택 이유를 manifest에
저장한다. configuration 선택용 seed와 최종 Train/Validation seed는 분리한다.

### 7.1.3 반복 라운드 종료 조건

다음 조건을 만족하면 coverage 보강 라운드를 종료하고 calibration/validation 자료로
승격 여부를 검토한다.

- 저Q·중간Q·고Q 구간별 최소 독립 domain 수를 충족함
- 핵심 bin의 `UNOBSERVED` 비율이 사전 기준 이하임
- 각 핵심 구간에 충분한 configuration signature가 존재함
- Q' 분포와 profile 경향이 추가 domain에서 재현됨
- bootstrap 후보와 상태가 반복 라운드 사이에서 안정됨

반대로 다음 경우에는 추가 보강을 계속하거나 적용 범위 밖으로 기록한다.

- 특정 bin이 반복 라운드에서도 계속 비어 있음
- signature를 바꾸어도 Q' 이동이 발생하지 않음
- configuration별 profile 방향이 충돌함
- 과밀 구간의 결과가 동일 domain 반복에 의해 설명됨
- lower/upper 후보가 반복 라운드에서 역전됨

coverage-adaptive iteration의 최대 반복 수는 기본 `3회`로 한다.

- Iteration 0: 기존 scenario/signature 전체 baseline sweep
- Iteration 1: gap을 메울 신규 signature 추가 후 전체 재-sweep
- Iteration 2: 새로 관측된 gap을 대상으로 signature 추가 후 전체 재-sweep
- Iteration 3: 남은 핵심 gap과 재현성 확인

Iteration 3 이후에도 핵심 bin이 계속 `UNOBSERVED`이거나 signature를 조정해도 Q' 이동이
없으면 무한히 simulation을 반복하지 않는다. 해당 구간을 `exclude_as_unreachable`,
적용 범위 밖 또는 `not_identifiable`로 기록하고 다음 단계로 넘어간다.

각 라운드 종료 시 다음 라운드로 진행할지, 3회 한도에 도달했는지 명시적으로
기록한다.

coverage pilot 자료는 이 반복 과정에서 reachability 판단에만 사용하고, 최종
calibration/validation 자료에는 독립적으로 승인된 경우에만 편입한다.

### 7.1.4 실행 환경과 시간 제한

simulation backend는 GPU 우선 정책을 따른다. `auto`는 MLX/CUDA/MPS 중 사용 가능한
GPU를 먼저 선택하고 CPU는 최후 fallback으로만 사용한다. CPU 실행은 smoke test 또는
명시적 긴급 fallback에서만 허용하며, 대규모 calibration/validation에서는 backend와
GPU 미감지 사유를 manifest에 기록한다.

Mac에서 simulation이 사전 지정한 시간 제한을 초과하면 실행을 중단하고, 완료된
seed/domain과 checkpoint를 보존한다. 중단 자체를 실패로 간주하지 않으며, 동일한
round manifest와 미완료 seed 목록을 PC Workstation에서 재개한다.

Workstation 재개 시 다음을 보장한다.

- 동일한 code version 또는 commit 식별자
- 동일한 configuration과 generation signature
- 동일한 seed 목록과 backend 설정 기록
- 기존 `domain_id`와 signature hash 중복 검사
- Mac checkpoint와 Workstation 결과의 결합 전 schema 검증

Mac과 Workstation의 backend가 다를 경우 결과를 하나의 calibration 자료로 바로
합치지 않고, backend를 metadata에 기록한 뒤 profile 방향과 수치 차이를 별도
reproducibility check로 확인한다.

### 7.1.5 자동화 범위

현재 QSimEx 코드는 결과 row에 generation signature와 `domain_id`를 저장하고,
`audit_qprime_coverage`로 빈 구간을 식별하며, coverage pilot configuration을
수동으로 실행할 수 있다. 그러나 현재 단계에는 coverage audit 결과에서 새로운
generation signature 후보를 자동 제안하고, 다음 pilot configuration을 자동 생성하는
엔진이 없다.

따라서 구현 시 다음 산출물을 별도 모듈로 추가한다.

- `coverage_round_<n>.json`: bin별 coverage, 중첩도, domain/signature 수, 상태
- `generation_signature_candidates_<n>.json`: 보강 후보와 feature 변경 내역
- `coverage_manifest_<n>.json`: pilot/train/validation seed와 domain 중복 여부
- `coverage_round_<n>.md`: 보강 사유, 도달성 결과, 다음 라운드 결정

자동 제안기는 정책 허용치나 Q' 단일 threshold를 사용하지 않고, 관측 공백·인접
configuration·실제 도달 결과를 근거로 후보를 제안한다. 최종 후보의 승인과 Train/
Validation 편입은 별도 단계에서 수행한다.

### 7.1.6 Coverage round ledger

coverage 보강 과정은 라운드별 ledger로 누적 기록한다. 각 라운드는 이전 라운드의
결과를 덮어쓰지 않고 새로운 기록으로 추가한다. 이를 통해 특정 Q' 구간이 언제
관측되기 시작했는지, 어떤 generation signature가 coverage를 이동시켰는지, 보강이
실패했는지를 추적할 수 있어야 한다.

각 라운드의 기본 식별자는 다음과 같다.

- `round_id`: 단조 증가하는 라운드 번호
- `run_id`: 해당 라운드 실행 묶음의 고유 식별자
- `parent_round_id`: 후보 signature를 만든 직전 라운드
- `round_type`: `baseline`, `coverage_pilot`, `coverage_expansion`, `calibration`,
  `validation`
- 실행 시각, 코드 버전 또는 commit 식별자, 설정 파일 hash

각 라운드는 다음 네 가지 기록을 함께 보존한다.

1. **계획 기록**
   - 직전 round의 bin별 상태와 coverage 부족 사유
   - 보강 대상 Q' 구간
   - 선택한 generation signature와 변경한 feature
   - 예상 Q' 이동 방향과 선택 근거
   - configuration 선택용 seed 목록
2. **실행 기록**
   - case/configuration 경로
   - seed, `domain_id`, generation signature hash
   - backend, correction mode, 실행 성공·실패·중단 상태
   - 완료 domain 수와 중복·제외 domain 수
3. **관측 기록**
   - bin별 row 수, 독립 domain 수, seed 수, configuration 수
   - 관측 최소·최대 Q'
   - `observed`, `UNOBSERVED`, 내부 gap, 범위 밖 gap
   - profile별 유효값 수와 결측 수
   - bin별 Q' 분포와 인접 bin 중첩도
4. **판정 기록**
   - profile 상태와 bootstrap 재현 비율
   - lower/upper 후보 및 불확실성
   - `provisional`, `identified`, `conflicting`, `not_identifiable` 상태
   - 다음 라운드 결정: `expand`, `refine_bins`, `accept_for_calibration`,
     `exclude_as_unreachable`, `stop`

라운드 간 coverage 변화는 동일한 bin 정의와 동일한 지표로 계산한다. 최소한 다음
변화량을 기록한다.

- 관측 Q' 범위의 변화
- 각 bin의 row/domain/signature 수 변화
- `UNOBSERVED` bin 수와 비율 변화
- 내부 gap과 범위 밖 gap의 변화
- 핵심 profile의 유효값 coverage 변화
- bootstrap에서 `identified` 또는 `provisional`이 된 비율 변화
- 새로 관측된 bin과 여전히 비어 있는 bin

권장 산출물 구조는 다음과 같다.

```text
results/coverage_rounds/
  ledger.jsonl
  round_000_baseline/
    plan.json
    manifest.json
    coverage_audit.json
    profile_search.json
    bootstrap_summary.json
    decision.md
  round_001_coverage_pilot/
    plan.json
    manifest.json
    coverage_audit.json
    profile_search.json
    bootstrap_summary.json
    decision.md
```

`ledger.jsonl`의 한 행은 한 라운드를 요약하며, 최소한 다음 필드를 포함한다.

```json
{
  "round_id": 1,
  "run_id": "20260925-r001-lowq",
  "parent_round_id": 0,
  "round_type": "coverage_expansion",
  "observed_qprime_range": [1.86, 266.67],
  "n_domains": 24,
  "n_signatures": 7,
  "unobserved_bins_before": 4,
  "unobserved_bins_after": 2,
  "newly_observed_bins": [1, 2],
  "remaining_gap_bins": [8, 9],
  "status": "provisional",
  "next_action": "expand"
}
```

각 라운드의 결과를 합칠 때는 `domain_id`와 generation signature hash를 기준으로
중복을 검사한다. 동일 domain을 새 라운드에서 다시 실행한 경우 새 관측으로 세지 않고
`duplicate_domain_ids`에 기록한다. 단, 코드 버전이나 configuration이 바뀌어 동일
seed라도 실제 생성 조건이 달라진 경우에는 signature hash가 달라지므로 별도 domain
또는 재현성 비교 대상으로 분리한다.

## 8. 보조 분석

주 검정 결과를 보완하기 위해 다음 분석을 수행할 수 있다.

### 8.1 Configuration별 추세 분석

각 configuration과 domain을 분리하여 Q' bin별 profile 방향을 확인한다. pooled 결과와
configuration별 결과의 방향이 일치하는지 비교한다. pooled row의 단순 상관이나
p-value는 독립성 보정 없이 최종 근거로 사용하지 않는다.

### 8.2 계층 모델

domain별 random intercept 또는 random slope를 포함한 계층 모델을 검토할 수 있다.
계층 모델은 domain 수와 profile 분포가 충분할 때만 사용하며, cluster bootstrap과
결과 방향·불확실성을 비교하는 민감도 분석으로 시작한다.

### 8.3 Adaptive binning 민감도

다음 두 binning 결과를 비교한다.

- 고정 `0.1~400` 로그 bin
- 관측 범위와 domain 수를 고려한 adaptive bin

두 방식에서 상태와 후보가 크게 달라지면 결과를 `provisional`로 낮춘다.

## 9. 판정 규칙

다음 조건을 모두 만족할 때만 `identified` 후보를 기록한다.

1. 각 핵심 bin에 최소 독립 domain 수가 확보됨
2. 핵심 profile에 `UNOBSERVED`가 남아 있지 않음
3. bootstrap에서 공통 PR/POST 구조가 사전 기준 이상 재현됨
4. lower와 upper가 모든 주요 분석에서 역전되지 않음
5. configuration 간 경향 충돌이 없음
6. lower/upper 후보의 bootstrap 불확실성이 허용 범위 안에 있음

일부 조건만 만족하면 `provisional`이다. coverage 부족, 상태 충돌 또는 후보 역전이
해소되지 않으면 `not_identifiable`이다.

`identified`는 시뮬레이션 기반 잠정 가이드의 식별을 의미하며, 실제 현장 안전이나
처분 적합성을 보증하지 않는다.

## 10. EFPC 미연결 시 적용 범위와 금지 사항

EFPC가 연결되지 않아도 다음 Phase 3 핵심 결과는 산출한다.

- Q' 후보 구간별 profile 분포
- PR/TR/POST와 `UNOBSERVED` 상태
- 공통 PR/POST 교집합
- lower/upper cutoff 후보
- cutoff 후보의 bootstrap 불확실성과 재현성

이 결과는 시뮬레이션 기반 잠정 cutoff이며, EFPC 부재를 이유로 산출을 보류하지
않는다. 다만 다음 공학적 성능 지표는 EFPC 또는 독립 평가 adapter가 연결되기 전에는
계산하거나 주장하지 않는다.

- suitable/unsuitable 정답 라벨
- false-safe, false-reject
- sensitivity, specificity, AUC
- 처분 적합성 또는 현장 안전성 보증
- `Qp_face_mean` 단일 threshold 기반 적합성 분류

## 11. 결과 보고서 구조

검정 결과는 최소한 다음 순서로 저장·보고한다.

1. 실행 식별자와 configuration/seed/domain manifest
2. coverage audit 및 `UNOBSERVED` 구간
3. profile별 bin 통계와 상태
4. domain cluster bootstrap 설정과 재현성
5. lower/upper 후보 분포 및 불확실성
6. configuration별 방향성·충돌 여부
7. 최종 상태와 판정 불가 사유
8. 적용 범위, 제외 자료, 한계

## 12. 구현 순서

1. 이 정의서의 검정 설정과 상태 판정 규칙을 configuration schema로 고정한다.
2. 배치 결과에 `domain_id`와 generation feature/signature를 저장한다.
3. coverage pilot, Train, Validation manifest를 분리 생성한다.
4. 빈 bin을 `UNOBSERVED`로 처리하고 adaptive binning을 추가한다.
5. domain cluster bootstrap을 구현하고 단위 테스트를 작성한다.
6. 기존 coverage 결과를 새 schema로 재분석한다.
7. 소규모 smoke run으로 재현성과 결과 schema를 확인한다.
8. 대규모 simulation을 실행한다.
9. bootstrap 및 configuration별 검정을 수행한다.
10. Train에서 후보를 고정하고 blind Validation을 수행한다.

레거시 분석 코드는 감사·재현 기록을 위해 보존하되, 이 정의서의 검정 경로에 연결하지
않는다.
