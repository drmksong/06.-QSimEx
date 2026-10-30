from __future__ import annotations

import math
import unittest

from src.euler_campaign.geometry import TunnelStation
from src.euler_campaign.models import (
    BartonCategory,
    BoreholeSpec,
    CaseSpec,
    DomainSpec,
    JointCondition,
    JointRealization,
    LineIntersection,
    TunnelSpec,
)
from src.euler_campaign.progress import ProgressUpdate
from src.rqd_exploration.measurement import (
    FACE_METHOD_ID,
    MEASUREMENT_VERSION,
    RawBHObservation,
    RawFaceObservation,
    measure_realization,
    plan_measurement_locations,
)
from src.rqd_exploration.records import PlannedBHInterval
from src.rqd_exploration.runner import generate_and_measure


def _condition(jr: float = 3.0, ja: float = 2.0) -> JointCondition:
    return JointCondition(
        BartonCategory("jr", "Jr", "fixture", jr, jr),
        BartonCategory("ja", "Ja", "fixture", ja, ja),
    )


def _joint(jr: float = 3.0, ja: float = 2.0) -> JointRealization:
    return JointRealization(
        "fixture-joint", 1, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 1.0,
        _condition(jr, ja),
    )


def _case(
    tunnel: TunnelSpec | None = None,
    *,
    domain_counts: tuple[int, int, int] = (5, 6, 6),
    borehole_length: float = 3.2,
) -> CaseSpec:
    actual_tunnel = tunnel or TunnelSpec(
        ((0.0, 3.0, 3.0), (3.2, 3.0, 3.0)), 0.5,
    )
    boreholes = ()
    if actual_tunnel.vertices[0] == (0.0, 3.0, 3.0):
        boreholes = (BoreholeSpec(
            "pilot-bh", (0.0, 3.0, 3.0), (1.0, 0.0, 0.0),
            borehole_length, 1.0, "face_comparison",
        ),)
    return CaseSpec(
        "fixture-case",
        DomainSpec(domain_counts, (1.0, 1.0, 1.0), 4.0),
        (),
        boreholes,
        actual_tunnel,
    )


class FixtureGeometry:
    def __init__(
        self,
        positions: tuple[float, ...] = (),
        *,
        joint: JointRealization | None = None,
    ) -> None:
        self.positions = positions
        self.joint = joint
        self.line_calls: list[
            tuple[tuple[float, float, float], tuple[float, float, float], float]
        ] = []
        self.face_calls: list[tuple[float, float, DomainSpec]] = []

    def line_intersections(self, start, direction, length):
        self.line_calls.append((start, direction, length))
        return tuple(
            LineIntersection(position, self.joint)
            for position in self.positions
            if self.joint is not None
        )

    def face_intersections(
        self, station: TunnelStation, radius: float, domain: DomainSpec,
    ):
        self.face_calls.append((station.chainage, radius, domain))
        return (self.joint,) if self.joint is not None and self.positions else ()


