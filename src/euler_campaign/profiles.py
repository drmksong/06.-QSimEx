"""Length-supported borehole and face sampling, without excavation progression.

Boreholes use Deere direct RQD. Faces use Priest-Hudson RQD.
No legacy imports, simulation backend, or persistence is included.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, floor, fsum, hypot, isclose, isfinite, log
from typing import Literal, Protocol

from .geometry import (
    ClippedBorehole, FaceSupport, OverlapInterval, TunnelStation,
    clip_borehole, locate_station, measure_face_support, normalize_direction,
    validate_borehole_tunnel,
)
from .models import (
    BoreholeSpec, CaseSpec, DomainSpec, JointRealization, LineIntersection, TunnelSpec, Vector3,
)
from .qprime import QPrimeResult, calculate_qprime


class JointGeometry(Protocol):
    def line_intersections(
        self, start: Vector3, direction: Vector3, length: float,
    ) -> tuple[LineIntersection, ...]: ...

    def face_intersections(
        self, station: TunnelStation, radius: float, domain: DomainSpec,
    ) -> tuple[JointRealization, ...]:
        """Return joints intersecting the circular face inside the domain only."""
        ...


@dataclass(frozen=True)
class ProfileInterval:
    start: float
    end: float
    qprime: QPrimeResult


@dataclass(frozen=True)
class BoreholeProfile:
    borehole: BoreholeSpec
    clipped: ClippedBorehole | None
    intervals: tuple[ProfileInterval, ...]
    excluded_tail_length: float


@dataclass(frozen=True)
class FaceScanline:
    start: Vector3
    direction: Vector3
    length: float
    intersection_count: int
    linear_frequency: float
    rqd: float


@dataclass(frozen=True)
class FaceObservation:
    station: TunnelStation
    support: FaceSupport
    qprime: QPrimeResult | None
    scanlines: tuple[FaceScanline, ...]


@dataclass(frozen=True)
class TunnelProfile:
    observations: tuple[FaceObservation, ...]
    intervals: tuple[ProfileInterval, ...]
    stop_reason: Literal["tunnel_end", "invalid_boundary_face"]
    rejected_face: FaceSupport | None


@dataclass(frozen=True)
class DistributionSummary:
    support_length: float
    minimum: float
    maximum: float
    mean: float


@dataclass(frozen=True)
class ProfileComparison:
    overlap: tuple[OverlapInterval, ...]
    borehole_summary: DistributionSummary | None
    face_summary: DistributionSummary | None
    wasserstein_1: float | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class SimulationResult:
    signature_id: str
    domain_id: str
    seed: int
    boreholes: tuple[BoreholeProfile, ...]
    tunnel: TunnelProfile


def _interior_positions(intersections: tuple[LineIntersection, ...], length: float) -> list[float]:
    positions: list[float] = []
    for hit in sorted(intersections, key=lambda hit: hit.distance):
        distance = hit.distance
        if not isfinite(distance) or distance < 0.0 or distance > length:
            raise ValueError("intersection distance must be finite and within the scan interval")
        # Endpoint fractures do not split an intact piece inside this interval.
        if isclose(distance, 0.0, rel_tol=0.0, abs_tol=1e-8) or isclose(
            distance, length, rel_tol=0.0, abs_tol=1e-8,
        ):
            continue
        if not positions or not isclose(distance, positions[-1], rel_tol=0.0, abs_tol=1e-8):
            positions.append(distance)
    return positions


def _direct_rqd(intersections: tuple[LineIntersection, ...], length: float) -> float:
    points = [0.0, *_interior_positions(intersections, length), length]
    counted = (
        right - left
        for left, right in zip(points, points[1:])
        if right - left >= 0.1 or isclose(right - left, 0.1, rel_tol=0.0, abs_tol=1e-12)
    )
    return fsum(counted) / length * 100.0


def sample_borehole(
    case: CaseSpec, borehole: BoreholeSpec, joints: JointGeometry,
) -> BoreholeProfile:
    """Sample full intervals; distances refer to the original requested start.

    Boundary intersections are retained for joint-condition selection even though
    they do not split a core piece for direct RQD.
    """
    validate_borehole_tunnel(borehole, case.tunnel)
    if not isfinite(case.domain.jn) or case.domain.jn <= 0:
        raise ValueError("domain Jn must be finite and positive")
    clipped = clip_borehole(borehole, case.domain)
    if clipped is None:
        raise ValueError("borehole has no positive-length support inside the domain")
    length = clipped.exit_distance - clipped.entry_distance
    ratio = length / borehole.interval_length
    if not isfinite(ratio):
        raise ValueError("profile interval count exceeds finite numerical range")
    nearest = round(ratio)
    count = nearest if isclose(ratio, nearest, rel_tol=0.0, abs_tol=1e-10) else floor(ratio)
    direction = normalize_direction(borehole.direction)
    intervals: list[ProfileInterval] = []
    for index in range(count):
        start = clipped.entry_distance + index * borehole.interval_length
        end = min(clipped.exit_distance, clipped.entry_distance + (index + 1) * borehole.interval_length)
        interval_length = end - start
        origin = (
            borehole.start[0] + direction[0] * start,
            borehole.start[1] + direction[1] * start,
            borehole.start[2] + direction[2] * start,
        )
        hits = joints.line_intersections(origin, direction, interval_length)
        raw_rqd = _direct_rqd(hits, interval_length)
        result = calculate_qprime(raw_rqd, case.domain.jn, tuple(hit.joint for hit in hits))
        intervals.append(ProfileInterval(start, end, result))
    tail = 0.0 if count == nearest and isclose(ratio, nearest, rel_tol=0.0, abs_tol=1e-10) else length - count * borehole.interval_length
    return BoreholeProfile(borehole, clipped, tuple(intervals), tail)


def sample_face(case: CaseSpec, station: TunnelStation, joints: JointGeometry) -> FaceObservation:
    """Use a horizontal diameter, or x/y diameters for a vertical tunnel.

    Scanline counts describe distinct interior fracture positions, not duplicated
    hits or endpoint fractures. Joint-condition selection uses the whole supported
    face, independently of the scanline counts.
    """
    if not isfinite(case.domain.jn) or case.domain.jn <= 0:
        raise ValueError("domain Jn must be finite and positive")
    expected = locate_station(case.tunnel, station.chainage)
    normal = normalize_direction(station.direction)
    if station.segment_index != expected.segment_index or not all(
        isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)
        for a, b in zip((*station.center, *normal), (*expected.center, *expected.direction))
    ):
        raise ValueError("face station does not match the case tunnel geometry")
    support = measure_face_support(station, case.tunnel.radius, case.domain)
    if not support.valid:
        return FaceObservation(station, support, None, ())

    horizontal = hypot(normal[0], normal[1])
    directions: tuple[Vector3, ...]
    if horizontal == 0.0:
        directions = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    else:
        directions = ((-normal[1] / horizontal, normal[0] / horizontal, 0.0),)
    scans: list[FaceScanline] = []
    for index, direction in enumerate(directions):
        radius = case.tunnel.radius
        start = (
            station.center[0] - radius * direction[0],
            station.center[1] - radius * direction[1],
            station.center[2] - radius * direction[2],
        )
        diameter = BoreholeSpec(
            f"face-scan-{index}", start, direction, 2.0 * radius, 1.0, "independent",
        )
        clipped = clip_borehole(diameter, case.domain)
        if clipped is None:
            raise ValueError("valid face has no positive-length central scanline support")
        length = clipped.exit_distance - clipped.entry_distance
        hits = joints.line_intersections(clipped.start, clipped.direction, length)
        count = len(_interior_positions(hits, length))
        frequency = count / length
        if not isfinite(frequency):
            raise ValueError("face fracture frequency exceeds finite numerical range")
        lt = frequency * 0.1
        # Log form avoids an overflowing factor times an underflowing exponential.
        rqd = 100.0 * exp(log(1.0 + lt) - lt)
        scans.append(FaceScanline(clipped.start, clipped.direction, length, count, frequency, rqd))
    face_joints = joints.face_intersections(station, case.tunnel.radius, case.domain)
    if any(scan.intersection_count > 0 for scan in scans) and not face_joints:
        raise ValueError("scanline intersections contradict an empty supported face")
    raw_rqd = fsum(scan.rqd for scan in scans) / len(scans)
    result = calculate_qprime(raw_rqd, case.domain.jn, face_joints)
    return FaceObservation(station, support, result, tuple(scans))


def next_round_length(qprime: float) -> float:
    raise NotImplementedError("Round-length policy is not implemented yet")


def sample_tunnel(case: CaseSpec, tunnel: TunnelSpec, joints: JointGeometry) -> TunnelProfile:
    raise NotImplementedError("Tunnel profile progression is not implemented yet")


def compare_profiles(
    borehole: BoreholeProfile, tunnel: TunnelProfile, overlap: tuple[OverlapInterval, ...],
) -> ProfileComparison:
    raise NotImplementedError("Profile distribution comparison is not implemented yet")
