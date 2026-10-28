from dataclasses import replace
import unittest
import math
from typing import Literal

from src.euler_campaign.geometry import OverlapInterval, TunnelStation
from src.euler_campaign.models import (
    BartonCategory, BoreholeSpec, CaseSpec, DomainSpec, JointCondition,
    JointRealization, LineIntersection, TunnelSpec, Vector3,
)
from src.euler_campaign.profiles import (
    BoreholeProfile, ProfileInterval, TunnelProfile, compare_profiles,
    next_round_length, sample_borehole, sample_face, sample_tunnel,
)
from src.euler_campaign.qprime import QPrimeProvenance, QPrimeResult


class TestNextRoundLength(unittest.TestCase):
    def test_uses_confirmed_ranges_for_the_next_advance(self) -> None:
        cases = (
            (10.1, 4.0),
            (10.0, 2.5),
            (4.000001, 2.5),
            (4.0, 1.75),
            (1.000001, 1.75),
            (1.0, 1.1),
            (0.100001, 1.1),
            (0.1, 0.75),
            (0.0, 0.75),
        )
        for qprime, expected in cases:
            with self.subTest(qprime=qprime):
                self.assertEqual(next_round_length(qprime), expected)

    def test_rejects_invalid_qprime(self) -> None:
        for qprime in (-0.1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(qprime=qprime):
                with self.assertRaises(ValueError):
                    next_round_length(qprime)


class FixedGeometry:
    def __init__(self, hits: tuple[LineIntersection, ...] = ()) -> None:
        self.hits = hits
        self.calls: list[tuple[Vector3, Vector3, float]] = []

    def line_intersections(
        self, start: Vector3, direction: Vector3, length: float,
    ) -> tuple[LineIntersection, ...]:
        self.calls.append((start, direction, length))
        return self.hits

    def face_intersections(
        self, station: TunnelStation, radius: float, domain: DomainSpec,
    ) -> tuple[JointRealization, ...]:
        raise AssertionError("Borehole sampling must not request face intersections")


class TestEulerBoreholeProfiles(unittest.TestCase):
    def setUp(self) -> None:
        self.hole = BoreholeSpec(
            "bh", (1.0, 5.0, 5.0), (2.0, 0.0, 0.0), 2.5, 1.0, "face_comparison",
        )
        self.case = CaseSpec(
            "case", DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 4.0),
            (), (self.hole,), TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 2.0),
        )
        self.joint = JointRealization(
            "joint", 1, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1.0,
            JointCondition(
                BartonCategory("jr", "Jr", "Test roughness", 3.0, 3.0),
                BartonCategory("ja", "Ja", "Test alteration", 2.0, 2.0),
            ),
        )

    def test_complete_intervals_only_and_normalized_sampling(self) -> None:
        geometry = FixedGeometry()
        profile = sample_borehole(self.case, self.hole, geometry)
        self.assertEqual([(item.start, item.end) for item in profile.intervals], [(0.0, 1.0), (1.0, 2.0)])
        self.assertEqual(profile.excluded_tail_length, 0.5)
        self.assertEqual(geometry.calls, [
            ((1.0, 5.0, 5.0), (1.0, 0.0, 0.0), 1.0),
            ((2.0, 5.0, 5.0), (1.0, 0.0, 0.0), 1.0),
        ])
        for interval in profile.intervals:
            self.assertEqual(interval.qprime.calculation_rqd, 100.0)
            self.assertEqual(interval.qprime.provenance.source, "no_intersection_convention")

    def test_direct_rqd_uses_positions_not_count(self) -> None:
        near_end = FixedGeometry((LineIntersection(0.05, self.joint),))
        middle = FixedGeometry((LineIntersection(0.5, self.joint),))
        near_result = sample_borehole(self.case, self.hole, near_end).intervals[0].qprime
        middle_result = sample_borehole(self.case, self.hole, middle).intervals[0].qprime
        self.assertAlmostEqual(near_result.raw_rqd, 95.0)
        self.assertEqual(middle_result.raw_rqd, 100.0)
        self.assertEqual(near_result.jn, 4.0)

    def test_ten_centimetre_pieces_are_included(self) -> None:
        geometry = FixedGeometry(tuple(LineIntersection(index / 10, self.joint) for index in range(1, 10)))
        result = sample_borehole(self.case, self.hole, geometry).intervals[0].qprime
        self.assertAlmostEqual(result.raw_rqd, 100.0)

    def test_short_pieces_produce_zero_raw_rqd_and_calculation_floor(self) -> None:
        geometry = FixedGeometry(tuple(LineIntersection(index / 20, self.joint) for index in range(1, 20)))
        result = sample_borehole(self.case, self.hole, geometry).intervals[0].qprime
        self.assertEqual(result.raw_rqd, 0.0)
        self.assertEqual(result.calculation_rqd, 10.0)
        self.assertEqual(result.value, 3.75)

    def test_duplicate_and_endpoint_hits_do_not_split_core(self) -> None:
        geometry = FixedGeometry(tuple(LineIntersection(value, self.joint) for value in (1.0, 0.05, 0.0, 0.05)))
        result = sample_borehole(self.case, self.hole, geometry).intervals[0].qprime
        self.assertAlmostEqual(result.raw_rqd, 95.0)
        self.assertEqual(result.provenance.source, "intersecting_joint")

    def test_clipping_preserves_requested_distance_coordinates(self) -> None:
        hole = replace(self.hole, start=(9.0, 5.0, 5.0), requested_length=2.5, purpose="independent")
        profile = sample_borehole(self.case, hole, FixedGeometry())
        self.assertEqual(len(profile.intervals), 1)
        self.assertEqual((profile.intervals[0].start, profile.intervals[0].end), (0.0, 1.0))
        self.assertEqual(profile.excluded_tail_length, 0.0)
        assert profile.clipped is not None
        self.assertEqual(profile.clipped.exit_distance, 1.0)

    def test_subinterval_support_has_no_fabricated_value(self) -> None:
        hole = replace(self.hole, requested_length=0.5)
        geometry = FixedGeometry()
        profile = sample_borehole(self.case, hole, geometry)
        self.assertEqual(profile.intervals, ())
        self.assertEqual(profile.excluded_tail_length, 0.5)
        self.assertEqual(geometry.calls, [])

    def test_invalid_hits_raise(self) -> None:
        for value in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sample_borehole(self.case, self.hole, FixedGeometry((LineIntersection(value, self.joint),)))

    def test_invalid_comparison_request_is_rejected_before_sampling(self) -> None:
        geometry = FixedGeometry()
        with self.assertRaises(ValueError):
            sample_borehole(self.case, replace(self.hole, requested_length=12.0), geometry)
        self.assertEqual(geometry.calls, [])


