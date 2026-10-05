"""Length-supported profile coverage and paired signature scores."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import exp, fsum, isfinite, log, log1p
from numbers import Real

from .profiles import ProfileInterval, SimulationResult
from .qprime import QPrimeResult

_LN_10 = log(10.0)


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


def _finite_sum(values: list[float], message: str) -> float:
    try:
        result = fsum(values)
    except OverflowError as error:
        raise ValueError(message) from error
    if not isfinite(result):
        raise ValueError(message)
    return result


def _edge_values(grid: CoverageGrid) -> tuple[float, ...]:
    if not isinstance(grid, CoverageGrid):
        raise TypeError("grid must be a CoverageGrid")
    if not isinstance(grid.grid_id, str) or not grid.grid_id.strip():
        raise ValueError("grid_id must not be empty")
    if not isinstance(grid.edges, tuple) or len(grid.edges) < 2:
        raise ValueError("grid must contain at least two edges")

    edges: list[float] = []
    for edge in grid.edges:
        if isinstance(edge, bool) or not isinstance(edge, Real):
            raise ValueError("grid edges must be finite real numbers")
        value = float(edge)
        if not isfinite(value):
            raise ValueError("grid edges must be finite real numbers")
        edges.append(value)

    if edges[0] != 0.0:
        raise ValueError("the first grid edge must be zero")
    if any(edge <= 0.0 for edge in edges[1:]):
        raise ValueError("grid edges after zero must be positive")
    if any(right <= left for left, right in zip(edges, edges[1:])):
        raise ValueError("grid edges must be strictly increasing")
    return tuple(edges)


def validate_grid(grid: CoverageGrid) -> None:
    _edge_values(grid)


def _log_ratio(upper: float, lower: float) -> float:
    difference = upper - lower
    if difference <= lower:
        result = log1p(difference / lower)
    else:
        result = log(upper) - log(lower)
    if not isfinite(result) or result <= 0.0:
        raise ValueError("grid bin must have a positive logarithmic width")
    return result


def _proximity(value: float, lower: float, upper: float, bin_index: int) -> float:
    if bin_index == 0:
        if value <= upper:
            return 1.0
        delta = (log(value) - log(upper)) / _LN_10
    elif value < lower:
        delta = _log_ratio(lower, value) / _log_ratio(upper, lower)
    elif value > upper:
        delta = _log_ratio(value, upper) / _log_ratio(upper, lower)
    else:
        return 1.0
    return exp(-delta * _LN_10 / 9.0)


def _audit_profile(
    intervals: tuple[ProfileInterval, ...], edges: tuple[float, ...],
) -> tuple[tuple[BinCoverage, ...], float]:
    if not isinstance(intervals, tuple):
        raise TypeError("profile intervals must be a tuple")
    if not intervals:
        raise ValueError("profile must contain positive-length support")

    lengths: list[float] = []
    values: list[float] = []
    previous_end: float | None = None
    for interval in intervals:
        if not isinstance(interval, ProfileInterval):
            raise TypeError("profile entries must be ProfileInterval values")
        if not isinstance(interval.qprime, QPrimeResult):
            raise TypeError("profile Q-prime values must be QPrimeResult values")
        start, end, value = interval.start, interval.end, interval.qprime.value
        if any(
            isinstance(item, bool) or not isinstance(item, Real) or not isfinite(item)
            for item in (start, end, value)
        ):
            raise ValueError("profile coordinates and Q-prime values must be finite")
        if start < 0.0 or end <= start:
            raise ValueError("profile intervals must have non-negative start and positive length")
        if value <= 0.0:
            raise ValueError("profile Q-prime values must be positive")
        if previous_end is not None and start < previous_end:
            raise ValueError("profile intervals must be ordered and non-overlapping")
        length = float(end - start)
        if not isfinite(length) or length <= 0.0:
            raise ValueError("profile interval lengths must be finite and positive")
        lengths.append(length)
        values.append(float(value))
        previous_end = float(end)

    total_length = _finite_sum(lengths, "total profile support exceeds finite numerical range")
    if total_length <= 0.0:
        raise ValueError("profile must contain positive-length support")

    observed_lengths: list[list[float]] = [[] for _ in range(len(edges) - 1)]
    proximity_sums: list[list[float]] = [[] for _ in range(len(edges) - 1)]
    for length, value in zip(lengths, values):
        observed_index = bisect_left(edges, value) - 1
        if 0 <= observed_index < len(observed_lengths):
            observed_lengths[observed_index].append(length)
        for bin_index, (lower, upper) in enumerate(zip(edges, edges[1:])):
            weight = _proximity(value, lower, upper, bin_index)
            proximity_sums[bin_index].append(length * weight)

    bins = tuple(
        BinCoverage(
            bin_index=index,
            observed_length=_finite_sum(
                observed_lengths[index], "observed profile support exceeds finite numerical range",
            ),
            proximity=_finite_sum(
                proximity_sums[index], "profile proximity exceeds finite numerical range",
            ) / total_length,
        )
        for index in range(len(observed_lengths))
    )
    return bins, total_length


def audit_profile(
    intervals: tuple[ProfileInterval, ...], grid: CoverageGrid,
) -> tuple[BinCoverage, ...]:
    edges = _edge_values(grid)
    bins, _ = _audit_profile(intervals, edges)
    return bins


def audit_simulation(result: SimulationResult, grid: CoverageGrid) -> CoverageResult:
    """Audit all independent borehole and tunnel profiles without joining chainages."""
    if not isinstance(result, SimulationResult):
        raise TypeError("result must be a SimulationResult")
    if not isinstance(result.signature_id, str) or not result.signature_id.strip():
        raise ValueError("simulation signature_id must not be empty")
    if isinstance(result.seed, bool) or not isinstance(result.seed, int) or result.seed < 0:
        raise ValueError("simulation seed must be a non-negative integer")

    edges = _edge_values(grid)
    profile_groups = [borehole.intervals for borehole in result.boreholes]
    profile_groups.append(result.tunnel.intervals)
    audited_profiles = [
        _audit_profile(intervals, edges)
        for intervals in profile_groups
        if intervals
    ]
    if not audited_profiles:
        raise ValueError("simulation contains no positive-length profile support")

    total_length = _finite_sum(
        [support for _, support in audited_profiles],
        "total simulation profile support exceeds finite numerical range",
    )
    bin_count = len(edges) - 1
    bins = tuple(
        BinCoverage(
            bin_index=index,
            observed_length=_finite_sum(
                [profile_bins[index].observed_length for profile_bins, _ in audited_profiles],
                "observed simulation support exceeds finite numerical range",
            ),
            proximity=_finite_sum(
                [
                    profile_bins[index].proximity * support
                    for profile_bins, support in audited_profiles
                ],
                "simulation proximity exceeds finite numerical range",
            ) / total_length,
        )
        for index in range(bin_count)
    )
    observed_bins = frozenset(
        item.bin_index for item in bins if item.observed_length > 0.0
    )
    return CoverageResult(result.signature_id, result.seed, grid, bins, observed_bins)


def _validate_coverage_result(result: CoverageResult) -> None:
    if not isinstance(result, CoverageResult):
        raise TypeError("coverage result must be a CoverageResult")
    if not isinstance(result.signature_id, str) or not result.signature_id.strip():
        raise ValueError("coverage signature_id must not be empty")
    if isinstance(result.seed, bool) or not isinstance(result.seed, int) or result.seed < 0:
        raise ValueError("coverage seed must be a non-negative integer")
    edges = _edge_values(result.grid)
    if not isinstance(result.bins, tuple) or len(result.bins) != len(edges) - 1:
        raise ValueError("coverage bins must match the grid")
    if not isinstance(result.observed_bins, frozenset):
        raise TypeError("observed_bins must be a frozenset")

    expected_observed: set[int] = set()
    for index, item in enumerate(result.bins):
        if not isinstance(item, BinCoverage):
            raise TypeError("coverage bins must contain BinCoverage values")
        if (
            isinstance(item.bin_index, bool)
            or not isinstance(item.bin_index, int)
            or item.bin_index != index
        ):
            raise ValueError("coverage bin indices must match their grid positions")
        if (
            isinstance(item.observed_length, bool)
            or not isinstance(item.observed_length, Real)
            or not isfinite(item.observed_length)
            or item.observed_length < 0.0
        ):
            raise ValueError("observed lengths must be finite and non-negative")
        if (
            isinstance(item.proximity, bool)
            or not isinstance(item.proximity, Real)
            or not isfinite(item.proximity)
            or not 0.0 <= item.proximity <= 1.0
        ):
            raise ValueError("proximity must be finite and between zero and one")
        if item.observed_length > 0.0:
            expected_observed.add(index)

    if any(
        isinstance(index, bool) or not isinstance(index, int)
        or not 0 <= index < len(result.bins)
        for index in result.observed_bins
    ):
        raise ValueError("observed bin indices must be within the grid")
    if result.observed_bins != frozenset(expected_observed):
        raise ValueError("observed_bins must match positive observed lengths")


def parent_gaps(parent: CoverageResult) -> frozenset[int]:
    _validate_coverage_result(parent)
    return frozenset(
        index for index in range(len(parent.bins))
        if index not in parent.observed_bins
    )


def score_pair(
    parent: CoverageResult, candidate: CoverageResult, gaps: frozenset[int],
) -> PairedScore:
    _validate_coverage_result(parent)
    _validate_coverage_result(candidate)
    if parent.seed != candidate.seed:
        raise ValueError("parent and candidate must use the same seed")
    if parent.grid.grid_id != candidate.grid.grid_id or parent.grid.edges != candidate.grid.edges:
        raise ValueError("parent and candidate must use the same coverage grid")
    if not isinstance(gaps, frozenset):
        raise TypeError("gaps must be a frozenset")
    if any(
        isinstance(index, bool) or not isinstance(index, int)
        or not 0 <= index < len(parent.bins)
        for index in gaps
    ):
        raise ValueError("gap bin indices must be within the grid")
    expected_gaps = parent_gaps(parent)
    if gaps != expected_gaps:
        raise ValueError("gaps must be the unobserved bins of the paired parent")

    if gaps:
        proximity_delta = _finite_sum(
            [
                candidate.bins[index].proximity - parent.bins[index].proximity
                for index in sorted(gaps)
            ],
            "paired proximity delta exceeds finite numerical range",
        ) / len(gaps)
        new_occupancy_fraction = len(gaps & candidate.observed_bins) / len(gaps)
    else:
        proximity_delta = 0.0
        new_occupancy_fraction = 0.0
    delta_score = 0.5 * proximity_delta + 0.5 * new_occupancy_fraction
    if not all(isfinite(value) for value in (
        proximity_delta, new_occupancy_fraction, delta_score,
    )):
        raise ValueError("paired coverage score exceeds finite numerical range")
    return PairedScore(
        seed=parent.seed,
        parent_signature_id=parent.signature_id,
        candidate_signature_id=candidate.signature_id,
        grid_id=parent.grid.grid_id,
        parent_gap_bins=gaps,
        proximity_delta=proximity_delta,
        new_occupancy_fraction=new_occupancy_fraction,
        delta_score=delta_score,
        parent_observed_count=len(parent.observed_bins),
        candidate_observed_count=len(candidate.observed_bins),
    )
