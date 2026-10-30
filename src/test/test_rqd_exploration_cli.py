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
CONFIG_PATH = PROJECT_ROOT / "config/rqd_exploration_pilot2.yml"
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
        kwargs["progress_callback"]("CLI progress fixture")
        reason = os.environ.get("QSIMEX_TEST_TERMINATION_REASON", "jobs_complete")
        return FrozenJobRunSummary(
            (), (), (), 0, kwargs["maximum_simulations"], reason,
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
            result = self.run_cli("preview")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["manifest"]["jobs"], 10)
            self.assertEqual(payload["manifest"]["planned_locations"], 1210)
            self.assertFalse(payload["manifest_id_is_persisted"])
            self.assertFalse(payload["database_written"])
            self.assertFalse(payload["simulation_started"])
            self.assertFalse(result_path.exists())

    def test_run_requires_confirmation_and_budget_before_touching_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "not-created.sqlite"
            refused = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "2",
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("Execution not confirmed", refused.stderr)
            self.assertFalse(database.exists())
            self.assertNotIn("FAKE_RUNNER_CALLED", refused.stdout)

            missing_budget = self.run_cli(
                "run", "--database", str(database), "--confirm-execution",
            )
            self.assertEqual(missing_budget.returncode, 2)
            self.assertFalse(database.exists())

            invalid_budget = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "0",
                "--confirm-execution",
            )
            self.assertEqual(invalid_budget.returncode, 1)
            self.assertIn("at least 1", invalid_budget.stderr)
            self.assertFalse(database.exists())

    def test_run_adds_batches_and_automatically_resumes_exact_unfinished_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "nested" / "pilot.sqlite"
            run = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "3",
                "--confirm-execution",
                stub_runner=True,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("FAKE_RUNNER_CALLED", run.stdout)
            self.assertIn('"batch_action": "added"', run.stdout)
            self.assertRegex(
                run.stderr,
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 CLI progress fixture",
            )
            self.assertTrue(database.is_file())
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    STORE_SCHEMA_VERSION,
                )
                original_id = connection.execute(
                    "SELECT manifest_id FROM manifest",
                ).fetchone()[0]
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0],
                    1,
                )

            resumed = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "2",
                "--confirm-execution",
                stub_runner=True,
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertIn("FAKE_RUNNER_CALLED", resumed.stdout)
            self.assertIn('"batch_action": "resumed"', resumed.stdout)
            resume_payload = json.loads(resumed.stdout.split("FAKE_RUNNER_CALLED\n", 1)[1])
            self.assertEqual(
                resume_payload["run_summary"]["maximum_simulations"], 2,
            )
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT manifest_id FROM manifest").fetchone()[0],
                    original_id,
                )

            copied_config = Path(temp_dir) / "same-bytes.yml"
            copied_config.write_bytes(CONFIG_PATH.read_bytes())
            copied_path_resume = self.run_cli(
                "run", "--config", str(copied_config), "--database", str(database),
                "--maximum-simulations", "1", "--confirm-execution",
                stub_runner=True,
            )
            self.assertEqual(copied_path_resume.returncode, 0, copied_path_resume.stderr)
            self.assertIn('"batch_action": "resumed"', copied_path_resume.stdout)

            changed_config = Path(temp_dir) / "same-values-different-bytes.yml"
            changed_config.write_bytes(CONFIG_PATH.read_bytes() + b"\n# distinct source bytes\n")
            changed_bytes_batch = self.run_cli(
                "run", "--config", str(changed_config), "--database", str(database),
                "--maximum-simulations", "1", "--confirm-execution",
                stub_runner=True,
            )
            self.assertEqual(changed_bytes_batch.returncode, 0, changed_bytes_batch.stderr)
            self.assertIn('"batch_action": "added"', changed_bytes_batch.stdout)

            new_runtime_batch = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "1",
                "--confirm-execution",
                stub_runner=True,
                generator_version="different-generator-version",
            )
            self.assertEqual(new_runtime_batch.returncode, 0, new_runtime_batch.stderr)
            self.assertIn('"batch_action": "added"', new_runtime_batch.stdout)
            self.assertIn("FAKE_RUNNER_CALLED", new_runtime_batch.stdout)
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0],
                    3,
                )

    def test_run_rejects_completed_exact_duplicate_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "completed.sqlite"
            first = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "1",
                "--confirm-execution", stub_runner=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            with sqlite3.connect(database) as connection:
                jobs = connection.execute(
                    """
                    SELECT manifest_id, design_id, block_id, sample_index,
                           realization_seed, execution_fingerprint_digest
                    FROM jobs
                    """,
                ).fetchall()
                for job in jobs:
                    connection.execute(
                        """
                        INSERT INTO attempts (
                            manifest_id, design_id, block_id, sample_index,
                            realization_seed, execution_fingerprint_digest,
                            attempt_index, status, started_at_utc, finished_at_utc,
                            runtime_seconds, runtime_is_lower_bound
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, 'succeeded', ?, ?, 0, 0)
                        """,
                        (*job, "2026-10-30T00:00:00Z", "2026-10-30T00:00:01Z"),
                    )

            duplicate = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "1",
                "--confirm-execution", stub_runner=True,
            )
            self.assertEqual(duplicate.returncode, 1)
            self.assertIn("completed exact duplicate batch", duplicate.stderr)
            self.assertNotIn("FAKE_RUNNER_CALLED", duplicate.stdout)
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0],
                    1,
                )

    def test_run_rejects_ambiguous_matching_batches_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "ambiguous.sqlite"
            first = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "1",
                "--confirm-execution", stub_runner=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            with sqlite3.connect(database) as connection:
                manifest_id, schema_version, manifest_json = connection.execute(
                    "SELECT manifest_id, schema_version, manifest_json FROM manifest",
                ).fetchone()
                yaml_bytes, yaml_sha256, source_reference = connection.execute(
                    """
                    SELECT yaml_bytes, yaml_sha256, source_reference
                    FROM input_provenance WHERE manifest_id = ?
                    """,
                    (manifest_id,),
                ).fetchone()
                duplicate_id = "batch-ambiguous-fixture"
                connection.execute(
                    "INSERT INTO manifest VALUES (?, ?, ?)",
                    (duplicate_id, schema_version, manifest_json),
                )
                connection.execute(
                    "INSERT INTO input_provenance VALUES (?, ?, ?, ?)",
                    (duplicate_id, yaml_bytes, yaml_sha256, source_reference),
                )

            ambiguous = self.run_cli(
                "run", "--database", str(database), "--maximum-simulations", "1",
                "--confirm-execution", stub_runner=True,
            )
            self.assertEqual(ambiguous.returncode, 1)
            self.assertIn("multiple unfinished or completed batches", ambiguous.stderr)
            self.assertNotIn("FAKE_RUNNER_CALLED", ambiguous.stdout)

    def test_run_rejects_invalid_database_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_database = Path(temp_dir) / "empty.sqlite"
            empty_database.touch()
            empty = self.run_cli(
                "run", "--database", str(empty_database), "--maximum-simulations", "1",
                "--confirm-execution",
            )
            self.assertEqual(empty.returncode, 1)
            self.assertIn("database file is empty", empty.stderr)

            incompatible = Path(temp_dir) / "incompatible.sqlite"
            with sqlite3.connect(incompatible) as connection:
                connection.execute("PRAGMA user_version = 99")
            schema_error = self.run_cli(
                "run", "--database", str(incompatible), "--maximum-simulations", "1",
                "--confirm-execution",
            )
            self.assertEqual(schema_error.returncode, 1)
            self.assertIn("schema version 4 required; found 99", schema_error.stderr)

            old_schema = Path(temp_dir) / "schema-v3.sqlite"
            with sqlite3.connect(old_schema) as connection:
                connection.execute("PRAGMA user_version = 3")
            v3_error = self.run_cli(
                "run", "--database", str(old_schema), "--maximum-simulations", "1",
                "--confirm-execution",
            )
            self.assertEqual(v3_error.returncode, 1)
            self.assertIn("unsupported store schema version: 3", v3_error.stderr)


if __name__ == "__main__":
    unittest.main()
