# Q' 프로파일 1차 탐색 기록

- 실행일: 2026-09-24
- 목적: Q' 구간별 실제 프로파일 분포가 PR/TR/POST 구간 분할을 시도할 만큼 구조적인지 확인
- 단계: 탐색적 확인
- 판정: PR/TR/POST 분할 및 기준값 제안은 아직 수행하지 않음

> **기록의 범위:** 이 문서는 2026-09-24 레거시 borehole-row 자료로 수행한 1차 탐색
> 기록이다. 아래 입력, bin별 통계, 해석은 당시 그대로 보존하며 현재 물리 geometry 기반
> Q′BH/Q′Face longitudinal profile 계약을 설명하지 않는다. 현재 계산·탐색 규칙은
> [DesignSpec_20260922.md](DesignSpec_20260922.md)의 2026-10-04 후속 기록을 참조한다.

## 1. 입력 자료

보존된 레거시 시뮬레이션 결과 중 시추공 단위 파일을 사용했다.

```text
legacy_results/outputs/disposal_lowfract_curated/all_cases_borehole_rows.csv
```

입력 관측 단위는 borehole row이다. face-level `Qp_borehole_mean`은 사용하지 않고, 각 시추공 행의 `Qp_bh_mean`을 Q' 축으로 사용했다.

## 2. 탐색 가정

이번 단계에서는 다음만 가정한다.

1. 동일한 로그 Q' 구간 안의 행들을 하나의 관측 묶음으로 요약한다.
2. 프로파일은 단일 평균이 아니라 중앙값과 25~75% 분위수 범위로 관찰한다.
3. `Qp_face_mean`, 절리 누락·교차 관련 지표, 절리 밀도, 방향성 차이를 서로 다른 프로파일로 유지한다.
4. 처분 적합성, 안전성, 불량·적합 라벨은 생성하지 않는다.
5. PR/TR/POST 상태를 이번 탐색 결과에서 자동 판정하지 않는다.

## 3. 사용한 프로파일

| 프로파일 이름       | 입력 컬럼                      | 해석 보류 사항                          |
| ------------------- | ------------------------------ | --------------------------------------- |
| `qprime_face`       | `Qp_face_mean`                 | 처분 적합성으로 해석하지 않음           |
| `intersection_risk` | `miss_ratio`                   | 위험 방향과 임계 의미는 확정하지 않음   |
| `fracture_density`  | `face_fracture_density`        | 높고 낮음의 공학적 기준은 확정하지 않음 |
| `orientation_gap`   | `orientation_bias_gap_to_face` | 방향성 차이의 허용 의미는 확정하지 않음 |

## 4. 탐색 방법

초기 분석은 `0.1~400` 범위를 로그 공간 10구간으로 나누어 11개 경계값을 만들었다. 2026-10 grid에서는 경계값 개수를 늘리지 않고 첫 경계 `0.1`만 `0`으로 교체한다. 따라서 primary profile은 계속 10 bins이며 이후 양수 로그 경계는 유지된다. 각 인접 경계 사이에 들어오는 시추공 행을 모아 다음을 계산한다.

- 행 수 `n_records`
- domain 수 `n_domains` (`case_name`, `seed` 조합)
- 각 프로파일의 유효 표본 수
- 중앙값
- 25% 분위수
- 75% 분위수

결과 파일:

```text
legacy_results/profile_exploration/disposal_lowfract_borehole_profiles.json
```

이 결과는 레거시 입력을 이용한 탐색 산출물이며 공식 `results/`가 아니다.

## 5. 1차 결과

실제 입력 행 수는 300개이며, 다음 구간에 관측값이 있었다.

| Q'\_BH 구간 | 행 수 | domain 수 | Q'\_face 중앙값 | miss ratio 중앙값 | face density 중앙값 | orientation gap 중앙값 |
| ----------- | ----: | --------: | --------------: | ----------------: | ------------------: | ---------------------: |
| 2.76~6.32   |    19 |        15 |            6.56 |            0.9983 |                7.47 |                 0.0621 |
| 6.32~14.50  |    65 |        20 |            6.66 |            0.9983 |                7.78 |                 0.0548 |
| 14.50~33.22 |   176 |        20 |           18.69 |            0.9791 |                2.22 |                 0.0611 |
| 33.22~76.15 |    40 |        19 |           34.09 |            0.9851 |                1.62 |                 0.1818 |

