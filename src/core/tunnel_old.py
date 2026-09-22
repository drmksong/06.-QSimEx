"""
터널 기하학, 시추공 샘플링, 막장면 샘플링

★ 수정: 격자값 읽기 → DFN 직접 교차 기반 샘플링
  - 시추공: 1D 라인(5cm 직경) × DFN → 방향 편향 + 소규모 샘플링
  - 막장면: 2D 원형면(10m) × DFN → 다방향 스캔 + 대규모 샘플링
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from .domain import RockDomain
from .q_calculator import QCalculator
from .rqd_calculator import RQDCalculator
from .q_calculator import QCalculator

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
            'RQD': rqd_arr,
            'Jn': jn_arr,
            'Jr': jr_arr,
            'Ja': ja_arr,
            'Jw': jw_arr,
            'SRF': srf_arr,
            'Q': q_arr,
            'Qprime': qp_arr,
            '_joint_count': joint_count_arr,
            '_intersections': intersections,
            '_joint_objects': unique_hit_joints,
            '_joint_ids': unique_hit_joint_ids,
            '_joint_ids_set': set(unique_hit_joint_ids),
        }
    # ================================================================
    # ★ 기계적 코어 파쇄 생성
    # ================================================================
    def _generate_mechanical_breaks(self, dfn_intersections: np.ndarray,
                                      segment_length: float) -> np.ndarray:
        """
        절리 교차점 근처에서 기계적 파쇄 생성

        현실:
        - 시추 진동으로 절리면 근처 암석이 추가 파손
        - 응력 해방으로 기존 미세균열 활성화
        - 특히 Ja가 높은(약한) 절리 근처에서 빈번
        """
        if len(dfn_intersections) == 0:
            return np.array([])

        breaks = []
        for t in dfn_intersections:
            # 각 DFN 절리 교차점에서 확률적 추가 파쇄
            if self.rng.random() < self.MECHANICAL_BREAK_PROB:
                # 절리 앞뒤로 ~3cm 위치에서 추가 파쇄
                offset = abs(self.rng.normal(
                    self.MECHANICAL_BREAK_OFFSET_MEAN,
                    self.MECHANICAL_BREAK_OFFSET_STD
                ))
                # 앞쪽 또는 뒤쪽
                if self.rng.random() < 0.5:
                    breaks.append(t - offset)
                else:
                    breaks.append(t + offset)

                # 양쪽 다 파쇄될 수도 있음 (심한 경우)
                if self.rng.random() < 0.3:
                    offset2 = abs(self.rng.normal(0.05, 0.02))
                    breaks.append(t + offset2 if breaks[-1] < t else t - offset2)

        return np.array(breaks) if breaks else np.array([])

    # ================================================================
    # ★ 미세절리 생성
    # ================================================================
    def _generate_micro_fractures(self, n_dfn_hits: int,
                                    segment_length: float) -> np.ndarray:
        """
        DFN에 포함되지 않는 미세절리 생성

        현실:
        - DFN 최소 반경 = 0.3m → 이보다 작은 절리 미포함
        - 실제 코어에는 mm~cm 스케일 불연속면 다수
        - 빈도: DFN 절리 수에 비례 (같은 지질환경)
        """
        # DFN 절리가 많은 구간 = 미세절리도 많은 구간
        n_micro = self.rng.poisson(
            max(n_dfn_hits * self.MICRO_FRACTURE_MULTIPLIER, 0.5)
        )

        if n_micro == 0:
            return np.array([])

        # 균일 분포로 위치 생성
        return self.rng.uniform(0, segment_length, n_micro)

    # ================================================================
    # ★ 코어 회수율 계산
    # ================================================================
    def _calc_core_recovery(self, n_breaks: int,
                             segment_length: float) -> float:
        """
        절리 밀집도에 따른 코어 회수율

        현실:
        - 절리 밀집 → 코어 붕괴 → 회수율 감소
        - 미회수 구간은 RQD 0으로 처리
        - TCR 80% → RQD에 0.8 곱함
        """
        linear_freq = n_breaks / segment_length
        recovery = self.CORE_RECOVERY_BASE - self.CORE_RECOVERY_DECAY * linear_freq
        return np.clip(recovery, 0.2, 1.0)  # 최소 20%

    # ================================================================
    # 막장면 샘플링 — DFN 직접 교차 (2D) + 현실 보정
    # ================================================================
    def sample_face(self, x_idx: int,
                     n_scanlines: int = 8,
                     scan_length: float = None) -> Dict:
        """
        터널 막장면 2D 원형 단면 샘플링 — DFN 직접 교차

        막장면의 현실성:
        - 2D 관찰이므로 미세절리도 관찰 가능
        - 다방향 스캔 → 모든 방향의 절리 포착
        - 지질기사의 보수적 평가 경향
        """
        if scan_length is None:
            scan_length = self.radius * 2

        face_x = (x_idx + 0.5) * self.domain.dx

        # ★ 막장면과 교차하는 절리 찾기
        face_joints = self._find_joints_intersecting_face(face_x)

        # ★ 다방향 스캔라인 RQD (미세절리 포함)
        face_rqd_values = self._multi_direction_face_rqd(
            face_x, n_scanlines, scan_length
        )

        # ★ 면에 노출된 절리에서 Jr, Ja 수집
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
            jr_mean, ja_mean = global_jr, global_ja
            jr_std, ja_std = 0.0, 0.0
            jr_values = np.array([])
            ja_values = np.array([])

        # Jn, Jw, SRF: 터널 단면 평균
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

        # RQD 통계
        rqd_mean = float(np.mean(face_rqd_values['all_rqd']))
        rqd_std = float(np.std(face_rqd_values['all_rqd']))
        rqd_min_dir = float(np.min(face_rqd_values['direction_means']))

        # "가장 불리한 방향" RQD
        if self._use_practical_face_rqd():
            # 기존 practical estimator
            rqd_practical = 0.6 * rqd_mean + 0.4 * rqd_min_dir
        else:
            # pure mode에서는 방향 평균 RQD를 face 대표값으로 사용
            rqd_practical = rqd_mean

        # ★ 막장면 관찰 보정: 지질기사 보수적 평가
        # 실무에서 막장면 RQD는 시추공보다 낮게 평가하는 경향
        if self._use_face_conservatism():
            FACE_CONSERVATISM = 0.95
            rqd_practical *= FACE_CONSERVATISM



        # Q 계산
        Q_mean = QCalculator.calc_Q(rqd_practical, jn_val, jr_mean, ja_mean, jw_mean, srf_mean)
        Qp_mean = QCalculator.calc_Qprime(rqd_practical, jn_val, jr_mean, ja_mean)

        # 셀별 배열
        n_points = len(face_points)
        rqd_arr = np.full(n_points, rqd_practical)
        jr_arr = np.full(n_points, jr_mean)
        ja_arr = np.full(n_points, ja_mean)
        jn_arr = np.full(n_points, jn_val)
        jw_arr = np.array(jw_list) if jw_list else np.full(n_points, jw_mean)
        srf_arr = np.array(srf_list) if srf_list else np.full(n_points, srf_mean)

        q_arr = np.array([
            QCalculator.calc_Q(rqd_arr[i], jn_arr[i], jr_arr[i],
                               ja_arr[i], jw_arr[i], srf_arr[i])
            for i in range(n_points)
        ])
        qp_arr = np.array([
            QCalculator.calc_Qprime(rqd_arr[i], jn_arr[i], jr_arr[i], ja_arr[i])
            for i in range(n_points)
        ])

        return {
            'x_idx': x_idx,
            'x_coord': face_x,
            'points': face_points,
            'RQD': rqd_arr,
            'Jn': jn_arr,
            'Jr': jr_arr,
            'Ja': ja_arr,
            'Jw': jw_arr,
            'SRF': srf_arr,
            'Q': q_arr,
            'Qprime': qp_arr,
            'stats': {
                'RQD': {'mean': rqd_practical, 'median': rqd_practical,
                        'std': rqd_std, 'min': rqd_min_dir,
                        'max': float(np.max(face_rqd_values['all_rqd'])),
                        'n_points': n_points},
                'Jn': {'mean': jn_val, 'median': jn_val,
                       'std': 0.0, 'min': jn_val, 'max': jn_val,
                       'n_points': n_points},
                'Jr': {'mean': jr_mean, 'median': jr_mean,
                       'std': jr_std,
                       'min': float(np.min(jr_values)) if len(jr_values) > 0 else jr_mean,
                       'max': float(np.max(jr_values)) if len(jr_values) > 0 else jr_mean,
                       'n_points': n_points},
                'Ja': {'mean': ja_mean, 'median': ja_mean,
                       'std': ja_std,
                       'min': float(np.min(ja_values)) if len(ja_values) > 0 else ja_mean,
                       'max': float(np.max(ja_values)) if len(ja_values) > 0 else ja_mean,
                       'n_points': n_points},
                'Jw': {'mean': jw_mean, 'median': float(np.median(jw_arr)),
                       'std': float(np.std(jw_arr)), 'min': float(np.min(jw_arr)),
                       'max': float(np.max(jw_arr)), 'n_points': n_points},
                'SRF': {'mean': srf_mean, 'median': float(np.median(srf_arr)),
                        'std': float(np.std(srf_arr)), 'min': float(np.min(srf_arr)),
                        'max': float(np.max(srf_arr)), 'n_points': n_points},
                'Q': {'mean': float(np.mean(q_arr)), 'median': float(np.median(q_arr)),
                      'std': float(np.std(q_arr)), 'min': float(np.min(q_arr)),
                      'max': float(np.max(q_arr)), 'n_points': n_points},
                'Qprime': {'mean': float(np.mean(qp_arr)), 'median': float(np.median(qp_arr)),
                           'std': float(np.std(qp_arr)), 'min': float(np.min(qp_arr)),
                           'max': float(np.max(qp_arr)), 'n_points': n_points},
            },
            '_face_joints_count': len(face_joints),
            '_rqd_by_direction': face_rqd_values,
            '_rqd_mean': rqd_mean,
            '_rqd_min_direction': rqd_min_dir,
            '_rqd_practical': rqd_practical,
            '_face_joints': face_joints,
            '_face_joint_ids': [id(j) for j in face_joints],
            '_face_joint_ids_set': set(id(j) for j in face_joints),            
        }

    # ================================================================
    # 내부: 다방향 스캔라인 RQD (미세절리 포함)
    # ================================================================
    def _multi_direction_face_rqd(self, face_x: float,
                                    n_scanlines: int = 8,
                                    scan_length: float = 10.0) -> Dict:
        """
        막장면에서 다방향 스캔라인 RQD (미세절리 포함)

        막장면에서는:
        - 2D 노출면이므로 미세절리도 육안 관찰 가능
        - 시추공보다 더 많은 절리를 관찰
        - 따라서 미세절리 승수를 높게 적용
        """
        FACE_MICRO_MULTIPLIER = 1.2  # 막장면 미세절리 (시추공보다 관찰↑)

        scan_directions = []
        for i in range(n_scanlines):
            angle = np.pi * i / n_scanlines
            d = np.array([0.0, np.cos(angle), np.sin(angle)])
            scan_directions.append(d)
        scan_directions.append(np.array([1.0, 0.0, 0.0]))

        all_rqd = []
        direction_means = []

        for d_idx, scan_dir in enumerate(scan_directions):
            dir_rqd_values = []
            n_grid = max(3, int(self.radius / 2))

            for iy in range(n_grid):
                for iz in range(n_grid):
                    y_off = -self.radius + (2 * self.radius * (iy + 0.5) / n_grid)
                    z_off = -self.radius + (2 * self.radius * (iz + 0.5) / n_grid)

                    if np.sqrt(y_off**2 + z_off**2) > self.radius * 0.9:
                        continue

                    origin = np.array([
                        face_x - scan_length / 2 * scan_dir[0],
                        self.center_y + y_off - scan_length / 2 * scan_dir[1],
                        self.center_z + z_off - scan_length / 2 * scan_dir[2],
                    ])

                    intersections = self.dfn.get_joints_intersecting_line(
                        origin, scan_dir, scan_length
                    )
                    t_vals_dfn = [t for t, _ in intersections]
                    n_dfn = len(t_vals_dfn)

                    # ★ 막장면 미세절리 추가
                    if self._use_micro_fractures():
                        n_micro = self.rng.poisson(
                            max(n_dfn * FACE_MICRO_MULTIPLIER, 0.5)
                        )
                        micro_t = self.rng.uniform(0, scan_length, n_micro).tolist() if n_micro > 0 else []
                    else:
                        micro_t = []

                    all_t = sorted(t_vals_dfn + micro_t)
                    rqd = RQDCalculator.calc_direct(all_t, scan_length)

                    dir_rqd_values.append(rqd)
                    all_rqd.append(rqd)

            if dir_rqd_values:
                direction_means.append(float(np.mean(dir_rqd_values)))

        return {
            'all_rqd': np.array(all_rqd) if all_rqd else np.array([100.0]),
            'direction_means': np.array(direction_means) if direction_means else np.array([100.0]),
            'scan_directions': scan_directions,
            'n_scanlines_total': len(all_rqd),
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
            'RQD': np.array([]), 'Jn': np.array([]),
            'Jr': np.array([]), 'Ja': np.array([]),
            'Jw': np.array([]), 'SRF': np.array([]),
            'Q': np.array([]), 'Qprime': np.array([]),
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


