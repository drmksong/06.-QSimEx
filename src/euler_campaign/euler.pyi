"""Pure probe/update contracts for bounded, profile-score-driven signatures.

The default rule scales the active block's sensitivities so its largest log-space
step is 0.05 or its largest orientation step is 5 degrees.
Fisher kappa and conditions outside the active feature block remain unchanged.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from .models import FeatureBlock, Signature, Vector3
from .coverage import CoverageResult, PairedScore

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
    def rule_id(self) -> str: ...
    def propose(self, parent: Signature, block: FeatureBlock, sensitivities: tuple[Sensitivity, ...], bounds: tuple[FeatureBound, ...]) -> UpdateProposal: ...

class NormalizedGradientUpdateRule:
    @property
    def rule_id(self) -> str: ...
    def propose(self, parent: Signature, block: FeatureBlock, sensitivities: tuple[Sensitivity, ...], bounds: tuple[FeatureBound, ...]) -> UpdateProposal: ...

class GapSeekingNormalizedGradientUpdateRule(NormalizedGradientUpdateRule):
    @property
    def rule_id(self) -> str: ...

def next_feature_block(block: FeatureBlock) -> FeatureBlock: ...
def orientation_beta(normal: Vector3, borehole_direction: Vector3) -> float: ...
def build_probes(parent: Signature, block: FeatureBlock, bounds: tuple[FeatureBound, ...]) -> tuple[ProbePair, ...]: ...
def estimate_sensitivity(evidence: ProbeEvidence) -> Sensitivity: ...
def propose_update(parent: Signature, block: FeatureBlock, sensitivities: tuple[Sensitivity, ...], bounds: tuple[FeatureBound, ...], rule: UpdateRule | None = ...) -> UpdateProposal: ...
def assess_repeatability(proposal: UpdateProposal, scores: tuple[PairedScore, PairedScore, PairedScore], *, require_new_bin: bool = ...) -> RepeatabilityResult: ...
