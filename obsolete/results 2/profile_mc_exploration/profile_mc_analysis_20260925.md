# Profile MC 분석 결과

- 분석일: 2026-09-25
- 입력: `results/profile_mc_exploration/all_cases_borehole_rows.csv`
- 분석 대상: `scenario_03`, `scenario_05`, `scenario_06`, `scenario_07`, `scenario_10`
- 목적: Q' coverage, 참조 profile 경향, lower/upper cutoff 식별 가능성 점검
- EFPC: 미연결. 본 보고서는 시뮬레이션 참조 profile과 cutoff 후보만 다룬다.

> 주의: 이 보고서의 입력은 `config/profile_mc_exploration.yml`의 5개 기존 case만
> 포함한다. 저Q·고Q 보강 case는 별도 coverage pilot 출력으로 실행되었지만, pilot
> 자료를 본 MC 결과에 자동 병합하거나 calibration 자료로 승격하는 단계가 당시
> 실행되지 않아 이 보고서의 combined CSV에는 포함되지 않았다. 이는 보강 case를
> 폐기한 것이 아니라, reachability pilot과 cutoff 검정용 독립 domain 자료를 분리한
> 것이다.

## 1. 실행 완전성

- case 수: 5
- case당 seed/domain 수: 100
- 총 독립 domain 수: 500
- borehole row 수: 1,500
- case당 face 위치: 3
- 결과 row의 `domain_id`, `generation_signature_hash`, `generation_features_json`: 저장 확인
- Q' 범위: `5.351066~47.867091`

## 2. Case별 Q' 범위

| Case                            | Domains | Rows | Qp_bh 최소 | Qp_bh 최대 |
| ------------------------------- | ------: | ---: | ---------: | ---------: |
| scenario_03_sparse_large        |     100 |  300 |     15.966 |     24.131 |
| scenario_05_orthogonal_two_sets |     100 |  300 |     20.588 |     38.324 |
| scenario_06_layered_density     |     100 |  300 |      5.351 |      9.318 |
| scenario_07_isotropic           |     100 |  300 |     27.466 |     47.867 |
| scenario_10_fieldlike           |     100 |  300 |     11.515 |     20.044 |

## 3. Coverage 결과

### 3.1 별도 coverage pilot 결과

보강 case의 실제 도달 결과는 다음과 같다.

| Pilot                                | Domains | Rows |      Qp_bh 범위 | 현재 역할                      |
| ------------------------------------ | ------: | ---: | --------------: | ------------------------------ |
| `scenario_11_coverage_low_q`         |       1 |   15 |     `3.20~4.35` | 저Q reachability pilot         |
| `scenario_13_coverage_low_q_refined` |       1 |    3 |     `1.86~2.06` | 저Q refined reachability pilot |
| `scenario_12_coverage_high_q`        |       1 |    3 | `266.67~266.67` | 고Q reachability pilot         |

이 pilot들은 목표 구간에 실제로 도달할 수 있음을 확인했다. 그러나 각 pilot이
1개 독립 domain뿐이므로 domain cluster bootstrap과 cutoff 재현성 검정의 근거로
바로 사용할 수 없다. 따라서 올바른 다음 단계는 이 case들을 제외하는 것이 아니라,
동일 signature를 독립 seed 여러 개로 확장한 뒤 coverage round 결과로 승격하는 것이다.

고정 log bin `[0.1, 400]` 기준:

| Bin |         Q' 범위 |  Rows | Domains | 상태         |
| --: | --------------: | ----: | ------: | ------------ |
|   0 |       0.1~0.270 |     0 |       0 | `UNOBSERVED` |
|   1 |     0.270~0.726 |     0 |       0 | `UNOBSERVED` |
|   2 |     0.726~1.957 |     0 |       0 | `UNOBSERVED` |
|   3 |     1.957~5.278 |     0 |       0 | `UNOBSERVED` |
|   4 |    5.278~14.232 |   435 |     186 | observed     |
|   5 |   14.232~38.350 | 1,011 |     394 | observed     |
|   6 |  38.350~103.300 |    54 |      45 | observed     |
|   7 | 103.300~278.500 |     0 |       0 | `UNOBSERVED` |
|   8 |     278.500~400 |     0 |       0 | `UNOBSERVED` |

해석:

