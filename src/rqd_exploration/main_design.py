"""Finite deterministic candidate proposals and generation-free expected costs."""

from dataclasses import asdict, dataclass, replace
from math import isfinite, prod

import numpy as np
from src.euler_campaign.generation import (
    FIXED_DOMAIN, LEGACY, generation_mode_for_version, radius_bin_plan,
)

from .config import EXECUTABLE_JN_SET_COUNTS
from .design import generate_lhs_design
from .fingerprint import (
    ExecutionGeometry, ExecutionJointSet, ExecutionMeasurements, ExecutionRuntime,
    ExecutionSnapshot, fingerprint_snapshot,
)
from .main_policy import AXES


def snapshot_from_dict(value):
    geometry = dict(value["geometry"])
    for key in ("domain_size_m", "grid_spacing_m", "borehole_start_m",
                "borehole_direction_enu"):
        geometry[key] = tuple(geometry[key])
    geometry["tunnel_vertices_m"] = tuple(tuple(v) for v in geometry["tunnel_vertices_m"])
    runtime = dict(value["runtime"])
    runtime["device_runtime"] = tuple(runtime["device_runtime"])
    return ExecutionSnapshot(
        ExecutionGeometry(**geometry), value["fixed_jn"],
        tuple(ExecutionJointSet(**s) for s in value["joint_sets"]),
        value["realization_seed"], ExecutionMeasurements(**value["measurements"]),
        ExecutionRuntime(**runtime))


def input_identity(snapshot):
    payload = asdict(snapshot)
    payload.pop("realization_seed")
    payload.pop("runtime")
    mode = generation_mode_for_version(snapshot.runtime.generator_version)
    if mode != LEGACY:
        payload["generation_mode"] = mode
    payload["joint_sets"] = [{k: v for k, v in asdict(s).items() if k != "joint_set_id"}
                             for s in sorted(snapshot.joint_sets, key=lambda s: s.joint_set_id)]
    return fingerprint_snapshot(payload).sha256_hex


def validate_generating_input(snapshot):
    count = EXECUTABLE_JN_SET_COUNTS.get(snapshot.fixed_jn)
    if count is None or len(snapshot.joint_sets) != count:
        raise ValueError("Jn/set count mismatch")
    if len({s.joint_set_id for s in snapshot.joint_sets}) != count:
        raise ValueError("joint-set identities must be unique")
    for s in snapshot.joint_sets:
        for name, _, _, lower, upper, inclusive in AXES:
            value = getattr(s, name)
            if (not isfinite(value) or not lower <= value <= upper
                or (not inclusive and value == upper)):
                raise ValueError(f"outside bounds: {s.joint_set_id}/{name}")
        if s.size_r_min_m > s.size_r_max_m:
            raise ValueError(f"radius order violation: {s.joint_set_id}")
        if (not 2.5 <= s.size_alpha <= 4 or not 0 <= s.fisher_kappa <= 50):
            raise ValueError("outside alpha/kappa bounds")


def expected_joint_counts(snapshot):
    from src.euler_campaign.dfn import _expected_joint_area
    mode = generation_mode_for_version(snapshot.runtime.generator_version)
    if mode != LEGACY:
        validate_generating_input(snapshot)
    volume = prod(snapshot.geometry.domain_size_m)
    if not isfinite(volume) or volume <= 0:
        raise ValueError("domain volume must be positive and finite")
    result = {}
    for s in snapshot.joint_sets:
        if not (isfinite(s.p32_m2_per_m3) and s.p32_m2_per_m3 > 0
                and 0 < s.size_r_min_m <= s.size_r_max_m):
            raise ValueError("invalid physical P32/radii")
        result[s.joint_set_id] = (
            s.p32_m2_per_m3 * volume / _expected_joint_area(
                s.size_alpha, s.size_r_min_m, s.size_r_max_m)
            if mode in (LEGACY, FIXED_DOMAIN) else
            sum(b.expected_count for b in radius_bin_plan(s.size_alpha, s.size_r_min_m,
                s.size_r_max_m, s.p32_m2_per_m3, snapshot.geometry.domain_size_m)))
    if not all(isfinite(v) and v >= 0 for v in result.values()):
        raise ValueError("nonfinite expected joint count")
    return result


@dataclass(frozen=True)
class Candidate:
    input_id: str
    snapshot: ExecutionSnapshot
    role: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProposalBatch:
    candidates: tuple[Candidate, ...]
    proposals: tuple[dict, ...]
    next_cursor: int
    rng_state: dict


def propose_candidates(reference, template, *, round_index, cursor, rng_seed,
                       seen=(), stream_key=0, lhs_count=2, runtime=None, lhs_only=False):
    validate_generating_input(reference)
    choices = [(i, axis) for i in range(len(reference.joint_sets)) for axis in AXES]
    chosen = [choices[(cursor + i) % len(choices)] for i in range(3)]
    raw = []
    for set_index, axis in chosen[:2]:
        for size, step in (("small", axis[1]), ("large", axis[2])):
            for sign in (-1, 1):
                raw.append(("single_axis", ((set_index, axis[0], sign * step),),
                            f"{set_index}/{axis[0]}/{size}/{sign}"))
    for width in (2, 3):
        changes = tuple((i, axis[0], axis[1] * (1 if (round_index + n) % 2 else -1))
                        for n, (i, axis) in enumerate(chosen[:width]))
        raw.append(("multi_axis", changes, f"{width}-axis"))
    proposals, candidates = [], {}
    def register(snapshot, role, reason):
        if runtime is not None:
            snapshot = replace(snapshot, runtime=runtime)
        proposal = {"role": role, "reason": reason, "reference": input_identity(reference)}
        try:
            validate_generating_input(snapshot)
        except ValueError as error:
            proposals.append({**proposal, "status": "skipped", "skip_reason": str(error)})
            return
        identity = input_identity(snapshot)
        proposal["input_id"] = identity
        if identity in candidates:
            old = candidates[identity]
            candidates[identity] = replace(old, reasons=old.reasons + (reason,))
            proposals.append({**proposal, "status": "merged", "skip_reason": "duplicate proposal"})
        elif identity in seen or identity == input_identity(reference):
            proposals.append({**proposal, "status": "skipped", "skip_reason": "already investigated input"})
        else:
            candidates[identity] = Candidate(identity, snapshot, role, (reason,))
            proposals.append({**proposal, "status": "eligible"})
    for role, changes, reason in (() if lhs_only else raw):
        sets = list(reference.joint_sets)
        for index, name, step in changes:
            sets[index] = replace(sets[index], **{name: getattr(sets[index], name) + step})
        register(replace(reference, joint_sets=tuple(sets)), role, reason)
    sequence = np.random.SeedSequence(
        rng_seed, spawn_key=(round_index, int(reference.fixed_jn), stream_key, 3))
    stream_seed = int(sequence.generate_state(1)[0])
    lhs = generate_lhs_design(replace(template, design_seed=stream_seed, sample_count=lhs_count))
    for sample in lhs.samples:
        register(replace(reference, joint_sets=sample.joint_sets), "lhs",
                 f"lhs/round={round_index}/stream={stream_seed}/sample={sample.sample_index}")
    return ProposalBatch(tuple(candidates.values()), tuple(proposals),
                         (cursor + 2) % len(choices),
                         {"scheme": "SeedSequence(round,Jn,condition,role=3)/PCG64",
                          "entropy": rng_seed, "spawn_key": list(sequence.spawn_key),
                          "design_seed": stream_seed})
