# QSimEx 단계별 signature 실험 근거표 (2026-09-27 정리)

이 문서는 오늘 검토한 D/A/B/C 탐색과 저Q·고Q 보강 실험의 **관측 결과**를 기록한다.
실행 날짜를 모두 9월 27일로 간주하지 않는다. 수치는 각 CSV에서 같은 `case_name`과
`seed`의 시추공 행을 먼저 평균하고, 그 seed별 평균을 다시 평균한 값이다. `n`은 독립
seed 수이며 시추공 행 수가 아니다. Q'은 `Qp_bh_mean`, RQD는 `RQD_bh_mean`, 교차수는
`borehole_n_intersections_sum`의 행 평균이다. 교차수는 전체 domain의 절리 수가
아니다. 아래 수치는 설명적 관측값이지 유의성 검정, 보편 임계값 또는 cutoff가 아니다.

| 단계/비교 조건                                     | seed             |             Q' 평균 |              RQD 평균 |           교차수 평균 | 관측과 해석                                                                                                                  | 원본                                                                                                                                                                   |
| -------------------------------------------------- | ---------------- | ------------------: | --------------------: | --------------------: | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D: 동일 총 P32의 1/2/3 절리군                      | 302~304 (각 n=3) | 17.26 / 8.79 / 3.72 | 97.79 / 97.34 / 97.37 |      seed에 따라 변동 | 군 수별 Q' 순서가 3 seed에서 반복됐다. 총 P32만으로 구조 차이를 대체할 수 없다.                                              | [round 005](../results/profile_mc_d_matched_round_005/all_cases_borehole_rows.csv), [round 006](../results/profile_mc_d_matched_round_006/all_cases_borehole_rows.csv) |
| A: 밀도 0.5x / 2x                                  | 306~308 (각 n=3) |         3.84 / 3.52 |         99.15 / 95.11 |          4.56 / 19.00 | 4배 밀도 비율에도 Q' 변화는 비교적 작고 교차수는 증가했다.                                                                   | [round 007](../results/profile_mc_a_density_round_007/all_cases_borehole_rows.csv)                                                                                     |
| A: 밀도 2x / 4x / 8x                               | 313~316 (각 n=4) |  3.54 / 3.17 / 2.35 | 94.56 / 86.80 / 62.60 | 20.33 / 40.58 / 80.75 | 같은 3-절리군 계열에서 밀도가 커질수록 교차가 늘고 RQD·Q'가 감소했다. 이는 이 조건에서의 반응이며 보편 밀도 임계값은 아니다. | [round 007-1](../results/profile_mc_a_density_round_007_1/all_cases_borehole_rows.csv)                                                                                 |
| B: size alpha high / low / max radius high         | 309~312 (각 n=4) |  3.93 / 3.70 / 3.75 | 97.67 / 97.21 / 97.70 | 10.08 / 10.75 / 10.75 | 이 probe들의 차이는 위 A의 4x→8x 변화보다 작다. size 효과가 없다는 결론은 아니다.                                            | [round 008](../results/profile_mc_b_size_round_008/all_cases_borehole_rows.csv)                                                                                        |
| C: dip high / direction rotated / spread wide (4x) | 317~320 (각 n=4) |  3.33 / 2.55 / 2.58 | 86.99 / 67.44 / 67.59 | 37.33 / 75.75 / 70.33 | 입력 dip만으로 효과를 설명할 수 없다. 실제 borehole-plane angle과 교차를 함께 확인해야 한다.                                 | [round 009](../results/profile_mc_c_orientation_round_009/all_cases_borehole_rows.csv)                                                                                 |

### 실제 시추공-절리면 사잇각 (C 단계, 고정 4x·3절리군 계열)

각 값은 seed 317~320 (case별 n=4)의 평균이다. 실제 사잇각은
`borehole_plane_angle_mean_deg`이고, 0도는 시추공과 절리면 평행,
90도는 절리면에 수직이다. case명에 들어간 입력 방향각과 동일한 값이 아니다.

