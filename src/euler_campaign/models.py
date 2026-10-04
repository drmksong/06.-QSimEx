"""Immutable campaign inputs, independent of legacy simulation and I/O.

Category catalogue lookup, case-wide validation, and identity generation are
separate implementation steps. These records do not select conditions for cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

Vector3 = tuple[float, float, float]
FeatureBlock = Literal["density", "size", "orientation"]


@dataclass(frozen=True)
class BartonCategory:
    category_id: str
    parameter: Literal["Jr", "Ja"]
    description: str
    lower_value: float
    upper_value: float

    def __post_init__(self) -> None:
        if not self.category_id.strip():
            raise ValueError("Barton category_id must not be empty")
        if self.parameter not in ("Jr", "Ja"):
            raise ValueError("Barton parameter must be Jr or Ja")
        if not self.description.strip():
            raise ValueError("Barton category description must not be empty")
        if not isfinite(self.lower_value) or not isfinite(self.upper_value):
            raise ValueError("Barton category values must be finite")
        if self.lower_value <= 0 or self.upper_value < self.lower_value:
            raise ValueError("Barton category requires 0 < lower_value <= upper_value")


@dataclass(frozen=True)
class JointCondition:
    jr_category: BartonCategory
    ja_category: BartonCategory

    def __post_init__(self) -> None:
        if self.jr_category.parameter != "Jr":
            raise ValueError("jr_category must refer to Jr")
        if self.ja_category.parameter != "Ja":
            raise ValueError("ja_category must refer to Ja")


@dataclass(frozen=True)
class JointSetSpec:
    set_id: int
    name: str
    density_type: Literal["P32", "spacing"]
    density_value: float
    size_alpha: float
    size_r_min: float
    size_r_max: float
    mean_normal: Vector3
    fisher_kappa: float
    condition: JointCondition


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
class LineIntersection:
    distance: float
    joint: JointRealization


def validate_case(case: CaseSpec) -> None:
    raise NotImplementedError("Case-wide validation is not implemented in the data-model step")


def identify_signature(case: CaseSpec) -> Signature:
    raise NotImplementedError("Signature identity generation is not implemented yet")


def identify_domain(signature: Signature, seed: int) -> str:
    raise NotImplementedError("Domain identity generation is not implemented yet")
