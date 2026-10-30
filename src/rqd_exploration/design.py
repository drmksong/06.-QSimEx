"""Deterministic pilot target ledger, LHS design, and manifest generation."""

from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import product
from math import exp, isclose, isfinite, log

import numpy as np
import scipy
from scipy.stats import qmc

from .config import (
    JA_VALUES,
    JN_VALUES,
    JR_VALUES,
    Bounds,
    DesignInput,
    NormalizedPilotInput,
    TargetGoalInput,
)
from .fingerprint import (
    ExecutionGeometry,
    ExecutionJointSet,
    ExecutionMeasurements,
    ExecutionRuntime,
    ExecutionSnapshot,
    JsonValue,
    execution_snapshot_payload,
    fingerprint_execution_snapshot,
    fingerprint_snapshot,
)
from .records import (
    ExecutionJob,
    FrozenManifest,
    PlannedBHInterval,
    PlannedFaceStation,
    PlannedLocation,
)

LHS_GENERATION_VERSION = "qsimex-pilot-lhs-v1"
LHS_RNG_SCHEME = (
    "LatinHypercube(scramble=True,strength=1,optimization=None); "
    "PCG64; LHS=default_rng(design_seed), scipy rng API; "
    "alpha=SeedSequence(design_seed,spawn_key=(1,)); "
    "kappa=SeedSequence(design_seed,spawn_key=(2,))"
)


@dataclass(frozen=True)
class LHSAxis:
    joint_set_id: str
    parameter: str
    bounds: Bounds


@dataclass(frozen=True)
class DesignSample:
    sample_index: int
    unit_coordinates: tuple[float, ...]
    joint_sets: tuple[ExecutionJointSet, ...]


@dataclass(frozen=True)
class LHSDesign:
    design: DesignInput
    axes: tuple[LHSAxis, ...]
    samples: tuple[DesignSample, ...]
    numpy_version: str
    scipy_version: str
    generation_version: str
    rng_scheme: str
    radius_transform: str


@dataclass(frozen=True)
class HighBinReachability:
    fixed_jn: float
    jr_value: float
    ja_value: float
    required_calculation_rqd_lower_exclusive: float
    max_qprime: float
    reachable: bool


@dataclass(frozen=True)
class TargetGoalLedgerEntry:
    goal: TargetGoalInput
    reachability: HighBinReachability


@dataclass(frozen=True)
class BlockTargetLedger:
    design_id: str
    block_id: str
    fixed_jn: float
    scenarios: tuple[HighBinReachability, ...]
    target_goals: tuple[TargetGoalLedgerEntry, ...]


