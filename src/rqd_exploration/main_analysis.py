"""BH-only inverse targets, paired effects and disjoint-group stability."""

from dataclasses import dataclass
from fractions import Fraction
from math import exp, isfinite

from .analysis import BIN_EDGES, calculate_scenario_scores
from .config import EXECUTABLE_JN_SET_COUNTS, JA_VALUES, JR_VALUES


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
class PairedEffect:
    status: str
    delta_distance_rqd: float | None
    delta_support_fraction: float | None
    common_support_m: float
    common_reference_fraction: float | None
    reason: str | None = None


def paired_progress(reference, candidate, target):
    if reference.seed != candidate.seed or reference.seed < 44:
        raise ValueError("candidate/reference require the same verification seed >=44")
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


@dataclass(frozen=True)
class GroupComparison:
    seeds_a: tuple[int, ...]
    seeds_b: tuple[int, ...]
    eligible: bool
    passed: bool
    maximum_cdf_difference: float | None
    support_difference: float | None
    support_fraction_a: float | None
    support_fraction_b: float | None
    common_support_m: float
    reason: str | None = None


def compare_groups(a, b, target):
    seeds_a, seeds_b = tuple(p.seed for p in a), tuple(p.seed for p in b)
    if (len(a) != 3 or len(b) != 3 or len(set(seeds_a + seeds_b)) != 6
        or any(s < 44 for s in seeds_a + seeds_b)):
        raise ValueError("stability requires disjoint three-seed groups excluding seed43")
    common = common_profiles(a + b)
    if not common:
        return GroupComparison(seeds_a, seeds_b, False, False, None, None,
                               None, None, 0, "no common valid positive BH support")
    metrics = [_metrics(p, target) for p in common]
    if any(m is None for m in metrics):
        return GroupComparison(seeds_a, seeds_b, False, False, None, None,
                               None, None, 0, "no positive BH support")
    values = sorted({calculate_scenario_scores(
        p.raw_rqd, target.fixed_jn, jr_values=(target.jr,), ja_values=(target.ja,)
    )[0].qprime for profile in common for p in profile.points})
    def cdf(profile, q):
        return sum((_fraction(p.support_m) for p in profile.points
                    if calculate_scenario_scores(
                        p.raw_rqd, target.fixed_jn, jr_values=(target.jr,),
                        ja_values=(target.ja,))[0].qprime <= q), Fraction()) / _metrics(profile, target)[2]
    maximum = max(abs(sum((cdf(p, q) for p in common[:3]), Fraction()) / 3
                      - sum((cdf(p, q) for p in common[3:]), Fraction()) / 3)
                  for q in values)
    fa = sum((m[1] for m in metrics[:3]), Fraction()) / 3
    fb = sum((m[1] for m in metrics[3:]), Fraction()) / 3
    difference = abs(fa - fb)
    passed = maximum <= Fraction(".10") and difference <= Fraction(".10") and fa > 0 and fb > 0
    return GroupComparison(seeds_a, seeds_b, True, passed, float(maximum),
                           float(difference), float(fa), float(fb), float(metrics[0][2]),
                           None if passed else "stability mismatch or zero target support")


@dataclass(frozen=True)
class StabilityHistory:
    stable: bool
    consecutive_passes: int
    comparisons: tuple[GroupComparison, ...]
    next_seed: int
    incomparable: bool = False


def stability_history(profiles, target):
    by_seed = {p.seed: p for p in profiles if p.seed >= 44}
    if len(by_seed) != len([p for p in profiles if p.seed >= 44]):
        raise ValueError("duplicate verification seed")
    groups = []
    next_seed = 44
    while all(next_seed + i in by_seed for i in range(3)):
        groups.append(tuple(by_seed[next_seed + i] for i in range(3)))
        next_seed += 3
    comparisons, passes = [], 0
    for a, b in zip(groups, groups[1:]):
        comparison = compare_groups(a, b, target)
        comparisons.append(comparison)
        if not comparison.eligible:
            return StabilityHistory(False, 0, tuple(comparisons), next_seed, True)
        passes = passes + 1 if comparison.passed else 0
        if passes >= 2:
            return StabilityHistory(True, passes, tuple(comparisons), next_seed)
    return StabilityHistory(False, passes, tuple(comparisons), next_seed)


def target_complete(histories):
    return sum(h.stable for h in histories.values()) >= 3
