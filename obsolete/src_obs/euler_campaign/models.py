"""Immutable campaign inputs, independent of legacy simulation and I/O.

Category catalogue lookup, case-wide validation, and identity generation are
separate implementation steps. These records do not select conditions for cases.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import acos, atan2, cos, degrees, hypot, isfinite, radians, sin
from typing import Literal, Union

Vector3 = tuple[float, float, float]
FeatureBlock = Literal["density", "size", "orientation"]
GENERATOR_VERSION = "qsimex-generation-v1"


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
    mean_dip: float
    mean_dip_dir: float
    fisher_kappa: float
    condition: JointCondition

    @property
    def mean_normal(self) -> Vector3:
        """Derived plane pole in East-North-Up coordinates; not a case input."""
        dip = radians(self.mean_dip)
        dip_dir = radians(self.mean_dip_dir % 360.0)
        return (
            -sin(dip) * sin(dip_dir),
            -sin(dip) * cos(dip_dir),
            cos(dip),
        )


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
    """Joint fields consumed by profile and Q-prime calculations only."""

    joint_id: str
    set_id: int
    condition: JointCondition


@dataclass(frozen=True)
class LineIntersection:
    distance: float
    joint: Union[JointRealization, JointProfileEvidence]


def validate_case(case: CaseSpec) -> None:
    from .geometry import clip_borehole, validate_borehole_tunnel, validate_tunnel

    if not isinstance(case, CaseSpec):
        raise TypeError("case must be a CaseSpec")
    if not case.case_id.strip():
        raise ValueError("case_id must not be empty")

    domain = case.domain
    if len(domain.cell_counts) != 3 or len(domain.grid_spacing) != 3:
        raise ValueError("domain requires three cell counts and grid spacings")
    for count in domain.cell_counts:
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("domain cell counts must be positive integers")
    if not all(isfinite(spacing) and spacing > 0.0 for spacing in domain.grid_spacing):
        raise ValueError("domain grid spacings must be finite and positive")
    if not isfinite(domain.jn) or domain.jn <= 0.0:
        raise ValueError("domain Jn must be finite and positive")

    joint_set_ids: set[int] = set()
    for joint_set in case.joint_sets:
        if isinstance(joint_set.set_id, bool) or not isinstance(joint_set.set_id, int):
            raise ValueError("joint set IDs must be integers")
        if joint_set.set_id in joint_set_ids:
            raise ValueError(f"duplicate joint set ID: {joint_set.set_id}")
        joint_set_ids.add(joint_set.set_id)
        if not joint_set.name.strip():
            raise ValueError("joint set name must not be empty")
        if joint_set.density_type not in ("P32", "spacing"):
            raise ValueError("joint set density_type must be P32 or spacing")
        if not isfinite(joint_set.density_value) or joint_set.density_value <= 0.0:
            raise ValueError("joint set density_value must be finite and positive")
        if not isfinite(joint_set.size_alpha) or joint_set.size_alpha <= 0.0:
            raise ValueError("joint set size_alpha must be finite and positive")
        if (
            not isfinite(joint_set.size_r_min)
            or not isfinite(joint_set.size_r_max)
            or joint_set.size_r_min <= 0.0
            or joint_set.size_r_max < joint_set.size_r_min
        ):
            raise ValueError("joint set radii must satisfy 0 < size_r_min <= size_r_max")
        if not isfinite(joint_set.mean_dip) or not 0.0 <= joint_set.mean_dip <= 90.0:
            raise ValueError("joint set mean_dip must be finite and between 0 and 90 degrees")
        if (
            not isfinite(joint_set.mean_dip_dir)
            or not 0.0 <= joint_set.mean_dip_dir <= 360.0
        ):
            raise ValueError(
                "joint set mean_dip_dir must be finite and between 0 and 360 degrees"
            )
        if not isfinite(joint_set.fisher_kappa) or joint_set.fisher_kappa < 0.0:
            raise ValueError("joint set fisher_kappa must be finite and non-negative")
        condition = joint_set.condition
        if (
            not isinstance(condition, JointCondition)
            or not isinstance(condition.jr_category, BartonCategory)
            or not isinstance(condition.ja_category, BartonCategory)
            or condition.jr_category.parameter != "Jr"
            or condition.ja_category.parameter != "Ja"
        ):
            raise ValueError("joint set must have a valid Jr/Ja condition")

    validate_tunnel(case.tunnel)
    borehole_ids: set[str] = set()
    for borehole in case.boreholes:
        if not isinstance(borehole, BoreholeSpec):
            raise TypeError("case boreholes must contain BoreholeSpec values")
        if not borehole.borehole_id.strip():
            raise ValueError("borehole_id must not be empty")
        if borehole.borehole_id in borehole_ids:
            raise ValueError(f"duplicate borehole ID: {borehole.borehole_id}")
        borehole_ids.add(borehole.borehole_id)
        clipped = clip_borehole(borehole, domain)
        if clipped is None:
            raise ValueError(f"borehole {borehole.borehole_id} has no domain support")
        if borehole.purpose == "face_comparison":
            validate_borehole_tunnel(borehole, case.tunnel)


def identify_signature(case: CaseSpec) -> Signature:
    validate_case(case)
    joint_sets = [
        {
            "set_id": joint_set.set_id,
            "density_type": joint_set.density_type,
            "density_value": joint_set.density_value,
            "size_alpha": joint_set.size_alpha,
            "size_r_min": joint_set.size_r_min,
            "size_r_max": joint_set.size_r_max,
            "mean_normal": joint_set.mean_normal,
            "fisher_kappa": joint_set.fisher_kappa,
            "condition": {
                "jr": [
                    joint_set.condition.jr_category.lower_value,
                    joint_set.condition.jr_category.upper_value,
                ],
                "ja": [
                    joint_set.condition.ja_category.lower_value,
                    joint_set.condition.ja_category.upper_value,
                ],
            },
        }
        for joint_set in sorted(case.joint_sets, key=lambda item: item.set_id)
    ]
    payload = json.dumps(
        {"joint_sets": joint_sets},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    signature_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return Signature(signature_id, case)


def dip_direction_from_mean_normal(
    normal: Vector3,
    fallback_dip_dir: float = 0.0,
) -> tuple[float, float]:
    """Convert a plane normal to canonical dip/dip-direction angles."""
    if len(normal) != 3 or not all(isfinite(component) for component in normal):
        raise ValueError("normal must contain three finite values")
    magnitude = hypot(*normal)
    if magnitude == 0.0:
        raise ValueError("normal must be non-zero")

    x, y, z = (component / magnitude for component in normal)
    if z < 0.0:
        x, y, z = -x, -y, -z
    dip = degrees(acos(max(-1.0, min(1.0, z))))
    if hypot(x, y) <= 1e-12:
        dip_dir = fallback_dip_dir % 360.0
    else:
        dip_dir = degrees(atan2(-x, -y)) % 360.0
    return dip, dip_dir


def identify_domain(
    signature: Signature,
    seed: int,
    generator_version: str = GENERATOR_VERSION,
) -> str:
    if not isinstance(signature, Signature):
        raise TypeError("signature must be a Signature")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if not isinstance(generator_version, str) or not generator_version.strip():
        raise ValueError("generator_version must be a non-empty string")
    validate_case(signature.case)
    expected_signature = identify_signature(signature.case).signature_id
    if signature.signature_id != expected_signature:
        raise ValueError("signature_id does not match its case generation features")

    domain = signature.case.domain
    payload = json.dumps(
        {
            "signature_id": signature.signature_id,
            "seed": seed,
            "domain": {
                "cell_counts": domain.cell_counts,
                "grid_spacing": domain.grid_spacing,
                "jn": domain.jn,
            },
            "generator_version": generator_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
