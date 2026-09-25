# QSimEx Coverage-Adaptive 실행 및 자동화 계획

- 작성일: 2026-09-25
- 적용 단계: Phase 3 Q' cutoff 탐색 및 Phase 4 통계적 재현성 검증
- 상태: 구현 계획
- 관련 정의서:
  - `HypothesisTestingMethod_20260925.md`
  - `DesignSpec_20260922.md`
  - `ImplementationPlan_20260925.md`

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

### Round 0: Baseline

- 기존 결과를 새 schema로 읽는다.
- `domain_id`, generation signature hash, seed, case를 확인한다.
- 고정 log bin 기준 coverage audit을 수행한다.
- `UNOBSERVED`와 과밀 구간을 기록한다.
- 기존 데이터는 최종 calibration/validation에 자동 편입하지 않는다.

### Round 1: Gap pilot 및 1차 보강

- 가장 중요한 내부 gap 또는 reachability gap을 선택한다.
- 인접 configuration과 generation feature 차이를 비교한다.
- P32, 평균 spacing, 방향성, Fisher 집중도, 크기분포, 절리군 수, 교차각 등을
  조정한 후보 signature를 생성한다.
- configuration 선택용 독립 seed로 소규모 pilot을 실행한다.
- Q' 이동 방향과 도달 여부를 확인한다.

### Round 2: 독립 domain 확장

- Round 1에서 실제 Q' 이동이 확인된 signature만 확장한다.
- 여러 독립 seed/domain을 추가한다.
- 기존 domain과 중복되지 않도록 signature hash와 `domain_id`를 검사한다.
- coverage audit과 staged bootstrap을 다시 수행한다.

### Round 3: 재현성 확인

- 남은 핵심 gap과 profile 방향 충돌을 확인한다.
- 독립 domain에서 Q' 범위와 profile 경향이 재현되는지 검증한다.
- lower/upper 후보가 반복 round에서 안정되는지 확인한다.
- 최대 3회 이후에는 무한히 simulation을 반복하지 않는다.

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