class FaceGeometry:
    def __init__(self, joint: JointRealization, positions: tuple[tuple[float, ...], ...]) -> None:
        self.joint = joint
        self.positions = positions
        self.calls: list[tuple[Vector3, Vector3, float]] = []
        self.face_calls: list[DomainSpec] = []

    def line_intersections(self, start: Vector3, direction: Vector3, length: float) -> tuple[LineIntersection, ...]:
        positions = self.positions[len(self.calls)]
        self.calls.append((start, direction, length))
        return tuple(LineIntersection(distance, self.joint) for distance in positions)

    def face_intersections(self, station: TunnelStation, radius: float, domain: DomainSpec) -> tuple[JointRealization, ...]:
        self.face_calls.append(domain)
        return (self.joint,) if any(self.positions) else ()


class TestEulerFaceProfiles(unittest.TestCase):
    def setUp(self) -> None:
        self.domain = DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 4.0)
        self.case = CaseSpec(
            "face-case", self.domain, (), (),
            TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 1.0),
        )
        self.joint = JointRealization(
            "joint", 1, (5.0, 5.0, 5.0), (0.0, 1.0, 0.0), 2.0,
            JointCondition(
                BartonCategory("jr", "Jr", "Test roughness", 3.0, 3.0),
                BartonCategory("ja", "Ja", "Test alteration", 2.0, 2.0),
            ),
        )

    def test_horizontal_face_uses_transverse_scan_and_hudson_formula(self) -> None:
        geometry = FaceGeometry(self.joint, ((0.5, 1.0),))
        result = sample_face(self.case, TunnelStation(5.0, 0, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0)), geometry)
        self.assertEqual(geometry.calls, [((5.0, 4.0, 5.0), (0.0, 1.0, 0.0), 2.0)])
        self.assertEqual(result.scanlines[0].linear_frequency, 1.0)
        expected = 100.0 * math.exp(-0.1) * 1.1
        assert result.qprime is not None
        self.assertAlmostEqual(result.qprime.raw_rqd, expected)
        self.assertAlmostEqual(result.qprime.value, expected / 4.0 * 1.5)
        self.assertEqual(geometry.face_calls, [self.domain])

    def test_vertical_face_averages_rqd_not_frequencies(self) -> None:
        case = replace(self.case, tunnel=TunnelSpec(((5.0, 5.0, 0.0), (5.0, 5.0, 10.0)), 1.0))
        geometry = FaceGeometry(self.joint, ((), (0.2, 0.4, 0.6, 0.8)))
        result = sample_face(case, TunnelStation(5.0, 0, (5.0, 5.0, 5.0), (0.0, 0.0, 1.0)), geometry)
        self.assertEqual([call[1] for call in geometry.calls], [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        expected = (100.0 + 100.0 * math.exp(-0.2) * 1.2) / 2.0
        assert result.qprime is not None
        self.assertAlmostEqual(result.qprime.raw_rqd, expected)
        self.assertNotAlmostEqual(result.qprime.raw_rqd, 100.0 * math.exp(-0.1) * 1.1)

    def test_half_face_uses_domain_clipped_scan_length(self) -> None:
        case = replace(self.case, tunnel=TunnelSpec(((0.0, 0.0, 5.0), (10.0, 0.0, 5.0)), 1.0))
        geometry = FaceGeometry(self.joint, ((0.5,),))
        result = sample_face(case, TunnelStation(5.0, 0, (5.0, 0.0, 5.0), (1.0, 0.0, 0.0)), geometry)
        self.assertTrue(result.support.valid)
        self.assertAlmostEqual(result.support.in_domain_area, math.pi / 2)
        self.assertEqual(result.scanlines[0].length, 1.0)
        self.assertEqual(result.scanlines[0].linear_frequency, 1.0)

    def test_invalid_face_has_no_qprime_or_backend_calls(self) -> None:
        case = replace(self.case, tunnel=TunnelSpec(((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)), 1.0))
        geometry = FaceGeometry(self.joint, ())
        result = sample_face(case, TunnelStation(5.0, 0, (5.0, 0.0, 0.0), (1.0, 0.0, 0.0)), geometry)
        self.assertFalse(result.support.valid)
        self.assertIsNone(result.qprime)
        self.assertEqual(result.scanlines, ())
        self.assertEqual(geometry.calls, [])
        self.assertEqual(geometry.face_calls, [])

    def test_no_intersection_face_uses_explicit_fallback(self) -> None:
        result = sample_face(
            self.case, TunnelStation(5.0, 0, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0)),
            FaceGeometry(self.joint, ((),)),
        )
        assert result.qprime is not None
        self.assertEqual(result.qprime.raw_rqd, 100.0)
        self.assertEqual(result.qprime.provenance.source, "no_intersection_convention")

    def test_wrong_station_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "station"):
            sample_face(
                self.case, TunnelStation(5.0, 0, (5.0, 6.0, 5.0), (1.0, 0.0, 0.0)),
                FaceGeometry(self.joint, ((),)),
            )


