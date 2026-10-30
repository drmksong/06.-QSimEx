from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from src.rqd_exploration.store import STORE_SCHEMA_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config/rqd_exploration_pilot.yml"
FAKE_BACKEND_SCRIPT = r"""
import os
import runpy
import sys
import types

backend = types.ModuleType("src.euler_campaign.mlx_backend")
backend.MLX_GENERATOR_VERSION = os.environ.get(
    "QSIMEX_TEST_GENERATOR_VERSION", "qsimex-mlx-generation-v1",
)
backend.require_mlx_gpu = lambda: ("test-mlx", "Device(gpu, test)")

class FakeFactory:
    def generate(self, case, seed):
        raise AssertionError("CLI tests must not generate a DFN")

backend.MlxCaseJointFactory = FakeFactory
sys.modules["src.euler_campaign.mlx_backend"] = backend

if os.environ.get("QSIMEX_TEST_STUB_RUNNER") == "1":
    from src.rqd_exploration.runner import FrozenJobRunSummary
    import src.rqd_exploration.cli as cli

    def fake_execute(*args, **kwargs):
        print("FAKE_RUNNER_CALLED")
        reason = os.environ.get("QSIMEX_TEST_TERMINATION_REASON", "jobs_complete")
        goal_statuses = (("goal-a", "unresolved_at_budget"),) if reason == "budget_exhausted" else ()
        return FrozenJobRunSummary(
            (), (), (), 0, kwargs["maximum_simulations"], reason, goal_statuses,
        )

    cli.execute_frozen_jobs = fake_execute
    sys.argv = ["run_rqd_exploration.py", *sys.argv[1:]]
    raise SystemExit(cli.main())

sys.argv = ["run_rqd_exploration.py", *sys.argv[1:]]
runpy.run_path("run_rqd_exploration.py", run_name="__main__")
"""


class TestExplorationCliSubprocess(unittest.TestCase):
    def run_cli(
        self,
        *arguments: str,
        generator_version: str = "qsimex-mlx-generation-v1",
        stub_runner: bool = False,
        termination_reason: str = "jobs_complete",
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["QSIMEX_TEST_GENERATOR_VERSION"] = generator_version
        environment["QSIMEX_TEST_STUB_RUNNER"] = "1" if stub_runner else "0"
        environment["QSIMEX_TEST_TERMINATION_REASON"] = termination_reason
        return subprocess.run(
            [sys.executable, "-c", FAKE_BACKEND_SCRIPT, *arguments],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_validate_subcommand_reports_config_summary(self) -> None:
        result = self.run_cli("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["config"]["samples"], 10)

    def test_preview_subcommand_is_read_only_and_reports_manifest_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "preview.sqlite"
            result = self.run_cli("preview", "--manifest-id", "cli-preview-test")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["manifest"]["jobs"], 10)
            self.assertEqual(payload["manifest"]["planned_locations"], 1210)
            self.assertFalse(payload["database_written"])
            self.assertFalse(payload["simulation_started"])
            self.assertFalse(result_path.exists())

    def test_run_requires_confirmation_and_budget_before_touching_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "not-created.sqlite"
            refused = self.run_cli(
                "run", "--manifest-id", "cli-run-test",
                "--database", str(database), "--maximum-simulations", "2",
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("Execution not confirmed", refused.stderr)
            self.assertFalse(database.exists())
            self.assertNotIn("FAKE_RUNNER_CALLED", refused.stdout)

            missing_budget = self.run_cli(
                "run", "--manifest-id", "cli-run-test",
                "--database", str(database), "--confirm-execution",
            )
            self.assertEqual(missing_budget.returncode, 2)
            self.assertFalse(database.exists())

            invalid_budget = self.run_cli(
                "run", "--manifest-id", "cli-run-test",
                "--database", str(database), "--maximum-simulations", "0",
                "--confirm-execution",
            )
            self.assertEqual(invalid_budget.returncode, 1)
            self.assertIn("at least 1", invalid_budget.stderr)
            self.assertFalse(database.exists())

    def test_run_and_resume_use_temporary_db_and_reject_manifest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "nested" / "pilot.sqlite"
            run = self.run_cli(
                "run", "--manifest-id", "cli-db-test",
                "--database", str(database), "--maximum-simulations", "3",
                "--confirm-execution",
                stub_runner=True,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("FAKE_RUNNER_CALLED", run.stdout)
            self.assertTrue(database.is_file())
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    STORE_SCHEMA_VERSION,
                )
                self.assertIsNotNone(connection.execute(
                    "SELECT 1 FROM manifest WHERE manifest_id = ?",
                    ("cli-db-test",),
                ).fetchone())

            resumed = self.run_cli(
                "resume", "--manifest-id", "cli-db-test",
                "--database", str(database), "--maximum-simulations", "2",
                "--confirm-execution",
                stub_runner=True,
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertIn("FAKE_RUNNER_CALLED", resumed.stdout)
            resume_payload = json.loads(resumed.stdout.split("FAKE_RUNNER_CALLED\n", 1)[1])
            self.assertEqual(
                resume_payload["run_summary"]["maximum_simulations"], 2,
            )

            budget_stop = self.run_cli(
                "run", "--manifest-id", "cli-budget-test",
                "--database", str(Path(temp_dir) / "budget.sqlite"),
                "--maximum-simulations", "1", "--confirm-execution",
                stub_runner=True,
                termination_reason="budget_exhausted",
            )
            self.assertEqual(budget_stop.returncode, 0, budget_stop.stderr)
            budget_payload = json.loads(
                budget_stop.stdout.split("FAKE_RUNNER_CALLED\n", 1)[1],
            )
            self.assertEqual(
                budget_payload["run_summary"]["termination_reason"],
                "budget_exhausted",
            )
            self.assertEqual(
                budget_payload["run_summary"]["goal_statuses"],
                [["goal-a", "unresolved_at_budget"]],
            )

            mismatch = self.run_cli(
                "resume", "--manifest-id", "cli-db-test",
                "--database", str(database), "--maximum-simulations", "2",
                "--confirm-execution",
                generator_version="different-generator-version",
                stub_runner=True,
            )
            self.assertEqual(mismatch.returncode, 1)
            self.assertIn("does not match the persisted manifest", mismatch.stderr)
            self.assertNotIn("FAKE_RUNNER_CALLED", mismatch.stdout)

    def test_run_rejects_existing_database_and_resume_rejects_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "existing.sqlite"
            database.touch()
            existing = self.run_cli(
                "run", "--manifest-id", "cli-existing-test",
                "--database", str(database), "--maximum-simulations", "1",
                "--confirm-execution",
            )
            self.assertEqual(existing.returncode, 1)
            self.assertIn("database already exists", existing.stderr)

            missing = self.run_cli(
                "resume", "--manifest-id", "cli-missing-test",
                "--database", str(Path(temp_dir) / "missing.sqlite"),
                "--maximum-simulations", "1", "--confirm-execution",
            )
            self.assertEqual(missing.returncode, 1)
            self.assertIn("resume database does not exist", missing.stderr)

            incompatible = Path(temp_dir) / "incompatible.sqlite"
            with sqlite3.connect(incompatible) as connection:
                connection.execute("PRAGMA user_version = 99")
            schema_error = self.run_cli(
                "resume", "--manifest-id", "cli-schema-test",
                "--database", str(incompatible),
                "--maximum-simulations", "1", "--confirm-execution",
            )
            self.assertEqual(schema_error.returncode, 1)
            self.assertIn("schema version 1 required; found 99", schema_error.stderr)


if __name__ == "__main__":
    unittest.main()
