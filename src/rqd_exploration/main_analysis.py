"""BH-only inverse targets, seed pass evidence and paired candidate effects."""

from dataclasses import dataclass
from fractions import Fraction
from math import exp, isfinite

from .analysis import BIN_EDGES, calculate_scenario_scores
from .config import EXECUTABLE_JN_SET_COUNTS, JA_VALUES, JR_VALUES


VERIFICATION_SEED_COUNT = 3
REQUIRED_VERIFICATION_PASSES = 2


def physical_rqd_floor(jn):
    x = .1 * 10 * EXECUTABLE_JN_SET_COUNTS[jn]
    return round(max(10., 100 * exp(-x) * (1 + x)), 1)


@dataclass(frozen=True)
class Target:
    bin_id: str
    fixed_jn: float
    jr: float
    ja: float
    profile_id: str

    def __post_init__(self):
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
                for v in (self.fixed_jn, self.jr, self.ja))
            or self.bin_id not in tuple(str(i) for i in range(1, 11))
            or self.fixed_jn not in EXECUTABLE_JN_SET_COUNTS
            or self.jr not in JR_VALUES or self.ja not in JA_VALUES
            or not isinstance(self.profile_id, str) or not self.profile_id.strip()):
            raise ValueError("target must use the approved primary bin/Jn/Jr/Ja catalog")

    @property
    def key(self):
        return f"{self.bin_id}/{self.fixed_jn:g}/{self.jr:g}/{self.ja:g}/{self.profile_id}"

    @property
    def rqd_lower(self):
        return BIN_EDGES[int(self.bin_id) - 1] * self.fixed_jn * self.ja / self.jr

    @property
    def rqd_upper(self):
        return BIN_EDGES[int(self.bin_id)] * self.fixed_jn * self.ja / self.jr

    @property
    def reachable(self):
        return self.rqd_upper >= physical_rqd_floor(self.fixed_jn) and self.rqd_lower < 100

    def contains(self, raw_rqd):
        return calculate_scenario_scores(raw_rqd, self.fixed_jn,
                                        jr_values=(self.jr,), ja_values=(self.ja,))[0].bin_id == self.bin_id

    def distance(self, raw_rqd):
        value = max(raw_rqd, 10.)
        return max(self.rqd_lower - value, value - self.rqd_upper, 0.)


def build_targets(profile_id: str, *, jn_values: tuple[float, ...] | None = None):
    values = tuple(EXECUTABLE_JN_SET_COUNTS) if jn_values is None else jn_values
    if not values or len(set(values)) != len(values) or any(
        jn not in EXECUTABLE_JN_SET_COUNTS for jn in values
    ):
        raise ValueError("target Jn values must be distinct executable conditions")
    return tuple(Target(str(b), jn, jr, ja, profile_id)
                 for b in range(10, 0, -1) for jn in values
                 for jr in JR_VALUES for ja in JA_VALUES)


@dataclass(frozen=True)
class BHPoint:
    start_m: float
    end_m: float
    raw_rqd: float
    support_m: float

    def __post_init__(self):
        if (not all(not isinstance(v, bool) and isinstance(v, (int, float)) and isfinite(v) for v in (
            self.start_m, self.end_m, self.raw_rqd, self.support_m))
            or self.end_m <= self.start_m or not 0 <= self.raw_rqd <= 100
            or self.support_m < 0 or self.support_m > self.end_m - self.start_m):
            raise ValueError("invalid physical BH observation")


@dataclass(frozen=True)
class SeedProfile:
    seed: int
    points: tuple[BHPoint, ...]

    def __post_init__(self):
        if (type(self.seed) is not int or not 0 <= self.seed <= 2**53 - 1
            or not isinstance(self.points, tuple) or any(not isinstance(p, BHPoint) for p in self.points)):
            raise ValueError("seed profile requires a safe integer seed and typed BH points")


def _valid(profile):
    points = sorted((p for p in profile.points
                     if p.support_m >= 1 and p.end_m - p.start_m >= 1),
                    key=lambda p: (p.start_m, p.end_m))
    if any(a.end_m > b.start_m for a, b in zip(points, points[1:])):
        raise ValueError("overlapping BH observation units are ambiguous")
    return tuple(points)


def common_profiles(profiles, *, paired=False):
    """Intersect physical units, never allocate an RQD to a sub-metre fragment."""
    if not profiles:
        return ()
    valid = [_valid(p) for p in profiles]
    if any(not p for p in valid):
        return ()
    segments = [(p.start_m, p.end_m, (p,)) for p in valid[0]]
    for points in valid[1:]:
        segments = [(max(start, p.start_m), min(end, p.end_m), prior + (p,))
                    for start, end, prior in segments for p in points
                    if min(end, p.end_m) - max(start, p.start_m) >= 1]
    if not segments:
        return ()
    return tuple(SeedProfile(profile.seed, tuple(
        BHPoint(start, end, prior[index].raw_rqd,
                min(end - start, *(p.support_m for p in prior)) if paired
                else min(end - start, prior[index].support_m))
        for start, end, prior in segments)) for index, profile in enumerate(profiles))