class NoIntersectionGeometry:
    def __init__(self) -> None:
        self.face_stations: list[TunnelStation] = []

    def line_intersections(
        self, start: Vector3, direction: Vector3, length: float,
    ) -> tuple[LineIntersection, ...]:
        return ()

    def face_intersections(
        self, station: TunnelStation, radius: float, domain: DomainSpec,
    ) -> tuple[JointRealization, ...]:
        self.face_stations.append(station)
        return ()


class TestEulerTunnelProfiles(unittest.TestCase):
    def setUp(self) -> None:
        self.domain = DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 4.0)

    def _case(self, tunnel: TunnelSpec) -> CaseSpec:
        return CaseSpec("tunnel-case", self.domain, (), (), tunnel)

    def test_start_face_only_sets_first_advance_and_future_faces_get_support(self) -> None:
        tunnel = TunnelSpec(((1.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 1.0)
        geometry = NoIntersectionGeometry()
        result = sample_tunnel(self._case(tunnel), tunnel, geometry)

        self.assertEqual(result.stop_reason, "tunnel_end")
        self.assertIsNone(result.rejected_face)
        self.assertEqual([item.station.chainage for item in result.observations], [4.0, 8.0, 9.0])
        self.assertEqual(
            [(item.start, item.end) for item in result.intervals],
            [(0.0, 4.0), (4.0, 8.0), (8.0, 9.0)],
        )
        self.assertEqual(len(geometry.face_stations), 4)

    def test_round_stops_at_vertex_and_next_round_uses_next_segment(self) -> None:
        tunnel = TunnelSpec(
            ((1.0, 5.0, 5.0), (3.0, 5.0, 5.0), (3.0, 5.0, 10.0)), 1.0,
        )
        result = sample_tunnel(self._case(tunnel), tunnel, NoIntersectionGeometry())

        self.assertEqual([item.station.chainage for item in result.observations], [2.0, 6.0, 7.0])
        self.assertEqual(
            [item.station.direction for item in result.observations],
            [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
        )
        self.assertEqual(
            [(item.start, item.end) for item in result.intervals],
            [(0.0, 2.0), (2.0, 6.0), (6.0, 7.0)],
        )
        self.assertEqual(result.stop_reason, "tunnel_end")

    def test_invalid_boundary_face_stops_and_preserves_valid_profile(self) -> None:
        tunnel = TunnelSpec(
            ((1.0, 5.0, 5.0), (5.0, 0.0, 5.0), (10.0, -5.0, 5.0)), 1.0,
        )
        result = sample_tunnel(self._case(tunnel), tunnel, NoIntersectionGeometry())

        self.assertEqual(result.stop_reason, "invalid_boundary_face")
        self.assertEqual([item.station.chainage for item in result.observations], [4.0, math.hypot(4.0, 5.0)])
        self.assertEqual(len(result.intervals), 2)
        self.assertIsNotNone(result.rejected_face)
        assert result.rejected_face is not None
        self.assertFalse(result.rejected_face.valid)

    def test_invalid_start_face_returns_empty_profile(self) -> None:
        tunnel = TunnelSpec(((1.0, 0.0, 0.0), (9.0, 0.0, 0.0)), 1.0)
        result = sample_tunnel(self._case(tunnel), tunnel, NoIntersectionGeometry())

        self.assertEqual(result.observations, ())
        self.assertEqual(result.intervals, ())
        self.assertEqual(result.stop_reason, "invalid_boundary_face")
        self.assertIsNotNone(result.rejected_face)

    def test_rejects_tunnel_that_differs_from_case_geometry(self) -> None:
        case_tunnel = TunnelSpec(((1.0, 5.0, 5.0), (9.0, 5.0, 5.0)), 1.0)
        other_tunnel = TunnelSpec(((1.0, 5.0, 5.0), (8.0, 5.0, 5.0)), 1.0)
        with self.assertRaisesRegex(ValueError, "case.tunnel"):
            sample_tunnel(self._case(case_tunnel), other_tunnel, NoIntersectionGeometry())


class TestEulerProfileComparison(unittest.TestCase):
    def setUp(self) -> None:
        self.borehole_spec = BoreholeSpec(
            "bh", (0.0, 5.0, 5.0), (1.0, 0.0, 0.0), 10.0, 1.0, "face_comparison",
        )
        self.provenance = QPrimeProvenance(
            "no_intersection_convention", None, None, None,
            "qsimex_no_intersection_rqd100_jr4_ja0.75",
        )

    def _interval(self, start: float, end: float, value: float) -> ProfileInterval:
        qprime = QPrimeResult(100.0, 100.0, 4.0, 4.0, 0.75, value, self.provenance)
        return ProfileInterval(start, end, qprime)

    def _borehole(
        self,
        intervals: tuple[ProfileInterval, ...],
        purpose: Literal["face_comparison", "independent"] = "face_comparison",
    ) -> BoreholeProfile:
        return BoreholeProfile(replace(self.borehole_spec, purpose=purpose), None, intervals, 0.0)

    def _tunnel(self, intervals: tuple[ProfileInterval, ...]) -> TunnelProfile:
        return TunnelProfile((), intervals, "tunnel_end", None)

    def test_clips_to_overlap_and_computes_length_weighted_summaries_and_wasserstein(self) -> None:
        borehole = self._borehole((
            self._interval(0.0, 2.0, 2.0),
            self._interval(2.0, 5.0, 6.0),
        ))
        tunnel = self._tunnel((
            self._interval(10.0, 11.0, 1.0),
            self._interval(11.0, 14.0, 5.0),
        ))

        result = compare_profiles(
            borehole, tunnel, (OverlapInterval(1.0, 4.0, 10.0, 13.0),),
        )

        assert result.borehole_summary is not None
        assert result.face_summary is not None
        self.assertEqual(result.borehole_summary.support_length, 3.0)
        self.assertEqual(result.borehole_summary.minimum, 2.0)
        self.assertEqual(result.borehole_summary.maximum, 6.0)
        self.assertAlmostEqual(result.borehole_summary.mean, 14.0 / 3.0)
        self.assertEqual(result.face_summary.support_length, 3.0)
        self.assertEqual(result.face_summary.minimum, 1.0)
        self.assertEqual(result.face_summary.maximum, 5.0)
        self.assertAlmostEqual(result.face_summary.mean, 11.0 / 3.0)
        self.assertAlmostEqual(result.wasserstein_1, 1.0)
        self.assertIsNone(result.unavailable_reason)

    def test_compares_only_shared_positive_length_profile_support(self) -> None:
        borehole = self._borehole((self._interval(0.0, 1.0, 2.0),))
        tunnel = self._tunnel((self._interval(11.0, 12.0, 5.0),))

        result = compare_profiles(
            borehole, tunnel, (OverlapInterval(0.0, 2.0, 10.0, 12.0),),
        )

        assert result.borehole_summary is not None
        assert result.face_summary is not None
        self.assertEqual(result.borehole_summary.support_length, 1.0)
        self.assertEqual(result.face_summary.support_length, 1.0)
        self.assertEqual(result.wasserstein_1, 3.0)

    def test_independent_borehole_and_empty_overlap_are_unavailable(self) -> None:
        tunnel = self._tunnel((self._interval(0.0, 1.0, 3.0),))
        independent = self._borehole((), purpose="independent")
        independent_result = compare_profiles(independent, tunnel, ())
        no_overlap_result = compare_profiles(self._borehole(()), tunnel, ())

        self.assertEqual(independent_result.unavailable_reason, "independent_borehole")
        self.assertEqual(no_overlap_result.unavailable_reason, "no_overlap")
        self.assertIsNone(independent_result.wasserstein_1)
        self.assertIsNone(no_overlap_result.wasserstein_1)

    def test_no_shared_profile_support_is_unavailable(self) -> None:
        result = compare_profiles(
            self._borehole((self._interval(0.0, 1.0, 2.0),)),
            self._tunnel((self._interval(11.0, 12.0, 5.0),)),
            (OverlapInterval(2.0, 3.0, 10.0, 11.0),),
        )

        self.assertEqual(result.unavailable_reason, "no_shared_profile_support")
        self.assertIsNone(result.borehole_summary)
        self.assertIsNone(result.face_summary)
        self.assertIsNone(result.wasserstein_1)

    def test_rejects_mismatched_or_overlapping_support_mappings(self) -> None:
        borehole = self._borehole((self._interval(0.0, 3.0, 2.0),))
        tunnel = self._tunnel((self._interval(0.0, 3.0, 5.0),))

        with self.assertRaisesRegex(ValueError, "lengths must match"):
            compare_profiles(
                borehole, tunnel, (OverlapInterval(0.0, 2.0, 10.0, 13.0),),
            )
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            compare_profiles(
                borehole, tunnel, (
                    OverlapInterval(0.0, 2.0, 0.0, 2.0),
                    OverlapInterval(1.0, 3.0, 2.0, 4.0),
                ),
            )


if __name__ == "__main__":
    unittest.main()
