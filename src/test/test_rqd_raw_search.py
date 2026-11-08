from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch
import yaml

from src.rqd_exploration.main_analysis import BHPoint, SeedProfile
from src.rqd_exploration.main_controller import PREVIEW_RUNTIME, reference_snapshot
from src.rqd_exploration.main_design import (
    expected_joint_counts,
    input_identity,
    snapshot_from_dict,
)
from src.rqd_exploration.main_policy import load_main_config
from src.rqd_exploration.main_store import initialize_main_store
from src.rqd_exploration.design import generate_lhs_design
from src.rqd_exploration.measurement import (
    MeasurementEvidence,
    RawBHObservation,
    RawFaceObservation,
)
from src.rqd_exploration.p32_store import _case_ids_for_manifest
from src.rqd_exploration.runner import _case_for_job
from src.rqd_exploration.store import initialize_store, store_manifest
from src.rqd_exploration.raw_rqd_search import (
    RAW_RQD_COORDINATE_PARAMETERS,
    RawRqdCondition,
    RawRqdController,
    _assert_raw_database_is_separate,
    lhs_signature_records,
    load_raw_rqd_config,
    main,
    raw_bh_records,
    raw_rqd_config,
    summarize_raw_rqd,
)


class TestRawRqdSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[2]

    def test_loads_raw_jn15_jn20_baseline3_input(self) -> None:
        path = self.repo_root / "config/rqd_exploration_main_baseline3.yml"

        config = load_raw_rqd_config(path)

        self.assertEqual(config.source_yaml_bytes, path.read_bytes())
        self.assertEqual(config.geometry.domain_size_m, (30.0, 20.0, 20.0))
        self.assertEqual(
            (config.measurements.bh_interval_m, config.measurements.face_advance_m),
            (1.0, 1.0),
        )
        self.assertEqual(
            [(d.fixed_jn, d.sample_count, d.design_seed, d.realization_seed,
              len(d.joint_sets)) for d in config.designs],
            [(15.0, 5, 36, 43, 4), (20.0, 5, 40, 43, 5)],
        )
        for design in config.designs:
            self.assertEqual((design.mean_dip_deg.lower, design.mean_dip_deg.upper),
                             (0.0, 90.0))
            self.assertEqual((design.mean_dip_dir_deg.lower,
                              design.mean_dip_dir_deg.upper,
                              design.mean_dip_dir_deg.upper_inclusive),
                             (0.0, 360.0, False))
            self.assertEqual((design.size_alpha.bounds.lower,
                              design.size_alpha.bounds.upper), (2.5, 4.0))
            self.assertEqual((design.fisher_kappa.bounds.lower,
                              design.fisher_kappa.bounds.upper), (0.0, 50.0))
            for joint_set in design.joint_sets:
                self.assertEqual((joint_set.p32.lower, joint_set.p32.upper,
                                  joint_set.p32.coordinate),
                                 (1.0, 100.0, "log"))
                for bounds in (joint_set.size_r_min_m, joint_set.size_r_max_m):
                    self.assertEqual((bounds.lower, bounds.upper, bounds.coordinate),
                                     (1.0, 150.0, "log"))

    def test_raw_loader_rejects_missing_or_duplicate_jn_designs(self) -> None:
        source = self.repo_root / "config/rqd_exploration_main_baseline3.yml"
        payload = yaml.safe_load(source.read_bytes())
        duplicate_jn15 = {
            **payload["designs"][1],
            "fixed_jn": 15,
            "joint_sets": payload["designs"][0]["joint_sets"],
        }
        invalid_inputs = (
            payload["designs"][:1],
            [payload["designs"][0], duplicate_jn15],
        )

        with TemporaryDirectory() as directory:
            for index, designs in enumerate(invalid_inputs):
                with self.subTest(index=index):
                    payload["designs"] = designs
                    path = Path(directory) / f"invalid-{index}.yml"
                    path.write_text(yaml.safe_dump(payload, sort_keys=False))
                    with self.assertRaisesRegex(
                        ValueError, "exactly one Jn15 and one Jn20",
                    ):
                        load_raw_rqd_config(path)
                    payload = yaml.safe_load(source.read_bytes())

    def bh_observation(
        self,
        *,
        location_index: int = 0,
        raw_rqd: float = 5.0,
        support: float = 1.0,
        valid: bool = True,
        exclusion_reason: str | None = None,
    ) -> RawBHObservation:
        return RawBHObservation(
            "pilot-bh", location_index, float(location_index),
            float(location_index + 1), raw_rqd, support,
            "deere_direct_rqd", "test", valid, exclusion_reason, False,
            MeasurementEvidence(
                0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1.0, (),
            ),
        )

    def test_extracts_only_bh_and_preserves_raw_rqd_and_exclusions(self) -> None:
        bh = self.bh_observation(raw_rqd=5.0)
        face = RawFaceObservation(
            "tunnel-face", 0, 0.0, 2.0, 1.0, None,
            "priest_hudson_rqd", "test", True, None, False, (),
        )

        records = raw_bh_records("sig-a", 43, (bh, face))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].raw_rqd, 5.0)
        self.assertEqual(records[0].realization_seed, 43)
        self.assertEqual(records[0].support_length_m, 1.0)

        excluded = raw_bh_records(
            "sig-a", 43,
            (self.bh_observation(
                raw_rqd=8.0, support=0.0, valid=False,
                exclusion_reason="no valid scanline",
            ),),
        )
        self.assertFalse(excluded[0].is_valid)
        self.assertEqual(excluded[0].raw_rqd, 8.0)

    def test_summarizes_raw_rqd_without_qprime_clamping(self) -> None:
        records = raw_bh_records("sig-a", 43, (
            self.bh_observation(raw_rqd=5.0),
            self.bh_observation(location_index=1, raw_rqd=12.0),
            self.bh_observation(
                location_index=2, raw_rqd=1.0, support=0.0,
                valid=False, exclusion_reason="invalid",
            ),
        ))

        (summary,) = summarize_raw_rqd(records)

        self.assertEqual(summary.observation_count, 3)
        self.assertEqual(summary.supported_valid_count, 2)
        self.assertEqual(summary.raw_rqd_min, 5.0)
        self.assertEqual(summary.raw_rqd_max, 12.0)
        self.assertEqual(summary.support_weighted_mean_rqd, 8.5)
        self.assertEqual(summary.raw_rqd_population_sd, 3.5)
        self.assertEqual(summary.seeds_with_supported_observations, (43,))
        self.assertFalse(hasattr(summary, "raw_rqd_at_or_below_target_count"))

    def test_raw_rqd_condition_has_no_threshold_or_pass_semantics(self) -> None:
        condition = RawRqdCondition(fixed_jn=4.0)

        self.assertEqual(condition.key, "raw-rqd/4/pilot-bh")
        self.assertFalse(hasattr(condition, "target_rqd"))
        self.assertFalse(hasattr(condition, "contains"))

    def test_interpolation_obeys_log_linear_and_circular_coordinates(self) -> None:
        design = raw_rqd_config(load_raw_rqd_config(
            self.repo_root / "config/rqd_exploration_main_baseline3.yml"
        )).templates[15.0]
        self.assertAlmostEqual(
            RawRqdController._interpolate_coordinate(
                1.0, 100.0, 0.5,
                design.joint_sets[0].p32,
                "p32_m2_per_m3",
            ),
            10.0,
        )
        self.assertAlmostEqual(
            RawRqdController._interpolate_coordinate(
                0.0, 90.0, 0.5, design.mean_dip_deg, "mean_dip_deg"),
            45.0,
        )
        self.assertAlmostEqual(
            RawRqdController._interpolate_coordinate(
                350.0, 10.0, 0.5,
                design.mean_dip_dir_deg,
                "mean_dip_dir_deg",
            ),
            0.0,
        )

    def test_lhs_preview_is_deterministic_and_does_not_run_simulation(self) -> None:
        config_path = self.repo_root / "config/rqd_exploration_main_baseline3.yml"
        config = load_raw_rqd_config(config_path)
        self.assertEqual(lhs_signature_records(config), lhs_signature_records(config))

        output = StringIO()
        with redirect_stdout(output):
            status = main(["preview", "--config", str(config_path)])
        payload = json.loads(output.getvalue())
        default_output = StringIO()
        with redirect_stdout(default_output):
            default_status = main(["preview"])
        default_payload = json.loads(default_output.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(default_status, 0)
        self.assertEqual(default_payload, payload)
        self.assertEqual(
            set(payload["fixed_jn_values"]),
            {15.0, 20.0},
        )
        self.assertEqual(
            payload["candidate_count"],
            sum(design.sample_count for design in config.designs),
        )
        self.assertEqual(payload["initial_signatures_by_jn"], {"15": 5, "20": 5})
        self.assertEqual(payload["realization"]["seeds_by_jn"], {"15": 43, "20": 43})
        self.assertEqual(payload["geometry"]["domain_size_m"], [30.0, 20.0, 20.0])
        self.assertEqual(payload["measurements"]["bh_interval_m"], 1.0)
        self.assertEqual(payload["measurements"]["face_advance_m"], 1.0)
        self.assertEqual(payload["handoff"], "initial_cohort_review")
        self.assertEqual(
            payload["coordinate_parameters"],
            list(RAW_RQD_COORDINATE_PARAMETERS),
        )
        self.assertEqual(payload["measurement_scope"], "BH-only")
        self.assertEqual(
            payload["update_method"], "hybrid-global-lhs-response-gap-v1")
        self.assertEqual(payload["objective"], "continuous_raw_bh_rqd_response")
        self.assertEqual(payload["realization"]["seed"], 43)
        self.assertIsNone(payload["realization"]["verification"])
        self.assertEqual(
            payload["refinement_metric"], "support_weighted_mean_raw_rqd")
        self.assertFalse(payload["simulation_started"])
        self.assertFalse(payload["database_written"])
        self.assertTrue(all("joint_sets" in item for item in payload["candidates"]))
        self.assertTrue(all("raw_rqd" not in item for item in payload["candidates"]))

    def test_preview_honors_input_configured_design_fields(self) -> None:
        source = self.repo_root / "config/rqd_exploration_main_baseline3.yml"
        payload = yaml.safe_load(source.read_bytes())
        payload["geometry"]["domain_size_m"][0] = 31
        payload["geometry"]["tunnel_vertices_m"] = [[0, 15, 15], [31, 15, 15]]
        payload["geometry"]["borehole"]["length_m"] = 31
        payload["measurements"]["bh_interval_m"] = 2
        payload["designs"][0].update(
            design_id="raw-rqd-jn15-test", block_id="input-block-15",
            sample_count=2, design_seed=101, realization_seed=17)
        payload["designs"][1].update(
            design_id="raw-rqd-jn20-test", block_id="input-block-20",
            sample_count=3, design_seed=202, realization_seed=19)
        for design in payload["designs"]:
            design["orientation_bounds"]["mean_dip_deg"].update(
                lower=10, upper=80)
            design["orientation_bounds"]["mean_dip_dir_deg"].update(
                lower=30, upper=300)
            design["shape_randomization"]["size_alpha"]["bounds"] = [2.7, 3.8]
            design["shape_randomization"]["fisher_kappa"]["bounds"] = [1, 45]
            for joint_set in design["joint_sets"]:
                joint_set["p32"].update(lower=2, upper=50)
                joint_set["size_r_min_m"].update(lower=2, upper=90)
                joint_set["size_r_max_m"].update(lower=2, upper=90)

        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "raw-rqd-input.yml"
            config_path.write_text(yaml.safe_dump(payload, sort_keys=False))
            input_config = load_raw_rqd_config(config_path)
            output = StringIO()
            with redirect_stdout(output):
                status = main(["preview", "--config", str(config_path)])

        preview = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(preview["candidate_count"], 5)
        self.assertEqual(preview["initial_signatures_by_jn"], {"15": 2, "20": 3})
        self.assertEqual(preview["realization"]["seeds_by_jn"], {"15": 17, "20": 19})
        self.assertEqual(preview["geometry"]["domain_size_m"], [31.0, 20.0, 20.0])
        self.assertEqual(preview["measurements"]["bh_interval_m"], 2.0)
        self.assertEqual(preview["measurements"]["face_advance_m"], 1.0)
        self.assertEqual(
            {item["design_seed"] for item in preview["candidates"]}, {101, 202})
        self.assertEqual(
            {
                f"{item['fixed_jn']:g}": (item["design_id"], item["block_id"])
                for item in preview["candidates"]
            },
            {
                "15": ("raw-rqd-jn15-test", "input-block-15"),
                "20": ("raw-rqd-jn20-test", "input-block-20"),
            },
        )
        for candidate in preview["candidates"]:
            for joint_set in candidate["joint_sets"]:
                self.assertGreaterEqual(joint_set["mean_dip_deg"], 10.0)
                self.assertLessEqual(joint_set["mean_dip_deg"], 80.0)
                self.assertGreaterEqual(joint_set["mean_dip_dir_deg"], 30.0)
                self.assertLess(joint_set["mean_dip_dir_deg"], 300.0)
                self.assertGreaterEqual(joint_set["p32_m2_per_m3"], 2.0)
                self.assertLessEqual(joint_set["p32_m2_per_m3"], 50.0)
                self.assertGreaterEqual(joint_set["size_r_min_m"], 2.0)
                self.assertLessEqual(joint_set["size_r_min_m"], 90.0)
                self.assertGreaterEqual(joint_set["size_r_max_m"], 2.0)
                self.assertLessEqual(joint_set["size_r_max_m"], 90.0)
                self.assertGreaterEqual(joint_set["size_alpha"], 2.7)
                self.assertLessEqual(joint_set["size_alpha"], 3.8)
                self.assertGreaterEqual(joint_set["fisher_kappa"], 1.0)
                self.assertLessEqual(joint_set["fisher_kappa"], 45.0)

        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)
        with TemporaryDirectory() as output_dir:
            controller = RawRqdController(
                connection, input_config, None, PREVIEW_RUNTIME,
                output_dir=Path(output_dir),
            )
            for target in controller.targets:
                design = controller.config.templates[target.fixed_jn]
                reference = replace(
                    reference_snapshot(controller.config, PREVIEW_RUNTIME),
                    fixed_jn=target.fixed_jn,
                    joint_sets=generate_lhs_design(design).samples[0].joint_sets,
                )
                axis_bounds = {
                    parameter: (lower, upper, upper_inclusive)
                    for _, (parameter, _, _, lower, upper, upper_inclusive)
                    in controller._signature_axes(reference)
                }
                self.assertEqual(
                    axis_bounds["p32_m2_per_m3"], (2.0, 50.0, True))
                self.assertEqual(
                    axis_bounds["size_r_min_m"], (2.0, 90.0, True))
                self.assertEqual(
                    axis_bounds["size_r_max_m"], (2.0, 90.0, True))
                self.assertEqual(
                    axis_bounds["mean_dip_deg"], (10.0, 80.0, True))
                self.assertEqual(
                    axis_bounds["mean_dip_dir_deg"], (30.0, 300.0, False))
                controller._plan_round(target)
                candidate_ids = controller.state["round"]["candidate_ids"]
                self.assertEqual(len(candidate_ids), design.sample_count)
                self.assertEqual(
                    {item["seed"] for item in controller.state["queue"]},
                    {design.realization_seed},
                )
                self.assertTrue(all(
                    controller.state["inputs"][identity]["geometry"]["domain_size_m"]
                    == (31.0, 20.0, 20.0)
                    for identity in candidate_ids
                ))
                preview_sets = [
                    item["joint_sets"] for item in preview["candidates"]
                    if item["fixed_jn"] == target.fixed_jn
                ]
                execution_sets = [
                    list(controller.state["inputs"][identity]["joint_sets"])
                    for identity in candidate_ids
                ]
                self.assertEqual(execution_sets, preview_sets)
                manifest, execution_input = controller._make_manifest(
                    candidate_ids[0], design.realization_seed)
                execution_snapshot = manifest.jobs[0].snapshot
                expected_case_id = (
                    f"{controller.run_prefix}-input-{candidate_ids[0]}")
                self.assertEqual(manifest.jobs[0].design_id, design.design_id)
                self.assertEqual(manifest.jobs[0].block_id, design.block_id)
                self.assertEqual(manifest.jobs[0].case_id, expected_case_id)
                payload_job = json.loads(manifest.manifest_json)["jobs"][0]
                self.assertEqual(payload_job["design_id"], design.design_id)
                self.assertEqual(payload_job["block_id"], design.block_id)
                self.assertEqual(payload_job["case_id"], expected_case_id)
                generated_case = _case_for_job(
                    execution_input, manifest.jobs[0], allow_constant_radius=True)
                self.assertEqual(generated_case.case_id, expected_case_id)
                self.assertEqual(
                    execution_snapshot.geometry.domain_size_m, (31.0, 20.0, 20.0))
                self.assertEqual(execution_snapshot.measurements.bh_interval_m, 2.0)
                self.assertEqual(execution_snapshot.measurements.face_advance_m, 1.0)
                self.assertEqual(execution_snapshot.realization_seed, design.realization_seed)
                self.assertEqual(
                    set(controller._expected_joint_counts(execution_snapshot)),
                    {joint_set.joint_set_id for joint_set in design.joint_sets},
                )
                self.assertEqual(
                    [asdict(item) for item in execution_snapshot.joint_sets],
                    list(controller.state["inputs"][candidate_ids[0]]["joint_sets"]),
                )
                self.assertEqual(execution_input.designs[0].design_seed, design.design_seed)
                store_manifest(connection, manifest)
                job_key = (
                    manifest.jobs[0].manifest_id,
                    manifest.jobs[0].design_id,
                    manifest.jobs[0].block_id,
                    manifest.jobs[0].sample_index,
                    manifest.jobs[0].realization_seed,
                    manifest.jobs[0].fingerprint.sha256_hex,
                )
                self.assertEqual(
                    _case_ids_for_manifest(connection, manifest.manifest_id)[job_key],
                    expected_case_id,
                )
                controller.state["queue"].clear()
                controller.state["round"] = None
        connection.close()

    def test_initial_lhs_counts_use_baseline3_joint_set_bounds(self) -> None:
        config = load_raw_rqd_config(
            self.repo_root / "config/rqd_exploration_main_baseline3.yml")
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)

        with TemporaryDirectory() as output_dir:
            controller = RawRqdController(
                connection, config, None, PREVIEW_RUNTIME,
                output_dir=Path(output_dir),
            )
            design = controller.config.templates[15.0]
            sample = generate_lhs_design(design).samples[0]
            snapshot = replace(
                reference_snapshot(controller.config, PREVIEW_RUNTIME),
                fixed_jn=design.fixed_jn,
                joint_sets=sample.joint_sets,
                realization_seed=design.realization_seed,
            )
            self.assertGreater(snapshot.joint_sets[1].p32_m2_per_m3, 10.0)
            with self.assertRaisesRegex(
                ValueError, "outside bounds: set-2/p32_m2_per_m3",
            ):
                expected_joint_counts(snapshot)

            counts = controller._expected_joint_counts(snapshot)
            self.assertEqual(
                set(counts),
                {joint_set.joint_set_id for joint_set in design.joint_sets},
            )
            identity = input_identity(snapshot)
            controller.state["inputs"][identity] = asdict(snapshot)
            reached_start = []

            class StartReserved(Exception):
                pass

            def stop_after_start(*args, **kwargs):
                kwargs["before_start"](args[1].jobs[0], False)
                reached_start.append(True)
                raise StartReserved

            with patch(
                "src.rqd_exploration.main_controller.execute_frozen_job",
                side_effect=stop_after_start,
            ):
                with self.assertRaises(StartReserved):
                    controller._perform({
                        "input_id": identity,
                        "seed": design.realization_seed,
                        "role": "initial_lhs",
                    })
            self.assertEqual(reached_start, [True])

        connection.close()

    def test_initial_cohort_is_preserved_at_review_handoff(self) -> None:
        config = load_raw_rqd_config(
            self.repo_root / "config/rqd_exploration_main_baseline3.yml")
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)

        class InMemoryRawRqdController(RawRqdController):
            def _perform(self, task):
                identity, seed = task["input_id"], task["seed"]
                rank = len(self.profiles)
                self.profiles[identity] = {
                    self.profile_id: {
                        seed: SeedProfile(
                            seed, (BHPoint(0.0, 1.0, 50.0 - rank, 1.0),),
                        )
                    }
                }

        with TemporaryDirectory() as output_dir:
            controller = InMemoryRawRqdController(
                connection, config, None, PREVIEW_RUNTIME,
                output_dir=Path(output_dir),
            )
            summary = controller.run()

            self.assertEqual(summary["phase"], "paused")
            self.assertEqual(summary["reason"], "initial_cohort_review")
            self.assertEqual(summary["signature_count"], 10)
            self.assertEqual(
                {jn: len(signatures)
                 for jn, signatures in summary["signatures_by_jn"].items()},
                {"15": 5, "20": 5},
            )
            self.assertEqual(set(summary["centers_by_jn"]), {"15", "20"})
            self.assertEqual(controller.state["round_index"], 2)
            self.assertIsNone(controller.state["round"])
            self.assertEqual(controller.state["queue"], [])
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0], 0)
            preview_by_jn = {
                jn: [item["joint_sets"] for item in lhs_signature_records(config)
                     if f"{item['fixed_jn']:g}" == jn]
                for jn in ("15", "20")
            }
            execution_by_jn = {
                jn: [
                    list(snapshot["joint_sets"])
                    for snapshot in controller.state["inputs"].values()
                    if f"{snapshot['fixed_jn']:g}" == jn
                ]
                for jn in ("15", "20")
            }
            self.assertEqual(execution_by_jn, preview_by_jn)

            repeated = controller.run()

        self.assertEqual(repeated["reason"], "initial_cohort_review")
        self.assertEqual(repeated["signature_count"], 10)
        self.assertEqual(controller.state["round_index"], 2)
        connection.close()

    def test_followup_batch_requires_release_and_pauses_for_review(self) -> None:
        config = load_raw_rqd_config(
            self.repo_root / "config/rqd_exploration_main_baseline3.yml")
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)

        class InMemoryRawRqdController(RawRqdController):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.initial_counts = {"15": 0, "20": 0}
                self.followup_counts = {"15": 0, "20": 0}

            def _perform(self, task):
                identity, seed = task["input_id"], task["seed"]
                fixed_jn = self.state["inputs"][identity]["fixed_jn"]
                jn_key = f"{fixed_jn:g}"
                if task["role"] == "initial_lhs":
                    means_by_jn = {
                        "15": (1.0, 22.0, 23.0, 89.0, 92.0),
                        "20": (1.0, 7.0, 8.0, 64.0, 66.0),
                    }
                    index = self.initial_counts[jn_key]
                    self.initial_counts[jn_key] += 1
                    value = means_by_jn[jn_key][index]
                else:
                    self.followup_counts[jn_key] += 1
                    value = 5.0 + self.followup_counts[jn_key]
                points = tuple(
                    BHPoint(float(index), float(index + 1), value, 1.0)
                    for index in range(30)
                )
                self.profiles[identity] = {
                    self.profile_id: {seed: SeedProfile(seed, points)}
                }

        with TemporaryDirectory() as output_dir:
            controller = InMemoryRawRqdController(
                connection, config, None, PREVIEW_RUNTIME,
                output_dir=Path(output_dir),
            )
            initial = controller.run()
            repeated = controller.run()
            self.assertEqual(initial["reason"], "initial_cohort_review")
            self.assertEqual(repeated["reason"], "initial_cohort_review")
            self.assertEqual(initial["signature_count"], 10)
            original_ids = set(controller.state["inputs"])

            summary = controller.run(continue_from_review=True)

        self.assertEqual(summary["reason"], "continuation_batch_review")
        self.assertEqual(summary["signature_count"], 30)
        self.assertEqual(summary["followup_batch_index"], 1)
        self.assertEqual(controller.followup_counts, {"15": 10, "20": 10})
        self.assertEqual(
            {jn: len(signatures)
             for jn, signatures in summary["signatures_by_jn"].items()},
            {"15": 15, "20": 15},
        )
        batch = summary["last_followup_batch"]
        self.assertEqual(batch["batch_index"], 1)
        for jn in ("15", "20"):
            candidates = [
                candidate for candidate in batch["candidates"]
                if f"{candidate['fixed_jn']:g}" == jn
            ]
            self.assertEqual(len(candidates), 10)
            self.assertEqual(
                [candidate["role"] for candidate in candidates].count(
                    "global_space_filling"), 5)
            self.assertEqual(
                [candidate["role"] for candidate in candidates].count(
                    "response_gap_refinement"), 5)
            self.assertEqual(len(batch["completed_signatures_by_jn"][jn]), 10)
            for candidate in candidates:
                controller._validate_generating_input(
                    snapshot_from_dict(
                        controller.state["inputs"][candidate["input_id"]]))
        new_ids = {
            candidate["input_id"] for candidate in batch["candidates"]
        }
        self.assertEqual(len(new_ids), 20)
        self.assertTrue(original_ids.isdisjoint(new_ids))
        first_signature = next(
            value for value in summary["raw_rqd_by_signature"].values()
            if value["raw_rqd_min"] == 1.0)
        self.assertEqual(first_signature["supported_valid_observation_count"], 30)
        self.assertEqual(first_signature["support_weighted_mean_rqd"], 1.0)
        self.assertEqual(first_signature["raw_rqd_population_sd"], 0.0)
        self.assertEqual(
            len(next(
                observations for observations in
                summary["raw_bh_observations_by_signature"].values()
                if len(observations) == 30
            )),
            30,
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0], 0)
        event_kind, payload = connection.execute(
            "SELECT kind,payload FROM main_control_events "
            "ORDER BY event_index DESC LIMIT 1").fetchone()
        self.assertEqual(event_kind, "pause")
        self.assertEqual(
            json.loads(payload)["last_followup_batch"]["batch_index"], 1)
        connection.close()

    def test_raw_controller_uses_one_seed_without_pass_or_verification_state(self) -> None:
        config = load_main_config(self.repo_root / "config/rqd_exploration_main.yml")
        runtime = PREVIEW_RUNTIME
        raw_config = raw_rqd_config(config)
        self.assertNotIn("bin_catalog", raw_config.snapshot_json)
        self.assertNotIn("Jr_values", raw_config.snapshot_json)
        self.assertNotIn("pass_rule", raw_config.snapshot_json)
        self.assertNotIn("verification_seed", raw_config.snapshot_json)
        self.assertNotIn("stagnant_rounds", raw_config.snapshot_json)
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)

        with TemporaryDirectory() as output_dir:
            controller = RawRqdController(
                connection, config, None, runtime, output_dir=Path(output_dir))
            condition = controller.targets[0]
            controller._plan_round(condition)
            initial_ids = list(controller.state["round"]["candidate_ids"])
            queued_seeds = [task["seed"] for task in controller.state["queue"]]
            self.assertEqual(len(initial_ids), config.templates[condition.fixed_jn].sample_count)
            self.assertEqual(len(controller.state["queue"]), len(initial_ids))
            preview_sets = [
                item["joint_sets"] for item in lhs_signature_records(raw_config)
                if item["fixed_jn"] == condition.fixed_jn
            ]
            execution_sets = [
                list(controller.state["inputs"][identity]["joint_sets"])
                for identity in initial_ids
            ]
            self.assertEqual(execution_sets, preview_sets)
            for rank, identity in enumerate(initial_ids):
                controller.profiles[identity] = {
                    controller.profile_id: {
                        config.policy.initial_seed: SeedProfile(
                            config.policy.initial_seed,
                            (BHPoint(0.0, 1.0, 50.0 - rank, 1.0),),
                        )
                    }
                }
            controller.state["queue"].clear()
            controller._plan_progress(condition)
            controller._complete_round(condition)
            selected_center = initial_ids[-1]
            self.assertEqual(
                controller.state["raw_rqd_centers"]["2"], selected_center)

            controller._plan_round(condition)
            coordinate_round = controller.state["round"]
            self.assertEqual(coordinate_round["kind"], "coordinate")
            self.assertEqual(coordinate_round["allocation_reference"], selected_center)
            coordinate_ids = coordinate_round["candidate_ids"]
            self.assertTrue(1 <= len(coordinate_ids) <= 2)
            for identity in coordinate_ids:
                reference_sets = controller.state["inputs"][selected_center]["joint_sets"]
                candidate_sets = controller.state["inputs"][identity]["joint_sets"]
                changed_axes = [
                    (set_index, key)
                    for set_index, (reference_set, candidate_set)
                    in enumerate(zip(reference_sets, candidate_sets))
                    for key in reference_set
                    if key != "joint_set_id" and reference_set[key] != candidate_set[key]
                ]
                self.assertEqual(len(changed_axes), 1)
                self.assertIn(changed_axes[0][1], RAW_RQD_COORDINATE_PARAMETERS)
                controller.profiles[identity] = {
                    controller.profile_id: {
                        config.policy.initial_seed: SeedProfile(
                            config.policy.initial_seed,
                            (BHPoint(0.0, 1.0, 20.0, 1.0),),
                        )
                    }
                }
            controller.state["queue"].clear()
            controller._plan_progress(condition)
            controller._complete_round(condition)
            (event_payload,) = connection.execute(
                "SELECT payload FROM main_control_events WHERE run_id=? "
                "AND kind='round_complete' ORDER BY event_index DESC LIMIT 1",
                (controller.run_id,),
            ).fetchone()
            round_event = json.loads(event_payload)
            summary = controller.summary()

        self.assertEqual(summary["objective"], "continuous_raw_bh_rqd_response")
        self.assertEqual(summary["realization"]["seed"], config.policy.initial_seed)
        self.assertIsNone(summary["realization"]["verification"])
        self.assertEqual(
            summary["signature_count"], len(initial_ids) + len(coordinate_ids))
        self.assertNotIn("passed_target_count", summary)
        self.assertNotIn("target_pass_rule", summary)
        self.assertEqual(set(queued_seeds), {config.policy.initial_seed})
        self.assertIsNone(controller.state["round"])
        self.assertEqual(controller.state["queue"], [])
        self.assertNotIn("stagnant_rounds", controller.state)
        self.assertNotIn("target_evidence", controller.state)
        self.assertNotIn("progress", round_event["round_outcome"])
        self.assertNotIn("stagnant_rounds", round_event)
        self.assertTrue(all(
            item["raw_rqd_min"] == item["raw_rqd_max"]
            and item["support_weighted_mean_rqd"] == item["raw_rqd_min"]
            for item in summary["raw_rqd_by_signature"].values()
        ))
        self.assertEqual(
            controller.state["raw_rqd_centers"]["2"],
            min(coordinate_ids),
        )
        self.assertTrue(round_event["completed_round"]["center_moved"])
        self.assertTrue(summary["raw_bh_observations_by_signature"])
        connection.close()

    def test_signature_response_delta_records_parameter_and_rqd_changes(self) -> None:
        config = load_main_config(self.repo_root / "config/rqd_exploration_main.yml")
        raw_config = raw_rqd_config(config)
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)

        with TemporaryDirectory() as output_dir:
            controller = RawRqdController(
                connection, config, None, PREVIEW_RUNTIME, output_dir=Path(output_dir))
            design = raw_config.templates[2.0]
            reference = replace(
                reference_snapshot(raw_config, PREVIEW_RUNTIME),
                fixed_jn=2.0,
                joint_sets=generate_lhs_design(design).samples[0].joint_sets,
            )
            candidate_sets = list(reference.joint_sets)
            original_p32 = candidate_sets[0].p32_m2_per_m3
            candidate_sets[0] = replace(
                candidate_sets[0],
                p32_m2_per_m3=0.5 if original_p32 != 0.5 else 0.6,
            )
            candidate = replace(reference, joint_sets=tuple(candidate_sets))
            reference_id, candidate_id = input_identity(reference), input_identity(candidate)
            controller.state["inputs"][reference_id] = asdict(reference)
            controller.state["inputs"][candidate_id] = asdict(candidate)
            seed = config.policy.initial_seed
            controller.profiles[reference_id] = {
                controller.profile_id: {
                    seed: SeedProfile(seed, (BHPoint(0.0, 1.0, 40.0, 1.0),)),
                },
            }
            controller.profiles[candidate_id] = {
                controller.profile_id: {
                    seed: SeedProfile(seed, (BHPoint(0.0, 1.0, 30.0, 1.0),)),
                },
            }
            controller.state["round"] = {
                "round_index": 2,
                "target": controller.targets[0].key,
                "kind": "coordinate",
                "candidate_ids": [candidate_id],
                "before_suitable": [reference_id],
                "allocation_reference": reference_id,
                "axis_check_key": f"{reference_id}:0",
            }
            controller._complete_round(controller.targets[0])
            (payload,) = connection.execute(
                "SELECT payload FROM main_control_events WHERE run_id=? "
                "AND kind='round_complete'",
                (controller.run_id,),
            ).fetchone()
            delta = json.loads(payload)["round_outcome"]["signature_response_deltas"][0]

        self.assertEqual(delta["reference_support_weighted_mean_rqd"], 40.0)
        self.assertEqual(delta["candidate_support_weighted_mean_rqd"], 30.0)
        self.assertEqual(delta["support_weighted_mean_rqd_delta"], -10.0)
        self.assertEqual(delta["parameter_deltas"][0]["parameter"], "p32_m2_per_m3")
        self.assertEqual(
            delta["parameter_deltas"][0]["delta"],
            candidate.joint_sets[0].p32_m2_per_m3
            - reference.joint_sets[0].p32_m2_per_m3,
        )
        self.assertEqual(
            controller.summary()["last_completed_round_response_deltas"], [delta])
        connection.close()

    def test_progress_log_reports_coordinate_and_rqd_response_without_hashes(self) -> None:
        config = load_main_config(self.repo_root / "config/rqd_exploration_main.yml")
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)
        messages = []

        with TemporaryDirectory() as output_dir:
            controller = RawRqdController(
                connection, config, None, PREVIEW_RUNTIME,
                output_dir=Path(output_dir), progress_callback=messages.append)
            design = config.templates[2.0]
            reference = replace(
                reference_snapshot(config, PREVIEW_RUNTIME),
                fixed_jn=2.0,
                joint_sets=generate_lhs_design(design).samples[0].joint_sets,
            )
            reference_sets = list(reference.joint_sets)
            original = reference_sets[0].p32_m2_per_m3
            sign = 1 if original + 0.1 <= 10.0 else -1
            candidate_value = original + sign * 0.1
            reference_sets[0] = replace(
                reference_sets[0], p32_m2_per_m3=candidate_value)
            candidate = replace(reference, joint_sets=tuple(reference_sets))
            reference_id = input_identity(reference)
            candidate_id = input_identity(candidate)
            controller.state["inputs"][reference_id] = asdict(reference)
            controller.state["inputs"][candidate_id] = asdict(candidate)
            seed = config.policy.initial_seed
            controller.profiles[reference_id] = {
                controller.profile_id: {
                    seed: SeedProfile(seed, (
                        BHPoint(0.0, 1.0, 40.0, 1.0),
                        BHPoint(1.0, 2.0, 60.0, 1.0),
                    )),
                },
            }
            controller.profiles[candidate_id] = {
                controller.profile_id: {
                    seed: SeedProfile(seed, (
                        BHPoint(0.0, 1.0, 20.0, 1.0),
                        BHPoint(1.0, 2.0, 30.0, 1.0),
                    )),
                },
            }
            controller.state["round"] = {
                "round_index": 7,
                "target": controller.targets[0].key,
                "phase": "search",
                "kind": "coordinate",
                "allocation_reference": reference_id,
                "axis": {
                    "joint_set_id": "set-1",
                    "parameter": "p32_m2_per_m3",
                    "step": 0.1,
                },
                "candidates": [{
                    "input_id": candidate_id,
                    "parameter": "p32_m2_per_m3",
                    "candidate_value": candidate_value,
                    "sign": sign,
                }],
            }
            controller.state["round_index"] = 7
            task = {
                "input_id": candidate_id,
                "seed": seed,
                "role": "coordinate_neighbor",
                "result": "generated",
            }
            context = controller._format_progress_context(task, 44)
            controller._report_task_completion(task)

        self.assertIn("starts=44/20000 remaining=19956", context)
        self.assertIn("round=7 kind=coordinate", context)
        self.assertIn("Jn=2", context)
        self.assertIn("set-1/p32_m2_per_m3=", context)
        self.assertIn("delta=", context)
        self.assertNotIn(controller.run_id, context)
        self.assertNotIn(candidate_id, context)
        self.assertIn("BH-supported=2 support=2.0m", messages[-1])
        self.assertIn("weighted-mean=25.00", messages[-1])
        self.assertIn("vs-center-mean=50.00 delta-mean=-25.00", messages[-1])
        self.assertNotIn(candidate_id, messages[-1])
        connection.close()

    def test_controller_finishes_after_all_jn_neighborhoods_are_exhausted(self) -> None:
        config = load_main_config(self.repo_root / "config/rqd_exploration_main.yml")
        connection = sqlite3.connect(":memory:")
        initialize_store(connection)
        initialize_main_store(connection)

        with TemporaryDirectory() as output_dir:
            controller = RawRqdController(
                connection, config, None, PREVIEW_RUNTIME,
                output_dir=Path(output_dir))
            controller.state["raw_rqd_exhausted_jn"] = [2.0, 4.0, 9.0, 15.0]
            summary = controller.run()

        self.assertEqual(summary["phase"], "complete")
        self.assertEqual(summary["reason"], "targets_complete")
        self.assertEqual(summary["starts_consumed"], 0)
        self.assertEqual(summary["signature_count"], 0)
        connection.close()

    def test_run_requires_explicit_confirmation_before_database_access(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "must-not-be-created.sqlite"
            output = StringIO()
            with redirect_stderr(output):
                status = main([
                    "run", "--database", str(database_path),
                    "--output-dir", str(database_path.parent / "raw-rqd-reports"),
                ])

        self.assertEqual(status, 2)
        self.assertFalse(database_path.exists())
        self.assertIn("no database was opened", output.getvalue())

    def test_raw_search_rejects_database_with_a_main_run(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE main_control_runs (run_id TEXT)")
        connection.execute("INSERT INTO main_control_runs VALUES ('main-existing-run')")

        with self.assertRaisesRegex(ValueError, "separate from every main run"):
            _assert_raw_database_is_separate(connection)

        connection.close()