def high_bin_reachability(
    fixed_jn: float, jr_value: float, ja_value: float,
) -> HighBinReachability:
    """Solve Q' > 400 over continuous calculation RQD in [10, 100]."""
    for name, value, allowed in (
        ("fixed_jn", fixed_jn, JN_VALUES),
        ("jr_value", jr_value, JR_VALUES),
        ("ja_value", ja_value, JA_VALUES),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number")
        if value not in allowed:
            raise ValueError(f"{name} must be one of {allowed}")
    jn, jr, ja = (Fraction(value) for value in (fixed_jn, jr_value, ja_value))
    threshold = 400 * jn * ja / jr
    maximum = 100 * jr / (jn * ja)
    return HighBinReachability(
        float(jn), float(jr), float(ja), float(threshold), float(maximum),
        threshold < 100,
    )


def build_target_ledger(config: NormalizedPilotInput) -> tuple[BlockTargetLedger, ...]:
    """Retain all 66 scenarios per design, separately linking explicit pilot goals."""
    if not isinstance(config, NormalizedPilotInput):
        raise TypeError("config must be a NormalizedPilotInput")
    ledgers: list[BlockTargetLedger] = []
    linked_goals: set[str] = set()
    for design in config.designs:
        scenarios = tuple(
            high_bin_reachability(design.fixed_jn, jr, ja)
            for jr, ja in product(JR_VALUES, JA_VALUES)
        )
        by_scores = {(item.jr_value, item.ja_value): item for item in scenarios}
        goals: list[TargetGoalLedgerEntry] = []
        for goal in config.target_goals:
            if goal.fixed_jn != design.fixed_jn:
                continue
            if (
                goal.target_bin_id != "qprime_gt_400"
                or goal.catalog_id != "primary_profile_10bin_v1"
            ):
                raise ValueError(f"unsupported target goal: {goal.goal_id}")
            reachability = by_scores.get((goal.jr_value, goal.ja_value))
            if reachability is None or not reachability.reachable:
                raise ValueError(f"target goal is not arithmetically reachable: {goal.goal_id}")
            goals.append(TargetGoalLedgerEntry(goal, reachability))
            linked_goals.add(goal.goal_id)
        ledgers.append(
            BlockTargetLedger(
                design.design_id, design.block_id, design.fixed_jn,
                scenarios, tuple(goals),
            )
        )
    unlinked = {goal.goal_id for goal in config.target_goals} - linked_goals
    if unlinked:
        raise ValueError(f"target goals have no matching design: {sorted(unlinked)}")
    return tuple(ledgers)


def _transform_coordinate(unit: float, bounds: Bounds, name: str) -> float:
    if not isfinite(unit) or not 0.0 <= unit < 1.0:
        raise ValueError(f"{name} LHS coordinate must be finite and in [0, 1)")
    if bounds.coordinate == "log":
        value = exp(log(bounds.lower) + unit * (log(bounds.upper) - log(bounds.lower)))
    elif bounds.coordinate == "linear":
        value = bounds.lower + unit * (bounds.upper - bounds.lower)
    else:
        raise ValueError(f"{name} has unsupported coordinate {bounds.coordinate!r}")
    if (
        not isfinite(value)
        or not bounds.lower <= value <= bounds.upper
        or (not bounds.upper_inclusive and value == bounds.upper)
    ):
        raise ValueError(f"{name} transformed value is outside its bounds")
    return value


def generate_lhs_design(design: DesignInput) -> LHSDesign:
    """Generate an immutable block design; do not generate DFNs or write a manifest."""
    if not isinstance(design, DesignInput):
        raise TypeError("design must be a validated DesignInput")
    if (
        isinstance(design.design_seed, bool)
        or not isinstance(design.design_seed, int)
        or not 0 <= design.design_seed <= 2**53 - 1
    ):
        raise ValueError("design_seed must be a non-negative safe integer")
    if (
        isinstance(design.sample_count, bool)
        or not isinstance(design.sample_count, int)
        or design.sample_count <= 0
    ):
        raise ValueError("sample_count must be a positive integer")
    if not 1 <= len(design.joint_sets) <= 5:
        raise ValueError("joint_sets must contain between 1 and 5 sets")
    if len({item.joint_set_id for item in design.joint_sets}) != len(design.joint_sets):
        raise ValueError("joint_set_id values must be unique")
    axes: list[LHSAxis] = []
    for joint_set in design.joint_sets:
        if (
            joint_set.size_radius_transform != "ordered_log_pair"
            or joint_set.size_r_min_m != joint_set.size_r_max_m
        ):
            raise ValueError("ordered_log_pair requires matching radius bounds")
        axes.extend(
            LHSAxis(joint_set.joint_set_id, parameter, bounds)
            for parameter, bounds in (
                ("p32_m2_per_m3", joint_set.p32),
                ("log_radius_a_m", joint_set.size_r_min_m),
                ("log_radius_b_m", joint_set.size_r_max_m),
                ("mean_dip_deg", design.mean_dip_deg),
                ("mean_dip_dir_deg", design.mean_dip_dir_deg),
            )
        )
    for axis in axes:
        expected_coordinate = (
            "linear" if axis.parameter.startswith("mean_dip") else "log"
        )
        bounds = axis.bounds
        if (
            bounds.coordinate != expected_coordinate
            or not isfinite(bounds.lower)
            or not isfinite(bounds.upper)
            or not bounds.lower < bounds.upper
            or (expected_coordinate == "log" and bounds.lower <= 0)
        ):
            raise ValueError(f"{axis.parameter} has invalid bounds or coordinate")
    for name, shape in (
        ("size_alpha", design.size_alpha), ("fisher_kappa", design.fisher_kappa),
    ):
        if (
            shape.distribution != "uniform"
            or shape.rng_stream != "separate_from_lhs"
            or not isfinite(shape.bounds.lower)
            or not isfinite(shape.bounds.upper)
            or not shape.bounds.lower < shape.bounds.upper
        ):
            raise ValueError(f"{name} requires finite uniform bounds and separate RNG")

    sampler = qmc.LatinHypercube(
        d=len(axes), scramble=True, strength=1, optimization=None,
        rng=np.random.default_rng(design.design_seed),
    )
    coordinates = sampler.random(n=design.sample_count)
    alpha_rng = np.random.default_rng(
        np.random.SeedSequence(design.design_seed, spawn_key=(1,)),
    )
    kappa_rng = np.random.default_rng(
        np.random.SeedSequence(design.design_seed, spawn_key=(2,)),
    )
    alphas = alpha_rng.uniform(
        design.size_alpha.bounds.lower, design.size_alpha.bounds.upper,
        size=design.sample_count,
    )
    kappas = kappa_rng.uniform(
        design.fisher_kappa.bounds.lower, design.fisher_kappa.bounds.upper,
        size=design.sample_count,
    )
    samples: list[DesignSample] = []
    for sample_index, row in enumerate(coordinates):
        values = tuple(
            _transform_coordinate(float(unit), axis.bounds, axis.parameter)
            for unit, axis in zip(row, axes)
        )
        joint_sets: list[ExecutionJointSet] = []
        for set_index, joint_set in enumerate(design.joint_sets):
            p32, radius_a, radius_b, dip, dip_dir = values[5 * set_index:5 * set_index + 5]
            r_min, r_max = sorted((radius_a, radius_b))
            if not r_min < r_max:
                raise ValueError(
                    f"design {design.design_id} sample {sample_index} "
                    f"set {joint_set.joint_set_id}: ordered radii are equal"
                )
            joint_sets.append(ExecutionJointSet(
                joint_set.joint_set_id, p32, float(alphas[sample_index]),
                r_min, r_max, dip, dip_dir, float(kappas[sample_index]),
            ))
        samples.append(DesignSample(
            sample_index, tuple(float(value) for value in row), tuple(joint_sets),
        ))
    return LHSDesign(
        design, tuple(axes), tuple(samples), np.__version__, scipy.__version__,
        LHS_GENERATION_VERSION, LHS_RNG_SCHEME, "ordered_log_pair",
    )


def _positive_number(value: float, name: str, *, allow_zero: bool = False) -> None:
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not isfinite(value) or value < 0 or (value == 0 and not allow_zero)
    ):
        raise ValueError(f"{name} must be a finite {'non-negative' if allow_zero else 'positive'} number")


