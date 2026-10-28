from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from src.euler_campaign.models import (
    BartonCategory, BoreholeSpec, CaseSpec, DomainSpec, JointCondition,
    JointSetSpec, TunnelSpec,
)


def _condition() -> JointCondition:
    return JointCondition(
        BartonCategory("jr", "Jr", "Good", 3.0, 4.0),
        BartonCategory("ja", "Ja", "Slight", 1.0, 2.0),
    )


def _case(joint_sets: tuple[JointSetSpec, ...] | None = None) -> CaseSpec:
    if joint_sets is None:
        joint_sets = (
            JointSetSpec(
                1, "set-1", "P32", 0.2, 3.0, 0.5, 1.0,
                90.0, 270.0, 10.0, _condition(),
            ),
        )
    return CaseSpec(
        "mlx-test",
        DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 1.0),
        joint_sets,
        (),
        TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 1.0),
    )


def _mlx_arrays(
    centers: tuple[tuple[float, float, float], ...],
    normals: tuple[tuple[float, float, float], ...],
    radii: tuple[float, ...],
):
    from src.euler_campaign.mlx_backend import MlxJointArrays, mx

    count = len(centers)
    return MlxJointArrays(
        centers=mx.array(centers, dtype=mx.float32),
        normals=mx.array(normals, dtype=mx.float32),
        radii=mx.array(radii, dtype=mx.float32),
        set_ids=mx.array((1,) * count, dtype=mx.int32),
        local_ids=mx.arange(count, dtype=mx.int32),
        conditions={1: _condition()},
    )


