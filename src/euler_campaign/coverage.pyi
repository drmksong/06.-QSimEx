"""Pure profile coverage and paired scores; never imports the cutoff selector."""

from dataclasses import dataclass
from .profiles import ProfileInterval, SimulationResult

@dataclass(frozen=True)
class CoverageGrid:
    grid_id: str
    edges: tuple[float, ...]

@dataclass(frozen=True)
class BinCoverage:
    bin_index: int
    observed_length: float
    proximity: float

@dataclass(frozen=True)
class CoverageResult:
    signature_id: str
    seed: int
    grid: CoverageGrid
    bins: tuple[BinCoverage, ...]
    observed_bins: frozenset[int]

@dataclass(frozen=True)
class PairedScore:
    seed: int
    parent_signature_id: str
    candidate_signature_id: str
    grid_id: str
    parent_gap_bins: frozenset[int]
    proximity_delta: float
    new_occupancy_fraction: float
    delta_score: float
    parent_observed_count: int
    candidate_observed_count: int

def validate_grid(grid: CoverageGrid) -> None: ...
def audit_profile(intervals: tuple[ProfileInterval, ...], grid: CoverageGrid) -> tuple[BinCoverage, ...]: ...
def audit_simulation(result: SimulationResult, grid: CoverageGrid) -> CoverageResult: ...
def parent_gaps(parent: CoverageResult) -> frozenset[int]: ...
def score_pair(parent: CoverageResult, candidate: CoverageResult, gaps: frozenset[int]) -> PairedScore: ...
