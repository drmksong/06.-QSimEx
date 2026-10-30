"""RFC 8785 canonical JSON and SHA-256 fingerprints."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from types import NoneType
from typing import Literal, TypeAlias

import rfc8785

EXECUTION_SCHEMA_VERSION = 1
CANONICALIZATION = "RFC 8785"
DIGEST_ALGORITHM = "SHA-256"

_JsonScalar: TypeAlias = NoneType | bool | int | float | str
JsonValue: TypeAlias = (
    _JsonScalar
    | list["JsonValue"]
    | tuple["JsonValue", ...]
    | dict[str, "JsonValue"]
)


@dataclass(frozen=True)
class SnapshotFingerprint:
    canonical_bytes: bytes
    sha256_hex: str


@dataclass(frozen=True)
class ExecutionGeometry:
    domain_size_m: tuple[float, float, float]
    grid_spacing_m: tuple[float, float, float]
    tunnel_vertices_m: tuple[tuple[float, float, float], ...]
    tunnel_radius_m: float
    borehole_start_m: tuple[float, float, float]
    borehole_direction_enu: tuple[float, float, float]
    borehole_length_m: float
    coordinate_frame: Literal["ENU"] = "ENU"


@dataclass(frozen=True)
class ExecutionJointSet:
    joint_set_id: str
    p32_m2_per_m3: float
    size_alpha: float
    size_r_min_m: float
    size_r_max_m: float
    mean_dip_deg: float
    mean_dip_dir_deg: float
    fisher_kappa: float


@dataclass(frozen=True)
class ExecutionMeasurements:
    bh_interval_m: float
    face_advance_m: float
    boundary_rules_version: str


@dataclass(frozen=True)
class ExecutionRuntime:
    generator_version: str
    measurement_version: str
    backend: str
    device_runtime: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionSnapshot:
    geometry: ExecutionGeometry
    fixed_jn: float
    joint_sets: tuple[ExecutionJointSet, ...]
    realization_seed: int
    measurements: ExecutionMeasurements
    runtime: ExecutionRuntime


def fingerprint_snapshot(value: JsonValue) -> SnapshotFingerprint:
    """Canonicalize a JSON value with JCS and return its bytes and SHA-256 digest."""
    canonical_bytes = rfc8785.dumps(value)
    return SnapshotFingerprint(
        canonical_bytes,
        sha256(canonical_bytes).hexdigest(),
    )


def _validate_finite_numbers(value: JsonValue, path: str = "snapshot") -> None:
    if isinstance(value, bool) or value is None:
        raise TypeError(f"{path} contains a non-numeric JSON scalar")
    if isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} object keys must be strings")
            _validate_finite_numbers(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_finite_numbers(child, f"{path}[{index}]")
        return
    raise TypeError(f"{path} contains a non-JSON value: {type(value).__name__}")


def _validate_numeric_input(value: object, path: str) -> None:
    if isinstance(value, bool):
        raise TypeError(f"{path} must contain numbers, not booleans")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_numeric_input(child, f"{path}[{index}]")
        return
    raise TypeError(f"{path} must contain only numbers")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_vector3(value: tuple[float, ...], name: str) -> None:
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError(f"{name} must contain exactly three values")
    _validate_numeric_input(value, name)


def execution_snapshot_payload(snapshot: ExecutionSnapshot) -> dict[str, JsonValue]:
    """Build the approved version-1 execution payload without attempt/provenance fields."""
    if not isinstance(snapshot, ExecutionSnapshot):
        raise TypeError("snapshot must be an ExecutionSnapshot")
    if snapshot.geometry.coordinate_frame != "ENU":
        raise ValueError("execution geometry coordinate_frame must be 'ENU'")
    for name in ("domain_size_m", "grid_spacing_m", "borehole_start_m",
                 "borehole_direction_enu"):
        _require_vector3(
            getattr(snapshot.geometry, name),
            f"geometry.{name}",
        )
    if (
        not isinstance(snapshot.geometry.tunnel_vertices_m, tuple)
        or len(snapshot.geometry.tunnel_vertices_m) < 2
    ):
        raise ValueError("geometry.tunnel_vertices_m must contain at least two points")
    for index, vertex in enumerate(snapshot.geometry.tunnel_vertices_m):
        _require_vector3(vertex, f"geometry.tunnel_vertices_m[{index}]")
    _validate_numeric_input(snapshot.geometry.tunnel_radius_m, "geometry.tunnel_radius_m")
    _validate_numeric_input(snapshot.geometry.borehole_length_m, "geometry.borehole_length_m")
    if not snapshot.joint_sets:
        raise ValueError("execution snapshot must contain at least one joint set")
    for index, joint_set in enumerate(snapshot.joint_sets):
        _require_text(joint_set.joint_set_id, f"joint_sets[{index}].joint_set_id")
        for name in (
            "p32_m2_per_m3",
            "size_alpha",
            "size_r_min_m",
            "size_r_max_m",
            "mean_dip_deg",
            "mean_dip_dir_deg",
            "fisher_kappa",
        ):
            _validate_numeric_input(
                getattr(joint_set, name),
                f"joint_sets[{index}].{name}",
            )
    if isinstance(snapshot.realization_seed, bool) or not isinstance(
        snapshot.realization_seed, int
    ):
        raise TypeError("realization_seed must be an integer")
    _validate_numeric_input(snapshot.realization_seed, "realization_seed")
    _validate_numeric_input(snapshot.fixed_jn, "fixed_jn")
    _validate_numeric_input(snapshot.measurements.bh_interval_m, "measurement.bh_interval_m")
    _validate_numeric_input(
        snapshot.measurements.face_advance_m,
        "measurement.face_advance_m",
    )
    if len({joint_set.joint_set_id for joint_set in snapshot.joint_sets}) != len(
        snapshot.joint_sets
    ):
        raise ValueError("execution snapshot joint_set_id values must be unique")
    _require_text(
        snapshot.measurements.boundary_rules_version,
        "boundary_rules_version",
    )
    for name, value in (
        ("generator_version", snapshot.runtime.generator_version),
        ("measurement_version", snapshot.runtime.measurement_version),
        ("backend", snapshot.runtime.backend),
    ):
        _require_text(value, name)
    if not snapshot.runtime.device_runtime or any(
        not isinstance(value, str) or not value.strip()
        for value in snapshot.runtime.device_runtime
    ):
        raise ValueError("device_runtime must contain non-empty values")

    joint_sets: list[JsonValue] = [
        {
            "joint_set_id": joint_set.joint_set_id,
            "p32_m2_per_m3": joint_set.p32_m2_per_m3,
            "size_alpha": joint_set.size_alpha,
            "size_r_min_m": joint_set.size_r_min_m,
            "size_r_max_m": joint_set.size_r_max_m,
            "mean_dip_deg": joint_set.mean_dip_deg,
            "mean_dip_dir_deg": joint_set.mean_dip_dir_deg,
            "fisher_kappa": joint_set.fisher_kappa,
        }
        for joint_set in snapshot.joint_sets
    ]
    payload: dict[str, JsonValue] = {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "canonicalization": CANONICALIZATION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "inputs": {
            "geometry": {
                "coordinate_frame": snapshot.geometry.coordinate_frame,
                "domain_size_m": snapshot.geometry.domain_size_m,
                "grid_spacing_m": snapshot.geometry.grid_spacing_m,
                "tunnel_vertices_m": snapshot.geometry.tunnel_vertices_m,
                "tunnel_radius_m": snapshot.geometry.tunnel_radius_m,
                "borehole_start_m": snapshot.geometry.borehole_start_m,
                "borehole_direction_enu": snapshot.geometry.borehole_direction_enu,
                "borehole_length_m": snapshot.geometry.borehole_length_m,
            },
            "dfn": {
                "fixed_jn": snapshot.fixed_jn,
                "joint_sets": joint_sets,
            },
            "realization_seed": snapshot.realization_seed,
            "measurement": {
                "bh_interval_m": snapshot.measurements.bh_interval_m,
                "face_advance_m": snapshot.measurements.face_advance_m,
                "boundary_rules_version": (
                    snapshot.measurements.boundary_rules_version
                ),
            },
            "runtime": {
                "generator_version": snapshot.runtime.generator_version,
                "measurement_version": snapshot.runtime.measurement_version,
                "backend": snapshot.runtime.backend,
                "device_runtime": snapshot.runtime.device_runtime,
            },
        },
    }
    _validate_finite_numbers(payload)
    return payload


def fingerprint_execution_snapshot(
    snapshot: ExecutionSnapshot,
) -> SnapshotFingerprint:
    """Fingerprint the approved normalized execution inputs and runtime conditions."""
    return fingerprint_snapshot(execution_snapshot_payload(snapshot))
