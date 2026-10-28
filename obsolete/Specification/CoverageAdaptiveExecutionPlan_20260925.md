# QSimEx Coverage-Adaptive 실행 및 자동화 계획

- 작성일: 2026-09-25
- 적용 단계: Phase 3 Q' cutoff 탐색 및 Phase 4 통계적 재현성 검증
- 상태: 구현 계획
- 관련 정의서:
  - `HypothesisTestingMethod_20260925.md`
  - `DesignSpec_20260922.md`
  - `ImplementationPlan_20260925.md`

## 현재 적용 상태 (2026-10-04)

이 계획서는 2026-09-25에 작성되고 이후 날짜별로 보완된 작업 기록이다. 아래의 과거
계획과 변경 이력은 당시 판단을 보존하기 위한 것으로, 이 안내와 DesignSpec의 최신
날짜별 후속 결정에 어긋나는 항목을 현재 실행 규칙으로 사용하지 않는다. 새 방법이
필요하면 기존 기록을 지우지 않고 이 절 또는 별도 날짜별 후속 기록을 갱신한다.

현재 구현·후보 실행 전에 적용할 계약은
[DesignSpec_20260922.md](DesignSpec_20260922.md)의 5.6.9와 5.8이다.

| 주제 | 현재 적용 계약 | 이 계획의 과거 항목 처리 |
|---|---|---|
| feature 탐색 | 밀도 → 크기 → 방향 round-robin; 한 probe에서는 한 block만 변경; `fisher_kappa` 제외 | 90/10 schedule randomization 및 D/A/B/C/E 순서를 활성 정책으로 쓰지 않음 |
| coverage 관측 | 실제 profile 값이 속한 bin만 observed; 양의 길이 support; gap은 각 paired seed의 parent 기준 | scalar-only coverage는 legacy row 결과의 audit 맥락에 한정 |
| update | coverage score의 중앙차분 민감도 기반 bounded ascent; 양수 파라미터는 로그 좌표 계산, 약 5% update; 방향 `β` probe ±5°, update 최대 5° | 고정 `η=0.5`, update 미정/후보 판정 미정은 과거 제안 |
| 반복성 | 첫 탐색 seed 후 별도 seed 3개에서 paired parent/candidate; 2/3 이상에서 `ΔS>0` 및 observed-bin 비감소 시 방향 채택 | 최소 3회 screening 및 기존 거리/새 bin 판정은 과거 절차 |
| 경계·종료 | 도달한 파라미터는 가능한 방향에서 고정; 나머지를 계속 조정; 주 파라미터 전부 소진 시 campaign 중단 | 자동 κ/기타 조건 변경으로 재시도하지 않음 |
| simulation geometry | 물리 시추공 선형 geometry, tunnel polyline, profile overlap·station 보존·굴진장 규칙은 DesignSpec 5.8 적용 | offset-only 및 고정 +x 가정은 새 입력 계약으로 사용하지 않음 |
| cutoff | cutoff 산출은 별도 방법론; profile signature score는 cutoff 자체가 아님 | cutoff selection method의 미결 표본 단위를 임의로 결정하지 않음 |

위 표는 방법 간 정합성 안내이지 실행 승인이나 자동 대규모 simulation 승인이 아니다.
기존 round 산출물과 ledger는 변경하지 않는다.

## 1. 목적

시뮬레이션 결과를 한 번 분석하고 종료하지 않고, Q' coverage와 profile 검정 결과를
다음 simulation configuration 설계에 반영하는 반복 실행 체계를 구축한다.

핵심 결과는 시뮬레이션 기반 `lower_cutoff`와 `upper_cutoff` 후보이다. EFPC 또는
독립 평가 adapter는 cutoff 후보 산출의 선행조건이 아니며, 이후 처분 적합성·오류율·
기대손실 검증이 필요할 때 선택적으로 연결한다.

## 2. 전체 흐름

```text
기존 결과 로드
  -> coverage audit
  -> 빈 구간·과밀 구간 진단
  -> generation signature 후보 생성
  -> pilot manifest 작성
  -> simulation 실행
  -> 결과 수집·중복 제거
  -> coverage 변화 기록
  -> domain cluster bootstrap
  -> lower/upper cutoff 후보 산출
  -> 다음 round 또는 종료
```

