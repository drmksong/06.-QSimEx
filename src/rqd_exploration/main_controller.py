"""Persistent T011 state machine; physical work uses the existing one-job runner."""

from dataclasses import asdict, replace
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from src.euler_campaign.generation import FIXED_DOMAIN_GENERATOR_VERSION

from . import analysis
from .adapter import build_generation_case
from .cumulative_reporting import (
    CUMULATIVE_CSV_HEADERS, cumulative_report_identity,
    export_cumulative_coverage_report, select_cumulative_observations,
)
from .dataset import (
    load_latest_cumulative_dataset_revision, persist_cumulative_analysis_run,
    persist_cumulative_derived_scores, read_current_cumulative_dataset,
)
from .design import DesignSample, build_frozen_manifest, generate_lhs_design
from .fingerprint import ExecutionRuntime, fingerprint_snapshot
from .main_analysis import (
    BHPoint, REQUIRED_VERIFICATION_PASSES, SeedProfile, VERIFICATION_SEED_COUNT,
    build_targets, paired_progress, progress_decision, seed_metrics, seed_pass_result,
    target_passed,
)
from .main_design import (
    expected_joint_counts, input_identity, propose_candidates, snapshot_from_dict,
    validate_generating_input,
)
from .main_store import (
    MainPause, append_event, checkpoint, initialize_main_store, open_run,
    reconcile_starts, reserve_start, single_writer, starts_consumed,
)
from .measurement import FACE_BOUNDARY_RULES_VERSION, MEASUREMENT_VERSION, plan_measurement_locations
from .records import PlannedBHInterval
from .runner import execute_frozen_job
from .store import STORE_SCHEMA_VERSION, _atomic, initialize_store, store_manifest


PREVIEW_RUNTIME = ExecutionRuntime(FIXED_DOMAIN_GENERATOR_VERSION,
                                  MEASUREMENT_VERSION, "mlx", ("not-preflighted",))


def _input_manifest(normalized, runtime):
    design = normalized.designs[0]
    sample = generate_lhs_design(design).samples[0]
    case = build_generation_case(normalized.geometry, normalized.measurements,
                                 design.fixed_jn, sample.joint_sets, case_id="main-initial")
    return build_frozen_manifest(normalized, manifest_id="main-initial-preview",
                                 runtime=runtime, boundary_rules_version=FACE_BOUNDARY_RULES_VERSION,
                                 planned_locations=plan_measurement_locations(case))


def initial_manifest(config, runtime=PREVIEW_RUNTIME):
    if config.initial is None:
        raise ValueError("Jn20 initialization is excluded by initial_input: null")
    return _input_manifest(config.initial, runtime)


def initial_snapshots(config, runtime=PREVIEW_RUNTIME):
    if config.initial is None:
        return ()
    return tuple(j.snapshot for j in initial_manifest(config, runtime).jobs)


def reference_snapshot(config, runtime=PREVIEW_RUNTIME):
    return _input_manifest(config.reference_input, runtime).jobs[0].snapshot


def _snapshot_from_payload(payload):
    item = payload["inputs"]
    return snapshot_from_dict({
        "geometry": item["geometry"], "fixed_jn": item["dfn"]["fixed_jn"],
        "joint_sets": item["dfn"]["joint_sets"], "realization_seed": item["realization_seed"],
        "measurements": item["measurement"], "runtime": item["runtime"]})


def preview_main(config, connection=None):
    reference = reference_snapshot(config)
    normalized = config.reference_input
    profile = next(p.profile_id for p in plan_measurement_locations(
        build_generation_case(normalized.geometry, normalized.measurements, reference.fixed_jn,
                              reference.joint_sets, case_id="preview"))
                   if isinstance(p, PlannedBHInterval))
    targets = build_targets(profile, jn_values=tuple(config.templates))
    initial_jobs = []
    for snapshot in initial_snapshots(config):
        counts = expected_joint_counts(snapshot)
        total = sum(counts.values())
        initial_jobs.append({
            "input_id": input_identity(snapshot), "Jn": snapshot.fixed_jn,
            "sets": len(snapshot.joint_sets), "seed": snapshot.realization_seed,
            "design_seed": config.reference_input.designs[0].design_seed,
            "expected_joints_by_set": counts, "total_expected_joints": total,
            "cost_review_required": total > config.policy.maximum_expected_joints})
    payload = {
        "policy": asdict(config.policy), "config_fingerprint": config.fingerprint,
        "initial_jobs": initial_jobs,
        "targets": [{"key": t.key, "reachable": t.reachable,
                     "rqd_lower_open": t.rqd_lower, "rqd_upper_closed": t.rqd_upper}
                    for t in targets],
        "database_written": False, "simulation_started": False,
        "runtime_preflighted": False,
    }
    if connection is not None:
        if connection.execute("PRAGMA user_version").fetchone()[0] != STORE_SCHEMA_VERSION:
            raise ValueError("main preview requires read-only raw schema4")
        if connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0]:
            revision = read_current_cumulative_dataset(connection)
            payload["existing_raw_observations"] = revision.raw_observation_count
            payload["existing_realizations"] = revision.independent_realization_count
        else:
            payload["existing_raw_observations"] = 0
            payload["existing_realizations"] = 0
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='main_control_runs'").fetchone():
            payload["main_runs"] = [
                {"run_id": r, "status": status, "reason": reason,
                 "starts_consumed": starts_consumed(connection, r)}
                for r, status, reason in connection.execute(
                    "SELECT run_id,status,reason FROM main_control_runs")]
    return payload


