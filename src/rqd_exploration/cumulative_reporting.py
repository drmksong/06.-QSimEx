"""Cumulative coverage reports with source provenance and unbounded streaming CSVs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Iterator

from . import analysis
from .analysis import (
    AnalysisLocationStatus,
    AnalysisObservation,
    ReferenceProfileAnalysis,
    ScenarioProfileSummary,
    calculate_scenario_scores,
)
from .dataset import CumulativeRawDatasetRevision
from .fingerprint import JsonValue, fingerprint_snapshot
from .reporting import _format_field

CUMULATIVE_REPORT_SCHEMA_VERSION = "rqd_exploration_cumulative_coverage_v1"

CUMULATIVE_CSV_HEADERS: dict[str, tuple[str, ...]] = {
    "signature_observation_scenarios.csv": (
        "source_manifest_id", "design_id", "block_id", "sample_index",
        "realization_seed", "execution_fingerprint_digest", "modality",
        "profile_id", "location_index", "raw_rqd", "calculation_rqd",
        "fixed_jn", "jr_value", "ja_value", "qprime", "bin_id", "is_valid",
        "exclusion_reason", "zero_cross", "actual_support", "support_unit",
    ),
    "source_observation_provenance.csv": (
        "manifest_id", "design_id", "block_id", "sample_index",
        "realization_seed", "execution_fingerprint_digest", "modality",
        "profile_id", "location_index", "raw_rqd", "fixed_jn", "is_valid",
        "exclusion_reason", "zero_cross", "actual_support", "support_unit",
        "fingerprint_status", "source_record_count", "is_coverage_representative",
    ),
    "cumulative_profile_summaries.csv": (
        "modality", "profile_id", "fixed_jn", "jr_value", "ja_value",
        "observation_count", "valid_support_observation_count", "signature_count",
        "realization_count", "execution_fingerprint_count", "support_unit",
        "total_support", "weighted_median_qprime", "minimum_qprime",
        "maximum_qprime",
    ),
    "cumulative_bin_coverage.csv": (
        "modality", "profile_id", "fixed_jn", "jr_value", "ja_value", "bin_id",
        "support_unit", "bin_support", "total_support", "support_fraction",
        "occupied", "execution_fingerprint_count",
    ),
    "batch_signature_coverage.csv": (
        "manifest_id", "source_observation_count", "source_location_status_count",
        "execution_fingerprint_count", "batch_exclusive_fingerprint_count",
        "shared_fingerprint_count", "conflicted_fingerprint_count",
    ),
    "fingerprint_conflicts.csv": (
        "execution_fingerprint_digest", "modality", "profile_id", "location_index",
        "conflict_types", "source_manifest_ids",
    ),
    "location_status_sources.csv": (
        "manifest_id", "design_id", "block_id", "sample_index",
        "realization_seed", "execution_fingerprint_digest", "modality",
        "profile_id", "location_index", "status", "reason", "fingerprint_status",
        "source_record_count", "is_coverage_representative",
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
        "source_manifest_id", "design_id", "block_id", "sample_index",
        "realization_seed", "profile_id", "location_index", "joint_set_id",
        "p32_m2_per_m3", "jr_value", "ja_value", "qprime_bh", "support_length_m",
    ),
    "unavailable_profiles.csv": ("profile_id", "reason"),
}

_CSV_FILE_ORDER = tuple(CUMULATIVE_CSV_HEADERS)


@dataclass(frozen=True)
class CumulativeReportFile:
    file_name: str
    expected_rows: int


@dataclass(frozen=True)
class FingerprintConflict:
    execution_fingerprint_digest: str
    modality: str | None
    profile_id: str | None
    location_index: int | None
    conflict_types: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]


@dataclass(frozen=True)
class CumulativeReportPreflight:
    dataset_revision_index: int
    dataset_sha256: str
    analysis_fingerprint_sha256: str
    files: tuple[CumulativeReportFile, ...]
    source_observation_count: int
    unique_observation_count: int
    source_execution_fingerprint_count: int
    eligible_execution_fingerprint_count: int
    conflicted_fingerprint_count: int


@dataclass(frozen=True)
class CumulativeReportExportResult:
    output_directory: Path
    preflight: CumulativeReportPreflight
    summary_sha256: str


@dataclass(frozen=True)
class _PreparedReport:
    observations: tuple[AnalysisObservation, ...]
    location_states: tuple[AnalysisLocationStatus, ...]
    analysis_result: ReferenceProfileAnalysis
    conflicts: tuple[FingerprintConflict, ...]
    fingerprint_status: dict[str, str]
    observation_source_counts: dict[tuple[object, ...], int]
    location_source_counts: dict[tuple[object, ...], int]
    representative_observation_keys: frozenset[tuple[object, ...]]
    representative_location_keys: frozenset[tuple[object, ...]]
    batch_fingerprints: dict[str, frozenset[str]]
    batch_observation_counts: dict[str, int]
    batch_location_counts: dict[str, int]
    execution_fingerprint_counts: dict[tuple[object, ...], int]
    bin_execution_fingerprint_counts: dict[tuple[object, ...], int]
    jr_values: tuple[float, ...]
    ja_values: tuple[float, ...]


def _observation_source_key(item: AnalysisObservation) -> tuple[object, ...]:
    return (
        item.manifest_id,
        item.design_id,
        item.block_id,
        item.sample_index,
        item.realization_seed,
        item.execution_fingerprint_digest,
        item.modality,
        item.profile_id,
        item.location_index,
    )


def _location_source_key(item: AnalysisLocationStatus) -> tuple[object, ...]:
    return (
        item.manifest_id,
        item.design_id,
        item.block_id,
        item.sample_index,
        item.realization_seed,
        item.execution_fingerprint_digest,
        item.modality,
        item.profile_id,
        item.location_index,
    )


def _fingerprint_location_key(
    fingerprint: str,
    modality: str,
    profile_id: str,
    location_index: int,
) -> tuple[str, str, str, int]:
    return fingerprint, modality, profile_id, location_index


def _observation_result(item: AnalysisObservation) -> tuple[object, ...]:
    return (
        item.raw_rqd,
        item.fixed_jn,
        item.is_valid,
        item.exclusion_reason,
        item.zero_cross,
        item.support_length_m,
        item.support_area_m2,
        item.p32_by_joint_set,
    )


def _location_result(item: AnalysisLocationStatus) -> tuple[object, ...]:
    return item.status, item.reason


def _validate_revision(revision: CumulativeRawDatasetRevision) -> None:
    if not isinstance(revision, CumulativeRawDatasetRevision):
        raise TypeError("revision must be a CumulativeRawDatasetRevision")
    if (
        isinstance(revision.revision_index, bool)
        or not isinstance(revision.revision_index, int)
        or revision.revision_index <= 0
    ):
        raise ValueError("revision.revision_index must be positive")
    digest = revision.dataset_sha256
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("revision.dataset_sha256 must be lowercase SHA-256")
    if fingerprint_snapshot(revision.dataset_snapshot).sha256_hex != digest:
        raise ValueError("cumulative dataset snapshot does not match its SHA-256")


def _prepare_report(
    revision: CumulativeRawDatasetRevision,
    *,
    jr_values: tuple[float, ...] | None,
    ja_values: tuple[float, ...] | None,
) -> _PreparedReport:
    _validate_revision(revision)
    selected_jr = analysis.JR_VALUES if jr_values is None else jr_values
    selected_ja = analysis.JA_VALUES if ja_values is None else ja_values

    observation_groups: dict[
        tuple[str, str, str, int], list[AnalysisObservation]
    ] = {}
    status_groups: dict[
        tuple[str, str, str, int], list[AnalysisLocationStatus]
    ] = {}
    batch_fingerprints: dict[str, set[str]] = {
        manifest_id: set() for manifest_id in revision.manifest_ids
    }
    batch_observation_counts = {manifest_id: 0 for manifest_id in revision.manifest_ids}
    batch_location_counts = {manifest_id: 0 for manifest_id in revision.manifest_ids}
    fingerprint_manifests: dict[str, set[str]] = {}
    fixed_jn_by_fingerprint: dict[str, set[float]] = {}

    for item in revision.observations:
        key = _fingerprint_location_key(
            item.execution_fingerprint_digest,
            item.modality,
            item.profile_id,
            item.location_index,
        )
        observation_groups.setdefault(key, []).append(item)
        batch_observation_counts[item.manifest_id] = (
            batch_observation_counts.get(item.manifest_id, 0) + 1
        )
        batch_fingerprints.setdefault(item.manifest_id, set()).add(
            item.execution_fingerprint_digest
        )
        fingerprint_manifests.setdefault(item.execution_fingerprint_digest, set()).add(
            item.manifest_id
        )
        fixed_jn_by_fingerprint.setdefault(
            item.execution_fingerprint_digest, set()
        ).add(item.fixed_jn)

    for item in revision.location_states:
        key = _fingerprint_location_key(
            item.execution_fingerprint_digest,
            item.modality,
            item.profile_id,
            item.location_index,
        )
        status_groups.setdefault(key, []).append(item)
        batch_location_counts[item.manifest_id] = (
            batch_location_counts.get(item.manifest_id, 0) + 1
        )
        batch_fingerprints.setdefault(item.manifest_id, set()).add(
            item.execution_fingerprint_digest
        )
        fingerprint_manifests.setdefault(item.execution_fingerprint_digest, set()).add(
            item.manifest_id
        )

    conflict_types_by_key: dict[tuple[str, str, str, int], set[str]] = {}
    for key, items in observation_groups.items():
        if len({_observation_result(item) for item in items}) > 1:
            conflict_types_by_key.setdefault(key, set()).add("observation_values")
    for key, items in status_groups.items():
        if len({_location_result(item) for item in items}) > 1:
            conflict_types_by_key.setdefault(key, set()).add("location_status")

    conflicts: list[FingerprintConflict] = []
    for fingerprint, jn_values in fixed_jn_by_fingerprint.items():
        if len(jn_values) > 1:
            conflicts.append(FingerprintConflict(
                fingerprint,
                None,
                None,
                None,
                ("execution_metadata",),
                tuple(sorted(fingerprint_manifests[fingerprint])),
            ))
    for key, conflict_types in sorted(conflict_types_by_key.items()):
        fingerprint = key[0]
        source_manifest_ids = {
            item.manifest_id for item in observation_groups.get(key, ())
        } | {
            item.manifest_id for item in status_groups.get(key, ())
        }
        conflicts.append(FingerprintConflict(
            fingerprint,
            key[1],
            key[2],
            key[3],
            tuple(sorted(conflict_types)),
            tuple(sorted(source_manifest_ids)),
        ))

    conflicted_fingerprints = {
        item.execution_fingerprint_digest for item in conflicts
    }
    fingerprint_status = {
        fingerprint: (
            "conflict" if fingerprint in conflicted_fingerprints
            else "repeated" if len(manifests) > 1
            else "unique"
        )
        for fingerprint, manifests in fingerprint_manifests.items()
    }

    unique_observations: list[AnalysisObservation] = []
    observation_source_counts: dict[tuple[object, ...], int] = {}
    representative_observation_keys: set[tuple[object, ...]] = set()
    for key, items in observation_groups.items():
        ordered = sorted(items, key=_observation_source_key)
        for item in ordered:
            observation_source_counts[_observation_source_key(item)] = len(items)
        if key[0] in conflicted_fingerprints:
            continue
        selected = ordered[0]
        unique_observations.append(selected)
        representative_observation_keys.add(_observation_source_key(selected))

    unique_location_states: list[AnalysisLocationStatus] = []
    location_source_counts: dict[tuple[object, ...], int] = {}
    representative_location_keys: set[tuple[object, ...]] = set()
    for key, items in status_groups.items():
        ordered = sorted(items, key=_location_source_key)
        for item in ordered:
            location_source_counts[_location_source_key(item)] = len(items)
        if key[0] in conflicted_fingerprints:
            continue
        selected = ordered[0]
        unique_location_states.append(selected)
        representative_location_keys.add(_location_source_key(selected))

    unique_observations.sort(key=_observation_source_key)
    unique_location_states.sort(key=_location_source_key)
    result = analysis.analyze_reference_profiles(
        tuple(unique_observations),
        tuple(unique_location_states),
        jr_values=selected_jr,
        ja_values=selected_ja,
    )

    execution_fingerprint_counts: dict[tuple[object, ...], set[str]] = {}
    bin_execution_fingerprint_counts: dict[tuple[object, ...], set[str]] = {}
    for item in unique_observations:
        support = (
            item.support_length_m if item.modality == "BH" else item.support_area_m2
        )
        if not item.is_valid or support is None or support <= 0.0:
            continue
        for score in calculate_scenario_scores(
            item.raw_rqd,
            item.fixed_jn,
            zero_cross=item.zero_cross,
            jr_values=selected_jr,
            ja_values=selected_ja,
        ):
            profile_key = (
                item.modality, item.profile_id, item.fixed_jn,
                score.jr_value, score.ja_value,
            )
            execution_fingerprint_counts.setdefault(profile_key, set()).add(
                item.execution_fingerprint_digest
            )
            bin_key = (*profile_key, score.bin_id)
            bin_execution_fingerprint_counts.setdefault(bin_key, set()).add(
                item.execution_fingerprint_digest
            )

    return _PreparedReport(
        tuple(unique_observations),
        tuple(unique_location_states),
        result,
        tuple(sorted(
            conflicts,
            key=lambda item: (
                item.execution_fingerprint_digest,
                item.modality or "",
                item.profile_id or "",
                -1 if item.location_index is None else item.location_index,
            ),
        )),
        fingerprint_status,
        observation_source_counts,
        location_source_counts,
        frozenset(representative_observation_keys),
        frozenset(representative_location_keys),
        {key: frozenset(value) for key, value in batch_fingerprints.items()},
        batch_observation_counts,
        batch_location_counts,
        {key: len(value) for key, value in execution_fingerprint_counts.items()},
        {key: len(value) for key, value in bin_execution_fingerprint_counts.items()},
        tuple(selected_jr),
        tuple(selected_ja),
    )


def _file_rows(prepared: _PreparedReport) -> dict[str, int]:
    result = prepared.analysis_result
    return {
        "signature_observation_scenarios.csv": (
            len(prepared.observations) * len(prepared.jr_values) * len(prepared.ja_values)
        ),
        "source_observation_provenance.csv": sum(
            prepared.batch_observation_counts.values()
        ),
        "cumulative_profile_summaries.csv": len(result.scenario_summaries),
        "cumulative_bin_coverage.csv": sum(
            len(item.bin_support) for item in result.scenario_summaries
        ),
        "batch_signature_coverage.csv": len(prepared.batch_fingerprints),
        "fingerprint_conflicts.csv": len(prepared.conflicts),
        "location_status_sources.csv": sum(prepared.batch_location_counts.values()),
        "bh_face_distribution_contrasts.csv": len(result.distribution_contrasts),
        "bh_face_bin_contrasts.csv": sum(
            len(item.bin_fraction_differences)
            for item in result.distribution_contrasts
        ),
        "qprime_p32.csv": len(result.qprime_p32_points),
        "unavailable_profiles.csv": len(result.unavailable_profiles),
    }


def _execution_fingerprint_counts(
    revision: CumulativeRawDatasetRevision,
    prepared: _PreparedReport,
) -> tuple[int, int]:
    fingerprints = set(revision.independent_execution_fingerprints)
    fingerprints.update(prepared.fingerprint_status)
    conflicted = {
        item.execution_fingerprint_digest for item in prepared.conflicts
    }
    return len(fingerprints), len(fingerprints - conflicted)


def preflight_cumulative_coverage_report(
    revision: CumulativeRawDatasetRevision,
    *,
    jr_values: tuple[float, ...] | None = None,
    ja_values: tuple[float, ...] | None = None,
) -> CumulativeReportPreflight:
    """Calculate exact cumulative report row counts without imposing a fixed cap."""
    prepared = _prepare_report(
        revision,
        jr_values=jr_values,
        ja_values=ja_values,
    )
    counts = _file_rows(prepared)
    analysis_fingerprint = fingerprint_snapshot(
        analysis.build_cumulative_analysis_snapshot(
            revision.revision_index,
            revision.dataset_sha256,
            jr_values=prepared.jr_values,
            ja_values=prepared.ja_values,
        )
    )
    source_fingerprint_count, eligible_fingerprint_count = (
        _execution_fingerprint_counts(revision, prepared)
    )
    return CumulativeReportPreflight(
        revision.revision_index,
        revision.dataset_sha256,
        analysis_fingerprint.sha256_hex,
        tuple(
            CumulativeReportFile(name, counts[name])
            for name in _CSV_FILE_ORDER
        ),
        sum(prepared.batch_observation_counts.values()),
        len(prepared.observations),
        source_fingerprint_count,
        eligible_fingerprint_count,
        len({
            conflict.execution_fingerprint_digest
            for conflict in prepared.conflicts
        }),
    )


def _support(item: AnalysisObservation) -> tuple[float | None, str]:
    if item.modality == "BH":
        return item.support_length_m, "m"
    return item.support_area_m2, "m2"


def _source_observation_rows(
    revision: CumulativeRawDatasetRevision,
    prepared: _PreparedReport,
) -> Iterator[tuple[object, ...]]:
    for item in sorted(revision.observations, key=_observation_source_key):
        support, unit = _support(item)
        yield (
            item.manifest_id,
            item.design_id,
            item.block_id,
            item.sample_index,
            item.realization_seed,
            item.execution_fingerprint_digest,
            item.modality,
            item.profile_id,
            item.location_index,
            item.raw_rqd,
            item.fixed_jn,
            item.is_valid,
            item.exclusion_reason,
            item.zero_cross,
            support,
            unit,
            prepared.fingerprint_status[item.execution_fingerprint_digest],
            prepared.observation_source_counts[_observation_source_key(item)],
            _observation_source_key(item) in prepared.representative_observation_keys,
        )


def _signature_scenario_rows(
    observations: tuple[AnalysisObservation, ...],
    prepared: _PreparedReport,
) -> Iterator[tuple[object, ...]]:
    for item in observations:
        support, unit = _support(item)
        for score in calculate_scenario_scores(
            item.raw_rqd,
            item.fixed_jn,
            zero_cross=item.zero_cross,
            jr_values=prepared.jr_values,
            ja_values=prepared.ja_values,
        ):
            yield (
                item.manifest_id,
                item.design_id,
                item.block_id,
                item.sample_index,
                item.realization_seed,
                item.execution_fingerprint_digest,
                item.modality,
                item.profile_id,
                item.location_index,
                score.raw_rqd,
                score.calculation_rqd,
                score.fixed_jn,
                score.jr_value,
                score.ja_value,
                score.qprime,
                score.bin_id,
                item.is_valid,
                item.exclusion_reason,
                score.zero_cross,
                support,
                unit,
            )


def _summary_rows(
    summaries: tuple[ScenarioProfileSummary, ...],
    prepared: _PreparedReport,
) -> Iterator[tuple[object, ...]]:
    for item in summaries:
        key = (
            item.modality,
            item.profile_id,
            item.fixed_jn,
            item.jr_value,
            item.ja_value,
        )
        yield (
            item.modality,
            item.profile_id,
            item.fixed_jn,
            item.jr_value,
            item.ja_value,
            item.observation_count,
            item.valid_support_observation_count,
            item.signature_count,
            item.realization_count,
            prepared.execution_fingerprint_counts.get(key, 0),
            item.support_unit,
            item.total_support,
            item.weighted_median_qprime,
            item.minimum_qprime,
            item.maximum_qprime,
        )


def _bin_coverage_rows(prepared: _PreparedReport) -> Iterator[tuple[object, ...]]:
    for item in prepared.analysis_result.scenario_summaries:
        for bin_item in item.bin_support:
            key = (
                item.modality,
                item.profile_id,
                item.fixed_jn,
                item.jr_value,
                item.ja_value,
                bin_item.bin_id,
            )
            yield (
                item.modality,
                item.profile_id,
                item.fixed_jn,
                item.jr_value,
                item.ja_value,
                bin_item.bin_id,
                item.support_unit,
                bin_item.support,
                item.total_support,
                bin_item.support_fraction,
                bin_item.support > 0.0,
                prepared.bin_execution_fingerprint_counts.get(key, 0),
            )


def _batch_rows(prepared: _PreparedReport) -> Iterator[tuple[object, ...]]:
    fingerprint_batch_counts: dict[str, int] = {}
    for fingerprints in prepared.batch_fingerprints.values():
        for fingerprint in fingerprints:
            fingerprint_batch_counts[fingerprint] = (
                fingerprint_batch_counts.get(fingerprint, 0) + 1
            )
    for manifest_id in sorted(prepared.batch_fingerprints):
        fingerprints = prepared.batch_fingerprints[manifest_id]
        exclusive = sum(fingerprint_batch_counts[item] == 1 for item in fingerprints)
        shared = len(fingerprints) - exclusive
        conflicted = sum(
            prepared.fingerprint_status.get(item) == "conflict"
            for item in fingerprints
        )
        yield (
            manifest_id,
            prepared.batch_observation_counts[manifest_id],
            prepared.batch_location_counts[manifest_id],
            len(fingerprints),
            exclusive,
            shared,
            conflicted,
        )


def _conflict_rows(
    conflicts: tuple[FingerprintConflict, ...],
) -> Iterator[tuple[object, ...]]:
    for item in conflicts:
        yield (
            item.execution_fingerprint_digest,
            item.modality,
            item.profile_id,
            item.location_index,
            "|".join(item.conflict_types),
            "|".join(item.source_manifest_ids),
        )


def _location_source_rows(
    revision: CumulativeRawDatasetRevision,
    prepared: _PreparedReport,
) -> Iterator[tuple[object, ...]]:
    for item in sorted(revision.location_states, key=_location_source_key):
        yield (
            item.manifest_id,
            item.design_id,
            item.block_id,
            item.sample_index,
            item.realization_seed,
            item.execution_fingerprint_digest,
            item.modality,
            item.profile_id,
            item.location_index,
            item.status,
            item.reason,
            prepared.fingerprint_status[item.execution_fingerprint_digest],
            prepared.location_source_counts[_location_source_key(item)],
            _location_source_key(item) in prepared.representative_location_keys,
        )


def _distribution_rows(
    result: ReferenceProfileAnalysis,
) -> Iterator[tuple[object, ...]]:
    for item in result.distribution_contrasts:
        yield (
            item.bh_profile_id,
            item.face_profile_id,
            item.fixed_jn,
            item.jr_value,
            item.ja_value,
            item.comparability_status,
            item.bh_support_m,
            item.face_support_m2,
            item.bh_weighted_median_qprime,
            item.face_weighted_median_qprime,
            item.face_minus_bh_weighted_median_qprime,
        )


def _distribution_bin_rows(
    result: ReferenceProfileAnalysis,
) -> Iterator[tuple[object, ...]]:
    summaries = {
        (
            item.modality,
            item.profile_id,
            item.fixed_jn,
            item.jr_value,
            item.ja_value,
        ): item
        for item in result.scenario_summaries
    }
    for contrast in result.distribution_contrasts:
        bh = summaries[(
            "BH",
            contrast.bh_profile_id,
            contrast.fixed_jn,
            contrast.jr_value,
            contrast.ja_value,
        )]
        face = summaries[(
            "face",
            contrast.face_profile_id,
            contrast.fixed_jn,
            contrast.jr_value,
            contrast.ja_value,
        )]
        bh_fractions = {item.bin_id: item.support_fraction for item in bh.bin_support}
        face_fractions = {
            item.bin_id: item.support_fraction for item in face.bin_support
        }
        for difference in contrast.bin_fraction_differences:
            yield (
                contrast.bh_profile_id,
                contrast.face_profile_id,
                contrast.fixed_jn,
                contrast.jr_value,
                contrast.ja_value,
                difference.bin_id,
                contrast.comparability_status,
                bh_fractions[difference.bin_id],
                face_fractions[difference.bin_id],
                difference.face_minus_bh_support_fraction,
            )


def _p32_rows(result: ReferenceProfileAnalysis) -> Iterator[tuple[object, ...]]:
    for item in result.qprime_p32_points:
        yield (
            item.manifest_id,
            item.design_id,
            item.block_id,
            item.sample_index,
            item.realization_seed,
            item.profile_id,
            item.location_index,
            item.joint_set_id,
            item.p32_m2_per_m3,
            item.jr_value,
            item.ja_value,
            item.qprime_bh,
            item.support_length_m,
        )


def _unavailable_rows(result: ReferenceProfileAnalysis) -> Iterator[tuple[object, ...]]:
    for item in sorted(result.unavailable_profiles, key=lambda value: value.profile_id):
        yield item.profile_id, item.reason


def _rows_by_file(
    revision: CumulativeRawDatasetRevision,
    prepared: _PreparedReport,
) -> dict[str, Iterable[tuple[object, ...]]]:
    result = prepared.analysis_result
    return {
        "signature_observation_scenarios.csv": _signature_scenario_rows(
            prepared.observations,
            prepared,
        ),
        "source_observation_provenance.csv": _source_observation_rows(
            revision,
            prepared,
        ),
        "cumulative_profile_summaries.csv": _summary_rows(
            result.scenario_summaries,
            prepared,
        ),
        "cumulative_bin_coverage.csv": _bin_coverage_rows(prepared),
        "batch_signature_coverage.csv": _batch_rows(prepared),
        "fingerprint_conflicts.csv": _conflict_rows(prepared.conflicts),
        "location_status_sources.csv": _location_source_rows(revision, prepared),
        "bh_face_distribution_contrasts.csv": _distribution_rows(result),
        "bh_face_bin_contrasts.csv": _distribution_bin_rows(result),
        "qprime_p32.csv": _p32_rows(result),
        "unavailable_profiles.csv": _unavailable_rows(result),
    }


def _summary_payload(
    preflight: CumulativeReportPreflight,
    prepared: _PreparedReport,
) -> dict[str, JsonValue]:
    return {
        "report_schema_version": CUMULATIVE_REPORT_SCHEMA_VERSION,
        "dataset_revision_index": preflight.dataset_revision_index,
        "dataset_sha256": preflight.dataset_sha256,
        "analysis_fingerprint_sha256": preflight.analysis_fingerprint_sha256,
        "duplicate_policy": (
            "preserve all source rows; identical fingerprint/location results count once; "
            "conflicted fingerprints are flagged and excluded from profile/bin aggregates"
        ),
        "row_policy": "exact preflight before writing; stream rows; no fixed row cap",
        "source_observation_count": preflight.source_observation_count,
        "unique_observation_count": preflight.unique_observation_count,
        "source_execution_fingerprint_count": (
            preflight.source_execution_fingerprint_count
        ),
        "eligible_execution_fingerprint_count": (
            preflight.eligible_execution_fingerprint_count
        ),
        "conflicted_fingerprint_count": preflight.conflicted_fingerprint_count,
        "files": [
            {"file_name": item.file_name, "row_count": item.expected_rows}
            for item in preflight.files
        ],
        "unavailable_profiles": [
            {"profile_id": item.profile_id, "reason": item.reason}
            for item in sorted(
                prepared.analysis_result.unavailable_profiles,
                key=lambda value: value.profile_id,
            )
        ],
    }


def export_cumulative_coverage_report(
    output_directory: Path,
    revision: CumulativeRawDatasetRevision,
    *,
    jr_values: tuple[float, ...] | None = None,
    ja_values: tuple[float, ...] | None = None,
) -> CumulativeReportExportResult:
    """Preflight exact row counts, then stream a cumulative coverage report."""
    if not isinstance(output_directory, Path):
        raise TypeError("output_directory must be a pathlib.Path")
    prepared = _prepare_report(
        revision,
        jr_values=jr_values,
        ja_values=ja_values,
    )
    counts = _file_rows(prepared)
    analysis_fingerprint = fingerprint_snapshot(
        analysis.build_cumulative_analysis_snapshot(
            revision.revision_index,
            revision.dataset_sha256,
            jr_values=prepared.jr_values,
            ja_values=prepared.ja_values,
        )
    )
    preflight = CumulativeReportPreflight(
        revision.revision_index,
        revision.dataset_sha256,
        analysis_fingerprint.sha256_hex,
        tuple(
            CumulativeReportFile(name, counts[name])
            for name in _CSV_FILE_ORDER
        ),
        sum(prepared.batch_observation_counts.values()),
        len(prepared.observations),
        *_execution_fingerprint_counts(revision, prepared),
        len({
            conflict.execution_fingerprint_digest
            for conflict in prepared.conflicts
        }),
    )
    rows_by_file = _rows_by_file(revision, prepared)
    output_directory.mkdir(parents=True, exist_ok=True)
    for item in preflight.files:
        with (output_directory / item.file_name).open(
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(CUMULATIVE_CSV_HEADERS[item.file_name])
            written_rows = 0
            for row in rows_by_file[item.file_name]:
                writer.writerow(tuple(_format_field(value) for value in row))
                written_rows += 1
            if written_rows != item.expected_rows:
                raise RuntimeError(
                    f"{item.file_name} wrote {written_rows} rows; "
                    f"preflight expected {item.expected_rows}"
                )

    summary_bytes = fingerprint_snapshot(
        _summary_payload(preflight, prepared)
    ).canonical_bytes
    with (output_directory / "report_summary.json").open("wb") as stream:
        stream.write(summary_bytes)
    return CumulativeReportExportResult(
        output_directory,
        preflight,
        sha256(summary_bytes).hexdigest(),
    )