각 round는 이전 결과를 덮어쓰지 않고 별도 artifact와 ledger 행으로 기록한다.

## 3. 자동화 대상과 수동 승인 대상

### 3.1 자동화 대상

- 기존 결과 CSV/JSON 수집
- Q' coverage audit
- bin별 row/domain/seed/signature 수 계산
- 내부 gap과 범위 밖 gap 구분
- 과밀 구간의 Q' 분포 중첩도 계산
- generation signature 후보 JSON 생성
- round simulation manifest 생성
- `domain_id`와 generation signature 중복 검사
- round 전후 coverage 변화 계산
- `ledger.jsonl` 갱신
- staged bootstrap 실행: `B=200 -> 500 -> 1000`
- lower/upper 후보와 bootstrap 불확실성 기록
- 완료·실패·중단 seed 목록 생성

### 3.2 수동 승인 대상

- generation signature 후보의 최종 선택
- 실제 대규모 simulation 실행 승인
- Mac에서 Workstation으로 작업을 넘길지 여부
- Workstation 결과를 calibration 자료에 편입할지 여부
- Round 3 이후 적용 범위 밖 또는 `not_identifiable` 확정

자동화는 후보를 제안하지만, 임의로 configuration을 승인하거나 Train/Validation
자료에 편입하지 않는다.

## 4. Round lifecycle

실행 순서는 seed를 먼저 소진하는 방식이 아니라 scenario/signature를 먼저 훑는
방식으로 고정한다.

```text
전체 scenario/signature를 seed 1개씩 실행
  -> coverage map 작성
  -> 빈 구간과 중복 구간 진단
  -> 빈 구간을 메울 새 generation signature 추가
  -> 기존 + 신규 scenario/signature 전체를 다음 iteration에서 재-sweep
  -> coverage 기여 signature만 seed 추가
  -> cutoff와 bootstrap 분석
```

### Iteration 0: Scenario/signature-first sweep

- 현재 보유한 모든 후보 scenario/signature를 독립 seed 1개로 실행한다.
- scenario별 Q' 범위, 새 bin, 중첩도, 절리 수, 실행 시간을 기록한다.
- 이 단계에서는 cutoff를 확정하지 않고 coverage map과 빈 구간만 평가한다.

### Iteration k+1: Gap signature 추가 및 전체 재-sweep

1. Iteration k의 coverage map에서 `UNOBSERVED`와 domain 부족 구간을 찾는다.
2. 인접 signature와 pilot 결과를 이용해 해당 구간을 메울 새 generation signature를
   설계하고 기존 목록에 추가한다.
3. 기존 scenario/signature와 신규 signature 전체를 seed 1개로 다시 실행한다.
4. 이전 iteration과 비교해 새 bin, 중복 감소, domain/signature 수 변화를 기록한다.
5. coverage를 넓힌 signature만 후속 독립 seed 확장 대상으로 검토한다. seed 수는
   고정하지 않고 반복 결과와 시간 기록으로 결정한다.
6. 여전히 빈 구간이 있으면 다음 iteration에서 signature를 추가한다.

기존 signature를 단순 반복하는 것은 새 signature 추가를 대체하지 않는다. 중앙 구간만
반복하고 새 bin이나 signature 다양성을 만들지 못한 scenario는 다음 iteration에서
seed 확장 대상에서 제외한다.

### Iteration 0: Baseline sweep

- 기존 결과를 새 schema로 읽는다.
- `domain_id`, generation signature hash, seed, case를 확인한다.
- 고정 log bin 기준 coverage audit을 수행한다.
- `UNOBSERVED`와 과밀 구간을 기록한다.
- 현재 보유한 전체 scenario/signature를 seed 1개씩 실행한다.
- 기존 결과는 최종 calibration/validation에 자동 편입하지 않는다.

### Iteration k+1: Gap signature 추가 및 전체 재-sweep

- Iteration k의 모든 `UNOBSERVED` gap을 순환 대상으로 등록한다. gap 사이의 의미적
  우선순위는 두지 않으며, 후보 상한 안에서 해결된 gap은 다음 순환에서 제외한다.
- 인접 configuration과 generation feature 차이를 비교한다.
- P32, 평균 spacing, 방향성, Fisher 집중도, 크기분포, 절리군 수, 교차각 등을
  조정한 후보 signature를 생성한다.