class MainController:
    include_face_measurements = True
    record_p32 = True
    progress_job_label = None

    def __init__(self, connection, config, factory, runtime, *, output_dir,
                 progress_callback=None, targets=None, run_prefix="main"):
        runtime = replace(runtime, generator_version=FIXED_DOMAIN_GENERATOR_VERSION)
        self.connection, self.config, self.factory, self.runtime = connection, config, factory, runtime
        self.output_dir = Path(output_dir)
        self.progress_callback = progress_callback
        self.run_prefix = run_prefix
        snapshots = initial_snapshots(config, runtime)
        reference = reference_snapshot(config, runtime)
        normalized = config.reference_input
        locations = plan_measurement_locations(build_generation_case(
            normalized.geometry, normalized.measurements, reference.fixed_jn, reference.joint_sets,
            case_id="main"))
        self.profile_id = next(p.profile_id for p in locations if isinstance(p, PlannedBHInterval))
        self.targets = (build_targets(self.profile_id, jn_values=tuple(config.templates))
                        if targets is None else tuple(targets))
        state = {
            "phase": "initial" if snapshots else "exploration",
            "bin": 10, "round_index": 0, "stagnant_rounds": 0,
            "target_cursor": 0, "reference_cursor": 0, "pair_reference_cursor": 0, "axis_cursors": {},
            "input_cursor": 0, "rng_states": [], "inputs": {},
            "queue": [], "round": None, "target_evidence": {}, "reason": None,
            "review_checkpoint_released": False,
        }
        for snapshot in snapshots:
            identity = input_identity(snapshot)
            state["inputs"][identity] = asdict(snapshot)
            state["queue"].append({
                "input_id": identity, "seed": config.policy.initial_seed, "role": "initial"})
        self.run_id, self.state = open_run(
            connection, config, asdict(runtime), state, run_prefix=run_prefix)
        self.state.setdefault("pair_reference_cursor", 0)
        self.profiles = {}
        self._initial_pause = None
        try:
            self._refresh()
        except MainPause as pause:
            self._initial_pause = pause

    def _save(self, *, status="running", reason=None):
        checkpoint(self.connection, self.run_id, self.state, status=status, reason=reason)

    def _check_review_checkpoint(self):
        checkpoint_starts = self.config.policy.review_checkpoint_starts
        if checkpoint_starts is None:
            return
        starts = starts_consumed(self.connection, self.run_id)
        if (not self.state.get("review_checkpoint_released", False)
            and starts >= checkpoint_starts):
            raise MainPause("review_checkpoint", {"starts_consumed": starts})

    def _refresh(self):
        if not self.connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0]:
            self.profiles, self.snapshot_by_digest, self.raw_revision = {}, {}, None
            return
        revision = read_current_cumulative_dataset(self.connection)
        observations = select_cumulative_observations(revision)
        reference = reference_snapshot(self.config, self.runtime)
        snapshots = {}
        physical_units = {}
        for digest, payload in self.connection.execute(
            "SELECT execution_fingerprint_digest,execution_snapshot FROM jobs"):
            snapshot = _snapshot_from_payload(json.loads(payload))
            if (snapshot.runtime.generator_version != FIXED_DOMAIN_GENERATOR_VERSION
                or snapshot.geometry != reference.geometry
                or snapshot.measurements != reference.measurements
                or snapshot.fixed_jn not in self.config.templates):
                continue
            snapshots[digest] = snapshot
            self.state["inputs"].setdefault(input_identity(snapshot), asdict(snapshot))
        sources = dict(revision.source_attempt_indices)
        for row in self.connection.execute(
            "SELECT manifest_id,design_id,block_id,sample_index,realization_seed,"
            "execution_fingerprint_digest,attempt_index,profile_id,location_index,start_m,end_m "
            "FROM observations WHERE modality='BH'"):
            physical_units[tuple(row[:-2])] = (row[-2], row[-1])
        selected = {}
        for item in observations:
            if (item.modality != "BH" or item.execution_fingerprint_digest not in snapshots
                or not item.is_valid or item.support_length_m is None or item.support_length_m < 1):
                continue
            snapshot = snapshots[item.execution_fingerprint_digest]
            key = (input_identity(snapshot), item.profile_id, item.realization_seed,
                   item.execution_fingerprint_digest)
            source_key = (item.manifest_id, item.design_id, item.block_id, item.sample_index,
                          item.realization_seed, item.execution_fingerprint_digest,
                          "BH", item.profile_id, item.location_index)
            attempt = sources[source_key]
            start, end = physical_units[(*source_key[:6], attempt, *source_key[7:])]
            selected.setdefault(key, []).append(BHPoint(start, end, item.raw_rqd, item.support_length_m))
        profiles = {}
        for (identity, profile, seed, _), points in selected.items():
            value = SeedProfile(seed, tuple(sorted(points, key=lambda p: p.start_m)))
            seed_map = profiles.setdefault(identity, {}).setdefault(profile, {})
            if seed in seed_map and seed_map[seed] != value:
                raise MainPause("incomparable", f"conflicting input/seed observations: {identity}/{seed}")
            seed_map[seed] = value
        self.profiles = profiles
        self.snapshot_by_digest = snapshots
        self.raw_revision = revision

    def _profile(self, identity, seed):
        return self.profiles.get(identity, {}).get(self.profile_id, {}).get(seed)

    def _release_recoverable_incomparable_pause(self):
        if self._initial_pause is not None:
            raise ValueError("incomparable recovery refused: cumulative data is still incomparable")
        if self.state.get("resume_phase") != "exploration":
            raise ValueError("incomparable recovery refused: saved resume phase is not exploration")
        queue = self.state.get("queue")
        if not isinstance(queue, list) or not queue or not isinstance(queue[0], dict):
            raise ValueError("incomparable recovery refused: no queued target verification sample")
        task = queue[0]
        identity, seed = task.get("input_id"), task.get("seed")
        round_state = self.state.get("round")
        if (
            task.get("role") != "target_verification"
            or not isinstance(identity, str)
            or not identity
            or isinstance(seed, bool)
            or not isinstance(seed, int)
            or not isinstance(round_state, dict)
            or round_state.get("phase") != "verification"
            or round_state.get("verification_input") != identity
        ):
            raise ValueError("incomparable recovery refused: pause is not a queued target verification sample")
        if seed not in range(
            self.config.policy.verification_seed,
            self.config.policy.verification_seed + VERIFICATION_SEED_COUNT,
        ):
            raise ValueError(
                "incomparable recovery refused: queued seed is outside configured verification seeds"
            )
        if self.state.get("detail") != f"no valid BH support for {identity}/{seed}":
            raise ValueError("incomparable recovery refused: pause detail does not match the repaired BH filter")
        if self._profile(identity, seed) is None:
            raise ValueError("incomparable recovery refused: queued sample still has no valid BH support")
        start = self.connection.execute(
            "SELECT role,status FROM main_control_starts "
            "WHERE run_id=? AND input_id=? AND seed=? "
            "ORDER BY start_index DESC LIMIT 1",
            (self.run_id, identity, seed),
        ).fetchone()
        if start != ("target_verification", "succeeded"):
            raise ValueError("incomparable recovery refused: matching start is not succeeded")

        self.state["phase"] = self.state.pop("resume_phase")
        self.state["reason"] = None
        self.state.pop("detail", None)
        self._save()
        if self.progress_callback is not None:
            self.progress_callback(
                f"main {self.run_id} recovered incomparable pause; "
                f"reusing saved verification sample seed={seed} without a new start"
            )

    def _histories(self, target):
        result = {}
        for identity, profiles in self.profiles.items():
            if self.state["inputs"][identity]["fixed_jn"] != target.fixed_jn:
                continue
            seeds = profiles.get(target.profile_id, {})
            result[identity] = seed_pass_result(
                tuple(seeds.values()), target,
                initial_seed=self.config.policy.initial_seed,
                verification_seed=self.config.policy.verification_seed)
        self.state["target_evidence"][target.key] = {
            i: asdict(h) for i, h in result.items()}
        return result

    def _verification_pending(self, target, histories=None):
        histories = self._histories(target) if histories is None else histories
        return any(
            result.initial_positive_support is True and not result.complete and not result.passed
            for result in histories.values()
        )

    def _suitable(self, target):
        result = []
        initial_seed = self.config.policy.initial_seed
        for identity in sorted(self.profiles):
            if self.state["inputs"][identity]["fixed_jn"] != target.fixed_jn:
                continue
            profile = self._profile(identity, initial_seed)
            metrics = None if profile is None else seed_metrics(profile, target)
            if metrics is not None and metrics[1] > 0:
                result.append(identity)
        return result

    def _references(self, target):
        metrics = {}
        self.reference_skips = []
        for identity in sorted(self.profiles):
            if self.state["inputs"][identity]["fixed_jn"] == target.fixed_jn:
                try:
                    validate_generating_input(snapshot_from_dict(self.state["inputs"][identity]))
                except ValueError as error:
                    self.reference_skips.append({"input_id": identity, "skip_reason": str(error)})
                    continue
                profile = self._profile(identity, self.config.policy.initial_seed)
                result = None if profile is None else seed_metrics(profile, target)
                if result is not None:
                    metrics[identity] = result
        if not metrics:
            return []
        distance = min(v[0] for v in metrics.values())
        support = max(v[1] for v in metrics.values())
        # No weighted objective and no single-parent replacement.
        return sorted(i for i, v in metrics.items() if v[0] == distance or v[1] == support)

    def _make_manifest(self, identity, seed):
        snapshot = replace(snapshot_from_dict(self.state["inputs"][identity]),
                           realization_seed=seed)
        runtime = replace(self.runtime, generator_version=snapshot.runtime.generator_version)
        snapshot = replace(snapshot, runtime=runtime)
        template = self.config.templates[snapshot.fixed_jn]
        design_id = f"{self.run_prefix}-input-" + identity
        design = replace(template, design_id=design_id, block_id="main",
                         sample_count=1, realization_seed=seed)
        normalized = replace(
            self.config.reference_input, designs=(design,), source_yaml_bytes=self.config.source_yaml_bytes,
            source_yaml_sha256=sha256(self.config.source_yaml_bytes).hexdigest(),
            source_reference=self.config.source_reference)
        case = build_generation_case(normalized.geometry, normalized.measurements,
                                     snapshot.fixed_jn, snapshot.joint_sets, case_id=design_id,
                                     allow_constant_radius=True)
        manifest = build_frozen_manifest(
            normalized, manifest_id=f"{self.run_id}-{identity}-{seed}", runtime=runtime,
            boundary_rules_version=FACE_BOUNDARY_RULES_VERSION,
            planned_locations=plan_measurement_locations(case),
            samples_by_design={design_id: (DesignSample(0, (), snapshot.joint_sets),)})
        return manifest, normalized

    def _perform(self, task):
        identity, seed = task["input_id"], task["seed"]
        if self._profile(identity, seed) is not None:
            task["result"] = "reused"
            self._report_task_completion(task)
            return
        for row in self.connection.execute(
            "SELECT execution_fingerprint_digest,status FROM attempts WHERE realization_seed=?", (seed,)):
            snapshot = self.snapshot_by_digest.get(row[0])
            if snapshot is not None and input_identity(snapshot) == identity:
                if row[1] == "failed":
                    raise MainPause("execution_error", f"saved failed input/seed {identity}/{seed}; no retry")
                if row[1] == "succeeded":
                    raise MainPause("incomparable", f"saved input/seed lacks valid BH support {identity}/{seed}")
        manifest, normalized = self._make_manifest(identity, seed)
        existing = self.connection.execute(
            "SELECT manifest_json FROM manifest WHERE manifest_id=?", (manifest.manifest_id,)).fetchone()
        if existing is None:
            store_manifest(self.connection, manifest)
        elif existing[0] != manifest.manifest_json:
            raise ValueError("saved main job manifest conflicts with its frozen plan")
        progress_context = self._format_progress_context(
            task, starts_consumed(self.connection, self.run_id))

        def report_job_progress(message):
            if self.progress_callback is not None:
                self.progress_callback(f"{progress_context} {message}")

        def before_start(job, resuming):
            nonlocal progress_context
            self._check_review_checkpoint()
            counts = expected_joint_counts(job.snapshot)
            index = reserve_start(self.connection, self.run_id, job, input_id=identity,
                          role=task["role"], resuming=resuming,
                          expected_counts=counts, policy=self.config.policy)
            progress_context = self._format_progress_context(task, index)
            if self.progress_callback is not None:
                self.progress_callback(
                    f"{progress_context} job_stage=starting resuming={resuming} "
                    f"total_expected_joints={sum(counts.values()):.6g}")
        execution_options = {}
        if not self.record_p32:
            execution_options["record_p32"] = False
        if not self.include_face_measurements:
            execution_options["include_face_measurements"] = False
        if self.progress_job_label is not None:
            execution_options["progress_job_label"] = self.progress_job_label
        summary = execute_frozen_job(
            self.connection, manifest, normalized, self.factory,
            before_start=before_start,
            progress_callback=(report_job_progress
                               if self.progress_callback is not None else None),
            allow_constant_radius=True,
            **execution_options,
        )
        reconcile_starts(self.connection, self.run_id)
        if summary.skipped_failed_job_keys:
            raise MainPause("execution_error", "saved failed attempt; no automatic retry")
        self._refresh()
        if self._profile(identity, seed) is None:
            raise MainPause("incomparable", f"no valid BH support for {identity}/{seed}")
        task["result"] = "generated" if summary.simulation_count else "reconciled"
        self._report_task_completion(task)

    def _report_task_completion(self, task):
        if self.progress_callback is None:
            return
        consumed = starts_consumed(self.connection, self.run_id)
        self.progress_callback(
            f"{self._format_progress_context(task, consumed)} "
            f"job_stage=completed result={task['result']}"
        )

    def _choose_rotating(self, values, cursor_name):
        if not values:
            return None
        cursor = self.state[cursor_name]
        self.state[cursor_name] += 1
        return values[cursor % len(values)]

    def _candidate_stream_key(self, target):
        return (int(target.bin_id) * 1000
                + analysis.JR_VALUES.index(target.jr) * 100
                + analysis.JA_VALUES.index(target.ja))

    def _plan_round(self, target):
        self.state["round_index"] += 1
        histories = self._histories(target)
        suitable = self._suitable(target)
        round_state = {"round_index": self.state["round_index"],
                       "target": target.key, "phase": "search", "candidates": [],
                       "references": self._references(target), "progress_pairs": [],
                       "before_suitable": suitable,
                       "progress": False, "verification_input": None, "proposals": []}
        round_state["reference_skips"] = self.reference_skips
        self.state["round"] = round_state
        if self._verification_pending(target, histories):
            round_state["phase"] = "verification"
            return
        references = round_state["references"]
        if not references:
            design = self.config.templates[target.fixed_jn]
            stream = propose_candidates(
                replace(reference_snapshot(self.config, self.runtime),
                        fixed_jn=target.fixed_jn,
                        joint_sets=generate_lhs_design(design).samples[0].joint_sets),
                design, round_index=self.state["round_index"], cursor=0,
                rng_seed=self.config.rng_seed, seen=set(self.profiles),
                stream_key=self._candidate_stream_key(target), lhs_count=12, lhs_only=True,
                runtime=self.runtime)
            candidates = [c for c in stream.candidates if c.role == "lhs"]
            if not candidates:
                raise MainPause("candidate_exhausted", "no valid unexplored LHS and no BH reference")
            reference = candidates[0].input_id
            round_state["references"] = [reference]
            round_state["proposals"] = list(stream.proposals)
            self.state["rng_states"].append(stream.rng_state)
            for candidate in candidates:
                self.state["inputs"].setdefault(candidate.input_id, asdict(candidate.snapshot))
                round_state["candidates"].append(
                    {"input_id": candidate.input_id, "references": [reference], "role": "lhs",
                     "reasons": list(candidate.reasons)})
                self.state["queue"].append(
                    {"input_id": candidate.input_id,
                     "seed": self.config.policy.initial_seed, "role": "lhs"})
            return
        cursor = self.state["reference_cursor"] % len(references)
        self.state["reference_cursor"] += 1
        references = references[cursor:] + references[:cursor]
        allocation_reference = references[0]
        round_state["allocation_reference"] = allocation_reference
        pools = {"single_axis": [], "multi_axis": [], "lhs": []}
        seen = set(self.profiles)
        condition_key = self._candidate_stream_key(target)
        merged = {}
        for reference in references:
            base = snapshot_from_dict(self.state["inputs"][reference])
            axis_cursor = self.state["axis_cursors"].get(reference, 0)
            proposals = propose_candidates(
                base, self.config.templates[target.fixed_jn], round_index=self.state["round_index"],
                cursor=axis_cursor, rng_seed=self.config.rng_seed, seen=seen,
                stream_key=condition_key, runtime=self.runtime)
            self.state["axis_cursors"][reference] = (
                proposals.next_cursor if reference == allocation_reference else axis_cursor)
            self.state["rng_states"].append(proposals.rng_state)
            round_state["proposals"].extend(proposals.proposals)
            for candidate in proposals.candidates:
                if candidate.input_id in merged:
                    merged[candidate.input_id]["references"].append(reference)
                    merged[candidate.input_id]["reasons"].extend(candidate.reasons)
                    continue
                item = {"input_id": candidate.input_id, "references": [reference],
                        "role": candidate.role, "reasons": list(candidate.reasons)}
                merged[candidate.input_id] = item
                pools[candidate.role].append(item)
                self.state["inputs"].setdefault(candidate.input_id, asdict(candidate.snapshot))
        # Rotate whole reference blocks, not individual steps: retain both axes and
        # both +/- step sizes instead of starving later proposals within every tie.
        selected = []
        for role, limit in (("single_axis", 8), ("multi_axis", 2), ("lhs", 2)):
            selected.extend([p for p in pools[role] if allocation_reference in p["references"]][:limit])
        round_state["candidates"] = selected
        if not selected:
            raise MainPause("candidate_exhausted", {"target": target.key,
                                                   "proposals": round_state["proposals"]})
        self.state["queue"] = [{"input_id": p["input_id"],
                                "seed": self.config.policy.initial_seed, "role": p["role"]}
                               for p in selected]

    def _plan_progress(self, target):
        round_state = self.state["round"]
        round_state["phase"] = "progress"
        initial_seed = self.config.policy.initial_seed
        verification_seed = self.config.policy.verification_seed
        verification_seeds = range(verification_seed, verification_seed + 3)
        candidates = [p for p in round_state["candidates"]
                      if self._profile(p["input_id"], initial_seed)]
        candidates = [p for p in candidates if any(r != p["input_id"] for r in p["references"])]
        ranked_distance = sorted(candidates, key=lambda p: (
            seed_metrics(self._profile(p["input_id"], initial_seed), target)[0], p["input_id"]))
        ranked_support = sorted(candidates, key=lambda p: (
            -seed_metrics(self._profile(p["input_id"], initial_seed), target)[1], p["input_id"]))
        chosen = []
        for items in zip(ranked_distance, ranked_support):
            for item in items:
                if item not in chosen:
                    chosen.append(item)
            if len(chosen) >= 2:
                break
        for candidate in chosen[:2]:
            references = [r for r in candidate["references"] if r != candidate["input_id"]]
            reference = self._choose_rotating(sorted(references), "pair_reference_cursor")
            if self._profile(reference, initial_seed) is None:
                self.state["queue"].append(
                    {"input_id": reference, "seed": initial_seed, "role": "reference"})
            pair = {"candidate": candidate["input_id"], "reference": reference,
                    "seeds": list(verification_seeds),
                    "effects": [], "decision": None}
            round_state["progress_pairs"].append(pair)
            for seed in pair["seeds"]:
                for identity, role in ((reference, "reference"), (candidate["input_id"], "progress")):
                    self.state["queue"].append({"input_id": identity, "seed": seed, "role": role})

    def _finish_progress(self, target):
        round_state = self.state["round"]
        for pair in round_state["progress_pairs"]:
            effects = [paired_progress(self._profile(pair["reference"], s),
                                       self._profile(pair["candidate"], s), target) for s in pair["seeds"]]
            pair["effects"] = [asdict(e) for e in effects]
            decision = progress_decision(tuple(e.status for e in effects))
            pair["decision"] = decision
            if any(e.status == "incomparable" for e in effects):
                raise MainPause("incomparable", pair)
            if decision == "extend":
                extra_seeds = range(
                    self.config.policy.verification_seed + 3,
                    self.config.policy.verification_seed + 5)
                pair["seeds"].extend(extra_seeds)
                for seed in extra_seeds:
                    for identity, role in ((pair["reference"], "reference"),
                                           (pair["candidate"], "progress")):
                        self.state["queue"].append({"input_id": identity, "seed": seed, "role": role})
            elif decision == "progress":
                round_state["progress"] = True
        if not self.state["queue"]:
            round_state["phase"] = "verification"

    def _plan_target_verification(self, target):
        round_state = self.state["round"]
        histories = self._histories(target)
        identity = round_state["verification_input"]
        if identity is None:
            pending = [
                i for i in self._suitable(target)
                if histories[i].initial_positive_support is True
                and not histories[i].complete and not histories[i].passed
            ]
            identity = self._choose_rotating(pending, "input_cursor")
            round_state["verification_input"] = identity
        if identity is None:
            return False
        history = histories[identity]
        if history.passed or history.complete:
            return False
        self.state["queue"] = [
            {"input_id": identity, "seed": seed, "role": "target_verification"}
            for seed, result in zip(history.verification_seeds,
                                    history.verification_positive_support)
            if result is None
        ]
        return bool(self.state["queue"])

    def _complete_round(self, target):
        round_state = self.state["round"]
        if round_state is None:
            return
        new_inputs = set(self._suitable(target)) - set(round_state["before_suitable"])
        progress = round_state["progress"] or bool(new_inputs)
        previous_state = self.state
        self.state = deepcopy(previous_state)
        self.state["stagnant_rounds"] = 0 if progress else previous_state["stagnant_rounds"] + 1
        self.state["last_round"] = round_state
        self.state["round"] = None
        payload = {
            **self.summary(), "completed_round": deepcopy(round_state),
            "round_outcome": {"progress": progress, "new_suitable_inputs": sorted(new_inputs),
                              "stagnant_rounds": self.state["stagnant_rounds"]},
            "dataset_revision_index": None, "dataset_sha256": None,
        }
        try:
            with _atomic(self.connection):
                index = append_event(self.connection, self.run_id, "round_complete", payload)
                self._save()
        except BaseException:
            self.state = previous_state
            raise
        self._write_event(index, payload)
        if self.state["stagnant_rounds"] >= self.config.policy.stagnant_rounds:
            raise MainPause("stagnation", {
                "completed_rounds_without_progress": self.config.policy.stagnant_rounds})

    def _target(self, key):
        return next(t for t in self.targets if t.key == key)

    def _progress_status(self, consumed=None):
        policy = self.config.policy
        maximum = policy.maximum_starts
        consumed = starts_consumed(self.connection, self.run_id) if consumed is None else consumed
        evidence_by_target = self.state["target_evidence"]
        rule = {
            "initial_seed": policy.initial_seed,
            "initial_positive_support_required": True,
            "verification_seeds": list(range(
                policy.verification_seed,
                policy.verification_seed + VERIFICATION_SEED_COUNT)),
            "required_verification_passes": REQUIRED_VERIFICATION_PASSES,
        }

        def target_progress(target):
            evidence = evidence_by_target.get(target.key)
            input_progress = {}
            for identity, result in sorted((evidence or {}).items()):
                support = result["verification_positive_support"]
                input_progress[identity] = {
                    "initial_positive_support": result["initial_positive_support"],
                    "positive_verification_count": sum(value is True for value in support),
                    "complete": result["complete"],
                    "passed": result["passed"],
                }
            evaluated = target.key in evidence_by_target
            passed = any(result["passed"] is True for result in (evidence or {}).values())
            return {
                "status": "passed" if passed else "in_progress" if evaluated else "not_evaluated",
                "passed": passed if evaluated else None,
                "input_progress": input_progress,
            }

        reachable = [target for target in self.targets if target.reachable]
        current_bin = self.state["bin"]
        current_bin_value = current_bin if current_bin in range(1, 11) else None
        bin_targets = [
            target for target in reachable
            if current_bin_value is not None and int(target.bin_id) == current_bin_value
        ]
        targets = {target.key: target_progress(target) for target in bin_targets}
        passed_count = sum(target["passed"] is True for target in targets.values())
        evaluated_count = sum(target["status"] != "not_evaluated" for target in targets.values())
        overall_passed_count = sum(
            any(result["passed"] is True
                for result in (evidence_by_target.get(target.key) or {}).values())
            for target in reachable
        )
        round_state = self.state.get("round")
        round_state = round_state if isinstance(round_state, dict) else {}
        queue = self.state.get("queue")
        task = queue[0] if isinstance(queue, list) and queue and isinstance(queue[0], dict) else {}
        current_work = {
            "round_index": self.state["round_index"],
            "phase": self.state["phase"],
            "round_phase": round_state.get("phase"),
            "target": round_state.get("target"),
            "input_id": task.get("input_id", round_state.get("verification_input")),
            "seed": task.get("seed"),
            "role": task.get("role"),
            "job_stage": "queued" if task else (
                round_state.get("phase") if round_state else self.state["phase"]),
        }
        return {
            "starts_consumed": consumed,
            "starts_maximum": maximum,
            "starts_remaining": max(0, maximum - consumed),
            "target_pass_rule": rule,
            "passed_target_count": overall_passed_count,
            "current_bin_progress": {
                "bin": current_bin_value,
                "reachable_target_count": len(bin_targets),
                "evaluated_target_count": evaluated_count,
                "passed_target_count": passed_count,
                "targets": targets,
            },
            "current_work": current_work,
        }

    def _format_progress_context(self, task, consumed):
        progress = self._progress_status(consumed)
        bin_progress = progress["current_bin_progress"]
        work = progress["current_work"]
        target = bin_progress["targets"].get(work["target"], {})
        current_input = target.get("input_progress", {}).get(task["input_id"], {})
        rule = progress["target_pass_rule"]
        initial_support = current_input.get("initial_positive_support")
        initial_text = "unknown" if initial_support is None else str(initial_support).lower()
        verification_count = current_input.get("positive_verification_count", 0)
        return (
            f"main {self.run_id} starts={progress['starts_consumed']}/"
            f"{progress['starts_maximum']} remaining={progress['starts_remaining']} "
            f"bin={bin_progress['bin'] or '-'} "
            f"targets_passed={bin_progress['passed_target_count']}/"
            f"{bin_progress['reachable_target_count']} "
            f"round={work['round_index']} phase={work['phase']}/"
            f"{work['round_phase'] or '-'} target={work['target'] or '-'} "
            f"input={task['input_id']} seed={task['seed']} role={task['role']} "
            f"target_status={target.get('status', 'not_evaluated')} "
            f"initial_support={initial_text} verification_positive="
            f"{verification_count}/{len(rule['verification_seeds'])} "
            f"required={rule['required_verification_passes']}"
        )

    def _report_progress_snapshot(self, event, *, reason=None, completed_bin=None,
                                  completed_bin_progress=None):
        if self.progress_callback is None:
            return
        progress = self._progress_status()
        bin_progress = progress["current_bin_progress"]
        details = [f"main {self.run_id} event={event}"]
        if completed_bin_progress is not None:
            details.extend((
                f"completed_bin={completed_bin}",
                "completed_targets_passed="
                f"{completed_bin_progress['passed_target_count']}/"
                f"{completed_bin_progress['reachable_target_count']}",
            ))
        details.extend((
            f"starts={progress['starts_consumed']}/{progress['starts_maximum']}",
            f"bin={bin_progress['bin'] or '-'}",
            f"targets_passed={bin_progress['passed_target_count']}/"
            f"{bin_progress['reachable_target_count']}",
            f"targets_evaluated={bin_progress['evaluated_target_count']}/"
            f"{bin_progress['reachable_target_count']}",
        ))
        if reason is not None:
            details.append(f"reason={reason}")
        self.progress_callback(" ".join(details))

    def summary(self):
        progress = self._progress_status()
        independent_inputs = len(self.profiles)
        seed_realizations = sum(len(p.get(self.profile_id, {})) for p in self.profiles.values())
        return {"run_id": self.run_id, "phase": self.state["phase"], "bin": self.state["bin"],
                "reason": self.state["reason"], **progress,
                "independent_inputs": independent_inputs, "input_seed_realizations": seed_realizations,
                "round_index": self.state["round_index"], "stagnant_rounds": self.state["stagnant_rounds"],
                "detail": self.state.get("detail"),
                "reachable_target_count": sum(t.reachable for t in self.targets),
                "theoretically_unreachable_targets": [t.key for t in self.targets if not t.reachable],
                "scenario_combinations_per_observation": len(analysis.JR_VALUES) * len(analysis.JA_VALUES),
                "input_conditions": {
                    i: {k: v for k, v in self.state["inputs"][i].items()
                        if k not in ("realization_seed", "runtime")}
                    for i in sorted(self.profiles)},
                "verification_seeds_by_input": {
                    i: [s for s in progress["target_pass_rule"]["verification_seeds"]
                        if s in self.profiles[i].get(self.profile_id, {})]
                    for i in sorted(self.profiles)},
                "target_evidence": self.state["target_evidence"],
                "completed_round_event_indices": [row[0] for row in self.connection.execute(
                    "SELECT event_index FROM main_control_events WHERE run_id=? AND kind='round_complete' "
                    "ORDER BY event_index", (self.run_id,))],
                "operational_gate_is_statistical_sufficiency": False}

    def _report_event(self, kind):
        if not self.connection.execute("SELECT COUNT(*) FROM manifest").fetchone()[0]:
            summary = self.summary()
            summary["dataset_revision_index"], summary["dataset_sha256"] = None, None
            index = append_event(self.connection, self.run_id, kind, summary)
            self._write_event(index, summary)
            return
        revision = load_latest_cumulative_dataset_revision(self.connection)
        snapshot = analysis.build_cumulative_analysis_snapshot(revision.revision_index, revision.dataset_sha256)
        fingerprint = persist_cumulative_analysis_run(self.connection, revision, snapshot)
        persist_cumulative_derived_scores(self.connection, revision, fingerprint)
        summary = self.summary()
        summary["dataset_revision_index"] = revision.revision_index
        summary["dataset_sha256"] = revision.dataset_sha256
        index = append_event(self.connection, self.run_id, kind, summary)
        self._write_event(index, summary)

    def _write_event(self, index, summary):
        if summary["dataset_revision_index"] is not None:
            revision = load_latest_cumulative_dataset_revision(self.connection, summary["dataset_revision_index"])
            fingerprint = fingerprint_snapshot(analysis.build_cumulative_analysis_snapshot(
                revision.revision_index, revision.dataset_sha256)).sha256_hex
            from .p32_store import read_measured_p32
            measured = read_measured_p32(self.connection)
            identity = cumulative_report_identity(revision, fingerprint, measured)
            root = self.output_dir / "cumulative" / f"revision-{revision.revision_index}"
            output = root / "reports"
            def matching_report(directory):
                path = directory / "report_summary.json"
                if not path.is_file():
                    return False
                try:
                    saved = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    return False
                return (isinstance(saved, dict) and all(saved.get(k) == v for k, v in identity.items())
                        and all((directory / name).is_file() for name in CUMULATIVE_CSV_HEADERS))
            if not matching_report(output):
                if output.exists():
                    output = root / f"analysis-{fingerprint}" / "reports"
                if output.exists() and not matching_report(output):
                    output = root / f"analysis-{fingerprint}-report-{identity['report_fingerprint_sha256']}" / "reports"
                if not matching_report(output):
                    path = output / "report_summary.json"
                    if path.is_file():
                        saved = json.loads(path.read_text())
                        if (saved.get("analysis_fingerprint_sha256") != fingerprint
                            or saved.get("dataset_sha256") != revision.dataset_sha256):
                            raise ValueError("main analysis report directory contains a different analysis")
                    export_cumulative_coverage_report(output, revision, measured_p32=measured)
        directory = self.output_dir / self.run_id / f"event-{index}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "summary.json"
        content = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if path.exists():
            if path.read_text() != content:
                raise ValueError("main event report conflicts with its immutable journal")
        else:
            path.write_text(content)

    def run(self, *, recover_incomparable=False):
        if recover_incomparable and (
            self.state.get("phase") != "paused"
            or self.state.get("reason") != "incomparable"
        ):
            raise ValueError("--recover-incomparable requires a paused incomparable run")
        reconcile_starts(self.connection, self.run_id)
        for index, payload in self.connection.execute(
            "SELECT event_index,payload FROM main_control_events WHERE run_id=? ORDER BY event_index",
            (self.run_id,)).fetchall():
            self._write_event(index, json.loads(payload))
        if self.state["phase"] in ("paused", "complete"):
            if self.state["reason"] in ("user_interruption", "review_checkpoint"):
                if self.state["reason"] == "review_checkpoint":
                    self.state["review_checkpoint_released"] = True
                self.state["phase"] = self.state.pop("resume_phase")
                self.state["reason"] = None
                self._save()
            elif self.state["reason"] == "incomparable" and recover_incomparable:
                self._release_recoverable_incomparable_pause()
            else:
                return self.summary()
        try:
            if self._initial_pause is not None:
                raise self._initial_pause
            while True:
                self._check_review_checkpoint()
                if (self.state["phase"] == "exploration" and self.state["round"] is None
                    and self.state["stagnant_rounds"] >= self.config.policy.stagnant_rounds):
                    raise MainPause(
                        "stagnation",
                        {"completed_rounds_without_progress": self.state["stagnant_rounds"]})
                if self.state["queue"]:
                    task = self.state["queue"][0]
                    self._save()
                    self._perform(task)
                    self.state["queue"].pop(0)
                    self._save()
                    continue
                if self.state["phase"] == "initial":
                    self.state["phase"] = "exploration"
                    self._save()
                if self.state["round"] is not None:
                    target = self._target(self.state["round"]["target"])
                    phase = self.state["round"]["phase"]
                    if phase == "search":
                        self._plan_progress(target)
                    elif phase == "progress":
                        self._finish_progress(target)
                    elif self._plan_target_verification(target):
                        pass
                    else:
                        self._complete_round(target)
                    self._save()
                    continue
                targets = [t for t in self.targets if int(t.bin_id) == self.state["bin"] and t.reachable]
                unfinished = [t for t in targets if not target_passed(self._histories(t))]
                if not unfinished:
                    completed_bin = self.state["bin"]
                    completed_bin_progress = self._progress_status()["current_bin_progress"]
                    self._save()
                    self._report_event("bin_transition")
                    self.state["bin"] -= 1
                    self.state["stagnant_rounds"] = 0
                    if self.state["bin"] == 0:
                        self.state["phase"], self.state["reason"] = "complete", "targets_complete"
                        self._save(status="complete", reason="targets_complete")
                        self._report_event("complete")
                        self._report_progress_snapshot(
                            "bin_transition", completed_bin=completed_bin,
                            completed_bin_progress=completed_bin_progress)
                        return self.summary()
                    self._save()
                    self._report_progress_snapshot(
                        "bin_transition", completed_bin=completed_bin,
                        completed_bin_progress=completed_bin_progress)
                    continue
                ready = [t for t in unfinished if self._verification_pending(t)]
                target = self._choose_rotating(ready or unfinished, "target_cursor")
                self._plan_round(target)
                self._save()
        except KeyboardInterrupt:
            self._pause("user_interruption")
            raise
        except MainPause as pause:
            self._pause(pause.reason, pause.detail)
            return self.summary()
        except Exception as error:
            self._pause("execution_error", f"{type(error).__name__}: {error}")
            return self.summary()

    def _pause(self, reason, detail=None):
        self.state["resume_phase"] = self.state["phase"]
        self.state["phase"], self.state["reason"], self.state["detail"] = "paused", reason, detail
        reconcile_starts(self.connection, self.run_id)
        self._save(status="paused", reason=reason)
        self._report_progress_snapshot("paused", reason=reason)
        self._report_event("pause")


