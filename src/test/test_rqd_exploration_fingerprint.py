import hashlib
from dataclasses import replace
import unittest

import rfc8785

from src.rqd_exploration.fingerprint import (
    ExecutionGeometry,
    ExecutionJointSet,
    ExecutionMeasurements,
    ExecutionRuntime,
    ExecutionSnapshot,
    execution_snapshot_payload,
    fingerprint_execution_snapshot,
    fingerprint_snapshot,
)


def _execution_snapshot(
    *,
    realization_seed: int = 43,
    backend: str = "numpy",
    generator_version: str = "generator-v1",
    measurement_version: str = "measurement-v1",
    boundary_rules_version: str = "pilot-boundary-v1",
) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        geometry=ExecutionGeometry(
            domain_size_m=(60.0, 30.0, 30.0),
            grid_spacing_m=(1.0, 1.0, 1.0),
            tunnel_vertices_m=((0.0, 15.0, 15.0), (60.0, 15.0, 15.0)),
            tunnel_radius_m=5.0,
            borehole_start_m=(0.0, 15.0, 15.0),
            borehole_direction_enu=(1.0, 0.0, 0.0),
            borehole_length_m=60.0,
        ),
        fixed_jn=0.5,
        joint_sets=(
            ExecutionJointSet(
                joint_set_id="set-1",
                p32_m2_per_m3=1.0,
                size_alpha=3.0,
                size_r_min_m=0.05,
                size_r_max_m=150.0,
                mean_dip_deg=45.0,
                mean_dip_dir_deg=120.0,
                fisher_kappa=20.0,
            ),
        ),
        realization_seed=realization_seed,
        measurements=ExecutionMeasurements(
            bh_interval_m=1.0,
            face_advance_m=1.0,
            boundary_rules_version=boundary_rules_version,
        ),
        runtime=ExecutionRuntime(
            generator_version=generator_version,
            measurement_version=measurement_version,
            backend=backend,
            device_runtime=("cpu", "numpy"),
        ),
    )


