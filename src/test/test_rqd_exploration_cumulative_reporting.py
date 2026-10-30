from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from src.rqd_exploration import analysis, cumulative_reporting
from src.rqd_exploration.dataset import CumulativeRawDatasetRevision
from src.rqd_exploration.fingerprint import fingerprint_snapshot


class TestCumulativeCoverageReporting(unittest.TestCase):
    def _revision(
        self,
        *,
        conflicting_duplicate: bool = False,
    ) -> CumulativeRawDatasetRevision:
        first = analysis.AnalysisObservation(
            manifest_id="batch-a",
            design_id="design",
            block_id="block",
            sample_index=0,
            realization_seed=17,
            execution_fingerprint_digest="a" * 64,
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=80.0,
            fixed_jn=2.0,
            is_valid=True,
            exclusion_reason=None,
            zero_cross=False,
            support_length_m=4.0,
            support_area_m2=None,
            p32_by_joint_set=(("joint-set-1", 2.5),),
        )
        duplicate = replace(
            first,
            manifest_id="batch-b",
            raw_rqd=90.0 if conflicting_duplicate else 80.0,
        )
        second_signature = analysis.AnalysisObservation(
            manifest_id="batch-b",
            design_id="design",
            block_id="block",
            sample_index=1,
            realization_seed=18,
            execution_fingerprint_digest="b" * 64,
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=95.0,
            fixed_jn=2.0,
            is_valid=True,
            exclusion_reason=None,
            zero_cross=False,
            support_length_m=2.0,
            support_area_m2=None,
            p32_by_joint_set=(("joint-set-1", 3.0),),
        )
        observations = (first, duplicate, second_signature)
        statuses = tuple(
            analysis.AnalysisLocationStatus(
                item.manifest_id,
                item.design_id,
                item.block_id,
                item.sample_index,
                item.realization_seed,
                item.execution_fingerprint_digest,
                item.modality,
                item.profile_id,
                item.location_index,
                "observed",
                None,
            )
            for item in observations
        )
        snapshot = {
            "schema_version": 1,
            "batches": [],
        }
        return CumulativeRawDatasetRevision(
            revision_index=1,
            previous_revision_index=None,
            dataset_sha256=fingerprint_snapshot(snapshot).sha256_hex,
            dataset_snapshot=snapshot,
            manifest_ids=("batch-a", "batch-b"),
            observations=observations,
            location_states=statuses,
            source_attempt_indices=(),
            independent_execution_fingerprints=("a" * 64, "b" * 64),
            raw_attempt_count=2,
            raw_observation_count=3,
        )

    def _read_rows(self, folder: Path, file_name: str) -> list[dict[str, str]]:
        with (folder / file_name).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_identical_fingerprint_is_preserved_but_counted_once(self) -> None:
        revision = self._revision()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "reports"
            report = cumulative_reporting.export_cumulative_coverage_report(
                output,
                revision,
                jr_values=(1.0,),
                ja_values=(1.0,),
            )

            self.assertEqual(report.preflight.source_observation_count, 3)
            self.assertEqual(report.preflight.unique_observation_count, 2)
            self.assertEqual(report.preflight.source_execution_fingerprint_count, 2)
            self.assertEqual(report.preflight.eligible_execution_fingerprint_count, 2)
            self.assertEqual(report.preflight.conflicted_fingerprint_count, 0)
            row_counts = {
                item.file_name: item.expected_rows
                for item in report.preflight.files
            }
            self.assertEqual(row_counts["signature_observation_scenarios.csv"], 2)
            self.assertEqual(row_counts["source_observation_provenance.csv"], 3)
            self.assertEqual(row_counts["fingerprint_conflicts.csv"], 0)

            source_rows = self._read_rows(output, "source_observation_provenance.csv")
            self.assertEqual(len(source_rows), 3)
            self.assertEqual(
                sum(row["is_coverage_representative"] == "true" for row in source_rows),
                2,
            )
            self.assertEqual(
                sum(row["fingerprint_status"] == "repeated" for row in source_rows),
                2,
            )
            batch_rows = self._read_rows(output, "batch_signature_coverage.csv")
            self.assertEqual(
                [(row["manifest_id"], row["shared_fingerprint_count"]) for row in batch_rows],
                [("batch-a", "1"), ("batch-b", "1")],
            )
            summary = json.loads((output / "report_summary.json").read_text())
            self.assertEqual(summary["row_policy"],
                             "exact preflight before writing; stream rows; no fixed row cap")

    def test_conflicting_fingerprint_is_reported_and_excluded_without_stopping(self) -> None:
        revision = self._revision(conflicting_duplicate=True)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "reports"
            report = cumulative_reporting.export_cumulative_coverage_report(
                output,
                revision,
                jr_values=(1.0,),
                ja_values=(1.0,),
            )

            self.assertEqual(report.preflight.source_observation_count, 3)
            self.assertEqual(report.preflight.unique_observation_count, 1)
            self.assertEqual(report.preflight.source_execution_fingerprint_count, 2)
            self.assertEqual(report.preflight.eligible_execution_fingerprint_count, 1)
            self.assertEqual(report.preflight.conflicted_fingerprint_count, 1)
            self.assertTrue((output / "cumulative_bin_coverage.csv").is_file())
            conflict_rows = self._read_rows(output, "fingerprint_conflicts.csv")
            self.assertEqual(len(conflict_rows), 1)
            self.assertEqual(
                conflict_rows[0]["execution_fingerprint_digest"],
                "a" * 64,
            )
            self.assertEqual(conflict_rows[0]["conflict_types"], "observation_values")
            source_rows = self._read_rows(output, "source_observation_provenance.csv")
            conflicted_rows = [
                row for row in source_rows if row["execution_fingerprint_digest"] == "a" * 64
            ]
            self.assertEqual(len(conflicted_rows), 2)
            self.assertTrue(all(row["fingerprint_status"] == "conflict"
                                for row in conflicted_rows))
            self.assertTrue(all(row["is_coverage_representative"] == "false"
                                for row in conflicted_rows))
            scenario_rows = self._read_rows(output, "signature_observation_scenarios.csv")
            self.assertEqual(len(scenario_rows), 1)
            self.assertEqual(
                scenario_rows[0]["execution_fingerprint_digest"],
                "b" * 64,
            )

    def test_conflicting_location_status_excludes_fingerprint(self) -> None:
        revision = self._revision()
        statuses = list(revision.location_states)
        statuses[1] = replace(
            statuses[1],
            status="unavailable",
            reason="unavailable in duplicate source batch",
        )
        revision = replace(
            revision,
            observations=(revision.observations[0], revision.observations[2]),
            location_states=tuple(statuses),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "reports"
            report = cumulative_reporting.export_cumulative_coverage_report(
                output,
                revision,
                jr_values=(1.0,),
                ja_values=(1.0,),
            )

            self.assertEqual(report.preflight.conflicted_fingerprint_count, 1)
            conflicts = self._read_rows(output, "fingerprint_conflicts.csv")
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0]["conflict_types"], "location_status")
            self.assertEqual(
                conflicts[0]["execution_fingerprint_digest"],
                "a" * 64,
            )
            source_rows = self._read_rows(output, "signature_observation_scenarios.csv")
            self.assertEqual(len(source_rows), 1)
            self.assertEqual(
                source_rows[0]["execution_fingerprint_digest"],
                "b" * 64,
            )


if __name__ == "__main__":
    unittest.main()
