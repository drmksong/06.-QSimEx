import math
import unittest

from src.euler_campaign.geometry import (
    TunnelStation,
    borehole_from_endpoints,
    clip_borehole,
    find_overlap,
    locate_station,
    measure_face_support,
    normalize_direction,
    validate_borehole_tunnel,
    validate_tunnel,
)
from src.euler_campaign.models import BoreholeSpec, DomainSpec, TunnelSpec


class TestEulerGeometry(unittest.TestCase):
    def setUp(self) -> None:
        self.domain = DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0)
        self.tunnel = TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 2.0)

    def test_normalization_and_endpoints(self) -> None:
        self.assertEqual(normalize_direction((3.0, 0.0, 4.0)), (0.6, 0.0, 0.8))
        hole = borehole_from_endpoints(
            "bh", (1.0, 5.0, 5.0), (9.0, 5.0, 5.0), 1.0, "face_comparison",
        )
        self.assertEqual(hole.direction, (1.0, 0.0, 0.0))
        self.assertEqual(hole.requested_length, 8.0)
        self.assertEqual(hole.purpose, "face_comparison")

    def test_invalid_directions_and_endpoints(self) -> None:
        for direction in ((0.0, 0.0, 0.0), (float("nan"), 0.0, 1.0)):
            with self.subTest(direction=direction):
                with self.assertRaises(ValueError):
                    normalize_direction(direction)
        with self.assertRaises(ValueError):
            borehole_from_endpoints("bh", (1.0, 1.0, 1.0), (1.0, 1.0, 1.0), 1.0, "independent")

    def test_domain_clipping_preserves_requested_distances(self) -> None:
        hole = BoreholeSpec("bh", (-2.0, 5.0, 5.0), (2.0, 0.0, 0.0), 15.0, 1.0, "independent")
        clipped = clip_borehole(hole, self.domain)
        self.assertIsNotNone(clipped)
        assert clipped is not None
        self.assertEqual((clipped.entry_distance, clipped.exit_distance), (2.0, 12.0))
        self.assertEqual(clipped.start, (0.0, 5.0, 5.0))
        self.assertIs(clipped.requested, hole)

    def test_domain_clipping_uses_physical_spacing(self) -> None:
        domain = DomainSpec((10, 10, 10), (2.0, 1.0, 1.0), 2.0)
        hole = BoreholeSpec("bh", (1.0, 5.0, 5.0), (1.0, 0.0, 0.0), 30.0, 1.0, "independent")
        clipped = clip_borehole(hole, domain)
        assert clipped is not None
        self.assertEqual(clipped.exit_distance, 19.0)

    def test_no_domain_support(self) -> None:
        hole = BoreholeSpec("bh", (0.0, 12.0, 5.0), (1.0, 0.0, 0.0), 10.0, 1.0, "independent")
        self.assertIsNone(clip_borehole(hole, self.domain))

    def test_polyline_vertex_uses_arriving_segment(self) -> None:
        tunnel = TunnelSpec(((0.0, 5.0, 5.0), (5.0, 5.0, 5.0), (5.0, 8.0, 5.0)), 1.0)
        vertex = locate_station(tunnel, 5.0)
        self.assertEqual(vertex.segment_index, 0)
        self.assertEqual(vertex.direction, (1.0, 0.0, 0.0))
        after = locate_station(tunnel, 6.0)
        self.assertEqual(after.segment_index, 1)
        self.assertEqual(after.center, (5.0, 6.0, 5.0))
        with self.assertRaises(ValueError):
            locate_station(tunnel, 9.0)

    def test_zero_length_segment_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_tunnel(TunnelSpec(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), 1.0))

    def test_parallel_hole_inside_tunnel_compares(self) -> None:
        hole = BoreholeSpec("bh", (1.0, 6.0, 5.0), (1.0, 0.0, 0.0), 8.0, 1.0, "face_comparison")
        validate_borehole_tunnel(hole, self.tunnel)
        clipped = clip_borehole(hole, self.domain)
        assert clipped is not None
        overlap = find_overlap(clipped, self.tunnel)
        self.assertEqual(len(overlap), 1)
        self.assertEqual((overlap[0].borehole_start, overlap[0].borehole_end), (0.0, 8.0))
        self.assertEqual((overlap[0].tunnel_start, overlap[0].tunnel_end), (1.0, 9.0))

    def test_drilling_start_outside_tunnel_is_rejected_for_both_purposes(self) -> None:
        for purpose in ("face_comparison", "independent"):
            hole = borehole_from_endpoints(
                "bh", (1.0, 8.0, 5.0), (9.0, 8.0, 5.0), 1.0,
                "face_comparison" if purpose == "face_comparison" else "independent",
            )
            with self.subTest(purpose=purpose):
                with self.assertRaisesRegex(ValueError, "drilling start"):
                    validate_borehole_tunnel(hole, self.tunnel)

    def test_protruding_comparison_hole_is_rejected_not_clipped_into_validity(self) -> None:
        hole = BoreholeSpec("bh", (1.0, 5.0, 5.0), (1.0, 0.0, 0.0), 12.0, 1.0, "face_comparison")
        clipped = clip_borehole(hole, self.domain)
        assert clipped is not None
        with self.assertRaisesRegex(ValueError, "comparison borehole"):
            find_overlap(clipped, self.tunnel)

    def test_independent_protruding_hole_has_no_comparison(self) -> None:
        hole = BoreholeSpec("bh", (1.0, 5.0, 5.0), (0.0, 1.0, 0.0), 8.0, 1.0, "independent")
        validate_borehole_tunnel(hole, self.tunnel)
        clipped = clip_borehole(hole, self.domain)
        assert clipped is not None
        self.assertEqual(find_overlap(clipped, self.tunnel), ())

    def test_inclined_comparison_hole_is_rejected(self) -> None:
        hole = BoreholeSpec("bh", (1.0, 5.0, 5.0), (1.0, 0.1, 0.0), 2.0, 1.0, "face_comparison")
        with self.assertRaises(ValueError):
            validate_borehole_tunnel(hole, self.tunnel)

    def test_full_half_and_quarter_face_areas(self) -> None:
        for center, fraction in (((5.0, 5.0, 5.0), 1.0),
                                 ((5.0, 0.0, 5.0), 0.5),
                                 ((5.0, 0.0, 0.0), 0.25)):
            with self.subTest(center=center):
                station = TunnelStation(5.0, 0, center, (1.0, 0.0, 0.0))
                support = measure_face_support(station, 1.0, self.domain)
                self.assertAlmostEqual(support.full_area, math.pi)
                self.assertAlmostEqual(support.in_domain_area, math.pi * fraction)
                self.assertEqual(support.valid, fraction >= 0.5)

    def test_face_outside_domain_has_no_area(self) -> None:
        station = TunnelStation(0.0, 0, (-1.0, 5.0, 5.0), (1.0, 0.0, 0.0))
        support = measure_face_support(station, 1.0, self.domain)
        self.assertEqual(support.in_domain_area, 0.0)
        self.assertFalse(support.valid)

    def test_half_face_at_each_transverse_boundary(self) -> None:
        for center in ((5.0, 0.0, 5.0), (5.0, 10.0, 5.0),
                       (5.0, 5.0, 0.0), (5.0, 5.0, 10.0)):
            with self.subTest(center=center):
                station = TunnelStation(5.0, 0, center, (1.0, 0.0, 0.0))
                support = measure_face_support(station, 1.0, self.domain)
                self.assertAlmostEqual(support.in_domain_area, math.pi / 2)
                self.assertTrue(support.valid)

    def test_oblique_face_fully_inside_domain(self) -> None:
        station = TunnelStation(0.0, 0, (5.0, 5.0, 5.0), (1.0, 1.0, 1.0))
        support = measure_face_support(station, 1.0, self.domain)
        self.assertAlmostEqual(support.in_domain_area, math.pi)
        self.assertTrue(support.valid)


if __name__ == "__main__":
    unittest.main()
