from dataclasses import replace
import unittest
import math

from src.euler_campaign.geometry import TunnelStation
from src.euler_campaign.models import (
    BartonCategory, BoreholeSpec, CaseSpec, DomainSpec, JointCondition,
    JointRealization, LineIntersection, TunnelSpec, Vector3,
)
from src.euler_campaign.profiles import sample_borehole, sample_face


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


if __name__ == "__main__":
    unittest.main()
