"""Typed data contracts for the RQD exploration pilot."""

from dataclasses import dataclass
from typing import TypeAlias

from .fingerprint import ExecutionSnapshot, SnapshotFingerprint

Vector3: TypeAlias = tuple[float, float, float]


@dataclass(frozen=True)
class PlannedScanline:
    scanline_index: int
    start_enu_m: Vector3
    direction_enu: Vector3
    planned_length_m: float


@dataclass(frozen=True)
class PlannedBHInterval:
    profile_id: str
    location_index: int
    start_m: float
    end_m: float
    start_enu_m: Vector3
    direction_enu: Vector3
    planned_support_length_m: float


@dataclass(frozen=True)
class PlannedFaceStation:
    profile_id: str
    location_index: int
    chainage_m: float
    center_enu_m: Vector3
    normal_enu: Vector3
    planned_support_area_m2: float
    advance_distance_m: float | None
    scanlines: tuple[PlannedScanline, ...]


PlannedLocation: TypeAlias = PlannedBHInterval | PlannedFaceStation


@dataclass(frozen=True)
class ExecutionJob:
    manifest_id: str
    design_id: str
    block_id: str
    sample_index: int
    realization_seed: int
    snapshot: ExecutionSnapshot
    fingerprint: SnapshotFingerprint


@dataclass(frozen=True)
class FrozenManifest:
    manifest_id: str
    manifest_json: str
    source_yaml_bytes: bytes
    source_yaml_sha256: str
    source_reference: str | None
    jobs: tuple[ExecutionJob, ...]
