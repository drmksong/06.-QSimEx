"""Versioned stationary disk intensity and finite per-radius-bin buffer costs."""

from dataclasses import dataclass
from math import exp, expm1, isfinite, log, prod

import numpy as np

LEGACY = "legacy"
FIXED_DOMAIN = "fixed_domain_centers"
PER_JOINT_BUFFER = "per_joint_buffer_v1"
RADIUS_BINS = 32
FIXED_DOMAIN_GENERATOR_VERSION = "qsimex-fixed-domain-centers-v1"
PER_JOINT_BUFFER_GENERATOR_VERSION = "qsimex-per-joint-buffer-v1-log32"


def generation_mode_for_version(version):
    if version == FIXED_DOMAIN_GENERATOR_VERSION:
        return FIXED_DOMAIN
    if version == PER_JOINT_BUFFER_GENERATOR_VERSION:
        return PER_JOINT_BUFFER
    if "fixed-domain-centers" in version:
        raise ValueError(f"unsupported generation version: {version}")
    if "per-joint-buffer" in version:
        raise ValueError(f"unsupported generation version: {version}")
    return LEGACY


@dataclass(frozen=True)
class RadiusBin:
    lower: float
    upper: float
    probability: float
    expected_count: float


def radius_bin_plan(alpha, radius_min, radius_max, p32, extents):
    from .dfn import _expected_joint_area
    if (not all(isfinite(v) for v in (alpha, radius_min, radius_max, p32, *extents))
        or alpha <= 0 or not 0 < radius_min <= radius_max or p32 < 0
        or len(extents) != 3 or any(v <= 0 for v in extents)):
        raise ValueError("invalid buffered generation parameters")
    mean_area = _expected_joint_area(alpha, radius_min, radius_max)
    if radius_min == radius_max:
        edges = (radius_min, radius_max)
    else:
        edges = np.geomspace(radius_min, radius_max, RADIUS_BINS + 1)
    plan = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        probability = (1. if radius_min == radius_max else
                       exp(-alpha * log(lower / radius_min))
                       * -expm1(-alpha * log(upper / lower))
                       / -expm1(-alpha * log(radius_max / radius_min)))
        count = p32 / mean_area * probability * prod(v + 2 * upper for v in extents)
        if not isfinite(count) or count > 2**63 - 1:
            raise ValueError("buffered expected count is too large")
        plan.append(RadiusBin(float(lower), float(upper), probability, count))
    return tuple(plan)
