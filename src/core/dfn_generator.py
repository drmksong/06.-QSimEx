"""
DFN (Discrete Fracture Network) 생성기
- Power Law 크기 + Fisher 방향 + Poisson 밀도
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from .joint_models import (
    Joint,
    JointSetDefinition,
    DomainJointConfig,
    PowerLawSampler,
    FisherDistribution,
)


class DiscreteFractureNetwork:
    """
    3D DFN 생성기

    절리군별 생성 과정:
      1. N = P32 × V / E[πr²]  (Poisson)
      2. r ~ PowerLaw(α, r_min, r_max)
      3. n̂ ~ Fisher(mean_normal, κ)
      4. center ~ Uniform(domain + buffer)
      5. Jr ~ N(μ, σ),  Ja ~ N(μ, σ)
    """

    def __init__(
        self,
        config: DomainJointConfig,
        domain_size: Tuple[float, float, float] = (100, 50, 50),
        seed: int = 42,
    ):
        self.config = config
        self.Lx, self.Ly, self.Lz = domain_size
        self.rng = np.random.RandomState(seed)
        self.joints: List[Joint] = []
        self.joints_by_set: Dict[int, List[Joint]] = {}
        self._generated: bool = False

        # cached numpy arrays (filled after generation)
        # initialize as empty arrays to avoid Optional/None typing issues in editors
        self._centers: np.ndarray = np.empty((0, 3), dtype=np.float32)
        self._normals: np.ndarray = np.empty((0, 3), dtype=np.float32)
        self._radii: np.ndarray = np.empty((0,), dtype=np.float32)
        self._jr: np.ndarray = np.empty((0,), dtype=np.float32)
        self._ja: np.ndarray = np.empty((0,), dtype=np.float32)
        self._set_ids: np.ndarray = np.empty((0,), dtype=np.int32)

        # 공간 인덱스
        self._x_bins: List[np.ndarray] = []
        self._bin_size: float = 0.0

    def generate(self, verbose: bool = True):
        """전체 DFN 생성"""
        self.joints = []
        self.joints_by_set = {}
        domain_volume = self.Lx * self.Ly * self.Lz

        if verbose:
            print(
                f"  도메인: {self.Lx}×{self.Ly}×{self.Lz}m "
                f"(V={domain_volume:.0f}m³)"
            )

        for js in self.config.joint_sets:
            # Power Law 샘플러
            pl = PowerLawSampler(js.size_alpha, js.size_r_min, js.size_r_max)
            mean_area = js.expected_mean_area()

            # 절리 개수
            if js.density_type == "P32":
                n_expected = js.P32 * domain_volume / mean_area
            else:
                n_expected = domain_volume / (js.mean_spacing * mean_area)
            n_expected = max(int(n_expected), 5)
            n_joints = max(self.rng.poisson(n_expected), 1)

            if verbose:
                print(f"\n  ── JS-{js.set_id}: {js.name} ──")
                print(f"     크기: {pl.summary()}")
                print(
                    f"     방향: dip={js.mean_dip}°/{js.mean_dip_dir}° κ={js.fisher_kappa}"
                )
                print(f"     N_expected={n_expected}, N_gen={n_joints}")

            # 크기 (Power Law)
            radii = pl.sample(n_joints, self.rng)

            # 방향 (Fisher)
            mean_normal = js.mean_normal_vector()
            normals = FisherDistribution.sample(
                mean_normal, js.fisher_kappa, n_joints, self.rng
            )

            # 위치 (Uniform + 버퍼)
            buffer = float(np.percentile(radii, 90))
            centers = np.column_stack(
                [
                    self.rng.uniform(-buffer, self.Lx + buffer, n_joints),
                    self.rng.uniform(-buffer, self.Ly + buffer, n_joints),
                    self.rng.uniform(-buffer, self.Lz + buffer, n_joints),
                ]
            )

            # Jr, Ja (정규분포)
            Jr_vals = np.clip(
                self.rng.normal(js.Jr_mean, js.Jr_std, n_joints), 0.5, 4.0
            )
            Ja_vals = np.clip(
                self.rng.normal(js.Ja_mean, js.Ja_std, n_joints), 0.75, 20.0
            )

            set_joints = []
            for i in range(n_joints):
                j = Joint(
                    center=centers[i],
                    normal=normals[i],
                    radius=radii[i],
                    set_id=js.set_id,
                    Jr=Jr_vals[i],
                    Ja=Ja_vals[i],
                )
                self.joints.append(j)
                set_joints.append(j)
            self.joints_by_set[js.set_id] = set_joints

            if verbose:
                print(
                    f"     반경: mean={radii.mean():.2f}m, "
                    f"range=[{radii.min():.2f},{radii.max():.2f}]m"
                )

        self._generated = True
        if verbose:
            print(
                f"\n  ✅ DFN 완료: 총 {len(self.joints)}개 절리 "
                f"({self.config.n_sets}개 절리군)"
            )

        self._build_array_cache()
        self._build_spatial_index(bin_size=2.0)

    def get_joints_intersecting_line(
        self, line_origin: np.ndarray, line_direction: np.ndarray, line_length: float
    ) -> List[Tuple[float, Joint]]:
        """직선(시추공/스캔라인)과 교차하는 절리 탐색"""
        if self._centers is not None and self._x_bins is not None:
            return self.get_joints_intersecting_line_fast(
                line_origin, line_direction, line_length
            )

        # fallback: 기존 방식
        line_direction = line_direction / np.linalg.norm(line_direction)
        intersections = []

        for joint in self.joints:
            n = joint.normal
            d_dot_n = np.dot(line_direction, n)
            if abs(d_dot_n) < 1e-10:
                continue
            t = np.dot(n, joint.center - line_origin) / d_dot_n
            if t < 0 or t > line_length:
                continue
            pt = line_origin + t * line_direction
            if np.linalg.norm(pt - joint.center) <= joint.radius:
                intersections.append((t, joint))

        intersections.sort(key=lambda x: x[0])
        return intersections

    def statistics(self) -> Dict:
        """DFN 통계 요약"""
        result = {
            "total_joints": len(self.joints),
            "n_sets": self.config.n_sets,
            "by_set": {},
        }
        for sid, joints in self.joints_by_set.items():
            radii = np.array([j.radius for j in joints])
            result["by_set"][sid] = {
                "count": len(joints),
                "radius_mean": float(radii.mean()),
                "radius_median": float(np.median(radii)),
                "radius_std": float(radii.std()),
                "radius_min": float(radii.min()),
                "radius_max": float(radii.max()),
            }
        return result

    def _build_array_cache(self):
        """절리 객체 리스트 → NumPy 배열 캐시"""
        n = len(self.joints)
        self._centers = np.array([j.center for j in self.joints], dtype=np.float32)
        self._normals = np.array([j.normal for j in self.joints], dtype=np.float32)
        self._radii = np.array([j.radius for j in self.joints], dtype=np.float32)
        self._jr = np.array([j.Jr for j in self.joints], dtype=np.float32)
        self._ja = np.array([j.Ja for j in self.joints], dtype=np.float32)
        self._set_ids = np.array([j.set_id for j in self.joints], dtype=np.int32)

    def _build_spatial_index(self, bin_size=2.0):
        """
        x축 bin 인덱스 구축
        각 절리를 center_x ± radius 범위의 bin에 등록
        """
        # ensure array cache is built
        assert (
            self._centers is not None and self._radii is not None
        ), "_build_array_cache must be called before _build_spatial_index"

        self._bin_size = float(bin_size)
        n_bins = int(np.ceil(self.Lx / self._bin_size)) + 2

        # build as native Python lists first (avoid assigning list[list] to typed attribute)
        bins: List[list] = [[] for _ in range(n_bins)]

        cx = self._centers[:, 0]
        r = self._radii

        x_min = np.clip(cx - r, 0.0, self.Lx)
        x_max = np.clip(cx + r, 0.0, self.Lx)

        b0 = np.floor(x_min / self._bin_size).astype(int)
        b1 = np.floor(x_max / self._bin_size).astype(int)

        for idx in range(len(self.joints)):
            for b in range(b0[idx], b1[idx] + 1):
                bins[b].append(idx)

        # convert to list of numpy arrays and assign to typed attribute
        self._x_bins = [
            (
                np.array(bin_list, dtype=np.int32)
                if len(bin_list) > 0
                else np.empty(0, dtype=np.int32)
            )
            for bin_list in bins
        ]

    def _get_candidate_indices_for_line(
        self, line_origin, line_direction, line_length, pad=0.0
    ):
        """
        line의 x 범위를 기준으로 후보 절리 인덱스 추출
        """
        d = line_direction / np.linalg.norm(line_direction)
        x0 = line_origin[0]
        x1 = line_origin[0] + line_length * d[0]

        xmin = min(x0, x1) - pad
        xmax = max(x0, x1) + pad

        # d[0]가 0인 y-z 평면 방향 스캔의 경우에도
        # line_origin x 근처만 보면 됨
        if abs(d[0]) < 1e-10:
            xmin = x0 - pad
            xmax = x0 + pad

        xmin = np.clip(xmin, 0.0, self.Lx)
        xmax = np.clip(xmax, 0.0, self.Lx)

        b0 = int(np.floor(xmin / self._bin_size))
        b1 = int(np.floor(xmax / self._bin_size))

        if b1 < b0:
            b0, b1 = b1, b0

        if b0 == b1:
            return self._x_bins[b0]

        candidates = np.concatenate([self._x_bins[b] for b in range(b0, b1 + 1)])
        if candidates.size == 0:
            return candidates

        return np.unique(candidates)

    def get_joints_intersecting_line_fast(
        self, line_origin: np.ndarray, line_direction: np.ndarray, line_length: float
    ) -> List[Tuple[float, Joint]]:
        """
        공간 인덱스 + NumPy 벡터화 기반 직선-절리 교차 계산
        """
        d = line_direction / np.linalg.norm(line_direction)

        # 후보 절리 조회
        pad = float(np.percentile(self._radii, 95)) if self._radii is not None else 2.0
        cand_idx = self._get_candidate_indices_for_line(
            line_origin, d, line_length, pad=pad
        )

        if cand_idx.size == 0:
            return []

        centers = self._centers[cand_idx]  # (M, 3)
        normals = self._normals[cand_idx]  # (M, 3)
        radii = self._radii[cand_idx]  # (M,)

        d_dot_n = normals @ d
        valid = np.abs(d_dot_n) > 1e-10
        if not np.any(valid):
            return []

        centers = centers[valid]
        normals = normals[valid]
        radii = radii[valid]
        cand_idx = cand_idx[valid]
        d_dot_n = d_dot_n[valid]

        # t = n·(c - o) / (d·n)
        t = np.sum(normals * (centers - line_origin), axis=1) / d_dot_n
        valid_t = (t >= 0.0) & (t <= line_length)
        if not np.any(valid_t):
            return []

        centers = centers[valid_t]
        radii = radii[valid_t]
        cand_idx = cand_idx[valid_t]
        t = t[valid_t]

        pts = line_origin[None, :] + t[:, None] * d[None, :]
        dist_sq = np.sum((pts - centers) ** 2, axis=1)
        hit = dist_sq <= (radii**2)

        if not np.any(hit):
            return []

        t = t[hit]
        cand_idx = cand_idx[hit]

        order = np.argsort(t)
        return [(float(t[i]), self.joints[cand_idx[i]]) for i in order]
