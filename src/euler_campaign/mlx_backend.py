"""MLX GPU primitives for Euler DFN generation.

The generated geometry remains in compact device arrays; this module does not
materialize one Python object per fracture.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from math import exp, floor, isfinite, lgamma, log, pi, sqrt

import mlx.core as mx

from .dfn import (
    _PARALLEL_TOL, _TOL, _circle_box_boundary_points, _domain_extents,
    _expected_joint_area, _plane_box_vertices,
)
from .geometry import TunnelStation, normalize_direction
from .models import (
    CaseSpec, DomainSpec, JointCondition, JointProfileEvidence,
    LineIntersection, Vector3, validate_case,
)

MLX_GENERATOR_VERSION = "qsimex-mlx-generation-v1"
LineQuery = tuple[Vector3, Vector3, float]


def _mlx_cross(left: mx.array, right: mx.array) -> mx.array:
    return mx.stack(
        (
            left[..., 1] * right[..., 2] - left[..., 2] * right[..., 1],
            left[..., 2] * right[..., 0] - left[..., 0] * right[..., 2],
            left[..., 0] * right[..., 1] - left[..., 1] * right[..., 0],
        ),
        axis=-1,
    )


def _as_profile_joint(
    set_id: int,
    local_id: int,
    conditions: dict[int, JointCondition],
) -> JointProfileEvidence:
    joint_set_id = int(set_id)
    return JointProfileEvidence(
        joint_id=f"{joint_set_id}:{int(local_id)}",
        set_id=joint_set_id,
        condition=conditions[joint_set_id],
    )


def _line_hit_arrays(
    starts: mx.array,
    directions: mx.array,
    lengths: mx.array,
    centers: mx.array,
    normals: mx.array,
    radii: mx.array,
) -> tuple[mx.array, mx.array]:
    denominator = mx.sum(
        directions[:, None, :] * normals[None, :, :], axis=2,
    )
    nonparallel = mx.abs(denominator) > _PARALLEL_TOL
    safe_denominator = mx.where(nonparallel, denominator, 1.0)
    distance = mx.sum(
        normals[None, :, :] * (centers[None, :, :] - starts[:, None, :]),
        axis=2,
    ) / safe_denominator
    within_segment = (
        nonparallel
        & (distance >= -_TOL)
        & (distance <= lengths[:, None] + _TOL)
    )
    clipped_distance = mx.minimum(
        mx.maximum(distance, 0.0), lengths[:, None],
    )
    intersection = (
        starts[:, None, :]
        + clipped_distance[:, :, None] * directions[:, None, :]
    )
    radial = intersection - centers[None, :, :]
    within_disk = mx.sum(radial * radial, axis=2) <= (radii[None, :] + _TOL) ** 2
    return clipped_distance, within_segment & within_disk


def require_mlx_gpu() -> tuple[str, str]:
    """Fail before simulation unless an MLX GPU can execute a real operation."""
    if mx.default_device().type != mx.DeviceType.gpu:
        raise RuntimeError(
            f"Euler campaign requires an MLX GPU; active device is {mx.default_device()}"
        )

    try:
        mlx_version = version("mlx")
    except PackageNotFoundError as error:
        raise RuntimeError("MLX distribution metadata is unavailable") from error

    probe = mx.sum(mx.array([1.0, 2.0, 3.0], dtype=mx.float32) ** 2)
    mx.eval(probe)
    if float(probe.item()) != 14.0:
        raise RuntimeError("MLX GPU preflight returned an unexpected result")
    return mlx_version, str(mx.default_device())


@dataclass(frozen=True)
class MlxJointArrays:
    """Compact, immutable-by-contract joint arrays retained on the MLX device."""

    centers: mx.array
    normals: mx.array
    radii: mx.array
    set_ids: mx.array
    local_ids: mx.array
    conditions: dict[int, JointCondition]

    @property
    def count(self) -> int:
        return self.centers.shape[0]

    def line_intersections(
        self,
        start: Vector3,
        direction: Vector3,
        length: float,
        chunk_size: int = 65_536,
    ) -> tuple[LineIntersection, ...]:
        return self.line_intersections_many(
            ((start, direction, length),),
            chunk_size=chunk_size,
            query_batch_size=1,
        )[0]

    def line_intersections_many(
        self,
        queries: tuple[LineQuery, ...],
        chunk_size: int = 65_536,
        query_batch_size: int = 4,
    ) -> tuple[tuple[LineIntersection, ...], ...]:
        if (
            isinstance(chunk_size, bool)
            or not isinstance(chunk_size, int)
            or chunk_size <= 0
        ):
            raise ValueError("chunk_size must be a positive integer")
        if (
            isinstance(query_batch_size, bool)
            or not isinstance(query_batch_size, int)
            or query_batch_size <= 0
        ):
            raise ValueError("query_batch_size must be a positive integer")
        if not queries:
            return ()
        normalized_queries: list[LineQuery] = []
        for start, direction, length in queries:
            if len(start) != 3 or not all(isfinite(value) for value in start):
                raise ValueError("line start must contain three finite coordinates")
            if not isfinite(length) or length <= 0.0:
                raise ValueError("line length must be finite and positive")
            normalized_queries.append(
                (start, normalize_direction(direction), length),
            )
        if self.count == 0:
            return tuple(() for _ in normalized_queries)

        results: list[list[tuple[float, int, int]]] = [
            [] for _ in normalized_queries
        ]
        for query_offset in range(0, len(normalized_queries), query_batch_size):
            query_batch = normalized_queries[
                query_offset:query_offset + query_batch_size
            ]
            starts = mx.array(
                tuple(item[0] for item in query_batch), dtype=mx.float32,
            )
            directions = mx.array(
                tuple(item[1] for item in query_batch), dtype=mx.float32,
            )
            lengths = mx.array(
                tuple(item[2] for item in query_batch), dtype=mx.float32,
            )
            for joint_offset in range(0, self.count, chunk_size):
                joint_stop = min(joint_offset + chunk_size, self.count)
                centers = self.centers[joint_offset:joint_stop]
                normals = self.normals[joint_offset:joint_stop]
                radii = self.radii[joint_offset:joint_stop]
                distances, hit_mask = _line_hit_arrays(
                    starts, directions, lengths, centers, normals, radii,
                )
                mx.eval(hit_mask)
                hit_rows = hit_mask.tolist()
                for query_index, row in enumerate(hit_rows):
                    selected_indices = [
                        index for index, is_hit in enumerate(row) if is_hit
                    ]
                    if not selected_indices:
                        continue
                    selected = mx.array(selected_indices, dtype=mx.int32)
                    hit_distances = distances[query_index, selected]
                    hit_set_ids = self.set_ids[
                        joint_offset:joint_stop
                    ][selected]
                    hit_local_ids = self.local_ids[
                        joint_offset:joint_stop
                    ][selected]
                    mx.eval(hit_distances, hit_set_ids, hit_local_ids)
                    results[query_offset + query_index].extend(
                        (
                            float(distance_value), int(set_id), int(local_id),
                        )
                        for distance_value, set_id, local_id in zip(
                            hit_distances.tolist(),
                            hit_set_ids.tolist(),
                            hit_local_ids.tolist(),
                        )
                    )

        outputs: list[tuple[LineIntersection, ...]] = []
        for query_hits in results:
            query_hits.sort(key=lambda hit: hit[0])
            outputs.append(tuple(
                LineIntersection(
                    distance,
                    _as_profile_joint(set_id, local_id, self.conditions),
                )
                for distance, set_id, local_id in query_hits
            ))
        return tuple(outputs)

    def face_intersections(
        self,
        station: TunnelStation,
        radius: float,
        domain: DomainSpec,
        chunk_size: int = 4_096,
    ) -> tuple[JointProfileEvidence, ...]:
        return self.face_and_line_intersections(
            station, radius, domain, (), chunk_size,
        )[1]

    def face_and_line_intersections(
        self,
        station: TunnelStation,
        radius: float,
        domain: DomainSpec,
        line_queries: tuple[LineQuery, ...],
        chunk_size: int = 4_096,
    ) -> tuple[
        tuple[tuple[LineIntersection, ...], ...],
        tuple[JointProfileEvidence, ...],
    ]:
        if not isfinite(radius) or radius <= 0.0:
            raise ValueError("face radius must be finite and positive")
        if len(station.center) != 3 or not all(
            isfinite(value) for value in station.center
        ):
            raise ValueError("face center must contain three finite coordinates")
        if (
            isinstance(chunk_size, bool)
            or not isinstance(chunk_size, int)
            or chunk_size <= 0
        ):
            raise ValueError("chunk_size must be a positive integer")
        normalized_queries: list[LineQuery] = []
        for line_start, line_direction, line_length in line_queries:
            if len(line_start) != 3 or not all(
                isfinite(value) for value in line_start
            ):
                raise ValueError("line start must contain three finite coordinates")
            if not isfinite(line_length) or line_length <= 0.0:
                raise ValueError("line length must be finite and positive")
            normalized_queries.append(
                (line_start, normalize_direction(line_direction), line_length),
            )
        face_normal = normalize_direction(station.direction)
        extents = _domain_extents(domain)
        if self.count == 0:
            return tuple(() for _ in normalized_queries), ()

        center = mx.array(station.center, dtype=mx.float32)
        normal = mx.array(face_normal, dtype=mx.float32)
        face_offset = mx.sum(normal * center)
        extent_array = mx.array(extents, dtype=mx.float32)
        fixed_points = (
            station.center,
            *_plane_box_vertices(station.center, face_normal, extents),
            *_circle_box_boundary_points(
                station.center, face_normal, radius, extents,
            ),
        )
        fixed = mx.array(fixed_points, dtype=mx.float32)
        face_radius_squared = radius * radius
        face_radius_tolerance = _TOL * max(1.0, face_radius_squared)
        if normalized_queries:
            query_starts = mx.array(
                tuple(item[0] for item in normalized_queries),
                dtype=mx.float32,
            )
            query_directions = mx.array(
                tuple(item[1] for item in normalized_queries),
                dtype=mx.float32,
            )
            query_lengths = mx.array(
                tuple(item[2] for item in normalized_queries),
                dtype=mx.float32,
            )
        line_results: list[list[tuple[float, int, int]]] = [
            [] for _ in normalized_queries
        ]
        intersections: list[JointProfileEvidence] = []

        for offset in range(0, self.count, chunk_size):
            stop = min(offset + chunk_size, self.count)
            centers = self.centers[offset:stop]
            normals = self.normals[offset:stop]
            radii = self.radii[offset:stop]
            count = stop - offset

            line_raw = _mlx_cross(normal, normals)
            line_magnitude = mx.sqrt(mx.sum(line_raw * line_raw, axis=1))
            nonparallel = line_magnitude > _PARALLEL_TOL
            safe_magnitude = mx.where(nonparallel, line_magnitude, 1.0)
            line_direction = line_raw / safe_magnitude[:, None]

            joint_offset = mx.sum(normals * centers, axis=1)
            joint_cross_direction = _mlx_cross(normals, line_raw)
            direction_cross_face = _mlx_cross(line_raw, normal)
            point = (
                face_offset * joint_cross_direction
                + joint_offset[:, None] * direction_cross_face
            ) / (safe_magnitude * safe_magnitude)[:, None]

            joint_displacement = centers - point
            joint_projection = mx.sum(
                joint_displacement * line_direction, axis=1,
            )
            joint_perpendicular_squared = mx.maximum(
                mx.sum(joint_displacement * joint_displacement, axis=1)
                - joint_projection * joint_projection,
                0.0,
            )
            joint_remaining = radii * radii - joint_perpendicular_squared
            joint_tolerance = _TOL * mx.maximum(1.0, radii * radii)
            joint_half_length = mx.sqrt(mx.maximum(joint_remaining, 0.0))
            joint_lower = joint_projection - joint_half_length
            joint_upper = joint_projection + joint_half_length
            joint_interval_valid = joint_remaining >= -joint_tolerance

            face_displacement = center - point
            face_projection = mx.sum(
                face_displacement * line_direction, axis=1,
            )
            face_perpendicular_squared = mx.maximum(
                mx.sum(face_displacement * face_displacement, axis=1)
                - face_projection * face_projection,
                0.0,
            )
            face_remaining = face_radius_squared - face_perpendicular_squared
            face_half_length = mx.sqrt(mx.maximum(face_remaining, 0.0))
            face_lower = face_projection - face_half_length
            face_upper = face_projection + face_half_length
            face_interval_valid = face_remaining >= -face_radius_tolerance

            domain_lower = mx.full((count,), -float("inf"), dtype=mx.float32)
            domain_upper = mx.full((count,), float("inf"), dtype=mx.float32)
            domain_valid = mx.ones((count,), dtype=mx.bool_)
            for axis in range(3):
                component = line_direction[:, axis]
                parallel = mx.abs(component) <= _PARALLEL_TOL
                safe_component = mx.where(parallel, 1.0, component)
                first = -point[:, axis] / safe_component
                last = (extent_array[axis] - point[:, axis]) / safe_component
                axis_lower = mx.minimum(first, last)
                axis_upper = mx.maximum(first, last)
                domain_lower = mx.where(
                    parallel, domain_lower, mx.maximum(domain_lower, axis_lower),
                )
                domain_upper = mx.where(
                    parallel, domain_upper, mx.minimum(domain_upper, axis_upper),
                )
                coordinate = point[:, axis]
                within_slab = (coordinate >= -_TOL) & (
                    coordinate <= extent_array[axis] + _TOL
                )
                domain_valid = domain_valid & (~parallel | within_slab)
            domain_valid = domain_valid & (domain_lower <= domain_upper + _TOL)
            nonparallel_hit = (
                nonparallel
                & joint_interval_valid
                & face_interval_valid
                & domain_valid
                & (
                    mx.maximum(
                        mx.maximum(joint_lower, face_lower), domain_lower,
                    )
                    <= mx.minimum(
                        mx.minimum(joint_upper, face_upper), domain_upper,
                    ) + _TOL
                )
            )

            separation = mx.abs(
                mx.sum(normal * (centers - center), axis=1)
            )
            coplanar = (~nonparallel) & (separation <= _TOL)

            fixed_points = mx.broadcast_to(
                fixed, (count, fixed.shape[0], 3),
            )
            candidates = [fixed_points, centers[:, None, :]]
            joint_circle_points: list[mx.array] = []
            for axis in range(3):
                normal_component = face_normal[axis]
                in_plane_squared = max(
                    0.0, 1.0 - normal_component * normal_component,
                )
                if in_plane_squared <= _PARALLEL_TOL:
                    continue
                basis = tuple(
                    1.0 if index == axis else 0.0 for index in range(3)
                )
                axis_vector = mx.array(basis, dtype=mx.float32)
                gradient = axis_vector - normal_component * normal
                circle_direction = _mlx_cross(normal, axis_vector) / sqrt(
                    in_plane_squared,
                )
                for bound in (0.0, extents[axis]):
                    displacement = bound - centers[:, axis]
                    remaining = (
                        radii * radii
                        - displacement * displacement / in_plane_squared
                    )
                    tolerance = _TOL * mx.maximum(1.0, radii * radii)
                    foot = (
                        centers
                        + displacement[:, None] * gradient / in_plane_squared
                    )
                    half_length = mx.sqrt(mx.maximum(remaining, 0.0))
                    valid = remaining >= -tolerance
                    for sign in (-1.0, 1.0):
                        point_candidate = (
                            foot + sign * half_length[:, None] * circle_direction
                        )
                        joint_circle_points.append(
                            mx.where(
                                valid[:, None],
                                point_candidate,
                                mx.full(
                                    point_candidate.shape, float("nan"),
                                    dtype=mx.float32,
                                ),
                            )[:, None, :],
                        )

            if joint_circle_points:
                candidates.extend(joint_circle_points)

            center_offset = centers - center
            center_distance = mx.sqrt(
                mx.sum(center_offset * center_offset, axis=1),
            )
            safe_center_distance = mx.where(center_distance > _TOL, center_distance, 1.0)
            along = (
                face_radius_squared - radii * radii
                + center_distance * center_distance
            ) / (2.0 * safe_center_distance)
            height_squared = face_radius_squared - along * along
            unit = center_offset / safe_center_distance[:, None]
            perpendicular = _mlx_cross(normal, unit)
            perpendicular_length = mx.sqrt(
                mx.sum(perpendicular * perpendicular, axis=1),
            )
            safe_perpendicular_length = mx.where(
                perpendicular_length > _TOL, perpendicular_length, 1.0,
            )
            perpendicular = perpendicular / safe_perpendicular_length[:, None]
            base = center + along[:, None] * unit
            height = mx.sqrt(mx.maximum(height_squared, 0.0))
            circle_intersections_valid = (
                (center_distance > _TOL)
                & (center_distance <= radius + radii + _TOL)
                & (
                    center_distance + mx.minimum(radius, radii)
                    >= mx.maximum(radius, radii) - _TOL
                )
                & (height_squared >= -_TOL)
                & (perpendicular_length > _TOL)
            )
            for sign in (-1.0, 1.0):
                point_candidate = base + sign * height[:, None] * perpendicular
                candidates.append(
                    mx.where(
                        circle_intersections_valid[:, None],
                        point_candidate,
                        mx.full(
                            point_candidate.shape, float("nan"),
                            dtype=mx.float32,
                        ),
                    )[:, None, :],
                )

            candidate_points = mx.concatenate(candidates, axis=1)
            candidate_from_face = candidate_points - center
            candidate_from_joint = candidate_points - centers[:, None, :]
            in_domain = mx.all(
                (candidate_points >= -_TOL)
                & (candidate_points <= extent_array + _TOL),
                axis=2,
            )
            in_face_plane = mx.abs(
                mx.sum(candidate_from_face * normal, axis=2)
            ) <= _TOL
            in_face_disk = (
                mx.sum(candidate_from_face * candidate_from_face, axis=2)
                <= (radius + _TOL) ** 2
            )
            in_joint_disk = (
                mx.sum(candidate_from_joint * candidate_from_joint, axis=2)
                <= (radii[:, None] + _TOL) ** 2
            )
            coplanar_overlap = mx.any(
                in_domain & in_face_plane & in_face_disk & in_joint_disk,
                axis=1,
            )
            face_hit_mask = nonparallel_hit | (coplanar & coplanar_overlap)
            if normalized_queries:
                line_distances, line_hit_mask = _line_hit_arrays(
                    query_starts, query_directions, query_lengths,
                    centers, normals, radii,
                )
                mx.eval(face_hit_mask, line_hit_mask)
                for query_index, row in enumerate(line_hit_mask.tolist()):
                    selected_line_indices = [
                        index for index, is_hit in enumerate(row) if is_hit
                    ]
                    if not selected_line_indices:
                        continue
                    selected_line = mx.array(
                        selected_line_indices, dtype=mx.int32,
                    )
                    hit_distances = line_distances[
                        query_index, selected_line,
                    ]
                    hit_set_ids = self.set_ids[offset:stop][selected_line]
                    hit_local_ids = self.local_ids[offset:stop][selected_line]
                    mx.eval(hit_distances, hit_set_ids, hit_local_ids)
                    line_results[query_index].extend(
                        (
                            float(distance_value), int(set_id), int(local_id),
                        )
                        for distance_value, set_id, local_id in zip(
                            hit_distances.tolist(),
                            hit_set_ids.tolist(),
                            hit_local_ids.tolist(),
                        )
                    )
            else:
                mx.eval(face_hit_mask)
            selected_indices = [
                index for index, is_hit in enumerate(face_hit_mask.tolist())
                if is_hit
            ]
            if not selected_indices:
                continue
            selected = mx.array(selected_indices, dtype=mx.int32)
            hit_set_ids = self.set_ids[offset:stop][selected]
            hit_local_ids = self.local_ids[offset:stop][selected]
            mx.eval(hit_set_ids, hit_local_ids)
            for set_id, local_id in zip(
                hit_set_ids.tolist(), hit_local_ids.tolist(),
            ):
                intersections.append(
                    _as_profile_joint(set_id, local_id, self.conditions),
                )
        line_outputs: list[tuple[LineIntersection, ...]] = []
        for query_hits in line_results:
            query_hits.sort(key=lambda hit: hit[0])
            line_outputs.append(tuple(
                LineIntersection(
                    distance,
                    _as_profile_joint(set_id, local_id, self.conditions),
                )
                for distance, set_id, local_id in query_hits
            ))
        return tuple(line_outputs), tuple(intersections)


def _sample_fisher_normals(
    mean_normal: tuple[float, float, float],
    kappa: float,
    count: int,
    key: mx.array,
) -> mx.array:
    if count == 0:
        return mx.zeros((0, 3), dtype=mx.float32)

    key_cos, key_phi = mx.random.split(key)
    mean = mx.array(mean_normal, dtype=mx.float32)
    if kappa < 1e-6:
        raw = mx.random.normal((count, 3), key=key_cos, dtype=mx.float32)
        return raw / mx.maximum(mx.linalg.norm(raw, axis=-1, keepdims=True), 1e-15)

    xi = mx.random.uniform(
        shape=(count,), dtype=mx.float32, key=key_cos,
    )
    cos_theta = 1.0 + mx.log(
        xi + (1.0 - xi) * mx.exp(-2.0 * kappa)
    ) / kappa
    cos_theta = mx.clip(cos_theta, -1.0, 1.0)
    sin_theta = mx.sqrt(mx.maximum(1.0 - cos_theta * cos_theta, 0.0))
    phi = mx.random.uniform(
        shape=(count,), low=0.0, high=2.0 * pi,
        dtype=mx.float32, key=key_phi,
    )
    local = mx.stack(
        (sin_theta * mx.cos(phi), sin_theta * mx.sin(phi), cos_theta),
        axis=-1,
    )

    # Rodrigues rotation mapping the local +Z axis to the requested plane pole.
    first_cross = mx.stack(
        (
            mean[0] * local[:, 2],
            mean[1] * local[:, 2],
            -mean[1] * local[:, 1] - mean[0] * local[:, 0],
        ),
        axis=-1,
    )
    second_cross = mx.stack(
        (
            mean[0] * first_cross[:, 2],
            mean[1] * first_cross[:, 2],
            -mean[1] * first_cross[:, 1] - mean[0] * first_cross[:, 0],
        ),
        axis=-1,
    )
    rotated = local + first_cross + second_cross / (1.0 + mean[2])
    return rotated / mx.maximum(
        mx.linalg.norm(rotated, axis=-1, keepdims=True), 1e-15,
    )


def _sample_poisson_count(expected_count: float, key: mx.array) -> int:
    """Draw one exact Poisson count using MLX-generated uniforms.

    MLX has no Poisson primitive. MLX generates batches of uniform draws; the
    small scalar candidate batch is evaluated on the host to retain double
    precision without requiring GPU float64 support.
    """
    if expected_count == 0.0:
        return 0
    if expected_count < 10.0:
        uniform = float(mx.random.uniform(shape=(), key=key).item())
        probability = exp(-expected_count)
        cumulative = probability
        count = 0
        while uniform > cumulative:
            count += 1
            probability *= expected_count / count
            cumulative += probability
        return count

    root = sqrt(expected_count)
    b = 0.931 + 2.53 * root
    a = -0.059 + 0.02483 * b
    inverse_alpha = 1.1239 + 1.1328 / (b - 3.4)
    quick_acceptance = 0.9277 - 3.6224 / (b - 2.0)
    log_rate = log(expected_count)

    while True:
        key_u, key_v, key = mx.random.split(key, num=3)
        uniform = mx.random.uniform(low=-0.5, high=0.5, shape=(64,), key=key_u)
        vertical = mx.random.uniform(shape=(64,), key=key_v)
        mx.eval(uniform, vertical)

        uniforms = uniform.tolist()
        verticals = vertical.tolist()
        for u_value, v_value in zip(uniforms, verticals):
            u_distance = 0.5 - abs(u_value)
            if u_distance <= 0.0:
                continue
            k = floor(
                (2.0 * a / u_distance + b) * u_value
                + expected_count + 0.43
            )
            if k < 0:
                continue
            if u_distance >= 0.07 and v_value <= quick_acceptance:
                return k
            if u_distance < 0.013 and v_value > u_distance:
                continue
            log_acceptance = log(
                v_value * inverse_alpha
                / (a / (u_distance * u_distance) + b)
            )
            log_probability = (
                -expected_count + k * log_rate - lgamma(k + 1.0)
            )
            if log_acceptance <= log_probability:
                return k


class MlxCaseJointFactory:
    """Generate a Case DFN as GPU arrays without per-joint Python objects."""

    def generate(self, case: CaseSpec, seed: int) -> MlxJointArrays:
        require_mlx_gpu()
        validate_case(case)
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")

        extents = _domain_extents(case.domain)
        volume = extents[0] * extents[1] * extents[2]
        if not isfinite(volume) or volume <= 0.0:
            raise ValueError("domain volume must be finite and positive")

        # MLX keys make the random streams deterministic and independent by set.
        ordered_sets = sorted(case.joint_sets, key=lambda item: item.set_id)
        set_keys = (
            mx.random.split(mx.random.key(seed), num=4 * len(ordered_sets))
            if ordered_sets else mx.zeros((0, 2), dtype=mx.uint32)
        )
        centers_by_set: list[mx.array] = []
        normals_by_set: list[mx.array] = []
        radii_by_set: list[mx.array] = []
        ids_by_set: list[mx.array] = []
        local_ids_by_set: list[mx.array] = []
        conditions: dict[int, JointCondition] = {}

        for set_index, joint_set in enumerate(ordered_sets):
            expected_area = _expected_joint_area(
                joint_set.size_alpha, joint_set.size_r_min, joint_set.size_r_max,
            )
            if joint_set.density_type == "P32":
                expected_count = joint_set.density_value * volume / expected_area
            else:
                expected_count = volume / (
                    joint_set.density_value * expected_area
                )
            if not isfinite(expected_count) or expected_count < 0.0:
                raise ValueError(
                    f"joint set {joint_set.set_id} has invalid expected count"
                )
            if expected_count > 2**63 - 1:
                raise ValueError(
                    f"joint set {joint_set.set_id} expected count is too large"
                )

            key_offset = 4 * set_index
            count = _sample_poisson_count(
                expected_count, set_keys[key_offset],
            )
            if count == 0:
                continue

            sample_key = set_keys[key_offset + 1]
            radius_key = set_keys[key_offset + 2]
            center_key = set_keys[key_offset + 3]
            if joint_set.size_r_min == joint_set.size_r_max:
                radii = mx.full(
                    (count,), joint_set.size_r_min, dtype=mx.float32,
                )
            else:
                uniform = mx.random.uniform(
                    shape=(count,), dtype=mx.float32, key=radius_key,
                )
                ratio_power = (
                    joint_set.size_r_min / joint_set.size_r_max
                ) ** joint_set.size_alpha
                radii = joint_set.size_r_min * (
                    1.0 - uniform * (1.0 - ratio_power)
                ) ** (-1.0 / joint_set.size_alpha)
                radii = mx.clip(
                    radii, joint_set.size_r_min, joint_set.size_r_max,
                )

            normals = _sample_fisher_normals(
                joint_set.mean_normal, joint_set.fisher_kappa, count, sample_key,
            )
            bounds = mx.array(extents, dtype=mx.float32)
            centers = mx.random.uniform(
                low=-joint_set.size_r_max,
                high=bounds + joint_set.size_r_max,
                shape=(count, 3),
                dtype=mx.float32,
                key=center_key,
            )
            centers_by_set.append(centers)
            normals_by_set.append(normals)
            radii_by_set.append(radii)
            ids_by_set.append(mx.full((count,), joint_set.set_id, dtype=mx.int32))
            local_ids_by_set.append(mx.arange(count, dtype=mx.int32))
            conditions[joint_set.set_id] = joint_set.condition

        if centers_by_set:
            centers = mx.concatenate(centers_by_set, axis=0)
            normals = mx.concatenate(normals_by_set, axis=0)
            radii = mx.concatenate(radii_by_set, axis=0)
            set_ids = mx.concatenate(ids_by_set, axis=0)
            local_ids = mx.concatenate(local_ids_by_set, axis=0)
        else:
            centers = mx.zeros((0, 3), dtype=mx.float32)
            normals = mx.zeros((0, 3), dtype=mx.float32)
            radii = mx.zeros((0,), dtype=mx.float32)
            set_ids = mx.zeros((0,), dtype=mx.int32)
            local_ids = mx.zeros((0,), dtype=mx.int32)

        mx.eval(centers, normals, radii, set_ids, local_ids)
        return MlxJointArrays(
            centers, normals, radii, set_ids, local_ids, conditions,
        )