- 중간 Q' 영역은 충분한 domain coverage를 확보했다.
- 저Q 영역 `0.1~5.278`은 여전히 완전히 비어 있다.
- 고Q 영역 `103.3~400`도 여전히 완전히 비어 있다.
- 이번 5-case MC는 기존 중간 영역의 domain 재현성을 보강했지만, 저Q·고Q reachability를 보강하지는 못했다.

## 4. Profile 경향

관측 bin별 중앙값은 다음과 같다.

| Q' bin         | Qp_face 중앙값 | miss ratio 중앙값 | face fracture density 중앙값 | orientation gap 중앙값 |
| -------------- | -------------: | ----------------: | ---------------------------: | ---------------------: |
| 5.278~14.232   |          6.650 |            0.9983 |                        7.665 |                 0.0515 |
| 14.232~38.350  |         26.075 |            0.9810 |                        1.732 |                 0.0987 |
| 38.350~103.300 |         33.873 |            0.9832 |                        1.528 |                 0.1455 |

Pooled Pearson correlation:

- `Qp_bh_mean` vs `Qp_face_mean`: `r=0.928`
- `Qp_bh_mean` vs `miss_ratio`: `r=0.106`
- `Qp_bh_mean` vs `face_fracture_density`: `r=-0.481`
- `Qp_bh_mean` vs `orientation_bias_gap_to_face`: `r=0.227`

Case 내부 Pearson correlation은 `Qp_face_mean` 기준으로 다음과 같다.

- scenario_03: `r=0.455`
- scenario_05: `r=0.100`
- scenario_06: `r=0.003`
- scenario_07: `r=0.003`
- scenario_10: `r=-0.034`

## 5. 가설 판정

현재 결과는 주 가설을 **부분적으로 지지하는 탐색 신호**를 보인다.

지지하는 부분:

- pooled 자료에서 Q'가 증가할수록 `Qp_face_mean`이 증가하는 강한 경향이 보인다.
- 낮은 관측 bin에서 높은 관측 bin으로 갈수록 face fracture density가 감소한다.
- 500개 독립 domain과 5개 configuration으로 중간 Q' 영역의 반복 자료가 확보되었다.

아직 지지하지 못하는 부분:

- 저Q와 고Q 구간이 모두 `UNOBSERVED`이므로 전체 목표 범위의 profile 변화는 확인할 수 없다.
- `Qp_face_mean` pooled 경향은 case 사이의 Q' regime 차이에 영향을 받았을 가능성이 크다.
- case 내부 `Qp_bh_mean`-`Qp_face_mean` 상관은 약하거나 불안정하다.
- profile 공통 PR/POST 영역을 구성할 수 없다.
- miss ratio와 orientation gap은 명확한 공통 방향성을 보이지 않는다.

## 6. Cutoff와 bootstrap

profile search 결과:

- 상태: `not_identifiable`
- `lower_cutoff`: `null`
- `upper_cutoff`: `null`
- 사유: 핵심 profile에 `UNOBSERVED` bin이 남아 있고 공통 PR/POST 영역이 없음

Domain cluster bootstrap:

- `B=200`: 전 반복 `not_identifiable`
- `B=500`: 전 반복 `not_identifiable`
- lower/upper bootstrap 분포: 산출되지 않음

이는 bootstrap 엔진의 실패가 아니라, coverage 부족을 정확히 차단한 결과다. 현재 자료로 숫자 cutoff를 임의로 제시하면 안 된다.

## 7. 다음 Round 권고

1. 현재 5개 중간-Q configuration 결과는 calibration 후보 자료와 분리 보존한다.
2. 저Q 보강:
   - `scenario_13_coverage_low_q_refined` 계열을 독립 seed 여러 개로 확장
   - 목표: `Qp_bh_mean < 5.278` 영역의 domain coverage 확보
3. 고Q 보강:
   - `scenario_12_coverage_high_q` 계열을 독립 seed 여러 개로 확장
   - 목표: `Qp_bh_mean > 103.3` 영역의 reachability 및 domain coverage 확인
4. 저Q·고Q pilot 결과가 실제 목표 bin에 들어오는지 먼저 확인한다.
5. 각 목표 영역에서 최소 5개 이상의 독립 domain을 확보한 뒤 `B=200` bootstrap을 재실행한다.
6. coverage가 확보된 뒤 `B=500`, 필요 시 `B=1000`으로 늘린다.
7. low/middle/high configuration을 모두 포함한 뒤 lower/upper cutoff 후보를 재산출한다.

