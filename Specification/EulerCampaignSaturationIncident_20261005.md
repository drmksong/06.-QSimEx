# Euler 캠페인 포화 오판 조사 기록

## 결론

`gpu-pilot-20261005-v2-2156` 실행은 시뮬레이션 자체는 끝났지만, 사용자가 요구한 밀도·크기·각도 설정 범위 탐색을 완료하지 않았다. 그럼에도 상태가 `all_lineages_saturated`로 끝났다. 현재 상태명은 알고리즘이 각 feature block에서 더 시도할 후보를 만들지 못했다는 뜻일 뿐, 파라미터 범위가 충분히 탐색됐다는 증거가 아니다. 이 결과를 전체 범위 탐색의 완료로 취급하면 안 된다.

## 조사 대상과 보존 자료

- 캠페인: `highq-euler-multistart-gap-v2`, plan revision `1`
- run generation: `gpu-pilot-20261005-v2-2156`
- 설정: [`highq_euler_multistart_campaign_gap_v2.yaml`](../cases/euler/highq_euler_multistart_campaign_gap_v2.yaml)
- 요약: [`run_summary.json`](../cases/euler/results/euler_campaigns/highq-euler-multistart-gap-v2/runs/gpu-pilot-20261005-v2-2156/run_summary.json)
- 원본 기록 DB: [`campaign.sqlite3`](../cases/euler/results/euler_campaigns/highq-euler-multistart-gap-v2/campaign.sqlite3)

DB와 run 산출물은 변경하거나 삭제하지 않았다. 이 run은 이후 수정의 비교 기준으로 보존한다. 테스트 및 시뮬레이션은 실행하지 않았다.

## 저장 기록에서 확인한 사실

- 저장된 시뮬레이션은 **95회**이며, 100번째 기록은 없다. 마지막 기록 #95는 사용자가 제공한 로그와 일치한다.
- 95회에는 **70개의 고유 signature ID**가 있다. 모든 signature ID에 대응하는 전체 `CaseSpec`을 라운드 payload에서 찾았고, DB 시뮬레이션 signature와의 미대응은 0건이다.
- seed별 기록: `1001` 62회, `1002` 11회, `1003` 11회, `1004` 11회. domain ID는 95개 모두 고유하다.
- coverage는 10개 중 3개만 채웠다. 0-based `[3, 4, 5]`, 즉 1-based **bin 4·5·6**이며, 빈 bin은 `[1, 2, 3, 7, 8, 9, 10]`이다.
- 총 9개 round: 세 lineage 각각에서 `density → size → orientation`을 한 번씩 시도했다. 저장 순서는 한 lineage의 3개 block을 처리한 뒤 다음 lineage로 넘어가는 방식으로, lineage 사이를 번갈아 실행하는 순서는 아니었다.
- 8개 후보는 모두 검증 seed `1002–1004`에서 새 bin을 `0/3`회 채워 거부됐다. 세 번째 lineage의 density 제안은 `bound_limited`여서 후보가 없었다. 어떤 후보도 parent로 채택되지 않았다.

## 전수 signature의 파라미터 범위

아래 관측치는 해당 generation의 70개 고유 signature 전체에서 집계했다. 설정 범위는 campaign YAML의 값이다.

| 파라미터 | 설정 범위 | 실제 signature에서 관측된 범위 |
|---|---:|---:|
| 절리군 1 density | 50–5,000 | 50–220 (10개 고유값) |
| 절리군 2 density | 2,000–10,000 | 2,000–2,200 (2개 고유값) |
| 절리군 3 density | 1,000–20,000 | 1,000–1,100 (3개 고유값) |
| 절리군 1 `size_r_min` / `size_r_max` | 5–20 / 50–150 | 9.091–11 / 90.909–110 |
| 절리군 2 `size_r_min` / `size_r_max` | 5–20 / 50–150 | 5–5.5 / 50–55.259 |
| 절리군 3 `size_r_min` / `size_r_max` | 5–20 / 50–150 | 9.091–11 / 90.909–110 |

따라서 절리군 3의 density 상한 20,000은 시험되지 않았다. 크기 값도 대부분 시작값 주변의 국소 probe 및 후보값이며 설정 구간 전체를 커버하지 않았다.

각도는 세 시작점 모두 같은 orientation에서 출발했다. `orientation_beta` probe는 절리군별로 다음 값 주변만 조사했다.

| 절리군 | probe 중심 β | 조사 probe |
|---|---:|---:|
| 1 | 25.659° | 20.659°–30.659° |
| 2 | 37.761° | 32.761°–42.761° |
| 3 | 28.879° | 23.879°–33.879° |

이는 설정된 β 범위 0°–90° 전체의 탐색이 아니다. v2의 log-coordinate update cap `0.10`이 실행에서 쓰인 흔적은 있다. 예를 들어 절리군 2 `size_r_max` 후보는 50에서 55.2585459로 이동했다. 다만 cap은 최대 이동량이지 전체 범위를 스캔한다는 뜻은 아니다.

## 확인된 알고리즘 결함 후보

[`NormalizedGradientUpdateRule.propose`](../src/euler_campaign/euler.py)의 현재 순서는 모든 비영(非零) 민감도에서 `max_sensitivity`를 계산한 다음 각 feature의 제안을 bound에 투영한다. 따라서 bound에 막힐 방향의 큰 민감도도 정규화 분모에 남는다.

실행 기록에서 절리군 2 density는 모든 시작점에서 하한 2,000에 있고 density 민감도는 대략 `-0.029`에서 `-0.031` 사이였다. 하한 바깥 방향 제안은 `bound_limited` 처리되지만 이 민감도가 정규화에 포함된다. 그 결과 다른 실행 가능한 density 좌표의 이동이 매우 작았다. 저장 후보에는 100→99.935, 200→200.050 같은 변화가 보인다. 시작점 하나에서는 density feature 세 개가 모두 bound-limited되어 후보 자체가 없었다.

이는 단순히 큰 탐색 범위를 시도하지 않은 문제와 별도로, **경계에서 막힌 민감도가 실행 가능한 좌표의 이동을 억제하는 정규화 문제**를 가리킨다. 수정 전에는 이 동작을 회귀 테스트로 고정해야 한다.

## 다음 작업 재개 체크리스트

1. 연속 파라미터의 “전 영역” 완료 기준을 명확히 정한다. 전체 Cartesian 조합을 뜻하는지, 각 축별 구간 sampling/coverage를 뜻하는지와 sampling resolution을 결정한다.
2. 경계에서 막힐 방향의 derivative를 제외하거나 projected/feasible gradient를 정규화해, 실행 가능한 다른 좌표의 제안이 축소되지 않도록 수정한다.
3. `all_lineages_saturated`와 “요구된 parameter-space coverage 완료”를 분리한다. 모든 block을 한 번 시도했다는 이유만으로 전체 탐색 완료로 표시하지 않는다.
4. density, size, β 구간을 계획적으로 탐색하는 전략을 설계한다. 단일 국소 gradient 후보와 새 bin 미발견만으로 탐색 종료하지 않게 한다.
5. 회귀 검증 항목: 경계의 최대 민감도가 feasible update를 억제하지 않는지, 범위 미탐색 시 saturation이 선언되지 않는지, 모든 축의 coverage 상태가 저장·표시되는지 확인한다.
6. 수정 실행은 이 DB와 generation을 덮어쓰지 말고 새 plan revision 또는 명확히 분리된 run generation에서 진행한다. 사용자가 테스트와 GPU 실행을 수행한다.
