"""Orchestration only: probes -> sensitivity -> update -> three-seed verification.

No geometry, score formula, subprocess command, or serialization implementation
belongs here. Store and simulator are injected; old campaigns are never mutated.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from .models import FeatureBlock, Signature
from .coverage import CoverageGrid, CoverageResult
from .euler import FeatureBound, ProbeEvidence, RepeatabilityResult, UpdateProposal, UpdateRule
from .ports import Simulator
from .profiles import SimulationResult

@dataclass(frozen=True)
class CampaignPlan:
    campaign_id: str
    initial_parent: Signature
    grid: CoverageGrid
    bounds: tuple[FeatureBound, ...]
    exploration_seed: int
    verification_seeds: tuple[int, int, int]

@dataclass(frozen=True)
class RoundRecord:
    round_index: int
    block: FeatureBlock
    parent_coverage: CoverageResult
    probes: tuple[ProbeEvidence, ...]
    proposal: UpdateProposal
    verification: RepeatabilityResult | None

@dataclass(frozen=True)
class CampaignState:
    campaign_id: str
    parent: Signature
    next_block: FeatureBlock
    next_round_index: int
    blocked_features: tuple[str, ...]
    status: Literal["ready", "running", "stopped", "decision_required", "failed"]
    reason: str | None

@dataclass(frozen=True)
class CampaignResult:
    state: CampaignState
    rounds: tuple[RoundRecord, ...]

class CampaignStore(Protocol):
    def load_state(self, campaign_id: str) -> CampaignState | None: ...
    def save_simulation(self, result: SimulationResult) -> None: ...
    def save_round(self, campaign_id: str, record: RoundRecord, state: CampaignState) -> None: ...

def validate_plan(plan: CampaignPlan) -> None: ...
def initialize_campaign(plan: CampaignPlan) -> CampaignState: ...
def run_round(plan: CampaignPlan, state: CampaignState, simulator: Simulator, update_rule: UpdateRule, store: CampaignStore) -> RoundRecord: ...
def advance_state(state: CampaignState, record: RoundRecord) -> CampaignState: ...
def run_campaign(plan: CampaignPlan, state: CampaignState, simulator: Simulator, update_rule: UpdateRule, store: CampaignStore) -> CampaignResult: ...
