from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.rqd_exploration import cli
from src.rqd_exploration.config import load_config
from src.rqd_exploration.design import build_frozen_manifest
from src.rqd_exploration.fingerprint import ExecutionRuntime
from src.rqd_exploration.measurement import (
    MeasurementEvidence,
    MeasurementResult,
    PlannedLocationState,
    RawBHObservation,
)
from src.rqd_exploration.records import PlannedBHInterval, PlannedFaceStation, PlannedScanline
from src.rqd_exploration.store import (
    begin_attempt,
    finish_attempt,
    initialize_store,
    record_measurement_result,
    store_manifest,
)


class TestAnalyzeCli(unittest.TestCase):
    def _create_database(self, database_path: Path) -> str:
        config_path = Path(__file__).resolve().parents[2] / "config/rqd_exploration_pilot2.yml"
        config = load_config(config_path)
        runtime = ExecutionRuntime(
            "fixture-generator-v1",
            "fixture-measurement-v1",
            "fixture-backend",
            ("fixture-device", "fixture-runtime"),
        )
        manifest = build_frozen_manifest(
            config,
            manifest_id="analyze-fixture",
            runtime=runtime,
            boundary_rules_version="fixture-boundary-v1",
            planned_locations=(
                PlannedBHInterval(
                    "fixture-bh", 0, 0.0, 1.0, (0.0, 15.0, 15.0),
                    (1.0, 0.0, 0.0), 1.0,
                ),
                PlannedFaceStation(
                    "fixture-face", 0, 0.0, (0.0, 15.0, 15.0),
                    (1.0, 0.0, 0.0), 78.53981633974483, None,
                    (PlannedScanline(
                        0, (0.0, 10.0, 15.0), (0.0, 1.0, 0.0), 10.0,
                    ),),
                ),
            ),
        )
        with sqlite3.connect(database_path) as connection:
            initialize_store(connection)
            store_manifest(connection, manifest)
            job = manifest.jobs[0]
            begin_attempt(connection, job, 0, "2026-10-30T00:00:00Z")
            observation = RawBHObservation(
                profile_id="fixture-bh",
                location_index=0,
                start_m=0.0,
                end_m=1.0,
                raw_rqd=100.0,
                support_length_m=1.0,
                method_id="deere_direct_rqd",
                method_version="qsimex-fixed-rqd-v1",
                is_valid=True,
                exclusion_reason=None,
                zero_cross=True,
                evidence=MeasurementEvidence(
                    0, (0.0, 15.0, 15.0), (1.0, 0.0, 0.0), 1.0, (),
                ),
            )
            result = MeasurementResult(
                planned_locations=(),
                location_states=(
                    PlannedLocationState("BH", "fixture-bh", 0, "observed", None),
                    PlannedLocationState(
                        "face", "fixture-face", 0, "unavailable",
                        "boundary support unavailable",
                    ),
                ),
                observations=(observation,),
                excluded_bh_tail_lengths_m=(),
                face_stop_reason="invalid_boundary_face",
            )
            record_measurement_result(connection, job, 0, result)
            finish_attempt(
                connection,
                job,
                0,
                status="succeeded",
                finished_at_utc="2026-10-30T00:00:02Z",
                runtime_seconds=2.0,
            )
        return manifest.manifest_id

    def _run_analyze(
        self,
        database_path: Path,
        output_path: Path,
        *,
        revision_index: int | None = None,
    ) -> tuple[int, dict[str, object], str]:
        arguments = [
            "analyze",
            "--database", str(database_path),
            "--manifest-id", "analyze-fixture",
            "--output-dir", str(output_path),
        ]
        if revision_index is not None:
            arguments.extend(("--revision-index", str(revision_index)))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(arguments)
        payload = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
        return code, payload, stderr.getvalue()

    def test_analyze_cumulative_rescores_without_simulation_or_raw_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "pilot.sqlite"
            self._create_database(database_path)
            with sqlite3.connect(database_path) as connection:
                before_observations = connection.execute(
                    "SELECT * FROM observations ORDER BY manifest_id, modality"
                ).fetchall()
                before_statuses = connection.execute(
                    "SELECT * FROM location_status ORDER BY manifest_id, modality"
                ).fetchall()
                before_evidence = connection.execute(
                    "SELECT * FROM measurement_evidence ORDER BY manifest_id, modality"
                ).fetchall()

            def run(jr_value: str) -> tuple[int, dict[str, object], str]:
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = cli.main([
                        "analyze-cumulative",
                        "--database", str(database_path),
                        "--jr-values", jr_value,
                        "--ja-values", "1.0",
                    ])
                payload = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
                return code, payload, stderr.getvalue()

            with patch.object(
                cli,
                "execute_frozen_jobs",
                side_effect=AssertionError("cumulative analysis must not run simulations"),
            ):
                first_code, first, first_error = run("1.0")
                second_code, second, second_error = run("2.0")

            self.assertEqual(first_code, 0, first_error)
            self.assertEqual(second_code, 0, second_error)
            self.assertEqual(first["command"], "analyze-cumulative")
            self.assertEqual(first["selected_observation_count"], 1)
            self.assertEqual(first["scenario_evaluation_count"], 1)
            self.assertEqual(first["derived_score_rows"], 1)
            self.assertFalse(first["simulation_started"])
            self.assertFalse(first["raw_observations_modified"])
            self.assertNotEqual(
                first["analysis_fingerprint_sha256"],
                second["analysis_fingerprint_sha256"],
            )
            with sqlite3.connect(database_path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_analysis_runs"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_derived_scores"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT * FROM observations ORDER BY manifest_id, modality"
                    ).fetchall(),
                    before_observations,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT * FROM location_status ORDER BY manifest_id, modality"
                    ).fetchall(),
                    before_statuses,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT * FROM measurement_evidence ORDER BY manifest_id, modality"
                    ).fetchall(),
                    before_evidence,
                )

    def test_analyze_writes_reports_without_simulation_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "pilot.sqlite"
            output_path = Path(temporary_directory) / "reports"
            self._create_database(database_path)
            with sqlite3.connect(database_path) as connection:
                before_observations = connection.execute(
                    "SELECT * FROM observations ORDER BY manifest_id, modality"
                ).fetchall()
                before_statuses = connection.execute(
                    "SELECT * FROM location_status ORDER BY manifest_id, modality"
                ).fetchall()

            with patch.object(
                cli,
                "execute_frozen_jobs",
                side_effect=AssertionError("analyze must not execute simulations"),
            ):
                first_code, first, first_error = self._run_analyze(
                    database_path,
                    output_path,
                )
                first_files = {
                    item.name: item.read_bytes()
                    for item in output_path.iterdir()
                }
                second_code, second, second_error = self._run_analyze(
                    database_path,
                    output_path,
                )

            self.assertEqual(first_code, 0, first_error)
            self.assertEqual(second_code, 0, second_error)
            self.assertFalse(first["simulation_started"])
            self.assertFalse(first["raw_observations_modified"])
            self.assertEqual(first["dataset_revision_index"], 1)
            self.assertEqual(first["derived_score_rows"], 66)
            file_rows = first["file_rows"]
            self.assertIsInstance(file_rows, dict)
            assert isinstance(file_rows, dict)
            self.assertEqual(file_rows["observation_scenarios.csv"], 66)
            self.assertEqual(file_rows["location_status.csv"], 20)
            self.assertEqual(first["analysis_fingerprint_sha256"],
                             second["analysis_fingerprint_sha256"])
            self.assertEqual(first["report_summary_sha256"], second["report_summary_sha256"])
            self.assertTrue(first["generated_at_utc"])

            with sqlite3.connect(database_path) as connection:
                after_observations = connection.execute(
                    "SELECT * FROM observations ORDER BY manifest_id, modality"
                ).fetchall()
                after_statuses = connection.execute(
                    "SELECT * FROM location_status ORDER BY manifest_id, modality"
                ).fetchall()
                self.assertEqual(before_observations, after_observations)
                self.assertEqual(before_statuses, after_statuses)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM dataset_revisions").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM derived_scores").fetchone()[0],
                    66,
                )
                self.assertEqual(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM derived_scores
                        WHERE attempt_index = 0 AND zero_cross_convention = ?
                        """,
                        ("raw_zero_cross_flag_preserved_without_score_adjustment",),
                    ).fetchone()[0],
                    66,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM dataset_revision_observations"
                    ).fetchone()[0],
                    1,
                )
            second_files = {item.name: item.read_bytes() for item in output_path.iterdir()}
            self.assertEqual(first_files, second_files)
            with (output_path / "observation_scenarios.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                scenarios = list(csv.DictReader(stream))
            self.assertEqual(len(scenarios), 66)
            self.assertTrue(all(row["actual_support"] == "1.0" for row in scenarios))
            with (output_path / "profile_summaries.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                summaries = list(csv.DictReader(stream))
            self.assertEqual(len(summaries), 66)
            self.assertTrue(all(row["observation_count"] == "1" for row in summaries))
            self.assertTrue(all(
                row["valid_support_observation_count"] == "1"
                for row in summaries
            ))
            self.assertTrue(all(row["signature_count"] == "1" for row in summaries))
            self.assertTrue(all(row["realization_count"] == "1" for row in summaries))
            self.assertTrue(all(row["total_support"] == "1.0" for row in summaries))

    def test_report_cumulative_exports_persisted_revision_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            database_path = base / "pilot.sqlite"
            output_path = base / "cumulative-reports"
            self._create_database(database_path)

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                analyze_code = cli.main([
                    "analyze-cumulative",
                    "--database", str(database_path),
                    "--jr-values", "1.0",
                    "--ja-values", "1.0",
                ])
            self.assertEqual(analyze_code, 0)

            with sqlite3.connect(database_path) as connection:
                before_counts = (
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_dataset_revisions"
                    ).fetchone()[0],
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_analysis_runs"
                    ).fetchone()[0],
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_derived_scores"
                    ).fetchone()[0],
                )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.object(
                    cli,
                    "execute_frozen_jobs",
                    side_effect=AssertionError("report-cumulative must not simulate"),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                report_code = cli.main([
                    "report-cumulative",
                    "--database", str(database_path),
                    "--output-dir", str(output_path),
                    "--jr-values", "1.0",
                    "--ja-values", "1.0",
                ])
            payload = json.loads(stdout.getvalue()) if stdout.getvalue() else {}

            self.assertEqual(report_code, 0, stderr.getvalue())
            self.assertEqual(payload["command"], "report-cumulative")
            self.assertEqual(payload["source_observation_count"], 1)
            self.assertEqual(payload["unique_observation_count"], 1)
            self.assertEqual(payload["conflicted_fingerprint_count"], 0)
            self.assertFalse(payload["simulation_started"])
            self.assertFalse(payload["database_modified"])
            self.assertTrue((output_path / "report_summary.json").is_file())
            self.assertEqual(
                payload["file_rows"]["signature_observation_scenarios.csv"],
                1,
            )
            with sqlite3.connect(database_path) as connection:
                after_counts = (
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_dataset_revisions"
                    ).fetchone()[0],
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_analysis_runs"
                    ).fetchone()[0],
                    connection.execute(
                        "SELECT COUNT(*) FROM cumulative_derived_scores"
                    ).fetchone()[0],
                )
            self.assertEqual(after_counts, before_counts)

    def test_analyze_rejects_missing_database_manifest_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            missing_database = base / "missing.sqlite"
            code, _, error = self._run_analyze(missing_database, base / "reports")
            self.assertEqual(code, 1)
            self.assertIn("database does not exist", error)
            self.assertFalse(missing_database.exists())

            database_path = base / "pilot.sqlite"
            self._create_database(database_path)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ) as error_output:
                missing_manifest_code = cli.main([
                    "analyze", "--database", str(database_path),
                    "--manifest-id", "not-present", "--output-dir", str(base / "missing"),
                ])
            self.assertEqual(missing_manifest_code, 1)
            self.assertIn("not present", error_output.getvalue())

            code, _, error = self._run_analyze(
                database_path,
                base / "wrong-revision",
                revision_index=8,
            )
            self.assertEqual(code, 1)
            self.assertIn("revision 8 is not present", error)


if __name__ == "__main__":
    unittest.main()