class TestRQDExplorationFingerprint(unittest.TestCase):
    def test_returns_canonical_bytes_and_matching_sha256(self) -> None:
        result = fingerprint_snapshot({"z": 1.0, "a": [3, 2, 1]})

        self.assertEqual(result.canonical_bytes, b'{"a":[3,2,1],"z":1}')
        self.assertEqual(
            result.sha256_hex,
            hashlib.sha256(result.canonical_bytes).hexdigest(),
        )
        self.assertEqual(len(result.sha256_hex), 64)

    def test_equivalent_number_forms_and_object_orders_have_same_fingerprint(self) -> None:
        integer = fingerprint_snapshot({"version": 1, "name": "pilot"})
        floating_point = fingerprint_snapshot({"name": "pilot", "version": 1.0})

        self.assertEqual(integer.canonical_bytes, floating_point.canonical_bytes)
        self.assertEqual(integer.sha256_hex, floating_point.sha256_hex)

    def test_uses_jcs_number_formatting_and_utf16_property_order(self) -> None:
        result = fingerprint_snapshot({
            "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27, -0.0],
            "\ue000": 1,
            "\U00010000": 2,
        })

        self.assertEqual(
            result.canonical_bytes,
            (
                '{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27,0],'
                '"\U00010000":2,"\ue000":1}'
            ).encode("utf-8"),
        )

    def test_rejects_values_outside_the_jcs_number_domain(self) -> None:
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(rfc8785.FloatDomainError):
                fingerprint_snapshot({"value": value})

        with self.assertRaises(rfc8785.IntegerDomainError):
            fingerprint_snapshot({"seed": 2**53})

        max_safe_integer = fingerprint_snapshot({"seed": 2**53 - 1})
        self.assertEqual(max_safe_integer.canonical_bytes, b'{"seed":9007199254740991}')

    def test_preserves_array_order(self) -> None:
        first = fingerprint_snapshot({"axes": ["north", "east"]})
        second = fingerprint_snapshot({"axes": ["east", "north"]})

        self.assertNotEqual(first.canonical_bytes, second.canonical_bytes)
        self.assertNotEqual(first.sha256_hex, second.sha256_hex)

    def test_execution_snapshot_is_stable_across_retries(self) -> None:
        first_attempt = fingerprint_execution_snapshot(_execution_snapshot())
        retry = fingerprint_execution_snapshot(_execution_snapshot())

        self.assertEqual(first_attempt, retry)

    def test_execution_input_and_runtime_changes_change_fingerprint(self) -> None:
        original = fingerprint_execution_snapshot(_execution_snapshot())
        changed_seed = fingerprint_execution_snapshot(
            _execution_snapshot(realization_seed=44)
        )
        changed_backend = fingerprint_execution_snapshot(
            _execution_snapshot(backend="mlx")
        )
        changed_generator = fingerprint_execution_snapshot(
            _execution_snapshot(generator_version="generator-v2")
        )
        changed_measurement = fingerprint_execution_snapshot(
            _execution_snapshot(measurement_version="measurement-v2")
        )
        changed_boundary_rules = fingerprint_execution_snapshot(
            _execution_snapshot(boundary_rules_version="pilot-boundary-v2")
        )

        self.assertNotEqual(original.sha256_hex, changed_seed.sha256_hex)
        self.assertNotEqual(original.sha256_hex, changed_backend.sha256_hex)
        self.assertNotEqual(original.sha256_hex, changed_generator.sha256_hex)
        self.assertNotEqual(original.sha256_hex, changed_measurement.sha256_hex)
        self.assertNotEqual(original.sha256_hex, changed_boundary_rules.sha256_hex)

    def test_execution_snapshot_rejects_non_finite_or_invalid_metadata(self) -> None:
        invalid_geometry = ExecutionSnapshot(
            geometry=ExecutionGeometry(
                domain_size_m=(float("nan"), 30.0, 30.0),
                grid_spacing_m=(1.0, 1.0, 1.0),
                tunnel_vertices_m=((0.0, 15.0, 15.0), (60.0, 15.0, 15.0)),
                tunnel_radius_m=5.0,
                borehole_start_m=(0.0, 15.0, 15.0),
                borehole_direction_enu=(1.0, 0.0, 0.0),
                borehole_length_m=60.0,
            ),
            fixed_jn=0.5,
            joint_sets=_execution_snapshot().joint_sets,
            realization_seed=43,
            measurements=_execution_snapshot().measurements,
            runtime=_execution_snapshot().runtime,
        )
        with self.assertRaisesRegex(ValueError, "finite numbers"):
            fingerprint_execution_snapshot(invalid_geometry)

        invalid_metadata = _execution_snapshot(generator_version=" ")
        with self.assertRaisesRegex(ValueError, "generator_version"):
            execution_snapshot_payload(invalid_metadata)

        with self.assertRaisesRegex(TypeError, "realization_seed must be an integer"):
            fingerprint_execution_snapshot(
                replace(_execution_snapshot(), realization_seed=True)
            )

        invalid_joint = replace(_execution_snapshot().joint_sets[0], p32_m2_per_m3=True)
        with self.assertRaisesRegex(TypeError, "p32_m2_per_m3"):
            fingerprint_execution_snapshot(
                replace(_execution_snapshot(), joint_sets=(invalid_joint,))
            )

    def test_execution_payload_excludes_provenance_and_attempt_metadata(self) -> None:
        payload = execution_snapshot_payload(_execution_snapshot())

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["canonicalization"], "RFC 8785")
        self.assertEqual(payload["digest_algorithm"], "SHA-256")
        self.assertEqual(
            set(payload),
            {"schema_version", "canonicalization", "digest_algorithm", "inputs"},
        )
        self.assertNotIn("source_yaml_sha256", payload)
        self.assertNotIn("attempt", payload)


if __name__ == "__main__":
    unittest.main()
