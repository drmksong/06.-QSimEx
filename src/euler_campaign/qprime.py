"""Pure Q-prime calculation, without legacy imports or full-Q classification."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from .models import BartonCategory, JointRealization


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


def category_midpoint(category: BartonCategory) -> float:
    return category.lower_value / 2.0 + category.upper_value / 2.0


def select_weakest_joint(
    joints: tuple[JointRealization, ...],
) -> JointRealization | None:
    """Return a minimum-ratio joint; equal ratios retain input order."""
    return min(
        joints,
        key=lambda joint: (
            category_midpoint(joint.condition.jr_category)
            / category_midpoint(joint.condition.ja_category)
        ),
        default=None,
    )


def calculate_qprime(
    raw_rqd: float,
    domain_jn: float,
    joints: tuple[JointRealization, ...],
) -> QPrimeResult:
    """Preserve supplied RQD separately from the calculation convention.

    No intersections use RQD=100, Jr=4, Ja=0.75, not an observed condition.
    Otherwise only the calculation RQD is floored at 10.
    """
    if not isfinite(raw_rqd) or not 0.0 <= raw_rqd <= 100.0:
        raise ValueError("raw_rqd must be finite and between 0 and 100")
    if not isfinite(domain_jn) or domain_jn <= 0.0:
        raise ValueError("domain_jn must be finite and positive")

    selected = select_weakest_joint(joints)
    if selected is None:
        calculation_rqd = 100.0
        jr, ja = 4.0, 0.75
        provenance = QPrimeProvenance(
            source="no_intersection_convention",
            selected_joint_id=None,
            jr_category=None,
            ja_category=None,
            convention_id="qsimex_no_intersection_rqd100_jr4_ja0.75",
        )
    else:
        calculation_rqd = max(raw_rqd, 10.0)
        jr = category_midpoint(selected.condition.jr_category)
        ja = category_midpoint(selected.condition.ja_category)
        provenance = QPrimeProvenance(
            source="intersecting_joint",
            selected_joint_id=selected.joint_id,
            jr_category=selected.condition.jr_category,
            ja_category=selected.condition.ja_category,
            convention_id=None,
        )

    value = (calculation_rqd / domain_jn) * (jr / ja)
    if not isfinite(value) or value <= 0.0:
        raise ValueError("Q-prime calculation is outside the finite positive range")
    return QPrimeResult(
        raw_rqd=raw_rqd,
        calculation_rqd=calculation_rqd,
        jn=domain_jn,
        jr=jr,
        ja=ja,
        value=value,
        provenance=provenance,
    )
