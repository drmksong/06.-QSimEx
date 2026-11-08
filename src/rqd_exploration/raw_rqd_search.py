"""Raw-BH-RQD-only signature preview and observation summaries."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from math import isfinite
from pathlib import Path
import json
import sqlite3
from statistics import pstdev
import sys
from typing import Iterable, Sequence

import numpy as np

from .adapter import build_generation_case
from .config import Bounds, DesignInput, JointSetInput, NormalizedPilotInput, load_config
from .design import generate_lhs_design
from .fingerprint import fingerprint_snapshot
from .main_controller import MainController, reference_snapshot
from .main_policy import AXES, MainConfig
from .main_design import (
    expected_joint_counts,
    input_identity,
    snapshot_from_dict,
    validate_generating_input,
)
from .main_store import (
    MainPause,
    append_event,
    initialize_main_store,
    reconcile_starts,
    single_writer,
    starts_consumed,
)
from .measurement import RawBHObservation, RawObservation
from .measurement import plan_measurement_locations
from .records import PlannedBHInterval
from .runner import build_mlx_pilot_manifest
from .store import STORE_SCHEMA_VERSION, _atomic, initialize_store

RAW_RQD_COORDINATE_PARAMETERS = tuple(axis[0] for axis in AXES)
RAW_RQD_FIXED_JN_VALUES = (15.0, 20.0)


def load_raw_rqd_config(path: str | Path) -> NormalizedPilotInput:
    """Load a single-file raw-RQD input containing exactly the Jn15/Jn20 designs."""
    config = load_config(path)
    fixed_jn_values = tuple(sorted(design.fixed_jn for design in config.designs))
    if fixed_jn_values != RAW_RQD_FIXED_JN_VALUES:
        raise ValueError("raw-RQD input must contain exactly one Jn15 and one Jn20 design")
    return config


@dataclass(frozen=True)
class RawRqdPolicy:
    maximum_starts: int = 20_000
    review_checkpoint_starts: int | None = 10_000
    maximum_expected_joints: int = 10_000_000


@dataclass(frozen=True)
class RawRqdRunConfig:
    input: NormalizedPilotInput
    policy: RawRqdPolicy
    fingerprint: str
    snapshot_json: str

    @property
    def initial(self) -> None:
        return None

    @property
    def templates(self) -> dict[float, DesignInput]:
        return {design.fixed_jn: design for design in self.input.designs}

    @property
    def reference_input(self) -> NormalizedPilotInput:
        return self.input

    @property
    def source_yaml_bytes(self) -> bytes:
        return self.input.source_yaml_bytes

    @property
    def source_reference(self) -> str | None:
        return self.input.source_reference


@dataclass(frozen=True)
class RawRqdCondition:
    fixed_jn: float
    profile_id: str = "pilot-bh"

    def __post_init__(self) -> None:
        if (isinstance(self.fixed_jn, bool)
                or not isinstance(self.fixed_jn, (int, float))
                or not isfinite(self.fixed_jn) or self.fixed_jn <= 0):
            raise ValueError("fixed_jn must be finite and positive")
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError("profile_id must be non-empty text")

    @property
    def key(self) -> str:
        return f"raw-rqd/{self.fixed_jn:g}/{self.profile_id}"


@dataclass(frozen=True)
class RawRqdRecord:
    signature_id: str
    realization_seed: int
    profile_id: str
    location_index: int
    raw_rqd: float
    support_length_m: float
    is_valid: bool
    exclusion_reason: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.signature_id, str) or not self.signature_id.strip():
            raise ValueError("signature_id must be non-empty text")
        if type(self.realization_seed) is not int or not 0 <= self.realization_seed <= 2**53 - 1:
            raise ValueError("realization_seed must be a non-negative safe integer")
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError("profile_id must be non-empty text")
        if type(self.location_index) is not int or not 0 <= self.location_index <= 2**53 - 1:
            raise ValueError("location_index must be a non-negative safe integer")
        if (isinstance(self.raw_rqd, bool) or not isinstance(self.raw_rqd, (int, float))
                or not isfinite(self.raw_rqd) or not 0 <= self.raw_rqd <= 100):
            raise ValueError("raw_rqd must be finite and between 0 and 100")
        if (isinstance(self.support_length_m, bool)
                or not isinstance(self.support_length_m, (int, float))
                or not isfinite(self.support_length_m) or self.support_length_m < 0):
            raise ValueError("support_length_m must be finite and non-negative")
        if type(self.is_valid) is not bool:
            raise TypeError("is_valid must be a bool")
        if (self.is_valid and self.exclusion_reason is not None
                or not self.is_valid and (
                    not isinstance(self.exclusion_reason, str)
                    or not self.exclusion_reason.strip()
                )):
            raise ValueError("validity and exclusion_reason are inconsistent")


@dataclass(frozen=True)
class RawRqdSummary:
    signature_id: str
    observation_count: int
    supported_valid_count: int
    raw_rqd_min: float | None
    raw_rqd_max: float | None
    support_weighted_mean_rqd: float | None
    raw_rqd_population_sd: float | None
    seeds_with_supported_observations: tuple[int, ...]


def lhs_signature_records(
    config: NormalizedPilotInput | MainConfig,
) -> tuple[dict[str, object], ...]:
    """Return deterministic LHS signature inputs without generating or persisting DFNs."""
    if isinstance(config, MainConfig):
        designs = tuple(config.templates[jn] for jn in sorted(config.templates))
    elif isinstance(config, NormalizedPilotInput):
        designs = config.designs
    else:
        raise TypeError("config must be a validated pilot input or main config")
    records: list[dict[str, object]] = []
    for design in designs:
        lhs = generate_lhs_design(design)
        for sample in lhs.samples:
            records.append({
                "design_id": design.design_id,
                "block_id": design.block_id,
                "sample_index": sample.sample_index,
                "design_seed": design.design_seed,
                "realization_seed": design.realization_seed,
                "fixed_jn": design.fixed_jn,
                "joint_sets": [asdict(item) for item in sample.joint_sets],
            })
    return tuple(records)


def raw_bh_records(
    signature_id: str,
    realization_seed: int,
    observations: Iterable[RawObservation],
) -> tuple[RawRqdRecord, ...]:
    """Extract raw BH measurements only; preserve raw values and validity evidence."""
    if not isinstance(observations, Iterable):
        raise TypeError("observations must be iterable")
    return tuple(
        RawRqdRecord(
            signature_id=signature_id,
            realization_seed=realization_seed,
            profile_id=item.profile_id,
            location_index=item.location_index,
            raw_rqd=item.raw_rqd,
            support_length_m=item.support_length_m,
            is_valid=item.is_valid,
            exclusion_reason=item.exclusion_reason,
        )
        for item in observations
        if isinstance(item, RawBHObservation)
    )


def summarize_raw_rqd(
    records: Iterable[RawRqdRecord],
) -> tuple[RawRqdSummary, ...]:
    """Summarize the continuous raw-RQD response by signature."""
    grouped: dict[str, list[RawRqdRecord]] = {}
    for record in records:
        if not isinstance(record, RawRqdRecord):
            raise TypeError("records must contain RawRqdRecord values")
        grouped.setdefault(record.signature_id, []).append(record)

    summaries = []
    for signature_id, observations in sorted(grouped.items()):
        supported = [
            item for item in observations
            if item.is_valid and item.support_length_m >= 1.0
        ]
        total_support = sum(item.support_length_m for item in supported)
        values = [item.raw_rqd for item in supported]
        summaries.append(RawRqdSummary(
            signature_id=signature_id,
            observation_count=len(observations),
            supported_valid_count=len(supported),
            raw_rqd_min=min(values) if values else None,
            raw_rqd_max=max(values) if values else None,
            support_weighted_mean_rqd=(
                sum(item.raw_rqd * item.support_length_m for item in supported)
                / total_support if total_support else None
            ),
            raw_rqd_population_sd=pstdev(values) if values else None,
            seeds_with_supported_observations=tuple(sorted({
                item.realization_seed for item in supported
            })),
        ))
    return tuple(summaries)


def raw_rqd_config(
    config: NormalizedPilotInput | MainConfig | RawRqdRunConfig,
) -> MainConfig | RawRqdRunConfig:
    """Fingerprint the continuous raw-RQD exploration contract."""
    if isinstance(config, RawRqdRunConfig):
        return config
    if isinstance(config, NormalizedPilotInput):
        policy = RawRqdPolicy()
        payload = {
            "schema_version": config.schema_version,
            "implementation_version": "qsimex-raw-rqd-initial-cohort-v1",
            "yaml_sha256": config.source_yaml_sha256,
            "objective": "continuous-raw-bh-rqd-response",
            "minimum_valid_support_m": 1.0,
            "measurement_scope": "BH-only",
            "initial_signatures_by_jn": {
                f"{design.fixed_jn:g}": design.sample_count for design in config.designs
            },
            "realization_seeds_by_jn": {
                f"{design.fixed_jn:g}": design.realization_seed for design in config.designs
            },
            "policy": asdict(policy),
            "handoff": "initial-cohort-review",
        }
        fingerprint = fingerprint_snapshot(payload)
        return RawRqdRunConfig(
            config,
            policy,
            fingerprint.sha256_hex,
            fingerprint.canonical_bytes.decode(),
        )
    if not isinstance(config, MainConfig):
        raise TypeError("config must be a validated pilot input, raw-RQD config, or MainConfig")
    payload = json.loads(config.snapshot_json)
    for key in ("analysis_version", "bin_catalog", "Jr_values", "Ja_values",
                "reachability_floor"):
        payload.pop(key, None)
    policy = payload["policy"]
    for key in ("verification_seed", "progress_inputs_per_round", "stagnant_rounds"):
        policy.pop(key, None)
    payload["implementation_version"] = "qsimex-raw-rqd-coordinate-search-v3"
    payload["objective"] = {
        "kind": "continuous-raw-bh-rqd-response",
        "minimum_valid_support_m": 1.0,
    }
    payload["proposal_method"] = "raw-rqd-lhs10-coordinate-neighborhood-v1"
    payload["realization"] = {
        "seed": config.policy.initial_seed,
        "runs_per_signature": 1,
        "verification": None,
    }
    payload["refinement_metric"] = "support_weighted_mean_raw_rqd"
    payload["initial_signatures_by_jn"] = {
        f"{jn:g}": design.sample_count for jn, design in sorted(config.templates.items())
    }
    payload["coordinate_parameters"] = list(RAW_RQD_COORDINATE_PARAMETERS)
    payload["measurement_scope"] = "BH-only"
    payload["update_method"] = "cyclic-coordinate-neighborhood-min-rqd"
    fingerprint = fingerprint_snapshot(payload)
    return replace(
        config,
        fingerprint=fingerprint.sha256_hex,
        snapshot_json=fingerprint.canonical_bytes.decode(),
    )


def _input_axis_bounds(
    design: DesignInput,
    joint_set: JointSetInput,
    parameter: str,
) -> Bounds:
    if parameter == "p32_m2_per_m3":
        return joint_set.p32
    if parameter == "size_r_min_m":
        return joint_set.size_r_min_m
    if parameter == "size_r_max_m":
        return joint_set.size_r_max_m
    if parameter == "mean_dip_deg":
        return design.mean_dip_deg
    if parameter == "mean_dip_dir_deg":
        return design.mean_dip_dir_deg
    raise ValueError(f"unsupported raw-RQD coordinate parameter: {parameter}")


class RawRqdController(MainController):
    """Explore raw BH-RQD response coverage for the configured Jn values."""

    include_face_measurements = False
    record_p32 = False
    preserve_input_manifest_ids = True
    progress_job_label = ""

    def __init__(self, connection, config, factory, runtime, *, output_dir,
                 progress_callback=None):
        config = raw_rqd_config(config)
        reference = reference_snapshot(config, runtime)
        normalized = config.reference_input
        case = build_generation_case(
            normalized.geometry, normalized.measurements, reference.fixed_jn,
            reference.joint_sets, case_id="raw-rqd-profile",
        )
        profile_id = next(
            (item.profile_id for item in plan_measurement_locations(case)
             if isinstance(item, PlannedBHInterval)),
            None,
        )
        if profile_id is None:
            raise ValueError("the configured raw-RQD search has no BH measurement profile")
        targets = tuple(RawRqdCondition(fixed_jn=jn, profile_id=profile_id)
                        for jn in sorted(config.templates))
        super().__init__(
            connection, config, factory, runtime, output_dir=output_dir,
            progress_callback=progress_callback, targets=targets, run_prefix="raw-rqd",
        )
        self.state.pop("target_evidence", None)
        self.state.pop("stagnant_rounds", None)
        self.state.setdefault("raw_rqd_centers", {})
        self.state.setdefault("raw_rqd_axis_cursors", {})
        self.state.setdefault("raw_rqd_axis_checks", {})
        self.state.setdefault("raw_rqd_exhausted_jn", [])
        self.state.setdefault("followup_batch_index", 0)
        self.state.setdefault("last_followup_batch", None)

    def _validate_generating_input(self, snapshot):
        validate_generating_input(
            snapshot, self.config.templates[snapshot.fixed_jn])

    def _expected_joint_counts(self, snapshot):
        return expected_joint_counts(
            snapshot, self.config.templates[snapshot.fixed_jn])

    def _suitable(self, target):
        seed = self.config.templates[target.fixed_jn].realization_seed
        return sorted(
            identity for identity in self.profiles
            if self.state["inputs"][identity]["fixed_jn"] == target.fixed_jn
            and self._profile(identity, seed) is not None
        )

    def _seed_for_identity(self, identity):
        fixed_jn = self.state["inputs"][identity]["fixed_jn"]
        return self.config.templates[fixed_jn].realization_seed

    def _raw_rqd_population_sd(self, identity):
        profile = self._profile(identity, self._seed_for_identity(identity))
        values = [] if profile is None else [
            point.raw_rqd for point in profile.points if point.support_m >= 1.0
        ]
        return pstdev(values) if values else None

    def _supported_weighted_mean_rqd(self, identity):
        profile = self._profile(identity, self._seed_for_identity(identity))
        points = [] if profile is None else [
            point for point in profile.points if point.support_m >= 1.0
        ]
        support = sum(point.support_m for point in points)
        if not support:
            return None
        return sum(point.raw_rqd * point.support_m for point in points) / support

    @staticmethod
    def _response_bin(value):
        return min(9, max(0, int(value // 10)))

    def _response_bin_coverage(self, target):
        counts = {f"{index * 10:02d}-{(index + 1) * 10:02d}": 0
                  for index in range(10)}
        for identity in self._suitable(target):
            mean = self._supported_weighted_mean_rqd(identity)
            if mean is not None:
                index = self._response_bin(mean)
                counts[f"{index * 10:02d}-{(index + 1) * 10:02d}"] += 1
        return counts

    @staticmethod
    def _stream_seed(design, batch_index, fixed_jn, stream, attempt=0):
        sequence = np.random.SeedSequence(
            design.design_seed,
            spawn_key=(batch_index, int(fixed_jn), stream, attempt),
        )
        return int(sequence.generate_state(1, dtype=np.uint32)[0])

    def _lhs_candidates(self, target, batch_index, count, stream, role, known):
        design = self.config.templates[target.fixed_jn]
        base = reference_snapshot(self.config, self.runtime)
        candidates = []
        attempt = 0
        while len(candidates) < count and attempt < 100:
            seed = self._stream_seed(
                design, batch_index, target.fixed_jn, stream, attempt)
            attempt += 1
            lhs = generate_lhs_design(replace(
                design, design_seed=seed, sample_count=count - len(candidates)))
            for sample in lhs.samples:
                snapshot = replace(
                    base,
                    fixed_jn=target.fixed_jn,
                    joint_sets=sample.joint_sets,
                    realization_seed=design.realization_seed,
                )
                self._validate_generating_input(snapshot)
                identity = input_identity(snapshot)
                if identity in known:
                    continue
                known.add(identity)
                candidates.append({
                    "input_id": identity,
                    "snapshot": snapshot,
                    "seed": design.realization_seed,
                    "role": role,
                    "design_seed": seed,
                })
                if len(candidates) == count:
                    break
        if len(candidates) != count:
            raise ValueError(
                f"could not generate {count} unique {role} signatures "
                f"for Jn={target.fixed_jn:g}"
            )
        return candidates

    def _response_gap_targets(self, target, count):
        ranked = sorted(
            (mean, identity)
            for identity in self._suitable(target)
            if (mean := self._supported_weighted_mean_rqd(identity)) is not None
        )
        if len(ranked) < 2:
            return []
        occupied_bins = {
            self._response_bin(mean) for mean, _ in ranked
        }
        gaps = []
        for (lower, lower_id), (upper, upper_id) in zip(ranked, ranked[1:]):
            if upper <= lower:
                continue
            midpoint = (lower + upper) / 2.0
            for bin_index in range(10):
                target_mean = bin_index * 10.0 + 5.0
                if (bin_index not in occupied_bins
                        and lower < target_mean < upper):
                    gaps.append((
                        -(upper - lower), abs(target_mean - midpoint),
                        target_mean, lower_id, upper_id,
                    ))
        gaps.sort()
        selected = gaps[:count]
        if len(selected) < count:
            # Keep refining the widest observed response gaps after all empty bins
            # inside the sampled response range have been proposed.
            fractions = (0.5, 0.25, 0.75, 0.125, 0.375, 0.625, 0.875)
            refinements = []
            for (lower, lower_id), (upper, upper_id) in zip(ranked, ranked[1:]):
                if upper <= lower:
                    continue
                for fraction in fractions:
                    target_mean = lower + (upper - lower) * fraction
                    refinements.append((
                        -(upper - lower), abs(fraction - 0.5),
                        target_mean, lower_id, upper_id,
                    ))
            refinements.sort()
            used = {item[2] for item in selected}
            for item in refinements:
                if item[2] in used:
                    continue
                selected.append(item)
                used.add(item[2])
                if len(selected) == count:
                    break
        return [
            {
                "target_mean_rqd": item[2],
                "lower_signature_id": item[3],
                "upper_signature_id": item[4],
            }
            for item in selected
        ]

    @staticmethod
    def _interpolate_coordinate(left, right, fraction, bounds, parameter):
        if bounds.coordinate == "log":
            value = np.exp(
                (1.0 - fraction) * np.log(left) + fraction * np.log(right))
        elif parameter == "mean_dip_dir_deg":
            delta = (right - left + 180.0) % 360.0 - 180.0
            value = (left + fraction * delta) % 360.0
        elif bounds.coordinate == "linear":
            value = left + fraction * (right - left)
        else:
            raise ValueError(
                f"unsupported coordinate for {parameter}: {bounds.coordinate}")
        if (not isfinite(float(value)) or value < bounds.lower or value > bounds.upper
                or not bounds.upper_inclusive and value == bounds.upper):
            raise ValueError(f"interpolated {parameter} is outside input bounds")
        return float(value)

    def _interpolated_snapshot(self, target, proposal, shape_sample):
        lower = snapshot_from_dict(
            self.state["inputs"][proposal["lower_signature_id"]])
        upper = snapshot_from_dict(
            self.state["inputs"][proposal["upper_signature_id"]])
        target_mean = proposal["target_mean_rqd"]
        lower_mean = self._supported_weighted_mean_rqd(
            proposal["lower_signature_id"])
        upper_mean = self._supported_weighted_mean_rqd(
            proposal["upper_signature_id"])
        if lower_mean is None or upper_mean is None or upper_mean <= lower_mean:
            raise ValueError("response-gap refinement has invalid bracketing means")
        fraction = (target_mean - lower_mean) / (upper_mean - lower_mean)
        design = self.config.templates[target.fixed_jn]
        input_joint_sets = {
            item.joint_set_id: item for item in design.joint_sets
        }
        joint_sets = []
        if not (len(lower.joint_sets) == len(upper.joint_sets)
                == len(shape_sample.joint_sets)):
            raise ValueError("response-gap refinement joint-set counts do not match")
        for left, right, shape in zip(
                lower.joint_sets, upper.joint_sets, shape_sample.joint_sets):
            if left.joint_set_id != right.joint_set_id:
                raise ValueError("response-gap refinement joint-set ids do not match")
            bounds = input_joint_sets[left.joint_set_id]
            values = {}
            for parameter in RAW_RQD_COORDINATE_PARAMETERS:
                input_bounds = _input_axis_bounds(design, bounds, parameter)
                values[parameter] = self._interpolate_coordinate(
                    getattr(left, parameter),
                    getattr(right, parameter),
                    fraction,
                    input_bounds,
                    parameter,
                )
            joint_sets.append(replace(
                left,
                p32_m2_per_m3=values["p32_m2_per_m3"],
                size_r_min_m=values["size_r_min_m"],
                size_r_max_m=values["size_r_max_m"],
                mean_dip_deg=values["mean_dip_deg"],
                mean_dip_dir_deg=values["mean_dip_dir_deg"],
                size_alpha=shape.size_alpha,
                fisher_kappa=shape.fisher_kappa,
            ))
        snapshot = replace(lower, joint_sets=tuple(joint_sets))
        self._validate_generating_input(snapshot)
        return snapshot, fraction

    def _local_candidates(self, target, batch_index, count, known):
        targets = self._response_gap_targets(target, count)
        if not targets:
            return []
        design = self.config.templates[target.fixed_jn]
        jitter_seed = self._stream_seed(
            design, batch_index, target.fixed_jn, 2)
        shape_design = generate_lhs_design(replace(
            design, design_seed=jitter_seed, sample_count=len(targets)))
        candidates = []
        for proposal, shape_sample in zip(targets, shape_design.samples):
            snapshot, fraction = self._interpolated_snapshot(
                target, proposal, shape_sample)
            identity = input_identity(snapshot)
            if identity in known:
                continue
            known.add(identity)
            candidates.append({
                "input_id": identity,
                "snapshot": snapshot,
                "seed": design.realization_seed,
                "role": "response_gap_refinement",
                "target_mean_rqd": proposal["target_mean_rqd"],
                "target_response_bin": self._response_bin(
                    proposal["target_mean_rqd"]),
                "lower_signature_id": proposal["lower_signature_id"],
                "upper_signature_id": proposal["upper_signature_id"],
                "interpolation_fraction": fraction,
                "design_seed": jitter_seed,
            })
        return candidates

    def _plan_followup_batch(self):
        if self.state.get("active_followup_batch") is not None:
            raise ValueError("a raw-RQD follow-up batch is already active")
        batch_index = self.state["followup_batch_index"] + 1
        known = set(self.state["inputs"])
        candidates = []
        candidate_ids_by_jn = {}
        for target in self.targets:
            key = f"{target.fixed_jn:g}"
            batch = self._lhs_candidates(
                target, batch_index, 5, 1, "global_space_filling", known)
            local = self._local_candidates(target, batch_index, 5, known)
            batch.extend(local)
            if len(local) < 5:
                batch.extend(self._lhs_candidates(
                    target, batch_index, 5 - len(local), 3,
                    "global_space_filling_fallback", known))
            candidate_ids_by_jn[key] = [item["input_id"] for item in batch]
            candidates.extend({**item, "fixed_jn": target.fixed_jn} for item in batch)
        self.state["round_index"] += 1
        self.state["followup_batch_index"] = batch_index
        self.state["active_followup_batch"] = {
            "batch_index": batch_index,
            "policy": "hybrid-global-lhs-response-gap-v1",
            "candidate_ids_by_jn": candidate_ids_by_jn,
            "candidates": [
                {key: value for key, value in item.items() if key != "snapshot"}
                for item in candidates
            ],
        }
        for item in candidates:
            self.state["inputs"][item["input_id"]] = asdict(item["snapshot"])
            self.state["queue"].append({
                "input_id": item["input_id"],
                "seed": item["seed"],
                "role": item["role"],
            })

    def _complete_followup_batch(self):
        batch = self.state.get("active_followup_batch")
        if batch is None:
            return
        completed_by_jn = {}
        for target in self.targets:
            key = f"{target.fixed_jn:g}"
            identities = batch["candidate_ids_by_jn"][key]
            if len(identities) != 10 or len(set(identities)) != 10:
                raise MainPause(
                    "execution_error",
                    f"follow-up batch must contain 10 unique signatures for Jn={key}",
                )
            completed = [
                identity for identity in identities
                if self._profile(identity, self._seed_for_identity(identity)) is not None
            ]
            if len(completed) != 10:
                raise MainPause(
                    "execution_error",
                    f"follow-up batch has {len(completed)}/10 completed signatures for Jn={key}",
                )
            completed_by_jn[key] = completed
        self.state["last_followup_batch"] = {
            **deepcopy(batch),
            "completed_signatures_by_jn": completed_by_jn,
            "response_bin_coverage_by_jn": {
                f"{target.fixed_jn:g}": self._response_bin_coverage(target)
                for target in self.targets
            },
        }
        self.state["active_followup_batch"] = None
        raise MainPause(
            "continuation_batch_review",
            {"batch_index": batch["batch_index"], "completed_signatures_by_jn": completed_by_jn},
        )

    def _signature_parameter_deltas(self, reference_id, candidate_id):
        reference_sets = {
            item["joint_set_id"]: item
            for item in self.state["inputs"][reference_id]["joint_sets"]
        }
        candidate_sets = {
            item["joint_set_id"]: item
            for item in self.state["inputs"][candidate_id]["joint_sets"]
        }
        deltas = []
        for joint_set_id in sorted(reference_sets.keys() & candidate_sets.keys()):
            for axis, *_ in AXES:
                reference_value = reference_sets[joint_set_id][axis]
                candidate_value = candidate_sets[joint_set_id][axis]
                if candidate_value != reference_value:
                    deltas.append({
                        "joint_set_id": joint_set_id,
                        "parameter": axis,
                        "reference_value": reference_value,
                        "candidate_value": candidate_value,
                        "delta": candidate_value - reference_value,
                    })
        return deltas

    def _signature_axes(self, snapshot):
        design = self.config.templates[snapshot.fixed_jn]
        input_joint_sets = {
            joint_set.joint_set_id: joint_set for joint_set in design.joint_sets
        }
        axes = []
        for set_index, snapshot_joint_set in enumerate(snapshot.joint_sets):
            input_joint_set = input_joint_sets.get(snapshot_joint_set.joint_set_id)
            if input_joint_set is None:
                raise ValueError(
                    f"unknown joint set in raw-RQD snapshot: "
                    f"{snapshot_joint_set.joint_set_id}"
                )
            for parameter, small_step, large_step, *_ in AXES:
                bounds = _input_axis_bounds(design, input_joint_set, parameter)
                axes.append((set_index, (
                    parameter,
                    small_step,
                    large_step,
                    bounds.lower,
                    bounds.upper,
                    bounds.upper_inclusive,
                )))
        return axes

    def _plan_round(self, target):
        self.state["round_index"] += 1
        jn_key = f"{target.fixed_jn:g}"
        round_state = {
            "round_index": self.state["round_index"],
            "target": target.key,
            "phase": "search",
            "kind": None,
            "candidate_ids": [],
            "candidates": [],
            "before_suitable": self._suitable(target),
            "proposals": [],
        }
        self.state["round"] = round_state
        center_id = self.state["raw_rqd_centers"].get(jn_key)
        design = self.config.templates[target.fixed_jn]
        seed = design.realization_seed

        if center_id is None:
            lhs = generate_lhs_design(design)
            base = reference_snapshot(self.config, self.runtime)
            for sample in lhs.samples:
                snapshot = replace(
                    base,
                    fixed_jn=target.fixed_jn,
                    joint_sets=sample.joint_sets,
                    realization_seed=seed,
                )
                identity = input_identity(snapshot)
                self.state["inputs"].setdefault(identity, asdict(snapshot))
                round_state["candidate_ids"].append(identity)
                round_state["candidates"].append({
                    "input_id": identity,
                    "role": "initial_lhs",
                })
                self.state["queue"].append({
                    "input_id": identity,
                    "seed": seed,
                    "role": "initial_lhs",
                })
            round_state["kind"] = "initial_lhs"
            return

        reference = snapshot_from_dict(self.state["inputs"][center_id])
        axes = self._signature_axes(reference)
        checks = self.state["raw_rqd_axis_checks"].setdefault(jn_key, [])
        cursor = self.state["raw_rqd_axis_cursors"].get(jn_key, 0)
        for offset in range(len(axes)):
            axis_index = (cursor + offset) % len(axes)
            check_key = f"{center_id}:{axis_index}"
            if check_key in checks:
                continue
            set_index, axis = axes[axis_index]
            parameter, step, _, lower, upper, upper_inclusive = axis
            joint_set = reference.joint_sets[set_index]
            value = getattr(joint_set, parameter)
            candidate_ids = []
            queued_ids = []
            proposal_records = []
            for sign in (-1, 1):
                candidate_value = value + sign * step
                if (candidate_value < lower or candidate_value > upper
                        or not upper_inclusive and candidate_value == upper):
                    proposal_records.append({
                        "parameter": parameter,
                        "sign": sign,
                        "status": "outside_bounds",
                    })
                    continue
                joint_sets = list(reference.joint_sets)
                joint_sets[set_index] = replace(
                    joint_set, **{parameter: candidate_value})
                snapshot = replace(reference, joint_sets=tuple(joint_sets))
                try:
                    self._validate_generating_input(snapshot)
                except ValueError as error:
                    proposal_records.append({
                        "parameter": parameter,
                        "sign": sign,
                        "status": "invalid",
                        "detail": str(error),
                    })
                    continue
                identity = input_identity(snapshot)
                if identity == center_id:
                    continue
                self.state["inputs"].setdefault(identity, asdict(snapshot))
                candidate_ids.append(identity)
                has_profile = self._profile(identity, seed) is not None
                proposal_records.append({
                    "input_id": identity,
                    "parameter": parameter,
                    "sign": sign,
                    "candidate_value": candidate_value,
                    "status": "reused" if has_profile else "eligible",
                })
                if not has_profile:
                    queued_ids.append(identity)

            if not candidate_ids:
                checks.append(check_key)
                continue

            self.state["raw_rqd_axis_cursors"][jn_key] = (
                axis_index + 1) % len(axes)
            round_state.update({
                "kind": "coordinate",
                "allocation_reference": center_id,
                "axis_index": axis_index,
                "axis_check_key": check_key,
                "axis": {
                    "joint_set_id": joint_set.joint_set_id,
                    "parameter": parameter,
                    "step": step,
                },
                "candidate_ids": candidate_ids,
                "candidates": proposal_records,
            })
            self.state["queue"].extend({
                "input_id": identity,
                "seed": seed,
                "role": "coordinate_neighbor",
            } for identity in queued_ids)
            return

        exhausted = self.state["raw_rqd_exhausted_jn"]
        if target.fixed_jn not in exhausted:
            exhausted.append(target.fixed_jn)
        self.state["round"] = None
        self._report_event("jn_neighborhood_exhausted")

    def _round_signature_response_deltas(self, round_state, candidate_ids):
        reference_id = round_state.get("allocation_reference")
        if reference_id is None:
            return []
        reference_mean = self._supported_weighted_mean_rqd(reference_id)
        deltas = []
        for candidate_id in sorted(candidate_ids):
            candidate_mean = self._supported_weighted_mean_rqd(candidate_id)
            deltas.append({
                "round_index": round_state["round_index"],
                "reference_signature_id": reference_id,
                "candidate_signature_id": candidate_id,
                "reference_support_weighted_mean_rqd": reference_mean,
                "candidate_support_weighted_mean_rqd": candidate_mean,
                "support_weighted_mean_rqd_delta": (
                    candidate_mean - reference_mean
                    if candidate_mean is not None and reference_mean is not None
                    else None
                ),
                "parameter_deltas": self._signature_parameter_deltas(
                    reference_id, candidate_id),
            })
        return deltas

    def _plan_progress(self, _target):
        del _target
        round_state = self.state["round"]
        round_state["phase"] = "round_complete"
        target = self._target(round_state["target"])
        round_state["realization_seed"] = self.config.templates[
            target.fixed_jn].realization_seed
        for key in ("progress", "progress_pairs", "verification_input"):
            round_state.pop(key, None)

    def _progress_status(self, consumed=None):
        policy = self.config.policy
        consumed = starts_consumed(self.connection, self.run_id) if consumed is None else consumed
        signatures_by_jn = {}
        for target in self.targets:
            signatures_by_jn[f"{target.fixed_jn:g}"] = self._suitable(target)
        round_state = self.state.get("round")
        round_state = round_state if isinstance(round_state, dict) else {}
        queue = self.state.get("queue")
        task = queue[0] if isinstance(queue, list) and queue and isinstance(queue[0], dict) else {}
        seeds_by_jn = {
            f"{jn:g}": design.realization_seed
            for jn, design in sorted(self.config.templates.items())
        }
        unique_seeds = set(seeds_by_jn.values())
        condition = round_state.get("target")
        if condition is None:
            target_index = self.state["target_cursor"] % len(self.targets)
            condition = self.targets[target_index].key
        return {
            "starts_consumed": consumed,
            "starts_maximum": policy.maximum_starts,
            "starts_remaining": max(0, policy.maximum_starts - consumed),
            "realization": {
                "seed": next(iter(unique_seeds)) if len(unique_seeds) == 1 else None,
                "seeds_by_jn": seeds_by_jn,
                "runs_per_signature": 1,
                "verification": None,
            },
            "signature_count": len(self.profiles),
            "signatures_by_jn": signatures_by_jn,
            "current_work": {
                "round_index": self.state["round_index"],
                "phase": self.state["phase"],
                "round_phase": round_state.get("phase"),
                "jn_condition": condition,
                "input_id": task.get("input_id"),
                "seed": task.get("seed"),
                "role": task.get("role"),
                "job_stage": "queued" if task else (
                    round_state.get("phase") if round_state else self.state["phase"]),
            },
        }

    def _candidate_log_label(self, task, round_state=None):
        round_state = self.state.get("round") if round_state is None else round_state
        identity = task["input_id"]
        if not isinstance(round_state, dict):
            return "signature"
        if round_state.get("kind") == "initial_lhs":
            try:
                index = round_state["candidate_ids"].index(identity) + 1
            except ValueError:
                return "initial LHS"
            return f"LHS {index}/{len(round_state['candidate_ids'])}"
        if round_state.get("kind") != "coordinate":
            return "signature"
        candidate = next(
            (item for item in round_state.get("candidates", [])
             if item.get("input_id") == identity),
            None,
        )
        reference_id = round_state.get("allocation_reference")
        if candidate is None or reference_id is None:
            return "coordinate neighbor"
        parameter = candidate["parameter"]
        joint_set_id = round_state["axis"]["joint_set_id"]
        reference = snapshot_from_dict(self.state["inputs"][reference_id])
        reference_set = next(
            item for item in reference.joint_sets
            if item.joint_set_id == joint_set_id
        )
        before = getattr(reference_set, parameter)
        after = candidate["candidate_value"]
        return (
            f"{joint_set_id}/{parameter}={before:.6g}->{after:.6g} "
            f"(delta={after - before:+.6g})"
        )

    def _format_progress_context(self, task, consumed):
        progress = self._progress_status(consumed)
        work = progress["current_work"]
        snapshot = self.state["inputs"].get(task["input_id"], {})
        fixed_jn = snapshot.get("fixed_jn")
        jn_label = f"{fixed_jn:g}" if isinstance(fixed_jn, (int, float)) else "?"
        round_state = self.state.get("round")
        round_kind = round_state.get("kind") if isinstance(round_state, dict) else None
        return (
            f"raw-rqd starts={progress['starts_consumed']}/"
            f"{progress['starts_maximum']} remaining={progress['starts_remaining']} "
            f"measured-signatures={progress['signature_count']} "
            f"round={work['round_index']} kind={round_kind or '-'} "
            f"phase={work['phase']}/{work['round_phase'] or '-'} Jn={jn_label} "
            f"candidate={self._candidate_log_label(task)} "
            f"seed={task['seed']} role={task['role']}"
        )

    def _report_task_completion(self, task):
        if self.progress_callback is None:
            return
        identity, seed = task["input_id"], task["seed"]
        profile = self._profile(identity, seed)
        points = [] if profile is None else list(profile.points)
        total_support = sum(point.support_m for point in points)
        mean = (
            sum(point.raw_rqd * point.support_m for point in points) / total_support
            if total_support else None
        )
        if mean is None:
            statistics = "BH-supported=0 raw-RQD=unavailable"
        else:
            raw_values = [point.raw_rqd for point in points]
            statistics = (
                f"BH-supported={len(points)} support={total_support:.1f}m "
                f"raw-RQD[min={min(raw_values):.2f},max={max(raw_values):.2f},"
                f"weighted-mean={mean:.2f},population-sd={pstdev(raw_values):.2f}]"
            )
        round_state = self.state.get("round")
        reference_id = (
            round_state.get("allocation_reference")
            if isinstance(round_state, dict) else None
        )
        if reference_id is not None:
            reference_mean = self._supported_weighted_mean_rqd(reference_id)
            if mean is not None and reference_mean is not None:
                statistics += (
                    f" vs-center-mean={reference_mean:.2f}"
                    f" delta-mean={mean - reference_mean:+.2f}"
                )
        consumed = starts_consumed(self.connection, self.run_id)
        self.progress_callback(
            f"{self._format_progress_context(task, consumed)} "
            f"result={task.get('result', 'reused')} {statistics}"
        )

    def _format_round_completion(self, round_state):
        target = self._target(round_state["target"])
        prefix = (
            f"raw-rqd round={round_state['round_index']} "
            f"Jn={target.fixed_jn:g} kind={round_state['kind']} "
        )
        if round_state["kind"] == "initial_lhs":
            center_id = round_state["selected_center"]
            center_label = self._candidate_log_label(
                {"input_id": center_id}, round_state)
            return (
                f"{prefix}center selected from "
                f"{len(round_state['candidate_ids'])} LHS signatures "
                f"({center_label}); "
                f"weighted-mean="
                f"{round_state['selected_center_support_weighted_mean_rqd']:.2f}"
            )
        before = round_state["center_before_support_weighted_mean_rqd"]
        after = round_state["center_after_support_weighted_mean_rqd"]
        if round_state["center_moved"]:
            label = self._candidate_log_label(
                {"input_id": round_state["center_after"]}, round_state)
            return (
                f"{prefix}center moved to {label}; "
                f"weighted-mean={before:.2f}->{after:.2f} "
                f"(delta={after - before:+.2f})"
            )
        axis = round_state["axis"]
        return (
            f"{prefix}center unchanged after testing "
            f"{axis['joint_set_id']}/{axis['parameter']} +/-{axis['step']:g}; "
            f"center-weighted-mean={before:.2f}"
        )

    def summary(self):
        progress = self._progress_status()
        raw_rqd_by_signature = {}
        raw_bh_observations_by_signature = {}
        for identity, profile_groups in sorted(self.profiles.items()):
            observations = [
                point
                for seed, profile in sorted(
                    profile_groups.get(self.profile_id, {}).items())
                if seed == self._seed_for_identity(identity)
                for point in profile.points
            ]
            values = [point.raw_rqd for point in observations]
            raw_rqd_by_signature[identity] = {
                "supported_valid_observation_count": len(observations),
                "raw_rqd_min": min(values) if values else None,
                "raw_rqd_max": max(values) if values else None,
                "support_weighted_mean_rqd": (
                    sum(point.raw_rqd * point.support_m for point in observations)
                    / sum(point.support_m for point in observations)
                    if observations else None
                ),
                "raw_rqd_population_sd": pstdev(values) if values else None,
                "realization_seed": self._seed_for_identity(identity),
            }
            raw_bh_observations_by_signature[identity] = [
                {
                    "start_m": point.start_m,
                    "end_m": point.end_m,
                    "raw_rqd": point.raw_rqd,
                    "support_m": point.support_m,
                }
                for point in observations
            ]
        centers_by_jn = {}
        for jn_key, identity in self.state["raw_rqd_centers"].items():
            centers_by_jn[jn_key] = {
                "signature_id": identity,
                "support_weighted_mean_rqd": self._supported_weighted_mean_rqd(identity),
                "raw_rqd_population_sd": self._raw_rqd_population_sd(identity),
            }
        return {
            "run_id": self.run_id,
            "phase": self.state["phase"],
            "reason": self.state.get("reason"),
            "objective": "continuous_raw_bh_rqd_response",
            **progress,
            "fixed_jn_values": [target.fixed_jn for target in self.targets],
            "round_index": self.state["round_index"],
            "detail": self.state.get("detail"),
            "input_conditions": {
                identity: {
                    key: value for key, value in self.state["inputs"][identity].items()
                    if key not in ("realization_seed", "runtime")
                }
                for identity in sorted(self.profiles)
            },
            "centers_by_jn": centers_by_jn,
            "coordinate_parameters": list(RAW_RQD_COORDINATE_PARAMETERS),
            "exhausted_jn_values": list(self.state["raw_rqd_exhausted_jn"]),
            "raw_rqd_by_signature": raw_rqd_by_signature,
            "raw_bh_observations_by_signature": raw_bh_observations_by_signature,
            "response_bin_coverage_by_jn": {
                f"{target.fixed_jn:g}": self._response_bin_coverage(target)
                for target in self.targets
            },
            "followup_batch_index": self.state["followup_batch_index"],
            "active_followup_batch": deepcopy(
                self.state.get("active_followup_batch")),
            "last_followup_batch": deepcopy(
                self.state.get("last_followup_batch")),
            "last_completed_round_response_deltas": (
                self.state.get("last_round", {}).get("signature_response_deltas", [])
            ),
        }

    def _report_progress_snapshot(self, event, *, reason=None, completed_bin=None,
                                  completed_bin_progress=None):
        del completed_bin, completed_bin_progress
        if self.progress_callback is None:
            return
        progress = self._progress_status()
        work = progress["current_work"]
        details = [
            f"raw-rqd event={event}",
            f"starts={progress['starts_consumed']}/{progress['starts_maximum']}",
            f"signatures={progress['signature_count']}",
            f"Jn={work['jn_condition'] or '-'}",
            f"round={work['round_index']}",
        ]
        if reason is not None:
            details.append(f"reason={reason}")
        self.progress_callback(" ".join(details))

    def _report_event(self, kind):
        summary = self.summary()
        summary["dataset_revision_index"] = None
        summary["dataset_sha256"] = None
        index = append_event(self.connection, self.run_id, kind, summary)
        self._write_event(index, summary)

    def _write_event(self, index, summary):
        directory = self.output_dir / self.run_id / f"event-{index}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "summary.json"
        content = json.dumps(
            summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if path.exists():
            if path.read_text() != content:
                raise ValueError("raw-RQD event report conflicts with its immutable journal")
        else:
            path.write_text(content)

    def _complete_round(self, target):
        round_state = self.state["round"]
        if round_state is None:
            return
        newly_observed = sorted(
            set(self._suitable(target)) - set(round_state["before_suitable"]))
        round_state["newly_observed_signatures"] = newly_observed
        response_deltas = self._round_signature_response_deltas(
            round_state, round_state["candidate_ids"])
        round_state["signature_response_deltas"] = response_deltas
        previous_state = self.state
        self.state = deepcopy(previous_state)
        jn_key = f"{target.fixed_jn:g}"
        if round_state["kind"] == "initial_lhs":
            ranked = [
                (mean, identity)
                for identity in round_state["candidate_ids"]
                if (mean := self._supported_weighted_mean_rqd(identity)) is not None
            ]
            if not ranked:
                self.state = previous_state
                raise MainPause(
                    "incomparable",
                    f"initial signatures for Jn={target.fixed_jn:g} have no supported BH RQD",
                )
            center_mean, center_id = min(ranked)
            self.state["raw_rqd_centers"][jn_key] = center_id
            self.state["raw_rqd_axis_checks"][jn_key] = []
            self.state["raw_rqd_axis_cursors"][jn_key] = 0
            round_state["selected_center"] = center_id
            round_state["selected_center_support_weighted_mean_rqd"] = center_mean
        elif round_state.get("kind") == "coordinate":
            reference_id = round_state["allocation_reference"]
            reference_mean = self._supported_weighted_mean_rqd(reference_id)
            ranked = [
                (mean, identity)
                for identity in round_state["candidate_ids"]
                if (mean := self._supported_weighted_mean_rqd(identity)) is not None
            ]
            best_mean, best_id = min(ranked, default=(None, reference_id))
            moved = (
                reference_mean is not None
                and best_mean is not None
                and best_mean < reference_mean
            )
            if moved:
                self.state["raw_rqd_centers"][jn_key] = best_id
            round_state["center_before"] = reference_id
            round_state["center_after"] = best_id if moved else reference_id
            round_state["center_moved"] = moved
            round_state["center_before_support_weighted_mean_rqd"] = reference_mean
            round_state["center_after_support_weighted_mean_rqd"] = (
                best_mean if moved else reference_mean)
            self.state["raw_rqd_axis_checks"].setdefault(jn_key, []).append(
                round_state["axis_check_key"])
        self.state["last_round"] = deepcopy(round_state)
        self.state["round"] = None
        payload = {
            **self.summary(),
            "completed_round": deepcopy(round_state),
            "round_outcome": {
                "newly_observed_signatures": newly_observed,
                "signature_response_deltas": response_deltas,
            },
            "dataset_revision_index": None,
            "dataset_sha256": None,
        }
        try:
            with _atomic(self.connection):
                index = append_event(self.connection, self.run_id, "round_complete", payload)
                self._save()
        except BaseException:
            self.state = previous_state
            raise
        self._write_event(index, payload)
        if self.progress_callback is not None:
            self.progress_callback(self._format_round_completion(round_state))

    def run(self, *, continue_from_review=False):
        reconcile_starts(self.connection, self.run_id)
        for index, payload in self.connection.execute(
            "SELECT event_index,payload FROM main_control_events WHERE run_id=? ORDER BY event_index",
            (self.run_id,),
        ).fetchall():
            self._write_event(index, json.loads(payload))
        if continue_from_review and (
                self.state["phase"] != "paused"
                or self.state["reason"] not in (
                    "initial_cohort_review", "continuation_batch_review")):
            raise ValueError(
                "--continue-from-review requires a paused initial-cohort or "
                "follow-up-batch review"
            )
        if self.state["phase"] in ("paused", "complete"):
            if continue_from_review:
                self.state["phase"] = self.state.pop("resume_phase", "exploration")
                self.state["reason"] = None
                self.state.pop("detail", None)
            elif self.state["reason"] in ("user_interruption", "review_checkpoint"):
                if self.state["reason"] == "review_checkpoint":
                    self.state["review_checkpoint_released"] = True
                self.state["phase"] = self.state.pop("resume_phase")
                self.state["reason"] = None
                self._save()
            else:
                return self.summary()
        try:
            if continue_from_review:
                self._plan_followup_batch()
                self._save()
            if self._initial_pause is not None:
                raise self._initial_pause
            while True:
                self._check_review_checkpoint()
                if self.state["queue"]:
                    task = self.state["queue"][0]
                    self._save()
                    self._perform(task)
                    self.state["queue"].pop(0)
                    self._save()
                    continue
                if self.state.get("active_followup_batch") is not None:
                    self._complete_followup_batch()
                if self.state["phase"] == "initial":
                    self.state["phase"] = "exploration"
                    self._save()
                if self.state["round"] is not None:
                    target = self._target(self.state["round"]["target"])
                    phase = self.state["round"]["phase"]
                    if phase == "search":
                        self._plan_progress(target)
                    elif phase == "round_complete":
                        self._complete_round(target)
                    else:
                        raise MainPause(
                            "execution_error",
                            f"unsupported raw-RQD round phase: {phase}",
                        )
                    self._save()
                    continue
                initial_jn_keys = {f"{target.fixed_jn:g}" for target in self.targets}
                if initial_jn_keys.issubset(self.state["raw_rqd_centers"]):
                    raise MainPause(
                        "initial_cohort_review",
                        {
                            "signatures_by_jn": {
                                f"{jn:g}": self._suitable(target)
                                for jn, target in (
                                    (target.fixed_jn, target) for target in self.targets
                                )
                            },
                            "centers_by_jn": deepcopy(self.state["raw_rqd_centers"]),
                        },
                    )
                available_targets = [
                    item for item in self.targets
                    if item.fixed_jn not in self.state["raw_rqd_exhausted_jn"]
                ]
                if not available_targets:
                    self.state["phase"] = "complete"
                    self.state["reason"] = "targets_complete"
                    self._save(status="complete", reason="targets_complete")
                    self._report_event("complete")
                    return self.summary()
                target = self._choose_rotating(available_targets, "target_cursor")
                self._plan_round(target)
                self._save()
        except KeyboardInterrupt:
            self._pause("user_interruption")
            raise
        except MainPause as pause:
            self._pause(pause.reason, pause.detail)
            return self.summary()
        except Exception as error:
            self._pause("execution_error", f"{type(error).__name__}: {error}")
            return self.summary()


def _assert_raw_database_is_separate(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, STORE_SCHEMA_VERSION):
        raise ValueError("raw-RQD requires an empty database or raw schema4; no automatic migration")
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "main_control_runs" in tables:
        run_ids = [row[0] for row in connection.execute(
            "SELECT run_id FROM main_control_runs")]
        if any(not run_id.startswith("raw-rqd-") for run_id in run_ids):
            raise ValueError("raw-RQD requires a database separate from every main run")
    if "manifest" in tables:
        manifest_ids = [row[0] for row in connection.execute(
            "SELECT manifest_id FROM manifest")]
        if any(not manifest_id.startswith("raw-rqd-") for manifest_id in manifest_ids):
            raise ValueError("raw-RQD requires a database separate from pilot and main manifests")


def execute_raw_rqd(connection, config, factory, runtime, *, confirmed=False,
                    output_dir, progress_callback=None, continue_from_review=False):
    if not confirmed:
        raise PermissionError("raw-RQD execution requires explicit confirmation")
    if runtime.backend != "mlx":
        raise ValueError("raw-RQD execution requires MLX; no automatic CPU fallback")
    if connection.in_transaction:
        raise ValueError("raw-RQD execution requires a connection without an uncommitted transaction")
    with single_writer(connection):
        connection.execute("PRAGMA foreign_keys = ON")
        _assert_raw_database_is_separate(connection)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            initialize_store(connection)
        elif version != STORE_SCHEMA_VERSION:
            raise ValueError("raw-RQD requires schema4; no automatic schema2/3 migration")
        initialize_main_store(connection)
        controller = RawRqdController(
            connection, config, factory, runtime, output_dir=output_dir,
            progress_callback=progress_callback,
        )
        return controller.run(continue_from_review=continue_from_review)


def _validate_database_path(path: Path) -> bool:
    exists = path.exists()
    if exists and (not path.is_file() or path.stat().st_size == 0):
        raise ValueError(f"invalid raw-RQD database file: {path}")
    if exists:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            _assert_raw_database_is_separate(connection)
        finally:
            connection.close()
    return exists


def _print_progress(message: str) -> None:
    from datetime import datetime, timezone

    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}",
          file=sys.stderr, flush=True)


def _parser() -> argparse.ArgumentParser:
    default_config = (
        Path(__file__).resolve().parents[2] / "config/rqd_exploration_main_baseline3.yml"
    )
    parser = argparse.ArgumentParser(
        prog="run_rqd_exploration.py raw-rqd",
        description="Explore continuous raw BH RQD responses across the main signature domain.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser(
        "preview", help="preview main-domain LHS signatures without simulation or database writes",
    )
    preview.add_argument("--config", type=Path, default=default_config)
    run = commands.add_parser(
        "run", help="execute raw-RQD search in a separate database after explicit confirmation",
    )
    run.add_argument("--config", type=Path, default=default_config)
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--confirm-execution", action="store_true")
    run.add_argument(
        "--continue-from-review",
        action="store_true",
        help="release a paused initial-cohort or follow-up-batch review",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "preview":
        config = load_raw_rqd_config(args.config)
        payload = lhs_signature_records(config)
        seeds_by_jn = {
            f"{design.fixed_jn:g}": design.realization_seed for design in config.designs
        }
        print(json.dumps({
            "command": "raw-rqd-preview",
            "objective": "continuous_raw_bh_rqd_response",
            "realization": {
                "seed": next(iter(set(seeds_by_jn.values())))
                if len(set(seeds_by_jn.values())) == 1 else None,
                "seeds_by_jn": seeds_by_jn,
                "runs_per_signature": 1,
                "verification": None,
            },
            "refinement_metric": "support_weighted_mean_raw_rqd",
            "initial_signatures_by_jn": {
                f"{design.fixed_jn:g}": design.sample_count for design in config.designs
            },
            "coordinate_parameters": list(RAW_RQD_COORDINATE_PARAMETERS),
            "measurement_scope": "BH-only",
            "update_method": "hybrid-global-lhs-response-gap-v1",
            "fixed_jn_values": [design.fixed_jn for design in config.designs],
            "candidate_count": len(payload),
            "candidates": payload,
            "geometry": asdict(config.geometry),
            "measurements": asdict(config.measurements),
            "handoff": "initial_cohort_review",
            "simulation_started": False,
            "database_written": False,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        if not args.confirm_execution:
            print(
                "Raw-RQD execution not confirmed. Add --confirm-execution to permit "
                "database writes and DFN generation; no database was opened.",
                file=sys.stderr,
            )
            return 2
        config = load_raw_rqd_config(args.config)
        runtime_manifest = build_mlx_pilot_manifest(
            config, manifest_id="raw-rqd-runtime-preflight")
        runtime = runtime_manifest.jobs[0].snapshot.runtime
        from src.euler_campaign.mlx_backend import MlxCaseJointFactory

        factory = MlxCaseJointFactory()
        exists = _validate_database_path(args.database)
        if not exists:
            args.database.parent.mkdir(parents=True, exist_ok=True)
        connection = (
            sqlite3.connect(f"{args.database.resolve().as_uri()}?mode=rw", uri=True)
            if exists else sqlite3.connect(args.database)
        )
        try:
            summary = execute_raw_rqd(
                connection, config, factory, runtime, confirmed=True,
                output_dir=args.output_dir, progress_callback=_print_progress,
                continue_from_review=args.continue_from_review,
            )
            print(json.dumps({
                "command": "raw-rqd-run",
                "summary": summary,
            }, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if summary["reason"] in (
                "targets_complete", "review_checkpoint", "initial_cohort_review",
                "continuation_batch_review",
            ) else 1
        finally:
            connection.close()
    raise ValueError(f"unsupported raw-RQD command: {args.command}")