- 후보를 기존 scenario/signature 목록에 추가한다.
- 기존 + 신규 scenario/signature 전체를 다음 iteration에서 공통 seed 1개씩 재-sweep한다.
- 새로 관측된 bin, 중복 감소, domain/signature 수 변화를 이전 iteration과 비교한다.

### 후속 단계: coverage 기여 signature의 독립 domain 확장

- 전체 재-sweep에서 실제 Q' 이동과 profile 기여가 확인된 signature만 확장한다.
- 여러 독립 seed/domain을 추가한다.
- 기존 domain과 중복되지 않도록 signature hash와 `domain_id`를 검사한다.
- coverage audit과 staged bootstrap을 다시 수행한다.

### Signature identity와 explicit-Euler-style update 계약

- `generation_signature_hash`는 canonical generation feature만 사용하며 seed, 이름,
  tags, runtime과 round metadata를 포함하지 않는다.
- `domain_id`는 canonical generation feature, seed, domain identity와 generator
  version을 사용한다. 동일 DFN 재생성과 다른 domain을 구분하는 중복 검사의 기준이다.
- domain geometry, tunnel/borehole geometry, joint-set 구조와 observation window는
  immutable context로 보존한다.
- P32, spacing, 방향성, 크기분포 등 승인된 mutable feature만 normalized signature
  space에서 bounded explicit-Euler-style iterative update한다. 이는 미분방정식 solver가
  아니라 simulation-guided 후보 갱신 규칙이다.
- midpoint와 Euler-style 후보의 `Δx`, coverage `ΔC`, residual, step size와 projection 결과를
  round ledger에 기록한다.
- 시간 예산은 soft planning signal이다. low-Q 후보를 runtime만으로 제외하지 않으며,
  예상·실제 시간 차이와 정보량을 다음 round에 반영한다.

### Feature 탐색 schedule

기본 schedule은 `joint-set structure -> density -> size distribution -> orientation ->
seed realization` 순서로 둔다. 여기서 seed realization은 generation signature 변경이
아니라 독립 domain 재현성 확인 단계다. 각 단계의 coverage 결과와 Euler 방향 추정에
따라 같은 단계를 반복하거나 다음 단계로 이동한다.

전체 schedule의 약 90%는 기본 순서를 사용하고, 약 10%는 기록된 randomization seed로
순서만 재배열한다. randomization은 feature 값 생성이 아니며, bounds·immutable context·
공통 seed·provenance를 변경하지 않는다. `schedule_mode`, feature 순서와
`randomization_seed`는 round ledger에 기록한다.

### 기본 3회 이후의 재현성 확인

- 남은 핵심 gap과 profile 방향 충돌을 확인한다.
- 독립 domain에서 Q' 범위와 profile 경향이 재현되는지 검증한다.
- lower/upper 후보가 반복 round에서 안정되는지 확인한다.
- 최소 3회의 공통-seed 변경 screening 후에도 방향성과 coverage 기여가 없을 때 종료
  또는 후순위화를 검토한다. 3회는 기본값이며, 정보량·시간·재현성 근거에 따라 조정한다.

## 5. Generation signature 후보 생성 규칙

후보 생성기는 Q' cutoff 숫자를 직접 목표로 사용하지 않는다. 다음 정보를 이용한다.

- 보강 대상 bin의 Q' 범위
- 인접 bin의 관측 configuration
- 기존 configuration의 generation signature
- pilot에서 실제 관측된 Q' 이동 방향
- 독립 domain과 signature 수
- profile의 `UNOBSERVED`, 충돌 및 불확실성 상태

조정 가능한 feature:

- joint set별 P32와 평균 spacing
- 절리 방향과 Fisher 집중도
- 방향성 및 이방성
- 절리 크기 분포와 최소·최대 크기
- 절리군 수와 구조 배열
- 터널·시추공 방향과 상대 교차각
- domain 크기, observation window, seed

후보에는 다음을 함께 저장한다.

- `candidate_id`
- parent signature hash
- 변경 feature와 이전·새 값
- 예상 Q' 이동 방향
- 보강 대상 bin
- 선택 이유
- configuration 선택용 seed
- Train/Validation seed와의 중복 여부

