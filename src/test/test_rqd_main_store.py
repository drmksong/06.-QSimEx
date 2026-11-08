from dataclasses import asdict, replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.euler_campaign.dfn import DiskJointGeometry
from src.rqd_exploration.main_controller import PREVIEW_RUNTIME, _input_manifest
from src.rqd_exploration.main_design import input_identity
from src.test.test_rqd_main_policy import load_main_config
from src.rqd_exploration.main_store import (
    MainPause, checkpoint, initialize_main_store, load_state, open_run,
    reconcile_starts, reserve_start, single_writer, starts_consumed,
)
from src.rqd_exploration.runner import execute_frozen_job
from src.rqd_exploration.store import (
    _atomic, begin_attempt, initialize_store, record_measurement_result, store_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


class TestMainStore(unittest.TestCase):
    def setUp(self):
        self.config = load_main_config(ROOT / "config/rqd_exploration_main.yml")
        self.connection = sqlite3.connect(":memory:")
        initialize_store(self.connection)
        initialize_main_store(self.connection)
        manifest = _input_manifest(self.config.reference_input, PREVIEW_RUNTIME)
        self.manifest = replace(manifest, jobs=(manifest.jobs[0],))
        self.job = self.manifest.jobs[0]
        store_manifest(self.connection, manifest)
        self.run_id, _ = open_run(self.connection, self.config,
                                  asdict(self.job.snapshot.runtime), {"queue": ["first"]})
        self.factory = Mock()
        self.factory.generate.return_value = DiskJointGeometry(())
        self.cost = {"set": 1.}

    def tearDown(self):
        self.connection.close()

    def reserve(self, job, resuming):
        return reserve_start(self.connection, self.run_id, job,
                             input_id=input_identity(job.snapshot), role="test",
                             resuming=resuming, expected_counts=self.cost,
                             policy=self.config.policy)

    def run_job(self):
        return execute_frozen_job(self.connection, self.manifest, self.config.reference_input,
                                  self.factory, before_start=self.reserve)

    def test_budget_20000_allowed_20001_denied_and_reuse_free(self):
        maximum_starts = self.config.policy.maximum_starts
        self.connection.executemany(
            "INSERT INTO main_control_starts VALUES (?, ?, 'input', 0, '{}', 'test', 0, 'started', '{}')",
            ((self.run_id, index) for index in range(1, maximum_starts)))
        self.assertEqual(self.run_job().simulation_count, 1)
        self.assertEqual(starts_consumed(self.connection, self.run_id), maximum_starts)
        self.assertEqual(self.run_job().simulation_count, 0)
        with self.assertRaises(MainPause) as raised:
            self.reserve(self.job, False)
        self.assertEqual(raised.exception.reason, "budget_exhausted")
        self.assertEqual(self.factory.generate.call_count, 1)
        self.assertEqual(starts_consumed(self.connection, self.run_id), maximum_starts)

    def test_cost_exact_10m_allowed_excess_no_start_no_generation(self):
        self.cost = {"set": 10_000_000.000001}
        with self.assertRaises(MainPause) as raised:
            self.run_job()
        self.assertEqual(raised.exception.reason, "high_cost_review")
        self.assertEqual(starts_consumed(self.connection, self.run_id), 0)
        self.factory.generate.assert_not_called()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
        self.cost = {"set": 10_000_000.}
        self.assertEqual(self.run_job().simulation_count, 1)

    def test_interrupt_generation_recharges_but_raw_commit_crash_does_not(self):
        self.factory.generate.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_job()
        reconcile_starts(self.connection, self.run_id)
        self.assertEqual(self.connection.execute(
            "SELECT status FROM main_control_starts").fetchall(), [("interrupted",)])
        self.factory.generate.side_effect = None
        self.assertEqual(self.run_job().simulation_count, 1)
        self.assertEqual(starts_consumed(self.connection, self.run_id), 2)
        self.assertEqual(load_state(self.connection, self.run_id)["queue"], ["first"])
        reconcile_starts(self.connection, self.run_id)
        self.assertEqual(self.connection.execute(
            "SELECT status FROM main_control_starts").fetchall(), [("succeeded",)] * 2)
        self.assertEqual(self.run_job().simulation_count, 0)
        checkpoint(self.connection, self.run_id, {"queue": []})
        self.assertEqual(load_state(self.connection, self.run_id)["queue"], [])

    def test_crash_during_start_transaction_rolls_back_both_records(self):
        def reserve_then_crash(job, resuming):
            self.reserve(job, resuming)
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            execute_frozen_job(self.connection, self.manifest, self.config.reference_input,
                               self.factory, before_start=reserve_then_crash)
        self.assertEqual(starts_consumed(self.connection, self.run_id), 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
        self.factory.generate.assert_not_called()
        self.run_job()
        self.assertEqual(starts_consumed(self.connection, self.run_id), 1)

    def test_failure_consumed_and_never_retried(self):
        self.factory.generate.side_effect = RuntimeError("explicit failure")
        with self.assertRaisesRegex(RuntimeError, "explicit failure"):
            self.run_job()
        reconcile_starts(self.connection, self.run_id)
        self.assertEqual(starts_consumed(self.connection, self.run_id), 1)
        self.assertEqual(self.connection.execute(
            "SELECT status FROM main_control_starts").fetchall(), [("failed",)])
        self.assertEqual(self.run_job().simulation_count, 0)
        self.assertEqual(self.factory.generate.call_count, 1)

    def test_partial_raw_commit_resume_preserves_observation_and_evidence(self):
        from src.rqd_exploration.adapter import build_generation_case
        from src.rqd_exploration.measurement import measure_realization
        from src.rqd_exploration.runner import _utc_now
        case = build_generation_case(
            self.config.reference_input.geometry, self.config.reference_input.measurements,
            self.job.snapshot.fixed_jn, self.job.snapshot.joint_sets,
            case_id=self.job.design_id)
        result = measure_realization(case, DiskJointGeometry(()))
        first = result.observations[0]
        partial = replace(result, observations=(first,), location_states=tuple(
            state for state in result.location_states
            if state.modality == "BH" and state.profile_id == first.profile_id
            and state.location_index == first.location_index))
        with _atomic(self.connection):
            self.reserve(self.job, False)
            begin_attempt(self.connection, self.job, 0, _utc_now())
        record_measurement_result(self.connection, self.job, 0, partial)
        original = self.connection.execute("SELECT * FROM observations").fetchall()
        evidence = self.connection.execute("SELECT * FROM measurement_evidence").fetchall()
        self.assertEqual(self.run_job().simulation_count, 1)
        self.assertEqual(starts_consumed(self.connection, self.run_id), 2)
        saved = self.connection.execute("SELECT * FROM observations").fetchall()
        self.assertEqual(len(saved), len(result.observations))
        self.assertTrue(all(o in saved for o in original))
        self.assertTrue(all(e in self.connection.execute(
            "SELECT * FROM measurement_evidence").fetchall() for e in evidence))
        self.assertEqual(self.connection.execute("SELECT status FROM attempts").fetchall(), [("succeeded",)])

    def test_budget_has_priority_over_high_cost(self):
        self.cost = {"set": 10_000_001.}
        with patch("src.rqd_exploration.main_store.starts_consumed",
                   return_value=self.config.policy.maximum_starts):
            with self.assertRaises(MainPause) as raised:
                self.run_job()
        self.assertEqual(raised.exception.reason, "budget_exhausted")
        self.factory.generate.assert_not_called()

    def test_migrates_v1_200_start_limit_without_losing_existing_journal(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA user_version = 4")
        connection.execute("CREATE TABLE main_control_schema (version INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO main_control_schema VALUES (1)")
        connection.execute("""
            CREATE TRIGGER main_control_schema_no_update
            BEFORE UPDATE ON main_control_schema
            BEGIN SELECT RAISE(ABORT, 'main control journal is immutable'); END
        """)
        connection.execute("""
            CREATE TABLE main_control_runs (
                run_id TEXT PRIMARY KEY, config_fingerprint TEXT NOT NULL,
                policy_snapshot TEXT NOT NULL, runtime_snapshot TEXT NOT NULL,
                state_json TEXT NOT NULL, status TEXT NOT NULL, reason TEXT)
        """)
        connection.execute(
            "INSERT INTO main_control_runs VALUES ('old-run','old-config','{}','{}','{}','paused','high_cost_review')")
        connection.execute("""
            CREATE TABLE main_control_starts (
                run_id TEXT NOT NULL REFERENCES main_control_runs(run_id),
                start_index INTEGER NOT NULL CHECK(start_index BETWEEN 1 AND 200),
                input_id TEXT NOT NULL, seed INTEGER NOT NULL,
                job_key TEXT NOT NULL, role TEXT NOT NULL, resuming INTEGER NOT NULL,
                status TEXT NOT NULL, expected_counts TEXT NOT NULL,
                PRIMARY KEY(run_id, start_index))
        """)
        connection.executemany(
            "INSERT INTO main_control_starts VALUES ('old-run', ?, 'input', 43, '{}', 'lhs', 0, 'succeeded', '{}')",
            ((index,) for index in range(1, 201)))
        connection.execute("""
            CREATE TRIGGER main_control_starts_no_delete
            BEFORE DELETE ON main_control_starts
            BEGIN SELECT RAISE(ABORT, 'main starts are immutable'); END
        """)

        initialize_main_store(connection)

        self.assertEqual(connection.execute(
            "SELECT version FROM main_control_schema").fetchall(), [(3,)])
        self.assertEqual(connection.execute(
            "SELECT config_fingerprint FROM main_control_runs WHERE run_id='old-run'").fetchone()[0],
            "old-config")
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM main_control_starts WHERE run_id='old-run'").fetchone()[0], 200)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM main_control_starts WHERE run_id='old-run'")
        connection.execute(
            "INSERT INTO main_control_starts VALUES ('old-run', 201, 'input', 43, '{}', 'lhs', 0, 'started', '{}')")
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM main_control_starts WHERE run_id='old-run'").fetchone()[0], 201)
        connection.close()

    def test_migrates_v2_300_start_limit_without_losing_existing_journal(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA user_version = 4")
        connection.execute("CREATE TABLE main_control_schema (version INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO main_control_schema VALUES (2)")
        connection.execute("""
            CREATE TABLE main_control_runs (
                run_id TEXT PRIMARY KEY, config_fingerprint TEXT NOT NULL,
                policy_snapshot TEXT NOT NULL, runtime_snapshot TEXT NOT NULL,
                state_json TEXT NOT NULL, status TEXT NOT NULL, reason TEXT)
        """)
        connection.execute(
            "INSERT INTO main_control_runs VALUES ('old-run','old-config','{}','{}','{}','paused','high_cost_review')")
        connection.execute("""
            CREATE TABLE main_control_starts (
                run_id TEXT NOT NULL REFERENCES main_control_runs(run_id),
                start_index INTEGER NOT NULL CHECK(start_index BETWEEN 1 AND 300),
                input_id TEXT NOT NULL, seed INTEGER NOT NULL,
                job_key TEXT NOT NULL, role TEXT NOT NULL, resuming INTEGER NOT NULL,
                status TEXT NOT NULL, expected_counts TEXT NOT NULL,
                PRIMARY KEY(run_id, start_index))
        """)
        connection.execute(
            "INSERT INTO main_control_starts VALUES ('old-run', 300, 'input', 43, '{}', 'lhs', 0, 'succeeded', '{}')")

        initialize_main_store(connection)

        self.assertEqual(connection.execute(
            "SELECT version FROM main_control_schema").fetchall(), [(3,)])
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM main_control_starts WHERE run_id='old-run'").fetchone()[0], 1)
        connection.execute(
            "INSERT INTO main_control_starts VALUES ('old-run', 20000, 'input', 43, '{}', 'lhs', 0, 'started', '{}')")
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO main_control_starts VALUES ('old-run', 20001, 'input', 43, '{}', 'lhs', 0, 'started', '{}')")
        connection.close()

    def test_policy_immutable_and_mismatch_rejected(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.connection.execute("UPDATE main_control_runs SET policy_snapshot='{}'")
        self.connection.rollback()
        with self.assertRaisesRegex(ValueError, "mismatch"):
            open_run(self.connection, self.config, {"other": "runtime"}, {})
        self.assertEqual(self.connection.execute("PRAGMA user_version").fetchone()[0], 4)

    def test_single_writer_survives_new_connections(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "control.sqlite"
            with sqlite3.connect(path) as a, sqlite3.connect(path) as b:
                with single_writer(a):
                    with self.assertRaisesRegex(RuntimeError, "another main"):
                        with single_writer(b):
                            self.fail("second writer acquired the lock")
                with single_writer(b):
                    pass
