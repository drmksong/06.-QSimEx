# scenario_02_dense_small_borehole_rows.csv — 예시 행 계산 추적

파일: `outputs/test_multicase/by_case_pure/scenario_02_dense_small/scenario_02_dense_small_borehole_rows.csv`

샘플: 첫 번째 데이터 행 (CSV 2행)

원시 행(요약):

- `case_name`: scenario_02_dense_small
- `seed`: 40
- `face_x_idx`: 10
- `face_x_coord`: 10.5
- `borehole_name`: Center

주요 수치(행에서 발췌):

- `Q_face_mean` = 30.392420499835023
- `Qp_face_mean` = 33.635888315255016
- `Q_bh_mean` = 20.958314275220374
- `Qp_bh_mean` = 28.067869276190027
- `RQD_bh_mean` = 82.63676049464769
- `RQD_face_scanline` = 100.0
- `Jv_face` method = P32_derived_Jv_proxy
- `Jn_bh_mean` = 2.0
- `Jr_bh_mean` = 1.2507671641877347
- `Ja_bh_mean` = 1.8397706198918304
- `Jw_bh_mean` = 0.8190682357572294
- `SRF_bh_mean` = 1.1443117334358373

계산 경로(컬럼별)

1. `Qp_face_mean` (33.6358883...)
   - 출처: `Tunnel.sample_face()` → `Qp_mean = QCalculator.calc_Qprime(rqd_reference, jn_val, jr_mean, ja_mean)`
   - 사용값: `rqd_reference = RQD_face_scanline = 100.0`, `jn_val` (face Jn) = 7.0 (case 기본값, CSV 끝부분에 `7.0`로 표시됨)
   - 수식: Q' = (RQD / Jn) \* (Jr / Ja)
   - 대입 (근사): (100.0 / 7.0) \* (jr_mean / ja_mean)
     - jr_mean ≈ (face에서 계산된 jr 평균, CSV의 Jr 관련 요약값 활용)
   - 결과: 33.635888315255016 (CSV 값)

2. `Qp_bh_mean` (28.06786927...)
   - 출처: `Tunnel.sample_borehole()` → `Qprime` 배열의 평균
   - per-segment: `Qprime_i = (RQD_i / Jn_i) * (Jr_i / Ja_i)`
   - 평균: `Qp_bh_mean = mean_i(Qprime_i)` → CSV에 28.067869276190027

3. `Q_bh_mean` (20.95831427...)
   - 출처: `Tunnel.sample_borehole()` → `Q` 배열의 평균
   - per-segment: `Q_i = (RQD_i / Jn_i) * (Jr_i / Ja_i) * (Jw_i / SRF_i)`
   - 평균: `Q_bh_mean = mean_i(Q_i)` → CSV에 20.958314275220374

4. `RQD_bh_mean` (82.63676049...)
   - 출처: `Tunnel.sample_borehole()` 내부 `rqd_arr` 평균
   - 계산: per-segment `rqd_raw` = `RQDCalculator.calc_direct(all_breaks, segment_length, threshold=0.1)`;
     - 필요시 `_calc_core_recovery()`로 보정 후 `rqd_arr[i] = rqd_raw * core_recovery`.
   - 평균 집계 결과: 82.63676049464769

5. `miss_ratio` / `detection_ratio`
   - 출처: `compare_at_face()`의 집합 연산
   - 계산: `miss_ratio = missed_count / face_count`; `detection_ratio = common_count / face_count`.
   - 예시 행: `miss_ratio` ≈ 0.9983296213808464? (CSV에 0.99833... 표기 — 주의: 이 값은 특정 행의 비율이며, face_count 큰 경우의 비율 결과임)

참고: 위 예시 계산은 CSV에 이미 집계된 값들을 역추적한 형식입니다. 실제 per-segment 배열(`RQD`, `Jn`, `Jr`, `Ja`, `Jw`, `SRF`)은 `Tunnel.sample_borehole()` 및 `Tunnel.sample_face()`에서 생성되며, 위 값을 그대로 대입하면 각 컬럼의 근사 재계산을 검증할 수 있습니다.

관련 코드 참조

- `src/core/tunnel.py` (`sample_borehole`, `sample_face`)
- `src/core/q_calculator.py` (`calc_Q`, `calc_Qprime`)
- `src/core/rqd_calculator.py` (`calc_direct`, `calc_hudson_from_lambda`, `calc_jv_proxy_from_joint_sets`)
- `src/core/comparison.py` (`comparisons_to_borehole_rows`)

문서 생성일: 2026-05-08