## 8. 결론

이번 profile MC는 실행과 metadata 저장, 중간-Q coverage 재현성 검증에는 성공했다. 그러나 목표한 전체 Q' 범위를 덮지 못했기 때문에 lower/upper cutoff는 아직 식별되지 않았다. 현재 가장 중요한 후속 작업은 signature를 저Q·고Q 방향으로 업데이트하여 두 끝단의 독립 domain coverage를 확보하는 것이다.

## 9. Coverage signature 변경 이력

coverage 보강 과정의 원본 기록은
`results/coverage_rounds/ledger.jsonl`에 누적한다. 현재 확인된 라운드는 다음과 같다.

| Round | Signature/configuration              | 실행 seed | 관측 Q' 범위   | 독립성 metadata                         | 해석                                      |
| ----: | ------------------------------------ | --------- | -------------- | --------------------------------------- | ----------------------------------------- |
|     0 | 기존 5개 중간-Q case                 | 40~139    | `5.351~47.867` | `domain_id`·signature 있음, 500 domains | 중간 영역 baseline 확보                   |
|     1 | `scenario_11_coverage_low_q`         | 200~204   | `3.198~4.346`  | 없음                                    | 저Q 도달성 부분 확인, provenance 불완전   |
|     1 | `scenario_13_coverage_low_q_refined` | 206       | `1.858~2.064`  | 없음                                    | 저Q refined 도달성 확인, domain 확장 필요 |
|     1 | `scenario_12_coverage_high_q`        | 205       | `266.667`      | 없음                                    | 고Q 도달성 확인, domain 확장 필요         |

중요한 구분:

- 저Q·고Q case가 분석에서 폐기된 것이 아니다.
- 별도 pilot에서 목표 범위 도달성은 확인되었다.
- 다만 해당 pilot 결과는 현재 metadata 패치 이전에 생성되어 `seed`만 있고
  `domain_id`와 `generation_signature_hash`가 없다.
- 따라서 pilot 결과를 독립 domain bootstrap 또는 cutoff calibration 자료로 직접
  편입하지 않고, 다음 실행의 signature 확장 근거로 사용한다.

다음 coverage round에서는 현재 runner로 동일 signature를 재실행하여 모든 row에
`domain_id`, `generation_signature_hash`, `generation_features_json`을 저장한다.
그 뒤 저Q·고Q 각각 독립 seed를 확장하고, baseline과 pilot을 provenance 기준으로
결합한 후 coverage audit과 cutoff bootstrap을 다시 수행한다.

## 10. Round 1 결과 기반 signature 업데이트 방향

현재 coverage 부족은 한 가지 원인만으로 설명되지 않는다.

### 10.1 공백과 중복의 분리

- 전체 1,500행 중 `14.232~38.350` 구간에 1,011행이 있어 약 67.4%가 집중됨
- `5.278~14.232` 구간에는 435행이 있어 약 29.0%가 분포함
- `38.350~103.300` 구간에는 54행만 있어 약 3.6%임
- `0.1~5.278`과 `103.3~400`은 row와 domain이 모두 0임

따라서 중앙부 coverage가 낮은 것은 일부 configuration의 Q' 범위가 서로 겹치고
중앙 구간에 domain이 집중된 영향이 맞다. 그러나 저Q·고Q 끝단은 중복 때문에
희석된 것이 아니라, 현재 baseline에서는 관측 자체가 없는 `UNOBSERVED` 공백이다.

### 10.2 Round 2 실행 목표

Round 2에서는 중앙 Q' 영역의 단순 seed 증량을 중단하고 다음을 우선한다.

1. `scenario_13_coverage_low_q_refined` signature를 현재 metadata runner로 재실행

- 새로운 독립 seed를 사용
- 목표: `Qp_bh_mean < 5.278` 구간의 domain 확보

2. `scenario_12_coverage_high_q` signature를 현재 metadata runner로 재실행

- 새로운 독립 seed를 사용
- 목표: `Qp_bh_mean > 103.3` 구간의 domain 확보

3. 기존 `scenario_11_coverage_low_q`는 refined signature와 결과가 중복되는지
   확인한 뒤 필요한 경우에만 추가한다.
4. 모든 새 결과에는 `domain_id`, signature hash, generation feature를 필수로 저장한다.

### 10.3 중복 감소 규칙

다음 조건을 만족하지 않는 새 configuration/domain은 대규모 확장 대상에서 제외한다.

