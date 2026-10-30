from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.rqd_exploration import analysis, reporting
from src.rqd_exploration.fingerprint import fingerprint_snapshot


class TestReferenceProfileReporting(unittest.TestCase):
    def _records(
        self,
    ) -> tuple[
        tuple[analysis.AnalysisObservation, ...],
        tuple[analysis.AnalysisLocationStatus, ...],
        analysis.ReferenceProfileAnalysis,
    ]:
        bh = analysis.AnalysisObservation(
            manifest_id="manifest",
            design_id="design",
            block_id="block",
            sample_index=0,
            realization_seed=17,
            execution_fingerprint_digest="a" * 64,
            modality="BH",
            profile_id="bh-main",
            location_index=0,
            raw_rqd=80.0,
            fixed_jn=1.0,
            is_valid=True,
            exclusion_reason=None,
            zero_cross=False,
            support_length_m=4,
            support_area_m2=None,
            p32_by_joint_set=(("joint-set-1", 2.5),),
        )
        face = analysis.AnalysisObservation(
            manifest_id="manifest",
            design_id="design",
            block_id="block",
            sample_index=0,
            realization_seed=17,
            execution_fingerprint_digest="a" * 64,
            modality="face",
            profile_id="face-main",
            location_index=0,
            raw_rqd=30.0,
            fixed_jn=1.0,
            is_valid=False,
            exclusion_reason="no valid scanline support",
            zero_cross=True,
            support_length_m=None,
            support_area_m2=0,
            p32_by_joint_set=(),
        )
        observations = (bh, face)
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
        ) + (
            analysis.AnalysisLocationStatus(
                "manifest", "design", "block", 0, 17, "a" * 64,
                "BH", "bh-main", 1, "unavailable", "outside measured boundary",
            ),
        )
        result = analysis.analyze_reference_profiles(observations, statuses)
        return observations, statuses, result

    def _export(self, folder: Path, reverse: bool = False) -> reporting.ReportExportResult:
        observations, statuses, result = self._records()
        if reverse:
            observations = tuple(reversed(observations))
            statuses = tuple(reversed(statuses))
            result = analysis.analyze_reference_profiles(
                observations,
                statuses,
            )
        return reporting.export_reference_profile_report(
            folder,
            "manifest",
            1,
            "b" * 64,
            observations,
            statuses,
            result,
        )

    def test_preflight_counts_files_and_reports_fixed_caps(self) -> None:
        observations, statuses, result = self._records()

        preflight = reporting.preflight_reference_profile_report(
            "manifest", 1, "b" * 64, observations, statuses, result,
        )

        counts = {item.file_name: item.expected_rows for item in preflight.files}
        self.assertEqual(counts["observation_scenarios.csv"], 132)
        self.assertEqual(counts["profile_summaries.csv"], 132)
        self.assertEqual(counts["profile_bin_support.csv"], 1_452)
        self.assertEqual(counts["bh_face_distribution_contrasts.csv"], 66)
        self.assertEqual(counts["bh_face_bin_contrasts.csv"], 726)
        self.assertEqual(counts["qprime_p32.csv"], 66)
        self.assertNotIn("target_observations.csv", counts)
        self.assertNotIn("target_summaries.csv", counts)
        self.assertEqual(counts["location_status.csv"], 3)
        self.assertEqual(counts["unavailable_profiles.csv"], len(result.unavailable_profiles))
        self.assertEqual(preflight.analysis_fingerprint_sha256,
                         analysis.fingerprint_analysis(1, "b" * 64).sha256_hex)

    def test_cap_overflow_fails_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "reports"
            observations, statuses, result = self._records()
            caps = dict(reporting.REPORT_ROW_CAPS)
            caps["observation_scenarios.csv"] = 131
            with patch.object(reporting, "REPORT_ROW_CAPS", caps):
                with self.assertRaisesRegex(ValueError, "row cap exceeded"):
                    reporting.export_reference_profile_report(
                        output, "manifest", 1, "b" * 64,
                        observations, statuses, result,
                    )
            self.assertFalse(output.exists())

    def test_csv_shapes_null_boolean_and_summary_are_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "reports"
            result = self._export(output)

            for file_name, headers in reporting.CSV_HEADERS.items():
                with (output / file_name).open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.reader(stream))
                self.assertEqual(tuple(rows[0]), headers)
                expected = next(
                    item.expected_rows
                    for item in result.preflight.files
                    if item.file_name == file_name
                )
                self.assertEqual(len(rows) - 1, expected)

            with (output / "observation_scenarios.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                scenario_rows = list(csv.DictReader(stream))
            self.assertEqual(scenario_rows[0]["is_valid"], "true")
            self.assertEqual(scenario_rows[66]["is_valid"], "false")
            self.assertEqual(scenario_rows[66]["actual_support"], "0.0")
            self.assertEqual(scenario_rows[66]["support_unit"], "m2")
            self.assertEqual(
                scenario_rows[66]["exclusion_reason"],
                "no valid scanline support",
            )
            with (output / "location_status.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                location_rows = list(csv.DictReader(stream))
            unavailable = next(row for row in location_rows if row["status"] == "unavailable")
            self.assertEqual(unavailable["reason"], "outside measured boundary")
            self.assertEqual(unavailable["is_valid"], r"\N")
            self.assertEqual(unavailable["actual_support"], r"\N")

            with (output / "bh_face_bin_contrasts.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                bin_contrasts = list(csv.DictReader(stream))
            populated_bh_bin = next(
                row for row in bin_contrasts
                if row["bh_support_fraction"] == "1.0"
            )
            self.assertEqual(populated_bh_bin["face_support_fraction"], "0.0")
            self.assertEqual(
                populated_bh_bin["face_minus_bh_support_fraction"],
                r"\N",
            )

            summary_path = output / "report_summary.json"
            summary_bytes = summary_path.read_bytes()
            summary = json.loads(summary_bytes)
            self.assertEqual(
                summary_bytes,
                fingerprint_snapshot(summary).canonical_bytes,
            )
            self.assertNotIn("generated_at", summary)
            self.assertEqual(
                summary["analysis_fingerprint_sha256"],
                result.preflight.analysis_fingerprint_sha256,
            )

    def test_literal_null_marker_text_is_escaped_without_changing_csv_rules(self) -> None:
        with self.assertRaises(ValueError):
            reporting._format_field(math.nan)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "roundtrip.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow((reporting._format_field(None),))
                writer.writerow((reporting._format_field(r"\N"),))
                writer.writerow((reporting._format_field("line one\nline two"),))
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows, [[r"\N"], [r"\\N"], ["line one\nline two"]])

    def test_export_is_byte_deterministic_for_reordered_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory) / "first"
            second = Path(temporary_directory) / "second"
            self._export(first)
            self._export(second, reverse=True)

            for file_name in (*reporting.CSV_HEADERS, "report_summary.json"):
                self.assertEqual(
                    (first / file_name).read_bytes(),
                    (second / file_name).read_bytes(),
                )

    def test_preflight_rejects_mismatched_analysis_inputs(self) -> None:
        observations, statuses, result = self._records()
        with self.assertRaisesRegex(ValueError, "source count"):
            reporting.preflight_reference_profile_report(
                "manifest", 1, "b" * 64, observations[:1], statuses, result,
            )


if __name__ == "__main__":
    unittest.main()
