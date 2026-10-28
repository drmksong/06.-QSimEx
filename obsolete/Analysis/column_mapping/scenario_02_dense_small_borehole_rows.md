# scenario_02_dense_small_borehole_rows.csv — 컬럼 매핑

파일: `outputs/test_multicase/by_case_pure/scenario_02_dense_small/scenario_02_dense_small_borehole_rows.csv`

아래는 CSV의 각 컬럼과 그 출처(코드 파일 및 계산식)의 요약입니다.

- case_name, seed, face_x_idx, face_x_coord
  - 출처: `src/core/comparison.py` (`comparisons_to_borehole_rows()`에서 복사)
  - 설명: 비교(dict)에서 복사됨. `face_x_coord`는 `Tunnel.sample_face()`의 `face["x_coord"]` 값.

- borehole_name
  - 출처: `src/core/tunnel.py::sample_borehole()` (`borehole_name` key, BH_NAMES 매핑)

- Q_face_mean, Qp_face_mean
  - 출처: `src/core/tunnel.py::sample_face()` → `face['stats']['Q']['mean']`, `face['stats']['Qprime']['mean']`
  - 계산: `Qp_face_mean = QCalculator.calc_Qprime(rqd_reference, jn_val, jr_mean, ja_mean)`

- Q_bh_mean, Q_bh_median, Qp_bh_mean, Qp_bh_median
  - 출처: `src/core/tunnel.py::sample_borehole()` → `Q` 및 `Qprime` 배열의 평균/중앙값
  - 계산: per-segment
    - `Q = QCalculator.calc_Q(RQD, Jn, Jr, Ja, Jw, SRF)`
    - `Qprime = QCalculator.calc_Qprime(RQD, Jn, Jr, Ja)`

- RQD_bh_mean, Jn_bh_mean
  - 출처: `src/core/tunnel.py::sample_borehole()`
  - 설명: `RQD` 배열(코어 회수율·미세절리 보정 반영 가능)의 평균; `Jn`은 세그먼트별 `Jn` 배열 평균

- RQD_borehole_direct_mean/\_median
  - 출처: `src/core/tunnel.py::sample_borehole()` (내부 `rqd_borehole_direct_arr`)
  - 계산: `RQDCalculator.calc_direct(seg_t, segment_length, threshold=0.1)` (Deere 직접법)

- RQD_borehole_hudson_mean/\_median
  - 출처: `src/core/tunnel.py::sample_borehole()` (내부 `rqd_borehole_hudson_arr`)
  - 계산: lambda = `RQDCalculator.calc_lambda_from_count(N, L)` → `RQDCalculator.calc_hudson_from_lambda(lambda, threshold=0.1)`

- lambda_borehole_mean, borehole_n_intersections_sum
  - 출처: `src/core/tunnel.py::sample_borehole()`

- RQD_face_scanline, RQD_face_jv, RQD_face_conservative, lambda_face_scanline, face_scanline_n_intersections
  - 출처: `src/core/tunnel.py::sample_face()`
  - 계산:
    - `rqd_face_scanline` = `DirectionalRQDCalculator.rqd_at_face_horizontal_scanline(...)` (중앙 수평 scanline)
    - `jv_face` = `RQDCalculator.calc_jv_proxy_from_joint_sets(...)`; `rqd_face_jv` = `RQDCalculator.calc_from_jv(jv_face)`
    - `rqd_face_conservative` = `min(rqd_face_scanline, rqd_face_jv)`

- Jv_face, Jv_method
  - 출처: `src/core/rqd_calculator.py::calc_jv_proxy_from_joint_sets()`

- Jr_bh_mean, Ja_bh_mean, Jw_bh_mean, SRF_bh_mean
  - 출처: `src/core/tunnel.py::sample_borehole()`
  - 설명: DFN 절리에서의 Jr/Ja 평균(없으면 global 값 사용), Jw/SRF는 도메인 그리드값을 사용. `correction_mode`에 따라 scaling 적용 가능.

- Q_ratio_bh_to_face, Qp_ratio_bh_to_face
  - 출처: `src/core/comparison.py::compare_at_face()` (per-borehole 항목)
  - 계산: `bh_mean / max(face_mean, 1e-10)`

- face_fracture_count, bh_fracture_count, common_fracture_count, missed_fracture_count, miss_ratio, detection_ratio
  - 출처: `src/core/tunnel.py::sample_borehole()`와 `compare_at_face()`의 집합 연산
  - 설명: face와 borehole의 절리 ID 집합 교집합/차집합으로 계산

- bh_window_length, bh_fracture_frequency
  - 출처: `src/core/comparison.py::compare_at_face()`
  - 계산: window_length = (x_end - x_start) \* domain.dx; fracture_frequency = len(bh_joint_ids)/window_length

- face_fracture_density, bh_union_fracture_frequency, common_fracture_density, missed_fracture_density
  - 출처: `src/core/comparison.py` (aggregate 계산)
  - 계산: 면적(π·radius^2) 대비 개수 등

- orientation_bias_bh, face_orientation_bias, orientation_bias_gap_to_face
  - 출처: `src/core/comparison.py::_calc_orientation_bias()`
  - 계산: `1 - mean(|n · d_bh|)` (절리 법선과 borehole 방향의 절대 내적 평균)

- Q*match*_ 및 Qp*match*_ (플래그)
  - 출처: `src/core/comparison.py::comparisons_to_borehole_rows()`
  - 기준: Strict 0.8–1.25, Normal 0.67–1.5, Loose 0.5–2.0

---

참고 소스 파일

- `src/core/comparison.py` (compare_at_face, comparisons_to_borehole_rows)
- `src/core/tunnel.py` (sample_borehole, sample_face)
- `src/core/rqd_calculator.py` (calc_direct, calc_hudson_from_lambda, calc_from_jv, calc_jv_proxy_from_joint_sets)
- `src/core/q_calculator.py` (calc_Q, calc_Qprime)

문서 생성일: 2026-05-08
