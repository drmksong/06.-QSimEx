"""
RQD 계산기

현실적인 RQD 비교를 위한 4가지 방법을 지원한다.

1. Borehole direct RQD
   - 굴착 전 수평시추공에서 절리 교차 위치를 이용한 Deere 직접법 RQD

2. Borehole Hudson/Priest-Hudson lambda RQD
   - 같은 시추공에서 얻은 선형 절리빈도 lambda = N/L 기반 이론식 RQD

3. Face single horizontal scanline RQD
   - 굴착 후 노출된 굴진면 x = face_x 평면 위에서
     중앙부를 수평으로 가로지르는 하나의 y방향 scanline만 사용

4. Jv-based RQD
   - Palmström형 RQD = 115 - 3.3 * Jv
   - P32 기반일 경우 엄밀한 Jv라기보다 Jv_proxy로 취급하는 것이 안전함

중요한 원칙:
- face RQD에서는 x방향, 즉 굴진 방향 scanline을 사용하지 않는다.
- face RQD에서는 multi-direction scanline 평균을 사용하지 않는다.
- x방향은 실제 수평시추공을 의미할 때만 허용한다.
"""

import numpy as np
from typing import Any, Dict, List, Optional, Tuple


class RQDCalculator:
    """RQD 계산 정적 메서드 모음"""

    @staticmethod
    def _clean_intersection_distances(
        intersection_distances: List[float],
        total_length: float,
        tol: float = 1e-8,
    ) -> List[float]:
        """
        scanline 구간 내부의 절리 교차 위치를 정리한다.

        - 0과 total_length 경계점은 제외한다.
        - NaN, inf는 제외한다.
        - 거의 같은 위치의 중복 교차점은 하나로 병합한다.
        """
        if total_length <= 0:
            return []

        vals = []
        for t in intersection_distances:
            try:
                tf = float(t)
            except Exception:
                continue

            if not np.isfinite(tf):
                continue

            if tol < tf < total_length - tol:
                vals.append(tf)

        vals = sorted(vals)

        unique_vals = []
        for v in vals:
            if len(unique_vals) == 0:
                unique_vals.append(v)
            elif abs(v - unique_vals[-1]) > tol:
                unique_vals.append(v)

        return unique_vals

    @staticmethod
    def calc_direct(
        intersection_distances: List[float],
        total_length: float,
        threshold: float = 0.1,
    ) -> float:
        """
        Deere 직접 정의:

        RQD = Σ(길이 >= threshold인 intact segment) / total_length × 100

        Parameters
        ----------
        intersection_distances:
            scanline 시작점으로부터 절리 교차점까지의 거리 목록.
        total_length:
            scanline 또는 시추공 평가 구간 길이.
        threshold:
            RQD에 포함할 최소 intact segment 길이.
            일반적으로 0.1 m.

        Returns
        -------
        float
            0~100 범위의 RQD.
        """
        details = RQDCalculator.calc_direct_details(
            intersection_distances=intersection_distances,
            total_length=total_length,
            threshold=threshold,
        )
        return details["rqd"]

    @staticmethod
    def calc_direct_details(
        intersection_distances: List[float],
        total_length: float,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Deere 직접법 RQD와 계산 세부 정보를 함께 반환한다.

        Returns
        -------
        dict
            {
                "rqd": ...,
                "total_length": ...,
                "threshold": ...,
                "intersection_positions": ...,
                "n_intersections": ...,
                "points": ...,
                "intact_lengths": ...,
                "counted_lengths": ...,
                "sum_counted_length": ...,
                "fracture_frequency": ...
            }
        """
        if total_length <= 0:
            return {
                "rqd": 0.0,
                "total_length": float(total_length),
                "threshold": float(threshold),
                "intersection_positions": [],
                "n_intersections": 0,
                "points": [],
                "intact_lengths": [],
                "counted_lengths": [],
                "sum_counted_length": 0.0,
                "fracture_frequency": np.nan,
            }

        clean_t = RQDCalculator._clean_intersection_distances(
            intersection_distances=intersection_distances,
            total_length=total_length,
        )

        points = [0.0] + clean_t + [float(total_length)]

        intact_lengths = []
        counted_lengths = []

        for i in range(len(points) - 1):
            spacing = points[i + 1] - points[i]
            intact_lengths.append(float(spacing))

            if spacing >= threshold:
                counted_lengths.append(float(spacing))

        sum_counted = float(np.sum(counted_lengths)) if counted_lengths else 0.0
        rqd = float(np.clip((sum_counted / total_length) * 100.0, 0.0, 100.0))

        fracture_frequency = len(clean_t) / total_length

        return {
            "rqd": rqd,
            "total_length": float(total_length),
            "threshold": float(threshold),
            "intersection_positions": clean_t,
            "n_intersections": int(len(clean_t)),
            "points": points,
            "intact_lengths": intact_lengths,
            "counted_lengths": counted_lengths,
            "sum_counted_length": sum_counted,
            "fracture_frequency": float(fracture_frequency),
        }

    @staticmethod
    def calc_theoretical(
        linear_frequency: float,
        threshold: float = 0.1,
    ) -> float:
        """
        Priest-Hudson 이론식:

        RQD = 100 × exp(-λt) × (λt + 1)

        여기서:
        - λ = linear_frequency = 절리 개수 / scanline 길이
        - t = threshold, 일반적으로 0.1 m

        주의:
        이 함수 자체는 방향을 모른다.
        따라서 face에서 사용할 경우 반드시 실제 굴진면 위에서 관찰 가능한
        scanline의 λ만 넣어야 한다.
        face에서 x방향, 즉 굴진 방향 λ를 넣으면 안 된다.
        """
        try:
            lam = float(linear_frequency)
        except Exception:
            return np.nan

        if not np.isfinite(lam):
            return np.nan

        lam = max(lam, 0.0)
        lt = lam * threshold

        return float(np.clip(100.0 * np.exp(-lt) * (lt + 1.0), 0.0, 100.0))

    @staticmethod
    def calc_hudson_from_lambda(
        linear_frequency: float,
        threshold: float = 0.1,
    ) -> float:
        """
        Priest-Hudson RQD 계산 alias.

        calc_theoretical()와 동일하지만, 코드 가독성을 위해 별도 이름 제공.
        """
        return RQDCalculator.calc_theoretical(
            linear_frequency=linear_frequency,
            threshold=threshold,
        )

    @staticmethod
    def calc_lambda_from_count(
        n_intersections: int,
        total_length: float,
    ) -> float:
        """
        선형 절리빈도 lambda 계산.

        lambda = N / L
        """
        if total_length <= 0:
            return np.nan

        return float(max(int(n_intersections), 0) / total_length)

    @staticmethod
    def calc_apparent_frequency(
        joint_normal: np.ndarray,
        true_spacing: float,
        scanline_direction: np.ndarray,
    ) -> float:
        """
        겉보기 선형빈도:

        λ_app = |cos α| / spacing

        여기서:
        - α = 절리 법선과 scanline 방향 사이의 각도
        - joint_normal = 절리면 법선
        - scanline_direction = 관찰 또는 시추 방향

        이 함수는 orientation bias 분석용으로 사용할 수 있다.
        """
        if true_spacing <= 0:
            return np.nan

        n = np.asarray(joint_normal, dtype=float)
        d = np.asarray(scanline_direction, dtype=float)

        n_norm = np.linalg.norm(n)
        d_norm = np.linalg.norm(d)

        if n_norm == 0 or d_norm == 0:
            return np.nan

        cos_alpha = abs(np.dot(n / n_norm, d / d_norm))
        return float(cos_alpha / true_spacing)

    @staticmethod
    def calc_from_jv(jv: float) -> float:
        """
        Palmström형 Jv 기반 RQD 계산.

        RQD = 115 - 3.3 * Jv

        최종값은 0~100으로 clipping한다.

        주의:
        P32 기반 proxy를 jv로 넣는 경우, 엄밀한 현장 Jv라기보다는
        Jv_proxy 또는 P32-derived Jv proxy로 명명하는 것이 안전하다.
        """
        try:
            jv_f = float(jv)
        except Exception:
            return np.nan

        if not np.isfinite(jv_f):
            return np.nan

        jv_f = max(jv_f, 0.0)
        rqd = 115.0 - 3.3 * jv_f

        return float(np.clip(rqd, 0.0, 100.0))

    @staticmethod
    def calc_jv_from_spacings(spacings: List[float]) -> float:
        """
        절리군 평균 간격 기반 Jv 계산.

        Jv = Σ 1 / S_i

        Parameters
        ----------
        spacings:
            각 절리군 평균 간격 목록.

        Returns
        -------
        float
            Jv
        """
        total = 0.0

        for s in spacings:
            try:
                sf = float(s)
            except Exception:
                continue

            if np.isfinite(sf) and sf > 0:
                total += 1.0 / sf

        return float(total)

    @staticmethod
    def _get_jointset_value(joint_set: Any, key: str, default: Any = None) -> Any:
        """
        joint_set이 dict이든 object이든 동일하게 값을 꺼내기 위한 helper.
        """
        if isinstance(joint_set, dict):
            return joint_set.get(key, default)

        return getattr(joint_set, key, default)

    @staticmethod
    def calc_jv_proxy_from_joint_sets(
        joint_sets: List[Any],
        prefer_p32: bool = True,
    ) -> Dict[str, Any]:
        """
        Joint set 정의로부터 Jv 또는 Jv_proxy를 계산한다.

        기준:
        - density_type == "P32"이고 P32가 있으면 P32를 contribution으로 사용.
        - 그렇지 않고 mean_spacing이 있으면 1 / mean_spacing 사용.
        - prefer_p32=True이면 density_type과 무관하게 P32가 있으면 우선 사용.

        Returns
        -------
        dict
            {
                "jv": ...,
                "method": ...,
                "contributions": [
                    {
                        "index": ...,
                        "source": "P32_proxy" or "spacing",
                        "value": ...
                    },
                    ...
                ]
            }

        주의:
        P32를 사용한 경우 엄밀한 Palmström 현장 Jv라기보다
        P32-derived Jv proxy로 해석하는 것이 안전하다.
        """
        contributions = []
        jv_total = 0.0
        used_sources = set()

        for idx, js in enumerate(joint_sets):
            density_type = RQDCalculator._get_jointset_value(js, "density_type", None)
            p32 = RQDCalculator._get_jointset_value(js, "P32", None)
            mean_spacing = RQDCalculator._get_jointset_value(js, "mean_spacing", None)

            p32_val = None
            spacing_val = None

            try:
                if p32 is not None:
                    p32_val = float(p32)
            except Exception:
                p32_val = None

            try:
                if mean_spacing is not None:
                    spacing_val = float(mean_spacing)
            except Exception:
                spacing_val = None

            use_p32 = False

            if prefer_p32 and p32_val is not None and np.isfinite(p32_val) and p32_val > 0:
                use_p32 = True
            elif (
                str(density_type).upper() == "P32"
                and p32_val is not None
                and np.isfinite(p32_val)
                and p32_val > 0
            ):
                use_p32 = True

            if use_p32:
                value = float(p32_val)
                source = "P32_proxy"
            elif spacing_val is not None and np.isfinite(spacing_val) and spacing_val > 0:
                value = float(1.0 / spacing_val)
                source = "spacing"
            elif p32_val is not None and np.isfinite(p32_val) and p32_val > 0:
                value = float(p32_val)
                source = "P32_proxy"
            else:
                value = 0.0
                source = "missing"

            jv_total += value
            used_sources.add(source)

            contributions.append(
                {
                    "index": idx,
                    "source": source,
                    "value": value,
                    "density_type": density_type,
                    "P32": p32_val,
                    "mean_spacing": spacing_val,
                }
            )

        if used_sources == {"spacing"}:
            method = "spacing_based_Jv"
        elif "P32_proxy" in used_sources:
            method = "P32_derived_Jv_proxy"
        else:
            method = "missing_or_zero"

        return {
            "jv": float(jv_total),
            "method": method,
            "contributions": contributions,
        }


class DirectionalRQDCalculator:
    """
    시추공 및 굴진면 RQD 계산.

    주요 원칙:
    - borehole은 실제 수평시추공이므로 x방향 line sampling이 가능하다.
    - face scanline은 노출된 굴진면 위에서만 가능하므로 x방향을 사용하지 않는다.
    - face scanline은 중앙 수평 y방향 단일 선분만 사용한다.
    """

    def __init__(self, dfn):
        self.dfn = dfn

    @staticmethod
    def _normalize_direction(direction: np.ndarray) -> np.ndarray:
        d = np.asarray(direction, dtype=float)
        norm = np.linalg.norm(d)

        if norm == 0:
            raise ValueError("Direction vector must be non-zero.")

        return d / norm

    def _get_line_intersection_positions(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        length: float,
    ) -> List[float]:
        """
        DFN 절리와 line segment의 교차 위치 t 목록을 반환한다.

        t는 origin으로부터 direction 방향으로 측정한 거리다.
        """
        if length <= 0:
            return []

        origin = np.asarray(origin, dtype=float)
        direction = self._normalize_direction(direction)

        intersections = self.dfn.get_joints_intersecting_line(
            origin,
            direction,
            length,
        )

        t_values = []
        for item in intersections:
            try:
                t = item[0]
            except Exception:
                continue

            try:
                tf = float(t)
            except Exception:
                continue

            if np.isfinite(tf) and 0.0 <= tf <= length:
                t_values.append(tf)

        return t_values

    def rqd_on_line(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        length: float,
        threshold: float = 0.1,
        label: str = "line",
    ) -> Dict[str, Any]:
        """
        임의의 line segment에 대해 직접 RQD와 Hudson RQD를 함께 계산한다.

        이 함수는 내부 공통 함수다.

        주의:
        face RQD 계산에서 이 함수를 쓸 때는 direction이 반드시
        굴진면 위의 방향이어야 한다. 즉 face에서 [1,0,0]은 사용하지 않는다.
        """
        if length <= 0:
            return {
                "label": label,
                "origin": np.asarray(origin, dtype=float).tolist(),
                "direction": np.asarray(direction, dtype=float).tolist(),
                "length": float(length),
                "threshold": float(threshold),
                "intersection_positions": [],
                "n_intersections": 0,
                "lambda": np.nan,
                "rqd_direct": 0.0,
                "rqd_hudson": np.nan,
                "direct_details": None,
            }

        direction_unit = self._normalize_direction(direction)

        t_values = self._get_line_intersection_positions(
            origin=origin,
            direction=direction_unit,
            length=length,
        )

        direct_details = RQDCalculator.calc_direct_details(
            intersection_distances=t_values,
            total_length=length,
            threshold=threshold,
        )

        n_intersections = direct_details["n_intersections"]
        lam = RQDCalculator.calc_lambda_from_count(
            n_intersections=n_intersections,
            total_length=length,
        )

        rqd_hudson = RQDCalculator.calc_hudson_from_lambda(
            linear_frequency=lam,
            threshold=threshold,
        )

        return {
            "label": label,
            "origin": np.asarray(origin, dtype=float).tolist(),
            "direction": direction_unit.tolist(),
            "length": float(length),
            "threshold": float(threshold),
            "intersection_positions": direct_details["intersection_positions"],
            "n_intersections": int(n_intersections),
            "lambda": float(lam),
            "rqd_direct": float(direct_details["rqd"]),
            "rqd_hudson": float(rqd_hudson),
            "direct_details": direct_details,
        }

    def rqd_borehole_interval(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        length: float,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Method 1 & 2:
        시추공 평가 구간에서 직접 RQD와 Hudson lambda RQD를 계산한다.

        사용 예:
        - origin: 평가 구간 시작점
        - direction: 수평시추공 방향. 일반적으로 [1,0,0]
        - length: 평가 구간 길이

        Returns
        -------
        dict
            {
                "RQD_borehole_direct": ...,
                "lambda_borehole": ...,
                "RQD_borehole_hudson": ...,
                ...
            }
        """
        result = self.rqd_on_line(
            origin=origin,
            direction=direction,
            length=length,
            threshold=threshold,
            label="borehole_interval",
        )

        return {
            "method": "borehole_direct_and_hudson",
            "origin": result["origin"],
            "direction": result["direction"],
            "length": result["length"],
            "threshold": result["threshold"],
            "intersection_positions": result["intersection_positions"],
            "borehole_n_intersections": result["n_intersections"],
            "lambda_borehole": result["lambda"],
            "RQD_borehole_direct": result["rqd_direct"],
            "RQD_borehole_hudson": result["rqd_hudson"],
            "direct_details": result["direct_details"],
        }

    def rqd_along_borehole(
        self,
        origin: np.ndarray,
        direction: np.ndarray,
        length: float,
        window: float = 1.0,
        step: float = 1.0,
        threshold: float = 0.1,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        기존 코드 호환용:
        이동 윈도우 방식 시추공 직접 RQD를 반환한다.

        Returns
        -------
        positions, rqd_values

        주의:
        이 함수는 기존 tuple 반환 구조를 유지한다.
        상세 정보가 필요하면 rqd_borehole_interval()을 사용한다.
        """
        if length <= 0:
            return np.array([]), np.array([])

        if window <= 0:
            raise ValueError("window must be positive.")

        if step <= 0:
            raise ValueError("step must be positive.")

        direction = self._normalize_direction(direction)

        all_ix = self.dfn.get_joints_intersecting_line(origin, direction, length)
        t_values = []

        for item in all_ix:
            try:
                t = float(item[0])
            except Exception:
                continue

            if np.isfinite(t) and 0.0 <= t <= length:
                t_values.append(t)

        t_values = np.array(t_values, dtype=float)

        if window > length:
            positions = np.array([0.0])
            effective_window = length
        else:
            positions = np.arange(0.0, length - window + 1e-9, step)
            effective_window = window

        rqd_values = np.zeros(len(positions), dtype=float)

        for idx, pos in enumerate(positions):
            mask = (t_values >= pos) & (t_values < pos + effective_window)
            window_t = (t_values[mask] - pos).tolist()

            rqd_values[idx] = RQDCalculator.calc_direct(
                intersection_distances=window_t,
                total_length=effective_window,
                threshold=threshold,
            )

        return positions, rqd_values

    def rqd_at_face_horizontal_scanline(
        self,
        face_x: float,
        tunnel_radius: Optional[float] = None,
        y_range: Optional[Tuple[float, float]] = None,
        y_center: float = 0.0,
        z_center: float = 0.0,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Method 3:
        굴진면 중앙 수평 단일 scanline RQD.

        scanline 정의:
        - 굴진면 평면: x = face_x
        - 방향: y방향 [0,1,0]
        - 위치: z = z_center
        - 범위:
            1) y_range가 주어지면 y_range[0] ~ y_range[1]
            2) 아니면 tunnel_radius를 이용해 y_center - R ~ y_center + R

        중요한 제한:
        - x방향 scanline을 사용하지 않는다.
        - 여러 방향 scanline 평균을 사용하지 않는다.
        - 실제 노출된 굴진면 위의 중앙 수평선 하나만 사용한다.

        Returns
        -------
        dict
            {
                "RQD_face_scanline": ...,
                "lambda_face_scanline": ...,
                "RQD_face_scanline_hudson": ...,
                "face_scanline_n_intersections": ...,
                ...
            }
        """
        if y_range is None:
            if tunnel_radius is None:
                raise ValueError("Either y_range or tunnel_radius must be provided.")

            y_min = y_center - float(tunnel_radius)
            y_max = y_center + float(tunnel_radius)
        else:
            y_min = float(y_range[0])
            y_max = float(y_range[1])

        if y_max <= y_min:
            raise ValueError("Invalid y_range. y_max must be greater than y_min.")

        origin = np.array([float(face_x), y_min, float(z_center)], dtype=float)
        direction = np.array([0.0, 1.0, 0.0], dtype=float)
        length = y_max - y_min

        result = self.rqd_on_line(
            origin=origin,
            direction=direction,
            length=length,
            threshold=threshold,
            label="face_single_horizontal_scanline",
        )

        return {
            "method": "face_single_horizontal_scanline",
            "face_x": float(face_x),
            "y_range": (float(y_min), float(y_max)),
            "z_center": float(z_center),
            "origin": result["origin"],
            "direction": result["direction"],
            "length": result["length"],
            "threshold": result["threshold"],
            "intersection_positions": result["intersection_positions"],
            "face_scanline_n_intersections": result["n_intersections"],
            "lambda_face_scanline": result["lambda"],
            "RQD_face_scanline": result["rqd_direct"],
            "RQD_face_scanline_hudson": result["rqd_hudson"],
            "direct_details": result["direct_details"],
        }

    def rqd_at_face(
        self,
        face_x: float,
        y_range: Tuple[float, float],
        z_range: Tuple[float, float],
        grid_spacing: float = 1.0,
        scan_length: float = 3.0,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        기존 rqd_at_face() 대체용 함수.

        기존 구현은 다음 문제가 있었다.
        - face에서 x방향 scanline 사용
        - 여러 방향 scanline 평균 사용
        - 현장 굴진면 mapping으로 보기 어려움

        따라서 이 함수는 더 이상 multi-direction scanline을 수행하지 않고,
        중앙 수평 단일 scanline만 계산한다.

        Parameters
        ----------
        face_x:
            굴진면 x 좌표.
        y_range:
            굴진면에서 수평 scanline의 y 범위.
        z_range:
            중앙 z 위치를 계산하기 위해 사용.
            z_center = (z_min + z_max) / 2
        grid_spacing:
            기존 signature 호환용. 사용하지 않음.
        scan_length:
            기존 signature 호환용. 사용하지 않음.
        threshold:
            RQD threshold. 기본 0.1 m.

        Returns
        -------
        dict
            기존 코드와 최소 호환을 위해 rqd_mean, rqd_std 등의 key를 포함하되,
            실제 값은 중앙 수평 단일 scanline 기준이다.
        """
        z_center = 0.5 * (float(z_range[0]) + float(z_range[1]))

        scan = self.rqd_at_face_horizontal_scanline(
            face_x=face_x,
            y_range=y_range,
            z_center=z_center,
            threshold=threshold,
        )

        rqd_val = scan["RQD_face_scanline"]

        return {
            "method": "face_single_horizontal_scanline",
            "face_x": float(face_x),

            # 신규 명확한 key
            "RQD_face_scanline": rqd_val,
            "lambda_face_scanline": scan["lambda_face_scanline"],
            "RQD_face_scanline_hudson": scan["RQD_face_scanline_hudson"],
            "face_scanline_n_intersections": scan["face_scanline_n_intersections"],
            "intersection_positions": scan["intersection_positions"],
            "scanline_origin": scan["origin"],
            "scanline_direction": scan["direction"],
            "scanline_length": scan["length"],
            "z_center": scan["z_center"],
            "y_range": scan["y_range"],

            # 기존 코드 최소 호환용 key
            # 이제 rqd_mean은 multi-direction 평균이 아니라
            # 단일 중앙 수평 scanline RQD를 의미한다.
            "y_points": np.array([0.5 * (float(y_range[0]) + float(y_range[1]))]),
            "z_points": np.array([z_center]),
            "rqd_map": np.array([[rqd_val]], dtype=float),
            "rqd_by_direction": np.array([[[rqd_val]]], dtype=float),
            "rqd_mean": float(rqd_val),
            "rqd_std": 0.0,
        }