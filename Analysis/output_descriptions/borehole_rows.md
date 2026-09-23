# `borehole_rows` — 의미와 용도

의미

- 보어홀(코어) 샘플 단위로 수집된 측정값과 요약 통계의 행(row)들입니다. 각 행은 특정 보어홀 윈도우(window) 또는 세그먼트에 대한 RQD, Jn/Jr/Ja/Jw/SRF 값, Q/Q' 계산 결과, 절리 검출 관련 집계(검출된 절리 개수, 공통 절리 개수 등)를 포함합니다.

주요 컬럼(일반적)

- 식별자: `case_name`, `seed`, `borehole_name`, 위치 인덱스/좌표
- RQD: `RQD_bh_mean`, `RQD_borehole_direct_mean`, `RQD_borehole_hudson_mean`, `lambda_borehole_mean` 등
- Q/Q': `Q_bh_mean`, `Q_bh_median`, `Qp_bh_mean`, `Qp_bh_median`
- 절리 통계: `bh_fracture_count`, `bh_fracture_frequency`, `bh_union_fracture_frequency`
- 비교 지표: `Q_ratio_bh_to_face`, `Qp_ratio_bh_to_face`, `miss_ratio`, `detection_ratio`

생성 코드(대표)

- `src/core/tunnel.py::sample_borehole()` — 세그먼트 샘플링과 per-segment 계산
- 집계/CSV 변환: `src/core/comparison.py::comparisons_to_borehole_rows()`

용도

- 보어홀 기반의 성능 평가(예: 보어홀에서 측정된 Q/Q'와 면 측정값 비교).
- 절리 검출률 분석과 Miss/False 비율 계산용 디버깅·검증 데이터.

참고

- 이 파일은 상세한 세그먼트 배열(각 세그먼트의 RQD/Jn/Jr 등)을 내부적으로 생성하지만 CSV에는 보통 요약 통계(평균/중앙값 등)를 저장합니다.