## 6. 산출물 구조

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
    generation_signature_candidates.json
    manifest.json
    coverage_audit.json
    profile_search.json
    bootstrap_summary.json
    decision.md
```

`ledger.jsonl`에는 round별로 다음을 기록한다.

- `round_id`, `run_id`, `parent_round_id`, `round_type`
- 실행 시각, code/commit 식별자, config hash
- 관측 Q' 최소·최대 범위
- row/domain/seed/signature 수
- `UNOBSERVED` 전후 bin 수
- 새로 관측된 bin과 남은 gap
- cutoff 후보와 bootstrap 상태
- `status`: `provisional`, `identified`, `conflicting`, `not_identifiable`
- `next_action`: `expand`, `refine_bins`, `accept_for_calibration`,
  `exclude_as_unreachable`, `stop`

## 7. Bootstrap 실행 예산

bootstrap은 기존 simulation 결과의 후처리이며 DFN을 재생성하지 않는다.

- pilot: `B=200`
- intermediate: `B=500`
- final default: `B=1000`
- 민감도 확인이 필요할 때만 `B=2000`

lower/upper 중앙값, 95% 구간 폭, 상태 비율이 안정되면 더 큰 B로 진행하지 않는다.

## 8. 실행 환경과 재개

모든 simulation round는 **GPU 우선**으로 실행한다.

- Apple Silicon: `mlx` 우선, 이어서 `mps`
- NVIDIA Workstation: `cuda` 우선
- `auto`: 사용 가능한 GPU backend를 위 순서로 감지
- `cpu`: 테스트·긴급 fallback에서만 명시적으로 사용

CPU로 자동 전환된 경우에는 로그와 round manifest에 GPU 미감지 사유를 남기며,
대규모 calibration/validation 실행을 CPU로 조용히 진행하지 않는다.

Mac에서 사전 지정한 시간 제한을 초과하면 다음을 보존한다.

- 완료 seed/domain checkpoint
- 미완료 seed 목록
- 동일 round manifest
- code/commit과 backend 정보
- 실행 로그와 실패 사유

Workstation 재개 시 다음을 확인한다.

- 동일 code version 또는 commit
- 동일 configuration과 generation signature
- 동일 seed 및 미완료 seed 목록
- `domain_id`와 signature hash 중복 여부
- 결과 schema 일치 여부

backend가 Mac과 Workstation에서 다르면 calibration 자료에 바로 합치지 않고,
profile 방향과 수치 차이를 별도 재현성 검증으로 기록한다.

## 9. 종료 조건

다음 조건을 만족하면 coverage round를 종료하고 cutoff 후보를 calibration 대상으로
검토한다.

- 저Q·중간Q·고Q 구간별 최소 독립 domain 수 확보
- 핵심 bin의 `UNOBSERVED` 비율이 기준 이하
- 충분한 configuration signature 확보
- 추가 domain에서 Q' 범위와 profile 경향 재현
- `B=200`, `500`, `1000` 결과가 안정
- lower < upper이고 반복 round에서 역전되지 않음

Round 3 이후에도 다음 중 하나가 남으면 무한 반복하지 않는다.

- 특정 bin이 계속 `UNOBSERVED`
- signature 조정에도 Q' 이동이 없음
- configuration별 profile 방향이 충돌
- cutoff 후보가 계속 역전

이 경우 해당 구간을 `exclude_as_unreachable`, 적용 범위 밖 또는
`not_identifiable`로 기록한다.

## 10. 구현 순서

1. `src/core/signature_candidates.py` 구현
2. generation signature 후보 JSON 생성
3. round manifest와 YAML 생성
4. 결과 수집·중복 제거 연결
5. coverage audit과 ledger 자동 연결
6. staged bootstrap 자동 연결
7. Mac/Workstation 재개 manifest 생성
8. Round 0 smoke 실행
9. Round 1 pilot 실행
10. 승인 후 독립 domain 대규모 확장

현재 구현된 기반:

- domain metadata 저장
- seed checkpoint 저장
- `UNOBSERVED` 상태 처리
- domain cluster bootstrap
- coverage delta와 ledger 기록

다음 미완성 구현은 generation signature 후보 생성기와 round manifest/YAML 자동
생성기이다.

## 11. 2026-09-26 실행 전략 변경 이력

초기 계획의 “기존 scenario/signature를 seed 1개씩 sweep한 뒤 coverage 결과를 보고
유효 후보를 확장”하는 원칙을 유지한다. 후보의 수와 구체적인 생성 규칙은 아직
확정하지 않는다.

| 항목           | 이전 계획                        | 현재 조정안                                                                         |
| -------------- | -------------------------------- | ----------------------------------------------------------------------------------- |
| 후보 규모      | 기존 signature와 일부 pilot 중심 | coverage gap과 중복 분석 결과에 따라 필요한 후보를 단계적으로 추가                  |
| 기존 결과 활용 | baseline 확인 후 재실행 가능성   | 기존 500 domain과 pilot 결과를 baseline/reachability 근거로 우선 재사용             |
| screening      | signature를 seed 1개씩 확인      | 전체 pool을 동일한 공통 seed로 순회하여 signature 효과 비교                         |
| seed 변경      | 후보별 독립 seed 확장            | 다음 iteration에서 공통 seed를 바꿔 전체 pool 재-sweep                              |
| 확장 대상      | coverage가 좋아 보이는 후보      | 새 bin·gap 감소·profile 방향 반복을 모두 만족한 후보만 후속 seed 확장 대상으로 검토 |

신규 후보는 cutoff 숫자를 직접 맞추기 위한 후보가 아니다. 저Q·고Q·중간 coverage
gap을 확인한 뒤 필요한 만큼 추가하며, 각 후보의 parent signature, 변경 feature, 목표
gap, 예상 이동 방향, 공통 seed, 결과 provenance를 manifest에 기록한다. 후보는 별도
승인 전까지 calibration/validation 자료로 편입하지 않는다.

signature 생성 로직과 후보 수는 아직 논의·합의되지 않았다. 현재 구현은 후보 생성
규칙을 확정한 것으로 해석하지 않으며, 자동 생성보다 먼저 coverage 결과와 중복 판단
기준을 합의한다.

## 12. 합의된 후보 생성 흐름

각 coverage iteration은 다음 순서를 따른다.

1. 기존 결과와 직전 round 결과로 coverage audit을 수행한다.
2. `UNOBSERVED` gap, 관측 범위, 과밀 구간과 기존 signature 중복을 진단한다.
3. audit 근거가 있는 gap에 대해서만 parent signature와 후보 계획을 만든다.
4. 후보 계획을 검토한 뒤 같은 iteration의 signature를 공통 seed로 screening한다.
5. 새 bin과 profile 변화를 확인하고, 다음 iteration에서 추가·유지·후순위화 대상을
   결정한다.

후보 수는 고정하지 않는다. 후보 feature와 변경 폭도 아직 확정하지 않았으며, 무작위
조합이나 cutoff 목표 기반 생성은 허용하지 않는다. 후보 계획은 실행 전 검토 가능한
artifact로 보존하고, calibration/validation 자료로 자동 승격하지 않는다.

이 변경은 DesignSpec의 cutoff 정의, EFPC 분리, Train/Validation 독립성 원칙과
상충하지 않는다. 실행 탐색의 폭과 seed 배정 방식을 확장한 것이며, 최종 cutoff의
승격 조건은 기존 설계와 가설검정 방법을 그대로 따른다.

## 13. 2026-10-03 시그니처 업데이트 합의와 후속 작업 (당시 기록; 2026-10-04 후속 결정 전)

> 이 절은 2026-10-03 당시의 합의·미결 목록을 보존한다. 아래의 “미정” 항목과 제안
> 순서는 현재 규칙이 아니다. 현재 결정은 문서 상단의 적용 상태와 DesignSpec 5.6.9를
> 참조한다.

### 합의된 탐색 정책

- 업데이트 대상은 세 feature block이다: joint-set별 `P32`, `(mean_dip, mean_dip_dir)`
  방향 쌍, `size_r_min`·`size_r_max` 크기 쌍.
- 세 block을 모두 탐색 대상으로 포함하고 round-robin으로 순환한다. 한 probe에서는 한
  block만 변경한다. 시작 block, block 내부의 probe 방향과 간격은 추가 결정이 필요하다.
- probe 반응으로 `ΔQ′/ΔX`를 추정한다. 이 기울기는 Q′의 무조건적인 증가가 아니라
  미관측 Q′ 구간을 향한 coverage 확장에 사용한다.
- 방향 update 좌표는 관측공 축과 절리면 사이의 사잇각이다. 목표 사잇각으로부터 가능한
  dip/dip direction 후보를 복원하며, 정의되지 않거나 퇴화하거나 유효 범위를 벗어나는
  해는 제외한다. 후보 중 선택 규칙은 미정이다.
- candidate 효과는 탐색 seed와 분리된 독립 seed 3개에서 확인한다. 각 seed에서 parent와
  candidate를 동일 seed로 짝지어 실행한다. 효과 판정 기준은 미정이다.

### 구현 현황과 작업 항목

현재 `validation/run_campaign.py`의 Euler probe 및 paired-response 경로는 한 번에 하나의
scalar feature만 변경하는 계약을 갖는다. `src/core/signature_candidates.py`의 bounded
feature update는 여러 numeric feature를 처리할 수 있지만, 세 feature block을 round-robin
선택·측정·갱신하는 campaign orchestration은 아직 연결되지 않았다.

관측공 방향도 현재 고정 가정이다. `src/core/tunnel.py`는 sampling line을 `+x`로 만들고,
`src/core/comparison.py`는 plane-angle과 orientation-bias 계산에 `+x` 축을 사용한다.
Case configuration에는 borehole 위치 offset은 있지만 방향 vector가 없다. 그러므로
방향 feature를 campaign에 접목하기 전에 실제 sampling geometry와 response 측정이 동일한
설정 방향을 사용하도록 일반화해야 한다.

후속 구현 작업:

1. Case schema에 관측공 방향 입력을 추가하고 유효한 단위 방향 vector로 검증한다.
2. Tunnel sampling, borehole-plane angle 및 방향 민감도 측정이 해당 입력을 공통으로
   사용하도록 전달 경로를 연결한다. 여러 관측공이 있을 때 방향 적용 범위도 명시한다.
3. 사잇각에서 방향 후보를 복원하는 변환을 정의한다. dip/dip direction 좌표 규약,
   법선의 부호 대칭, 경계·퇴화점, 유효하지 않은 후보 제외를 테스트한다.
4. orientation pair와 min/max-radius pair를 campaign에서 각각 하나의 feature block으로
   표현하도록 현재 scalar 단일 변경 검사와 ledger schema를 확장한다.
5. `P32` → orientation → size block을 round-robin으로 probe하는 상태·재개 로직을
   구현하고, 각 probe의 `ΔX`, `ΔQ′`, 목표 gap, parent signature를 기록한다.
6. 고정 `P32`에서 size distribution 변경으로 기대 절리 개수가 변하는 효과를 ledger와
   분석에서 추적한다.
7. 탐색에 사용하지 않은 새 seed 3개에서 parent/candidate paired validation을 수행하고,
   결과를 보존하는 테스트와 campaign 검증을 추가한다.

### 미결 설계 결정

- Round-robin의 시작 block, block별 probe 방향과 perturbation 크기
- 학습률, normalized update 식, step 상한 및 민감도가 불안정하거나 0일 때의 처리
- `size_r_min`·`size_r_max`를 묶는 parameterization. 공통 배율 `λ`와 `log(λ)` 좌표는
  검토안이며 합의된 규칙이 아니다.
- 사잇각이 허용하는 복수 방향 후보 중 선택하는 기준 및 복수 관측공의 처리
- 3개 독립 seed 결과의 효과 합격 기준

본 절은 설계 합의를 기록하며 자동 simulation 승인이나 실행 승인을 부여하지 않는다.
위 미결 항목을 확정하고 후보 계획을 검토하기 전까지 다변수 block update를 대규모
campaign에 적용하지 않는다.

## 17. 2026-10-04 profile coverage 기반 후속 실행 계약

이 절은 이전 iteration 계획과 실험 결과를 삭제하거나 재해석하지 않고, 다음 단계의
signature update 실행에서 적용할 현재 규칙을 DesignSpec 5.6.9 및 5.8에 연결한다.

1. **입력·관측 단위:** 새 실행은 물리 geometry로 정의된 시추공 Q′BH profile과 tunnel
   Q′Face station profile을 보존한다. 실제 tunnel/borehole overlap 구간만 대응 비교에
   사용하고, 나머지 시추공 profile도 독립 자료로 남긴다. 레거시 CSV row 단위 자료는
   그 당시 입력 단위와 provenance를 유지하며 새 profile처럼 재해석하지 않는다.
2. **Coverage audit:** cutoff grid의 실제 profile 값 점유만 bin coverage로 센다. 양의
   길이 support를 인정하며, 범위/envelope만 통과한 bin은 채우지 않는다. Profile 통계와
   관측 bin 집합은 각각 보존한다.
3. **Candidate score:** paired parent/candidate에서 각 seed의 parent 미관측 bin을 gap으로
   고정한다. 그 gap에 대해 실제 profile 길이 가중 proximity `P_b`, 평균 proximity 변화
   `D`, 새 점유 비율 `C`, `ΔS=0.5D+0.5C`를 산출한다. bin grid가 다르면 score 비교 전에
   같은 grid임을 검증하고, 다르면 직접 delta 비교를 하지 않는다.
4. **Probe/update:** round-robin은 밀도 → 크기 → 방향이다. 양수 probe는 로그 좌표에서
   ×/÷1.1을 시작값으로 하고, 중앙차분으로 score 민감도를 구한다. 양수 update는 로그
   좌표 기준 약 5%, orientation `β` probe는 ±5°, orientation update는 최대 5°다.
   실제 입력·저장값은 물리 단위다. update 후보는 물리 bounds와 `size_r_max >
   size_r_min > 0`을 만족해야 한다.
5. **Paired validation:** 탐색 seed에서 효과가 확인된 update 방향은 탐색에 사용하지 않은
   사전 고정 seed 3개로 평가한다. 각 seed 안에서 parent/candidate를 같은 seed로 짝지어
   실행하고, seed별 parent gap에서 `ΔS>0` 및 전체 observed-bin 수 비감소를 모두 만족하면
   성공이다. 3개 중 2개 이상 성공할 때 update 방향을 채택한다. 별도 1% 최소 개선치는 없다.
6. **경계·종료:** 한 파라미터가 해당 방향의 유효 경계에 닿으면 그 방향 update에서
   고정하고 다른 조정 가능 파라미터를 처리한다. 주 파라미터가 모두 경계에 도달해
   진행할 방향이 없으면 현재 campaign을 중단한다. 자동으로 `fisher_kappa`나 다른
   조건을 바꾸지 않는다. 새 조건의 campaign은 결과를 검토한 사용자가 별도로 결정한다.
7. **cutoff 분리:** 이 signature score는 coverage 탐색/update 선택용이다. 이를
   `Q'_lowerbound` 또는 `Q'_upperbound`로 해석하지 않는다. Cutoff 방법론 문서에서
   새 longitudinal profile을 cutoff 상태 추정에 넣는 관측 단위와 가중 방식을 정하기
   전까지 해당 변환은 미결이다.

이번 계약의 수치 및 방법은 구현 전 설계 선택이다. 관측된 실행 결과나 학술적 타당성
주장으로 기록하지 않으며, 이후 성능·민감도 평가는 별도 evidence 기록으로 남긴다.

## 18. 2026-10-05 새 구현 전 Core 재사용 검토

새 Euler campaign 또는 coverage 기능을 구현할 때는 `src/core`에 있는 선행 기능을 먼저
대조한다. 구체적인 중복 검토 결과와 기능별 재사용/분리 근거는
[20261005.md](20261005.md)에 기록했다.

- 구현 전에 기존 API와 계획된 API의 의미, 자료형, 관측 단위, 경계 조건, ID 및 seed
  identity를 비교하고 직접 재사용·adapter·공통 primitive·분리 구현 중 하나를 선택한다.
- Q′BH 값 bin coverage와 longitudinal profile support coverage를 같은 것으로 취급하지 않는다.
- 기존 `signature_candidates`/`coverage_rounds`의 Euler-style updater가 있으므로 새 updater를
  만들기 전에 알고리즘·정규화·검증 차이를 확인한다. 미결 정책은 임의로 채우지 않는다.
- 재사용이 안전하지 않으면 분리 구현할 수 있지만, 중복 책임과 그 이유를 계획 및 작업
  로그에 남긴다. 이 검토는 구현 승인이나 campaign 실행 승인이 아니다.
