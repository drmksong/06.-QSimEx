from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from src.rqd_exploration import cli
from src.rqd_exploration.measurement import (
    MeasurementEvidence,
    MeasurementResult,
    PlannedLocationState,
    RawBHObservation,
    plan_measurement_locations,
)
from src.rqd_exploration.records import PlannedBHInterval


class TestCumulativeWorkflowAcceptance(unittest.TestCase):
    def _command(self, *arguments: str) -> list[dict]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(arguments))
        self.assertEqual(code, 0, stderr.getvalue())
        remaining = stdout.getvalue().strip()
        payloads = []
        decoder = json.JSONDecoder()
        while remaining:
            payload, end = decoder.raw_decode(remaining)
            payloads.append(payload)
            remaining = remaining[end:].strip()
        return payloads

    def _fixture_measurement(self, case, factory, seed, **kwargs) -> MeasurementResult:
        locations = plan_measurement_locations(case)
        first_bh = next(item for item in locations if isinstance(item, PlannedBHInterval))
        observation = RawBHObservation(
            profile_id=first_bh.profile_id,
            location_index=first_bh.location_index,
            start_m=first_bh.start_m,
            end_m=first_bh.end_m,
            raw_rqd=80.0,
            support_length_m=1.0,
            method_id="deere_direct_rqd",
            method_version="qsimex-fixed-rqd-v1",
            is_valid=True,
            exclusion_reason=None,
            zero_cross=False,
            evidence=MeasurementEvidence(
                0, (0.0, 15.0, 15.0), (1.0, 0.0, 0.0), 1.0, (0.2,),
            ),
        )
        return MeasurementResult(
            planned_locations=locations,
            location_states=tuple(
                PlannedLocationState(
                    "BH" if isinstance(item, PlannedBHInterval) else "face",
                    item.profile_id,
                    item.location_index,
                    "observed" if item is first_bh else "unavailable",
                    None if item is first_bh else "acceptance fixture: not measured",
                )
                for item in locations
            ),
            observations=(observation,),
            excluded_bh_tail_lengths_m=(),
            face_stop_reason="tunnel_end",
        )

    def test_two_pilots_interrupt_resume_append_rescore_and_report(self) -> None:
        root = Path(__file__).resolve().parents[2]
        backend = ModuleType("src.euler_campaign.mlx_backend")
        backend.MLX_GENERATOR_VERSION = "acceptance-fixture-generator-v1"
        backend.require_mlx_gpu = lambda: ("fixture-version", "fixture-device")
        factory = Mock()
        factory.generate.side_effect = AssertionError("real DFN generation forbidden")
        backend.MlxCaseJointFactory = lambda: factory
        calls = []

        def measure(case, factory, seed, **kwargs):
            calls.append((case.domain.jn, len(case.joint_sets)))
            if len(calls) == 2:
                raise KeyboardInterrupt
            return self._fixture_measurement(case, factory, seed, **kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            sys.modules, {"src.euler_campaign.mlx_backend": backend},
        ), patch(
            "src.rqd_exploration.runner.generate_and_measure", side_effect=measure,
        ) as measurement:
            database = Path(directory) / "acceptance.sqlite"
            output = Path(directory) / "reports"
            configs = [root / "config" / name for name in (
                "rqd_exploration_pilot.yml", "rqd_exploration_pilot2.yml",
            )]

            def run(path):
                return self._command(
                    "run", "--config", str(path), "--database", str(database),
                    "--confirm-execution",
                )

            with self.assertRaises(KeyboardInterrupt):
                run(configs[0])
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute(
                    "SELECT status FROM attempts ORDER BY sample_index",
                ).fetchall(), [("succeeded",), ("running",)])
                first_rows = connection.execute(
                    "SELECT * FROM observations ORDER BY manifest_id, sample_index",
                ).fetchall()
            resumed = run(configs[0])
            self.assertEqual(resumed[0]["batch_action"], "resumed")
            self.assertEqual(resumed[-1]["run_summary"]["simulation_count"], 9)
            self.assertNotIn("maximum_simulations", resumed[-1]["run_summary"])
            self.assertEqual(len(calls), 11)
            self.assertEqual(calls[:6], [(2.0, 1)] * 6)
            self.assertEqual(calls[6:], [(4.0, 2)] * 5)
            first = self._command("analyze-cumulative", "--database", str(database))[0]
            self.assertEqual(first["selected_observation_count"], 10)
            self.assertEqual(first["derived_score_rows"], 660)
            added = run(configs[1])
            self.assertEqual(added[0]["batch_action"], "added")
            self.assertEqual(added[-1]["run_summary"]["simulation_count"], 10)
            self.assertEqual(added[-1]["run_summary"]["termination_reason"], "jobs_complete")
            self.assertEqual(calls[11:], [(9.0, 3)] * 5 + [(15.0, 4)] * 5)
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM manifest",
                ).fetchone()[0], 2)
                self.assertEqual(connection.execute(
                    "SELECT status, COUNT(*) FROM attempts GROUP BY status",
                ).fetchall(), [("succeeded", 20)])
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM location_status",
                ).fetchone()[0], 2420)
                self.assertEqual(connection.execute(
                    "SELECT * FROM observations ORDER BY manifest_id, sample_index",
                ).fetchall().count(first_rows[0]), 1)
                raw_before = {
                    table: connection.execute(f"SELECT * FROM {table}").fetchall()
                    for table in ("observations", "measurement_evidence", "location_status")
                }
            measurement.side_effect = AssertionError("analysis/report must not simulate")
            cumulative = self._command(
                "analyze-cumulative", "--database", str(database),
            )[0]
            self.assertEqual(cumulative["selected_observation_count"], 20)
            self.assertEqual(cumulative["independent_realization_count"], 20)
            self.assertEqual(cumulative["derived_score_rows"], 1320)
            self.assertGreater(cumulative["dataset_revision_index"],
                               first["dataset_revision_index"])
            subset_args = (
                "analyze-cumulative", "--database", str(database),
                "--jr-values", "1", "--ja-values", "1",
            )
            subset = self._command(*subset_args)[0]
            repeated = self._command(*subset_args)[0]
            self.assertEqual(subset, repeated)
            self.assertEqual(subset["derived_score_rows"], 20)
            self.assertNotEqual(subset["analysis_fingerprint_sha256"],
                                cumulative["analysis_fingerprint_sha256"])
            historical = self._command(
                "analyze-cumulative", "--database", str(database),
                "--revision-index", str(first["dataset_revision_index"]),
            )[0]
            self.assertEqual(first, historical)
            with sqlite3.connect(database) as connection:
                for table, before in raw_before.items():
                    self.assertEqual(connection.execute(
                        f"SELECT * FROM {table}",
                    ).fetchall(), before)
            db_bytes = database.read_bytes()
            report = self._command(
                "report-cumulative", "--database", str(database),
                "--output-dir", str(output),
            )[0]
            self.assertEqual(database.read_bytes(), db_bytes)
            self.assertFalse(report["database_modified"])
            self.assertFalse(report["simulation_started"])
            self.assertEqual(report["unique_observation_count"], 20)
            self.assertEqual(report["conflicted_fingerprint_count"], 0)
            for filename, expected in report["file_rows"].items():
                with (output / filename).open(encoding="utf-8", newline="") as stream:
                    self.assertEqual(sum(1 for _ in csv.DictReader(stream)), expected)
            with (output / "signature_observation_scenarios.csv").open(
                encoding="utf-8", newline="",
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1320)
            self.assertEqual({float(row["fixed_jn"]) for row in rows}, {2, 4, 9, 15})
            for row in rows:
                self.assertAlmostEqual(
                    float(row["qprime"]),
                    80 / float(row["fixed_jn"]) * float(row["jr_value"])
                    / float(row["ja_value"]),
                )
            with (output / "cumulative_bin_coverage.csv").open(
                encoding="utf-8", newline="",
            ) as stream:
                bins = list(csv.DictReader(stream))
            self.assertEqual(len(bins), 4 * 66 * 11)
            groups = {}
            for row in bins:
                key = (row["fixed_jn"], row["jr_value"], row["ja_value"])
                groups.setdefault(key, []).append(row)
                self.assertEqual(row["support_unit"], "m")
            for group in groups.values():
                self.assertEqual(
                    {row["bin_id"] for row in group},
                    {*(str(index) for index in range(1, 11)), "qprime_gt_400"},
                )
                self.assertAlmostEqual(sum(float(row["bin_support"]) for row in group), 5)
                self.assertAlmostEqual(sum(float(row["support_fraction"]) for row in group), 1)
            factory.generate.assert_not_called()
            self.assertEqual(measurement.call_count, 21)


if __name__ == "__main__":
    unittest.main()
