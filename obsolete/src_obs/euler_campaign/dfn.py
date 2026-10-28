"""Whole-domain DFN generation and disk-joint intersection geometry."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import expm1, hypot, isfinite, log, pi, sqrt

import numpy as np

from src.core.joint_models import FisherDistribution, PowerLawSampler

from .geometry import TunnelStation, normalize_direction
from .models import (
    CaseSpec, DomainSpec, JointRealization, LineIntersection, Vector3,
    validate_case,
)
from .profiles import JointGeometry

_TOL = 1e-10
_PARALLEL_TOL = 1e-12


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right))


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[0] - right[0],
        left[1] - right[1],
        left[2] - right[2],
    )


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _domain_extents(domain: DomainSpec) -> Vector3:
    if len(domain.cell_counts) != 3 or len(domain.grid_spacing) != 3:
        raise ValueError("domain requires three cell counts and grid spacings")
    extents = tuple(
        count * spacing for count, spacing in zip(domain.cell_counts, domain.grid_spacing)
    )
    if not all(isfinite(extent) and extent > 0.0 for extent in extents):
        raise ValueError("domain extents must be finite and positive")
    return (extents[0], extents[1], extents[2])


def _disk_interval(
    point: Vector3, direction: Vector3, center: Vector3, radius: float,
) -> tuple[float, float] | None:
    offset = _subtract(center, point)
    projected = _dot(offset, direction)
    perpendicular_squared = max(0.0, _dot(offset, offset) - projected * projected)
    remaining = radius * radius - perpendicular_squared
    tolerance = _TOL * max(1.0, radius * radius)
    if remaining < -tolerance:
        return None
    half_length = sqrt(max(remaining, 0.0))
    return projected - half_length, projected + half_length


def _domain_line_interval(
    point: Vector3, direction: Vector3, extents: Vector3,
) -> tuple[float, float] | None:
    lower, upper = float("-inf"), float("inf")
    for coordinate, component, extent in zip(point, direction, extents):
        if abs(component) <= _PARALLEL_TOL:
            if coordinate < -_TOL or coordinate > extent + _TOL:
                return None
            continue
        first, last = sorted((-coordinate / component, (extent - coordinate) / component))
        lower = max(lower, first)
        upper = min(upper, last)
        if lower > upper + _TOL:
            return None
    return lower, upper


def _plane_box_vertices(
    center: Vector3, normal: Vector3, extents: Vector3,
) -> tuple[Vector3, ...]:
    corners = tuple(product(
        (0.0, extents[0]), (0.0, extents[1]), (0.0, extents[2]),
    ))
    points: list[Vector3] = []
    for corner in corners:
        for axis in range(3):
            if corner[axis] != 0.0:
                continue
            other = list(corner)
            other[axis] = extents[axis]
            endpoint = (other[0], other[1], other[2])
            first_distance = _dot(normal, _subtract(corner, center))
            last_distance = _dot(normal, _subtract(endpoint, center))
            if abs(first_distance) <= _TOL:
                points.append(corner)
            if abs(last_distance) <= _TOL:
                points.append(endpoint)
            if first_distance * last_distance < 0.0:
                fraction = first_distance / (first_distance - last_distance)
                points.append(tuple(
                    corner[index] + fraction * (endpoint[index] - corner[index])
                    for index in range(3)
                ))

    unique: list[Vector3] = []
    for point in points:
        if not any(hypot(*_subtract(point, existing)) <= _TOL for existing in unique):
            unique.append(point)
    return tuple(unique)


def _circle_box_boundary_points(
    center: Vector3, normal: Vector3, radius: float, extents: Vector3,
) -> tuple[Vector3, ...]:
    points: list[Vector3] = []
    for axis in range(3):
        normal_component = normal[axis]
        in_plane_squared = max(0.0, 1.0 - normal_component * normal_component)
        if in_plane_squared <= _PARALLEL_TOL:
            continue
        if axis == 0:
            axis_vector: Vector3 = (1.0, 0.0, 0.0)
        elif axis == 1:
            axis_vector = (0.0, 1.0, 0.0)
        else:
            axis_vector = (0.0, 0.0, 1.0)
        direction_raw = _cross(normal, axis_vector)
        direction_length = sqrt(in_plane_squared)
        circle_line_direction = tuple(
            component / direction_length for component in direction_raw
        )
        for bound in (0.0, extents[axis]):
            offset = bound - center[axis]
            distance_squared = offset * offset / in_plane_squared
            remaining = radius * radius - distance_squared
            tolerance = _TOL * max(1.0, radius * radius)
            if remaining < -tolerance:
                continue
            gradient = tuple(
                (axis_vector[index] - normal_component * normal[index])
                for index in range(3)
            )
            foot = tuple(
                center[index] + offset * gradient[index] / in_plane_squared
                for index in range(3)
            )
            half_length = sqrt(max(remaining, 0.0))
            points.append(tuple(
                foot[index] + half_length * circle_line_direction[index]
                for index in range(3)
            ))
            points.append(tuple(
                foot[index] - half_length * circle_line_direction[index]
                for index in range(3)
            ))
    return tuple(points)


def _coplanar_disks_overlap_in_domain(
    face_center: Vector3,
    face_radius: float,
    joint_center: Vector3,
    joint_radius: float,
    normal: Vector3,
    extents: Vector3,
) -> bool:
    candidates = [
        face_center,
        joint_center,
        *_plane_box_vertices(face_center, normal, extents),
        *_circle_box_boundary_points(face_center, normal, face_radius, extents),
        *_circle_box_boundary_points(joint_center, normal, joint_radius, extents),
    ]

    offset = _subtract(joint_center, face_center)
    center_distance = hypot(*offset)
    if center_distance > _TOL:
        if (
            center_distance <= face_radius + joint_radius + _TOL
            and center_distance + min(face_radius, joint_radius)
            >= max(face_radius, joint_radius) - _TOL
        ):
            along = (
                face_radius * face_radius - joint_radius * joint_radius
                + center_distance * center_distance
            ) / (2.0 * center_distance)
            height_squared = face_radius * face_radius - along * along
            if height_squared >= -_TOL:
                unit = tuple(component / center_distance for component in offset)
                perpendicular_raw = _cross(normal, unit)
                perpendicular = normalize_direction(perpendicular_raw)
                base = tuple(
                    face_center[index] + along * unit[index] for index in range(3)
                )
                height = sqrt(max(height_squared, 0.0))
                candidates.extend((
                    tuple(base[index] + height * perpendicular[index] for index in range(3)),
                    tuple(base[index] - height * perpendicular[index] for index in range(3)),
                ))

    for point in candidates:
        if any(
            coordinate < -_TOL or coordinate > extent + _TOL
            for coordinate, extent in zip(point, extents)
        ):
            continue
        if abs(_dot(normal, _subtract(point, face_center))) > _TOL:
            continue
        if hypot(*_subtract(point, face_center)) > face_radius + _TOL:
            continue
        if hypot(*_subtract(point, joint_center)) <= joint_radius + _TOL:
            return True
    return False


@dataclass(frozen=True)
class DiskJointGeometry:
    """One immutable, fully generated set of finite circular joints."""

    joints: tuple[JointRealization, ...]

    def line_intersections(
        self, start: Vector3, direction: Vector3, length: float,
    ) -> tuple[LineIntersection, ...]:
        if len(start) != 3 or not all(isfinite(value) for value in start):
            raise ValueError("line start must contain three finite coordinates")
        if not isfinite(length) or length <= 0.0:
            raise ValueError("line length must be finite and positive")
        axis = normalize_direction(direction)
        hits: list[LineIntersection] = []
        for joint in self.joints:
            normal = normalize_direction(joint.normal)
            denominator = _dot(axis, normal)
            # Parallel and coplanar lines have no unique point intersection.
            if abs(denominator) <= _PARALLEL_TOL:
                continue
            distance = _dot(normal, _subtract(joint.center, start)) / denominator
            if distance < -_TOL or distance > length + _TOL:
                continue
            distance = min(max(distance, 0.0), length)
            intersection = tuple(
                start[index] + distance * axis[index] for index in range(3)
            )
            radial = _subtract(intersection, joint.center)
            if _dot(radial, radial) <= (joint.radius + _TOL) ** 2:
                hits.append(LineIntersection(distance, joint))
        hits.sort(key=lambda hit: hit.distance)
        return tuple(hits)

    def face_intersections(
        self, station: TunnelStation, radius: float, domain: DomainSpec,
    ) -> tuple[JointRealization, ...]:
        if not isfinite(radius) or radius <= 0.0:
            raise ValueError("face radius must be finite and positive")
        if len(station.center) != 3 or not all(isfinite(value) for value in station.center):
            raise ValueError("face center must contain three finite coordinates")
        face_normal = normalize_direction(station.direction)
        extents = _domain_extents(domain)
        face_offset = _dot(face_normal, station.center)
        result: list[JointRealization] = []

        for joint in self.joints:
            joint_normal = normalize_direction(joint.normal)
            joint_offset = _dot(joint_normal, joint.center)
            line_direction_raw = _cross(face_normal, joint_normal)
            line_magnitude = hypot(*line_direction_raw)
            if line_magnitude <= _PARALLEL_TOL:
                separation = abs(_dot(
                    face_normal, _subtract(joint.center, station.center),
                ))
                if separation <= _TOL and _coplanar_disks_overlap_in_domain(
                    station.center, radius, joint.center, joint.radius,
                    face_normal, extents,
                ):
                    result.append(joint)
                continue

            raw_direction = tuple(
                component / line_magnitude for component in line_direction_raw
            )
            joint_cross_direction = _cross(joint_normal, line_direction_raw)
            direction_cross_face = _cross(line_direction_raw, face_normal)
            denominator = line_magnitude * line_magnitude
            point = tuple(
                (
                    face_offset * joint_cross_direction[index]
                    + joint_offset * direction_cross_face[index]
                ) / denominator
                for index in range(3)
            )
            point3: Vector3 = (point[0], point[1], point[2])
            direction3: Vector3 = (
                raw_direction[0], raw_direction[1], raw_direction[2],
            )

            joint_interval = _disk_interval(
                point3, direction3, joint.center, joint.radius,
            )
            face_interval = _disk_interval(
                point3, direction3, station.center, radius,
            )
            domain_interval = _domain_line_interval(point3, direction3, extents)
            if joint_interval is None or face_interval is None or domain_interval is None:
                continue

            lower = max(joint_interval[0], face_interval[0], domain_interval[0])
            upper = min(joint_interval[1], face_interval[1], domain_interval[1])
            if lower <= upper + _TOL:
                result.append(joint)
        return tuple(result)


def _expected_joint_area(size_alpha: float, radius_min: float, radius_max: float) -> float:
    if radius_min == radius_max:
        return pi * radius_min * radius_min

    log_ratio = log(radius_max / radius_min)
    try:
        exponent = 2.0 - size_alpha
        if size_alpha * log_ratio <= 1e-12:
            expected_radius_squared = (
                radius_min * radius_min * expm1(2.0 * log_ratio) / (2.0 * log_ratio)
            )
        else:
            denominator = -expm1(-size_alpha * log_ratio)
            moment_factor = (
                log_ratio if abs(exponent) <= 1e-12
                else expm1(exponent * log_ratio) / exponent
            )
            expected_radius_squared = (
                radius_min * radius_min * size_alpha * moment_factor / denominator
            )
    except OverflowError as error:
        raise ValueError("joint size distribution has no finite positive mean area") from error
    expected_area = pi * expected_radius_squared
    if not isfinite(expected_area) or expected_area <= 0.0:
        raise ValueError("joint size distribution has no finite positive mean area")
    return expected_area


class CaseJointFactory:
    """Generate the complete domain DFN once for a CaseSpec and seed."""

    def generate(self, case: CaseSpec, seed: int) -> DiskJointGeometry:
        validate_case(case)
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")

        domain = case.domain
        extents = _domain_extents(domain)
        volume = extents[0] * extents[1] * extents[2]
        if not isfinite(volume) or volume <= 0.0:
            raise ValueError("domain volume must be finite and positive")
        rng = np.random.RandomState(np.random.SeedSequence(seed).generate_state(4))
        generated: list[JointRealization] = []

        for joint_set in sorted(case.joint_sets, key=lambda item: item.set_id):
            expected_area = _expected_joint_area(
                joint_set.size_alpha, joint_set.size_r_min, joint_set.size_r_max,
            )
            if joint_set.density_type == "P32":
                expected_count = joint_set.density_value * volume / expected_area
            else:
                expected_count = volume / (joint_set.density_value * expected_area)
            if not isfinite(expected_count) or expected_count < 0.0:
                raise ValueError(f"joint set {joint_set.set_id} has invalid expected count")
            if expected_count > np.iinfo(np.int64).max:
                raise ValueError(f"joint set {joint_set.set_id} expected count is too large")

            count = int(rng.poisson(expected_count))
            if count == 0:
                continue

            if joint_set.size_r_min == joint_set.size_r_max:
                radii = np.full(count, joint_set.size_r_min, dtype=float)
            else:
                radii = PowerLawSampler(
                    joint_set.size_alpha,
                    joint_set.size_r_min,
                    joint_set.size_r_max,
                ).sample(count, rng)
            normals = FisherDistribution.sample(
                np.asarray(joint_set.mean_normal, dtype=float),
                joint_set.fisher_kappa,
                count,
                rng,
            )

            # The maximum-radius buffer keeps every disk capable of reaching the
            # domain in the generated set, including disks centered outside it.
            buffer = joint_set.size_r_max
            centers = np.column_stack(tuple(
                rng.uniform(-buffer, extent + buffer, count) for extent in extents
            ))
            for index in range(count):
                center = centers[index]
                normal = normals[index]
                generated.append(JointRealization(
                    joint_id=f"{joint_set.set_id}:{index}",
                    set_id=joint_set.set_id,
                    center=(float(center[0]), float(center[1]), float(center[2])),
                    normal=(float(normal[0]), float(normal[1]), float(normal[2])),
                    radius=float(radii[index]),
                    condition=joint_set.condition,
                ))

        return DiskJointGeometry(tuple(generated))
