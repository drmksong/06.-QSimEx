"""Q-prime only: raw RQD is preserved; no Jw/SRF or rock-class policy."""

from dataclasses import dataclass
from typing import Literal, Union
from .models import BartonCategory, JointProfileEvidence, JointRealization

ProfileJoint = Union[JointRealization, JointProfileEvidence]

@dataclass(frozen=True)
class QPrimeProvenance:
    source: Literal["intersecting_joint", "no_intersection_convention"]
    selected_joint_id: str | None
    jr_category: BartonCategory | None
    ja_category: BartonCategory | None
    convention_id: str | None

@dataclass(frozen=True)
class QPrimeResult:
    raw_rqd: float
    calculation_rqd: float
    jn: float
    jr: float
    ja: float
    value: float
    provenance: QPrimeProvenance

def category_midpoint(category: BartonCategory) -> float: ...
def select_weakest_joint(joints: tuple[ProfileJoint, ...]) -> ProfileJoint | None: ...
def calculate_qprime(raw_rqd: float, domain_jn: float, joints: tuple[ProfileJoint, ...]) -> QPrimeResult: ...