- 기존 관측 bin과 동일한 중앙 Q' 범위만 반복하고 새 bin을 만들지 못함
- 새로운 독립 signature가 아니라 기존 signature와 동일함
- 같은 domain 또는 seed를 재사용함
- Q' 이동 방향이 pilot에서 확인된 목표 방향과 다름

새 결과는 단순 row 수가 아니라 다음 기여도로 평가한다.

- 새로 관측된 Q' bin 수
- 해당 bin의 독립 domain 수
- 해당 bin의 독립 signature 수
- 기존 관측 구간과의 분포 중첩도
- profile 유효값과 상태 재현성

중앙 구간에 새 domain을 추가하더라도 저Q·고Q 공백을 줄이지 못하면 coverage 개선
라운드의 우선순위 성과로 인정하지 않는다.

### 10.4 Round 2 종료 조건

- 저Q·고Q 목표 bin에 각각 최소 5개 독립 domain 확보
- 모든 새 row에 provenance metadata 존재
- `UNOBSERVED` 끝단이 실제 관측 또는 도달 불가로 구분됨
- 새 round에서 중앙부 중복 비율과 끝단 coverage 변화가 ledger에 기록됨
- 조건을 만족하면 `B=200` bootstrap, 이후 안정 시 `B=500`으로 진행

## 11. Seed 변동성과 signature 확장 전략

### 11.1 Seed가 바꾸는 것

현재 DFN 생성기에서 seed는 다음 난수 추출을 모두 바꾼다.

- Poisson 절리 개수
- Power-law 절리 반경
- Fisher 방향 샘플
- 절리 중심 위치
- `Jr`, `Ja` 재료값

따라서 seed는 단순히 절리 위치만 이동시키는 것은 아니다. 다만 동일한 generation
signature 안에서 같은 분포를 재표본화하므로, 절리 수가 많고 결과가 평균화되는
configuration에서는 seed를 100개로 늘려도 Q' 범위가 크게 넓어지지 않을 수 있다.

### 11.2 이번 MC에서 관측된 seed 효과

face 위치별 row 변동을 제거하기 위해 각 seed의 3개 face row를 먼저 평균한 뒤 seed 간
표준편차를 계산했다.

| Case                            | Seed 평균 Qp_bh 표준편차 | Seed 평균 Qp_bh 범위 |
| ------------------------------- | -----------------------: | -------------------: |
| scenario_03_sparse_large        |                    0.266 |        16.433~19.155 |
| scenario_05_orthogonal_two_sets |                    1.742 |        22.626~32.319 |
| scenario_06_layered_density     |                    0.318 |          5.959~7.463 |
| scenario_07_isotropic           |                    1.941 |        30.391~41.035 |
| scenario_10_fieldlike           |                    0.751 |        12.425~17.323 |

반면 generation signature가 다른 case의 평균 Qp_bh는 약 `6.595~35.118`로
차이가 훨씬 컸다. 전체 Qp_bh 분산을 단순 분해한 결과에서도 case 간 분산은 case
내 seed 분산 평균보다 약 25.7배 컸다.

이 결과는 현재 목표가 같은 signature 안의 평균 추정 정밀도보다 Q' coverage 확장인
경우, 100개 seed를 모든 signature에 동일하게 투입하는 방식이 비효율적일 수 있음을
보여준다.

### 11.3 수정된 실행 전략

Round 2부터는 다음 2단계로 운영한다.

1. **Signature screening**
   - 후보 signature당 독립 seed 5개부터 실행
   - Q' 이동 방향, 목표 bin 도달 여부, profile 변화량 확인
   - 기존 중앙 구간과 중복만 만들면 후보를 확장하지 않음
2. **Signature confirmation**
   - 목표 bin을 실제로 만들고 profile 방향이 유지되는 signature만 선택
   - 선택된 signature에 독립 seed를 추가하여 최소 5개 domain, 필요 시 10~20개로 확장
   - 100개 seed는 cutoff 안정성 검증에 실제로 필요한 signature에만 사용

저Q·고Q 끝단은 seed를 100개 먼저 돌리는 것이 아니라, refined signature 후보를
소수 seed로 screening하여 실제 이동성을 확인하는 것이 우선이다. 목표 bin에 도달하지
못한 signature는 seed를 무작정 늘리지 않고 feature를 다시 조정한다.

### 11.4 해석상의 주의

