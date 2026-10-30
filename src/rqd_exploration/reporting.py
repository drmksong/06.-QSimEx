"""Deterministic bounded CSV reports for reference-profile analysis."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Iterable, Iterator

from .analysis import (
    AnalysisLocationStatus,
    AnalysisObservation,
    ReferenceProfileAnalysis,
    ScenarioProfileSummary,
    calculate_scenario_scores,
    fingerprint_analysis,
)
from .fingerprint import JsonValue, fingerprint_snapshot

REPORT_SCHEMA_VERSION = "rqd_exploration_report_v2"
NULL_MARKER = r"\N"

CSV_HEADERS: dict[str, tuple[str, ...]] = {
    "observation_scenarios.csv": (
        "manifest_id", "design_id", "block_id", "sample_index", "realization_seed",
        "execution_fingerprint_digest", "modality", "profile_id", "location_index",
        "raw_rqd", "calculation_rqd", "fixed_jn", "jr_value", "ja_value", "qprime",
        "bin_id", "is_valid", "exclusion_reason", "zero_cross", "actual_support",
        "support_unit",
    ),
    "profile_summaries.csv": (
        "modality", "profile_id", "fixed_jn", "jr_value", "ja_value",
        "observation_count", "valid_support_observation_count", "signature_count",
        "realization_count", "support_unit", "total_support",
        "weighted_median_qprime", "minimum_qprime", "maximum_qprime",
    ),
    "profile_bin_support.csv": (
        "modality", "profile_id", "fixed_jn", "jr_value", "ja_value", "bin_id",
        "support_unit", "bin_support", "total_support", "support_fraction",
    ),
    "bh_face_distribution_contrasts.csv": (
        "bh_profile_id", "face_profile_id", "fixed_jn", "jr_value", "ja_value",
        "comparability_status", "bh_support_m", "face_support_m2",
        "bh_weighted_median_qprime", "face_weighted_median_qprime",
        "face_minus_bh_weighted_median_qprime",
    ),
    "bh_face_bin_contrasts.csv": (
        "bh_profile_id", "face_profile_id", "fixed_jn", "jr_value", "ja_value",
        "bin_id", "comparability_status", "bh_support_fraction",
        "face_support_fraction", "face_minus_bh_support_fraction",
    ),
    "qprime_p32.csv": (
        "manifest_id", "design_id", "block_id", "sample_index", "realization_seed",
        "profile_id", "location_index", "joint_set_id", "p32_m2_per_m3", "jr_value",
        "ja_value", "qprime_bh", "support_length_m",
    ),
    "location_status.csv": (
        "manifest_id", "design_id", "block_id", "sample_index", "realization_seed",
        "execution_fingerprint_digest", "modality", "profile_id", "location_index",
        "status", "reason", "is_valid", "exclusion_reason", "actual_support",
        "support_unit", "zero_support",
    ),
    "unavailable_profiles.csv": ("profile_id", "reason"),
}

REPORT_ROW_CAPS: dict[str, int] = {
    "observation_scenarios.csv": 79_860,
    "profile_summaries.csv": 264,
    "profile_bin_support.csv": 2_904,
    "bh_face_distribution_contrasts.csv": 132,
    "bh_face_bin_contrasts.csv": 1_452,
    "qprime_p32.csv": 39_600,
    "location_status.csv": 1_210,
    "unavailable_profiles.csv": 6,
}

_CSV_FILE_ORDER = tuple(CSV_HEADERS)
_OBSERVATION_KEY_FIELDS = (
    "manifest_id", "design_id", "block_id", "sample_index", "realization_seed",
    "execution_fingerprint_digest", "modality", "profile_id", "location_index",
)
_FLOAT_FIELDS = {
    "observation_scenarios.csv": {
        "raw_rqd", "calculation_rqd", "fixed_jn", "jr_value", "ja_value",
        "qprime", "actual_support",
    },
    "profile_summaries.csv": {
        "fixed_jn", "jr_value", "ja_value", "total_support",
        "weighted_median_qprime", "minimum_qprime", "maximum_qprime",
    },
    "profile_bin_support.csv": {
        "fixed_jn", "jr_value", "ja_value", "bin_support", "total_support",
        "support_fraction",
    },
    "bh_face_distribution_contrasts.csv": {
        "fixed_jn", "jr_value", "ja_value", "bh_support_m", "face_support_m2",
        "bh_weighted_median_qprime", "face_weighted_median_qprime",
        "face_minus_bh_weighted_median_qprime",
    },
    "bh_face_bin_contrasts.csv": {
        "fixed_jn", "jr_value", "ja_value", "bh_support_fraction",
        "face_support_fraction", "face_minus_bh_support_fraction",
    },
    "qprime_p32.csv": {
        "p32_m2_per_m3", "jr_value", "ja_value", "qprime_bh", "support_length_m",
    },
    "location_status.csv": {"actual_support"},
    "unavailable_profiles.csv": set(),
}


@dataclass(frozen=True)
class ReportFilePreflight:
    file_name: str
    expected_rows: int
    row_cap: int


@dataclass(frozen=True)
class ReportPreflight:
    manifest_id: str
    dataset_revision_index: int
    dataset_sha256: str
    analysis_fingerprint_sha256: str
    files: tuple[ReportFilePreflight, ...]


@dataclass(frozen=True)
class ReportExportResult:
    output_directory: Path
    preflight: ReportPreflight
    summary_sha256: str


def _observation_key(item: AnalysisObservation | AnalysisLocationStatus) -> tuple[object, ...]:
    return tuple(getattr(item, name) for name in _OBSERVATION_KEY_FIELDS)


def _nonempty_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _row_counts(
    observations: tuple[AnalysisObservation, ...],
    location_states: tuple[AnalysisLocationStatus, ...],
    result: ReferenceProfileAnalysis,
) -> dict[str, int]:
    return {
        "observation_scenarios.csv": len(observations) * 66,
        "profile_summaries.csv": len(result.scenario_summaries),
        "profile_bin_support.csv": sum(
            len(summary.bin_support) for summary in result.scenario_summaries
        ),
        "bh_face_distribution_contrasts.csv": len(result.distribution_contrasts),
        "bh_face_bin_contrasts.csv": sum(
            len(contrast.bin_fraction_differences)
            for contrast in result.distribution_contrasts
        ),
        "qprime_p32.csv": len(result.qprime_p32_points),
        "location_status.csv": len(location_states),
        "unavailable_profiles.csv": len(result.unavailable_profiles),
    }


def preflight_reference_profile_report(
    manifest_id: str,
    dataset_revision_index: int,
    dataset_sha256: str,
    observations: tuple[AnalysisObservation, ...],
    location_states: tuple[AnalysisLocationStatus, ...],
    result: ReferenceProfileAnalysis,
) -> ReportPreflight:
    """Count all output rows and reject over-cap reports before creating files."""
    _nonempty_text(manifest_id, "manifest_id")
    if isinstance(dataset_revision_index, bool) or not isinstance(
        dataset_revision_index, int
    ) or dataset_revision_index <= 0:
        raise ValueError("dataset_revision_index must be a positive integer")
    if (
        not isinstance(dataset_sha256, str)
        or len(dataset_sha256) != 64
        or any(char not in "0123456789abcdef" for char in dataset_sha256)
    ):
        raise ValueError("dataset_sha256 must be 64 lowercase hexadecimal characters")
    if not isinstance(observations, tuple) or not all(
        isinstance(item, AnalysisObservation) for item in observations
    ):
        raise TypeError("observations must be a tuple of AnalysisObservation values")
    if not isinstance(location_states, tuple) or not all(
        isinstance(item, AnalysisLocationStatus) for item in location_states
    ):
        raise TypeError(
            "location_states must be a tuple of AnalysisLocationStatus values"
        )
    if not isinstance(result, ReferenceProfileAnalysis):
        raise TypeError("result must be a ReferenceProfileAnalysis")
    if result.source_observation_count != len(observations):
        raise ValueError("analysis result source count does not match observations")
    if result.scenario_evaluation_count != len(observations) * 66:
        raise ValueError("analysis result scenario count does not match observations")
    if any(item.manifest_id != manifest_id for item in (*observations, *location_states)):
        raise ValueError("all observations and location states must match manifest_id")
    if len({_observation_key(item) for item in observations}) != len(observations):
        raise ValueError("observations contain duplicate location keys")
    if len({_observation_key(item) for item in location_states}) != len(location_states):
        raise ValueError("location_states contain duplicate location keys")
    if {
        _observation_key(item) for item in observations
    } != {
        _observation_key(item) for item in location_states if item.status == "observed"
    }:
        raise ValueError("observed location states must match observations exactly")
    if any(item.manifest_id != manifest_id for item in result.qprime_p32_points):
        raise ValueError("derived report rows must match manifest_id")

    counts = _row_counts(observations, location_states, result)
    files = tuple(
        ReportFilePreflight(file_name, counts[file_name], REPORT_ROW_CAPS[file_name])
        for file_name in _CSV_FILE_ORDER
    )
    exceeded = [
        f"{item.file_name}: {item.expected_rows} > {item.row_cap}"
        for item in files
        if item.expected_rows > item.row_cap
    ]
    if exceeded:
        raise ValueError("report row cap exceeded: " + "; ".join(exceeded))
    analysis_fingerprint = fingerprint_analysis(
        dataset_revision_index,
        dataset_sha256,
    )
    return ReportPreflight(
        manifest_id,
        dataset_revision_index,
        dataset_sha256,
        analysis_fingerprint.sha256_hex,
        files,
    )


def _format_field(value: object) -> str:
    if value is None:
        return NULL_MARKER
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("CSV floating-point values must be finite")
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # Escape a leading backslash so a literal text value cannot be read as NULL.
        return "\\" + value if value.startswith("\\") else value
    raise TypeError(f"unsupported CSV value type: {type(value).__name__}")


def _format_row(file_name: str, row: tuple[object, ...]) -> tuple[str, ...]:
    headers = CSV_HEADERS[file_name]
    if len(row) != len(headers):
        raise ValueError(f"{file_name} row has {len(row)} values; expected {len(headers)}")
    formatted: list[str] = []
    for header, value in zip(headers, row):
        if header in _FLOAT_FIELDS[file_name] and value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{file_name}.{header} must be a number or NULL")
            formatted.append(_format_field(float(value)))
        else:
            formatted.append(_format_field(value))
    return tuple(formatted)


def _score_rows(
    observations: tuple[AnalysisObservation, ...],
) -> Iterator[tuple[object, ...]]:
    for observation in sorted(observations, key=_observation_key):
        support = (
            observation.support_length_m
            if observation.modality == "BH"
            else observation.support_area_m2
        )
        for score in calculate_scenario_scores(
            observation.raw_rqd,
            observation.fixed_jn,
            zero_cross=observation.zero_cross,
        ):
            yield (
                observation.manifest_id, observation.design_id, observation.block_id,
                observation.sample_index, observation.realization_seed,
                observation.execution_fingerprint_digest, observation.modality,
                observation.profile_id, observation.location_index, score.raw_rqd,
                score.calculation_rqd, score.fixed_jn, score.jr_value, score.ja_value,
                score.qprime, score.bin_id, observation.is_valid,
                observation.exclusion_reason, score.zero_cross, support,
                "m" if observation.modality == "BH" else "m2",
            )


def _profile_rows(
    summaries: tuple[ScenarioProfileSummary, ...],
) -> Iterator[tuple[object, ...]]:
    for item in summaries:
        yield (
            item.modality, item.profile_id, item.fixed_jn, item.jr_value, item.ja_value,
            item.observation_count, item.valid_support_observation_count,
            item.signature_count, item.realization_count, item.support_unit,
            item.total_support, item.weighted_median_qprime, item.minimum_qprime,
            item.maximum_qprime,
        )


def _profile_bin_rows(
    summaries: tuple[ScenarioProfileSummary, ...],
) -> Iterator[tuple[object, ...]]:
    for item in summaries:
        for bin_item in item.bin_support:
            yield (
                item.modality, item.profile_id, item.fixed_jn, item.jr_value,
                item.ja_value, bin_item.bin_id, item.support_unit, bin_item.support,
                item.total_support, bin_item.support_fraction,
            )


def _distribution_rows(result: ReferenceProfileAnalysis) -> Iterator[tuple[object, ...]]:
    for item in result.distribution_contrasts:
        yield (
            item.bh_profile_id, item.face_profile_id, item.fixed_jn, item.jr_value,
            item.ja_value, item.comparability_status, item.bh_support_m,
            item.face_support_m2, item.bh_weighted_median_qprime,
            item.face_weighted_median_qprime,
            item.face_minus_bh_weighted_median_qprime,
        )


def _distribution_bin_rows(
    result: ReferenceProfileAnalysis,
) -> Iterator[tuple[object, ...]]:
    summaries = {
        (
            item.modality, item.profile_id, item.fixed_jn, item.jr_value, item.ja_value,
        ): item
        for item in result.scenario_summaries
    }
    for item in result.distribution_contrasts:
        bh_summary = summaries[(
            "BH", item.bh_profile_id, item.fixed_jn, item.jr_value, item.ja_value,
        )]
        face_summary = summaries[(
            "face", item.face_profile_id, item.fixed_jn, item.jr_value, item.ja_value,
        )]
        bh_bin_fractions = {
            entry.bin_id: entry.support_fraction for entry in bh_summary.bin_support
        }
        face_bin_fractions = {
            entry.bin_id: entry.support_fraction for entry in face_summary.bin_support
        }
        for difference in item.bin_fraction_differences:
            bh_fraction = bh_bin_fractions[difference.bin_id]
            face_fraction = face_bin_fractions[difference.bin_id]
            yield (
                item.bh_profile_id, item.face_profile_id, item.fixed_jn,
                item.jr_value, item.ja_value, difference.bin_id,
                item.comparability_status, bh_fraction, face_fraction,
                difference.face_minus_bh_support_fraction,
            )


def _p32_rows(result: ReferenceProfileAnalysis) -> Iterator[tuple[object, ...]]:
    for item in sorted(
        result.qprime_p32_points,
        key=lambda value: (
            value.manifest_id, value.design_id, value.block_id, value.sample_index,
            value.realization_seed, value.profile_id, value.location_index,
            value.joint_set_id, value.jr_value, value.ja_value,
        ),
    ):
        yield (
            item.manifest_id, item.design_id, item.block_id, item.sample_index,
            item.realization_seed, item.profile_id, item.location_index,
            item.joint_set_id, item.p32_m2_per_m3, item.jr_value, item.ja_value,
            item.qprime_bh, item.support_length_m,
        )


def _location_rows(
    observations: tuple[AnalysisObservation, ...],
    location_states: tuple[AnalysisLocationStatus, ...],
) -> Iterator[tuple[object, ...]]:
    observation_by_key = {_observation_key(item): item for item in observations}
    for status in sorted(location_states, key=_observation_key):
        observation = observation_by_key.get(_observation_key(status))
        support = None
        unit = None
        valid = None
        exclusion_reason = None
        zero_support = None
        if observation is not None:
            support = (
                observation.support_length_m
                if observation.modality == "BH"
                else observation.support_area_m2
            )
            unit = "m" if observation.modality == "BH" else "m2"
            valid = observation.is_valid
            exclusion_reason = observation.exclusion_reason
            zero_support = support == 0.0
        yield (
            status.manifest_id, status.design_id, status.block_id,
            status.sample_index, status.realization_seed,
            status.execution_fingerprint_digest, status.modality, status.profile_id,
            status.location_index, status.status, status.reason, valid,
            exclusion_reason, support, unit, zero_support,
        )


def _unavailable_rows(result: ReferenceProfileAnalysis) -> Iterator[tuple[object, ...]]:
    for item in sorted(result.unavailable_profiles, key=lambda value: value.profile_id):
        yield item.profile_id, item.reason


def _rows_by_file(
    observations: tuple[AnalysisObservation, ...],
    location_states: tuple[AnalysisLocationStatus, ...],
    result: ReferenceProfileAnalysis,
) -> dict[str, Iterable[tuple[object, ...]]]:
    return {
        "observation_scenarios.csv": _score_rows(observations),
        "profile_summaries.csv": _profile_rows(result.scenario_summaries),
        "profile_bin_support.csv": _profile_bin_rows(result.scenario_summaries),
        "bh_face_distribution_contrasts.csv": _distribution_rows(result),
        "bh_face_bin_contrasts.csv": _distribution_bin_rows(result),
        "qprime_p32.csv": _p32_rows(result),
        "location_status.csv": _location_rows(observations, location_states),
        "unavailable_profiles.csv": _unavailable_rows(result),
    }


def _summary_payload(
    preflight: ReportPreflight,
    result: ReferenceProfileAnalysis,
) -> dict[str, JsonValue]:
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "manifest_id": preflight.manifest_id,
        "dataset_revision_index": preflight.dataset_revision_index,
        "dataset_sha256": preflight.dataset_sha256,
        "analysis_fingerprint_sha256": preflight.analysis_fingerprint_sha256,
        "files": [
            {
                "file_name": item.file_name,
                "row_count": item.expected_rows,
                "planned_row_cap": item.row_cap,
            }
            for item in preflight.files
        ],
        "unavailable_profiles": [
            {"profile_id": item.profile_id, "reason": item.reason}
            for item in sorted(
                result.unavailable_profiles,
                key=lambda value: value.profile_id,
            )
        ],
    }


def export_reference_profile_report(
    output_directory: Path,
    manifest_id: str,
    dataset_revision_index: int,
    dataset_sha256: str,
    observations: tuple[AnalysisObservation, ...],
    location_states: tuple[AnalysisLocationStatus, ...],
    result: ReferenceProfileAnalysis,
) -> ReportExportResult:
    """Write approved CSVs and canonical summary after a successful row preflight."""
    if not isinstance(output_directory, Path):
        raise TypeError("output_directory must be a pathlib.Path")
    preflight = preflight_reference_profile_report(
        manifest_id,
        dataset_revision_index,
        dataset_sha256,
        observations,
        location_states,
        result,
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    rows_by_file = _rows_by_file(observations, location_states, result)
    for item in preflight.files:
        path = output_directory / item.file_name
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(CSV_HEADERS[item.file_name])
            written_rows = 0
            for row in rows_by_file[item.file_name]:
                writer.writerow(_format_row(item.file_name, row))
                written_rows += 1
            if written_rows != item.expected_rows:
                raise RuntimeError(
                    f"{item.file_name} wrote {written_rows} rows; "
                    f"preflight expected {item.expected_rows}"
                )

    summary_bytes = fingerprint_snapshot(
        _summary_payload(preflight, result)
    ).canonical_bytes
    summary_path = output_directory / "report_summary.json"
    with summary_path.open("wb") as stream:
        stream.write(summary_bytes)
    return ReportExportResult(
        output_directory,
        preflight,
        sha256(summary_bytes).hexdigest(),
    )
