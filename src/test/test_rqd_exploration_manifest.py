from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from pathlib import Path
import unittest

from src.rqd_exploration.config import load_config
from src.rqd_exploration.design import build_frozen_manifest, generate_lhs_design
from src.rqd_exploration.fingerprint import (
    ExecutionRuntime, fingerprint_execution_snapshot, fingerprint_snapshot,
)
from src.rqd_exploration.records import (
    PlannedBHInterval, PlannedFaceStation, PlannedScanline,
)


class TestFrozenManifest(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
        self.config = load_config(path)
        self.runtime = ExecutionRuntime(
            "fixture-generator-v1", "fixture-measurement-v1", "fixture-numpy",
            ("fixture-device", "fixture-runtime"),
        )
        # Deliberately partial fixture, not an executable pilot location plan.
        self.locations = (
            PlannedBHInterval(
                "fixture-bh", 0, 0, 1, (0, 15, 15), (1, 0, 0), 1,
            ),
            PlannedFaceStation(
                "fixture-face", 0, 0, (0, 15, 15), (1, 0, 0), 78.53981633974483,
                None,
                (PlannedScanline(0, (0, 10, 15), (0, 1, 0), 10),),
            ),
        )

    def build(self, **changes):
        arguments = {
            "manifest_id": "fixture-pilot",
            "runtime": self.runtime,
            "boundary_rules_version": "fixture-boundary-v1",
            "planned_locations": self.locations,
        }
        arguments.update(changes)
        return build_frozen_manifest(self.config, **arguments)

    def test_builds_reproducible_immutable_db_payload_without_side_effects(self) -> None:
        manifest = self.build()
        self.assertEqual(manifest, self.build())
        payload = json.loads(manifest.manifest_json)
        self.assertEqual(manifest.manifest_json.encode(),
                         fingerprint_snapshot(payload).canonical_bytes)
        self.assertEqual(len(payload["designs"]), 2)
        self.assertEqual(len(payload["design_samples"]), 10)
        self.assertEqual(len(payload["jobs"]), 10)
        self.assertNotIn("target_goals", payload)
        self.assertNotIn("target_ledger", payload)
        self.assertEqual(len(payload["planned_locations"]), 20)
        self.assertEqual(manifest.source_yaml_bytes, self.config.source_yaml_bytes)
        self.assertEqual(sha256(manifest.source_yaml_bytes).hexdigest(),
                         payload["input_provenance"]["yaml_sha256"])
        with self.assertRaises(FrozenInstanceError):
            setattr(manifest, "manifest_id", "changed")
        for forbidden in ("attempts", "observations", "derived_scores"):
            self.assertNotIn(forbidden, payload)

    def test_real_samples_are_connected_to_snapshot_and_matching_composite_keys(self) -> None:
        manifest = self.build()
        payload = json.loads(manifest.manifest_json)
        keys = set()
        for design in self.config.designs:
            result = generate_lhs_design(design)
            for sample in result.samples:
                job = next(
                    j for j in manifest.jobs
                    if j.design_id == design.design_id and j.sample_index == sample.sample_index
                )
                self.assertEqual(job.snapshot.joint_sets, sample.joint_sets)
                self.assertEqual(job.realization_seed, 43)
                self.assertEqual(job.snapshot.fixed_jn, design.fixed_jn)
                self.assertEqual(job.fingerprint, fingerprint_execution_snapshot(job.snapshot))
                self.assertEqual(job.fingerprint.sha256_hex,
                                 sha256(job.fingerprint.canonical_bytes).hexdigest())
                keys.add((job.design_id, job.block_id, job.sample_index,
                          job.realization_seed, job.fingerprint.sha256_hex))
        for item in payload["planned_locations"]:
            self.assertEqual(item["manifest_id"], manifest.manifest_id)
            self.assertIn(
                (item["design_id"], item["block_id"], item["sample_index"],
                 item["realization_seed"], item["execution_fingerprint_digest"]), keys,
            )
            self.assertNotIn("raw_rqd", item)
        for job, item in zip(manifest.jobs, payload["jobs"]):
            self.assertEqual(json.loads(job.fingerprint.canonical_bytes),
                             item["execution_snapshot"])

    def test_fingerprint_ignores_manifest_ids_provenance_and_retry_metadata(self) -> None:
        original = self.build()
        renamed = self.build(manifest_id="renamed")
        self.assertNotEqual(original.manifest_json, renamed.manifest_json)
        self.assertEqual([j.fingerprint for j in original.jobs],
                         [j.fingerprint for j in renamed.jobs])
        self.config = replace(
            self.config, source_yaml_bytes=b"fixture-source\n",
            source_yaml_sha256=sha256(b"fixture-source\n").hexdigest(),
            source_reference="fixture-other-path",
        )
        changed = self.build()
        self.assertNotEqual(original.manifest_json, changed.manifest_json)
        self.assertEqual([j.fingerprint for j in original.jobs],
                         [j.fingerprint for j in changed.jobs])

    def test_seed_and_runtime_versions_change_execution_digest(self) -> None:
        original = self.build()
        for field, value in (
            ("generator_version", "fixture-generator-v2"),
            ("measurement_version", "fixture-measurement-v2"),
            ("backend", "fixture-other-backend"),
            ("device_runtime", ("fixture-other-device",)),
        ):
            changed = self.build(runtime=replace(self.runtime, **{field: value}))
            self.assertNotEqual([j.fingerprint for j in original.jobs],
                                [j.fingerprint for j in changed.jobs])
        changed = self.build(boundary_rules_version="fixture-boundary-v2")
        self.assertNotEqual(original.jobs[0].fingerprint, changed.jobs[0].fingerprint)
        self.config = replace(self.config, designs=tuple(
            replace(d, realization_seed=44) for d in self.config.designs
        ))
        changed = self.build()
        self.assertEqual(original.jobs[0].snapshot.joint_sets,
                         changed.jobs[0].snapshot.joint_sets)
        self.assertNotEqual(original.jobs[0].fingerprint, changed.jobs[0].fingerprint)

    def test_location_order_is_canonical_and_plan_does_not_change_execution_digest(self) -> None:
        original = self.build()
        reordered = self.build(planned_locations=tuple(reversed(self.locations)))
        self.assertEqual(original, reordered)
        bh, face = self.locations
        changed = self.build(planned_locations=(replace(bh, profile_id="other"), face))
        self.assertNotEqual(original.manifest_json, changed.manifest_json)
        self.assertEqual([j.fingerprint for j in original.jobs],
                         [j.fingerprint for j in changed.jobs])

    def test_design_ids_and_sample_values_have_distinct_fingerprint_roles(self) -> None:
        original = self.build()
        self.config = replace(self.config, designs=tuple(
            replace(d, design_id=f"renamed-{d.design_id}", block_id=f"renamed-{d.block_id}")
            for d in self.config.designs
        ))
        renamed = self.build()
        self.assertNotEqual(original.manifest_json, renamed.manifest_json)
        self.assertEqual([j.fingerprint for j in original.jobs],
                         [j.fingerprint for j in renamed.jobs])
        first = self.config.designs[0]
        self.config = replace(self.config, designs=(
            replace(first, design_seed=40), self.config.designs[1],
        ))
        changed = self.build()
        self.assertNotEqual(renamed.jobs[0].fingerprint, changed.jobs[0].fingerprint)
        self.assertEqual(renamed.jobs[-1].fingerprint, changed.jobs[-1].fingerprint)

    def test_missing_or_invalid_metadata_and_locations_fail_explicitly(self) -> None:
        bh, face = self.locations
        for arguments, message in (
            ({"manifest_id": ""}, "manifest_id"),
            ({"runtime": replace(self.runtime, generator_version="")}, "generator_version"),
            ({"boundary_rules_version": ""}, "boundary_rules_version"),
            ({"planned_locations": ()}, "explicitly supplied"),
            ({"planned_locations": (bh,)}, "both BH and face"),
            ({"planned_locations": (*self.locations, bh)}, "duplicate planned"),
            ({"planned_locations": (replace(bh, planned_support_length_m=2), face)},
             "support must equal"),
            ({"planned_locations": (replace(bh, direction_enu=(2, 0, 0)), face)},
             "unit direction"),
            ({"planned_locations": (bh, replace(face, advance_distance_m=1))},
             "initial reference"),
            ({"planned_locations": (bh, replace(face, scanlines=()))}, "scanlines"),
            ({"planned_locations": (bh, replace(face, planned_support_area_m2=float("nan")))},
             "finite"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.build(**arguments)
        self.config = replace(self.config, source_yaml_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "YAML digest"):
            self.build()

    def test_all_composite_keys_are_unique_and_every_job_has_exact_plan(self) -> None:
        payload = json.loads(self.build().manifest_json)
        sample_fields = ("manifest_id", "design_id", "block_id", "sample_index")
        job_fields = (*sample_fields, "realization_seed", "execution_fingerprint_digest")
        location_fields = (*job_fields, "modality", "profile_id", "location_index")
        sample_keys = {
            tuple(item[field] for field in sample_fields)
            for item in payload["design_samples"]
        }
        job_keys = {
            tuple(item[field] for field in job_fields) for item in payload["jobs"]
        }
        location_keys = {
            tuple(item[field] for field in location_fields)
            for item in payload["planned_locations"]
        }
        self.assertEqual(len(sample_keys), 10)
        self.assertEqual(len(job_keys), 10)
        self.assertEqual(len(location_keys), 20)
        self.assertEqual({key[:4] for key in job_keys}, sample_keys)
        for job_key in job_keys:
            attached = {key[6:] for key in location_keys if key[:6] == job_key}
            self.assertEqual(attached, {("BH", "fixture-bh", 0), ("face", "fixture-face", 0)})
        for item in payload["planned_locations"]:
            self.assertNotIn("support_length_m", item)
            self.assertNotIn("support_area_m2", item)

    def test_geometry_and_measurement_settings_reach_snapshot_and_digest(self) -> None:
        original_config = self.config
        original = self.build()
        changes = (
            replace(original_config, geometry=replace(
                original_config.geometry, tunnel_radius_m=4,
            )),
            replace(original_config, geometry=replace(
                original_config.geometry, borehole_length_m=59,
            )),
            replace(original_config, measurements=replace(
                original_config.measurements, bh_interval_m=0.5,
            )),
            replace(original_config, measurements=replace(
                original_config.measurements, face_advance_m=0.5,
            )),
        )
        # Injected settings test serialization sensitivity, not new pilot YAML policy.
        for changed_config in changes:
            with self.subTest(config=changed_config):
                self.config = changed_config
                changed = self.build()
                for before, after in zip(original.jobs, changed.jobs):
                    self.assertEqual(before.snapshot.joint_sets, after.snapshot.joint_sets)
                    self.assertNotEqual(before.fingerprint, after.fingerprint)
                    self.assertEqual(
                        after.snapshot.geometry.tunnel_radius_m,
                        changed_config.geometry.tunnel_radius_m,
                    )
                    self.assertEqual(
                        after.snapshot.geometry.borehole_length_m,
                        changed_config.geometry.borehole_length_m,
                    )
                    self.assertEqual(
                        after.snapshot.measurements.bh_interval_m,
                        changed_config.measurements.bh_interval_m,
                    )
                    self.assertEqual(
                        after.snapshot.measurements.face_advance_m,
                        changed_config.measurements.face_advance_m,
                    )

    def test_block_specific_count_and_bounds_changes_are_preserved(self) -> None:
        original = self.build()
        first, second = self.config.designs
        joint_set = first.joint_sets[0]
        self.config = replace(self.config, designs=(
            replace(first, sample_count=3, joint_sets=(replace(
                joint_set, p32=replace(joint_set.p32, lower=0.02, upper=50),
            ),)),
            second,
        ))
        changed = self.build()
        payload = json.loads(changed.manifest_json)
        self.assertEqual(len(changed.jobs), 8)
        self.assertEqual(len(payload["design_samples"]), 8)
        self.assertEqual(len(payload["planned_locations"]), 16)
        self.assertEqual([j.sample_index for j in changed.jobs[:3]], [0, 1, 2])
        self.assertEqual(original.jobs[5:], changed.jobs[3:])
        bounds = payload["designs"][0]["axes"][0]["bounds"]
        self.assertEqual((bounds["lower"], bounds["upper"]), (0.02, 50))
        for job in changed.jobs[:3]:
            self.assertLessEqual(0.02, job.snapshot.joint_sets[0].p32_m2_per_m3)
            self.assertLessEqual(job.snapshot.joint_sets[0].p32_m2_per_m3, 50)

    def test_duplicate_sample_keys_and_invalid_plan_indices_are_rejected(self) -> None:
        original_config = self.config
        self.config = replace(
            original_config, designs=(*original_config.designs, original_config.designs[0]),
        )
        with self.assertRaisesRegex(ValueError, "duplicate design sample"):
            self.build()
        self.config = original_config
        bh, face = self.locations
        line = face.scanlines[0]
        for locations, message in (
            ((replace(bh, location_index=True), face), "safe integer"),
            ((replace(bh, location_index=-1), face), "safe integer"),
            ((bh, replace(face, chainage_m=1)), "requires advance"),
            ((bh, replace(face, scanlines=(line, line))), "unique ordered"),
            ((bh, replace(face, scanlines=(
                replace(line, scanline_index=1), line,
            ))), "unique ordered"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.build(planned_locations=locations)


if __name__ == "__main__":
    unittest.main()
