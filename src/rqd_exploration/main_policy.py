"""Approved T011 operating policy; loading and preview never authorize execution."""

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from pathlib import Path

import yaml
from src.euler_campaign.generation import FIXED_DOMAIN_GENERATOR_VERSION

from .analysis import (
    ANALYSIS_IMPLEMENTATION_VERSION, BIN_CATALOG_ID, BIN_EDGES, CALCULATION_RQD_FLOOR,
)
from .config import (
    EXECUTABLE_JN_SET_COUNTS, JA_VALUES, JR_VALUES, DesignInput, NormalizedPilotInput,
    _UniqueKeySafeLoader, _fields, load_config,
)
from .fingerprint import fingerprint_snapshot


MAIN_IMPLEMENTATION_VERSION = "qsimex-t011-main-v2-stationary-p32"
MAXIMUM_STARTS = 20_000
REVIEW_CHECKPOINT_STARTS = 10_000
AXES = (
    ("p32_m2_per_m3", .1, 1., .01, 10., True),
    ("size_r_min_m", .1, 1., 1., 150., True),
    ("size_r_max_m", .1, 1., 1., 150., True),
    ("mean_dip_deg", 5., 15., 0., 90., True),
    ("mean_dip_dir_deg", 5., 15., 0., 360., False),
)


@dataclass(frozen=True)
class MainPolicy:
    group_size: int = 3
    consecutive_passes: int = 2
    stability_tolerance: float = .10
    required_inputs: int = 3
    distance_step_rqd: float = 1.
    support_step_fraction: float = .01
    initial_seed: int = 43
    verification_seed: int = 44
    single_axis_candidates: int = 8
    multi_axis_candidates: int = 2
    lhs_candidates: int = 2
    progress_inputs_per_round: int = 2
    stability_inputs_per_round: int = 1
    stagnant_rounds: int = 3
    maximum_starts: int = MAXIMUM_STARTS
    review_checkpoint_starts: int | None = REVIEW_CHECKPOINT_STARTS
    maximum_expected_joints: int = 10_000_000
    automatic_retries: int = 0

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not type(item.default) or value != item.default:
                raise ValueError(f"{item.name} must equal approved value {item.default!r}")


@dataclass(frozen=True)
class MainConfig:
    policy: MainPolicy
    initial: NormalizedPilotInput | None
    baselines: tuple[NormalizedPilotInput, ...]
    rng_seed: int
    source_yaml_bytes: bytes
    source_reference: str
    fingerprint: str
    snapshot_json: str

    @property
    def templates(self) -> dict[float, DesignInput]:
        inputs = self.baselines + (() if self.initial is None else (self.initial,))
        return {d.fixed_jn: d for c in inputs for d in c.designs}

    @property
    def reference_input(self) -> NormalizedPilotInput:
        return self.baselines[0] if self.initial is None else self.initial


def load_main_config(path: Path | str) -> MainConfig:
    path = Path(path).resolve()
    source = path.read_bytes()
    root = _fields(yaml.load(source, Loader=_UniqueKeySafeLoader), "main",
                   {"schema_version", "policy", "initial_input", "baseline_inputs", "rng_seed"})
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ValueError("main schema_version must be 1")
    policy = MainPolicy(**_fields(root["policy"], "policy",
                                {f.name for f in fields(MainPolicy)}))
    if type(root["rng_seed"]) is not int or not 0 <= root["rng_seed"] < 2**32:
        raise ValueError("rng_seed must be an unsigned 32-bit integer")
    if root["initial_input"] is not None and not isinstance(root["initial_input"], str):
        raise TypeError("initial_input must be a YAML path or null to exclude Jn20")
    paths = root["baseline_inputs"]
    if not isinstance(paths, list) or len(paths) != 2 or any(
        not isinstance(p, str) for p in paths
    ):
        raise ValueError("baseline_inputs must contain the two main baseline YAML paths")
    initial = (None if root["initial_input"] is None
               else load_config(path.parent / root["initial_input"]))
    baselines = tuple(load_config(path.parent / p) for p in paths)
    if initial is not None:
        if len(initial.designs) != 1:
            raise ValueError("Jn20 initial input requires one design")
        design = initial.designs[0]
        if (design.fixed_jn, len(design.joint_sets), design.sample_count,
            design.design_seed, design.realization_seed) != (20, 5, 5, 40, 43):
            raise ValueError("Jn20 requires five sets, LHS5, design seed40 and realization43")
    baseline_templates = {d.fixed_jn for c in baselines for d in c.designs}
    if baseline_templates != {2., 4., 9., 15.} or sum(len(c.designs) for c in baselines) != 4:
        raise ValueError("main baselines require exactly Jn2/4/9/15 templates")
    inputs = baselines + (() if initial is None else (initial,))
    reference = baselines[0]
    for config in inputs:
        if config.geometry != reference.geometry or config.measurements != reference.measurements:
            raise ValueError("main and baseline geometry/measurements must match")
        if config.measurements.bh_interval_m < 1:
            raise ValueError("main BH comparison units must be at least 1m")
        for d in config.designs:
            if (d.mean_dip_deg.lower, d.mean_dip_deg.upper,
                d.mean_dip_dir_deg.lower, d.mean_dip_dir_deg.upper,
                d.size_alpha.bounds.lower, d.size_alpha.bounds.upper,
                d.fisher_kappa.bounds.lower, d.fisher_kappa.bounds.upper) != (
                    0, 90, 0, 360, 2.5, 4, 0, 50):
                raise ValueError("main requires the approved full orientation/shape bounds")
            for s in d.joint_sets:
                if (s.p32.lower, s.p32.upper, s.size_r_min_m.lower,
                    s.size_r_min_m.upper, s.size_r_max_m.lower,
                    s.size_r_max_m.upper) != (.01, 10, 1, 150, 1, 150):
                    raise ValueError("main requires the approved P32/radius bounds")
    payload = {
        "schema_version": 1, "policy": asdict(policy), "rng_seed": root["rng_seed"],
        "implementation_version": MAIN_IMPLEMENTATION_VERSION,
        "generator_version": FIXED_DOMAIN_GENERATOR_VERSION,
        "reachability_floor": "round(max(10,100*exp(-n_sets)*(1+n_sets)),1); per-set P32<=10",
        "analysis_version": ANALYSIS_IMPLEMENTATION_VERSION,
        "bin_catalog": {"id": BIN_CATALOG_ID, "edges": BIN_EDGES,
                        "boundary_rule": "(lower,upper]", "calculation_rqd_floor": CALCULATION_RQD_FLOOR},
        "Jn_set_counts": {str(jn): count for jn, count in EXECUTABLE_JN_SET_COUNTS.items()},
        "Jr_values": JR_VALUES, "Ja_values": JA_VALUES,
        "axis_steps_bounds": [
            {"axis": name, "small_step": small, "large_step": large,
             "lower": lower, "upper": upper, "upper_inclusive": inclusive,
             "unit": "m^2/m^3" if name.startswith("p32") else
                     "degree" if name.startswith("mean_dip") else "m"}
            for name, small, large, lower, upper, inclusive in AXES],
        "yaml_sha256": sha256(source).hexdigest(),
        "initial_yaml_sha256": None if initial is None else initial.source_yaml_sha256,
        "active_Jn": sorted(d.fixed_jn for c in inputs for d in c.designs),
        "baseline_yaml_sha256": [c.source_yaml_sha256 for c in baselines],
    }
    fingerprint = fingerprint_snapshot(payload)
    return MainConfig(policy, initial, baselines, root["rng_seed"], source, str(path),
                      fingerprint.sha256_hex, fingerprint.canonical_bytes.decode())
