"""Resumable orchestration for bounded Euler signature campaigns."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import uuid4

from .coverage import (
    CoverageGrid,
    CoverageResult,
    audit_simulation,
    parent_gaps,
    score_pair,
    validate_grid,
)
from .euler import (
    FeatureBound,
    GapSeekingNormalizedGradientUpdateRule,
    ProbeEvidence,
    RepeatabilityResult,
    UpdateProposal,
    UpdateRule,
    assess_repeatability,
    build_probes,
    estimate_sensitivity,
    next_feature_block,
    propose_update,
)
from .models import FeatureBlock, Signature, identify_signature
from .ports import Simulator
from .profiles import SimulationResult

if TYPE_CHECKING:
    from .config import CampaignProject

_FEATURE_BLOCKS: tuple[FeatureBlock, ...] = ("density", "size", "orientation")
_TERMINAL_STATUSES = frozenset(("stopped", "decision_required", "failed"))
_CAMPAIGN_TERMINAL_STATUSES = frozenset(
    (
        "coverage_complete",
        "round_budget_exhausted",
        "all_lineages_saturated",
        "decision_required",
        "failed",
    )
)


def _feature_block(feature_id: str) -> FeatureBlock:
    if not isinstance(feature_id, str):
        raise ValueError("feature_id must be a string")
    parts = feature_id.split(".", 2)
    if len(parts) != 3 or parts[0] != "joint_sets":
        raise ValueError(f"invalid Euler feature_id: {feature_id}")
    name = parts[2]
    if name == "density_value":
        return "density"
    if name in ("size_r_min", "size_r_max"):
        return "size"
    if name.startswith("orientation_beta@"):
        return "orientation"
    raise ValueError(f"unsupported Euler feature_id: {feature_id}")


@dataclass(frozen=True)
class CampaignPlan:
    """Immutable execution inputs; update_rule_id identifies the rule configuration."""

    campaign_id: str
    start_signatures: tuple[Signature, ...]
    grid: CoverageGrid
    bounds: tuple[FeatureBound, ...]
    exploration_seed: int
    verification_seeds: tuple[int, int, int]
    update_rule_id: str = "normalized-gradient-v1"

    @property
    def initial_parent(self) -> Signature:
        """First start signature, retained for the single-lineage prototype."""
        return self.start_signatures[0]


@dataclass(frozen=True)
class RoundRecord:
    round_index: int
    block: FeatureBlock
    parent_coverage: CoverageResult
    probes: tuple[ProbeEvidence, ...]
    proposal: UpdateProposal
    verification: RepeatabilityResult | None
    lineage_start_signature_id: str


@dataclass(frozen=True)
class LineageState:
    """Independent resumable progress for one ordered campaign start."""

    start_signature_id: str
    parent: Signature
    next_block: FeatureBlock
    next_round_index: int
    blocked_features: tuple[str, ...]
    status: Literal["ready", "running", "stopped", "decision_required", "failed"]
    reason: str | None


@dataclass(frozen=True)
class CampaignState:
    """Campaign checkpoint with an independent state for every start lineage."""

    campaign_id: str
    plan_fingerprint: str
    active_lineage_index: int
    lineages: tuple[LineageState, ...]
    status: Literal[
        "ready",
        "running",
        "coverage_complete",
        "round_budget_exhausted",
        "all_lineages_saturated",
        "stopped",
        "decision_required",
        "failed",
    ]
    reason: str | None

    @property
    def active_lineage(self) -> LineageState:
        return self.lineages[self.active_lineage_index]

    @property
    def parent(self) -> Signature:
        return self.active_lineage.parent

    @property
    def next_block(self) -> FeatureBlock:
        return self.active_lineage.next_block

    @property
    def next_round_index(self) -> int:
        return self.active_lineage.next_round_index

    @property
    def blocked_features(self) -> tuple[str, ...]:
        return self.active_lineage.blocked_features


@dataclass(frozen=True)
class CampaignResult:
    state: CampaignState
    rounds: tuple[RoundRecord, ...]
    plan_revision: int | None = None
    run_generation_id: str | None = None


class CampaignStore(Protocol):
    """Persistence boundary for reproducible checkpoints and the campaign pool."""

    def load_plan(self, campaign_id: str) -> CampaignPlan | None:
        """Return the immutable plan recorded for this campaign, if any."""
        ...

    def save_plan(self, plan: CampaignPlan) -> None:
        """Persist the plan; reject a different plan under the same ID."""
        ...

    def load_state(self, campaign_id: str) -> CampaignState | None:
        ...

    def save_state(self, campaign_id: str, state: CampaignState) -> None:
        ...

    def save_simulation(self, campaign_id: str, result: SimulationResult) -> None:
        """Persist simulation evidence idempotently by campaign and domain ID."""
        ...

    def covered_bins(
        self, campaign_id: str, grid: CoverageGrid,
    ) -> frozenset[int]:
        """Union observed bins across distinct saved domain IDs on the requested grid."""
        ...

    def save_round(
        self, campaign_id: str, record: RoundRecord, state: CampaignState,
    ) -> None:
        """Persist a completed round and its resulting state as one checkpoint."""
        ...


class RevisionCampaignStore(CampaignStore, Protocol):
    """Revision- and run-generation-aware extension of CampaignStore."""

    def save_revision(
        self,
        project: CampaignProject,
        source_generation_id: str | None = None,
    ) -> None: ...

    def load_revision(
        self, campaign_id: str, plan_revision: int,
    ) -> CampaignProject | None: ...

    def latest_revision(self, campaign_id: str) -> CampaignProject | None: ...

    def latest_generation(self, campaign_id: str, plan_revision: int) -> str | None: ...

    def generation_exists(self, campaign_id: str, run_generation_id: str) -> bool: ...

    def generation_fingerprint(
        self, campaign_id: str, run_generation_id: str,
    ) -> str | None: ...

    def load_generation_state(
        self, campaign_id: str, run_generation_id: str, plan_revision: int,
    ) -> CampaignState | None: ...

    def create_generation(
        self,
        campaign_id: str,
        run_generation_id: str,
        plan_revision: int,
        simulation_fingerprint: str,
        state: CampaignState,
    ) -> None: ...

    def save_generation_state(
        self,
        campaign_id: str,
        run_generation_id: str,
        plan_revision: int,
        state: CampaignState,
    ) -> None: ...

    def load_generation_simulation(
        self,
        campaign_id: str,
        run_generation_id: str,
        simulation_fingerprint: str,
        signature_id: str,
        seed: int,
    ) -> SimulationResult | None: ...

    def save_generation_simulation(
        self,
        campaign_id: str,
        run_generation_id: str,
        simulation_fingerprint: str,
        plan_revision: int,
        result: SimulationResult,
    ) -> None: ...

    def generation_covered_bins(
        self, campaign_id: str, run_generation_id: str, grid: CoverageGrid,
    ) -> frozenset[int]: ...

    def generation_round_count(
        self, campaign_id: str, run_generation_id: str,
    ) -> int: ...

    def save_generation_round(
        self,
        campaign_id: str,
        run_generation_id: str,
        plan_revision: int,
        record: RoundRecord,
        state: CampaignState,
    ) -> None: ...


class _CampaignRunFailure(RuntimeError):
    pass


def _validate_update_rule(plan: CampaignPlan, update_rule: UpdateRule) -> None:
    rule_id = getattr(update_rule, "rule_id", None)
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise TypeError("update_rule must expose a stable, non-empty rule_id")
    if rule_id != plan.update_rule_id:
        raise ValueError("update rule does not match the campaign plan")


def _plan_fingerprint(plan: CampaignPlan) -> str:
    data = {
        "campaign_id": plan.campaign_id,
        "start_signatures": tuple(
            signature.signature_id for signature in plan.start_signatures
        ),
        "grid_id": plan.grid.grid_id,
        "grid_edges": plan.grid.edges,
        "bounds": sorted(
            (bound.feature_id, bound.lower, bound.upper)
            for bound in plan.bounds
        ),
        "exploration_seed": plan.exploration_seed,
        "verification_seeds": plan.verification_seeds,
        "update_rule_id": plan.update_rule_id,
    }
    encoded = json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def validate_plan(plan: CampaignPlan) -> None:
    if not isinstance(plan, CampaignPlan):
        raise TypeError("plan must be a CampaignPlan")
    if not isinstance(plan.campaign_id, str) or not plan.campaign_id.strip():
        raise ValueError("campaign_id must not be empty")
    if not isinstance(plan.update_rule_id, str) or not plan.update_rule_id.strip():
        raise ValueError("update_rule_id must not be empty")
    if (
        not isinstance(plan.start_signatures, tuple)
        or not plan.start_signatures
    ):
        raise ValueError("start_signatures must be a non-empty tuple")
    if any(not isinstance(signature, Signature) for signature in plan.start_signatures):
        raise TypeError("start_signatures must contain Signature values")
    signature_ids = tuple(
        signature.signature_id for signature in plan.start_signatures
    )
    if len(set(signature_ids)) != len(signature_ids):
        raise ValueError("start_signatures must have unique signature IDs")
    for signature in plan.start_signatures:
        if identify_signature(signature.case) != signature:
            raise ValueError("start signature_id does not match its case")
    initial_case = plan.initial_parent.case
    initial_sets = {item.set_id: item for item in initial_case.joint_sets}
    for signature in plan.start_signatures[1:]:
        case = signature.case
        case_sets = {item.set_id: item for item in case.joint_sets}
        if (
            case.case_id != initial_case.case_id
            or case.domain != initial_case.domain
            or case.boreholes != initial_case.boreholes
            or case.tunnel != initial_case.tunnel
            or case_sets.keys() != initial_sets.keys()
        ):
            raise ValueError(
                "all start signatures must share case geometry and joint-set IDs"
            )
        for set_id, original in initial_sets.items():
            joint_set = case_sets[set_id]
            if (
                joint_set.name != original.name
                or joint_set.density_type != original.density_type
                or joint_set.size_alpha != original.size_alpha
                or joint_set.fisher_kappa != original.fisher_kappa
                or joint_set.condition != original.condition
            ):
                raise ValueError(
                    "all start signatures must share immutable joint-set properties"
                )
    validate_grid(plan.grid)
    if not isinstance(plan.bounds, tuple) or not plan.bounds:
        raise ValueError("bounds must be a non-empty tuple")
    if any(not isinstance(bound, FeatureBound) for bound in plan.bounds):
        raise TypeError("bounds must contain FeatureBound values")
    if (
        isinstance(plan.exploration_seed, bool)
        or not isinstance(plan.exploration_seed, int)
        or plan.exploration_seed < 0
    ):
        raise ValueError("exploration_seed must be a non-negative integer")
    if (
        not isinstance(plan.verification_seeds, tuple)
        or len(plan.verification_seeds) != 3
        or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in plan.verification_seeds
        )
    ):
        raise ValueError("verification_seeds must contain three non-negative integers")
    seeds = (plan.exploration_seed, *plan.verification_seeds)
    if len(set(seeds)) != len(seeds):
        raise ValueError("exploration and verification seeds must be distinct")
    if any(
        _feature_block(bound.feature_id) not in _FEATURE_BLOCKS
        for bound in plan.bounds
    ):
        raise ValueError("all bounds must refer to supported feature blocks")
    for block in _FEATURE_BLOCKS:
        if any(_feature_block(bound.feature_id) == block for bound in plan.bounds):
            for signature in plan.start_signatures:
                build_probes(signature, block, plan.bounds)
    _plan_fingerprint(plan)


def initialize_campaign(plan: CampaignPlan) -> CampaignState:
    validate_plan(plan)
    return CampaignState(
        campaign_id=plan.campaign_id,
        plan_fingerprint=_plan_fingerprint(plan),
        active_lineage_index=0,
        lineages=tuple(
            LineageState(
                start_signature_id=signature.signature_id,
                parent=signature,
                next_block="density",
                next_round_index=0,
                blocked_features=(),
                status="ready",
                reason=None,
            )
            for signature in plan.start_signatures
        ),
        status="ready",
        reason=None,
    )


def _validate_state(plan: CampaignPlan, state: CampaignState) -> None:
    if not isinstance(state, CampaignState):
        raise TypeError("state must be a CampaignState")
    if state.campaign_id != plan.campaign_id:
        raise ValueError("state campaign_id does not match the plan")
    if state.plan_fingerprint != _plan_fingerprint(plan):
        raise ValueError("state was created for a different campaign plan")
    if (
        isinstance(state.active_lineage_index, bool)
        or not isinstance(state.active_lineage_index, int)
        or not 0 <= state.active_lineage_index < len(plan.start_signatures)
    ):
        raise ValueError("active_lineage_index must select a planned lineage")
    if (
        not isinstance(state.lineages, tuple)
        or len(state.lineages) != len(plan.start_signatures)
    ):
        raise ValueError("campaign state must contain one lineage per start signature")
    if state.status not in (
        "ready", "running", *_CAMPAIGN_TERMINAL_STATUSES, "stopped",
    ):
        raise ValueError("state status is unsupported")
    if state.status in _CAMPAIGN_TERMINAL_STATUSES or state.status == "stopped":
        if not isinstance(state.reason, str) or not state.reason.strip():
            raise ValueError("terminal campaign state requires a non-empty reason")
    elif state.reason is not None:
        raise ValueError("ready/running campaign state must not have a terminal reason")

    initial_case = plan.initial_parent.case
    initial_sets = {item.set_id: item for item in initial_case.joint_sets}
    bound_ids = {bound.feature_id for bound in plan.bounds}
    for start_signature, lineage in zip(plan.start_signatures, state.lineages):
        if not isinstance(lineage, LineageState):
            raise TypeError("campaign lineages must contain LineageState values")
        if lineage.start_signature_id != start_signature.signature_id:
            raise ValueError("lineage order does not match the plan start signatures")
        if identify_signature(lineage.parent.case) != lineage.parent:
            raise ValueError("lineage parent signature_id does not match its case")
        case = lineage.parent.case
        case_sets = {item.set_id: item for item in case.joint_sets}
        if (
            case.case_id != initial_case.case_id
            or case.domain != initial_case.domain
            or case.boreholes != initial_case.boreholes
            or case.tunnel != initial_case.tunnel
            or case_sets.keys() != initial_sets.keys()
        ):
            raise ValueError("lineage parent changed shared case geometry")
        for set_id, original in initial_sets.items():
            joint_set = case_sets[set_id]
            if (
                joint_set.name != original.name
                or joint_set.density_type != original.density_type
                or joint_set.size_alpha != original.size_alpha
                or joint_set.fisher_kappa != original.fisher_kappa
                or joint_set.condition != original.condition
            ):
                raise ValueError("lineage parent changed an immutable joint-set property")
        if lineage.next_block not in _FEATURE_BLOCKS:
            raise ValueError("lineage next_block is unsupported")
        if (
            isinstance(lineage.next_round_index, bool)
            or not isinstance(lineage.next_round_index, int)
            or lineage.next_round_index < 0
        ):
            raise ValueError("lineage next_round_index must be non-negative")
        if lineage.status not in ("ready", "running", *_TERMINAL_STATUSES):
            raise ValueError("lineage status is unsupported")
        if not isinstance(lineage.blocked_features, tuple):
            raise TypeError("blocked_features must be a tuple")
        if (
            len(set(lineage.blocked_features)) != len(lineage.blocked_features)
            or not set(lineage.blocked_features) <= bound_ids
        ):
            raise ValueError("blocked_features must be unique planned feature IDs")
        for block in _FEATURE_BLOCKS:
            if any(_feature_block(bound.feature_id) == block for bound in plan.bounds):
                build_probes(lineage.parent, block, plan.bounds)
        if lineage.status in _TERMINAL_STATUSES:
            if not isinstance(lineage.reason, str) or not lineage.reason.strip():
                raise ValueError("terminal lineage requires a non-empty reason")
        elif lineage.reason is not None:
            raise ValueError("ready/running lineage must not have a terminal reason")
    if state.status in ("ready", "running", "round_budget_exhausted") and (
        state.active_lineage.status not in ("ready", "running")
    ):
        raise ValueError("active campaign cursor must point to a runnable lineage")
    if any(
        lineage.status in ("ready", "running")
        for lineage in state.lineages[:state.active_lineage_index]
    ):
        raise ValueError("campaign cursor cannot skip a runnable earlier lineage")
    if any(
        lineage.status == "running"
        for lineage in state.lineages[state.active_lineage_index + 1:]
    ):
        raise ValueError("only the active lineage may be running")
    if state.status == "all_lineages_saturated" and any(
        lineage.status != "stopped" for lineage in state.lineages
    ):
        raise ValueError("all_lineages_saturated requires every lineage to be stopped")
    if state.status == "round_budget_exhausted" and (
        state.active_lineage.status not in ("ready", "running")
    ):
        raise ValueError("round_budget_exhausted requires a runnable active lineage")


def _replace_active_lineage(
    state: CampaignState, **changes: object,
) -> CampaignState:
    lineages = list(state.lineages)
    updated = replace(state.active_lineage, **changes)
    lineages[state.active_lineage_index] = updated
    return replace(
        state,
        lineages=tuple(lineages),
        status=updated.status,
        reason=updated.reason,
    )


def _report_coverage(simulator: Simulator, coverage: CoverageResult) -> None:
    reporter = getattr(simulator, "report_coverage", None)
    if callable(reporter):
        reporter(coverage)


def _evaluate(
    plan: CampaignPlan,
    signature: Signature,
    seed: int,
    simulator: Simulator,
    store: CampaignStore,
    cache: dict[tuple[str, int], CoverageResult],
) -> CoverageResult:
    key = (signature.signature_id, seed)
    if key in cache:
        coverage = cache[key]
        _report_coverage(simulator, coverage)
        return coverage
    load_simulation = getattr(store, "load_simulation", None)
    if callable(load_simulation):
        result = load_simulation(plan.campaign_id, signature.signature_id, seed)
        if result is not None:
            if (
                not isinstance(result, SimulationResult)
                or result.signature_id != signature.signature_id
                or result.seed != seed
            ):
                raise _CampaignRunFailure(
                    "stored simulation does not match the requested signature and seed"
                )
            try:
                coverage = audit_simulation(result, plan.grid)
            except (TypeError, ValueError) as error:
                raise _CampaignRunFailure(
                    f"stored simulation profile audit failed: {error}"
                ) from error
            cache[key] = coverage
            _report_coverage(simulator, coverage)
            return coverage
    try:
        result = simulator.evaluate(signature, seed)
    except (ValueError, RuntimeError) as error:
        raise _CampaignRunFailure(
            f"simulation failed for {signature.signature_id[:12]}... "
            f"with seed {seed}: {error}"
        ) from error
    if not isinstance(result, SimulationResult):
        raise _CampaignRunFailure("simulator must return a SimulationResult")
    if result.signature_id != signature.signature_id or result.seed != seed:
        raise _CampaignRunFailure(
            "simulation result signature_id and seed must match the requested inputs"
        )
    if not isinstance(result.domain_id, str) or not result.domain_id.strip():
        raise _CampaignRunFailure("simulation result domain_id must not be empty")
    try:
        coverage = audit_simulation(result, plan.grid)
    except (TypeError, ValueError) as error:
        raise _CampaignRunFailure(f"simulation profile audit failed: {error}") from error
    store.save_simulation(plan.campaign_id, result)
    cache[key] = coverage
    _report_coverage(simulator, coverage)
    return coverage


def run_round(
    plan: CampaignPlan,
    state: CampaignState,
    simulator: Simulator,
    update_rule: UpdateRule,
    store: CampaignStore,
) -> RoundRecord:
    validate_plan(plan)
    _validate_state(plan, state)
    if state.status not in ("ready", "running"):
        raise ValueError("only ready/running campaigns can execute a round")
    if state.active_lineage.status not in ("ready", "running"):
        raise ValueError("the active lineage is not ready to execute a round")
    _validate_update_rule(plan, update_rule)

    cache: dict[tuple[str, int], CoverageResult] = {}
    parent_coverage = _evaluate(
        plan, state.parent, plan.exploration_seed, simulator, store, cache,
    )
    if len(parent_coverage.observed_bins) == len(parent_coverage.bins):
        proposal = UpdateProposal(
            state.parent, None, state.next_block, (), (), "no_direction",
            "the current parent observes every coverage bin",
        )
        return RoundRecord(
            state.next_round_index, state.next_block, parent_coverage, (),
            proposal, None, state.active_lineage.start_signature_id,
        )

    active_bounds = tuple(
        bound for bound in plan.bounds
        if bound.feature_id not in state.blocked_features
    )
    block_bounds = tuple(
        bound for bound in active_bounds
        if _feature_block(bound.feature_id) == state.next_block
    )
    if not block_bounds:
        previously_blocked = tuple(
            sorted(
                bound.feature_id for bound in plan.bounds
                if bound.feature_id in state.blocked_features
                and _feature_block(bound.feature_id) == state.next_block
            )
        )
        has_block_features = any(
            _feature_block(bound.feature_id) == state.next_block
            for bound in plan.bounds
        )
        proposal = UpdateProposal(
            state.parent, None, state.next_block, (), previously_blocked,
            "bound_limited" if has_block_features else "no_direction",
            "all features in this block are already blocked"
            if has_block_features
            else "no features are configured for this block",
        )
        return RoundRecord(
            state.next_round_index, state.next_block, parent_coverage, (),
            proposal, None, state.active_lineage.start_signature_id,
        )

    probes = build_probes(state.parent, state.next_block, block_bounds)
    gaps = parent_gaps(parent_coverage)
    evidence: list[ProbeEvidence] = []
    for probe in probes:
        minus_score = None
        plus_score = None
        if probe.minus is not None:
            minus_coverage = _evaluate(
                plan, probe.minus, plan.exploration_seed, simulator, store, cache,
            )
            minus_score = score_pair(parent_coverage, minus_coverage, gaps)
        if probe.plus is not None:
            plus_coverage = _evaluate(
                plan, probe.plus, plan.exploration_seed, simulator, store, cache,
            )
            plus_score = score_pair(parent_coverage, plus_coverage, gaps)
        evidence.append(
            ProbeEvidence(
                probe, plan.exploration_seed, parent_coverage,
                minus_score, plus_score,
            )
        )

    sensitivities = tuple(estimate_sensitivity(item) for item in evidence)
    proposal = propose_update(
        state.parent, state.next_block, sensitivities, block_bounds, update_rule,
    )
    verification = None
    if proposal.status == "candidate":
        candidate = proposal.candidate
        if candidate is None:
            raise ValueError("candidate proposal is missing its candidate signature")
        paired_scores = []
        for seed in plan.verification_seeds:
            verified_parent = _evaluate(
                plan, state.parent, seed, simulator, store, cache,
            )
            verified_candidate = _evaluate(
                plan, candidate, seed, simulator, store, cache,
            )
            paired_scores.append(
                score_pair(
                    verified_parent, verified_candidate,
                    parent_gaps(verified_parent),
                )
            )
        verification = assess_repeatability(
            proposal, (paired_scores[0], paired_scores[1], paired_scores[2]),
            require_new_bin=isinstance(
                update_rule, GapSeekingNormalizedGradientUpdateRule,
            ),
        )

    return RoundRecord(
        state.next_round_index, state.next_block, parent_coverage,
        tuple(evidence), proposal, verification,
        state.active_lineage.start_signature_id,
    )


def advance_state(state: CampaignState, record: RoundRecord) -> CampaignState:
    if not isinstance(state, CampaignState) or not isinstance(record, RoundRecord):
        raise TypeError("state and record must be campaign values")
    if state.status not in ("ready", "running"):
        raise ValueError("only ready/running campaigns can advance")
    lineage = state.active_lineage
    if lineage.status not in ("ready", "running"):
        raise ValueError("the active lineage is not ready to advance")
    if record.lineage_start_signature_id != lineage.start_signature_id:
        raise ValueError("round record belongs to a different start lineage")
    if record.round_index != state.next_round_index or record.block != state.next_block:
        raise ValueError("round record does not match the next campaign round")
    if record.parent_coverage.signature_id != state.parent.signature_id:
        raise ValueError("round parent coverage does not match the campaign parent")
    proposal = record.proposal
    if proposal.parent != state.parent or proposal.block != state.next_block:
        raise ValueError("round proposal does not match the campaign parent and block")

    parent = state.parent
    blocked = set(state.blocked_features)
    status: Literal["ready", "running", "stopped", "decision_required", "failed"] = "running"
    reason = None
    if len(record.parent_coverage.observed_bins) == len(record.parent_coverage.bins):
        status, reason = "stopped", "the current parent observes every coverage bin"
    elif proposal.status == "decision_required":
        status, reason = "decision_required", proposal.reason
    elif proposal.status == "candidate":
        if record.verification is None:
            raise ValueError("candidate proposal requires paired verification")
        if record.verification.proposal != proposal:
            raise ValueError("verification result does not match the round proposal")
        if record.verification.accepted:
            if proposal.candidate is None:
                raise ValueError("accepted proposal is missing its candidate signature")
            parent = proposal.candidate
            blocked = set()
        else:
            blocked.update(item.feature_id for item in proposal.sensitivities)
            blocked.update(proposal.bound_limited_features)
    else:
        if record.verification is not None:
            raise ValueError("non-candidate proposals must not have verification results")
        blocked.update(proposal.bound_limited_features)
        blocked.update(item.feature_id for item in proposal.sensitivities)

    return _replace_active_lineage(
        state,
        parent=parent,
        next_block=next_feature_block(state.next_block),
        next_round_index=state.next_round_index + 1,
        blocked_features=tuple(sorted(blocked)),
        status=status,
        reason=reason,
    )


def _covered_bins(
    store: CampaignStore, campaign_id: str, grid: CoverageGrid,
) -> frozenset[int]:
    bins = store.covered_bins(campaign_id, grid)
    count = len(grid.edges) - 1
    if not isinstance(bins, frozenset) or any(
        isinstance(index, bool) or not isinstance(index, int)
        or not 0 <= index < count
        for index in bins
    ):
        raise ValueError("store covered_bins must contain valid grid indices")
    return bins


def _all_bins_covered(bins: frozenset[int], grid: CoverageGrid) -> bool:
    return bins == frozenset(range(len(grid.edges) - 1))


def _remaining_bins_reason(store: CampaignStore, plan: CampaignPlan) -> str:
    covered = _covered_bins(store, plan.campaign_id, plan.grid)
    remaining = sorted(set(range(len(plan.grid.edges) - 1)) - set(covered))
    return f"remaining coverage bins: {remaining}"


def _campaign_status(
    state: CampaignState,
    status: Literal[
        "ready",
        "running",
        "coverage_complete",
        "round_budget_exhausted",
        "all_lineages_saturated",
        "decision_required",
        "failed",
    ],
    reason: str | None,
) -> CampaignState:
    return replace(state, status=status, reason=reason)


def _advance_saturated_lineage(
    state: CampaignState, store: CampaignStore, plan: CampaignPlan,
) -> CampaignState:
    for index in range(state.active_lineage_index + 1, len(state.lineages)):
        if state.lineages[index].status in ("ready", "running"):
            return replace(
                state, active_lineage_index=index, status="running", reason=None,
            )
    if all(lineage.status == "stopped" for lineage in state.lineages):
        return _campaign_status(
            state,
            "all_lineages_saturated",
            "all start lineages are saturated; " + _remaining_bins_reason(store, plan),
        )
    if any(lineage.status == "decision_required" for lineage in state.lineages):
        return _campaign_status(
            state, "decision_required", "a lineage requires an explicit decision",
        )
    if any(lineage.status == "failed" for lineage in state.lineages):
        return _campaign_status(state, "failed", "a lineage failed")
    raise ValueError("no runnable lineage follows the saturated active lineage")


def run_campaign(
    plan: CampaignPlan,
    state: CampaignState,
    simulator: Simulator,
    update_rule: UpdateRule,
    store: CampaignStore,
    *,
    round_budget: int | None = None,
    rounds_already_completed: int = 0,
) -> CampaignResult:
    """Resume and run ordered lineages until a campaign-level stop condition.

    The returned rounds are those executed by this invocation; prior rounds remain
    available through the store.
    """
    validate_plan(plan)
    if (
        round_budget is not None
        and (
            isinstance(round_budget, bool)
            or not isinstance(round_budget, int)
            or round_budget < 1
        )
    ):
        raise ValueError("round_budget must be null or a positive integer")
    if (
        isinstance(rounds_already_completed, bool)
        or not isinstance(rounds_already_completed, int)
        or rounds_already_completed < 0
    ):
        raise ValueError("rounds_already_completed must be a non-negative integer")
    _validate_state(plan, state)
    _validate_update_rule(plan, update_rule)
    fingerprint = _plan_fingerprint(plan)
    persisted_plan = store.load_plan(plan.campaign_id)
    persisted_state = store.load_state(plan.campaign_id)
    if persisted_plan is None:
        if persisted_state is not None:
            raise ValueError("campaign state exists without its persisted plan")
        store.save_plan(plan)
    else:
        validate_plan(persisted_plan)
        if _plan_fingerprint(persisted_plan) != fingerprint:
            raise ValueError("stored campaign plan does not match the supplied plan")

    current = persisted_state if persisted_state is not None else state
    _validate_state(plan, current)
    if persisted_state is None:
        store.save_state(plan.campaign_id, current)
    completed_rounds: list[RoundRecord] = []
    all_feature_ids = {bound.feature_id for bound in plan.bounds}
    total_rounds = rounds_already_completed

    while current.status in ("ready", "running"):
        covered = _covered_bins(store, plan.campaign_id, plan.grid)
        if _all_bins_covered(covered, plan.grid):
            reason = "the cumulative campaign pool observes every coverage bin"
            if current.active_lineage.status in ("ready", "running"):
                current = _replace_active_lineage(
                    current, status="stopped", reason=reason,
                )
            current = _campaign_status(
                current, "coverage_complete", reason,
            )
            store.save_state(plan.campaign_id, current)
            break
        if all_feature_ids <= set(current.blocked_features):
            current = _replace_active_lineage(
                current, status="stopped",
                reason=(
                    "no untried feature remains under the update rule at the current parent; "
                    + _remaining_bins_reason(store, plan)
                ),
            )
            current = _advance_saturated_lineage(current, store, plan)
            store.save_state(plan.campaign_id, current)
            continue
        if round_budget is not None and total_rounds >= round_budget:
            current = _campaign_status(
                current,
                "round_budget_exhausted",
                f"round budget {round_budget} exhausted; "
                + _remaining_bins_reason(store, plan),
            )
            store.save_state(plan.campaign_id, current)
            break
        try:
            record = run_round(plan, current, simulator, update_rule, store)
        except _CampaignRunFailure as error:
            covered = _covered_bins(store, plan.campaign_id, plan.grid)
            if _all_bins_covered(covered, plan.grid):
                reason = "the cumulative campaign pool observes every coverage bin"
                current = _replace_active_lineage(
                    current, status="stopped", reason=reason,
                )
                current = _campaign_status(
                    current, "coverage_complete", reason,
                )
            else:
                current = _replace_active_lineage(
                    current, status="failed",
                    reason=f"{error}; {_remaining_bins_reason(store, plan)}",
                )
            store.save_state(plan.campaign_id, current)
            break

        next_state = advance_state(current, record)
        if (
            next_state.status == "running"
            and all_feature_ids <= set(next_state.blocked_features)
        ):
            next_state = _replace_active_lineage(
                next_state, status="stopped",
                reason=(
                    "no untried feature remains under the update rule at the current parent; "
                    + _remaining_bins_reason(store, plan)
                ),
            )
        elif next_state.status == "decision_required":
            next_state = _replace_active_lineage(
                next_state,
                reason=f"{next_state.reason}; {_remaining_bins_reason(store, plan)}",
            )
        covered = _covered_bins(store, plan.campaign_id, plan.grid)
        if _all_bins_covered(covered, plan.grid):
            reason = "the cumulative campaign pool observes every coverage bin"
            if next_state.active_lineage.status in ("ready", "running"):
                next_state = _replace_active_lineage(
                    next_state, status="stopped", reason=reason,
                )
            next_state = _campaign_status(
                next_state, "coverage_complete", reason,
            )
        elif (
            next_state.active_lineage.status == "stopped"
            and next_state.status == "stopped"
        ):
            next_state = _advance_saturated_lineage(next_state, store, plan)
        store.save_round(plan.campaign_id, record, next_state)
        completed_rounds.append(record)
        current = next_state
        total_rounds += 1

    return CampaignResult(current, tuple(completed_rounds))


class _RevisionScopedStore:
    def __init__(
        self,
        store: RevisionCampaignStore,
        project: CampaignProject,
        run_generation_id: str,
        simulation_fingerprint: str,
    ) -> None:
        self._store = store
        self._project = project
        self._generation = run_generation_id
        self._simulation_fingerprint = simulation_fingerprint

    def load_plan(self, campaign_id: str) -> CampaignPlan | None:
        if campaign_id != self._project.plan.campaign_id:
            raise ValueError("campaign ID does not match the active revision")
        return self._project.plan

    def save_plan(self, plan: CampaignPlan) -> None:
        if _plan_fingerprint(plan) != _plan_fingerprint(self._project.plan):
            raise ValueError("cannot change the plan inside a stored revision")

    def load_state(self, campaign_id: str) -> CampaignState | None:
        return self._store.load_generation_state(
            campaign_id, self._generation, self._project.plan_revision,
        )

    def save_state(self, campaign_id: str, state: CampaignState) -> None:
        self._store.save_generation_state(
            campaign_id, self._generation, self._project.plan_revision, state,
        )

    def load_simulation(
        self, campaign_id: str, signature_id: str, seed: int,
    ) -> SimulationResult | None:
        return self._store.load_generation_simulation(
            campaign_id, self._generation, self._simulation_fingerprint,
            signature_id, seed,
        )

    def save_simulation(self, campaign_id: str, result: SimulationResult) -> None:
        self._store.save_generation_simulation(
            campaign_id, self._generation, self._simulation_fingerprint,
            self._project.plan_revision, result,
        )

    def covered_bins(
        self, campaign_id: str, grid: CoverageGrid,
    ) -> frozenset[int]:
        return self._store.generation_covered_bins(
            campaign_id, self._generation, grid,
        )

    def save_round(
        self, campaign_id: str, record: RoundRecord, state: CampaignState,
    ) -> None:
        self._store.save_generation_round(
            campaign_id, self._generation, self._project.plan_revision,
            record, state,
        )


def _state_for_project_revision(
    previous_project: CampaignProject,
    project: CampaignProject,
    previous_state: CampaignState,
) -> CampaignState:
    _validate_state(previous_project.plan, previous_state)
    old_plan, new_plan = previous_project.plan, project.plan
    starts_appended = (
        len(new_plan.start_signatures) > len(old_plan.start_signatures)
        and new_plan.start_signatures[:len(old_plan.start_signatures)]
        == old_plan.start_signatures
    )
    if starts_appended:
        if previous_state.status != "all_lineages_saturated":
            raise ValueError("new starts require a saturated predecessor campaign")
        additions = tuple(
            LineageState(
                signature.signature_id, signature, "density", 0, (),
                "ready", None,
            )
            for signature in new_plan.start_signatures[len(old_plan.start_signatures):]
        )
        return CampaignState(
            new_plan.campaign_id,
            _plan_fingerprint(new_plan),
            len(previous_state.lineages),
            (*previous_state.lineages, *additions),
            "ready",
            None,
        )
    if new_plan.start_signatures == old_plan.start_signatures:
        if previous_state.status != "round_budget_exhausted":
            raise ValueError("additional rounds require an exhausted predecessor budget")
        return replace(
            previous_state,
            plan_fingerprint=_plan_fingerprint(new_plan),
            status="ready",
            reason=None,
        )
    raise ValueError("new revision is not a valid signature or round-budget extension")


def run_campaign_project(
    project: CampaignProject,
    simulator: Simulator,
    update_rule: UpdateRule,
    store: RevisionCampaignStore,
    execution_fingerprint: str | None = None,
    *,
    source_generation_id: str | None = None,
    run_generation_id: str | None = None,
    force_from_scratch: bool = False,
) -> CampaignResult:
    """Run or resume one immutable project revision in a durable generation."""
    from .config import _validate_campaign_revision

    validate_plan(project.plan)
    _validate_campaign_revision(project)
    _validate_update_rule(project.plan, update_rule)
    if execution_fingerprint is None:
        execution_fingerprint = getattr(simulator, "execution_fingerprint", None)
    if not isinstance(execution_fingerprint, str) or not execution_fingerprint.strip():
        raise ValueError(
            "simulator must expose a stable execution_fingerprint or one must be supplied"
        )
    if not isinstance(force_from_scratch, bool):
        raise TypeError("force_from_scratch must be a boolean")

    campaign_id = project.plan.campaign_id
    previous_project = None
    if project.plan_revision > 1:
        previous_project = store.load_revision(campaign_id, project.plan_revision - 1)
        if previous_project is None:
            raise ValueError("campaign predecessor revision is not stored")
        if source_generation_id is None:
            if (
                not force_from_scratch
                and run_generation_id is not None
                and store.generation_exists(campaign_id, run_generation_id)
            ):
                source_generation_id = run_generation_id
            else:
                source_generation_id = store.latest_generation(
                    campaign_id, project.plan_revision - 1,
                )
        if source_generation_id is None:
            raise ValueError("revision extension requires its source run generation")
    store.save_revision(project, source_generation_id)

    if force_from_scratch:
        if run_generation_id is not None and store.generation_exists(
            campaign_id, run_generation_id,
        ):
            raise ValueError("force-from-scratch requires a new run_generation_id")
        generation = run_generation_id or uuid4().hex
    elif run_generation_id is not None:
        generation = run_generation_id
    else:
        generation = store.latest_generation(campaign_id, project.plan_revision)
        if generation is None:
            generation = source_generation_id or uuid4().hex

    if not generation.strip():
        raise ValueError("run_generation_id must not be empty")
    simulation_fingerprint = sha256(
        execution_fingerprint.encode("utf-8"),
    ).hexdigest()
    stored_fingerprint = store.generation_fingerprint(campaign_id, generation)
    if (
        stored_fingerprint is not None
        and stored_fingerprint != simulation_fingerprint
    ):
        raise ValueError("execution fingerprint changed within a run generation")

    current = store.load_generation_state(
        campaign_id, generation, project.plan_revision,
    )
    if current is None:
        if (
            previous_project is not None
            and not force_from_scratch
            and generation == source_generation_id
        ):
            previous_state = store.load_generation_state(
                campaign_id, generation, previous_project.plan_revision,
            )
            if previous_state is None:
                raise ValueError("source generation has no predecessor state")
            current = _state_for_project_revision(
                previous_project, project, previous_state,
            )
        else:
            current = initialize_campaign(project.plan)
        store.create_generation(
            campaign_id, generation, project.plan_revision,
            simulation_fingerprint, current,
        )
    _validate_state(project.plan, current)

    scoped_store = _RevisionScopedStore(
        store, project, generation, simulation_fingerprint,
    )
    result = run_campaign(
        project.plan,
        current,
        simulator,
        update_rule,
        scoped_store,
        round_budget=project.round_budget,
        rounds_already_completed=store.generation_round_count(campaign_id, generation),
    )
    return replace(
        result,
        plan_revision=project.plan_revision,
        run_generation_id=generation,
    )