| case 입력 방향 표기 | 실제 사잇각 (도) | Q' 평균 | RQD 평균 | 교차수 평균 | 원본                                                                             |
| ------------------- | ---------------: | ------: | -------: | ----------: | -------------------------------------------------------------------------------- |
| dir 000             |            13.24 |    3.33 |    86.99 |       37.33 | [round 010](../results/profile_mc_c_angle_round_010/all_cases_borehole_rows.csv) |
| dir 005             |            14.16 |    3.21 |    84.68 |       41.25 | [round 010](../results/profile_mc_c_angle_round_010/all_cases_borehole_rows.csv) |
| dir 015             |            19.89 |    2.69 |    71.48 |       65.50 | [round 010](../results/profile_mc_c_angle_round_010/all_cases_borehole_rows.csv) |
| dir 030             |            29.10 |    1.79 |    47.54 |      117.08 | [round 010](../results/profile_mc_c_angle_round_010/all_cases_borehole_rows.csv) |
| dir 060             |            49.32 |    0.75 |    20.27 |      202.67 | [round 010](../results/profile_mc_c_angle_round_010/all_cases_borehole_rows.csv) |
| dir 090             |            59.31 |    0.54 |    14.50 |      236.00 | [round 010](../results/profile_mc_c_angle_round_010/all_cases_borehole_rows.csv) |

이 데이터의 **관측 구간은 약 13.24~59.31도**이다. 인접 관측점의 Q'/도 변화율은
약 -0.135, -0.091, -0.097, -0.051, -0.021로 일정하지 않다. 이는 case 평균의
구간별 기술량이지 인과적 도함수는 아니다. [각도 분석 JSON](../results/coverage_rounds/round_010_c_angle/angle_sensitivity.json)의
60~90도 PCHIP 값은 **관측이 아닌 외삽**이며 후보 cutoff나 update 방향의 근거로
사용하지 않는다.

### 저Q·고Q 도달성과 조합 효과

| 실험 조건                                           | seed          |    Q' 평균 (seed 범위) | RQD 평균 (seed 범위) | 교차수 평균 | 실제 사잇각 평균 | 해석과 원본                                                                                                                                                                                                                                                                                                                                           |
| --------------------------------------------------- | ------------- | ---------------------: | -------------------: | ----------: | ---------------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 저Q: density8 + angle49, 3절리군                    | 321~324 (n=4) |    0.067 (0.018~0.148) |  1.816 (0.494~4.024) |      403.75 |          49.18도 | 밀도와 각도를 함께 바꾼 조합의 도달 결과로, 각각의 독립 효과를 분리할 수 없다. [round 011](../results/profile_mc_next_lowq_round_011/all_cases_borehole_rows.csv), [round 012](../results/profile_mc_next_lowq_round_012/all_cases_borehole_rows.csv)                                                                                                 |
| 고Q: round 014의 d10 base/base                      | 325~328 (n=4) |                 266.67 | 100.00 |        0.00 | 해당 교차 절리 없음 | 교차가 없으면 Q'이 매우 높게 유지될 수 있다. 사잇각 결측은 0도가 아니다. [round 014](../results/profile_mc_highq_portfolio_round_014/all_cases_borehole_rows.csv) |
| 고Q: round 014 v2 d10000 angle60 focused large base | 325~328 (n=4) |                 222.54 | 88.34 |        34.92 | 57.79도 | 밀도·방향·크기 조합이 달라 단일 변수 효과로 해석하지 않는다. [round 014 v2](../results/profile_mc_highq_portfolio_round_014_v2/all_cases_borehole_rows.csv) |
| 고Q: d20000 focused large base                      | 333~336 (n=4) | 164.14 (156.78~173.53) |  65.67 (62.92~69.73) |       76.75 |          56.77도 | 목표 76.15~174.52 구간에 반복 도달했다. `d20000`은 case명이며 [loop manifest](../results/profile_mc_highq_euler_round_015/loop_manifest.json)의 `total_p32`는 200이다. [round 015](../results/profile_mc_highq_euler_round_015/all_cases_borehole_rows.csv), [repeat](../results/profile_mc_highq_euler_round_015_repeat/all_cases_borehole_rows.csv) |

### 로직 검토에 사용할 때

- D의 절리군 구조는 A의 밀도 조절만으로 치환하지 않는다. 같은 seed에서 바꾼 feature와
  관측 교차수·RQD·Q'의 동반 변화를 따로 기록한다.
- C에서는 입력 dip/dip direction보다 **실제로 생성된 시추공-절리면 사잇각**을
  반응 설명변수로 보고, 관측된 사잇각 범위에서만 민감도를 비교한다. 사잇각은
  realization 결과이므로 입력 feature를 기계적으로 해당 도수로 설정할 수 없다.
- A와 고Q 결과를 함께 고려하면 P32의 고정 배율이나 교차수의 단일 임계값을 이
  표에서 도출할 수 없다. feature 선택과 step 크기는 조건을 맞춘 probe와 독립 seed
  재현을 확인한 뒤에만 결정한다. 이 표만으로 운영 lower/upper cutoff를 확정하지 않는다.
