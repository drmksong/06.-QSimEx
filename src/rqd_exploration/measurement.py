"""Fixed-interval raw RQD measurements for one generated DFN realization."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, hypot, isclose, isfinite
from typing import Callable, Literal, TypeAlias

from src.euler_campaign.geometry import (
    TunnelStation,
    clip_borehole,
    locate_station,
    measure_face_support,
    normalize_direction,
    validate_borehole_tunnel,
    validate_tunnel,
)
from src.euler_campaign.models import (
    CaseSpec,
    DomainSpec,
    LineIntersection,
    TunnelSpec,
    Vector3,
)
from src.euler_campaign.progress import ProgressUpdate
from src.euler_campaign.profiles import (
    BatchedFaceGeometry,
    BatchedLineGeometry,
    FaceObservation,
    JointGeometry,
    LineQuery,
    ProfileJoint,
    sample_borehole,
    sample_face,
)

from .records import (
    PlannedBHInterval,
    PlannedFaceStation,
    PlannedLocation,
    PlannedScanline,
)

MEASUREMENT_VERSION = "qsimex-fixed-rqd-v1"
BH_METHOD_ID = "deere_direct_rqd"
FACE_METHOD_ID = "priest_hudson_rqd"
FACE_BOUNDARY_RULES_VERSION = "qsimex-face-boundary-half-area-v1"
FACE_PROFILE_ID = "tunnel-face"


@dataclass(frozen=True)
class MeasurementEvidence:
    """Line geometry and raw hit distances sufficient to recompute raw RQD."""

    scanline_index: int
    start_enu_m: Vector3
    direction_enu: Vector3
    length_m: float
    intersection_positions_m: tuple[float, ...]


@dataclass(frozen=True)
class RawBHObservation:
    profile_id: str
    location_index: int
    start_m: float
    end_m: float
    raw_rqd: float
    support_length_m: float
    method_id: Literal["deere_direct_rqd"]
    method_version: str
    is_valid: bool
    exclusion_reason: str | None
    zero_cross: bool
    evidence: MeasurementEvidence


@dataclass(frozen=True)
class RawFaceObservation:
    profile_id: str
    location_index: int
    chainage_m: float
    raw_rqd: float
    support_area_m2: float
    advance_distance_m: float | None
    method_id: Literal["priest_hudson_rqd"]
    method_version: str
    is_valid: bool
    exclusion_reason: str | None
    zero_cross: bool
    evidence: tuple[MeasurementEvidence, ...]


RawObservation: TypeAlias = RawBHObservation | RawFaceObservation
LocationStatus: TypeAlias = Literal["planned", "observed", "unavailable", "missing"]
FaceStopReason: TypeAlias = Literal["tunnel_end", "invalid_boundary_face"]


@dataclass(frozen=True)
class PlannedLocationState:
    modality: Literal["BH", "face"]
    profile_id: str
    location_index: int
    status: LocationStatus
    reason: str | None


@dataclass(frozen=True)
class MeasurementResult:
    planned_locations: tuple[PlannedLocation, ...]
    location_states: tuple[PlannedLocationState, ...]
    observations: tuple[RawObservation, ...]
    excluded_bh_tail_lengths_m: tuple[tuple[str, float], ...]
    face_stop_reason: FaceStopReason


class _RecordingJointGeometry:
    """Preserve the exact profile queries so raw observations remain auditable."""

    def __init__(self, joints: JointGeometry) -> None:
        self._joints = joints
        self.line_queries: tuple[LineQuery, ...] = ()
        self.line_results: tuple[tuple[LineIntersection, ...], ...] = ()

    def _line_intersections(
        self, queries: tuple[LineQuery, ...],
        *,
        progress_callback: Callable[[ProgressUpdate], None] | None = None,
    ) -> tuple[tuple[LineIntersection, ...], ...]:
        if isinstance(self._joints, BatchedLineGeometry):
            results = self._joints.line_intersections_many(
                queries,
                progress_callback=progress_callback,
            )
        else:
            result_list: list[tuple[LineIntersection, ...]] = []
            for index, (start, direction, length) in enumerate(queries, start=1):
                result_list.append(
                    self._joints.line_intersections(start, direction, length),
                )
                if progress_callback is not None:
                    progress_callback(ProgressUpdate(
                        "BH intersection",
                        f"completed interval queries {index}/{len(queries)}",
                        index,
                        len(queries),
                    ))
            results = tuple(result_list)
        if len(results) != len(queries):
            raise ValueError("geometry returned the wrong number of line results")
        self.line_queries = queries
        self.line_results = results
        return results

    def line_intersections(
        self, start: Vector3, direction: Vector3, length: float,
    ) -> tuple[LineIntersection, ...]:
        return self._line_intersections(((start, direction, length),))[0]

    def line_intersections_many(
        self, queries: tuple[LineQuery, ...],
        *,
        progress_callback: Callable[[ProgressUpdate], None] | None = None,
    ) -> tuple[tuple[LineIntersection, ...], ...]:
        return self._line_intersections(
            queries,
            progress_callback=progress_callback,
        )

    def face_intersections(
        self, station: TunnelStation, radius: float, domain: DomainSpec,
    ) -> tuple[ProfileJoint, ...]:
        return self._joints.face_intersections(station, radius, domain)

    def face_and_line_intersections(
        self,
        station: TunnelStation,
        radius: float,
        domain: DomainSpec,
        line_queries: tuple[LineQuery, ...],
    ) -> tuple[tuple[tuple[LineIntersection, ...], ...], tuple[ProfileJoint, ...]]:
        if isinstance(self._joints, BatchedFaceGeometry):
            line_results, face_joints = self._joints.face_and_line_intersections(
                station, radius, domain, line_queries,
            )
            if len(line_results) != len(line_queries):
                raise ValueError("geometry returned the wrong number of face scanlines")
            self.line_queries = line_queries
            self.line_results = line_results
            return line_results, face_joints
        line_results = self._line_intersections(line_queries)
        face_joints = self._joints.face_intersections(station, radius, domain)
        return line_results, face_joints


def _full_interval_count(length: float, interval: float) -> int:
    ratio = length / interval
    if not isfinite(ratio) or ratio <= 0.0:
        raise ValueError("profile interval count exceeds finite numerical range")
    nearest = round(ratio)
    if isclose(ratio, nearest, rel_tol=0.0, abs_tol=1e-10):
        return nearest
    return floor(ratio)


def _face_stations(
    tunnel: TunnelSpec, advance_m: float,
) -> tuple[tuple[TunnelStation, float | None], ...]:
    validate_tunnel(tunnel)
    if not isfinite(advance_m) or advance_m <= 0.0:
        raise ValueError("face advance must be finite and positive")
    stations: list[tuple[TunnelStation, float | None]] = [
        (locate_station(tunnel, 0.0), None),
    ]
    previous_chainage = 0.0
    segment_start = 0.0
    for start, end in zip(tunnel.vertices, tunnel.vertices[1:]):
        segment_length = hypot(*(right - left for left, right in zip(start, end)))
        segment_end = segment_start + segment_length
        chainage = segment_start
        while chainage < segment_end:
            next_chainage = min(chainage + advance_m, segment_end)
            if isclose(next_chainage, segment_end, rel_tol=1e-12, abs_tol=1e-10):
                next_chainage = segment_end
            if next_chainage <= chainage:
                raise ValueError("fixed face station planning did not advance")
            stations.append((
                locate_station(tunnel, next_chainage),
                next_chainage - previous_chainage,
            ))
            previous_chainage = next_chainage
            chainage = next_chainage
        segment_start = segment_end
    return tuple(stations)


def _planned_scanlines(
    station: TunnelStation, radius: float,
) -> tuple[PlannedScanline, ...]:
    normal = normalize_direction(station.direction)
    horizontal = hypot(normal[0], normal[1])
    if horizontal == 0.0:
        directions: tuple[Vector3, ...] = (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        )
    else:
        directions = ((-normal[1] / horizontal, normal[0] / horizontal, 0.0),)
    return tuple(
        PlannedScanline(
            index,
            tuple(
                station.center[axis] - radius * direction[axis]
                for axis in range(3)
            ),
            direction,
            2.0 * radius,
        )
        for index, direction in enumerate(directions)
    )


def _bh_plans(case: CaseSpec) -> tuple[PlannedBHInterval, ...]:
    planned: list[PlannedBHInterval] = []
    for borehole in case.boreholes:
        validate_borehole_tunnel(borehole, case.tunnel)
        clipped = clip_borehole(borehole, case.domain)
        if clipped is None:
            raise ValueError(
                f"borehole {borehole.borehole_id!r} has no domain support"
            )
        interval_count = _full_interval_count(
            clipped.exit_distance - clipped.entry_distance,
            borehole.interval_length,
        )
        direction = normalize_direction(borehole.direction)
        for index in range(interval_count):
            start_m = clipped.entry_distance + index * borehole.interval_length
            end_m = min(
                clipped.exit_distance,
                clipped.entry_distance + (index + 1) * borehole.interval_length,
            )
            if not isclose(
                end_m - start_m, borehole.interval_length,
                rel_tol=0.0, abs_tol=1e-10,
            ):
                raise ValueError("BH planned intervals must have full 1 m support")
            start = tuple(
                borehole.start[axis] + direction[axis] * start_m
                for axis in range(3)
            )
            planned.append(PlannedBHInterval(
                borehole.borehole_id, index, start_m, end_m, start, direction,
                end_m - start_m,
            ))
    return tuple(planned)


def plan_measurement_locations(case: CaseSpec) -> tuple[PlannedLocation, ...]:
    """Build the geometry-only pilot plan without generating a DFN."""
    bh_locations = _bh_plans(case)
    face_locations: list[PlannedFaceStation] = []
    radius = case.tunnel.radius
    for location_index, (station, advance) in enumerate(
        _face_stations(case.tunnel, 1.0),
    ):
        support = measure_face_support(station, radius, case.domain)
        face_locations.append(PlannedFaceStation(
            FACE_PROFILE_ID,
            location_index,
            station.chainage,
            station.center,
            station.direction,
            support.full_area,
            advance,
            _planned_scanlines(station, radius),
        ))
        if not support.valid:
            break
    return (*bh_locations, *face_locations)


def _evidence(
    queries: tuple[LineQuery, ...],
    results: tuple[tuple[LineIntersection, ...], ...],
) -> tuple[MeasurementEvidence, ...]:
    if len(queries) != len(results):
        raise ValueError("geometry returned mismatched line evidence")
    return tuple(
        MeasurementEvidence(
            index,
            start,
            direction,
            length,
            tuple(sorted(hit.distance for hit in hits)),
        )
        for index, ((start, direction, length), hits) in enumerate(
            zip(queries, results)
        )
    )


def measure_realization(
    case: CaseSpec,
    joints: JointGeometry,
    *,
    progress_callback: Callable[[ProgressUpdate], None] | None = None,
) -> MeasurementResult:
    """Measure BH intervals and fixed face stations from one existing realization."""
    planned_locations = plan_measurement_locations(case)
    location_states: list[PlannedLocationState] = []
    observations: list[RawObservation] = []
    excluded_tails: list[tuple[str, float]] = []

    planned_bh = tuple(
        location for location in planned_locations
        if isinstance(location, PlannedBHInterval)
    )
    planned_by_borehole: dict[str, list[PlannedBHInterval]] = {}
    for location in planned_bh:
        planned_by_borehole.setdefault(location.profile_id, []).append(location)
    bh_interval_total = len(planned_bh)
    bh_intervals_completed = 0
    active_boreholes = [
        borehole for borehole in case.boreholes
        if planned_by_borehole.get(borehole.borehole_id)
    ]
    for borehole_index, borehole in enumerate(active_boreholes, start=1):
        locations = planned_by_borehole.get(borehole.borehole_id, [])
        if progress_callback is not None:
            progress_callback(ProgressUpdate(
                "BH measurement",
                f"starting borehole {borehole.borehole_id} "
                f"({borehole_index}/{len(active_boreholes)}); "
                f"campaign intervals completed "
                f"{bh_intervals_completed}/{bh_interval_total}",
                bh_intervals_completed,
                bh_interval_total,
            ))

        def report_bh_progress(update: ProgressUpdate) -> None:
            if progress_callback is None:
                return
            completed = update.completed or 0
            progress_callback(ProgressUpdate(
                update.stage,
                f"borehole {borehole.borehole_id}: {update.detail}; "
                f"campaign intervals completed "
                f"{bh_intervals_completed + completed}/{bh_interval_total}",
                bh_intervals_completed + completed,
                bh_interval_total,
                update.log,
            ))

        recorder = _RecordingJointGeometry(joints)
        profile = sample_borehole(
            case,
            borehole,
            recorder,
            progress_callback=report_bh_progress,
        )
        if len(profile.intervals) != len(locations):
            raise ValueError("BH profile intervals do not match the planned locations")
        if len(recorder.line_queries) != len(locations):
            raise ValueError("BH geometry evidence does not match planned intervals")
        excluded_tails.append((borehole.borehole_id, profile.excluded_tail_length))
        for location, interval, query, hits in zip(
            locations, profile.intervals, recorder.line_queries, recorder.line_results,
        ):
            evidence = _evidence((query,), (hits,))[0]
            observations.append(RawBHObservation(
                location.profile_id,
                location.location_index,
                location.start_m,
                location.end_m,
                interval.qprime.raw_rqd,
                interval.end - interval.start,
                BH_METHOD_ID,
                MEASUREMENT_VERSION,
                True,
                None,
                not hits,
                evidence,
            ))
            location_states.append(PlannedLocationState(
                "BH", location.profile_id, location.location_index, "observed", None,
            ))
        bh_intervals_completed += len(locations)
        if progress_callback is not None:
            progress_callback(ProgressUpdate(
                "BH measurement",
                f"completed borehole {borehole.borehole_id}; "
                f"campaign intervals completed "
                f"{bh_intervals_completed}/{bh_interval_total}",
                bh_intervals_completed,
                bh_interval_total,
            ))

    planned_faces = tuple(
        location for location in planned_locations
        if isinstance(location, PlannedFaceStation)
    )
    face_stop_reason: FaceStopReason = "tunnel_end"
    previous_chainage: float | None = None
    face_station_total = len(planned_faces)
    for station_index, location in enumerate(planned_faces, start=1):
        if progress_callback is not None:
            progress_callback(ProgressUpdate(
                "Face measurement",
                f"processing station {station_index}/{face_station_total} "
                f"at chainage {location.chainage_m:g} m",
                station_index - 1,
                face_station_total,
                log=(
                    station_index == 1
                    or station_index % 10 == 0
                    or station_index == face_station_total
                ),
            ))
        station = locate_station(case.tunnel, location.chainage_m)
        recorder = _RecordingJointGeometry(joints)
        face: FaceObservation = sample_face(case, station, recorder)
        if not face.support.valid:
            location_states.append(PlannedLocationState(
                "face",
                location.profile_id,
                location.location_index,
                "unavailable",
                "face_support_below_half_area",
            ))
            face_stop_reason = "invalid_boundary_face"
            if progress_callback is not None:
                progress_callback(ProgressUpdate(
                    "Face measurement",
                    f"stopped at invalid boundary station "
                    f"{station_index}/{face_station_total}",
                    station_index,
                    face_station_total,
                ))
            break
        if face.qprime is None:
            raise ValueError("valid face support has no raw RQD result")
        advance = location.advance_distance_m
        if location.location_index == 0:
            if advance is not None:
                raise ValueError("initial reference face must not have advance support")
        elif previous_chainage is not None and not isclose(
            location.chainage_m - previous_chainage,
            advance if advance is not None else -1.0,
            rel_tol=1e-12,
            abs_tol=1e-10,
        ):
            raise ValueError("face advance does not match adjacent station chainage")
        evidence = _evidence(recorder.line_queries, recorder.line_results)
        observations.append(RawFaceObservation(
            location.profile_id,
            location.location_index,
            location.chainage_m,
            face.qprime.raw_rqd,
            face.support.in_domain_area,
            advance,
            FACE_METHOD_ID,
            MEASUREMENT_VERSION,
            True,
            None,
            face.qprime.provenance.source == "no_intersection_convention",
            evidence,
        ))
        location_states.append(PlannedLocationState(
            "face", location.profile_id, location.location_index, "observed", None,
        ))
        previous_chainage = location.chainage_m
        if progress_callback is not None:
            progress_callback(ProgressUpdate(
                "Face measurement",
                f"completed station {station_index}/{face_station_total}",
                station_index,
                face_station_total,
                log=(
                    station_index % 10 == 0
                    or station_index == face_station_total
                ),
            ))

    return MeasurementResult(
        planned_locations,
        tuple(location_states),
        tuple(observations),
        tuple(excluded_tails),
        face_stop_reason,
    )
