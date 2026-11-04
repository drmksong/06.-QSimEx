from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from dataclasses import asdict, replace

from src.rqd_exploration.main_analysis import BHPoint, SeedProfile
from src.rqd_exploration.main_controller import PREVIEW_RUNTIME, reference_snapshot
from src.rqd_exploration.main_design import input_identity
from src.rqd_exploration.main_policy import load_main_config
from src.rqd_exploration.main_store import initialize_main_store
from src.rqd_exploration.design import generate_lhs_design
from src.rqd_exploration.measurement import (
    MeasurementEvidence,
    RawBHObservation,
    RawFaceObservation,
)
from src.rqd_exploration.store import initialize_store
from src.rqd_exploration.raw_rqd_search import (
    RAW_RQD_INITIAL_SIGNATURES_PER_JN,
    RAW_RQD_COORDINATE_PARAMETERS,
    RawRqdCondition,
    RawRqdController,
    _assert_raw_database_is_separate,
    lhs_signature_records,
    main,
    raw_bh_records,
    raw_rqd_config,
    summarize_raw_rqd,
)


class TestRawRqdSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[2]

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
        self.assertEqual(summary.seeds_with_supported_observations, (43,))
        self.assertFalse(hasattr(summary, "raw_rqd_at_or_below_target_count"))

    def test_raw_rqd_condition_has_no_threshold_or_pass_semantics(self) -> None:
        condition = RawRqdCondition(fixed_jn=4.0)

        self.assertEqual(condition.key, "raw-rqd/4/pilot-bh")
        self.assertFalse(hasattr(condition, "target_rqd"))
        self.assertFalse(hasattr(condition, "contains"))

    def test_lhs_preview_is_deterministic_and_does_not_run_simulation(self) -> None:
        config_path = self.repo_root / "config/rqd_exploration_main.yml"
        config = load_main_config(config_path)
        self.assertEqual(lhs_signature_records(config), lhs_signature_records(config))

        output = StringIO()
        with redirect_stdout(output):
            status = main(["preview", "--config", str(config_path)])
        payload = json.loads(output.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(
            set(payload["fixed_jn_values"]),
            {2.0, 4.0, 9.0, 15.0},
        )
        self.assertEqual(
            payload["candidate_count"],
            RAW_RQD_INITIAL_SIGNATURES_PER_JN * len(config.templates),
        )
        self.assertEqual(payload["initial_signatures_per_jn"], 10)
        self.assertEqual(
            payload["coordinate_parameters"],
            list(RAW_RQD_COORDINATE_PARAMETERS),
        )
        self.assertEqual(payload["measurement_scope"], "BH-only")
        self.assertEqual(
            payload["update_method"], "cyclic-coordinate-neighborhood-min-rqd")
        self.assertEqual(payload["objective"], "continuous_raw_bh_rqd_response")
        self.assertEqual(payload["realization"]["seed"], config.policy.initial_seed)
        self.assertIsNone(payload["realization"]["verification"])
        self.assertEqual(
            payload["refinement_metric"], "support_weighted_mean_raw_rqd")
        self.assertFalse(payload["simulation_started"])
        self.assertFalse(payload["database_written"])
        self.assertTrue(all("joint_sets" in item for item in payload["candidates"]))
        self.assertTrue(all("raw_rqd" not in item for item in payload["candidates"]))

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
            self.assertEqual(len(initial_ids), 10)
            self.assertEqual(len(controller.state["queue"]), 10)
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