seed를 줄이는 것은 독립성 검정을 포기하는 것이 아니다. seed는 선택된 signature의
domain 재현성을 확인하는 표본이고, signature는 적용성 범위와 Q' coverage를 넓히는
설계 요인이다. 최종 cutoff 검정에는 여러 signature와 각 signature의 독립 domain이
함께 필요하다.

## 12. Scenario MC 접근법 재검토

### 12.1 Profile MC로 바꾼 이유와 한계

`profile_mc_exploration`은 scenario별 분석을 폐기한 것이 아니다. 기존 계획의
`case × seed × face position` 실행을 하나의 재현 가능한 batch runner로 묶고, 여러
scenario의 borehole profile을 공통 schema로 수집하기 위해 도입했다. 따라서 실행
단위는 여전히 scenario/case이며, MC는 실행·수집·반복성 검사를 담당한다.

다만 전체 결과를 pooled profile로 먼저 요약하면 scenario 간 Q' regime 차이가 강하게
반영되어 case 내부 경향보다 커질 수 있다. 이번 결과의 pooled `Qp_bh_mean`-
`Qp_face_mean` 경향과 불안정한 case 내부 상관이 그 위험을 보여준다. 따라서 다음
분석부터는 pooled 결과를 cutoff 근거로 사용하지 않고 다음 순서를 따른다.

1. scenario/signature별 coverage와 profile을 먼저 계산
2. scenario 내부 seed/domain 재현성을 확인
3. scenario 간 공통 PR/POST와 Q' coverage를 비교
4. 마지막에만 전체 결과를 보조적으로 요약

### 12.2 Scenario 수와 seed 수의 재설계

현재 `5 scenarios × 100 seeds = 500 domain runs`는 같은 signature의 반복성에는
충분하지만, Q' coverage를 넓히는 데는 비효율적일 수 있다. 반대로 `50 scenarios ×
10 seeds = 500 domain runs`는 총 실행 수가 비슷하므로 계산량도 대체로 비슷할 수
있지만, scenario별 DFN 절리 수와 GPU 처리량이 다르므로 실제 시간은 동일하다고
보장할 수 없다.

scenario를 늘리는 목적은 기존 scenario의 seed를 대체하는 것이 아니라, 빈 coverage
구간을 메울 수 있는 **새 generation signature를 추가**하는 것이다. 각 iteration에서
현재 scenario/signature 전체를 먼저 훑고, 그 결과로 확인된 gap에 맞춰 다음 iteration의
signature 집합을 확장한다.

```text
Iteration k: 현재 signature 전체 × seed 1개 sweep
   -> coverage map과 gap 산출
   -> gap을 메울 새 signature 설계·추가
   -> Iteration k+1: 기존 signature + 새 signature 전체 재-sweep
