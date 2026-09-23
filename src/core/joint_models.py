"""
절리 모델 정의
- JointSetDefinition: 절리군 입력 파라미터
- DomainJointConfig: 도메인 절리 구성
- Joint: 개별 절리 (디스크)
- FisherDistribution: 방향 분포
- PowerLawSampler: 크기 분포
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from scipy.spatial.transform import Rotation


# ================================================================
# 1. 개별 절리 (디스크 모델)
# ================================================================
@dataclass
class Joint:
    """개별 절리 — 원판(Disk) 형상"""
    center: np.ndarray        # 중심점 (x, y, z)
    normal: np.ndarray        # 법선벡터 (단위)
    radius: float             # 반경 (m) — Power Law 샘플링
    set_id: int               # 소속 절리군 ID
    Jr: float = 1.5           # 절리면 거칠기
    Ja: float = 2.0           # 절리면 변질도


# ================================================================
# 2. 절리군 정의
# ================================================================
@dataclass
class JointSetDefinition:
    """
    단일 절리군의 입력 파라미터

    [A] 식별
    [B] 크기 분포 — Power Law: f(r) = C·r^(-α-1), r ∈ [r_min, r_max]
    [C] 방향 분포 — Fisher:    f(θ) ∝ exp(κ cos θ)
    [D] 밀도      — P32 (m²/m³) 또는 평균간격 (m)
    [E] 역학 파라미터 — Jr, Ja (정규분포)
    """
    # [A] 식별
    set_id: int
    name: str = ""

    # [B] 크기 분포 (Power Law)
    size_alpha: float = 3.0       # 멱지수 α (일반적 2.5~4.0)
    size_r_min: float = 0.5       # 최소 반경 (m)
    size_r_max: float = 20.0      # 최대 반경 (m)

    # [C] 방향 분포 (Fisher)
    mean_dip: float = 45.0        # 평균 경사각 (°) [0~90]
    mean_dip_dir: float = 180.0   # 평균 경사방향 (°) [0~360]
    fisher_kappa: float = 20.0    # Fisher 집중도 κ

    # [D] 밀도
    density_type: str = 'P32'     # 'P32' or 'spacing'
    P32: float = 1.0              # 체적 면적밀도 (m²/m³)
    mean_spacing: float = 0.5     # 평균 수직간격 (m)

    # [E] 역학 파라미터 (정규분포)
    Jr_mean: float = 1.5
    Jr_std: float = 0.3
    Ja_mean: float = 2.0
    Ja_std: float = 0.5

    def mean_normal_vector(self) -> np.ndarray:
        """경사/경사방향 → 단위 법선벡터 (x=East, y=North, z=Up)"""
        dip_rad = np.radians(self.mean_dip)
        dd_rad = np.radians(self.mean_dip_dir)
        nx = -np.sin(dip_rad) * np.sin(dd_rad)
        ny = -np.sin(dip_rad) * np.cos(dd_rad)
        nz = np.cos(dip_rad)
        return np.array([nx, ny, nz])

    def expected_mean_area(self) -> float:
        """절리 1개의 기대 면적 E[πr²]"""
        try:
            a = float(self.size_alpha)
            rn = float(self.size_r_min)
            rx = float(self.size_r_max)
        except (TypeError, ValueError):
            return np.pi * 1.0

        if not np.isfinite(a) or not np.isfinite(rn) or not np.isfinite(rx):
            return np.pi * 1.0
        if rn <= 0 or rx <= rn or a <= 0:
            return np.pi * max((0.5 * (rn + rx)), 1.0) ** 2

        ratio_a = (rn / rx) ** a
        norm = 1.0 - ratio_a
        if a <= 2.0 or norm < 1e-15:
            return np.pi * max(((rn + rx) / 2.0), 1.0) ** 2
        num = (a * rn ** a * (rn ** (2 - a) - rx ** (2 - a))) / (a - 2)
        E_r2 = num / norm
        if not np.isfinite(E_r2) or E_r2 <= 0:
            return np.pi * max(((rn + rx) / 2.0), 1.0) ** 2
        return np.pi * E_r2

    def summary(self) -> str:
        return (
            f"JS-{self.set_id} '{self.name}': "
            f"dip={self.mean_dip}°/{self.mean_dip_dir}° κ={self.fisher_kappa}, "
            f"PL(α={self.size_alpha}, r=[{self.size_r_min},{self.size_r_max}]m), "
            f"P32={self.P32}"
        )


# ================================================================
# 3. 도메인 절리 구성
# ================================================================
@dataclass
class DomainJointConfig:
    """도메인 전체의 절리 구성"""
    joint_sets: List[JointSetDefinition] = field(default_factory=list)

    # 전역 역학 파라미터
    Jw_mean: float = 0.66
    Jw_std: float = 0.15
    SRF_mean: float = 2.5
    SRF_std: float = 1.0

    @property
    def Jn(self) -> float:
        """절리군 수 → Jn (Barton 테이블)"""
        n = len(self.joint_sets)
        jn_map = {0: 0.5, 1: 2.0, 2: 4.0, 3: 9.0, 4: 15.0}
        return jn_map.get(n, min(n * 3, 20.0))

    @property
    def n_sets(self) -> int:
        return len(self.joint_sets)

    def summary(self):
        print(f"  ┌─ DomainJointConfig ─────────────────────────┐")
        print(f"  │ 절리군 수: {self.n_sets} → Jn = {self.Jn}")
        print(f"  │ Jw ~ N({self.Jw_mean}, {self.Jw_std}²)")
        print(f"  │ SRF ~ N({self.SRF_mean}, {self.SRF_std}²)")
        for js in self.joint_sets:
            print(f"  │ {js.summary()}")
        print(f"  └─────────────────────────────────────────────┘")


# ================================================================
# 4. Power Law 분포 샘플러
# ================================================================
class PowerLawSampler:
    """
    Truncated Power Law 분포 (절리 크기)

    PDF:  f(r) = C · r^(-α-1),  r ∈ [r_min, r_max]
    CDF:  F(r) = [1 - (r_min/r)^α] / [1 - (r_min/r_max)^α]
    역CDF: r = r_min · [1 - U·(1 - (r_min/r_max)^α)]^(-1/α)

    참고: Bonnet et al. (2001), Davy et al. (2010)
    """

    def __init__(self, alpha: float, r_min: float, r_max: float):
        try:
            alpha = float(alpha)
            r_min = float(r_min)
            r_max = float(r_max)
        except (TypeError, ValueError):
            alpha, r_min, r_max = 3.0, 0.5, 10.0

        if not np.isfinite(alpha) or alpha <= 0:
            alpha = 3.0
        if not np.isfinite(r_min) or r_min <= 0:
            r_min = 0.5
        if not np.isfinite(r_max) or r_max <= r_min:
            r_max = max(r_min * 2.0, r_min + 1.0)

        self.alpha = alpha
        self.r_min = r_min
        self.r_max = r_max
        self._ratio_alpha = (r_min / r_max) ** alpha
        self._norm_factor = 1.0 - self._ratio_alpha

    def sample(self, n: int, rng: np.random.RandomState = None) -> np.ndarray:
        """역CDF법 샘플링"""
        if rng is None:
            rng = np.random.RandomState()
        U = rng.uniform(0, 1, n)
        r = self.r_min * (1.0 - U * self._norm_factor) ** (-1.0 / self.alpha)
        return np.clip(r, self.r_min, self.r_max)

    def pdf(self, r: np.ndarray) -> np.ndarray:
        r = np.asarray(r, dtype=float)
        C = self.alpha * self.r_min ** self.alpha / self._norm_factor
        return np.where(
            (r >= self.r_min) & (r <= self.r_max),
            C * r ** (-self.alpha - 1), 0.0
        )

    def cdf(self, r: np.ndarray) -> np.ndarray:
        r = np.asarray(r, dtype=float)
        return np.where(
            r < self.r_min, 0.0,
            np.where(r > self.r_max, 1.0,
                     (1.0 - (self.r_min / r) ** self.alpha) / self._norm_factor)
        )

    def mean(self) -> float:
        a, rn, rx = self.alpha, self.r_min, self.r_max
        if abs(a - 1.0) < 1e-10:
            return rn * np.log(rx / rn) / self._norm_factor
        num = (a * rn ** a) * (rn ** (1 - a) - rx ** (1 - a)) / (a - 1)
        return num / self._norm_factor

    def variance(self) -> float:
        E_r = self.mean()
        a, rn, rx = self.alpha, self.r_min, self.r_max
        if abs(a - 2.0) < 1e-10:
            E_r2 = (a * rn ** a * np.log(rx / rn)) / self._norm_factor
        else:
            E_r2 = (a * rn ** a * (rn ** (2 - a) - rx ** (2 - a))) / \
                   ((a - 2) * self._norm_factor)
        return E_r2 - E_r ** 2

    def summary(self) -> str:
        return (f"PowerLaw(α={self.alpha}, r=[{self.r_min:.2f},{self.r_max:.2f}]m, "
                f"E[r]={self.mean():.2f}m)")


# ================================================================
# 5. Fisher 분포
# ================================================================
class FisherDistribution:
    """
    Fisher 분포 (von Mises-Fisher on S²)

    PDF: f(θ) = κ/(4π sinh κ) · exp(κ cos θ)
    κ: 집중도 (클수록 분산 작음)
       κ=10 → ~σ≈18°, κ=30 → ~σ≈10°, κ=100 → ~σ≈6°

    알고리즘: Wood (1994) 역CDF법
    """

    @staticmethod
    def sample(mean_vector: np.ndarray,
               kappa: float,
               n_samples: int,
               rng: np.random.RandomState = None) -> np.ndarray:
        if rng is None:
            rng = np.random.RandomState()

        mean_vector = np.asarray(mean_vector, dtype=float)
        mean_vector = mean_vector / np.linalg.norm(mean_vector)

        if kappa < 1e-6:
            vecs = rng.randn(n_samples, 3)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
            return vecs

        # cos θ 역CDF
        xi = rng.uniform(0, 1, n_samples)
        log_term = np.log(xi + (1.0 - xi) * np.exp(-2.0 * kappa))
        cos_theta = 1.0 + log_term / kappa
        cos_theta = np.clip(cos_theta, -1.0, 1.0)
        sin_theta = np.sqrt(np.maximum(1.0 - cos_theta ** 2, 0.0))
        phi = rng.uniform(0, 2.0 * np.pi, n_samples)

        local = np.column_stack([
            sin_theta * np.cos(phi),
            sin_theta * np.sin(phi),
            cos_theta
        ])

        # z축 → mean_vector 회전
        z_axis = np.array([0.0, 0.0, 1.0])
        dot = np.dot(z_axis, mean_vector)

        if dot > 0.9999:
            return local
        elif dot < -0.9999:
            local[:, 2] *= -1
            return local

        rot_axis = np.cross(z_axis, mean_vector)
        rot_axis /= np.linalg.norm(rot_axis)
        rot_angle = np.arccos(np.clip(dot, -1, 1))
        rot = Rotation.from_rotvec(rot_angle * rot_axis)
        rotated = rot.apply(local)
        norms = np.linalg.norm(rotated, axis=1, keepdims=True)
        rotated /= np.maximum(norms, 1e-15)
        return rotated

    @staticmethod
    def estimate_kappa(vectors: np.ndarray) -> float:
        """관측 벡터 집합으로부터 κ MLE 추정"""
        N = len(vectors)
        R = np.linalg.norm(vectors.sum(axis=0)) / N
        if R > 0.999:
            return 1000.0
        kappa = R * (3.0 - R ** 2) / (1.0 - R ** 2)
        if N < 50:
            kappa = max(kappa - 2.0 / (N * kappa), 0.1)
        return kappa

    @staticmethod
    def kappa_to_angular_std(kappa: float) -> float:
        """κ → 각도 표준편차(°) 근사"""
        if kappa > 500:
            return np.degrees(1.0 / np.sqrt(kappa))
        rng = np.random.RandomState(0)
        samples = FisherDistribution.sample(np.array([0, 0, 1]), kappa, 5000, rng)
        angles = np.arccos(np.clip(samples[:, 2], -1, 1))
        return np.degrees(np.std(angles))

    @staticmethod
    def angular_std_to_kappa(std_deg: float) -> float:
        """각도 표준편차(°) → κ 근사"""
        sigma = np.radians(std_deg)
        if sigma < 0.01:
            return 10000.0
        return 1.0 / (sigma ** 2)