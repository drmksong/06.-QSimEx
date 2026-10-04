"""Length-supported observations, sampling contracts, and distribution comparison."""

from dataclasses import dataclass
from typing import Literal, Protocol
from .models import BoreholeSpec, CaseSpec, DomainSpec, JointRealization, LineIntersection, TunnelSpec, Vector3
from .geometry import ClippedBorehole, FaceSupport, OverlapInterval, TunnelStation
from .qprime import QPrimeResult

class JointGeometry(Protocol):
    def line_intersections(self, start: Vector3, direction: Vector3, length: float) -> tuple[LineIntersection, ...]: ...
    def face_intersections(self, station: TunnelStation, radius: float, domain: DomainSpec) -> tuple[JointRealization, ...]: ...

@dataclass(frozen=True)
class ProfileInterval:
    start: float
    end: float
    qprime: QPrimeResult

@dataclass(frozen=True)
class BoreholeProfile:
    borehole: BoreholeSpec
    clipped: ClippedBorehole | None
    intervals: tuple[ProfileInterval, ...]
    excluded_tail_length: float

@dataclass(frozen=True)
class FaceScanline:
    start: Vector3
    direction: Vector3
    length: float
    intersection_count: int
    linear_frequency: float
    rqd: float

@dataclass(frozen=True)
class FaceObservation:
    station: TunnelStation
    support: FaceSupport
    qprime: QPrimeResult | None
    scanlines: tuple[FaceScanline, ...]

@dataclass(frozen=True)
class TunnelProfile:
    observations: tuple[FaceObservation, ...]
    intervals: tuple[ProfileInterval, ...]
    stop_reason: Literal["tunnel_end", "invalid_boundary_face"]
    rejected_face: FaceSupport | None

@dataclass(frozen=True)
class DistributionSummary:
    support_length: float
    minimum: float
    maximum: float
    mean: float

@dataclass(frozen=True)
class ProfileComparison:
    overlap: tuple[OverlapInterval, ...]
    borehole_summary: DistributionSummary | None
    face_summary: DistributionSummary | None
    wasserstein_1: float | None
    unavailable_reason: str | None

@dataclass(frozen=True)
class SimulationResult:
    signature_id: str
    domain_id: str
    seed: int
    boreholes: tuple[BoreholeProfile, ...]
    tunnel: TunnelProfile

def sample_borehole(case: CaseSpec, borehole: BoreholeSpec, joints: JointGeometry) -> BoreholeProfile: ...
def sample_face(case: CaseSpec, station: TunnelStation, joints: JointGeometry) -> FaceObservation: ...
def next_round_length(qprime: float) -> float: ...
def sample_tunnel(case: CaseSpec, tunnel: TunnelSpec, joints: JointGeometry) -> TunnelProfile: ...
def compare_profiles(borehole: BoreholeProfile, tunnel: TunnelProfile, overlap: tuple[OverlapInterval, ...]) -> ProfileComparison: ...