`0.1~2.76` 및 `76.15~400` 구간은 관측값이 없었다.

## 6. 현재 해석

이번 결과만으로 PR/TR/POST를 판정하지 않는다. 다만 다음 탐색 신호는 보인다.

- `Q'_BH`가 6.32~14.50에서 14.50~33.22로 이동할 때 `Q'_face` 중앙값은 증가했다.
- 같은 구간에서 `face_fracture_density` 중앙값은 크게 감소했다.
- `miss_ratio` 중앙값은 높은 수준으로 유지되어, 모든 프로파일이 같은 방식으로 안정된다고 볼 수 없다.
- `orientation_gap`은 높은 Q' 구간에서 오히려 변동과 중앙값 변화가 있어 단순한 안정 구간으로 해석하기 어렵다.
- 가장 많은 표본이 14.50~33.22 구간에 몰려 있어, 다른 구간과 직접 비교할 때 표본 불균형을 주의해야 한다.

따라서 현재 결과는 다음 결론을 지지한다.

```text
프로파일 변화의 가능성은 보이지만,
현재 자료만으로 PR/TR/POST 구간을 확정할 수 없다.
```

## 7. 가설 확인 결과

검토한 가설:

> Q'\_BH가 증가하면 Q'\_face와 절리 관련 프로파일이 일정한 구조를 가지고 함께 변화하여, PR/TR/POST 구간으로 깔끔하게 나뉠 것이다.

1차 탐색 결과:

```text
부분적으로만 관찰됨.
Q'_face와 face density에서는 구간 변화가 보이지만,
miss ratio와 orientation gap까지 동일한 안정 구조를 보인다고 판단할 근거는 부족함.
```

따라서 이 가설은 현재 단계에서 **확정되지 않았다**. 통계적 검정이나 최종 기준값 선정으로 진행하지 않고, 다음 탐색에서 데이터 분포와 domain별 패턴을 더 확인해야 한다.

## 8. 대규모 MC 후속 실행 준비

파일럿에서 얻은 다음 교훈을 반영하여 대규모 실행 설정을 분리했다.

- 시추공 단위 `Qp_bh_mean`을 유지한다.
- `Qp_face_mean`과 절리 관련 참조지표를 원자료로 저장한다.
- case·seed·face 위치·borehole window를 고정된 YAML로 기록한다.
- 기존 레거시 결과를 재사용하지 않고 새 결과를 `results/profile_mc_exploration/`에 저장한다.
- 대규모 실행 후 먼저 프로파일 분포를 확인하고, PR/TR/POST 상태 판정은 그 결과를 본 뒤 결정한다.

실행 설정:

```text
config/profile_mc_exploration.yml
```

실행 명령:

```bash
conda run -n dlo-cq python run_profile_mc.py \
	--config config/profile_mc_exploration.yml
```

## 9. 2026-10-04 후속 정합성 메모

이 메모는 1~8절의 결과나 원자료를 수정하지 않는다. 당시 `Qp_bh_mean` row를 관측
단위로 삼고 `Qp_face_mean` 등 참조지표를 Q′ 구간별로 요약한 결과는 legacy row-level
exploratory evidence로 유지한다. 그 표본 단위·요약 통계는 새 profile contract에 따른
station/segment-level 자료와 동일하지 않으며, 두 자료를 하나의 연속 profile로 이어 붙이지
않는다.

후속 실행은 물리 좌표의 시추공 geometry와 tunnel polyline을 사용하고, 전체 Q′BH
profile 및 거리순 Q′Face station sequence를 보존한다. Face/BH 대응 분석은 실제 overlap에
한정하고, overlap 밖 Q′BH 자료는 독립 관측으로 유지한다. Bin coverage는 profile 값이
실제로 점유한 bin과 양의 길이 support로 판단하며 envelope만으로 빈 bin을 채우지 않는다.
상세 계약은 DesignSpec 5.8 및 adaptive execution plan의 2026-10-04 후속 기록을 따른다.

이전 파일과 같은 입력으로 재분석하지 않는 한 이 후속 계약은 본 문서의 2026-09-24
수치표를 갱신하지 않는다. 새 profile 데이터로 분석하는 경우에는 별도 결과 파일과 날짜,
입력 manifest, 코드/설정 식별자, 관측 단위 및 요약 규칙을 기록한다.
