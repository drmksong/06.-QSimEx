import unittest

from src.euler_campaign.dfn import CaseJointFactory, DiskJointGeometry
from src.euler_campaign.geometry import TunnelStation
from src.euler_campaign.models import (
    BartonCategory, BoreholeSpec, CaseSpec, DomainSpec, JointCondition,
    JointRealization, JointSetSpec, TunnelSpec, identify_signature,
)
from src.euler_campaign.simulator import EulerSimulator


def _condition() -> JointCondition:
    return JointCondition(
        BartonCategory("jr-good", "Jr", "Good", 3.0, 4.0),
        BartonCategory("ja-slight", "Ja", "Slight", 1.0, 2.0),
    )


def _case() -> CaseSpec:
    return CaseSpec(
        "dfn-test",
        DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0),
        (
            JointSetSpec(
                1, "set-1", "P32", 0.2, 3.0, 0.5, 1.0,
                90.0, 270.0, 10.0, _condition(),
            ),
        ),
        (BoreholeSpec(
            "bh-1", (3.0, 5.0, 5.0), (1.0, 0.0, 0.0), 4.0, 1.0,
            "face_comparison",
        ),),
        TunnelSpec(((3.0, 5.0, 5.0), (7.0, 5.0, 5.0)), 1.0),
    )


class TestDiskJointGeometry(unittest.TestCase):
    def setUp(self) -> None:
        self.joint = JointRealization(
            "set:0", 1, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0), 1.0, _condition(),
        )
        self.geometry = DiskJointGeometry((self.joint,))

    def test_line_intersection_uses_finite_disk_and_returns_distance(self) -> None:
        hits = self.geometry.line_intersections(
            (0.0, 5.0, 5.0), (2.0, 0.0, 0.0), 10.0,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].distance, 5.0)
        self.assertIs(hits[0].joint, self.joint)

    def test_line_misses_disk_and_out_of_interval_hit(self) -> None:
        self.assertEqual(
            self.geometry.line_intersections((0.0, 6.01, 5.0), (1.0, 0.0, 0.0), 10.0),
            (),
        )
        self.assertEqual(
            self.geometry.line_intersections((6.0, 5.0, 5.0), (1.0, 0.0, 0.0), 1.0),
            (),
        )

    def test_face_intersection_requires_shared_disk_segment_inside_domain(self) -> None:
        face_joint = JointRealization(
            "set:face", 1, (1.0, 5.0, 7.6), (0.0, 1.0, 0.0), 1.5, _condition(),
        )
        geometry = DiskJointGeometry((face_joint,))
        face = TunnelStation(0.0, 0, (1.0, 5.0, 5.0), (1.0, 0.0, 0.0))
        clipped_domain = DomainSpec((10, 10, 6), (1.0, 1.0, 1.0), 2.0)

        # The disks overlap above z=6, but their supported intersection is empty.
        self.assertEqual(geometry.face_intersections(face, 2.0, clipped_domain), ())

    def test_face_intersection_finds_crossing_disks(self) -> None:
        face_joint = JointRealization(
            "set:face", 1, (5.0, 5.0, 5.0), (0.0, 1.0, 0.0), 1.0, _condition(),
        )
        geometry = DiskJointGeometry((face_joint,))
        face = TunnelStation(0.0, 0, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0))
        domain = DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0)

        self.assertEqual(geometry.face_intersections(face, 2.0, domain), (face_joint,))

    def test_coplanar_disk_overlap_in_supported_face_is_included(self) -> None:
        face_joint = JointRealization(
            "set:coplanar", 1, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0), 1.0, _condition(),
        )
        geometry = DiskJointGeometry((face_joint,))
        face = TunnelStation(0.0, 0, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0))
        domain = DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0)

        self.assertEqual(geometry.face_intersections(face, 2.0, domain), (face_joint,))

    def test_coplanar_overlap_outside_domain_is_excluded(self) -> None:
        face_joint = JointRealization(
            "set:coplanar", 1, (5.0, 6.8, 5.0), (1.0, 0.0, 0.0), 1.0, _condition(),
        )
        geometry = DiskJointGeometry((face_joint,))
        face = TunnelStation(0.0, 0, (5.0, 4.0, 5.0), (1.0, 0.0, 0.0))
        domain = DomainSpec((10, 5, 10), (1.0, 1.0, 1.0), 2.0)

        self.assertEqual(geometry.face_intersections(face, 2.0, domain), ())


class TestCaseJointFactory(unittest.TestCase):
    def test_generation_is_reproducible_and_preserves_set_condition(self) -> None:
        case = _case()
        factory = CaseJointFactory()

        first = factory.generate(case, 1234)
        second = factory.generate(case, 1234)
        self.assertEqual(first, second)
        self.assertTrue(first.joints)
        self.assertTrue(all(joint.condition == case.joint_sets[0].condition for joint in first.joints))

    def test_case_without_joint_sets_produces_empty_dfn(self) -> None:
        case = _case()
        empty_case = CaseSpec(
            case.case_id, case.domain, (), case.boreholes, case.tunnel,
        )
        geometry = CaseJointFactory().generate(empty_case, 1)
        self.assertEqual(geometry.joints, ())

    def test_simulator_uses_generated_geometry_for_case_profiles(self) -> None:
        signature = identify_signature(_case())

        result = EulerSimulator().evaluate(signature, 1234)

        self.assertEqual(result.signature_id, signature.signature_id)
        self.assertEqual(result.seed, 1234)
        self.assertEqual(len(result.boreholes), 1)
        self.assertEqual(result.tunnel.stop_reason, "tunnel_end")
