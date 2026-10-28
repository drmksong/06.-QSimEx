"""Pure physical geometry, without legacy imports, sampling, or file access.

Domain bounds are [0, cell_count * spacing] on each physical axis.
Comparison holes follow a segment's forward direction inside its circular tube.
Numerical tolerances handle floating-point roundoff, not physical clearance.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, copysign, hypot, isclose, isfinite, pi, sqrt
from typing import Literal

from .models import BoreholeSpec, DomainSpec, TunnelSpec, Vector3

_REL_TOL = 1e-12
_ABS_TOL = 1e-10


@dataclass(frozen=True)
class ClippedBorehole:
    requested: BoreholeSpec
    start: Vector3
    direction: Vector3
    entry_distance: float
    exit_distance: float


@dataclass(frozen=True)
class TunnelStation:
    chainage: float
    segment_index: int
    center: Vector3
    direction: Vector3


@dataclass(frozen=True)
class FaceSupport:
    station: TunnelStation
    full_area: float
    in_domain_area: float
    valid: bool


@dataclass(frozen=True)
class OverlapInterval:
    borehole_start: float
    borehole_end: float
    tunnel_start: float
    tunnel_end: float


def _vector(value: Vector3, name: str) -> Vector3:
    if len(value) != 3 or not all(isfinite(component) for component in value):
        raise ValueError(f"{name} must contain three finite coordinates")
    return value


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right))


def _point(start: Vector3, direction: Vector3, distance: float) -> Vector3:
    return (
        start[0] + direction[0] * distance,
        start[1] + direction[1] * distance,
        start[2] + direction[2] * distance,
    )


def _positive(value: float, name: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _domain_extents(domain: DomainSpec) -> Vector3:
    if len(domain.cell_counts) != 3:
        raise ValueError("domain requires three cell counts")
    _vector(domain.grid_spacing, "grid_spacing")
    for count, spacing in zip(domain.cell_counts, domain.grid_spacing):
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("cell counts must be positive integers")
        _positive(spacing, "grid spacing")
    extents = tuple(count * spacing for count, spacing in zip(domain.cell_counts, domain.grid_spacing))
    return _vector((extents[0], extents[1], extents[2]), "domain extents")


def normalize_direction(direction: Vector3) -> Vector3:
    _vector(direction, "direction")
    length = hypot(*direction)
    _positive(length, "direction magnitude")
    return (direction[0] / length, direction[1] / length, direction[2] / length)


def _validate_borehole(borehole: BoreholeSpec) -> Vector3:
    if not borehole.borehole_id.strip():
        raise ValueError("borehole_id must not be empty")
    if borehole.purpose not in ("face_comparison", "independent"):
        raise ValueError("borehole purpose must be explicitly specified")
    _vector(borehole.start, "borehole start")
    _positive(borehole.requested_length, "requested length")
    _positive(borehole.interval_length, "profile interval length")
    direction = normalize_direction(borehole.direction)
    _vector(_point(borehole.start, direction, borehole.requested_length), "borehole end")
    return direction


def borehole_from_endpoints(
    borehole_id: str,
    start: Vector3,
    end: Vector3,
    interval_length: float,
    purpose: Literal["face_comparison", "independent"],
) -> BoreholeSpec:
    _vector(start, "start")
    _vector(end, "end")
    displacement = _subtract(end, start)
    borehole = BoreholeSpec(
        borehole_id, start, normalize_direction(displacement),
        hypot(*displacement), interval_length, purpose,
    )
    _validate_borehole(borehole)
    return borehole


def clip_borehole(borehole: BoreholeSpec, domain: DomainSpec) -> ClippedBorehole | None:
    direction = _validate_borehole(borehole)
    extents = _domain_extents(domain)
    entry, exit_distance = 0.0, borehole.requested_length
    for origin, component, extent in zip(borehole.start, direction, extents):
        if component == 0.0:
            if not 0.0 <= origin <= extent:
                return None
            continue
        first, last = sorted((-origin / component, (extent - origin) / component))
        entry = max(entry, first)
        exit_distance = min(exit_distance, last)
        if exit_distance <= entry:
            return None
    return ClippedBorehole(
        borehole, _point(borehole.start, direction, entry),
        direction, entry, exit_distance,
    )


def validate_tunnel(tunnel: TunnelSpec) -> None:
    _positive(tunnel.radius, "tunnel radius")
    if len(tunnel.vertices) < 2:
        raise ValueError("tunnel requires at least two ordered vertices")
    for vertex in tunnel.vertices:
        _vector(vertex, "tunnel vertex")
    for start, end in zip(tunnel.vertices, tunnel.vertices[1:]):
        _positive(hypot(*_subtract(end, start)), "tunnel segment length")


def locate_station(tunnel: TunnelSpec, chainage: float) -> TunnelStation:
    validate_tunnel(tunnel)
    if not isfinite(chainage) or chainage < 0:
        raise ValueError("chainage must be finite and non-negative")
    accumulated = 0.0
    for index, (start, end) in enumerate(zip(tunnel.vertices, tunnel.vertices[1:])):
        displacement = _subtract(end, start)
        length = hypot(*displacement)
        segment_end = accumulated + length
        if chainage <= segment_end:
            direction = normalize_direction(displacement)
            return TunnelStation(
                chainage, index, _point(start, direction, chainage - accumulated), direction,
            )
        accumulated = segment_end
    raise ValueError("chainage exceeds tunnel length")


def _planned_overlap(borehole: BoreholeSpec, tunnel: TunnelSpec) -> tuple[OverlapInterval, ...]:
    direction = _validate_borehole(borehole)
    validate_tunnel(tunnel)
    coverage: list[tuple[float, float]] = []
    overlaps: list[OverlapInterval] = []
    chainage = 0.0
    start_inside = False
    for start, end in zip(tunnel.vertices, tunnel.vertices[1:]):
        displacement = _subtract(end, start)
        length = hypot(*displacement)
        axis = normalize_direction(displacement)
        offset = _subtract(borehole.start, start)
        along = _dot(offset, axis)
        radial = _subtract(offset, _point((0.0, 0.0, 0.0), axis, along))
        radius = hypot(*radial)
        radial_inside = radius <= tunnel.radius or isclose(radius, tunnel.radius, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)
        if 0.0 <= along <= length and radial_inside:
            start_inside = True
        if all(isclose(a, b, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)
               for a, b in zip(direction, axis)):
            if radial_inside:
                low = max(0.0, -along)
                high = min(borehole.requested_length, length - along)
                if high > low:
                    coverage.append((low, high))
                    overlaps.append(OverlapInterval(
                        low, high, chainage + along + low, chainage + along + high,
                    ))
        chainage += length
    if not start_inside:
        raise ValueError("borehole drilling start must be inside the planned tunnel volume")
    if borehole.purpose == "independent":
        return ()
    covered_end = 0.0
    for low, high in sorted(coverage):
        if low > covered_end and not isclose(low, covered_end, rel_tol=_REL_TOL, abs_tol=_ABS_TOL):
            break
        covered_end = max(covered_end, high)
    requested_length = borehole.requested_length
    if covered_end < requested_length and not isclose(covered_end, requested_length, rel_tol=_REL_TOL, abs_tol=_ABS_TOL):
        raise ValueError(
            "comparison borehole must start inside and remain within the planned "
            "tunnel volume, following the tunnel direction; use explicit independent "
            "purpose for an external investigation"
        )
    return tuple(sorted(overlaps, key=lambda interval: interval.tunnel_start))


def validate_borehole_tunnel(borehole: BoreholeSpec, tunnel: TunnelSpec) -> None:
    """Reject invalid drilling geometry before domain clipping or simulation."""
    _planned_overlap(borehole, tunnel)


def find_overlap(borehole: ClippedBorehole, tunnel: TunnelSpec) -> tuple[OverlapInterval, ...]:
    """Restrict approved comparison geometry to domain support.

    Independent investigation holes deliberately produce no face comparison.
    Interval distances are measured from the original requested borehole start.
    """
    planned = _planned_overlap(borehole.requested, tunnel)
    direction = _validate_borehole(borehole.requested)
    if not 0 <= borehole.entry_distance < borehole.exit_distance <= borehole.requested.requested_length:
        raise ValueError("invalid clipped borehole distances")
    expected_start = _point(borehole.requested.start, direction, borehole.entry_distance)
    if not all(isclose(a, b, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)
               for a, b in zip(expected_start, borehole.start)):
        raise ValueError("clipped start does not match requested geometry")
    if not all(isclose(a, b, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)
               for a, b in zip(direction, borehole.direction)):
        raise ValueError("clipped direction does not match requested geometry")
    overlaps: list[OverlapInterval] = []
    for interval in planned:
        low = max(interval.borehole_start, borehole.entry_distance)
        high = min(interval.borehole_end, borehole.exit_distance)
        if high > low:
            overlaps.append(OverlapInterval(
                low, high,
                interval.tunnel_start + low - interval.borehole_start,
                interval.tunnel_start + high - interval.borehole_start,
            ))
    return tuple(overlaps)


def _clip_polygon(
    polygon: list[tuple[float, float]], a: float, b: float, limit: float,
) -> list[tuple[float, float]]:
    if not polygon:
        return []
    result: list[tuple[float, float]] = []
    previous = polygon[-1]
    previous_value = a * previous[0] + b * previous[1] - limit
    for current in polygon:
        current_value = a * current[0] + b * current[1] - limit
        if (previous_value <= 0) != (current_value <= 0):
            fraction = previous_value / (previous_value - current_value)
            result.append((
                previous[0] + fraction * (current[0] - previous[0]),
                previous[1] + fraction * (current[1] - previous[1]),
            ))
        if current_value <= 0:
            result.append(current)
        previous, previous_value = current, current_value
    return result


def _disk_edge_area(start: tuple[float, float], end: tuple[float, float], radius: float) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    a = dx * dx + dy * dy
    if a == 0:
        return 0.0
    b = 2 * (start[0] * dx + start[1] * dy)
    c = start[0] ** 2 + start[1] ** 2 - radius ** 2
    discriminant = b * b - 4 * a * c
    cuts = [0.0, 1.0]
    if discriminant > 0:
        q = -0.5 * (b + copysign(sqrt(discriminant), b))
        roots = (q / a, c / q)
        cuts.extend(root for root in roots if 0 < root < 1)
    cuts.sort()
    area = 0.0
    for low, high in zip(cuts, cuts[1:]):
        first = (start[0] + low * dx, start[1] + low * dy)
        last = (start[0] + high * dx, start[1] + high * dy)
        middle = (start[0] + (low + high) / 2 * dx, start[1] + (low + high) / 2 * dy)
        cross = first[0] * last[1] - first[1] * last[0]
        dot = first[0] * last[0] + first[1] * last[1]
        # A tangent midpoint is on the circle, but the edge is outside the disk.
        if hypot(*middle) < radius:
            area += cross / 2
        else:
            area += radius ** 2 * atan2(cross, dot) / 2
    return area


def measure_face_support(station: TunnelStation, radius: float, domain: DomainSpec) -> FaceSupport:
    """Intersect a circular face with the domain analytically in its local plane."""
    _positive(radius, "face radius")
    _vector(station.center, "face center")
    normal = normalize_direction(station.direction)
    extents = _domain_extents(domain)
    reference: Vector3 = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = normalize_direction((
        normal[1] * reference[2] - normal[2] * reference[1],
        normal[2] * reference[0] - normal[0] * reference[2],
        normal[0] * reference[1] - normal[1] * reference[0],
    ))
    v = (
        normal[1] * u[2] - normal[2] * u[1],
        normal[2] * u[0] - normal[0] * u[2],
        normal[0] * u[1] - normal[1] * u[0],
    )
    polygon = [(-radius, -radius), (radius, -radius), (radius, radius), (-radius, radius)]
    for index, extent in enumerate(extents):
        polygon = _clip_polygon(polygon, u[index], v[index], extent - station.center[index])
        polygon = _clip_polygon(polygon, -u[index], -v[index], station.center[index])
    area = 0.0
    if polygon:
        for start, end in zip(polygon, polygon[1:] + polygon[:1]):
            area += _disk_edge_area(start, end, radius)
    full_area = pi * radius ** 2
    if not isfinite(full_area) or not isfinite(area):
        raise ValueError("face area exceeds finite numerical range")
    area = max(0.0, min(full_area, area))
    valid = area >= full_area / 2 or isclose(area, full_area / 2, rel_tol=_REL_TOL, abs_tol=0.0)
    return FaceSupport(station, full_area, area, valid)
