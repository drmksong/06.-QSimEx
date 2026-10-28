"""Length-supported borehole sampling and face-by-face tunnel progression.

Boreholes use Deere direct RQD. Faces use Priest-Hudson RQD.
No legacy imports, simulation backend, or persistence is included.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, floor, fsum, hypot, isclose, isfinite, log
from typing import Literal, Protocol, Union, runtime_checkable

from .geometry import (
    ClippedBorehole, FaceSupport, OverlapInterval, TunnelStation,
    clip_borehole, locate_station, measure_face_support, normalize_direction,
    validate_borehole_tunnel, validate_tunnel,
)
from .models import (
    BoreholeSpec, CaseSpec, DomainSpec, JointProfileEvidence,
    JointRealization, LineIntersection, TunnelSpec, Vector3,
)
from .qprime import QPrimeResult, calculate_qprime

PROFILE_CALCULATION_VERSION = "qsimex-profile-v1"
ProfileJoint = Union[JointRealization, JointProfileEvidence]
LineQuery = tuple[Vector3, Vector3, float]


class JointGeometry(Protocol):
    def line_intersections(
        self, start: Vector3, direction: Vector3, length: float,
    ) -> tuple[LineIntersection, ...]: ...

    def face_intersections(
        self, station: TunnelStation, radius: float, domain: DomainSpec,
    ) -> tuple[ProfileJoint, ...]:
        """Return joints intersecting the circular face inside the domain only."""
        ...


@runtime_checkable
class BatchedLineGeometry(Protocol):
    def line_intersections_many(
        self, queries: tuple[LineQuery, ...],
    ) -> tuple[tuple[LineIntersection, ...], ...]: ...


@runtime_checkable
class BatchedFaceGeometry(Protocol):
    def face_and_line_intersections(
        self,
        station: TunnelStation,
        radius: float,
        domain: DomainSpec,
        line_queries: tuple[LineQuery, ...],
    ) -> tuple[tuple[tuple[LineIntersection, ...], ...], tuple[ProfileJoint, ...]]: ...


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
    interval_ranges: list[tuple[float, float]] = []
    line_queries: list[LineQuery] = []
    for index in range(count):
        start = clipped.entry_distance + index * borehole.interval_length
        end = min(clipped.exit_distance, clipped.entry_distance + (index + 1) * borehole.interval_length)
        interval_length = end - start
        origin = (
            borehole.start[0] + direction[0] * start,
            borehole.start[1] + direction[1] * start,
            borehole.start[2] + direction[2] * start,
        )
        interval_ranges.append((start, end))
        line_queries.append((origin, direction, interval_length))
    if isinstance(joints, BatchedLineGeometry):
        hits_by_interval = joints.line_intersections_many(tuple(line_queries))
    else:
        hits_by_interval = tuple(
            joints.line_intersections(*query) for query in line_queries
        )
    if len(hits_by_interval) != len(interval_ranges):
        raise ValueError("batched geometry returned the wrong number of line results")
    intervals: list[ProfileInterval] = []
    for (start, end), hits in zip(interval_ranges, hits_by_interval):
        interval_length = end - start
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
    scan_descriptors: list[tuple[Vector3, Vector3, float]] = []
    line_queries: list[LineQuery] = []
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
        scan_descriptors.append((clipped.start, clipped.direction, length))
        line_queries.append((clipped.start, clipped.direction, length))

    if isinstance(joints, BatchedFaceGeometry):
        scan_hits, face_joints = joints.face_and_line_intersections(
            station, case.tunnel.radius, case.domain, tuple(line_queries),
        )
    else:
        scan_hits = tuple(
            joints.line_intersections(*query) for query in line_queries
        )
        face_joints = joints.face_intersections(
            station, case.tunnel.radius, case.domain,
        )
    if len(scan_hits) != len(scan_descriptors):
        raise ValueError("batched geometry returned the wrong number of scanline results")

    scans: list[FaceScanline] = []
    for (start, direction, length), hits in zip(scan_descriptors, scan_hits):
        count = len(_interior_positions(hits, length))
        frequency = count / length
        if not isfinite(frequency):
            raise ValueError("face fracture frequency exceeds finite numerical range")
        lt = frequency * 0.1
        # Log form avoids an overflowing factor times an underflowing exponential.
        rqd = 100.0 * exp(log(1.0 + lt) - lt)
        scans.append(FaceScanline(start, direction, length, count, frequency, rqd))
    if any(scan.intersection_count > 0 for scan in scans) and not face_joints:
        raise ValueError("scanline intersections contradict an empty supported face")
    raw_rqd = fsum(scan.rqd for scan in scans) / len(scans)
    result = calculate_qprime(raw_rqd, case.domain.jn, face_joints)
    return FaceObservation(station, support, result, tuple(scans))


def next_round_length(qprime: float) -> float:
    """Return the next advance length for the current face Q-prime."""
    if not isfinite(qprime) or qprime < 0.0:
        raise ValueError("qprime must be finite and non-negative")
    if qprime > 10.0:
        return 4.0
    if qprime > 4.0:
        return 2.5
    if qprime > 1.0:
        return 1.75
    if qprime > 0.1:
        return 1.1
    return 0.75


def sample_tunnel(case: CaseSpec, tunnel: TunnelSpec, joints: JointGeometry) -> TunnelProfile:
    """Progress face by face, using each current face to set the next advance."""
    if tunnel != case.tunnel:
        raise ValueError("tunnel must match case.tunnel")
    validate_tunnel(tunnel)

    segment_ends: list[float] = []
    total_length = 0.0
    for start, end in zip(tunnel.vertices, tunnel.vertices[1:]):
        total_length += hypot(*(right - left for left, right in zip(start, end)))
        if not isfinite(total_length):
            raise ValueError("tunnel length exceeds finite numerical range")
        segment_ends.append(total_length)

    initial = sample_face(case, locate_station(tunnel, 0.0), joints)
    if not initial.support.valid:
        return TunnelProfile((), (), "invalid_boundary_face", initial.support)
    if initial.qprime is None:
        raise ValueError("valid starting face has no Q-prime result")

    observations: list[FaceObservation] = []
    intervals: list[ProfileInterval] = []
    current_chainage = 0.0
    current_qprime = initial.qprime
    segment_index = 0

    while current_chainage < total_length:
        while (
            segment_index < len(segment_ends) - 1
            and current_chainage >= segment_ends[segment_index]
        ):
            segment_index += 1

        segment_end = segment_ends[segment_index]
        proposed_chainage = current_chainage + next_round_length(current_qprime.value)
        if isclose(proposed_chainage, segment_end, rel_tol=1e-12, abs_tol=1e-10):
            next_chainage = segment_end
        else:
            next_chainage = min(proposed_chainage, segment_end)
        if next_chainage <= current_chainage:
            raise ValueError("tunnel progression did not advance")

        observation = sample_face(case, locate_station(tunnel, next_chainage), joints)
        if not observation.support.valid:
            return TunnelProfile(
                tuple(observations), tuple(intervals),
                "invalid_boundary_face", observation.support,
            )
        if observation.qprime is None:
            raise ValueError("valid face has no Q-prime result")

        observations.append(observation)
        intervals.append(ProfileInterval(current_chainage, next_chainage, observation.qprime))
        current_chainage = next_chainage
        current_qprime = observation.qprime

    return TunnelProfile(tuple(observations), tuple(intervals), "tunnel_end", None)


def compare_profiles(
    borehole: BoreholeProfile, tunnel: TunnelProfile, overlap: tuple[OverlapInterval, ...],
) -> ProfileComparison:
    if borehole.borehole.purpose == "independent":
        return ProfileComparison(overlap, None, None, None, "independent_borehole")
    if not overlap:
        return ProfileComparison(overlap, None, None, None, "no_overlap")

    ordered_overlaps = sorted(overlap, key=lambda item: item.tunnel_start)
    previous_borehole_end = -1.0
    previous_tunnel_end = -1.0
    for item in ordered_overlaps:
        values = (
            item.borehole_start, item.borehole_end,
            item.tunnel_start, item.tunnel_end,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("overlap coordinates must be finite")
        borehole_length = item.borehole_end - item.borehole_start
        tunnel_length = item.tunnel_end - item.tunnel_start
        if item.borehole_start < 0.0 or item.tunnel_start < 0.0:
            raise ValueError("overlap coordinates must be non-negative")
        if borehole_length <= 0.0 or tunnel_length <= 0.0:
            raise ValueError("overlap intervals must have positive length")
        if not isclose(borehole_length, tunnel_length, rel_tol=1e-12, abs_tol=1e-10):
            raise ValueError("borehole and tunnel overlap lengths must match")
        if item.borehole_start < previous_borehole_end or item.tunnel_start < previous_tunnel_end:
            raise ValueError("overlap intervals must not overlap")
        previous_borehole_end = item.borehole_end
        previous_tunnel_end = item.tunnel_end

    def validate_intervals(intervals: tuple[ProfileInterval, ...]) -> None:
        previous_end = -1.0
        for interval in intervals:
            if (
                not isfinite(interval.start)
                or not isfinite(interval.end)
                or not isfinite(interval.qprime.value)
            ):
                raise ValueError("profile interval coordinates and Q-prime values must be finite")
            if interval.start < 0.0 or interval.end <= interval.start:
                raise ValueError("profile intervals must have non-negative start and positive length")
            if interval.qprime.value <= 0.0:
                raise ValueError("profile Q-prime values must be positive")
            if interval.start < previous_end:
                raise ValueError("profile intervals must be ordered and non-overlapping")
            previous_end = interval.end

    validate_intervals(borehole.intervals)
    validate_intervals(tunnel.intervals)

    borehole_values: list[tuple[float, float]] = []
    face_values: list[tuple[float, float]] = []
    for item in ordered_overlaps:
        for interval in borehole.intervals:
            support_start = max(interval.start, item.borehole_start)
            support_end = min(interval.end, item.borehole_end)
            if support_end > support_start:
                borehole_values.append((interval.qprime.value, support_end - support_start))

        for interval in tunnel.intervals:
            support_start = max(interval.start, item.tunnel_start)
            support_end = min(interval.end, item.tunnel_end)
            if support_end > support_start:
                face_values.append((interval.qprime.value, support_end - support_start))

    if not borehole_values or not face_values:
        return ProfileComparison(overlap, None, None, None, "no_shared_profile_support")

    def summarize(values: list[tuple[float, float]]) -> DistributionSummary:
        support_length = fsum(length for _, length in values)
        weighted_sum = fsum(value * length for value, length in values)
        mean = weighted_sum / support_length
        if not all(isfinite(value) for value in (support_length, weighted_sum, mean)):
            raise ValueError("weighted profile summary exceeds finite numerical range")
        return DistributionSummary(
            support_length=support_length,
            minimum=min(value for value, _ in values),
            maximum=max(value for value, _ in values),
            mean=mean,
        )

    def wasserstein_1(
        left: list[tuple[float, float]], right: list[tuple[float, float]],
    ) -> float:
        left_total = fsum(weight for _, weight in left)
        right_total = fsum(weight for _, weight in right)
        left_mass: dict[float, float] = {}
        right_mass: dict[float, float] = {}
        for value, weight in left:
            left_mass[value] = left_mass.get(value, 0.0) + weight / left_total
        for value, weight in right:
            right_mass[value] = right_mass.get(value, 0.0) + weight / right_total

        points = sorted(left_mass.keys() | right_mass.keys())
        left_cumulative = right_cumulative = distance = 0.0
        for index, value in enumerate(points[:-1]):
            left_cumulative += left_mass.get(value, 0.0)
            right_cumulative += right_mass.get(value, 0.0)
            distance += (points[index + 1] - value) * abs(left_cumulative - right_cumulative)
        if not isfinite(distance):
            raise ValueError("Wasserstein-1 distance exceeds finite numerical range")
        return distance

    return ProfileComparison(
        overlap=overlap,
        borehole_summary=summarize(borehole_values),
        face_summary=summarize(face_values),
        wasserstein_1=wasserstein_1(borehole_values, face_values),
        unavailable_reason=None,
    )