```

seed 확장은 새 signature가 목표 bin을 실제로 만들고 재현되는지 확인하는 후속 단계다.
총 run budget은 고정하지 않고, signature 집합이 coverage를 얼마나 넓혔는지에 따라
다음 iteration의 규모를 정한다.

### 12.3 다음 실행의 설계 원칙

- scenario/signature가 Q' coverage를 이동시키는 주된 설계 요인이다.
- seed는 선택된 signature의 domain 재현성과 변동성 추정에 사용한다.
- 중앙 Q' 구간만 반복하는 scenario는 새 bin 또는 새로운 signature 다양성을 만들지
   못하면 다음 iteration의 signature 집합에 추가하지 않는다.
- 저Q·고Q gap마다 그 구간을 메울 generation feature 조합을 새 signature로 만든다.
- 새 signature는 먼저 seed 1개로 전체 sweep에 포함한다.
- 새 signature가 목표 bin을 만들면 다음 iteration에서 기존 signature와 함께 다시
   실행하여 coverage map의 변화를 비교한다.
- 반복 확인이 필요한 signature만 seed 5~10개로 확장한다.
- 모든 결과는 scenario/signature별로 분석한 뒤 pooled 결과를 보조적으로 산출한다.
- 각 signature의 실행 시간과 생성 절리 수를 기록하여 단순 run 수가 아닌 실제 계산
  비용으로 다음 budget을 조정한다.

결론적으로 `50 scenarios × 10 seeds`를 한 번에 수행하는 방식은 사용하지 않는다.
현재 signature 전체를 1 seed로 sweep한 뒤, 빈 구간을 메울 새 signature를 추가하고
다음 iteration에서 전체 signature 집합을 다시 실행한다. seed는 그 후 선택된
signature의 재현성 확인에만 사용한다.

## 13. 순차적 Scenario-First 실행 전략

앞선 screening 표현을 실제 실행 순서에 맞게 다음과 같이 구체화한다. 처음부터
각 scenario를 100개 seed로 완주하지 않으며, **빈 구간을 메울 새 signature를
iteration 사이에 추가**한다.

### Iteration 0: 전체 scenario/signature 1-seed sweep

1. 후보 generation signature 전체를 준비한다.
2. 각 scenario/signature를 독립 seed 1개로 실행한다.
3. 모든 결과를 하나의 coverage map으로 합친다.
4. scenario별 Q' 범위, 새로 관측한 bin, 기존 구간과의 중첩도, 생성 절리 수와
   실행 시간을 비교한다.

이 단계의 목적은 seed 반복성 검정이 아니라 **현재 signature 공간의 coverage 기여도와
계산 비용을 빠르게 파악하는 것**이다.

### Iteration k+1: gap 보강 signature 추가 후 전체 재-sweep

1. Iteration k의 coverage map에서 `UNOBSERVED` 또는 domain 부족 bin을 찾는다.
2. 각 gap의 인접 signature와 Q' 이동 pilot을 근거로 새 generation signature를 설계한다.
3. 새 signature를 기존 signature 목록에 추가한다.
4. 기존 signature와 새 signature 전체를 seed 1개 이상으로 다시 실행한다.
5. 이전 iteration과 비교하여 새로 관측된 bin, 중첩 감소, domain/signature 수 변화를
   ledger에 기록한다.
6. 여전히 비어 있는 구간이 있으면 다음 iteration에서 signature를 다시 추가한다.

새 signature는 기존 결과를 대체하지 않는다. 매 iteration의 signature 집합과 변경
내역을 보존하여 coverage가 어떤 signature 추가로 개선되었는지 추적한다.

### 후속 단계: coverage 기여 signature의 seed 확장

Round A에서 실제 목표 bin에 도달하거나 그 방향으로 이동한 scenario만 독립 seed를
추가한다.

- 저Q gap에 기여한 signature: 저Q seed 확장
- 고Q gap에 기여한 signature: 고Q seed 확장
- 중앙 구간만 반복하는 signature: 새 bin/signature 기여가 없으면 중단

추가 seed 결과가 기존 scenario의 Q' 분포만 반복하고 coverage를 넓히지 않으면 더
이상 seed를 늘리지 않는다. 반대로 동일 signature에서 충분한 Q' 변동이 관측되면
해당 signature를 재현성 검증 대상으로 승격한다.

### Round C: cutoff 분석용 domain 확장

Round B에서 선택된 low/middle/high signature 각각에 대해 필요한 독립 domain 수를
확보한다. 이때 처음부터 모든 scenario에 같은 seed 수를 배정하지 않고, 다음 조건을
만족하는 signature에만 seed를 추가한다.

- 목표 Q' bin에 실제 row가 생성됨
- 새 독립 domain이 추가됨
- generation signature가 기존 signature와 구분됨
- profile 방향이 이전 결과와 충돌하지 않음
- 실행 비용 대비 새 coverage 기여가 있음

그 후 scenario/signature별 profile 분석, 공통 PR/POST, domain cluster bootstrap,
lower/upper cutoff 산출을 수행한다.

### 계산량 원칙

기존 방식:

```text
5 scenarios × 100 seeds = 500 runs
```

새 방식의 예시는 다음과 같다.

```text
50 scenarios × 1 seed       = 50 runs  # 전체 signature sweep
10 유효 scenarios × 10 seed = 100 runs # coverage 방향 확장
5 핵심 scenarios × 20 seed  = 100 runs # cutoff 재현성
```

총 run 수를 고정하지 않고, 각 run의 실제 절리 수와 GPU 실행 시간을 함께 기록한다.
따라서 `50 scenarios × 10 seeds`가 항상 기존 500 runs와 같은 시간이라고 가정하지
않으며, Round A 결과를 본 뒤 다음 run budget을 결정한다.

이 순서에서는 scenario가 coverage를 넓히는 설계 요인이고 seed는 선택된 scenario의
재현성을 확인하는 요인이다. coverage map을 만들기 전에 seed를 대량 투입하지 않는
것이 핵심이다.
