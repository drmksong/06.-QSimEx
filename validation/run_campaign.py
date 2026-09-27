"""Run an isolated QSimEx validation campaign.

The campaign owns its configs, runner outputs, audits, and ledger under one
work directory. It never reads prior production result directories.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

# Allow execution from the QSimEx repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.core.coverage_rounds import audit_borehole_records, append_ledger, build_round_record
from src.core.signature_candidates import (
    apply_normalized_features,
    build_euler_update_candidate_from_probes,
    compute_domain_id,
    compute_generation_signature_hash,
    extract_normalized_features,
    load_case_mapping,
)
from src.core.profile_exploration import (
    audit_qprime_coverage,
    load_csv_records,
    search_profile_boundaries,
)
from src.core.qprime_cutoff_search import generate_qprime_cutoffs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--seed-start", type=int, required=True)
    parser.add_argument("--seed-stop", type=int, required=True)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--backend", default="mlx")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--euler-spec",
        help="JSON spec containing case_path, feature_bounds, probes, and step_size",
    )
    return parser.parse_args(argv)


def build_iteration_config(
    case_paths: list[str],
    *,
    output_dir: Path,
    seed_start: int,
    seed_stop: int,
    backend: str,
) -> dict:
    return {
        "profile_mc_exploration": {
            "case_paths": case_paths,
            "seed_range": {"start": seed_start, "stop": seed_stop, "step": 1},
            "face_positions": [10, 20, 30],
            "borehole_window": 3,
            "backend": backend,
            "batch_size": 100,
            "correction_mode": "pure",
            "output_dir": str(output_dir),
            "save_each_case": True,
            "save_combined": True,
            "checkpoint_on_seed": True,
            "verbose": True,
        }
    }


def observed_euler_probe(
    records: list[dict],
    *,
    parent_path: str,
    probe_path: str,
    feature_bounds: dict[str, tuple[float, float]],
    target_bins: list[int],
    cutoffs: list[float],
) -> dict:
    """Measure a reviewed one-feature probe from paired, same-seed simulations."""
    parent = load_case_mapping(parent_path)
    probe = load_case_mapping(probe_path)
    parent_name = parent.get("name", Path(parent_path).stem)
    probe_name = probe.get("name", Path(probe_path).stem)
    if parent_name == probe_name:
        raise ValueError("parent and probe case names must differ")
    before = extract_normalized_features(parent, feature_bounds)
    after = extract_normalized_features(probe, feature_bounds)
    feature_delta = {
        name: after[name] - value for name, value in before.items()
        if after[name] != value
    }
    if len(feature_delta) != 1 or compute_generation_signature_hash(
        apply_normalized_features(parent, after, feature_bounds)
    ) != compute_generation_signature_hash(probe):
        raise ValueError("probe must change exactly one reviewed generation feature")
    if not target_bins or any(index < 0 or index >= len(cutoffs) - 1 for index in target_bins):
        raise ValueError("target_bins must contain valid indices on the update grid")

    observations = {}
    for name in (parent_name, probe_name):
        selected = [row for row in records if row.get("case_name") == name]
        seeds = {str(row["seed"]) for row in selected if row.get("seed") not in (None, "")}
        hashes = {row.get("generation_signature_hash") for row in selected}
        if not seeds or len(hashes) != 1 or None in hashes or "" in hashes:
            raise ValueError(f"missing or ambiguous simulation provenance for {name}")
        observations[name] = (selected, seeds, hashes.pop())
    if observations[parent_name][1] != observations[probe_name][1]:
        raise ValueError("parent and probe must share the same seed set")
    if observations[parent_name][2] == observations[probe_name][2]:
        raise ValueError("probe must generate a distinct signature")

    physical_response = {}
    seed_responses = {seed: {} for seed in observations[parent_name][1]}
    for field in (
        "Qp_bh_mean", "RQD_bh_mean", "borehole_n_intersections_sum",
        "borehole_plane_angle_mean_deg",
    ):
        means = {}
        for name, (selected, seeds, _) in observations.items():
            per_seed = []
            for seed in seeds:
                values = [
                    float(row[field]) for row in selected
                    if str(row["seed"]) == seed and row.get(field) not in (None, "", "nan")
                ]
                if values:
                    per_seed.append(sum(values) / len(values))
            if len(per_seed) == len(seeds):
                means[name] = sum(per_seed) / len(per_seed)
        if len(means) == 2:
            physical_response[field] = means[probe_name] - means[parent_name]
            for seed in seed_responses:
                per_case = {}
                for name, (selected, _, _) in observations.items():
                    values = [
                        float(row[field]) for row in selected
                        if str(row["seed"]) == seed and row.get(field) not in (None, "", "nan")
                    ]
                    per_case[name] = sum(values) / len(values)
                seed_responses[seed][field] = per_case[probe_name] - per_case[parent_name]
    if any("dip" in name or "kappa" in name for name in feature_delta):
        if "borehole_plane_angle_mean_deg" not in physical_response:
            raise ValueError("orientation probe requires measured borehole-plane angle")
        if physical_response["borehole_plane_angle_mean_deg"] == 0.0:
            raise ValueError("orientation probe did not change measured borehole-plane angle")

    frequencies = {}
    for name, (selected, seeds, _) in observations.items():
        per_seed = []
        for seed in sorted(seeds):
            audit = audit_qprime_coverage(
                [row for row in selected if str(row["seed"]) == seed],
                cutoffs=cutoffs,
            )
            per_seed.append([float(row["n_records"] > 0) for row in audit["bins"]])
        frequencies[name] = [
            sum(bin_values) / len(seeds) for bin_values in zip(*per_seed)
        ]
    distances = {}
    for name, (selected, seeds, _) in observations.items():
        per_seed_distances = []
        for seed in seeds:
            audit = audit_qprime_coverage(
                [row for row in selected if str(row["seed"]) == seed], cutoffs=cutoffs
            )
            observed_bins = [row["bin_index"] for row in audit["bins"] if row["n_records"]]
            if not observed_bins:
                raise ValueError(f"no in-range Q' bins for {name} at seed {seed}")
            per_seed_distances.append(sum(
                min(abs(index - target) for index in observed_bins)
                for target in target_bins
            ) / len(target_bins))
        distances[name] = sum(per_seed_distances) / len(seeds)
    nearer, farther = sorted((parent_name, probe_name), key=lambda name: distances[name])
    near_bins = frequencies[nearer]
    far_bins = frequencies[farther]
    feature_delta = {
        name: (after[name] - before[name]) * (1 if nearer == probe_name else -1)
        for name in feature_delta
    }
    coverage_delta = {
        f"bin_{index}": near_bins[index] - observed
        for index, observed in enumerate(far_bins)
    }
    coverage_delta["proximity_gain"] = distances[farther] - distances[nearer]
    residual = {"proximity_gain": distances[nearer]}
    return {
        "feature_delta": feature_delta,
        "coverage_delta": coverage_delta,
        "coverage_residual": residual,
        "physical_response": physical_response,
        "seed_physical_responses": seed_responses,
        "source_case_path": probe_path if nearer == probe_name else parent_path,
        "nearest_observed_bin": min(
            (index for index, value in enumerate(near_bins) if value > 0),
            key=lambda index: min(abs(index - target) for target in target_bins),
        ),
        "distance_to_target": distances[nearer],
        "parent_case": parent_name,
        "probe_case": probe_name,
        "seed_values": sorted(observations[parent_name][1]),
        "parent_signature_hash": observations[parent_name][2],
        "probe_signature_hash": observations[probe_name][2],
    }


def assess_physical_probe(probe: dict) -> dict:
    """Use measured responses to qualify one local update, not to set cutoffs."""
    feature, delta = next(iter(probe["feature_delta"].items()))
    response = probe["physical_response"]
    fields = ("Qp_bh_mean", "RQD_bh_mean", "borehole_n_intersections_sum")
    missing = [field for field in fields if field not in response]
    if missing:
        return {"status": "needs_measurement", "missing_metrics": missing}
    if (feature.endswith(".P32") or feature.endswith(".mean_spacing")) and response["borehole_n_intersections_sum"] == 0.0:
        return {"status": "no_intersection_response", "feature": feature}
    if response["Qp_bh_mean"] == 0.0 and response["RQD_bh_mean"] == 0.0:
        return {"status": "no_quality_response", "feature": feature}
    orientation = any(word in feature for word in ("dip", "kappa"))
    for field in ("Qp_bh_mean", "borehole_plane_angle_mean_deg" if orientation else "borehole_n_intersections_sum"):
        changes = [
            entry[field] for entry in probe.get("seed_physical_responses", {}).values()
            if field in entry
        ]
        if len(changes) > 1 and min(changes) < 0.0 < max(changes):
            return {"status": "needs_repeatability", "feature": feature, "conflicting_metric": field}
    if orientation:
        angle_change = response.get("borehole_plane_angle_mean_deg")
        if angle_change is None or angle_change == 0.0:
            return {"status": "needs_measured_angle_response", "feature": feature}
    sensitivities = {field: response[field] / delta for field in fields}
    angle_change = response.get("borehole_plane_angle_mean_deg")
    if orientation and angle_change is not None and angle_change != 0.0:
        sensitivities["Qp_bh_mean_per_plane_angle_deg"] = response["Qp_bh_mean"] / angle_change
        sensitivities["intersections_per_plane_angle_deg"] = response["borehole_n_intersections_sum"] / angle_change
    return {
        "status": "observed_local_response",
        "feature": feature,
        "delta_normalized_feature": delta,
        "sensitivity_per_normalized_feature": sensitivities,
    }


def build_density_reachability_probe(
    parent_path: str,
    probe_path: str,
    *,
    feature_bounds: dict[str, tuple[float, float]],
    round_id: int,
    target_region: str,
    screening_seed: int,
    generator_version: str,
) -> dict | None:
    """Extend a reviewed density probe without inventing a coverage gradient."""
    parent = load_case_mapping(parent_path)
    probe = load_case_mapping(probe_path)
    before = extract_normalized_features(parent, feature_bounds)
    after = extract_normalized_features(probe, feature_bounds)
    changes = {
        name: after[name] - value for name, value in before.items()
        if after[name] != value
    }
    if len(changes) != 1:
        raise ValueError("density reachability requires a one-feature probe")
    feature, feature_delta = next(iter(changes.items()))
    if not (feature.endswith(".P32") or feature.endswith(".mean_spacing")):
        raise ValueError("density reachability requires P32 or mean_spacing")
    if compute_generation_signature_hash(
        apply_normalized_features(parent, after, feature_bounds)
    ) != compute_generation_signature_hash(probe):
        raise ValueError("density reachability cannot change other generation features")

    origin = probe.get("tags", {}).get("density_probe_origin_normalized", before[feature])
    next_value = min(1.0, max(0.0, after[feature] + (after[feature] - origin)))
    if next_value == after[feature]:
        return None
    candidate_case = apply_normalized_features(
        probe, {feature: next_value}, feature_bounds
    )
    signature_hash = compute_generation_signature_hash(candidate_case)
    candidate_id = f"r{round_id:03d}-density-probe-{signature_hash[:12]}"
    candidate_case["name"] = f"{probe.get('name', Path(probe_path).stem)}__{candidate_id}"
    candidate_case["seed"] = int(screening_seed)
    candidate_case.setdefault("tags", {}).update({
        "candidate_id": candidate_id,
        "coverage_target": target_region,
        "parent_case": probe.get("name", Path(probe_path).stem),
        "update_method": "density_reachability_probe",
        "density_probe_origin_normalized": origin,
    })
    return {
        "candidate_id": candidate_id,
        "parent_case_path": probe_path,
        "comparison_case_path": parent_path,
        "target_region": target_region,
        "generation_signature_hash": signature_hash,
        "domain_id": compute_domain_id(
            candidate_case, seed=screening_seed, generator_version=generator_version
        ),
        "feature_delta": {feature: next_value - after[feature]},
        "normalized_feature_before": after[feature],
        "normalized_feature_after": next_value,
        "density_probe_origin_normalized": origin,
        "reason": "extend observed density probe within reviewed exploration bounds",
        "case": candidate_case,
    }


def nearest_observed_signatures(audit: dict, target_bins: list[int]) -> dict:
    """Find the closest actually observed signatures on the log-bin grid."""
    observed = [row for row in audit["bins"] if row["signature_hashes"]]
    if not observed:
        return {"bin_indices": [], "signature_hashes": []}
    distance = min(
        abs(row["bin_index"] - target) for row in observed for target in target_bins
    )
    nearest = [
        row for row in observed
        if min(abs(row["bin_index"] - target) for target in target_bins) == distance
    ]
    return {
        "bin_indices": [row["bin_index"] for row in nearest],
        "signature_hashes": sorted({
            signature for row in nearest for signature in row["signature_hashes"]
        }),
    }


def run_campaign(args: argparse.Namespace) -> dict:
    if args.seed_stop < args.seed_start:
        raise ValueError("seed-stop must be >= seed-start")
    if args.iterations <= 0:
        raise ValueError("iterations must be positive")
    case_paths = [str(Path(path).resolve()) for path in args.case]
    for path in case_paths:
        if not Path(path).is_file():
            raise FileNotFoundError(path)

    euler_spec = None
    if args.euler_spec:
        euler_spec = json.loads(Path(args.euler_spec).read_text(encoding="utf-8"))
        if not euler_spec.get("case_path"):
            raise ValueError("euler spec requires case_path")
        euler_spec["case_path"] = str(Path(euler_spec["case_path"]).resolve())
        if euler_spec.get("probe_case_path"):
            euler_spec["probe_case_path"] = str(Path(euler_spec["probe_case_path"]).resolve())
            if not euler_spec.get("target_bins"):
                raise ValueError("observed Euler spec requires target_bins")
            if not {euler_spec["case_path"], euler_spec["probe_case_path"]}.issubset(case_paths):
                raise ValueError("parent and probe cases must run in iteration 0")
        if not args.dry_run and euler_spec.get("approval_status") != "approved_for_screening":
            raise ValueError("actual Euler campaign requires approved_for_screening spec")

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "campaign_type": "isolated_validation",
        "existing_results_used": False,
        "profile_intervals": 10,
        "coverage_intervals": 20,
        "case_paths": case_paths,
        "seed_range": [args.seed_start, args.seed_stop],
        "iterations_requested": args.iterations,
        "backend": args.backend,
        "status": "dry_run" if args.dry_run else "planned",
        "euler_spec": args.euler_spec,
    }
    (workdir / "campaign_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.dry_run:
        for iteration in range(args.iterations):
            iteration_dir = workdir / f"iteration_{iteration:03d}"
            iteration_dir.mkdir(parents=True, exist_ok=True)
            config = build_iteration_config(
                case_paths,
                output_dir=iteration_dir / "simulation",
                seed_start=args.seed_start,
                seed_stop=args.seed_stop,
                backend=args.backend,
            )
            (iteration_dir / "config.yml").write_text(
                yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
            )
        return manifest

    ledger_path = workdir / "ledger.jsonl"
    current_case_paths = case_paths
    before_audit = None
    previous_records = None
    previous_case_path = None
    campaign_rows = []
    domain_signatures = {}
    campaign_csv_paths = []
    campaign_records = []
    for iteration in range(args.iterations):
        iteration_dir = workdir / f"iteration_{iteration:03d}"
        simulation_dir = iteration_dir / "simulation"
        config = build_iteration_config(
            current_case_paths,
            output_dir=simulation_dir,
            seed_start=args.seed_start,
            seed_stop=args.seed_stop,
            backend=args.backend,
        )
        config_path = iteration_dir / "config.yml"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        subprocess.run(
            [sys.executable, "run_profile_mc.py", "--config", str(config_path)],
            cwd=REPO_ROOT,
            check=True,
        )
        csv_path = simulation_dir / "all_cases_borehole_rows.csv"
        csv_records = load_csv_records(str(csv_path))
        new_domain_ids = set()
        for row in csv_records:
            domain_id = row.get("domain_id")
            signature = row.get("generation_signature_hash")
            if not domain_id or not signature:
                raise ValueError("isolated campaign requires domain and signature provenance")
            if domain_id in domain_signatures and domain_signatures[domain_id] != signature:
                raise ValueError(f"conflicting signature for domain_id: {domain_id}")
            if domain_id not in domain_signatures:
                new_domain_ids.add(domain_id)
            domain_signatures[domain_id] = signature
        campaign_rows.extend(
            row for row in csv_records if row["domain_id"] in new_domain_ids
        )
        campaign_csv_paths.append(str(csv_path))
        audit = audit_borehole_records(
            campaign_rows, cutoffs=generate_qprime_cutoffs(intervals=10)
        )
        coverage_audit = audit_borehole_records(
            campaign_rows, cutoffs=generate_qprime_cutoffs(intervals=20)
        )
        audit["source_csvs"] = list(campaign_csv_paths)
        coverage_audit["source_csvs"] = list(campaign_csv_paths)
        profile_search = search_profile_boundaries(
            campaign_rows,
            cutoffs=generate_qprime_cutoffs(intervals=10),
            min_records=1,
            min_domains=1,
            stable_bins=1,
        )
        audit_path = iteration_dir / "coverage_audit.json"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        (iteration_dir / "coverage_audit_20.json").write_text(
            json.dumps(coverage_audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        profile_path = iteration_dir / "profile_boundary_search.json"
        profile_path.write_text(
            json.dumps(profile_search, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        record = build_round_record(
            round_id=iteration,
            run_id=f"validation-{iteration:03d}",
            round_type="validation_screening",
            before_audit=before_audit,
            after_audit=audit,
            n_domains=len(domain_signatures),
            n_signatures=len(set(domain_signatures.values())),
            extra={
                "iteration_dir": str(iteration_dir),
                "provenance_status": audit["provenance_status"],
                "new_domain_count": len(new_domain_ids),
                "duplicate_domain_count": len({row["domain_id"] for row in csv_records}) - len(new_domain_ids),
                "coverage_20_unobserved_bins": sum(
                    row["status"] == "UNOBSERVED" for row in coverage_audit["bins"]
                ),
                "coverage_20_audit_path": str(iteration_dir / "coverage_audit_20.json"),
                "profile_search_status": profile_search["status"],
                "profile_search_reason": profile_search["reason"],
                "lower_cutoff_candidate": profile_search["lower_cutoff"],
                "upper_cutoff_candidate": profile_search["upper_cutoff"],
            },
        )
        if profile_search["status"] == "identified":
            append_ledger(str(ledger_path), record)
            campaign_records.append(record)
            before_audit = audit
            break
        if euler_spec is not None and (
            iteration + 1 < args.iterations or euler_spec.get("probe_case_path")
        ):
            next_iteration_dir = workdir / f"iteration_{iteration + 1:03d}"
            feature_bounds = {
                key: tuple(value) for key, value in euler_spec["feature_bounds"].items()
            }
            if euler_spec.get("probe_case_path"):
                parent_path = previous_case_path or euler_spec["case_path"]
                probe_path = (current_case_paths[0] if previous_case_path
                              else euler_spec["probe_case_path"])
                measured_probe = observed_euler_probe(
                    (previous_records or []) + csv_records,
                    parent_path=parent_path,
                    probe_path=probe_path,
                    feature_bounds=feature_bounds,
                    target_bins=euler_spec["target_bins"],
                    cutoffs=audit["cutoffs"],
                )
                record["euler_probe"] = measured_probe
                if iteration == 0:
                    nearest = nearest_observed_signatures(
                        audit, euler_spec["target_bins"]
                    )
                    record["nearest_observed_signatures"] = nearest
                    nearest_hash = (
                        measured_probe["probe_signature_hash"]
                        if measured_probe["source_case_path"] == probe_path
                        else measured_probe["parent_signature_hash"]
                    )
                    if nearest_hash not in nearest["signature_hashes"]:
                        compatible = None
                        for near_path in case_paths:
                            near_name = load_case_mapping(near_path).get("name", Path(near_path).stem)
                            near_hashes = {
                                row.get("generation_signature_hash") for row in csv_records
                                if row.get("case_name") == near_name
                            }
                            if len(near_hashes) != 1 or not near_hashes.issubset(nearest["signature_hashes"]):
                                continue
                            for other_path in (euler_spec["probe_case_path"], euler_spec["case_path"]):
                                if near_path == other_path:
                                    continue
                                try:
                                    attempt = observed_euler_probe(
                                        csv_records, parent_path=near_path,
                                        probe_path=other_path, feature_bounds=feature_bounds,
                                        target_bins=euler_spec["target_bins"],
                                        cutoffs=audit["cutoffs"],
                                    )
                                except ValueError:
                                    continue
                                if (attempt["source_case_path"] == near_path
                                    and assess_physical_probe(attempt)["status"] == "observed_local_response"):
                                    compatible = attempt
                                    break
                            if compatible is not None:
                                break
                        if compatible is None:
                            record["next_action"] = "await_nearest_signature_probe"
                            record["euler_stop_reason"] = (
                                "a closer observed signature requires a paired one-feature probe with measured physical response"
                            )
                            append_ledger(str(ledger_path), record)
                            campaign_records.append(record)
                            break
                        measured_probe = compatible
                        record["euler_probe"] = measured_probe
                delta = measured_probe["coverage_delta"]
                residual = measured_probe["coverage_residual"]
                response = sum(delta.get(key, 0.0) * value for key, value in residual.items())
                physical_assessment = assess_physical_probe(measured_probe)
                record["physical_assessment"] = physical_assessment
                if measured_probe["distance_to_target"] == 0.0:
                    record["next_action"] = "stop_target_bins_reached"
                    record["euler_stop_reason"] = "target bins observed by the nearest signature"
                    append_ledger(str(ledger_path), record)
                    campaign_records.append(record)
                    break
                feature = next(iter(measured_probe["feature_delta"]))
                density_probe = feature.endswith(".P32") or feature.endswith(".mean_spacing")
                extend_density = density_probe and (
                    response == 0.0 or physical_assessment["status"] in {
                        "no_intersection_response", "no_quality_response"
                    }
                )
                if extend_density and physical_assessment["status"] not in {
                    "needs_measurement", "needs_repeatability"
                } and (response == 0.0 or measured_probe["source_case_path"] == probe_path):
                    candidate = build_density_reachability_probe(
                        parent_path, probe_path,
                        feature_bounds=feature_bounds, round_id=iteration + 1,
                        target_region=euler_spec["target_region"],
                        screening_seed=euler_spec.get("screening_seed", args.seed_start),
                        generator_version=euler_spec.get("generator_version", "validation-v1"),
                    )
                    if candidate is None:
                        record["next_action"] = "await_wider_density_bounds"
                        record["euler_stop_reason"] = "reviewed exploration bounds reached without sufficient response"
                        append_ledger(str(ledger_path), record)
                        campaign_records.append(record)
                        break
                    record["next_action"] = "expand_density_probe"
                    parent_path = probe_path
                elif physical_assessment["status"] in {"needs_measurement", "needs_repeatability"}:
                    record["next_action"] = "await_physical_probe_response"
                    record["euler_stop_reason"] = physical_assessment["status"]
                    append_ledger(str(ledger_path), record)
                    campaign_records.append(record)
                    break
                elif response == 0.0:
                    record["next_action"] = "stop_no_observed_euler_direction"
                    record["euler_stop_reason"] = "no measured movement toward target bins"
                    append_ledger(str(ledger_path), record)
                    campaign_records.append(record)
                    break
                elif physical_assessment["status"] != "observed_local_response":
                    record["next_action"] = "await_physical_probe_response"
                    record["euler_stop_reason"] = physical_assessment["status"]
                    append_ledger(str(ledger_path), record)
                    campaign_records.append(record)
                    break
                else:
                    parent_path = measured_probe["source_case_path"]
                    probes = [measured_probe]
            else:
                parent_path = euler_spec["case_path"]
                probes = euler_spec["probes"]
            if iteration + 1 >= args.iterations:
                if record.get("next_action") == "expand_density_probe":
                    record["next_action"] = "density_probe_iteration_limit"
                    record["euler_stop_reason"] = "a wider density probe needs another iteration"
                append_ledger(str(ledger_path), record)
                campaign_records.append(record)
                break
            if not (euler_spec.get("probe_case_path") and record.get("next_action") == "expand_density_probe"):
                candidate = build_euler_update_candidate_from_probes(
                    parent_path,
                    round_id=iteration + 1,
                    target_region=euler_spec["target_region"],
                    screening_seed=euler_spec.get("screening_seed", args.seed_start),
                    feature_bounds=feature_bounds,
                    probes=probes,
                    step_size=float(euler_spec["step_size"]),
                    discrete_features=euler_spec.get("discrete_features", []),
                    generator_version=euler_spec.get("generator_version", "validation-v1"),
                )
                candidate["case"].get("tags", {}).pop("density_probe_origin_normalized", None)
            if euler_spec.get("probe_case_path") and candidate["generation_signature_hash"] == compute_generation_signature_hash(load_case_mapping(parent_path)):
                record["next_action"] = "stop_no_observed_euler_direction"
                record["euler_stop_reason"] = "bounded step did not change the parent signature"
                append_ledger(str(ledger_path), record)
                campaign_records.append(record)
                break
            candidate_dir = next_iteration_dir / "candidate"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            candidate_path = candidate_dir / f"{candidate['candidate_id']}.yaml"
            candidate_path.write_text(
                yaml.safe_dump(candidate["case"], sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            (candidate_dir / "candidate.json").write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            current_case_paths = [str(candidate_path)]
            record["next_candidate_path"] = str(candidate_path)
            record["next_candidate_id"] = candidate["candidate_id"]
            if euler_spec.get("probe_case_path"):
                previous_records = (previous_records or []) + csv_records
                previous_case_path = parent_path
        append_ledger(str(ledger_path), record)
        campaign_records.append(record)
        before_audit = audit

    manifest["status"] = "completed"
    manifest["records"] = campaign_records
    (workdir / "campaign_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_campaign(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