def execute_main(connection, config, factory, runtime, *, confirmed=False,
                 output_dir, progress_callback=None, recover_incomparable=False):
    if not confirmed:
        raise PermissionError("main execution requires explicit confirmation before writes/generation")
    if runtime.backend != "mlx":
        raise ValueError("main execution requires MLX; no automatic CPU fallback")
    runtime = replace(runtime, generator_version=FIXED_DOMAIN_GENERATOR_VERSION)
    if connection.in_transaction:
        raise ValueError("main execution requires a connection without an uncommitted transaction")
    with single_writer(connection):
        connection.execute("PRAGMA foreign_keys = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if recover_incomparable:
            if version != STORE_SCHEMA_VERSION:
                raise ValueError("--recover-incomparable requires an existing schema4 database")
            has_main_runs = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='main_control_runs'"
            ).fetchone()
            if has_main_runs is None:
                raise ValueError("--recover-incomparable requires an existing paused main run")
            matching_runs = connection.execute(
                "SELECT status,reason,runtime_snapshot FROM main_control_runs "
                "WHERE config_fingerprint=?",
                (config.fingerprint,),
            ).fetchall()
            runtime_snapshot = json.dumps(
                asdict(runtime), sort_keys=True, separators=(",", ":"), allow_nan=False,
            )
            if matching_runs != [("paused", "incomparable", runtime_snapshot)]:
                raise ValueError(
                    "--recover-incomparable requires one paused run with matching config/runtime"
                )
        if version == 0:
            initialize_store(connection)
        elif version != STORE_SCHEMA_VERSION:
            raise ValueError("main requires schema4; no automatic schema2/3 migration")
        initialize_main_store(connection)
        controller = MainController(connection, config, factory, runtime, output_dir=output_dir,
                                    progress_callback=progress_callback)
        return controller.run(recover_incomparable=recover_incomparable)
