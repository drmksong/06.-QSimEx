# `face_rows` — 의미와 용도

의미

- 터널 면(face) 단위로 수집된 측정값과 요약 통계의 행입니다. 면 스캔라인에서 계산된 RQD(수평 스캔라인), 면 기반 Q/Q', 면 절리 목록 및 면 특성(절리 밀도, 방향 편향 등)을 포함합니다.

주요 컬럼(일반적)

- 식별자: `case_name`, `seed`, `face_x_idx`, `face_x_coord`
- RQD(면): `RQD_face_scanline`, `RQD_face_jv`, `RQD_face_conservative`, `lambda_face_scanline`
- Q/Q': `Q_face_mean`, `Qp_face_mean`, 면 통계(평균/분산)
- 절리 통계: `face_fracture_count`, `face_fracture_density`, `face_orientation_bias`
- 탐지 관련: `common_fracture_count`, `missed_fracture_count` (보어홀 대비)

생성 코드(대표)

- `src/core/tunnel.py::sample_face()` — 면 스캔라인 계산 및 면 통계 생성
- CSV 출력: `src/core/comparison.py::comparisons_to_face_rows()`

용도

- 면 기반의 지표(현장 관찰)와 보어홀 샘플을 비교할 때 주로 사용됩니다.
- 면에서의 RQD/Q' 분포를 분석하고, 보어홀로부터 추정된 값과의 차이를 평가합니다.