def _index(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**53 - 1:
        raise ValueError(f"{name} must be a non-negative safe integer")


def _vector(value: tuple[float, float, float], name: str, *, unit: bool = False) -> None:
    if (
        not isinstance(value, tuple) or len(value) != 3
        or any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not isfinite(v) for v in value)
    ):
        raise ValueError(f"{name} must be a finite ENU 3-vector")
    if unit and not isclose(sum(v * v for v in value), 1.0, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError(f"{name} must be a unit direction")


def _planned_location_payload(location: PlannedLocation) -> dict[str, JsonValue]:
    if not isinstance(location, (PlannedBHInterval, PlannedFaceStation)):
        raise TypeError("planned locations must be typed BH intervals or face stations")
    if not isinstance(location.profile_id, str) or not location.profile_id.strip():
        raise ValueError("planned profile_id must be non-empty text")
    _index(location.location_index, "location_index")
    if isinstance(location, PlannedBHInterval):
        _positive_number(location.start_m, "BH start_m", allow_zero=True)
        _positive_number(location.end_m, "BH end_m")
        _positive_number(location.planned_support_length_m, "BH planned support length")
        if location.end_m <= location.start_m or not isclose(
            location.end_m - location.start_m, location.planned_support_length_m,
            rel_tol=1e-10, abs_tol=1e-10,
        ):
            raise ValueError("BH planned support must equal the positive interval length")
        _vector(location.start_enu_m, "BH start")
        _vector(location.direction_enu, "BH direction", unit=True)
        return {"modality": "BH", **asdict(location)}
    _positive_number(location.chainage_m, "face chainage_m", allow_zero=True)
    _positive_number(location.planned_support_area_m2, "face planned area")
    _vector(location.center_enu_m, "face center")
    _vector(location.normal_enu, "face normal", unit=True)
    if location.chainage_m == 0:
        if location.advance_distance_m is not None:
            raise ValueError("initial reference face must have NULL advance distance")
    elif location.advance_distance_m is None:
        raise ValueError("non-initial face requires advance distance")
    else:
        _positive_number(location.advance_distance_m, "face advance_distance_m")
    if not location.scanlines:
        raise ValueError("planned face must contain scanlines")
    indices = []
    for line in location.scanlines:
        _index(line.scanline_index, "scanline_index")
        indices.append(line.scanline_index)
        _vector(line.start_enu_m, "scanline start")
        _vector(line.direction_enu, "scanline direction", unit=True)
        _positive_number(line.planned_length_m, "scanline planned length")
    if len(set(indices)) != len(indices) or indices != sorted(indices):
        raise ValueError("planned scanlines must have unique ordered indices")
    return {"modality": "face", **asdict(location)}


def build_frozen_manifest(
    config: NormalizedPilotInput,
    *,
    manifest_id: str,
    runtime: ExecutionRuntime,
    boundary_rules_version: str,
    planned_locations: tuple[PlannedLocation, ...],
) -> FrozenManifest:
    """Build DB-ready JSON with explicit execution metadata; never infer or execute it.

    The caller must supply a complete geometry-consistent location plan and verified
    runtime/version metadata. Producer integration and completeness checks are P2.03b.
    """
    if not isinstance(config, NormalizedPilotInput):
        raise TypeError("config must be a NormalizedPilotInput")
    if not isinstance(manifest_id, str) or not manifest_id.strip():
        raise ValueError("manifest_id must be non-empty text")
    if sha256(config.source_yaml_bytes).hexdigest() != config.source_yaml_sha256:
        raise ValueError("source YAML digest does not match exact input bytes")
    if not planned_locations:
        raise ValueError("planned_locations must be explicitly supplied")
    locations = [_planned_location_payload(location) for location in planned_locations]
    location_keys = [
        ("BH" if isinstance(location, PlannedBHInterval) else "face",
         location.profile_id, location.location_index)
        for location in planned_locations
    ]
    if len(set(location_keys)) != len(location_keys):
        raise ValueError("duplicate planned location composite key")
    if {key[0] for key in location_keys} != {"BH", "face"}:
        raise ValueError("pilot requires both BH and face planned locations")
    locations = [
        item for _, item in sorted(zip(location_keys, locations), key=lambda pair: pair[0])
    ]
    geometry = config.geometry
    execution_geometry = ExecutionGeometry(
        geometry.domain_size_m, geometry.grid_spacing_m, geometry.tunnel_vertices_m,
        geometry.tunnel_radius_m, geometry.borehole_start_m,
        geometry.borehole_direction_enu, geometry.borehole_length_m,
        coordinate_frame="ENU",
    )
    if geometry.coordinate_frame != "ENU":
        raise ValueError("geometry coordinate_frame must be ENU")
    measurement = ExecutionMeasurements(
        config.measurements.bh_interval_m, config.measurements.face_advance_m,
        boundary_rules_version,
    )
    ledgers = build_target_ledger(config)
    designs: list[JsonValue] = []
    samples: list[JsonValue] = []
    jobs_payload: list[JsonValue] = []
    all_locations: list[JsonValue] = []
    jobs: list[ExecutionJob] = []
    sample_keys: set[tuple[str, str, int]] = set()
    for design in config.designs:
        result = generate_lhs_design(design)
        designs.append({
            "input": asdict(design),
            "axes": [asdict(axis) for axis in result.axes],
            "numpy_version": result.numpy_version,
            "scipy_version": result.scipy_version,
            "generation_version": result.generation_version,
            "rng_scheme": result.rng_scheme,
            "radius_transform": result.radius_transform,
        })
        for sample in result.samples:
            sample_key = (design.design_id, design.block_id, sample.sample_index)
            if sample_key in sample_keys:
                raise ValueError("duplicate design sample composite key")
            sample_keys.add(sample_key)
            key: dict[str, JsonValue] = {
                "manifest_id": manifest_id, "design_id": design.design_id,
                "block_id": design.block_id, "sample_index": sample.sample_index,
            }
            samples.append({
                **key, "fixed_jn": design.fixed_jn,
                "unit_coordinates": sample.unit_coordinates,
                "joint_sets": [asdict(joint_set) for joint_set in sample.joint_sets],
            })
            snapshot = ExecutionSnapshot(
                execution_geometry, design.fixed_jn, sample.joint_sets,
                design.realization_seed, measurement, runtime,
            )
            fingerprint = fingerprint_execution_snapshot(snapshot)
            job = ExecutionJob(
                manifest_id, design.design_id, design.block_id, sample.sample_index,
                design.realization_seed, snapshot, fingerprint,
            )
            jobs.append(job)
            job_key = {
                **key, "realization_seed": design.realization_seed,
                "execution_fingerprint_digest": fingerprint.sha256_hex,
            }
            jobs_payload.append({
                **job_key, "execution_snapshot": execution_snapshot_payload(snapshot),
            })
            all_locations.extend({**job_key, **location} for location in locations)
    payload: dict[str, JsonValue] = {
        "schema_version": 1,
        "manifest_id": manifest_id,
        "coordinate_frame": "ENU",
        "input_provenance": {
            "yaml_sha256": config.source_yaml_sha256,
            "source_reference": config.source_reference,
        },
        "designs": designs,
        "design_samples": samples,
        "target_goals": [
            {"manifest_id": manifest_id, **asdict(goal)} for goal in config.target_goals
        ],
        "target_ledger": [asdict(ledger) for ledger in ledgers],
        "jobs": jobs_payload,
        "planned_locations": all_locations,
    }
    return FrozenManifest(
        manifest_id, fingerprint_snapshot(payload).canonical_bytes.decode("utf-8"),
        config.source_yaml_bytes, config.source_yaml_sha256, config.source_reference,
        tuple(jobs),
    )