def _fraction(value):
    return Fraction(str(value))


def _metrics(profile, target):
    points = _valid(profile)
    total = sum((_fraction(p.support_m) for p in points), Fraction())
    if total <= 0:
        return None
    distance = sum((_fraction(p.support_m) * _fraction(target.distance(p.raw_rqd))
                    for p in points), Fraction()) / total
    support = sum((_fraction(p.support_m) for p in points
                   if target.contains(p.raw_rqd)), Fraction()) / total
    return distance, support, total


def seed_metrics(profile, target):
    result = _metrics(profile, target)
    return None if result is None else tuple(float(v) for v in result)


@dataclass(frozen=True)
class SeedPassResult:
    initial_seed: int
    verification_seeds: tuple[int, int, int]
    initial_positive_support: bool | None
    verification_positive_support: tuple[bool | None, bool | None, bool | None]
    complete: bool
    passed: bool

    @property
    def positive_verification_count(self):
        return sum(value is True for value in self.verification_positive_support)


def _has_positive_target_support(profile, target):
    metrics = _metrics(profile, target)
    return metrics is not None and metrics[1] > 0


def seed_pass_result(profiles, target, *, initial_seed, verification_seed):
    if (type(initial_seed) is not int or type(verification_seed) is not int
        or not 0 <= initial_seed <= 2**53 - 1
        or not 0 <= verification_seed <= 2**53 - VERIFICATION_SEED_COUNT):
        raise ValueError("initial and verification seeds must be distinct safe integers")
    verification_seeds = tuple(
        range(verification_seed, verification_seed + VERIFICATION_SEED_COUNT))
    if initial_seed in verification_seeds:
        raise ValueError("initial seed must not be a verification seed")

    by_seed = {}
    for profile in profiles:
        if profile.seed in by_seed:
            raise ValueError("duplicate seed profile")
        by_seed[profile.seed] = profile

    initial = by_seed.get(initial_seed)
    initial_positive = (
        None if initial is None else _has_positive_target_support(initial, target)
    )
    verification = tuple(
        None if seed not in by_seed else _has_positive_target_support(by_seed[seed], target)
        for seed in verification_seeds
    )
    complete = initial_positive is not None and all(value is not None for value in verification)
    passed = (complete and initial_positive
              and sum(value is True for value in verification) >= REQUIRED_VERIFICATION_PASSES)
    return SeedPassResult(initial_seed, verification_seeds, initial_positive,
                          verification, complete, passed)


def target_passed(pass_results):
    results = tuple(pass_results.values())
    if any(not isinstance(result, SeedPassResult) for result in results):
        raise TypeError("target pass requires SeedPassResult values")
    return any(result.passed for result in results)


@dataclass(frozen=True)
class PairedEffect:
    status: str
    delta_distance_rqd: float | None
    delta_support_fraction: float | None
    common_support_m: float
    common_reference_fraction: float | None
    reason: str | None = None


def paired_progress(reference, candidate, target):
    if reference.seed != candidate.seed:
        raise ValueError("candidate/reference require the same realization seed")
    profiles = common_profiles((reference, candidate), paired=True)
    original = _metrics(reference, target)
    if not profiles or original is None:
        return PairedEffect("incomparable", None, None, 0, None,
                            "no common valid BH comparison units >=1m")
    ref, cand = (_metrics(p, target) for p in profiles)
    if ref is None or cand is None:
        return PairedEffect("incomparable", None, None, 0, None, "no positive support")
    dd, ds = cand[0] - ref[0], cand[1] - ref[1]
    distance_improved, support_improved = dd <= -1, ds >= Fraction("0.01")
    distance_adverse, support_adverse = dd >= 1, ds <= -Fraction("0.01")
    improved = distance_improved or support_improved
    adverse = distance_adverse or support_adverse
    progress = (distance_improved and ds >= 0) or (support_improved and dd <= 0)
    status = ("progress" if progress else "conflict" if improved
              else "adverse" if adverse else "same")
    return PairedEffect(status, float(dd), float(ds), float(ref[2]),
                        float(ref[2] / original[2]))


def progress_decision(statuses):
    if len(statuses) not in (3, 5) or any(
        s not in {"progress", "same", "adverse", "conflict", "incomparable"}
        for s in statuses
    ):
        raise ValueError("progress requires exactly the prescribed three or five seeds")
    count = statuses.count("progress")
    if len(statuses) == 3:
        return "progress" if count >= 2 else "extend" if count == 1 else "no_progress"
    if statuses[:3].count("progress") != 1:
        raise ValueError("five-seed confirmation requires exactly one initial progress seed")
    return "progress" if count >= 3 else "no_progress"
