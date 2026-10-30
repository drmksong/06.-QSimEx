"""Offline scenario scoring and fingerprints from immutable raw observations."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np

from .config import JA_VALUES, JN_VALUES, JR_VALUES
from .fingerprint import JsonValue, SnapshotFingerprint, fingerprint_snapshot

RAW_DATASET_SCHEMA_VERSION = 1
ANALYSIS_SCHEMA_VERSION = 1
ANALYSIS_IMPLEMENTATION_VERSION = "qsimex-reference-profile-analysis-v2"
CALCULATION_RQD_FLOOR = 10.0
BIN_CATALOG_ID = "primary_profile_10bin_v1"
HIGH_BIN_ID = "qprime_gt_400"
OVERFLOW_BIN_ID = HIGH_BIN_ID
BIN_EDGES = (0.0, *(float(edge) for edge in np.geomspace(0.1, 400.0, 11)[1:]))
ZERO_CROSS_CONVENTION = "raw_zero_cross_flag_preserved_without_score_adjustment"
Modality = Literal["BH", "face"]


@dataclass(frozen=True)
class ScenarioScore:
    raw_rqd: float
    calculation_rqd: float
    fixed_jn: float
    jr_value: float
    ja_value: float
    qprime: float
    bin_id: str
    zero_cross: bool


@dataclass(frozen=True)
class AnalysisObservation:
    """One selected successful raw observation joined to its frozen DFN job."""

    manifest_id: str
    design_id: str
    block_id: str
    sample_index: int
    realization_seed: int
    execution_fingerprint_digest: str
    modality: Modality
    profile_id: str
    location_index: int
    raw_rqd: float
    fixed_jn: float
    is_valid: bool
    exclusion_reason: str | None
    zero_cross: bool
    support_length_m: float | None
    support_area_m2: float | None
    p32_by_joint_set: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class AnalysisLocationStatus:
    manifest_id: str
    design_id: str
    block_id: str
    sample_index: int
    realization_seed: int
    execution_fingerprint_digest: str
    modality: Modality
    profile_id: str
    location_index: int
    status: Literal["planned", "observed", "unavailable", "missing"]
    reason: str | None


@dataclass(frozen=True)
class BinSupport:
    bin_id: str
    support: float
    support_fraction: float


@dataclass(frozen=True)
class ScenarioProfileSummary:
    modality: Modality
    profile_id: str
    fixed_jn: float
    jr_value: float
    ja_value: float
    observation_count: int
    valid_support_observation_count: int
    signature_count: int
    realization_count: int
    support_unit: Literal["m", "m2"]
    total_support: float
    weighted_median_qprime: float | None
    minimum_qprime: float | None
    maximum_qprime: float | None
    bin_support: tuple[BinSupport, ...]


@dataclass(frozen=True)
class QprimeP32Point:
    manifest_id: str
    design_id: str
    block_id: str
    sample_index: int
    realization_seed: int
    profile_id: str
    location_index: int
    joint_set_id: str
    p32_m2_per_m3: float
    jr_value: float
    ja_value: float
    qprime_bh: float
    support_length_m: float


@dataclass(frozen=True)
class LocationStatusSummary:
    modality: Literal["BH", "face"]
    profile_id: str
    planned_count: int
    observed_count: int
    unavailable_count: int
    missing_count: int
    invalid_observation_count: int
    zero_support_observation_count: int


@dataclass(frozen=True)
class LocationStatusReasonCount:
    modality: Modality
    profile_id: str
    status: Literal["unavailable", "missing"]
    reason: str
    count: int


@dataclass(frozen=True)
class BinFractionDifference:
    bin_id: str
    face_minus_bh_support_fraction: float | None


@dataclass(frozen=True)
class ProfileDistributionContrast:
    """Exploratory non-paired contrast; BH and face supports stay separate."""

    bh_profile_id: str
    face_profile_id: str
    fixed_jn: float
    jr_value: float
    ja_value: float
    comparability_status: Literal["comparable", "no_valid_positive_support"]
    bh_support_m: float
    face_support_m2: float
    bh_weighted_median_qprime: float | None
    face_weighted_median_qprime: float | None
    face_minus_bh_weighted_median_qprime: float | None
    bin_fraction_differences: tuple[BinFractionDifference, ...]


@dataclass(frozen=True)
class UnavailableProfile:
    profile_id: str
    reason: str


@dataclass(frozen=True)
class ReferenceProfileAnalysis:
    scenario_summaries: tuple[ScenarioProfileSummary, ...]
    distribution_contrasts: tuple[ProfileDistributionContrast, ...]
    qprime_p32_points: tuple[QprimeP32Point, ...]
    location_status_summaries: tuple[LocationStatusSummary, ...]
    location_status_reason_counts: tuple[LocationStatusReasonCount, ...]
    source_observation_count: int
    scenario_evaluation_count: int
    retry_count_available: bool
    unavailable_profiles: tuple[UnavailableProfile, ...]


def assign_qprime_bin(qprime: float) -> str:
    """Assign a positive Q′ using the approved (lower, upper] catalog."""
    if isinstance(qprime, bool) or not isinstance(qprime, (int, float)):
        raise TypeError("qprime must be a number")
    if not isfinite(qprime) or qprime <= 0.0:
        raise ValueError("qprime must be finite and positive")
    if qprime > BIN_EDGES[-1]:
        return OVERFLOW_BIN_ID
    index = bisect_left(BIN_EDGES, qprime) - 1
    if not 0 <= index < len(BIN_EDGES) - 1:
        raise ValueError("qprime is outside the primary bin catalog")
    return str(index + 1)


def _selected_scenario_values(
    values: tuple[float, ...] | None,
    catalog: tuple[float, ...],
    name: str,
) -> tuple[float, ...]:
    if values is None:
        return catalog
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{name} must be a non-empty tuple")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not isfinite(value) or value not in catalog
        for value in values
    ):
        raise ValueError(f"{name} values must be selected from {catalog}")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must not contain duplicates")
    selected = set(float(value) for value in values)
    return tuple(value for value in catalog if value in selected)


def calculate_scenario_scores(
    raw_rqd: float,
    fixed_jn: float,
    *,
    zero_cross: bool = False,
    jr_values: tuple[float, ...] | None = None,
    ja_values: tuple[float, ...] | None = None,
) -> tuple[ScenarioScore, ...]:
    """Apply selected approved Jr/Ja values without changing the raw observation."""
    if isinstance(raw_rqd, bool) or not isinstance(raw_rqd, (int, float)):
        raise TypeError("raw_rqd must be a number")
    if not isfinite(raw_rqd) or not 0.0 <= raw_rqd <= 100.0:
        raise ValueError("raw_rqd must be finite and between 0 and 100")
    if isinstance(fixed_jn, bool) or not isinstance(fixed_jn, (int, float)):
        raise TypeError("fixed_jn must be a number")
    if not isfinite(fixed_jn) or fixed_jn not in JN_VALUES:
        raise ValueError(f"fixed_jn must be one of {JN_VALUES}")
    if not isinstance(zero_cross, bool):
        raise TypeError("zero_cross must be a bool")

    selected_jr_values = _selected_scenario_values(jr_values, JR_VALUES, "jr_values")
    selected_ja_values = _selected_scenario_values(ja_values, JA_VALUES, "ja_values")
    calculation_rqd = max(float(raw_rqd), CALCULATION_RQD_FLOOR)
    scores_list: list[ScenarioScore] = []
    for jr_value in selected_jr_values:
        for ja_value in selected_ja_values:
            qprime = (calculation_rqd * jr_value) / (fixed_jn * ja_value)
            scores_list.append(
                ScenarioScore(
                    raw_rqd=float(raw_rqd),
                    calculation_rqd=calculation_rqd,
                    fixed_jn=float(fixed_jn),
                    jr_value=jr_value,
                    ja_value=ja_value,
                    qprime=qprime,
                    bin_id=assign_qprime_bin(qprime),
                    zero_cross=zero_cross,
                )
            )
    scores = tuple(scores_list)
    if len(scores) != len(selected_jr_values) * len(selected_ja_values):
        raise RuntimeError("scenario scoring did not produce the complete grid")
    return scores


def _require_nonempty_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _validate_analysis_observation(observation: AnalysisObservation) -> None:
    if not isinstance(observation, AnalysisObservation):
        raise TypeError("observations must contain AnalysisObservation values")
    for name in ("manifest_id", "design_id", "block_id", "profile_id"):
        _require_nonempty_text(getattr(observation, name), name)
    if not isinstance(observation.execution_fingerprint_digest, str):
        raise TypeError("execution_fingerprint_digest must be text")
    if observation.modality not in ("BH", "face"):
        raise ValueError("observation modality must be BH or face")
    for name in ("sample_index", "realization_seed", "location_index"):
        value = getattr(observation, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
    if observation.sample_index < 0 or observation.location_index < 0:
        raise ValueError("sample_index and location_index must be non-negative")
    digest = observation.execution_fingerprint_digest
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("execution_fingerprint_digest must be lowercase SHA-256")
    if not isinstance(observation.is_valid, bool):
        raise TypeError("is_valid must be a bool")
    if observation.is_valid and observation.exclusion_reason is not None:
        raise ValueError("valid observations must not have an exclusion_reason")
    if not observation.is_valid:
        if not isinstance(observation.exclusion_reason, str):
            raise TypeError("invalid observations require an exclusion_reason")
        _require_nonempty_text(observation.exclusion_reason, "exclusion_reason")
    if not isinstance(observation.zero_cross, bool):
        raise TypeError("zero_cross must be a bool")
    calculate_scenario_scores(
        observation.raw_rqd,
        observation.fixed_jn,
        zero_cross=observation.zero_cross,
    )
    if observation.modality == "BH":
        support = observation.support_length_m
        if observation.support_area_m2 is not None:
            raise ValueError("BH observations must not contain face area support")
    else:
        support = observation.support_area_m2
        if observation.support_length_m is not None:
            raise ValueError("face observations must not contain BH length support")
    if (
        isinstance(support, bool)
        or not isinstance(support, (int, float))
        or not isfinite(support)
        or support < 0.0
    ):
        raise ValueError("observation support must be finite and non-negative")
    if not isinstance(observation.p32_by_joint_set, tuple):
        raise TypeError("p32_by_joint_set must be a tuple")
    if observation.modality == "face" and observation.p32_by_joint_set:
        raise ValueError("P32 correspondence is defined only for BH observations")
    joint_set_ids: set[str] = set()
    for joint_set_id, p32 in observation.p32_by_joint_set:
        _require_nonempty_text(joint_set_id, "joint_set_id")
        if joint_set_id in joint_set_ids:
            raise ValueError("p32_by_joint_set contains duplicate joint_set_id values")
        joint_set_ids.add(joint_set_id)
        if (
            isinstance(p32, bool)
            or not isinstance(p32, (int, float))
            or not isfinite(p32)
            or p32 <= 0.0
        ):
            raise ValueError("P32 values must be finite and positive")


def _validate_location_status(status: AnalysisLocationStatus) -> None:
    if not isinstance(status, AnalysisLocationStatus):
        raise TypeError("location_states must contain AnalysisLocationStatus values")
    for name in ("manifest_id", "design_id", "block_id", "profile_id"):
        _require_nonempty_text(getattr(status, name), name)
    if not isinstance(status.execution_fingerprint_digest, str):
        raise TypeError("execution_fingerprint_digest must be text")
    digest = status.execution_fingerprint_digest
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("execution_fingerprint_digest must be lowercase SHA-256")
    for name in ("sample_index", "realization_seed", "location_index"):
        value = getattr(status, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
    if status.sample_index < 0 or status.location_index < 0:
        raise ValueError("sample_index and location_index must be non-negative")
    if status.modality not in ("BH", "face"):
        raise ValueError("location status modality must be BH or face")
    if status.status not in ("planned", "observed", "unavailable", "missing"):
        raise ValueError("location status is invalid")
    if status.status in ("unavailable", "missing"):
        if not isinstance(status.reason, str):
            raise TypeError("unavailable and missing locations require a reason")
        _require_nonempty_text(status.reason, "reason")
    elif status.reason is not None:
        raise ValueError("planned and observed location statuses must not have a reason")


def _weighted_median(values: list[tuple[float, float]]) -> float | None:
    """Return the lower inverse-support-CDF median (first value at 50% support)."""
    if not values:
        return None
    ordered = sorted(values)
    half_support = sum(support for _, support in ordered) / 2.0
    accumulated = 0.0
    for qprime, support in ordered:
        accumulated += support
        if accumulated >= half_support:
            return qprime
    raise RuntimeError("weighted median could not be resolved")


def _distribution_contrasts(
    summaries: tuple[ScenarioProfileSummary, ...],
) -> tuple[ProfileDistributionContrast, ...]:
    by_modality: dict[
        tuple[str, float, float, float], list[ScenarioProfileSummary]
    ] = {}
    for summary in summaries:
        key = (
            summary.modality, summary.fixed_jn,
            summary.jr_value, summary.ja_value,
        )
        by_modality.setdefault(key, []).append(summary)

    contrasts: list[ProfileDistributionContrast] = []
    scenario_keys = sorted({
        (summary.fixed_jn, summary.jr_value, summary.ja_value)
        for summary in summaries
    })
    for fixed_jn, jr_value, ja_value in scenario_keys:
        bh_summaries = by_modality.get(("BH", fixed_jn, jr_value, ja_value), [])
        face_summaries = by_modality.get(("face", fixed_jn, jr_value, ja_value), [])
        for bh in sorted(bh_summaries, key=lambda item: item.profile_id):
            for face in sorted(face_summaries, key=lambda item: item.profile_id):
                bh_bin_fractions = {
                    item.bin_id: item.support_fraction for item in bh.bin_support
                }
                face_bin_fractions = {
                    item.bin_id: item.support_fraction for item in face.bin_support
                }
                has_bh_support = bh.total_support > 0.0
                has_face_support = face.total_support > 0.0
                median_delta = (
                    face.weighted_median_qprime - bh.weighted_median_qprime
                    if (
                        bh.weighted_median_qprime is not None
                        and face.weighted_median_qprime is not None
                    )
                    else None
                )
                contrasts.append(ProfileDistributionContrast(
                    bh_profile_id=bh.profile_id,
                    face_profile_id=face.profile_id,
                    fixed_jn=fixed_jn,
                    jr_value=jr_value,
                    ja_value=ja_value,
                    comparability_status=(
                        "comparable" if has_bh_support and has_face_support
                        else "no_valid_positive_support"
                    ),
                    bh_support_m=bh.total_support,
                    face_support_m2=face.total_support,
                    bh_weighted_median_qprime=bh.weighted_median_qprime,
                    face_weighted_median_qprime=face.weighted_median_qprime,
                    face_minus_bh_weighted_median_qprime=median_delta,
                    bin_fraction_differences=tuple(
                        BinFractionDifference(
                            bin_id,
                            (
                                face_bin_fractions[bin_id] - bh_bin_fractions[bin_id]
                                if has_bh_support and has_face_support else None
                            ),
                        )
                        for bin_id in (*(
                            str(index) for index in range(1, len(BIN_EDGES))
                        ), OVERFLOW_BIN_ID)
                    ),
                ))
    return tuple(contrasts)


def analyze_reference_profiles(
    observations: tuple[AnalysisObservation, ...],
    location_states: tuple[AnalysisLocationStatus, ...],
    *,
    jr_values: tuple[float, ...] | None = None,
    ja_values: tuple[float, ...] | None = None,
) -> ReferenceProfileAnalysis:
    """Summarize approved profiles without combining incompatible support units.

    Inputs must contain one selected successful attempt per observation location.
    Retry history is deliberately not inferred from raw observations.
    """
    if not isinstance(observations, tuple):
        raise TypeError("observations must be a tuple")
    if not isinstance(location_states, tuple):
        raise TypeError("location_states must be a tuple")
    for observation in observations:
        _validate_analysis_observation(observation)
    for status in location_states:
        _validate_location_status(status)
    selected_jr_values = _selected_scenario_values(jr_values, JR_VALUES, "jr_values")
    selected_ja_values = _selected_scenario_values(ja_values, JA_VALUES, "ja_values")

    observation_keys = [
        (
            item.manifest_id, item.design_id, item.block_id, item.sample_index,
            item.realization_seed, item.execution_fingerprint_digest,
            item.modality, item.profile_id, item.location_index,
        )
        for item in observations
    ]
    if len(observation_keys) != len(set(observation_keys)):
        raise ValueError("observations contain duplicate selected location records")
    status_keys = [
        (
            item.manifest_id, item.design_id, item.block_id, item.sample_index,
            item.realization_seed, item.execution_fingerprint_digest,
            item.modality, item.profile_id, item.location_index,
        )
        for item in location_states
    ]
    if len(status_keys) != len(set(status_keys)):
        raise ValueError("location_states contain duplicate location records")
    observed_keys = {
        key for key, item in zip(status_keys, location_states)
        if item.status == "observed"
    }
    if observed_keys != set(observation_keys):
        raise ValueError("observed location states must match raw observations exactly")
    job_jn_values: dict[tuple[str, str, str, int, int, str], float] = {}
    job_p32_values: dict[
        tuple[str, str, str, int, int, str], tuple[tuple[str, float], ...]
    ] = {}
    for item in observations:
        job_key = (
            item.manifest_id, item.design_id, item.block_id, item.sample_index,
            item.realization_seed, item.execution_fingerprint_digest,
        )
        if job_key in job_jn_values and job_jn_values[job_key] != item.fixed_jn:
            raise ValueError("observations in one execution job must share fixed_jn")
        job_jn_values[job_key] = item.fixed_jn
        if item.modality == "BH":
            p32_values = tuple(sorted(item.p32_by_joint_set))
            if (
                job_key in job_p32_values
                and job_p32_values[job_key] != p32_values
            ):
                raise ValueError(
                    "BH observations in one execution job must share the same P32 values"
                )
            job_p32_values[job_key] = p32_values

    grouped: dict[
        tuple[Modality, str, float, float, float],
        list[tuple[AnalysisObservation, ScenarioScore, float]],
    ] = {}
    p32_points: list[QprimeP32Point] = []
    scenario_evaluation_count = 0
    for observation in observations:
        support = (
            observation.support_length_m
            if observation.modality == "BH"
            else observation.support_area_m2
        )
        if support is None:
            raise RuntimeError("validated observation is missing its support")
        scores = calculate_scenario_scores(
            observation.raw_rqd,
            observation.fixed_jn,
            zero_cross=observation.zero_cross,
            jr_values=selected_jr_values,
            ja_values=selected_ja_values,
        )
        scenario_evaluation_count += len(scores)
        for score in scores:
            key = (
                observation.modality, observation.profile_id,
                observation.fixed_jn, score.jr_value, score.ja_value,
            )
            grouped.setdefault(key, []).append((observation, score, float(support)))
            if (
                observation.modality == "BH"
                and observation.is_valid
                and support > 0.0
            ):
                for joint_set_id, p32 in observation.p32_by_joint_set:
                    p32_points.append(QprimeP32Point(
                        observation.manifest_id,
                        observation.design_id,
                        observation.block_id,
                        observation.sample_index,
                        observation.realization_seed,
                        observation.profile_id,
                        observation.location_index,
                        joint_set_id,
                        float(p32),
                        score.jr_value,
                        score.ja_value,
                        score.qprime,
                        float(support),
                    ))

    primary_bin_ids = tuple(str(index) for index in range(1, len(BIN_EDGES)))
    bin_ids = (*primary_bin_ids, OVERFLOW_BIN_ID)
    summaries: list[ScenarioProfileSummary] = []
    for key in sorted(grouped):
        modality, profile_id, fixed_jn, jr_value, ja_value = key
        rows = grouped[key]
        supported = [
            (observation, score, support)
            for observation, score, support in rows
            if observation.is_valid and support > 0.0
        ]
        total_support = sum(support for _, _, support in supported)
        qprime_support = [(score.qprime, support) for _, score, support in supported]
        bin_support_values = {
            bin_id: sum(
                support
                for _, score, support in supported
                if score.bin_id == bin_id
            )
            for bin_id in bin_ids
        }
        signature_keys = {
            (item.manifest_id, item.design_id, item.block_id, item.sample_index)
            for item, _, _ in supported
        }
        realization_keys = {
            (
                item.manifest_id, item.design_id, item.block_id,
                item.sample_index, item.realization_seed,
            )
            for item, _, _ in supported
        }
        summaries.append(ScenarioProfileSummary(
            modality=modality,
            profile_id=profile_id,
            fixed_jn=fixed_jn,
            jr_value=jr_value,
            ja_value=ja_value,
            observation_count=len(rows),
            valid_support_observation_count=len(supported),
            signature_count=len(signature_keys),
            realization_count=len(realization_keys),
            support_unit="m" if modality == "BH" else "m2",
            total_support=total_support,
            weighted_median_qprime=_weighted_median(qprime_support),
            minimum_qprime=min((qprime for qprime, _ in qprime_support), default=None),
            maximum_qprime=max((qprime for qprime, _ in qprime_support), default=None),
            bin_support=tuple(
                BinSupport(
                    bin_id=bin_id,
                    support=bin_support_values[bin_id],
                    support_fraction=(
                        bin_support_values[bin_id] / total_support
                        if total_support > 0.0 else 0.0
                    ),
                )
                for bin_id in bin_ids
            ),
        ))

    observation_by_key = {
        key: item for key, item in zip(observation_keys, observations)
    }
    status_groups: dict[tuple[Modality, str], list[AnalysisLocationStatus]] = {}
    for item in location_states:
        status_groups.setdefault((item.modality, item.profile_id), []).append(item)
    location_status_summaries: list[LocationStatusSummary] = []
    reason_counts: dict[
        tuple[Modality, str, Literal["unavailable", "missing"], str], int
    ] = {}
    for item in location_states:
        if item.status in ("unavailable", "missing"):
            if item.reason is None:
                raise RuntimeError("validated unavailable location lost its reason")
            reason_key = (item.modality, item.profile_id, item.status, item.reason)
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1
    for (modality, profile_id), statuses in sorted(status_groups.items()):
        observed_items: list[AnalysisObservation] = []
        for item in statuses:
            if item.status == "observed":
                key = (
                    item.manifest_id, item.design_id, item.block_id,
                    item.sample_index, item.realization_seed,
                    item.execution_fingerprint_digest, item.modality,
                    item.profile_id, item.location_index,
                )
                observed_items.append(observation_by_key[key])
        zero_support_count = sum(
            (
                item.support_length_m if modality == "BH"
                else item.support_area_m2
            ) == 0.0
            for item in observed_items
        )
        location_status_summaries.append(LocationStatusSummary(
            modality=modality,
            profile_id=profile_id,
            planned_count=sum(item.status == "planned" for item in statuses),
            observed_count=sum(item.status == "observed" for item in statuses),
            unavailable_count=sum(item.status == "unavailable" for item in statuses),
            missing_count=sum(item.status == "missing" for item in statuses),
            invalid_observation_count=sum(
                not item.is_valid for item in observed_items
            ),
            zero_support_observation_count=zero_support_count,
        ))
    location_status_reason_counts = tuple(
        LocationStatusReasonCount(
            modality=modality,
            profile_id=profile_id,
            status=status,
            reason=reason,
            count=count,
        )
        for (modality, profile_id, status, reason), count in sorted(reason_counts.items())
    )

    scenario_summaries = tuple(summaries)
    unavailable_profiles = [
        UnavailableProfile(
            "detection_miss_ratio",
            "Deferred pending an approved numerator, denominator, and comparison population.",
        ),
        UnavailableProfile(
            "face_areal_density",
            "Raw face observations store scanline evidence, not the total face-joint count.",
        ),
        UnavailableProfile(
            "tunnel_axis_intersection_rate",
            "Tunnel-axis intersections are not measured or stored in the current evidence.",
        ),
        UnavailableProfile(
            "retry_count",
            "Retry history is outside the raw observation input and must be reported separately.",
        ),
    ]
    if not p32_points:
        unavailable_profiles.append(UnavailableProfile(
            "qprime_bh_p32",
            "No valid positive-support BH observation had P32 values joined from its frozen job.",
        ))
    if not _distribution_contrasts(scenario_summaries):
        unavailable_profiles.append(UnavailableProfile(
            "bh_face_distribution_contrast",
            "The input has no matching scenario represented by both BH and face profiles.",
        ))
    distribution_contrasts = _distribution_contrasts(scenario_summaries)
    return ReferenceProfileAnalysis(
        scenario_summaries=scenario_summaries,
        distribution_contrasts=distribution_contrasts,
        qprime_p32_points=tuple(p32_points),
        location_status_summaries=tuple(location_status_summaries),
        location_status_reason_counts=location_status_reason_counts,
        source_observation_count=len(observations),
        scenario_evaluation_count=scenario_evaluation_count,
        retry_count_available=False,
        unavailable_profiles=tuple(unavailable_profiles),
    )


def fingerprint_raw_dataset(
    dataset_snapshot: dict[str, JsonValue],
) -> SnapshotFingerprint:
    """Fingerprint a schema-versioned raw dataset snapshot as canonical JCS."""
    if not isinstance(dataset_snapshot, dict):
        raise TypeError("dataset_snapshot must be a dictionary")
    schema_version = dataset_snapshot.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != RAW_DATASET_SCHEMA_VERSION
    ):
        raise ValueError(
            f"dataset_snapshot.schema_version must be {RAW_DATASET_SCHEMA_VERSION}"
        )
    return fingerprint_snapshot(dataset_snapshot)


def build_analysis_snapshot(
    dataset_revision_index: int,
    dataset_sha256: str,
    *,
    jr_values: tuple[float, ...] | None = None,
    ja_values: tuple[float, ...] | None = None,
) -> dict[str, JsonValue]:
    """Build the approved analysis rules payload for one immutable raw revision."""
    if (
        isinstance(dataset_revision_index, bool)
        or not isinstance(dataset_revision_index, int)
        or dataset_revision_index <= 0
    ):
        raise ValueError("dataset_revision_index must be a positive integer")
    if (
        not isinstance(dataset_sha256, str)
        or len(dataset_sha256) != 64
        or any(character not in "0123456789abcdef" for character in dataset_sha256)
    ):
        raise ValueError("dataset_sha256 must be 64 lowercase hexadecimal characters")
    selected_jr_values = _selected_scenario_values(jr_values, JR_VALUES, "jr_values")
    selected_ja_values = _selected_scenario_values(ja_values, JA_VALUES, "ja_values")

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "dataset": {
            "revision_index": dataset_revision_index,
            "sha256": dataset_sha256,
        },
        "rules": {
            "formula": "calculation_rqd * jr / (fixed_jn * ja)",
            "calculation_rqd_floor": CALCULATION_RQD_FLOOR,
            "zero_cross_convention": ZERO_CROSS_CONVENTION,
            "fixed_jn_values": JN_VALUES,
            "jr_values": selected_jr_values,
            "ja_values": selected_ja_values,
            "bin_catalog_id": BIN_CATALOG_ID,
            "bin_edges": BIN_EDGES,
            "primary_bin_ids": tuple(
                str(index) for index in range(1, len(BIN_EDGES))
            ),
            "bin_assignment": "(lower, upper]",
            "overflow_bin_id": OVERFLOW_BIN_ID,
            "overflow_rule": "qprime > 400",
            "profile_summary": {
                "support_weighted_median": (
                    "first_qprime_with_cumulative_support_at_least_50_percent"
                ),
                "support_units": {"BH": "m", "face": "m2"},
                "cross_profile_comparison": (
                    "non_paired_descriptive_only; preserve modality support separately; "
                    "face_minus_bh_median_and_bin_support_fraction"
                ),
                "target_reach_rule": "qprime > 400",
                "target_required_calculation_rqd": (
                    "400 * fixed_jn * ja / jr; strict lower-exclusive threshold"
                ),
                "retry_history": "excluded_from_raw_observation_analysis",
            },
        },
        "implementation_version": ANALYSIS_IMPLEMENTATION_VERSION,
    }


def build_cumulative_analysis_snapshot(
    dataset_revision_index: int,
    dataset_sha256: str,
    *,
    jr_values: tuple[float, ...] | None = None,
    ja_values: tuple[float, ...] | None = None,
) -> dict[str, JsonValue]:
    """Build the rules payload for an immutable cumulative dataset revision."""
    snapshot = build_analysis_snapshot(
        dataset_revision_index,
        dataset_sha256,
        jr_values=jr_values,
        ja_values=ja_values,
    )
    dataset = snapshot["dataset"]
    if not isinstance(dataset, dict):
        raise RuntimeError("analysis snapshot dataset must be an object")
    return {
        **snapshot,
        "dataset": {
            "kind": "cumulative",
            **dataset,
        },
    }


def fingerprint_analysis(
    dataset_revision_index: int,
    dataset_sha256: str,
    *,
    jr_values: tuple[float, ...] | None = None,
    ja_values: tuple[float, ...] | None = None,
) -> SnapshotFingerprint:
    """Fingerprint analysis rules separately from the raw dataset and execution."""
    return fingerprint_snapshot(
        build_analysis_snapshot(
            dataset_revision_index,
            dataset_sha256,
            jr_values=jr_values,
            ja_values=ja_values,
        )
    )