class TestMlxCaseJointFactory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from src.euler_campaign.mlx_backend import require_mlx_gpu
            require_mlx_gpu()
        except (ImportError, RuntimeError) as error:
            raise unittest.SkipTest(f"MLX GPU is unavailable: {error}") from error

    def test_preflight_rejects_non_gpu_device_without_fallback(self) -> None:
        from src.euler_campaign import mlx_backend
        from src.euler_campaign.simulator import EulerSimulator

        non_gpu = Mock(type=mlx_backend.mx.DeviceType.cpu)
        with patch.object(mlx_backend.mx, "default_device", return_value=non_gpu):
            with self.assertRaisesRegex(RuntimeError, "requires an MLX GPU"):
                mlx_backend.require_mlx_gpu()
            with self.assertRaisesRegex(RuntimeError, "requires an MLX GPU"):
                EulerSimulator(backend="mlx")

    def test_mlx_simulator_connects_geometry_and_separates_domain_identity(self) -> None:
        from src.euler_campaign.models import identify_domain, identify_signature
        from src.euler_campaign.simulator import EulerSimulator

        case = replace(
            _case(),
            boreholes=(
                BoreholeSpec(
                    "bh-mlx", (2.0, 5.0, 5.0), (1.0, 0.0, 0.0),
                    2.0, 1.0, "independent",
                ),
            ),
        )
        signature = identify_signature(case)
        result = EulerSimulator(backend="mlx").evaluate(signature, 21)

        self.assertEqual(result.signature_id, signature.signature_id)
        self.assertEqual(result.seed, 21)
        self.assertNotEqual(result.domain_id, identify_domain(signature, 21))
        self.assertEqual(len(result.boreholes), 1)
        self.assertEqual(result.tunnel.stop_reason, "tunnel_end")

    def test_generation_is_reproducible_and_keeps_bulk_data_in_mlx_arrays(self) -> None:
        from src.euler_campaign.mlx_backend import (
            MLX_GENERATOR_VERSION, MlxCaseJointFactory,
        )

        factory = MlxCaseJointFactory()
        first = factory.generate(_case(), 1234)
        second = factory.generate(_case(), 1234)

        self.assertEqual(MLX_GENERATOR_VERSION, "qsimex-mlx-generation-v1")
        self.assertGreater(first.count, 0)
        self.assertEqual(first.centers.tolist(), second.centers.tolist())
        self.assertEqual(first.normals.tolist(), second.normals.tolist())
        self.assertEqual(first.radii.tolist(), second.radii.tolist())
        self.assertEqual(first.set_ids.tolist(), second.set_ids.tolist())
        self.assertEqual(first.centers.__dlpack_device__()[0], 8)
        self.assertEqual(first.conditions, {1: _condition()})

    def test_samples_respect_radius_and_buffered_domain_bounds(self) -> None:
        from src.euler_campaign.mlx_backend import MlxCaseJointFactory

        generated = MlxCaseJointFactory().generate(_case(), 42)
        radii = generated.radii.tolist()
        centers = generated.centers.tolist()
        self.assertTrue(all(0.5 <= radius <= 1.0 for radius in radii))
        self.assertTrue(all(-1.0 <= value <= 11.0 for row in centers for value in row))
        for normal in generated.normals.tolist():
            self.assertAlmostEqual(sum(value * value for value in normal), 1.0, places=5)

    def test_empty_case_returns_empty_gpu_arrays(self) -> None:
        from src.euler_campaign.mlx_backend import MlxCaseJointFactory

        generated = MlxCaseJointFactory().generate(_case(()), 9)
        self.assertEqual(generated.count, 0)
        self.assertEqual(generated.centers.shape, (0, 3))
        self.assertEqual(generated.normals.shape, (0, 3))
        self.assertEqual(generated.radii.shape, (0,))
        self.assertEqual(
            generated.line_intersections(
                (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1.0,
            ),
            (),
        )

    def test_line_intersections_filter_finite_disks_and_include_endpoints(self) -> None:
        arrays = _mlx_arrays(
            (
                (0.0, 5.0, 5.0), (5.0, 5.0, 5.0),
                (10.0, 5.0, 5.0), (5.0, 6.01, 5.0),
            ),
            ((1.0, 0.0, 0.0),) * 4,
            (1.0,) * 4,
        )

        hits = arrays.line_intersections(
            (0.0, 5.0, 5.0), (2.0, 0.0, 0.0), 10.0, chunk_size=2,
        )

        self.assertEqual(
            [(hit.distance, hit.joint.joint_id) for hit in hits],
            [(0.0, "1:0"), (5.0, "1:1"), (10.0, "1:2")],
        )

    def test_batched_line_intersections_match_single_query_results(self) -> None:
        arrays = _mlx_arrays(
            (
                (0.0, 5.0, 5.0), (5.0, 5.0, 5.0),
                (10.0, 5.0, 5.0), (5.0, 6.01, 5.0),
            ),
            ((1.0, 0.0, 0.0),) * 4,
            (1.0,) * 4,
        )
        queries = (
            ((0.0, 5.0, 5.0), (1.0, 0.0, 0.0), 10.0),
            ((10.0, 5.0, 5.0), (-1.0, 0.0, 0.0), 10.0),
            ((5.0, 0.0, 5.0), (0.0, 1.0, 0.0), 10.0),
        )

        batched = arrays.line_intersections_many(
            queries, chunk_size=2, query_batch_size=2,
        )
        individual = tuple(arrays.line_intersections(*query) for query in queries)

        self.assertEqual(batched, individual)
        self.assertEqual(
            tuple(
                tuple(hit.joint.joint_id for hit in hits)
                for hits in batched
            ),
            (("1:0", "1:1", "1:2"), ("1:2", "1:1", "1:0"), ()),
        )
        self.assertEqual(
            tuple(
                tuple(hit.distance for hit in hits)
                for hits in batched
            ),
            ((0.0, 5.0, 10.0), (0.0, 5.0, 10.0), ()),
        )

    def test_face_and_scanline_queries_share_joint_chunk_pass(self) -> None:
        from src.euler_campaign import mlx_backend
        from src.euler_campaign.geometry import TunnelStation
        from src.euler_campaign.models import DomainSpec, JointProfileEvidence
        from src.euler_campaign.qprime import calculate_qprime

        arrays = _mlx_arrays(
            ((5.0, 5.0, 5.0),),
            ((0.0, 1.0, 0.0),),
            (1.0,),
        )
        face = TunnelStation(0.0, 0, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0))
        domain = DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0)
        query = ((5.0, 4.0, 5.0), (0.0, 1.0, 0.0), 2.0)
        original_kernel = mlx_backend._line_hit_arrays
        with patch.object(
            mlx_backend, "_line_hit_arrays", wraps=original_kernel,
        ) as line_kernel:
            scanlines, face_joints = arrays.face_and_line_intersections(
                face, 2.0, domain, (query,), chunk_size=1,
            )

        self.assertEqual(line_kernel.call_count, 1)
        self.assertEqual(scanlines, (arrays.line_intersections(*query),))
        self.assertEqual(face_joints, arrays.face_intersections(face, 2.0, domain))
        self.assertEqual(len(face_joints), 1)
        self.assertIsInstance(face_joints[0], JointProfileEvidence)
        result = calculate_qprime(100.0, domain.jn, face_joints)
        self.assertEqual(result.provenance.selected_joint_id, "1:0")

    def test_face_intersections_handle_crossing_and_coplanar_disks_in_domain(self) -> None:
        from src.euler_campaign.geometry import TunnelStation
        from src.euler_campaign.models import DomainSpec

        domain = DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0)
        crossing = _mlx_arrays(
            ((5.0, 5.0, 5.0),),
            ((0.0, 1.0, 0.0),),
            (1.0,),
        )
        face = TunnelStation(0.0, 0, (5.0, 5.0, 5.0), (1.0, 0.0, 0.0))
        self.assertEqual(
            tuple(joint.joint_id for joint in crossing.face_intersections(
                face, 2.0, domain, chunk_size=1,
            )),
            ("1:0",),
        )

        coplanar = _mlx_arrays(
            ((5.0, 5.0, 5.0),),
            ((1.0, 0.0, 0.0),),
            (1.0,),
        )
        self.assertEqual(
            tuple(joint.joint_id for joint in coplanar.face_intersections(
                face, 2.0, domain, chunk_size=1,
            )),
            ("1:0",),
        )

    def test_face_intersections_exclude_disk_overlap_outside_domain(self) -> None:
        from src.euler_campaign.geometry import TunnelStation
        from src.euler_campaign.models import DomainSpec

        domain = DomainSpec((10, 5, 10), (1.0, 1.0, 1.0), 2.0)
        face = TunnelStation(0.0, 0, (5.0, 4.0, 5.0), (1.0, 0.0, 0.0))
        coplanar = _mlx_arrays(
            ((5.0, 6.8, 5.0),),
            ((1.0, 0.0, 0.0),),
            (1.0,),
        )
        self.assertEqual(coplanar.face_intersections(face, 2.0, domain), ())

        crossing_outside = _mlx_arrays(
            ((1.0, 5.0, 7.6),),
            ((0.0, 1.0, 0.0),),
            (1.5,),
        )
        clipped_domain = DomainSpec((10, 10, 6), (1.0, 1.0, 1.0), 2.0)
        clipped_face = TunnelStation(0.0, 0, (1.0, 5.0, 5.0), (1.0, 0.0, 0.0))
        self.assertEqual(
            crossing_outside.face_intersections(
                clipped_face, 2.0, clipped_domain,
            ),
            (),
        )
