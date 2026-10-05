"""Physical inputs and identities; no sampling, calculation, or file access."""

from dataclasses import dataclass
from typing import Literal, Union

Vector3 = tuple[float, float, float]
FeatureBlock = Literal["density", "size", "orientation"]
GENERATOR_VERSION: str

@dataclass(frozen=True)
class BartonCategory:
    category_id: str
    parameter: Literal["Jr", "Ja"]
    description: str
    lower_value: float
    upper_value: float

@dataclass(frozen=True)
class JointCondition:
    jr_category: BartonCategory
    ja_category: BartonCategory

@dataclass(frozen=True)
class JointSetSpec:
    set_id: int
    name: str
    density_type: Literal["P32", "spacing"]
    density_value: float
    size_alpha: float
    size_r_min: float
    size_r_max: float
    mean_dip: float
    mean_dip_dir: float
    fisher_kappa: float
    condition: JointCondition
    @property
    def mean_normal(self) -> Vector3: ...

@dataclass(frozen=True)
class DomainSpec:
    cell_counts: tuple[int, int, int]
    grid_spacing: Vector3
    jn: float

@dataclass(frozen=True)
class BoreholeSpec:
    borehole_id: str
    start: Vector3
    direction: Vector3
    requested_length: float
    interval_length: float
    purpose: Literal["face_comparison", "independent"]

@dataclass(frozen=True)
class TunnelSpec:
    vertices: tuple[Vector3, ...]
    radius: float

@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    domain: DomainSpec
    joint_sets: tuple[JointSetSpec, ...]
    boreholes: tuple[BoreholeSpec, ...]
    tunnel: TunnelSpec

@dataclass(frozen=True)
class Signature:
    signature_id: str
    case: CaseSpec

@dataclass(frozen=True)
class JointRealization:
    joint_id: str
    set_id: int
    center: Vector3
    normal: Vector3
    radius: float
    condition: JointCondition

@dataclass(frozen=True)
class JointProfileEvidence:
    joint_id: str
    set_id: int
    condition: JointCondition

@dataclass(frozen=True)
class LineIntersection:
    distance: float
    joint: Union[JointRealization, JointProfileEvidence]

def validate_case(case: CaseSpec) -> None: ...
def identify_signature(case: CaseSpec) -> Signature: ...
def dip_direction_from_mean_normal(
    normal: Vector3, fallback_dip_dir: float = ...
) -> tuple[float, float]: ...
def identify_domain(
    signature: Signature, seed: int, generator_version: str = ...
) -> str: ...