class TestMeasurementPlanning(unittest.TestCase):
    def test_borehole_uses_full_one_metre_intervals_and_excludes_tail(self) -> None:
        locations = plan_measurement_locations(_case())
        bh = [item for item in locations if isinstance(item, PlannedBHInterval)]
        self.assertEqual(
            [(item.start_m, item.end_m) for item in bh],
            [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
        )
        self.assertTrue(all(item.planned_support_length_m == 1.0 for item in bh))

    def test_borehole_intervals_follow_domain_clipping(self) -> None:
        case = _case(domain_counts=(2, 6, 6))
        locations = [
            item for item in plan_measurement_locations(case)
            if isinstance(item, PlannedBHInterval)
        ]
        self.assertEqual(
            [(item.start_m, item.end_m) for item in locations],
            [(0.0, 1.0), (1.0, 2.0)],
        )
        self.assertEqual(locations[0].start_enu_m, (0.0, 3.0, 3.0))
        self.assertEqual(locations[-1].end_m, 2.0)

    def test_face_stations_are_fixed_by_segment_with_arriving_vertex_direction(self) -> None:
        tunnel = TunnelSpec(
            ((0.0, 3.0, 3.0), (1.5, 3.0, 3.0), (1.5, 4.5, 3.0)), 0.5,
        )
        case = CaseSpec(
            "bent-case",
            DomainSpec((5, 6, 6), (1.0, 1.0, 1.0), 4.0),
            (),
            (),
            tunnel,
        )
        locations = [
            item for item in plan_measurement_locations(case)
            if not isinstance(item, PlannedBHInterval)
        ]
        self.assertEqual(
            [item.chainage_m for item in locations],
            [0.0, 1.0, 1.5, 2.5, 3.0],
        )
        self.assertEqual(
            [item.advance_distance_m for item in locations],
            [None, 1.0, 0.5, 1.0, 0.5],
        )
        self.assertEqual(locations[2].normal_enu, (1.0, 0.0, 0.0))
        self.assertEqual(locations[3].normal_enu, (0.0, 1.0, 0.0))

    def test_face_plan_stops_at_first_invalid_boundary_and_includes_it(self) -> None:
        tunnel = TunnelSpec(((0.0, 3.0, 3.0), (4.0, 3.0, 3.0)), 0.5)
        locations = [
            item for item in plan_measurement_locations(
                _case(tunnel, domain_counts=(2, 6, 6), borehole_length=1.0),
            )
            if not isinstance(item, PlannedBHInterval)
        ]
        self.assertEqual([item.chainage_m for item in locations], [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(locations[-1].planned_support_area_m2, math.pi * 0.25)


class TestRawMeasurements(unittest.TestCase):
    def test_progress_callback_reports_bh_interval_and_face_station_counts(self) -> None:
        updates = []
        measure_realization(
            _case(),
            FixtureGeometry(),
            progress_callback=updates.append,
        )

        self.assertTrue(any(
            update.stage == "BH intersection"
            and update.completed == 3
            and update.total == 3
            for update in updates
        ))
        self.assertTrue(any(
            update.stage == "Face measurement"
            and update.completed == 5
            and update.total == 5
            for update in updates
        ))

    def test_bh_evidence_preserves_sorted_hits_and_recomputable_raw_rqd(self) -> None:
        case = _case()
        geometry = FixtureGeometry((1.0, 0.05, 0.05, 0.0), joint=_joint())
        result = measure_realization(case, geometry)
        bh = [item for item in result.observations if isinstance(item, RawBHObservation)]
        self.assertEqual(len(bh), 3)
        self.assertEqual(bh[0].raw_rqd, 95.0)
        self.assertEqual(bh[0].evidence.intersection_positions_m, (0.0, 0.05, 0.05, 1.0))
        self.assertEqual(bh[0].support_length_m, 1.0)
        self.assertFalse(bh[0].zero_cross)
        self.assertEqual(len(result.excluded_bh_tail_lengths_m), 1)
        self.assertAlmostEqual(result.excluded_bh_tail_lengths_m[0][1], 0.2)
        positions = bh[0].evidence.intersection_positions_m
        interior: list[float] = []
        for position in positions:
            if position <= 1e-8 or position >= 1.0 - 1e-8:
                continue
            if not interior or not math.isclose(
                position, interior[-1], rel_tol=0.0, abs_tol=1e-8,
            ):
                interior.append(position)
        points = (0.0, *interior, 1.0)
        recomputed = 100.0 * sum(
            right - left
            for left, right in zip(points, points[1:])
            if right - left >= 0.1
        )
        self.assertAlmostEqual(bh[0].raw_rqd, recomputed)

    def test_direct_rqd_counts_pieces_at_the_point_one_metre_cutoff(self) -> None:
        positions = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
        result = measure_realization(
            _case(), FixtureGeometry(positions, joint=_joint()),
        )
        first_interval = next(
            item for item in result.observations
            if isinstance(item, RawBHObservation)
        )
        self.assertEqual(first_interval.raw_rqd, 100.0)
        self.assertEqual(first_interval.evidence.intersection_positions_m, positions)

    def test_no_intersections_are_valid_raw_observations_not_missing_values(self) -> None:
        result = measure_realization(_case(), FixtureGeometry())
        self.assertEqual(len(result.observations), 8)
        self.assertTrue(all(item.raw_rqd == 100.0 for item in result.observations))
        self.assertTrue(all(item.zero_cross for item in result.observations))
        self.assertTrue(all(item.is_valid for item in result.observations))
        self.assertTrue(all(item.exclusion_reason is None for item in result.observations))

    def test_face_observations_use_fixed_locations_and_actual_support(self) -> None:
        result = measure_realization(_case(), FixtureGeometry((0.05,), joint=_joint()))
        faces = [item for item in result.observations if isinstance(item, RawFaceObservation)]
        self.assertEqual([item.chainage_m for item in faces], [0, 1, 2, 3, 3.2])
        self.assertEqual([item.advance_distance_m for item in faces[:-1]], [None, 1, 1, 1])
        self.assertAlmostEqual(faces[-1].advance_distance_m or 0.0, 0.2)
        self.assertTrue(all(item.method_id == FACE_METHOD_ID for item in faces))
        self.assertTrue(all(item.method_version == MEASUREMENT_VERSION for item in faces))
        self.assertTrue(all(item.support_area_m2 == math.pi * 0.25 for item in faces))
        self.assertTrue(all(len(item.evidence) == 1 for item in faces))
        self.assertTrue(all(item.evidence[0].intersection_positions_m == (0.05,) for item in faces))
        for observation in faces:
            evidence = observation.evidence[0]
            count = len(evidence.intersection_positions_m)
            frequency = count / evidence.length_m
            line_rqd = 100.0 * (1.0 + 0.1 * frequency) * math.exp(
                -0.1 * frequency,
            )
            self.assertAlmostEqual(observation.raw_rqd, line_rqd)

    def test_partial_valid_face_support_is_recorded_as_actual_area(self) -> None:
        tunnel = TunnelSpec(((0.0, 0.0, 3.0), (2.0, 0.0, 3.0)), 0.5)
        case = CaseSpec(
            "partial-face",
            DomainSpec((3, 3, 6), (1.0, 1.0, 1.0), 4.0),
            (),
            (),
            tunnel,
        )
        result = measure_realization(case, FixtureGeometry())
        faces = [item for item in result.observations if isinstance(item, RawFaceObservation)]
        self.assertEqual(len(faces), 3)
        self.assertTrue(all(
            math.isclose(item.support_area_m2, math.pi * 0.25 / 2)
            for item in faces
        ))
        self.assertTrue(all(item.evidence[0].length_m == 0.5 for item in faces))

    def test_invalid_face_boundary_is_unavailable_without_observation(self) -> None:
        tunnel = TunnelSpec(((0.0, 3.0, 3.0), (4.0, 3.0, 3.0)), 0.5)
        result = measure_realization(
            _case(tunnel, domain_counts=(2, 6, 6), borehole_length=1.0),
            FixtureGeometry(),
        )
        faces = [item for item in result.observations if isinstance(item, RawFaceObservation)]
        face_states = [item for item in result.location_states if item.modality == "face"]
        self.assertEqual([item.chainage_m for item in faces], [0.0, 1.0, 2.0])
        self.assertEqual(face_states[-1].status, "unavailable")
        self.assertEqual(face_states[-1].reason, "face_support_below_half_area")
        self.assertEqual(result.face_stop_reason, "invalid_boundary_face")

    def test_changing_joint_conditions_does_not_change_raw_rqd_or_stations(self) -> None:
        conditions_a = measure_realization(
            _case(), FixtureGeometry((0.05,), joint=_joint(3.0, 2.0)),
        )
        conditions_b = measure_realization(
            _case(), FixtureGeometry((0.05,), joint=_joint(0.5, 20.0)),
        )
        self.assertEqual(conditions_a.planned_locations, conditions_b.planned_locations)
        self.assertEqual(
            [item.raw_rqd for item in conditions_a.observations],
            [item.raw_rqd for item in conditions_b.observations],
        )

    def test_runner_generates_one_realization_then_measures_it(self) -> None:
        geometry = FixtureGeometry()
        updates = []

        class Factory:
            calls = 0

            def generate(self, case, seed, *, progress_callback=None):
                self.calls += 1
                self.asserted = (case.case_id, seed)
                if progress_callback is not None:
                    progress_callback(ProgressUpdate(
                        "DFN generation",
                        "fixture DFN ready",
                    ))
                return geometry

        factory = Factory()
        result = generate_and_measure(
            _case(),
            factory,
            43,
            progress_callback=updates.append,
        )
        self.assertEqual(factory.calls, 1)
        self.assertEqual(factory.asserted, ("fixture-case", 43))
        self.assertEqual(len(result.observations), 8)
        self.assertTrue(any(
            update.stage == "BH intersection"
            and update.completed == update.total
            for update in updates
        ))
        self.assertTrue(any(
            update.stage == "Face measurement"
            and update.completed == update.total
            for update in updates
        ))


if __name__ == "__main__":
    unittest.main()
