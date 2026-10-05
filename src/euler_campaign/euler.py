"""Probe-based signature updates with bounded, normalized gradient ascent.

Feature IDs use ``joint_sets.<set_id>.<field>``. Orientation IDs use
``joint_sets.<set_id>.orientation_beta@<borehole_id>``.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from math import asin, cos, degrees, exp, isfinite, log, log1p, radians, sin, sqrt
from numbers import Real
from typing import Literal, Protocol

from .coverage import CoverageResult, PairedScore, parent_gaps
from .models import (
    BoreholeSpec,
    FeatureBlock,
    JointSetSpec,
    Signature,
    Vector3,
    dip_direction_from_mean_normal,
    identify_signature,
    validate_case,
)


@dataclass(frozen=True)
class FeatureBound:
    feature_id: str
    lower: float
    upper: float


@dataclass(frozen=True)
class ProbePair:
    feature_id: str
    block: FeatureBlock
    parent: Signature
    minus: Signature | None
    plus: Signature | None
    minus_coordinate: float
    plus_coordinate: float
    blocked_reason: str | None


@dataclass(frozen=True)
class ProbeEvidence:
    probe: ProbePair
    seed: int
    parent_coverage: CoverageResult
    minus_score: PairedScore | None
    plus_score: PairedScore | None


@dataclass(frozen=True)
class Sensitivity:
    feature_id: str
    block: FeatureBlock
    derivative: float | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class UpdateProposal:
    parent: Signature
    candidate: Signature | None
    block: FeatureBlock
    sensitivities: tuple[Sensitivity, ...]
    bound_limited_features: tuple[str, ...]
    status: Literal["candidate", "bound_limited", "no_direction", "decision_required"]
    reason: str


@dataclass(frozen=True)
class RepeatabilityResult:
    proposal: UpdateProposal
    scores: tuple[PairedScore, PairedScore, PairedScore]
    accepted: bool
    reason: str


class UpdateRule(Protocol):
    @property
    def rule_id(self) -> str:
        """Stable ID including algorithm version and any configured parameters."""
        ...

    def propose(
        self,
        parent: Signature,
        block: FeatureBlock,
        sensitivities: tuple[Sensitivity, ...],
        bounds: tuple[FeatureBound, ...],
    ) -> UpdateProposal: ...


class NormalizedGradientUpdateRule:
    """Scale sensitivities so the largest coordinate step reaches its fixed cap."""

    _LOG_COORDINATE_STEP_CAP = 0.05
    _ORIENTATION_STEP_CAP = 5.0

    @property
    def rule_id(self) -> str:
        return "normalized-gradient-v1"

    def propose(
        self,
        parent: Signature,
        block: FeatureBlock,
        sensitivities: tuple[Sensitivity, ...],
        bounds: tuple[FeatureBound, ...],
    ) -> UpdateProposal:
        if block not in _FEATURE_BLOCKS:
            raise ValueError(f"unsupported feature block: {block}")
        _validate_signature(parent, "parent")
        bound_map = _bound_map(bounds)
        active: list[
            tuple[
                Sensitivity,
                FeatureBound,
                tuple[int, str, str | None, FeatureBlock],
                float,
            ]
        ] = []
        seen: set[str] = set()
        for sensitivity in sensitivities:
            if not isinstance(sensitivity, Sensitivity):
                raise TypeError("sensitivities must contain Sensitivity values")
            if sensitivity.feature_id in seen:
                raise ValueError(f"duplicate sensitivity: {sensitivity.feature_id}")
            seen.add(sensitivity.feature_id)
            if sensitivity.feature_id not in bound_map:
                raise ValueError(f"missing feature bound: {sensitivity.feature_id}")
            bound, descriptor = bound_map[sensitivity.feature_id]
            if sensitivity.block != block or descriptor[3] != block:
                raise ValueError("all sensitivities and bounds must belong to the active block")
            if sensitivity.derivative is None:
                continue
            if not isfinite(sensitivity.derivative):
                raise ValueError("sensitivity derivatives must be finite")
            if sensitivity.derivative == 0.0:
                continue
            coordinate = _feature_coordinate(parent, descriptor)
            if descriptor[1] == "orientation_beta":
                within_bounds = bound.lower <= coordinate <= bound.upper
            else:
                within_bounds = log(bound.lower) <= coordinate <= log(bound.upper)
            if not within_bounds:
                raise ValueError(f"parent feature is outside bounds: {bound.feature_id}")
            active.append((sensitivity, bound, descriptor, coordinate))

        if not active:
            return UpdateProposal(
                parent, None, block, sensitivities, (), "no_direction",
                "no finite non-zero sensitivity is available in the active block",
            )

        orientation_features_by_set: dict[int, set[str]] = {}
        for sensitivity, _, descriptor, _ in active:
            if descriptor[1] == "orientation_beta":
                orientation_features_by_set.setdefault(descriptor[0], set()).add(
                    sensitivity.feature_id
                )
        if any(len(features) > 1 for features in orientation_features_by_set.values()):
            return UpdateProposal(
                parent, None, block, sensitivities, (), "decision_required",
                "update one borehole-axis orientation probe per joint set at a time",
            )

        max_sensitivity = max(abs(item[0].derivative) for item in active)
        updates: dict[str, float] = {}
        bound_limited: list[str] = []
        for sensitivity, bound, descriptor, coordinate in active:
            cap = (
                self._ORIENTATION_STEP_CAP
                if descriptor[1] == "orientation_beta"
                else self._LOG_COORDINATE_STEP_CAP
            )
            requested = coordinate + cap * sensitivity.derivative / max_sensitivity
            if descriptor[1] == "orientation_beta":
                bounded = min(max(requested, bound.lower), bound.upper)
                value = bounded
            else:
                lower_coordinate = log(bound.lower)
                upper_coordinate = log(bound.upper)
                bounded = min(max(requested, lower_coordinate), upper_coordinate)
                value = min(max(exp(bounded), bound.lower), bound.upper)
            if abs(bounded - coordinate) <= _VECTOR_EPSILON:
                bound_limited.append(sensitivity.feature_id)
            else:
                updates[sensitivity.feature_id] = value

        size_updates_by_set: dict[int, dict[str, float]] = {}
        for feature_id, value in updates.items():
            descriptor = bound_map[feature_id][1]
            if descriptor[1] in ("size_r_min", "size_r_max"):
                size_updates_by_set.setdefault(descriptor[0], {})[descriptor[1]] = value
        for set_id, values in size_updates_by_set.items():
            joint_set = _joint_set(parent, set_id)
            new_min = values.get("size_r_min", joint_set.size_r_min)
            new_max = values.get("size_r_max", joint_set.size_r_max)
            if new_min >= new_max:
                for field_name in values:
                    feature_id = f"joint_sets.{set_id}.{field_name}"
                    bound_limited.append(feature_id)
                    updates.pop(feature_id, None)

        for feature_id, value in tuple(updates.items()):
            descriptor = bound_map[feature_id][1]
            if descriptor[1] != "orientation_beta":
                continue
            joint_set = _joint_set(parent, descriptor[0])
            borehole_id = descriptor[2]
            if borehole_id is None:
                raise ValueError("orientation feature requires a borehole ID")
            borehole = _orientation_borehole(parent, borehole_id)
            try:
                _rotate_normal_to_beta(joint_set.mean_normal, borehole.direction, value)
            except ValueError:
                bound_limited.append(feature_id)
                updates.pop(feature_id, None)

        if not updates:
            return UpdateProposal(
                parent,
                None,
                block,
                sensitivities,
                tuple(sorted(set(bound_limited))),
                "bound_limited" if bound_limited else "no_direction",
                "all proposed feature changes were blocked by bounds or physical constraints",
            )

        candidate = _signature_with_updates(parent, updates, bound_map)
        return UpdateProposal(
            parent,
            candidate,
            block,
            sensitivities,
            tuple(sorted(set(bound_limited))),
            "candidate",
            "normalized sensitivity ascent projected to physical bounds",
        )


class GapSeekingNormalizedGradientUpdateRule(NormalizedGradientUpdateRule):
    """Use 10%/10-degree steps and require new-bin verification acceptance."""

    _LOG_COORDINATE_STEP_CAP = 0.10
    _ORIENTATION_STEP_CAP = 10.0

    @property
    def rule_id(self) -> str:
        return "normalized-gradient-gap-v2"


_FEATURE_BLOCKS: tuple[FeatureBlock, ...] = ("density", "size", "orientation")
_LOG_PROBE_STEP = log1p(0.1)
_ANGLE_PROBE_STEP = 5.0
_VECTOR_EPSILON = 1e-12


def _feature_descriptor(feature_id: str) -> tuple[int, str, str | None, FeatureBlock]:
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("feature_id must be a non-empty string")
    parts = feature_id.split(".", 2)
    if len(parts) != 3 or parts[0] != "joint_sets":
        raise ValueError(f"invalid Euler feature_id: {feature_id}")
    try:
        set_id = int(parts[1])
    except ValueError as error:
        raise ValueError(f"invalid joint set ID in feature_id: {feature_id}") from error
    if str(set_id) != parts[1]:
        raise ValueError(f"joint set ID in feature_id must be canonical: {feature_id}")

    field = parts[2]
    if field == "density_value":
        return set_id, field, None, "density"
    if field in ("size_r_min", "size_r_max"):
        return set_id, field, None, "size"
    orientation_prefix = "orientation_beta@"
    if field.startswith(orientation_prefix) and field[len(orientation_prefix):]:
        return set_id, "orientation_beta", field[len(orientation_prefix):], "orientation"
    raise ValueError(f"unsupported Euler feature_id: {feature_id}")


def _bound_map(
    bounds: tuple[FeatureBound, ...],
) -> dict[str, tuple[FeatureBound, tuple[int, str, str | None, FeatureBlock]]]:
    if not isinstance(bounds, tuple):
        raise TypeError("bounds must be a tuple")
    result: dict[
        str, tuple[FeatureBound, tuple[int, str, str | None, FeatureBlock]]
    ] = {}
    for bound in bounds:
        if not isinstance(bound, FeatureBound):
            raise TypeError("bounds must contain FeatureBound values")
        if (
            isinstance(bound.lower, bool)
            or isinstance(bound.upper, bool)
            or not isinstance(bound.lower, Real)
            or not isinstance(bound.upper, Real)
            or not isfinite(bound.lower)
            or not isfinite(bound.upper)
            or bound.lower >= bound.upper
        ):
            raise ValueError(f"invalid bounds for feature: {bound.feature_id}")
        descriptor = _feature_descriptor(bound.feature_id)
        _, name, _, block = descriptor
        if block in ("density", "size") and bound.lower <= 0.0:
            raise ValueError(f"positive feature bounds must be greater than zero: {bound.feature_id}")
        if name == "orientation_beta" and not 0.0 <= bound.lower < bound.upper <= 90.0:
            raise ValueError(f"orientation beta bounds must lie within [0, 90]: {bound.feature_id}")
        if bound.feature_id in result:
            raise ValueError(f"duplicate feature bound: {bound.feature_id}")
        result[bound.feature_id] = (bound, descriptor)
    return result


def _joint_set(signature: Signature, set_id: int) -> JointSetSpec:
    matches = [item for item in signature.case.joint_sets if item.set_id == set_id]
    if len(matches) != 1:
        raise ValueError(f"signature must contain exactly one joint set with ID {set_id}")
    return matches[0]


def _validate_signature(signature: Signature, name: str) -> None:
    if not isinstance(signature, Signature):
        raise TypeError(f"{name} must be a Signature")
    validate_case(signature.case)
    if identify_signature(signature.case).signature_id != signature.signature_id:
        raise ValueError(f"{name} signature_id does not match its case")


def _unit_vector(vector: Vector3, name: str) -> Vector3:
    if (
        not isinstance(vector, tuple)
        or len(vector) != 3
        or any(
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not isfinite(value)
            for value in vector
        )
    ):
        raise ValueError(f"{name} must contain three finite coordinates")
    magnitude = sqrt(sum(value * value for value in vector))
    if not isfinite(magnitude) or magnitude <= _VECTOR_EPSILON:
        raise ValueError(f"{name} must be non-zero")
    return (
        vector[0] / magnitude,
        vector[1] / magnitude,
        vector[2] / magnitude,
    )


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right))


def _orientation_borehole(signature: Signature, borehole_id: str) -> BoreholeSpec:
    matches = [
        borehole
        for borehole in signature.case.boreholes
        if borehole.borehole_id == borehole_id
    ]
    if len(matches) != 1:
        raise ValueError(f"signature must contain exactly one borehole named {borehole_id!r}")
    return matches[0]


def _feature_coordinate(
    signature: Signature,
    descriptor: tuple[int, str, str | None, FeatureBlock],
) -> float:
    set_id, name, borehole_id, _ = descriptor
    joint_set = _joint_set(signature, set_id)
    if name == "orientation_beta":
        if borehole_id is None:
            raise ValueError("orientation feature requires a borehole ID")
        borehole = _orientation_borehole(signature, borehole_id)
        return orientation_beta(joint_set.mean_normal, borehole.direction)
    value = getattr(joint_set, name)
    if isinstance(value, bool) or not isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return log(value)


def _rotate_normal_to_beta(normal: Vector3, direction: Vector3, beta: float) -> Vector3:
    unit_normal = _unit_vector(normal, "normal")
    unit_direction = _unit_vector(direction, "borehole_direction")
    dot = max(-1.0, min(1.0, _dot(unit_normal, unit_direction)))
    projection = tuple(
        unit_normal[index] - dot * unit_direction[index]
        for index in range(3)
    )
    projection_magnitude = sqrt(sum(value * value for value in projection))
    if projection_magnitude <= _VECTOR_EPSILON:
        if abs(beta - 90.0) <= _VECTOR_EPSILON:
            return unit_normal
        raise ValueError("orientation direction is undefined for a normal parallel to the borehole")

    perpendicular = tuple(value / projection_magnitude for value in projection)
    sign = -1.0 if dot < 0.0 else 1.0
    beta_radians = radians(beta)
    updated = tuple(
        sign * sin(beta_radians) * unit_direction[index]
        + cos(beta_radians) * perpendicular[index]
        for index in range(3)
    )
    return _unit_vector(updated, "updated normal")


def _signature_with_feature(
    parent: Signature,
    descriptor: tuple[int, str, str | None, FeatureBlock],
    value: float,
) -> Signature:
    set_id, name, borehole_id, _ = descriptor
    joint_sets = list(parent.case.joint_sets)
    index = next(
        index for index, joint_set in enumerate(joint_sets)
        if joint_set.set_id == set_id
    )
    joint_set = joint_sets[index]
    if name == "orientation_beta":
        if borehole_id is None:
            raise ValueError("orientation feature requires a borehole ID")
        borehole = _orientation_borehole(parent, borehole_id)
        normal = _rotate_normal_to_beta(
            joint_set.mean_normal,
            borehole.direction,
            value,
        )
        mean_dip, mean_dip_dir = dip_direction_from_mean_normal(
            normal,
            joint_set.mean_dip_dir,
        )
        joint_sets[index] = replace(
            joint_set,
            mean_dip=mean_dip,
            mean_dip_dir=mean_dip_dir,
        )
    else:
        joint_sets[index] = replace(joint_set, **{name: value})
    case = replace(parent.case, joint_sets=tuple(joint_sets))
    return identify_signature(case)


def _signature_with_updates(
    parent: Signature,
    updates: dict[str, float],
    bounds: dict[
        str, tuple[FeatureBound, tuple[int, str, str | None, FeatureBlock]]
    ],
) -> Signature:
    values_by_set: dict[int, dict[str, tuple[float, str | None]]] = {}
    for feature_id, value in updates.items():
        if feature_id not in bounds:
            raise ValueError(f"missing feature bound: {feature_id}")
        _, descriptor = bounds[feature_id]
        set_id, name, borehole_id, _ = descriptor
        values_by_set.setdefault(set_id, {})[name] = (value, borehole_id)

    joint_sets: list[JointSetSpec] = []
    for original in parent.case.joint_sets:
        values = values_by_set.get(original.set_id, {})
        changes: dict[str, object] = {}
        if "density_value" in values:
            changes["density_value"] = values["density_value"][0]
        if "size_r_min" in values:
            changes["size_r_min"] = values["size_r_min"][0]
        if "size_r_max" in values:
            changes["size_r_max"] = values["size_r_max"][0]
        if "orientation_beta" in values:
            beta, borehole_id = values["orientation_beta"]
            if borehole_id is None:
                raise ValueError("orientation feature requires a borehole ID")
            borehole = _orientation_borehole(parent, borehole_id)
            normal = _rotate_normal_to_beta(
                original.mean_normal,
                borehole.direction,
                beta,
            )
            mean_dip, mean_dip_dir = dip_direction_from_mean_normal(
                normal,
                original.mean_dip_dir,
            )
            changes["mean_dip"] = mean_dip
            changes["mean_dip_dir"] = mean_dip_dir
        joint_sets.append(replace(original, **changes))
    return identify_signature(replace(parent.case, joint_sets=tuple(joint_sets)))


def _candidate_at_probe_coordinate(
    parent: Signature,
    bound: FeatureBound,
    descriptor: tuple[int, str, str | None, FeatureBlock],
    coordinate: float,
) -> Signature | None:
    set_id, name, _, _ = descriptor
    joint_set = _joint_set(parent, set_id)
    if name == "orientation_beta":
        value = coordinate
    else:
        value = exp(coordinate)
    if value < bound.lower or value > bound.upper or not isfinite(value):
        return None
    if name == "size_r_min" and value >= joint_set.size_r_max:
        return None
    if name == "size_r_max" and value <= joint_set.size_r_min:
        return None
    if name == "orientation_beta":
        try:
            return _signature_with_feature(parent, descriptor, value)
        except ValueError:
            return None
    return _signature_with_feature(parent, descriptor, value)


def next_feature_block(block: FeatureBlock) -> FeatureBlock:
    if block not in _FEATURE_BLOCKS:
        raise ValueError(f"unsupported feature block: {block}")
    return _FEATURE_BLOCKS[(_FEATURE_BLOCKS.index(block) + 1) % len(_FEATURE_BLOCKS)]


def orientation_beta(normal: Vector3, borehole_direction: Vector3) -> float:
    unit_normal = _unit_vector(normal, "normal")
    unit_direction = _unit_vector(borehole_direction, "borehole_direction")
    return degrees(asin(min(1.0, abs(_dot(unit_normal, unit_direction)))))


def build_probes(
    parent: Signature,
    block: FeatureBlock,
    bounds: tuple[FeatureBound, ...],
) -> tuple[ProbePair, ...]:
    if block not in _FEATURE_BLOCKS:
        raise ValueError(f"unsupported feature block: {block}")
    _validate_signature(parent, "parent")
    all_bounds = _bound_map(bounds)
    selected = sorted(
        (
            pair for pair in all_bounds.values()
            if pair[1][3] == block
        ),
        key=lambda pair: pair[0].feature_id,
    )
    probes: list[ProbePair] = []
    for bound, descriptor in selected:
        current = _feature_coordinate(parent, descriptor)
        coordinate = current if descriptor[1] == "orientation_beta" else log(
            getattr(_joint_set(parent, descriptor[0]), descriptor[1])
        )
        if descriptor[1] == "orientation_beta":
            if current < bound.lower or current > bound.upper:
                raise ValueError(f"parent feature is outside bounds: {bound.feature_id}")
            delta = _ANGLE_PROBE_STEP
        else:
            physical_value = getattr(_joint_set(parent, descriptor[0]), descriptor[1])
            if physical_value < bound.lower or physical_value > bound.upper:
                raise ValueError(f"parent feature is outside bounds: {bound.feature_id}")
            delta = _LOG_PROBE_STEP

        lower_coordinate = (
            bound.lower
            if descriptor[1] == "orientation_beta"
            else log(bound.lower)
        )
        upper_coordinate = (
            bound.upper
            if descriptor[1] == "orientation_beta"
            else log(bound.upper)
        )
        minus_coordinate = max(lower_coordinate, coordinate - delta)
        plus_coordinate = min(upper_coordinate, coordinate + delta)
        minus = (
            None
            if minus_coordinate >= coordinate
            else _candidate_at_probe_coordinate(
                parent, bound, descriptor, minus_coordinate,
            )
        )
        plus = (
            None
            if plus_coordinate <= coordinate
            else _candidate_at_probe_coordinate(
                parent, bound, descriptor, plus_coordinate,
            )
        )
        if minus is None:
            minus_coordinate = coordinate
        if plus is None:
            plus_coordinate = coordinate
        if minus is None and plus is None:
            reason = "both probe directions are blocked by bounds or physical constraints"
        elif minus is None or plus is None:
            reason = "one probe direction is blocked by bounds or physical constraints"
        else:
            reason = None
        probes.append(
            ProbePair(
                feature_id=bound.feature_id,
                block=block,
                parent=parent,
                minus=minus,
                plus=plus,
                minus_coordinate=minus_coordinate,
                plus_coordinate=plus_coordinate,
                blocked_reason=reason,
            )
        )
    if not probes:
        raise ValueError(f"no feature bounds were supplied for the {block} block")
    return tuple(probes)


def _validate_paired_score(
    score: PairedScore,
    *,
    parent: Signature,
    candidate: Signature,
    seed: int,
    grid_id: str,
    gaps: frozenset[int],
) -> None:
    if not isinstance(score, PairedScore):
        raise TypeError("probe scores must be PairedScore values")
    if (
        score.seed != seed
        or score.parent_signature_id != parent.signature_id
        or score.candidate_signature_id != candidate.signature_id
        or score.grid_id != grid_id
        or score.parent_gap_bins != gaps
    ):
        raise ValueError("paired score does not match its probe evidence")
    if not isfinite(score.delta_score):
        raise ValueError("paired score must be finite")


def estimate_sensitivity(evidence: ProbeEvidence) -> Sensitivity:
    if not isinstance(evidence, ProbeEvidence):
        raise TypeError("evidence must be a ProbeEvidence value")
    probe = evidence.probe
    if not isinstance(probe, ProbePair):
        raise TypeError("probe evidence must contain a ProbePair")
    _validate_signature(probe.parent, "probe parent")
    if probe.block not in _FEATURE_BLOCKS:
        raise ValueError("probe has an unsupported feature block")
    if isinstance(evidence.seed, bool) or not isinstance(evidence.seed, int) or evidence.seed < 0:
        raise ValueError("probe seed must be a non-negative integer")
    if evidence.seed != evidence.parent_coverage.seed:
        raise ValueError("probe and parent coverage must use the same seed")
    if evidence.parent_coverage.signature_id != probe.parent.signature_id:
        raise ValueError("parent coverage must match the probe parent")
    gaps = parent_gaps(evidence.parent_coverage)

    bound_descriptor = _feature_descriptor(probe.feature_id)
    if bound_descriptor[3] != probe.block:
        raise ValueError("probe feature does not belong to its declared block")
    parent_coordinate = _feature_coordinate(probe.parent, bound_descriptor)
    minus_score = evidence.minus_score
    plus_score = evidence.plus_score
    if probe.minus is None and minus_score is not None:
        raise ValueError("minus score supplied without a minus probe")
    if probe.plus is None and plus_score is not None:
        raise ValueError("plus score supplied without a plus probe")
    if (probe.minus is not None and minus_score is None) or (
        probe.plus is not None and plus_score is None
    ):
        return Sensitivity(
            probe.feature_id,
            probe.block,
            None,
            "a valid probe candidate is missing its paired coverage score",
        )

    if minus_score is not None:
        minus_candidate = probe.minus
        if minus_candidate is None:
            raise ValueError("minus score supplied without a minus probe")
        _validate_paired_score(
            minus_score,
            parent=probe.parent,
            candidate=minus_candidate,
            seed=evidence.seed,
            grid_id=evidence.parent_coverage.grid.grid_id,
            gaps=gaps,
        )
    if plus_score is not None:
        plus_candidate = probe.plus
        if plus_candidate is None:
            raise ValueError("plus score supplied without a plus probe")
        _validate_paired_score(
            plus_score,
            parent=probe.parent,
            candidate=plus_candidate,
            seed=evidence.seed,
            grid_id=evidence.parent_coverage.grid.grid_id,
            gaps=gaps,
        )

    if minus_score is not None and plus_score is not None:
        denominator = probe.plus_coordinate - probe.minus_coordinate
        numerator = plus_score.delta_score - minus_score.delta_score
    elif minus_score is not None:
        denominator = probe.minus_coordinate - parent_coordinate
        numerator = minus_score.delta_score
    elif plus_score is not None:
        denominator = probe.plus_coordinate - parent_coordinate
        numerator = plus_score.delta_score
    else:
        return Sensitivity(
            probe.feature_id,
            probe.block,
            None,
            probe.blocked_reason or "no scored probe direction is available",
        )
    if not isfinite(denominator) or abs(denominator) <= _VECTOR_EPSILON:
        return Sensitivity(
            probe.feature_id,
            probe.block,
            None,
            "probe coordinates do not define a finite difference",
        )
    derivative = numerator / denominator
    if not isfinite(derivative):
        raise ValueError("estimated sensitivity must be finite")
    return Sensitivity(probe.feature_id, probe.block, derivative, None)


def _validate_candidate(
    parent: Signature,
    candidate: Signature,
    block: FeatureBlock,
    bounds: dict[str, tuple[FeatureBound, tuple[int, str, str | None, FeatureBlock]]],
    update_feature_ids: frozenset[str],
) -> None:
    if not isinstance(candidate, Signature):
        raise TypeError("candidate must be a Signature")
    validate_case(candidate.case)
    if candidate.signature_id != identify_signature(candidate.case).signature_id:
        raise ValueError("candidate signature_id does not match its case")
    if (
        candidate.case.case_id != parent.case.case_id
        or candidate.case.domain != parent.case.domain
        or candidate.case.boreholes != parent.case.boreholes
        or candidate.case.tunnel != parent.case.tunnel
    ):
        raise ValueError("an update must preserve case, domain, boreholes, and tunnel")
    if len(candidate.case.joint_sets) != len(parent.case.joint_sets):
        raise ValueError("an update must preserve the joint-set collection")
    candidate_sets = {item.set_id: item for item in candidate.case.joint_sets}
    if set(candidate_sets) != {item.set_id for item in parent.case.joint_sets}:
        raise ValueError("an update must preserve joint-set IDs")

    allowed_fields = {
        "density": {"density_value"},
        "size": {"size_r_min", "size_r_max"},
        "orientation": {"mean_dip", "mean_dip_dir"},
    }[block]
    changed = False
    for original in parent.case.joint_sets:
        updated = candidate_sets[original.set_id]
        for item in fields(JointSetSpec):
            name = item.name
            before = getattr(original, name)
            after = getattr(updated, name)
            if before == after:
                continue
            if name not in allowed_fields:
                raise ValueError(f"update changed immutable/out-of-block feature {name!r}")
            changed = True
            if name in {"mean_dip", "mean_dip_dir"}:
                matching_bounds = [
                    (feature_id, bound, descriptor)
                    for feature_id, (bound, descriptor) in bounds.items()
                    if feature_id in update_feature_ids
                    and descriptor[0] == original.set_id
                    and descriptor[1] == "orientation_beta"
                    and descriptor[3] == block
                ]
                if len(matching_bounds) != 1:
                    raise ValueError(
                        "an orientation candidate must update one borehole axis per joint set"
                    )
                _, orientation_bound, orientation_descriptor = matching_bounds[0]
                if not (
                    orientation_bound.lower
                    <= orientation_beta(
                        updated.mean_normal,
                        _orientation_borehole(
                            parent,
                            orientation_descriptor[2]
                            if orientation_descriptor[2] is not None
                            else "",
                        ).direction,
                    )
                    <= orientation_bound.upper
                ):
                    raise ValueError(
                        f"updated orientation for joint set {original.set_id} is outside its bound"
                    )
            else:
                feature_id = f"joint_sets.{original.set_id}.{name}"
                if feature_id not in bounds or feature_id not in update_feature_ids:
                    raise ValueError(f"missing bound for changed feature {feature_id}")
                bound = bounds[feature_id][0]
                if not isfinite(after) or not bound.lower <= after <= bound.upper:
                    raise ValueError(f"updated feature is outside bounds: {feature_id}")
                if name == "size_r_min" and after >= updated.size_r_max:
                    raise ValueError("size update must satisfy size_r_min < size_r_max")
                if name == "size_r_max" and after <= updated.size_r_min:
                    raise ValueError("size update must satisfy size_r_min < size_r_max")
    if not changed:
        raise ValueError("candidate must change at least one feature in the active block")


def propose_update(
    parent: Signature,
    block: FeatureBlock,
    sensitivities: tuple[Sensitivity, ...],
    bounds: tuple[FeatureBound, ...],
    rule: UpdateRule | None = None,
) -> UpdateProposal:
    if block not in _FEATURE_BLOCKS:
        raise ValueError(f"unsupported feature block: {block}")
    _validate_signature(parent, "parent")
    bound_map = _bound_map(bounds)
    if not isinstance(sensitivities, tuple):
        raise TypeError("sensitivities must be a tuple")
    seen: set[str] = set()
    for sensitivity in sensitivities:
        if not isinstance(sensitivity, Sensitivity):
            raise TypeError("sensitivities must contain Sensitivity values")
        if sensitivity.feature_id in seen:
            raise ValueError(f"duplicate sensitivity: {sensitivity.feature_id}")
        seen.add(sensitivity.feature_id)
        if sensitivity.feature_id not in bound_map:
            raise ValueError(f"missing feature bound: {sensitivity.feature_id}")
        if sensitivity.block != block or bound_map[sensitivity.feature_id][1][3] != block:
            raise ValueError("all sensitivities and bounds must belong to the active block")
        if sensitivity.derivative is not None and not isfinite(sensitivity.derivative):
            raise ValueError("sensitivity derivatives must be finite")
    selected_rule = rule if rule is not None else NormalizedGradientUpdateRule()
    if not callable(getattr(selected_rule, "propose", None)):
        raise TypeError("rule must provide a callable propose method")
    proposal = selected_rule.propose(parent, block, sensitivities, bounds)
    if not isinstance(proposal, UpdateProposal):
        raise TypeError("UpdateRule.propose must return an UpdateProposal")
    if proposal.parent != parent or proposal.block != block:
        raise ValueError("update proposal must refer to the supplied parent and block")
    if proposal.sensitivities != sensitivities:
        raise ValueError("update proposal must preserve the supplied sensitivities")
    if not isinstance(proposal.status, str) or proposal.status not in (
        "candidate", "bound_limited", "no_direction", "decision_required",
    ):
        raise ValueError("update proposal has an unsupported status")
    if not isinstance(proposal.reason, str) or not proposal.reason.strip():
        raise ValueError("update proposal reason must not be empty")
    if len(set(proposal.bound_limited_features)) != len(proposal.bound_limited_features):
        raise ValueError("bound-limited features must not contain duplicates")
    for feature_id in proposal.bound_limited_features:
        if feature_id not in bound_map or bound_map[feature_id][1][3] != block:
            raise ValueError("bound-limited features must have bounds in the active block")
    if proposal.status in ("candidate", "bound_limited") and proposal.candidate is not None:
        update_feature_ids = frozenset(
            sensitivity.feature_id
            for sensitivity in sensitivities
            if sensitivity.derivative is not None and sensitivity.derivative != 0.0
        )
        _validate_candidate(
            parent,
            proposal.candidate,
            block,
            bound_map,
            update_feature_ids,
        )
    elif proposal.candidate is not None:
        raise ValueError(f"{proposal.status} proposals must not contain a candidate")
    if proposal.status == "candidate" and proposal.candidate is None:
        raise ValueError("candidate status requires a candidate signature")
    return proposal


def assess_repeatability(
    proposal: UpdateProposal,
    scores: tuple[PairedScore, PairedScore, PairedScore],
    *,
    require_new_bin: bool = False,
) -> RepeatabilityResult:
    if not isinstance(proposal, UpdateProposal):
        raise TypeError("proposal must be an UpdateProposal")
    if not isinstance(require_new_bin, bool):
        raise TypeError("require_new_bin must be a boolean")
    if proposal.candidate is None or proposal.status not in ("candidate", "bound_limited"):
        raise ValueError("repeatability can only assess a proposal with a candidate")
    if not isinstance(scores, tuple) or len(scores) != 3:
        raise ValueError("repeatability requires exactly three paired scores")
    seeds: set[int] = set()
    grid_ids: set[str] = set()
    successes = 0
    for score in scores:
        if not isinstance(score, PairedScore):
            raise TypeError("scores must contain PairedScore values")
        if score.seed in seeds:
            raise ValueError("repeatability scores must use three distinct seeds")
        seeds.add(score.seed)
        if (
            score.parent_signature_id != proposal.parent.signature_id
            or score.candidate_signature_id != proposal.candidate.signature_id
        ):
            raise ValueError("repeatability score does not match the proposal")
        if not isfinite(score.delta_score) or score.seed < 0:
            raise ValueError("repeatability scores require finite values and non-negative seeds")
        if (
            not isfinite(score.new_occupancy_fraction)
            or not 0.0 <= score.new_occupancy_fraction <= 1.0
        ):
            raise ValueError("new occupancy fractions must be finite and between zero and one")
        if score.candidate_observed_count < 0 or score.parent_observed_count < 0:
            raise ValueError("observed-bin counts must be non-negative")
        grid_ids.add(score.grid_id)
        if (
            score.delta_score > 0.0
            and score.candidate_observed_count >= score.parent_observed_count
            and (not require_new_bin or score.new_occupancy_fraction > 0.0)
        ):
            successes += 1
    if len(grid_ids) != 1:
        raise ValueError("repeatability scores must use the same coverage grid")
    accepted = successes >= 2
    rule_description = (
        "new-bin coverage rule" if require_new_bin else "coverage rule"
    )
    reason = (
        f"accepted: {successes}/3 paired seeds met the {rule_description}"
        if accepted
        else f"rejected: only {successes}/3 paired seeds met the {rule_description}"
    )
    return RepeatabilityResult(proposal, scores, accepted, reason)
