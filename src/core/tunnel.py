"""
터널 기하학, 시추공 샘플링, 굴진면 샘플링

DFN 직접 교차 기반 샘플링:
  - 시추공:
      굴착 전 수평시추공을 x방향 1D line으로 샘플링한다.
      Deere 직접법 RQD와 Hudson/Priest-Hudson lambda 기반 RQD를 계산한다.

  - 굴진면:
      굴착 후 노출된 face plane(x = face_x) 위에서만 RQD를 계산한다.
      현실적인 현장 mapping을 반영하여 중앙 수평 y방향 단일 scanline만 사용한다.
      x방향, 즉 굴진 방향 face scanline과 multi-direction 평균은 사용하지 않는다.

  - Jv:
      절리군 spacing 또는 P32-derived Jv proxy를 이용하여 Palmström형 RQD를 계산한다.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional

from .domain import RockDomain
from .q_calculator import QCalculator
from .rqd_calculator import RQDCalculator, DirectionalRQDCalculator


class Tunnel:
    """터널 & 시추공 & 막장면 — DFN 직접 교차 기반"""

    BH_NAMES = ['Center', 'Top', 'Bottom']

    # ─── 물리 상수 ───
    BOREHOLE_DIAMETER = 0.076
    FACE_OBSERVATION_DEPTH = 1.0

    # ─── 스케일 효과 파라미터 ───
    JR_SCALE_FACTOR_FACE = 0.85
    JR_SCALE_FACTOR_BH = 1.10
    JA_UNDERESTIMATE_BH = 0.85
    JA_SCALE_FACTOR_FACE = 1.05

    # ─── 코어 손실 모델 ───
    CORE_LOSS_THRESHOLD = 15
    CORE_LOSS_RATE = 0.15

    # ─── ★ 추가: 현실성 보정 파라미터 ───
    # [1] 기계적 코어 파쇄 (Mechanical Break)
    MECHANICAL_BREAK_PROB = 0.15        # 절리 교차점에서 추가 파쇄 확률
    MECHANICAL_BREAK_OFFSET_MEAN = 0.03 # 추가 파쇄 위치 (절리에서 ~3cm)
    MECHANICAL_BREAK_OFFSET_STD = 0.02

    # [2] 미세절리 (Micro-fractures)
    # DFN에 포함되지 않는 소규모 절리
    # 실측 기반: 대규모 절리 빈도의 0.5~2.0배 추가
    MICRO_FRACTURE_MULTIPLIER = 0.8     # 관측 절리 수 × 이 계수 = 추가 미세절리

    # [3] 코어 회수율 감소 (절리 밀집구간)
    CORE_RECOVERY_BASE = 0.98           # 기본 회수율 98%
    CORE_RECOVERY_DECAY = 0.03          # 절리 1개당 회수율 감소

    def __init__(self, domain: RockDomain, correction_mode: str = "pure"):
        """
        correction_mode:
        - "practice": 기존 보정 모두 사용
        - "neutral_strength": Jr/Ja/face conservatism만 제거
        - "pure": 모든 artificial correction 제거
        """
        self.correction_mode = correction_mode

        valid_modes = ["practice", "neutral_strength", "pure"]
        if correction_mode not in valid_modes:
            raise ValueError(f"Invalid correction_mode={correction_mode}. Use {valid_modes}")        
        self.domain = domain
        self.case = domain.case
        self.dfn = domain.dfn
        self.rqd_calculator = DirectionalRQDCalculator(self.dfn)
        self.rng = np.random.RandomState(self.case.seed + 200)

        self.center_y = self.case.tunnel_center_y
        self.center_z = self.case.tunnel_center_z
        self.center_y_idx = int(self.center_y / domain.dy)
        self.center_z_idx = int(self.center_z / domain.dz)
        self.radius = self.case.tunnel_radius

        self.borehole_positions = []
        self.borehole_coords = []
        for dy_off, dz_off in self.case.borehole_offsets:
            y_m = self.center_y + dy_off
            z_m = self.center_z + dz_off
            y_idx = int(np.clip(y_m / domain.dy, 0, domain.ny - 1))
            z_idx = int(np.clip(z_m / domain.dz, 0, domain.nz - 1))
            self.borehole_positions.append((y_idx, z_idx))
            self.borehole_coords.append((y_m, z_m))
    
    def _use_strength_scaling(self) -> bool:
        return self.correction_mode == "practice"

    def _use_drilling_damage(self) -> bool:
        return self.correction_mode == "practice"

    def _use_micro_fractures(self) -> bool:
        return self.correction_mode == "practice"

    def _use_face_conservatism(self) -> bool:
        return self.correction_mode == "practice"

    def _use_practical_face_rqd(self) -> bool:
        return self.correction_mode in ["practice", "neutral_strength"]

    # ================================================================
    # 시추공 샘플링 — DFN 직접 교차 + 현실 보정
    # ================================================================
    def sample_borehole(self, bh_idx: int,
                         x_start: int, x_end: int,
                         window: float = None) -> Dict:
        """
        시추공 1D 라인 샘플링 — DFN 직접 교차 + 현실 보정

        현실 보정:
        1. 기계적 코어 파쇄 (절리 근처 추가 break)
        2. 미세절리 (DFN 미포함 소규모 절리)
        3. 코어 회수율 감소 (절리 밀집구간)
        4. Jr/Ja 스케일 효과
        """
        y_m, z_m = self.borehole_coords[bh_idx]
        x_start_m = x_start * self.domain.dx
        x_end_m = x_end * self.domain.dx
        bh_length = x_end_m - x_start_m

        if bh_length <= 0:
            return self._empty_borehole_result(bh_idx, x_start, x_end)

        # ★ DFN과 직접 교차 계산
        origin = np.array([x_start_m, y_m, z_m])
        direction = np.array([1.0, 0.0, 0.0])

        intersections = self.dfn.get_joints_intersecting_line(
            origin, direction, bh_length
        )

        t_values = np.array([t for t, _ in intersections]) if intersections else np.array([])
        hit_joints = [j for _, j in intersections]

        # ── 구간별 계산 ──
        n_segments = x_end - x_start
        segment_length = self.domain.dx

        rqd_arr = np.zeros(n_segments)
        jr_arr = np.zeros(n_segments)
        ja_arr = np.zeros(n_segments)
        jn_arr = np.full(n_segments, self.case.joint_config.Jn)
        jw_arr = np.zeros(n_segments)
        srf_arr = np.zeros(n_segments)
        joint_count_arr = np.zeros(n_segments, dtype=int)

        # ============================================================
        # RQD 방법 비교용 신규 배열
        # ------------------------------------------------------------
        # RQD_borehole_direct:
        #   DFN 자연 절리 교차점만 사용한 시추공 Deere 직접 RQD
        #
        # RQD_borehole_hudson:
        #   같은 DFN 자연 절리 교차점 수로부터 lambda = N/L 계산 후
        #   Priest-Hudson 식으로 계산한 RQD
        #
        # 주의:
        #   practice mode에서 기계적 파쇄/미세절리를 추가하더라도,
        #   아래 RQD 비교용 컬럼은 "자연 DFN 절리" 기준으로 유지한다.
        #   그래야 시추공 RQD와 face RQD의 기하학적/방향성 차이를 분리해서 볼 수 있다.
        # ============================================================

        rqd_borehole_direct_arr = np.zeros(n_segments)
        lambda_borehole_arr = np.zeros(n_segments)
        rqd_borehole_hudson_arr = np.zeros(n_segments)
        borehole_n_intersections_arr = np.zeros(n_segments, dtype=int)

        y_idx, z_idx = self.borehole_positions[bh_idx]
        for i in range(n_segments):
            xi = x_start + i
            if xi < self.domain.nx:
                jw_arr[i] = self.domain.fields['Jw'][xi, y_idx, z_idx]
                srf_arr[i] = self.domain.fields['SRF'][xi, y_idx, z_idx]
            else:
                jw_arr[i] = self.case.joint_config.Jw_mean
                srf_arr[i] = self.case.joint_config.SRF_mean

        global_jr = np.mean([js.Jr_mean for js in self.case.joint_config.joint_sets])
        global_ja = np.mean([js.Ja_mean for js in self.case.joint_config.joint_sets])

        for i in range(n_segments):
            seg_start = i * segment_length
            seg_end = seg_start + segment_length

            # 이 구간 내 DFN 교차점
            if len(t_values) > 0:
                mask = (t_values >= seg_start) & (t_values < seg_end)
                seg_t = t_values[mask] - seg_start
                seg_joints = [hit_joints[idx] for idx in np.where(mask)[0]]
            else:
                seg_t = np.array([])
                seg_joints = []

            n_dfn_hits = len(seg_joints)

            # ============================================================
            # Method 1: Borehole direct RQD
            # Method 2: Borehole Hudson lambda RQD
            # ------------------------------------------------------------
            # 둘 다 자연 DFN 절리 교차점 seg_t만 사용한다.
            # 기계적 파쇄나 미세절리는 RQD 방법 비교용 컬럼에는 넣지 않는다.
            # ============================================================
            borehole_n_intersections_arr[i] = n_dfn_hits

            rqd_borehole_direct_arr[i] = RQDCalculator.calc_direct(
                seg_t.tolist(),
                segment_length,
                threshold=0.1,
            )

            lambda_bh = RQDCalculator.calc_lambda_from_count(
                n_intersections=n_dfn_hits,
                total_length=segment_length,
            )

            lambda_borehole_arr[i] = lambda_bh

            rqd_borehole_hudson_arr[i] = RQDCalculator.calc_hudson_from_lambda(
                linear_frequency=lambda_bh,
                threshold=0.1,
            )

            if self._use_drilling_damage():
                mechanical_breaks = self._generate_mechanical_breaks(
                    seg_t, segment_length
                )
            else:
                mechanical_breaks = np.array([])

            if self._use_micro_fractures():
                micro_fractures = self._generate_micro_fractures(
                    n_dfn_hits, segment_length
                )
            else:
                micro_fractures = np.array([])

            # 모든 파단점 합산
            all_breaks = np.concatenate([
                seg_t,
                mechanical_breaks,
                micro_fractures
            ])
            all_breaks = np.sort(all_breaks)
            all_breaks = all_breaks[(all_breaks >= 0) & (all_breaks <= segment_length)]

            total_breaks = len(all_breaks)
            joint_count_arr[i] = total_breaks

            # ★ [3] RQD 계산 (Deere 직접법, 모든 파단점 포함)
            rqd_raw = RQDCalculator.calc_direct(
                all_breaks.tolist(), segment_length, threshold=0.1
            )

            # ★ [4] 코어 회수율 보정
            if self._use_drilling_damage():
                core_recovery = self._calc_core_recovery(total_breaks, segment_length)
            else:
                core_recovery = 1.0
            
            # 코어 손실 구간은 RQD 계산에서 "0cm 조각"으로 처리
            rqd_arr[i] = rqd_raw * core_recovery

            # Jr, Ja: DFN 절리에서만 수집 (미세절리는 Jr/Ja 없음)
            if n_dfn_hits > 0:
                jr_raw = np.mean([j.Jr for j in seg_joints])
                ja_raw = np.mean([j.Ja for j in seg_joints])
                if self._use_strength_scaling():
                    jr_arr[i] = np.clip(jr_raw * self.JR_SCALE_FACTOR_BH, 0.5, 4.0)
                    ja_arr[i] = np.clip(ja_raw * self.JA_UNDERESTIMATE_BH, 0.75, 20.0)
                else:
                    jr_arr[i] = np.clip(jr_raw, 0.5, 4.0)
                    ja_arr[i] = np.clip(ja_raw, 0.75, 20.0)
            else:
                jr_arr[i] = global_jr
                ja_arr[i] = global_ja

        # Q, Q' 계산
        q_arr = np.array([
            QCalculator.calc_Q(rqd_arr[i], jn_arr[i], jr_arr[i],
                               ja_arr[i], jw_arr[i], srf_arr[i])
            for i in range(n_segments)
        ])
        qp_arr = np.array([
            QCalculator.calc_Qprime(rqd_arr[i], jn_arr[i],
                                     jr_arr[i], ja_arr[i])
            for i in range(n_segments)
        ])

        unique_hit_joints = list({id(j): j for _, j in intersections}.values())
        unique_hit_joint_ids = [id(j) for j in unique_hit_joints]

        return {
            'x': np.arange(x_start, x_end) * self.domain.dx,
            'borehole_name': self.BH_NAMES[bh_idx] if bh_idx < 3 else f'BH-{bh_idx}',

            # 기존 호환용
            # practice mode에서는 기계적 파쇄/미세절리/회수율 보정이 반영될 수 있음.
            # pure mode에서는 RQD_borehole_direct와 사실상 동일해짐.
            'RQD': rqd_arr,

            'Jn': jn_arr,
            'Jr': jr_arr,
            'Ja': ja_arr,
            'Jw': jw_arr,
            'SRF': srf_arr,
            'Q': q_arr,
            'Qprime': qp_arr,

            # ============================================================
            # RQD 방법 비교용 신규 컬럼
            # ============================================================
            'RQD_borehole_direct': rqd_borehole_direct_arr,
            'lambda_borehole': lambda_borehole_arr,
            'RQD_borehole_hudson': rqd_borehole_hudson_arr,
            'borehole_n_intersections': borehole_n_intersections_arr,

            # 기존/보조 내부 정보
            '_joint_count': joint_count_arr,
            '_intersections': intersections,
            '_joint_objects': unique_hit_joints,
            '_joint_ids': unique_hit_joint_ids,
            '_joint_ids_set': set(unique_hit_joint_ids),
        }
    
    ##### Delete it later ####
    # # ================================================================
    # # ★ 기계적 코어 파쇄 생성
    # # ================================================================
    # def _generate_mechanical_breaks(self, dfn_intersections: np.ndarray,
    #                                   segment_length: float) -> np.ndarray:
    #     """
    #     절리 교차점 근처에서 기계적 파쇄 생성

    #     현실:
    #     - 시추 진동으로 절리면 근처 암석이 추가 파손
    #     - 응력 해방으로 기존 미세균열 활성화
    #     - 특히 Ja가 높은(약한) 절리 근처에서 빈번
    #     """
    #     if len(dfn_intersections) == 0:
    #         return np.array([])

    #     breaks = []
    #     for t in dfn_intersections:
    #         # 각 DFN 절리 교차점에서 확률적 추가 파쇄
    #         if self.rng.random() < self.MECHANICAL_BREAK_PROB:
    #             # 절리 앞뒤로 ~3cm 위치에서 추가 파쇄
    #             offset = abs(self.rng.normal(
    #                 self.MECHANICAL_BREAK_OFFSET_MEAN,
    #                 self.MECHANICAL_BREAK_OFFSET_STD
    #             ))
    #             # 앞쪽 또는 뒤쪽
    #             if self.rng.random() < 0.5:
    #                 breaks.append(t - offset)
    #             else:
    #                 breaks.append(t + offset)

    #             # 양쪽 다 파쇄될 수도 있음 (심한 경우)
    #             if self.rng.random() < 0.3:
    #                 offset2 = abs(self.rng.normal(0.05, 0.02))
    #                 breaks.append(t + offset2 if breaks[-1] < t else t - offset2)

    #     return np.array(breaks) if breaks else np.array([])

    # # ================================================================
    # # ★ 미세절리 생성
    # # ================================================================
    # def _generate_micro_fractures(self, n_dfn_hits: int,
    #                                 segment_length: float) -> np.ndarray:
    #     """
    #     DFN에 포함되지 않는 미세절리 생성

    #     현실:
    #     - DFN 최소 반경 = 0.3m → 이보다 작은 절리 미포함
    #     - 실제 코어에는 mm~cm 스케일 불연속면 다수
    #     - 빈도: DFN 절리 수에 비례 (같은 지질환경)
    #     """
    #     # DFN 절리가 많은 구간 = 미세절리도 많은 구간
    #     n_micro = self.rng.poisson(
    #         max(n_dfn_hits * self.MICRO_FRACTURE_MULTIPLIER, 0.5)
    #     )

    #     if n_micro == 0:
    #         return np.array([])

    #     # 균일 분포로 위치 생성
    #     return self.rng.uniform(0, segment_length, n_micro)

    # # ================================================================
    # # ★ 코어 회수율 계산
    # # ================================================================
    # def _calc_core_recovery(self, n_breaks: int,
    #                          segment_length: float) -> float:
    #     """
    #     절리 밀집도에 따른 코어 회수율

    #     현실:
    #     - 절리 밀집 → 코어 붕괴 → 회수율 감소
    #     - 미회수 구간은 RQD 0으로 처리
    #     - TCR 80% → RQD에 0.8 곱함
    #     """
    #     linear_freq = n_breaks / segment_length
    #     recovery = self.CORE_RECOVERY_BASE - self.CORE_RECOVERY_DECAY * linear_freq
    #     return np.clip(recovery, 0.2, 1.0)  # 최소 20%

    # ================================================================
    # 막장면 샘플링 — DFN 직접 교차 (2D) + 현실 보정
    # ================================================================
    # ================================================================
    # 막장면 샘플링 — 현실적 중앙 수평 scanline + Jv 기반 RQD
    # ================================================================
    def sample_face(self, x_idx: int,
                    n_scanlines: int = 8,
                    scan_length: float = None) -> Dict:
        """
        터널 막장면 샘플링.

        수정 후 원칙:
        - 굴진면 RQD는 노출된 face 위에서만 계산한다.
        - x방향, 즉 굴진 방향 scanline은 사용하지 않는다.
        - multi-direction scanline 평균은 사용하지 않는다.
        - 중앙부 수평 y방향 scanline 하나만 사용한다.
        - 별도로 Jv 기반 RQD를 계산해 face volumetric reference로 저장한다.

        n_scanlines, scan_length는 기존 호출부 호환을 위해 남겨두지만,
        더 이상 multi-direction scanline에는 사용하지 않는다.
        """
        face_x = (x_idx + 0.5) * self.domain.dx

        # ------------------------------------------------------------
        # 1. 막장면과 교차 또는 근접 노출되는 절리 찾기
        # ------------------------------------------------------------
        face_joints = self._find_joints_intersecting_face(face_x)

        # ------------------------------------------------------------
        # 2. Method 3: 굴진면 중앙 수평 scanline RQD
        # ------------------------------------------------------------
        # scanline:
        #   x = face_x
        #   y = center_y - R ~ center_y + R
        #   z = center_z
        #   direction = [0, 1, 0]
        #
        # 절대 x방향 scanline을 사용하지 않는다.
        # ------------------------------------------------------------
        face_scan = self.rqd_calculator.rqd_at_face_horizontal_scanline(
            face_x=face_x,
            tunnel_radius=self.radius,
            y_center=self.center_y,
            z_center=self.center_z,
            threshold=0.1,
        )

        rqd_face_scanline = float(face_scan["RQD_face_scanline"])
        lambda_face_scanline = float(face_scan["lambda_face_scanline"])
        rqd_face_scanline_hudson = float(face_scan["RQD_face_scanline_hudson"])
        face_scanline_n_intersections = int(face_scan["face_scanline_n_intersections"])

        # ------------------------------------------------------------
        # 3. Method 4: Jv 기반 RQD
        # ------------------------------------------------------------
        # 현재는 joint set 정의에서 global Jv 또는 P32-derived Jv_proxy를 계산한다.
        # density_type == P32인 case에서는 엄밀한 현장 Jv라기보다는
        # P32-derived Jv proxy로 해석해야 한다.
        # ------------------------------------------------------------
        jv_info = RQDCalculator.calc_jv_proxy_from_joint_sets(
            self.case.joint_config.joint_sets,
            prefer_p32=True,
        )

        jv_face = float(jv_info["jv"])
        jv_method = jv_info["method"]
        rqd_face_jv = float(RQDCalculator.calc_from_jv(jv_face))

        # 보수적 face RQD 후보
        rqd_face_conservative = float(min(rqd_face_scanline, rqd_face_jv))

        # ------------------------------------------------------------
        # 4. Face 대표 RQD 설정
        # ------------------------------------------------------------
        # 기존 코드 호환을 위해 sample_face()의 대표 RQD는 scanline RQD로 둔다.
        #
        # 중요:
        #   이 값은 더 이상 multi-direction average가 아니다.
        #   굴진면 중앙 수평 단일 scanline RQD이다.
        # ------------------------------------------------------------
        rqd_reference = rqd_face_scanline

        # ------------------------------------------------------------
        # 5. face에 노출된 절리에서 Jr, Ja 수집
        # ------------------------------------------------------------
        if len(face_joints) > 0:
            jr_raw = np.array([j.Jr for j in face_joints])
            ja_raw = np.array([j.Ja for j in face_joints])

            if self._use_strength_scaling():
                jr_values = np.clip(jr_raw * self.JR_SCALE_FACTOR_FACE, 0.5, 4.0)
                ja_values = np.clip(ja_raw * self.JA_SCALE_FACTOR_FACE, 0.75, 20.0)
            else:
                jr_values = np.clip(jr_raw, 0.5, 4.0)
                ja_values = np.clip(ja_raw, 0.75, 20.0)

            jr_mean = float(np.mean(jr_values))
            ja_mean = float(np.mean(ja_values))
            jr_std = float(np.std(jr_values))
            ja_std = float(np.std(ja_values))
        else:
            global_jr = np.mean([js.Jr_mean for js in self.case.joint_config.joint_sets])
            global_ja = np.mean([js.Ja_mean for js in self.case.joint_config.joint_sets])

            jr_mean = float(global_jr)
            ja_mean = float(global_ja)
            jr_std = 0.0
            ja_std = 0.0
            jr_values = np.array([])
            ja_values = np.array([])

        # ------------------------------------------------------------
        # 6. Jn, Jw, SRF: 터널 단면 평균
        # ------------------------------------------------------------
        cy, cz = self.center_y_idx, self.center_z_idx
        r_cells = self.radius / self.domain.dy

        face_points = []
        jw_list, srf_list = [], []

        for j in range(self.domain.ny):
            for k in range(self.domain.nz):
                if np.sqrt((j - cy) ** 2 + (k - cz) ** 2) <= r_cells:
                    face_points.append((j, k))

                    if x_idx < self.domain.nx:
                        jw_list.append(self.domain.fields['Jw'][x_idx, j, k])
                        srf_list.append(self.domain.fields['SRF'][x_idx, j, k])

        jw_mean = float(np.mean(jw_list)) if jw_list else self.case.joint_config.Jw_mean
        srf_mean = float(np.mean(srf_list)) if srf_list else self.case.joint_config.SRF_mean
        jn_val = self.case.joint_config.Jn

        # ------------------------------------------------------------
        # 7. Q, Qprime 계산
        # ------------------------------------------------------------
        # 기존 호환 대표값은 scanline RQD 기반으로 계산한다.
        # Jv 기반 Qprime도 별도 key로 저장한다.
        # ------------------------------------------------------------
        Q_mean = QCalculator.calc_Q(
            rqd_reference,
            jn_val,
            jr_mean,
            ja_mean,
            jw_mean,
            srf_mean,
        )

        Qp_mean = QCalculator.calc_Qprime(
            rqd_reference,
            jn_val,
            jr_mean,
            ja_mean,
        )

        Q_from_jv = QCalculator.calc_Q(
            rqd_face_jv,
            jn_val,
            jr_mean,
            ja_mean,
            jw_mean,
            srf_mean,
        )

        Qp_from_jv = QCalculator.calc_Qprime(
            rqd_face_jv,
            jn_val,
            jr_mean,
            ja_mean,
        )

        Q_from_conservative = QCalculator.calc_Q(
            rqd_face_conservative,
            jn_val,
            jr_mean,
            ja_mean,
            jw_mean,
            srf_mean,
        )

        Qp_from_conservative = QCalculator.calc_Qprime(
            rqd_face_conservative,
            jn_val,
            jr_mean,
            ja_mean,
        )

        # ------------------------------------------------------------
        # 8. 셀별 배열 생성
        # ------------------------------------------------------------
        n_points = len(face_points)

        rqd_arr = np.full(n_points, rqd_reference)
        jr_arr = np.full(n_points, jr_mean)
        ja_arr = np.full(n_points, ja_mean)
        jn_arr = np.full(n_points, jn_val)
        jw_arr = np.array(jw_list) if jw_list else np.full(n_points, jw_mean)
        srf_arr = np.array(srf_list) if srf_list else np.full(n_points, srf_mean)

        q_arr = np.array([
            QCalculator.calc_Q(
                rqd_arr[i],
                jn_arr[i],
                jr_arr[i],
                ja_arr[i],
                jw_arr[i],
                srf_arr[i],
            )
            for i in range(n_points)
        ])

        qp_arr = np.array([
            QCalculator.calc_Qprime(
                rqd_arr[i],
                jn_arr[i],
                jr_arr[i],
                ja_arr[i],
            )
            for i in range(n_points)
        ])

        # ------------------------------------------------------------
        # 9. 기존 _rqd_by_direction 호환용 구조
        # ------------------------------------------------------------
        # 이제 direction은 단 하나, [0,1,0]뿐이다.
        # ------------------------------------------------------------
        rqd_by_direction_compat = {
            'all_rqd': np.array([rqd_face_scanline]),
            'direction_means': np.array([rqd_face_scanline]),
            'scan_directions': [np.array([0.0, 1.0, 0.0])],
            'n_scanlines_total': 1,
            'method': 'face_single_horizontal_scanline',
        }

        return {
            'x_idx': x_idx,
            'x_coord': face_x,
            'points': face_points,

            # 기존 호환용 대표값
            # 이제 이 RQD는 multi-direction 평균이 아니라
            # 중앙 수평 face scanline RQD이다.
            'RQD': rqd_arr,
            'Jn': jn_arr,
            'Jr': jr_arr,
            'Ja': ja_arr,
            'Jw': jw_arr,
            'SRF': srf_arr,
            'Q': q_arr,
            'Qprime': qp_arr,

            # ========================================================
            # RQD 방법 비교용 신규 key
            # ========================================================
            'RQD_face_scanline': rqd_face_scanline,
            'lambda_face_scanline': lambda_face_scanline,
            'RQD_face_scanline_hudson': rqd_face_scanline_hudson,
            'face_scanline_n_intersections': face_scanline_n_intersections,

            'Jv_face': jv_face,
            'Jv_method': jv_method,
            'Jv_contributions': jv_info.get("contributions", []),
            'RQD_face_jv': rqd_face_jv,

            'RQD_face_conservative': rqd_face_conservative,

            # Q/Qprime의 estimator별 값
            'Q_face_scanline': Q_mean,
            'Qp_face_scanline': Qp_mean,
            'Q_face_jv': Q_from_jv,
            'Qp_face_jv': Qp_from_jv,
            'Q_face_conservative': Q_from_conservative,
            'Qp_face_conservative': Qp_from_conservative,

            # scanline geometry 기록
            'face_scanline_origin': face_scan["origin"],
            'face_scanline_direction': face_scan["direction"],
            'face_scanline_length': face_scan["length"],
            'face_scanline_intersection_positions': face_scan["intersection_positions"],

            'stats': {
                'RQD': {
                    'mean': rqd_reference,
                    'median': rqd_reference,
                    'std': 0.0,
                    'min': rqd_reference,
                    'max': rqd_reference,
                    'n_points': n_points,
                },
                'Jn': {
                    'mean': jn_val,
                    'median': jn_val,
                    'std': 0.0,
                    'min': jn_val,
                    'max': jn_val,
                    'n_points': n_points,
                },
                'Jr': {
                    'mean': jr_mean,
                    'median': jr_mean,
                    'std': jr_std,
                    'min': float(np.min(jr_values)) if len(jr_values) > 0 else jr_mean,
                    'max': float(np.max(jr_values)) if len(jr_values) > 0 else jr_mean,
                    'n_points': n_points,
                },
                'Ja': {
                    'mean': ja_mean,
                    'median': ja_mean,
                    'std': ja_std,
                    'min': float(np.min(ja_values)) if len(ja_values) > 0 else ja_mean,
                    'max': float(np.max(ja_values)) if len(ja_values) > 0 else ja_mean,
                    'n_points': n_points,
                },
                'Jw': {
                    'mean': jw_mean,
                    'median': float(np.median(jw_arr)) if len(jw_arr) > 0 else jw_mean,
                    'std': float(np.std(jw_arr)) if len(jw_arr) > 0 else 0.0,
                    'min': float(np.min(jw_arr)) if len(jw_arr) > 0 else jw_mean,
                    'max': float(np.max(jw_arr)) if len(jw_arr) > 0 else jw_mean,
                    'n_points': n_points,
                },
                'SRF': {
                    'mean': srf_mean,
                    'median': float(np.median(srf_arr)) if len(srf_arr) > 0 else srf_mean,
                    'std': float(np.std(srf_arr)) if len(srf_arr) > 0 else 0.0,
                    'min': float(np.min(srf_arr)) if len(srf_arr) > 0 else srf_mean,
                    'max': float(np.max(srf_arr)) if len(srf_arr) > 0 else srf_mean,
                    'n_points': n_points,
                },
                'Q': {
                    'mean': float(np.mean(q_arr)) if len(q_arr) > 0 else Q_mean,
                    'median': float(np.median(q_arr)) if len(q_arr) > 0 else Q_mean,
                    'std': float(np.std(q_arr)) if len(q_arr) > 0 else 0.0,
                    'min': float(np.min(q_arr)) if len(q_arr) > 0 else Q_mean,
                    'max': float(np.max(q_arr)) if len(q_arr) > 0 else Q_mean,
                    'n_points': n_points,
                },
                'Qprime': {
                    'mean': float(np.mean(qp_arr)) if len(qp_arr) > 0 else Qp_mean,
                    'median': float(np.median(qp_arr)) if len(qp_arr) > 0 else Qp_mean,
                    'std': float(np.std(qp_arr)) if len(qp_arr) > 0 else 0.0,
                    'min': float(np.min(qp_arr)) if len(qp_arr) > 0 else Qp_mean,
                    'max': float(np.max(qp_arr)) if len(qp_arr) > 0 else Qp_mean,
                    'n_points': n_points,
                },
            },

            # 기존 내부 호환 key
            '_face_joints_count': len(face_joints),
            '_rqd_by_direction': rqd_by_direction_compat,
            '_rqd_mean': rqd_face_scanline,
            '_rqd_min_direction': rqd_face_scanline,
            '_rqd_practical': rqd_face_scanline,
            '_face_joints': face_joints,
            '_face_joint_ids': [id(j) for j in face_joints],
            '_face_joint_ids_set': set(id(j) for j in face_joints),

            # 신규 내부 key
            '_RQD_face_scanline': rqd_face_scanline,
            '_lambda_face_scanline': lambda_face_scanline,
            '_RQD_face_scanline_hudson': rqd_face_scanline_hudson,
            '_face_scanline_n_intersections': face_scanline_n_intersections,
            '_Jv_face': jv_face,
            '_Jv_method': jv_method,
            '_RQD_face_jv': rqd_face_jv,
            '_RQD_face_conservative': rqd_face_conservative,
            '_Qp_face_scanline': Qp_mean,
            '_Qp_face_jv': Qp_from_jv,
            '_Qp_face_conservative': Qp_from_conservative,
        }

    # ================================================================
    # 내부: 다방향 스캔라인 RQD (미세절리 포함)
    # ================================================================
    # ================================================================
    # 내부: 기존 다방향 face RQD 함수의 legacy wrapper
    # ================================================================
    def _multi_direction_face_rqd(self, face_x: float,
                                  n_scanlines: int = 8,
                                  scan_length: float = 10.0) -> Dict:
        """
        Legacy wrapper.

        기존 구현은 막장면에서 여러 방향 scanline을 평균하고,
        심지어 x방향, 즉 굴진 방향 scanline까지 포함했다.

        수정 후 원칙:
        - face에서는 x방향 scanline 금지
        - multi-direction 평균 금지
        - 중앙 수평 y방향 scanline 하나만 사용

        따라서 이 함수가 호출되더라도 중앙 수평 scanline 결과만 반환한다.
        """
        face_scan = self.rqd_calculator.rqd_at_face_horizontal_scanline(
            face_x=face_x,
            tunnel_radius=self.radius,
            y_center=self.center_y,
            z_center=self.center_z,
            threshold=0.1,
        )

        rqd_val = float(face_scan["RQD_face_scanline"])

        return {
            'all_rqd': np.array([rqd_val]),
            'direction_means': np.array([rqd_val]),
            'scan_directions': [np.array([0.0, 1.0, 0.0])],
            'n_scanlines_total': 1,
            'method': 'legacy_wrapper_single_horizontal_face_scanline',
            'lambda_face_scanline': float(face_scan["lambda_face_scanline"]),
            'RQD_face_scanline_hudson': float(face_scan["RQD_face_scanline_hudson"]),
            'face_scanline_n_intersections': int(face_scan["face_scanline_n_intersections"]),
            'intersection_positions': face_scan["intersection_positions"],
        }

    # ================================================================
    # 내부: 막장면-절리 교차 탐색 (기존과 동일)
    # ================================================================
    def _find_joints_intersecting_face(self, face_x: float) -> list:
        """막장면(y-z 평면)과 교차하는 절리 탐색"""
        face_joints = []
        obs_depth = self.FACE_OBSERVATION_DEPTH

        for joint in self.dfn.joints:
            c = joint.center
            n = joint.normal
            r = joint.radius

            if abs(c[0] - face_x) > r + obs_depth:
                continue

            if abs(n[0]) < 1e-10:
                if abs(c[0] - face_x) <= r:
                    dy = c[1] - self.center_y
                    dz = c[2] - self.center_z
                    dist_to_tunnel = np.sqrt(dy**2 + dz**2)
                    if dist_to_tunnel <= self.radius + r:
                        face_joints.append(joint)
            else:
                x_dist = abs(c[0] - face_x)
                if x_dist <= r:
                    dy = c[1] - self.center_y
                    dz = c[2] - self.center_z
                    dist_to_tunnel = np.sqrt(dy**2 + dz**2)
                    if dist_to_tunnel <= self.radius + r:
                        face_joints.append(joint)

        return face_joints

    # ================================================================
    # 내부 유틸리티
    # ================================================================
    def _generate_mechanical_breaks(self, dfn_intersections, segment_length):
        """절리 교차점 근처에서 기계적 파쇄 생성"""
        if len(dfn_intersections) == 0:
            return np.array([])
        breaks = []
        for t in dfn_intersections:
            if self.rng.random() < self.MECHANICAL_BREAK_PROB:
                offset = abs(self.rng.normal(
                    self.MECHANICAL_BREAK_OFFSET_MEAN,
                    self.MECHANICAL_BREAK_OFFSET_STD
                ))
                if self.rng.random() < 0.5:
                    breaks.append(t - offset)
                else:
                    breaks.append(t + offset)
                if self.rng.random() < 0.3:
                    offset2 = abs(self.rng.normal(0.05, 0.02))
                    breaks.append(t + offset2 if breaks[-1] < t else t - offset2)
        return np.array(breaks) if breaks else np.array([])

    def _generate_micro_fractures(self, n_dfn_hits, segment_length):
        """DFN 미포함 미세절리 생성"""
        n_micro = self.rng.poisson(
            max(n_dfn_hits * self.MICRO_FRACTURE_MULTIPLIER, 0.5)
        )
        if n_micro == 0:
            return np.array([])
        return self.rng.uniform(0, segment_length, n_micro)

    def _calc_core_recovery(self, n_breaks, segment_length):
        """절리 밀집도에 따른 코어 회수율"""
        linear_freq = n_breaks / segment_length
        recovery = self.CORE_RECOVERY_BASE - self.CORE_RECOVERY_DECAY * linear_freq
        return np.clip(recovery, 0.2, 1.0)

    def _empty_borehole_result(self, bh_idx, x_start, x_end):
        """빈 시추공 결과"""
        return {
            'x': np.array([]),
            'borehole_name': self.BH_NAMES[bh_idx] if bh_idx < 3 else f'BH-{bh_idx}',

            'RQD': np.array([]),
            'Jn': np.array([]),
            'Jr': np.array([]),
            'Ja': np.array([]),
            'Jw': np.array([]),
            'SRF': np.array([]),
            'Q': np.array([]),
            'Qprime': np.array([]),

            # RQD 방법 비교용 빈 배열
            'RQD_borehole_direct': np.array([]),
            'lambda_borehole': np.array([]),
            'RQD_borehole_hudson': np.array([]),
            'borehole_n_intersections': np.array([], dtype=int),
        }
    
    # ================================================================
    # 기존 호환 (비교 검증용)
    # ================================================================
    def sample_borehole_grid(self, bh_idx, x_start, x_end):
        """[기존 방식] 격자값 읽기"""
        y_idx, z_idx = self.borehole_positions[bh_idx]
        x_indices = np.arange(x_start, x_end)
        result = {
            'x': x_indices * self.domain.dx,
            'borehole_name': self.BH_NAMES[bh_idx] if bh_idx < 3 else f'BH-{bh_idx}',
        }
        for name in self.domain.fields:
            result[name] = self.domain.fields[name][x_start:x_end, y_idx, z_idx]
        result['Q'] = self.domain.Q_field[x_start:x_end, y_idx, z_idx]
        result['Qprime'] = self.domain.Qprime_field[x_start:x_end, y_idx, z_idx]
        return result

    def sample_face_grid(self, x_idx):
        """[기존 방식] 격자값 읽기"""
        cy, cz = self.center_y_idx, self.center_z_idx
        r_cells = self.radius / self.domain.dy
        face_points = []
        for j in range(self.domain.ny):
            for k in range(self.domain.nz):
                if np.sqrt((j - cy)**2 + (k - cz)**2) <= r_cells:
                    face_points.append((j, k))
        data = {name: [] for name in self.domain.fields}
        data['Q'], data['Qprime'], data['points'] = [], [], face_points
        for j, k in face_points:
            for name in self.domain.fields:
                data[name].append(self.domain.fields[name][x_idx, j, k])
            data['Q'].append(self.domain.Q_field[x_idx, j, k])
            data['Qprime'].append(self.domain.Qprime_field[x_idx, j, k])
        for key in data:
            if key != 'points':
                data[key] = np.array(data[key])
        data['stats'] = {}
        for key in ['RQD', 'Jn', 'Jr', 'Ja', 'Jw', 'SRF', 'Q', 'Qprime']:
            arr = data[key]
            data['stats'][key] = {
                'mean': float(np.mean(arr)), 'median': float(np.median(arr)),
                'std': float(np.std(arr)), 'min': float(np.min(arr)),
                'max': float(np.max(arr)), 'n_points': len(arr),
            }
        data['x_idx'] = x_idx
        data['x_coord'] = x_idx * self.domain.dx
        return data


