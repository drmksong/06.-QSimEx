"""Pure geometry contracts, independent of simulation backends and campaign state."""

from dataclasses import dataclass
from typing import Literal
from .models import BoreholeSpec, DomainSpec, TunnelSpec, Vector3

@dataclass(frozen=True)
class ClippedBorehole:
    requested: BoreholeSpec
    start: Vector3
    direction: Vector3
    entry_distance: float
    exit_distance: float

@dataclass(frozen=True)
class TunnelStation:
    chainage: float
    segment_index: int
    center: Vector3
    direction: Vector3

@dataclass(frozen=True)
class FaceSupport:
    station: TunnelStation
    full_area: float
    in_domain_area: float
    valid: bool

@dataclass(frozen=True)
class OverlapInterval:
    borehole_start: float
    borehole_end: float
    tunnel_start: float
    tunnel_end: float

def normalize_direction(direction: Vector3) -> Vector3: ...
def borehole_from_endpoints(borehole_id: str, start: Vector3, end: Vector3, interval_length: float, purpose: Literal["face_comparison", "independent"]) -> BoreholeSpec: ...
def clip_borehole(borehole: BoreholeSpec, domain: DomainSpec) -> ClippedBorehole | None: ...
def validate_tunnel(tunnel: TunnelSpec) -> None: ...
def validate_borehole_tunnel(borehole: BoreholeSpec, tunnel: TunnelSpec) -> None: ...
def locate_station(tunnel: TunnelSpec, chainage: float) -> TunnelStation: ...
def measure_face_support(station: TunnelStation, radius: float, domain: DomainSpec) -> FaceSupport: ...
def find_overlap(borehole: ClippedBorehole, tunnel: TunnelSpec) -> tuple[OverlapInterval, ...]: ...
