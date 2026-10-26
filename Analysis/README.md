# QSimEx 문서

QSimEx의 설명서, 분석 보고서, 산출물 사전, 예시 계산을 보관합니다.

## 구성

- `qprime_*.md`: Q' 예측성 및 의사결정 분석 보고서
- `output_descriptions/`: CSV와 분석 표의 컬럼·용도 설명
- `column_mapping/`: 출력 CSV 컬럼 매핑
- `example_calculation/`: 개별 결과 행의 계산 추적 예시

## Q′ 점수 조합 전수 열거 (2026-10-26)

결과는 [qprime_score_grid_20261026/](qprime_score_grid_20261026/)에 저장한다.
근거는 사용자가 제공한 [NGI Q-system handbook 2025](../Specification/q-handbook_2025_english_final.pdf)의
인쇄면 53–55쪽(PDF 57–59쪽), 부록 표 1–4이다.

- 원시 RQD: 0부터 100까지 2 간격, 총 51개. 계산에는 `max(RQD, 10)` 적용.
- Jn: `0.5, 1, 2, 3, 4, 6, 9, 12, 15, 20`.
- Jr: `0.5, 1, 1.5, 2, 3, 4`.
- Ja: `0.75, 1, 2, 3, 4, 6, 8, 10, 12, 13, 20`.
- 범위형 점수는 사용자 승인에 따라 끝점으로 이산화한다. 범위 내부 값이 핸드북에서
  금지된다는 뜻이 아니며 임의의 중간값은 추가하지 않는다. Ja=10은 표 N에도 존재한다.
- 같은 숫자의 범주 중복은 제거하고 모든 숫자 조합을 열거한다. 암벽 접촉 조건으로
  조합을 걸러내지 않으므로 모든 행을 지질학적으로 양립 가능한 상태로 해석하지 않는다.
- Jn의 갱구 ×2·교차부 ×3, Jr의 절리 간격 조건부 +1 보정은 제외한다.
- 무교차 특례는 적용하지 않는다. DFN 및 기존 campaign 계산 모델은 변경하지 않는다.

| 결과 | 내용 |
|---|---|
| [qprime_combinations.csv](qprime_score_grid_20261026/qprime_combinations.csv) | 33,660개 조합, 원시·계산 RQD와 Q′의 실수·정확한 유리수 표현 |
| [qprime_value_distribution.csv](qprime_score_grid_20261026/qprime_value_distribution.csv) | 고유 Q′별 빈도. 원시 RQD 51개 기준과 계산 RQD 46개 기준을 구분 |
| [qprime_by_rqd.csv](qprime_score_grid_20261026/qprime_by_rqd.csv) | RQD별 660개 조합의 최솟값·최댓값·평균·선형 보간 분위수 |
| [qprime_histogram.csv](qprime_score_grid_20261026/qprime_histogram.csv) | 로그 간격 40개 구간의 빈도. 마지막 구간만 상한 포함 |
| [qprime_campaign_bins.csv](qprime_score_grid_20261026/qprime_campaign_bins.csv) | 기존 campaign의 10개 `(하한, 상한]` 구간과 400 초과를 별도 집계 |
| [qprime_distribution.png](qprime_score_grid_20261026/qprime_distribution.png) | 히스토그램·누적분포·RQD별 분포·기존 bin별 빈도 |

분포는 **이 열거 격자의 조합 빈도**이며 현장 발생확률이 아니다. 원시 RQD 0, 2, 4,
6, 8, 10은 계산 RQD 10으로 합쳐진다. 계산 RQD 기준 빈도는 이 중복을 제거하며,
서로 다른 인자 조합에서 같은 Q′가 나오는 중복은 유지한다. 고유값 판별에는 정확한
유리수 연산을 사용한다. 기존 10개 bin의 수치적 점유는 DFN 도달성이나 cutoff 식별의
증거가 아니다.

### Bin별 입력 시그니처 역추적

같은 점수 격자를 기존 campaign의 10개 bin과 `overflow`(400 초과)로 분할한다.
여기서 시그니처는 `(RQD, Jn, Jr, Ja)` 점수 조합이며 밀도·크기·방향 등 DFN 생성
시그니처를 역추정한 것은 아니다. 기존 원자료와 같은 경계 비교를 사용한다.

| 결과 | 용도 |
|---|---|
| [qprime_bin_signature_summary.csv](qprime_score_grid_20261026/qprime_bin_signature_summary.csv) | Bin별 조합 수, 고유 Q′ 수, 도달 가능한 Jn·Jr·Ja 조합 수, RQD 범위 및 각 인자의 가능한 점수 목록 |
| [qprime_bin_combinations.csv](qprime_score_grid_20261026/qprime_bin_combinations.csv) | Bin별로 묶은 전체 공동 조합 33,660행 |
| [qprime_bin_factor_distribution.csv](qprime_score_grid_20261026/qprime_bin_factor_distribution.csv) | Bin·인자·점수별 빈도 및 bin 안에서의 비율. 빈도 0인 점수도 포함 |
| [qprime_bin_required_rqd.csv](qprime_score_grid_20261026/qprime_bin_required_rqd.csv) | 각 bin의 Jn·Jr·Ja 660개 조합마다 도달 가능 여부와 필요한 원시·계산 RQD 목록 |

점수 목록은 세미콜론으로 구분한다. 역추적 RQD 표의 도달 가능 여부는 **이번 2단위
RQD 격자 내** 판정이며 연속 RQD 전체에 대한 불가능 증명이 아니다. 도달 불가능한
행도 보존하며 해당 RQD 목록과 최솟값·최댓값은 공란으로 둔다.

분포표의 `raw_fraction_within_bin`은 해당 bin의 전체 원시 격자 조합 중 그 인자값을
가진 비율이고, `calculation_fraction_within_bin`은 RQD 하한 중복을 제거한 격자에서의
비율이다. `rqd_raw` 인자의 계산 격자 열에는 원시 RQD 10 이상만 남긴다.
각 bin·인자 내 비율의 합은 1이다. 이 비율은 현장 확률이나
`P(bin | 인자값)`이 아니라 열거 격자의 `P(인자값 | bin)`에 해당한다.
서로 다른 인자의 주변분포를 독립적으로 조합하면 해당 bin에 도달하지 않을 수 있으므로
탐색 조건 선정에는 공동 조합 또는 필요한 RQD 표를 사용한다.

재생성:

```bash
conda run -n dlo-cq python tools/tabulate_qprime_scores.py \
  --output-dir Analysis/qprime_score_grid_20261026
```

## 문서 작성 규칙

- 확정된 기술 기준과 검증 방법은 이 폴더에 기록합니다.
- 실행 중간 메모와 날짜별 작업 기록은 `../doc/`에 둡니다.
- 문서에서 생성 데이터는 `../outputs/`, 단일 시각화 파일은 `../output/`을 참조합니다.
