"""
RQD 계산기
- 직접법 (Deere 정의)
- 이론식 (Priest-Hudson, 1976)
- 방향별 RQD (시추공/막장면 전용)
"""

import numpy as np
from typing import List, Tuple, Dict, Optional


class RQDCalculator:
    """RQD 계산 (정적 메서드 모음)"""

    @staticmethod
    def calc_direct(intersection_distances: List[float],
                    total_length: float,
                    threshold: float = 0.1) -> float:
        """
        Deere 직접 정의:
        RQD = Σ(코어길이 ≥ threshold) / total_length × 100
        """
        if total_length <= 0:
            return 0.0
        if len(intersection_distances) == 0:
            return 100.0

        points = [0.0] + sorted(intersection_distances) + [total_length]
        sum_intact = 0.0
        for i in range(len(points) - 1):
            spacing = points[i + 1] - points[i]
            if spacing >= threshold:
                sum_intact += spacing
        return np.clip((sum_intact / total_length) * 100.0, 0, 100)

    @staticmethod
    def calc_theoretical(linear_frequency: float,
                         threshold: float = 0.1) -> float:
        """
        Priest & Hudson (1976):
        RQD = 100 × exp(-λt) × (λt + 1)
        """
        lt = linear_frequency * threshold
        return np.clip(100.0 * np.exp(-lt) * (lt + 1.0), 0, 100)

    @staticmethod
    def calc_apparent_frequency(joint_normal: np.ndarray,
                                true_spacing: float,
                                scanline_direction: np.ndarray) -> float:
        """
        겉보기 선형빈도:
        λ_app = |cos α| / spacing
        α = 법선과 스캔라인의 각도
        """
        cos_alpha = abs(np.dot(
            joint_normal / np.linalg.norm(joint_normal),
            scanline_direction / np.linalg.norm(scanline_direction)
        ))
        return cos_alpha / true_spacing


class DirectionalRQDCalculator:
    """시추공(1D) 및 막장면(2D) 방향별 RQD 계산"""

    def __init__(self, dfn):
        self.dfn = dfn

    def rqd_along_borehole(self,
                            origin: np.ndarray,
                            direction: np.ndarray,
                            length: float,
                            window: float = 1.0,
                            step: float = 1.0
                            ) -> Tuple[np.ndarray, np.ndarray]:
        """이동 윈도우 방식 시추공 RQD"""
        direction = direction / np.linalg.norm(direction)
        all_ix = self.dfn.get_joints_intersecting_line(origin, direction, length)
        t_values = np.array([t for t, _ in all_ix])

        positions = np.arange(0, length - window + step, step)
        rqd_values = np.zeros(len(positions))

        for idx, pos in enumerate(positions):
            mask = (t_values >= pos) & (t_values < pos + window)
            window_t = (t_values[mask] - pos).tolist()
            rqd_values[idx] = RQDCalculator.calc_direct(window_t, window)

        return positions, rqd_values

    def rqd_at_face(self,
                     face_x: float,
                     y_range: Tuple[float, float],
                     z_range: Tuple[float, float],
                     grid_spacing: float = 1.0,
                     scan_length: float = 3.0
                     ) -> Dict:
        """막장면(2D)에서의 RQD 분포 (다방향 스캔)"""
        scan_dirs = [
            np.array([1, 0, 0]),
            np.array([0, 1, 0]),
            np.array([0, 0, 1]),
            np.array([0, 1, 1]) / np.sqrt(2),
            np.array([0, 1, -1]) / np.sqrt(2),
        ]

        y_pts = np.arange(y_range[0], y_range[1], grid_spacing)
        z_pts = np.arange(z_range[0], z_range[1], grid_spacing)
        rqd_map = np.zeros((len(y_pts), len(z_pts)))
        rqd_by_dir = np.zeros((len(y_pts), len(z_pts), len(scan_dirs)))

        for iy, y in enumerate(y_pts):
            for iz, z in enumerate(z_pts):
                pt = np.array([face_x, y, z])
                for idir, d in enumerate(scan_dirs):
                    origin = pt - (scan_length / 2) * d
                    ix = self.dfn.get_joints_intersecting_line(origin, d, scan_length)
                    t_vals = [t for t, _ in ix]
                    rqd_by_dir[iy, iz, idir] = RQDCalculator.calc_direct(t_vals, scan_length)
                rqd_map[iy, iz] = np.mean(rqd_by_dir[iy, iz, :])

        return {
            'y_points': y_pts, 'z_points': z_pts,
            'rqd_map': rqd_map, 'rqd_by_direction': rqd_by_dir,
            'rqd_mean': float(np.mean(rqd_map)),
            'rqd_std': float(np.std(rqd_map)),
            'face_x': face_x,
        }