from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.euler_campaign.campaign import (
    CampaignPlan,
    CampaignState,
    advance_state,
    initialize_campaign,
    run_campaign,
    run_campaign_project,
    run_round,
    _plan_fingerprint,
    validate_plan,
    RoundRecord,
)
from src.euler_campaign.campaign_store import SQLiteCampaignStore, _dump, _load
from src.euler_campaign.coverage import CoverageGrid, audit_simulation
from src.euler_campaign.config import CampaignProject, extend_campaign_project
from src.euler_campaign.euler import (
    DensityExplorationUpdateRule,
    DensitySweepCursor,
    FeatureBound,
    NormalizedGradientUpdateRule,
    OrientationSweepCursor,
)
from src.euler_campaign.models import (
    BartonCategory,
    BoreholeSpec,
    CaseSpec,
    DomainSpec,
    JointCondition,
    JointSetSpec,
    Signature,
    TunnelSpec,
    identify_signature,
)
from src.euler_campaign.profiles import (
    ProfileInterval,
    SimulationResult,
    TunnelProfile,
)
from src.euler_campaign.qprime import QPrimeProvenance, QPrimeResult


def _signature() -> Signature:
    condition = JointCondition(
        BartonCategory("jr", "Jr", "Good", 3.0, 4.0),
        BartonCategory("ja", "Ja", "Slight", 1.0, 2.0),
    )
    case = CaseSpec(
        "campaign-test",
        DomainSpec((10, 10, 10), (1.0, 1.0, 1.0), 2.0),
        (
            JointSetSpec(
                1, "set-1", "P32", 1.0, 3.0, 0.5, 5.0,
                0.0, 0.0, 20.0, condition,
            ),
        ),
        (
            BoreholeSpec(
                "bh-1", (0.0, 5.0, 5.0), (1.0, 0.0, 0.0), 10.0, 1.0,
                "face_comparison",
            ),
        ),
        TunnelSpec(((0.0, 5.0, 5.0), (10.0, 5.0, 5.0)), 1.0),
    )
    return identify_signature(case)


def _signature_with_density(density: float) -> Signature:
    signature = _signature()
    joint_set = replace(signature.case.joint_sets[0], density_value=density)
    case = replace(signature.case, joint_sets=(joint_set,))
    return identify_signature(case)


def _plan() -> CampaignPlan:
    return CampaignPlan(
        "campaign-test",
        (_signature(),),
        CoverageGrid("grid-v1", (0.0, 1.0, 10.0)),
        (
            FeatureBound("joint_sets.1.density_value", 0.1, 10.0),
            FeatureBound("joint_sets.1.size_r_min", 0.1, 1.0),
            FeatureBound("joint_sets.1.size_r_max", 1.0, 10.0),
            FeatureBound("joint_sets.1.orientation_beta@bh-1", 0.0, 90.0),
        ),
        17,
        (31, 37, 41),
    )


def _checkpoint(state: CampaignState, **lineage_changes: object) -> CampaignState:
    lineages = list(state.lineages)
    active = replace(
        lineages[state.active_lineage_index], **lineage_changes,
    )
    lineages[state.active_lineage_index] = active
    return replace(
        state, lineages=tuple(lineages), status=active.status, reason=active.reason,
    )


def _simulation(signature: Signature, seed: int, value: float) -> SimulationResult:
    provenance = QPrimeProvenance(
        "no_intersection_convention", None, None, None,
        "qsimex_no_intersection_rqd100_jr4_ja0.75",
    )
    qprime = QPrimeResult(100.0, 100.0, 2.0, 4.0, 0.75, value, provenance)
    return SimulationResult(
        signature.signature_id,
        f"{signature.signature_id}-{seed}",
        seed,
        (),
        TunnelProfile(
            (), (ProfileInterval(0.0, 1.0, qprime),), "tunnel_end", None,
        ),
    )


class _FlatSimulator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def evaluate(self, signature: Signature, seed: int) -> SimulationResult:
        self.calls.append((signature.signature_id, seed))
        return _simulation(signature, seed, 5.0)


class _DensitySimulator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def evaluate(self, signature: Signature, seed: int) -> SimulationResult:
        self.calls.append((signature.signature_id, seed))
        density = signature.case.joint_sets[0].density_value
        return _simulation(signature, seed, 5.0 if density > 1.04 else 0.5)


class _FingerprintFlatSimulator(_FlatSimulator):
    @property
    def execution_fingerprint(self) -> str:
        return "campaign-test-execution-v1"


class _MemoryStore:
    def __init__(self) -> None:
        self.plans: dict[str, CampaignPlan] = {}
        self.states: dict[str, CampaignState] = {}
        self.simulations: dict[tuple[str, str], SimulationResult] = {}
        self.rounds: list[tuple[str, RoundRecord, CampaignState]] = []

    def load_plan(self, campaign_id: str) -> CampaignPlan | None:
        return self.plans.get(campaign_id)

    def save_plan(self, plan: CampaignPlan) -> None:
        self.plans[plan.campaign_id] = plan

    def load_state(self, campaign_id: str) -> CampaignState | None:
        return self.states.get(campaign_id)

    def save_state(self, campaign_id: str, state: CampaignState) -> None:
        self.states[campaign_id] = state

    def save_simulation(self, campaign_id: str, result: SimulationResult) -> None:
        self.simulations[(campaign_id, result.domain_id)] = result

    def covered_bins(self, campaign_id: str, grid: CoverageGrid) -> frozenset[int]:
        covered: set[int] = set()
        for (stored_campaign_id, _), result in self.simulations.items():
            if stored_campaign_id == campaign_id:
                covered.update(audit_simulation(result, grid).observed_bins)
        return frozenset(covered)

    def save_round(
        self, campaign_id: str, record: RoundRecord, state: CampaignState,
    ) -> None:
        self.rounds.append((campaign_id, record, state))
        self.states[campaign_id] = state


class TestCampaignOrchestration(unittest.TestCase):
    def test_campaign_plan_preserves_unique_start_order_in_its_fingerprint(self) -> None:
        from src.euler_campaign.campaign import _plan_fingerprint

        first = _signature()
        second = _signature_with_density(2.0)
        plan = replace(_plan(), start_signatures=(first, second))
        reversed_plan = replace(plan, start_signatures=(second, first))

        validate_plan(plan)
        self.assertNotEqual(_plan_fingerprint(plan), _plan_fingerprint(reversed_plan))
        with self.assertRaisesRegex(ValueError, "unique signature IDs"):
            validate_plan(replace(plan, start_signatures=(first, first)))

    def test_campaign_initializes_and_advances_lineages_independently(self) -> None:
        first = _signature()
        second = _signature_with_density(2.0)
        plan = replace(_plan(), start_signatures=(first, second))
        state = initialize_campaign(plan)
        original_second_lineage = state.lineages[1]

        record = run_round(
            plan, state, _FlatSimulator(),
            NormalizedGradientUpdateRule(), _MemoryStore(),
        )
        advanced = advance_state(state, record)

        self.assertEqual(state.active_lineage_index, 0)
        self.assertEqual(
            tuple(lineage.start_signature_id for lineage in state.lineages),
            (first.signature_id, second.signature_id),
        )
        self.assertEqual(record.lineage_start_signature_id, first.signature_id)
        self.assertEqual(advanced.lineages[1], original_second_lineage)
        self.assertEqual(advanced.lineages[0].next_round_index, 1)

    def test_rejected_density_candidate_scales_up_without_blocking_features(self) -> None:
        rule = DensityExplorationUpdateRule()
        plan = replace(_plan(), update_rule_id=rule.rule_id)
        state = initialize_campaign(plan)
        record = run_round(
            plan, state, _DensitySimulator(), rule, _MemoryStore(),
        )
        self.assertEqual(record.proposal.status, "candidate")
        if record.verification is None:
            self.fail("candidate proposal must have verification evidence")
        rejected = replace(
            record,
            verification=replace(
                record.verification, accepted=False, reason="rejected for test",
            ),
        )

        advanced = advance_state(
            state, rejected, escalate_density_on_rejection=True,
        )

        self.assertEqual(advanced.parent, state.parent)
        self.assertEqual(advanced.blocked_features, ())
        self.assertEqual(advanced.active_lineage.density_step_scale, 2.0)
        self.assertEqual(advanced.active_lineage.status, "running")
        self.assertEqual(
            advanced.active_lineage.density_cursors,
            record.proposal.density_cursor_updates,
        )

    def test_rejected_orientation_candidate_advances_persisted_sweep_cursor(self) -> None:
        rule = DensityExplorationUpdateRule()
        plan = replace(_plan(), update_rule_id=rule.rule_id)
        state = _checkpoint(initialize_campaign(plan), next_block="orientation")
        record = run_round(plan, state, _FlatSimulator(), rule, _MemoryStore())

        self.assertEqual(record.proposal.status, "candidate")
        self.assertEqual(
            record.proposal.orientation_cursor_updates,
            (OrientationSweepCursor(
                "joint_sets.1.orientation_beta@bh-1", 10.0, 1,
            ),),
        )
        if record.verification is None:
            self.fail("candidate proposal must have verification evidence")
        rejected = replace(
            record,
            verification=replace(
                record.verification, accepted=False, reason="rejected for test",
            ),
        )

        advanced = advance_state(
            state, rejected, escalate_density_on_rejection=True,
        )

        self.assertEqual(advanced.parent, state.parent)
        self.assertEqual(advanced.blocked_features, ())
        self.assertEqual(
            advanced.active_lineage.orientation_cursors,
            record.proposal.orientation_cursor_updates,
        )

    def test_v3_size_candidate_is_seeded_and_checkpointed_per_lineage(self) -> None:
        rule = DensityExplorationUpdateRule()
        plan = replace(_plan(), update_rule_id=rule.rule_id)
        state = _checkpoint(initialize_campaign(plan), next_block="size")
        simulator = _FlatSimulator()
        store = _MemoryStore()

        first = run_round(plan, state, simulator, rule, store)
        repeated = run_round(plan, state, simulator, rule, store)

        self.assertEqual(first.proposal, repeated.proposal)
        self.assertEqual(first.probes, ())
        self.assertEqual(first.proposal.status, "candidate")
        self.assertEqual(len(first.proposal.randomized_feature_ids), 2)
        if first.proposal.candidate is None:
            self.fail("v3 size sampling must propose a candidate")
        joint_set = first.proposal.candidate.case.joint_sets[0]
        self.assertLess(joint_set.size_r_min, joint_set.size_r_max)
        advanced = advance_state(state, first)
        self.assertEqual(advanced.active_lineage.size_sample_count, 1)

        encoded = json.loads(_dump(advanced))
        restored = _load(json.dumps(encoded))
        self.assertEqual(restored, advanced)

    def test_v3_size_sampling_continues_past_former_quota(self) -> None:
        rule = DensityExplorationUpdateRule()
        plan = replace(_plan(), update_rule_id=rule.rule_id)
        state = _checkpoint(
            initialize_campaign(plan),
            next_block="size",
            size_sample_count=100,
        )

        record = run_round(plan, state, _FlatSimulator(), rule, _MemoryStore())
        advanced = advance_state(state, record)

        self.assertEqual(record.proposal.status, "candidate")
        self.assertEqual(len(record.proposal.randomized_feature_ids), 2)
        self.assertEqual(advanced.next_block, "orientation")
        self.assertEqual(advanced.active_lineage.size_sample_count, 101)

    def test_v3_resamples_only_out_of_bounds_start_size_pair(self) -> None:
        rule = DensityExplorationUpdateRule()
        original = _signature()
        original_set = replace(
            original.case.joint_sets[0],
            size_r_min=0.01,
            size_r_max=120.0,
        )
        start = identify_signature(replace(
            original.case,
            joint_sets=(original_set,),
        ))
        plan = replace(
            _plan(),
            start_signatures=(start,),
            update_rule_id=rule.rule_id,
        )

        first = initialize_campaign(plan)
        repeated = initialize_campaign(plan)

        self.assertEqual(first, repeated)
        lineage = first.active_lineage
        self.assertEqual(lineage.start_signature_id, start.signature_id)
        sampled_set = lineage.parent.case.joint_sets[0]
        self.assertGreaterEqual(sampled_set.size_r_min, 0.1)
        self.assertLessEqual(sampled_set.size_r_min, 1.0)
        self.assertGreaterEqual(sampled_set.size_r_max, 1.0)
        self.assertLessEqual(sampled_set.size_r_max, 10.0)
        self.assertLess(sampled_set.size_r_min, sampled_set.size_r_max)
        self.assertEqual(
            replace(
                sampled_set,
                size_r_min=original_set.size_r_min,
                size_r_max=original_set.size_r_max,
            ),
            original_set,
        )

    def test_v3_density_exhaustion_requests_new_start_after_planned_lineages(self) -> None:
        rule = DensityExplorationUpdateRule()
        first = _signature()
        second = _signature_with_density(2.0)
        plan = replace(
            _plan(),
            start_signatures=(first, second),
            update_rule_id=rule.rule_id,
        )
        initial = initialize_campaign(plan)
        density_cursor = DensitySweepCursor(
            "joint_sets.1.density_value", 1, True,
        )
        lineages = (
            replace(
                initial.lineages[0],
                status="running",
                density_cursors=(density_cursor,),
            ),
            replace(
                initial.lineages[1],
                density_cursors=(density_cursor,),
            ),
        )
        checkpoint = replace(
            initial,
            lineages=lineages,
            status="running",
        )
        project = CampaignProject(
            plan, "case.yaml", "catalog.yaml", 1, None, None, None,
            "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
        )

        result = run_campaign(
            plan, checkpoint, _FlatSimulator(), rule, _MemoryStore(),
        )

        self.assertEqual(result.rounds, ())
        self.assertEqual(result.state.status, "decision_required")
        self.assertIn("all planned density ranges exhausted", result.state.reason or "")
        self.assertTrue(all(
            lineage.status == "stopped" for lineage in result.state.lineages
        ))
        extended = extend_campaign_project(
            project,
            result.state,
            new_start_signatures=(_signature_with_density(3.0),),
        )
        self.assertEqual(len(extended.plan.start_signatures), 3)
        from src.euler_campaign.campaign import _state_for_project_revision

        resumed = _state_for_project_revision(project, extended, result.state)
        self.assertEqual(resumed.status, "ready")
        self.assertEqual(resumed.active_lineage_index, 2)

    def test_legacy_campaign_state_payload_uses_default_density_step_scale(self) -> None:
        state = initialize_campaign(_plan())
        encoded = json.loads(_dump(state))
        for lineage in encoded["fields"]["lineages"]["$tuple"]:
            lineage["fields"].pop("density_step_scale")
            lineage["fields"].pop("size_sample_count")
            lineage["fields"].pop("density_cursors")

        restored = _load(json.dumps(encoded))

        self.assertEqual(restored, state)

    def test_run_campaign_saturates_each_start_lineage_in_order(self) -> None:
        first = _signature()
        second = _signature_with_density(2.0)
        plan = replace(
            _plan(),
            start_signatures=(first, second),
        )
        store = _MemoryStore()
        result = run_campaign(
            plan, initialize_campaign(plan), _FlatSimulator(),
            NormalizedGradientUpdateRule(), store,
        )

        self.assertEqual(result.state.status, "all_lineages_saturated")
        self.assertEqual(result.state.active_lineage_index, 1)
        self.assertEqual(
            [round_record.lineage_start_signature_id for round_record in result.rounds],
            [first.signature_id] * 3 + [second.signature_id] * 3,
        )
        self.assertTrue(all(lineage.status == "stopped" for lineage in result.state.lineages))

    def test_validate_plan_requires_distinct_exploration_and_verification_seeds(self) -> None:
        plan = _plan()
        validate_plan(plan)
        invalid = replace(plan, verification_seeds=(31, 37, 17))
        with self.assertRaises(ValueError):
            validate_plan(invalid)

    def test_run_round_rejects_an_unplanned_update_rule(self) -> None:
        plan = replace(_plan(), update_rule_id="another-rule-v1")
        with self.assertRaises(ValueError):
            run_round(
                plan, initialize_campaign(plan), _FlatSimulator(),
                NormalizedGradientUpdateRule(), _MemoryStore(),
            )

    def test_run_round_pairs_probe_scores_on_exploration_seed(self) -> None:
        plan = _plan()
        state = initialize_campaign(plan)
        simulator = _FlatSimulator()
        store = _MemoryStore()

        record = run_round(
            plan, state, simulator, NormalizedGradientUpdateRule(), store,
        )

        self.assertEqual(record.block, "density")
        self.assertEqual(record.round_index, 0)
        self.assertEqual(len(record.probes), 1)
        self.assertEqual(record.proposal.status, "no_direction")
        self.assertTrue(all(seed == plan.exploration_seed for _, seed in simulator.calls))
        self.assertEqual(len(store.simulations), len(simulator.calls))

    def test_run_round_verifies_candidate_on_fixed_independent_seeds(self) -> None:
        plan = _plan()
        simulator = _DensitySimulator()
        store = _MemoryStore()

        record = run_round(
            plan, initialize_campaign(plan), simulator,
            NormalizedGradientUpdateRule(), store,
        )

        self.assertEqual(record.proposal.status, "candidate")
        self.assertIsNotNone(record.verification)
        verification = record.verification
        self.assertIsNotNone(verification)
        self.assertTrue(verification.accepted)
        self.assertEqual(
            tuple(score.seed for score in verification.scores),
            plan.verification_seeds,
        )
        self.assertEqual(len(simulator.calls), 9)

    def test_run_campaign_resumes_saved_round_and_explores_remaining_blocks(self) -> None:
        plan = _plan()
        initialized = initialize_campaign(plan)
        checkpoint = _checkpoint(
            initialized, next_block="orientation", next_round_index=7,
            status="running",
        )
        store = _MemoryStore()
        store.save_plan(plan)
        store.save_state(plan.campaign_id, checkpoint)
        simulator = _FlatSimulator()

        result = run_campaign(
            plan, initialized, simulator, NormalizedGradientUpdateRule(), store,
        )

        self.assertEqual([item.round_index for item in result.rounds], [7, 8, 9])
        self.assertEqual(
            [item.block for item in result.rounds],
            ["orientation", "density", "size"],
        )
        self.assertEqual(result.state.status, "all_lineages_saturated")
        self.assertIn("no untried feature", result.state.lineages[0].reason or "")
        self.assertEqual(store.states[plan.campaign_id], result.state)

    def test_run_campaign_stops_on_existing_cumulative_full_coverage(self) -> None:
        plan = _plan()
        initialized = initialize_campaign(plan)
        checkpoint = _checkpoint(
            initialized, next_block="size", next_round_index=5,
            status="running",
        )
        store = _MemoryStore()
        store.save_plan(plan)
        store.save_state(plan.campaign_id, checkpoint)
        store.save_simulation(
            plan.campaign_id, _simulation(plan.initial_parent, 101, 0.5),
        )
        store.save_simulation(
            plan.campaign_id, _simulation(plan.initial_parent, 103, 5.0),
        )
        simulator = _FlatSimulator()

        result = run_campaign(
            plan, initialized, simulator, NormalizedGradientUpdateRule(), store,
        )

        self.assertEqual(result.rounds, ())
        self.assertEqual(result.state.next_round_index, 5)
        self.assertEqual(result.state.status, "coverage_complete")
        self.assertIn("cumulative campaign pool", result.state.reason or "")
        self.assertEqual(simulator.calls, [])

    def test_campaign_project_extensions_are_explicit_and_append_only(self) -> None:
        plan = _plan()
        project = CampaignProject(
            plan, "case.yaml", "catalog.yaml", 1, None, None, 4,
            "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
        )

        exhausted = replace(
            initialize_campaign(plan),
            status="round_budget_exhausted",
            reason="round budget exhausted",
        )
        budget_revision = extend_campaign_project(
            project, exhausted, additional_rounds=3,
        )

        self.assertEqual(budget_revision.plan_revision, 2)
        self.assertEqual(budget_revision.parent_revision, 1)
        self.assertEqual(budget_revision.round_budget, 7)
        self.assertEqual(budget_revision.plan.start_signatures, plan.start_signatures)

        saturated_lineages = tuple(
            replace(lineage, status="stopped", reason="saturated")
            for lineage in initialize_campaign(plan).lineages
        )
        saturated = replace(
            initialize_campaign(plan),
            lineages=saturated_lineages,
            status="all_lineages_saturated",
            reason="all lineages saturated",
        )
        start_revision = extend_campaign_project(
            replace(project, round_budget=None),
            saturated,
            new_start_signatures=(_signature_with_density(2.0),),
        )

        self.assertEqual(
            start_revision.plan.start_signatures,
            (plan.start_signatures[0], _signature_with_density(2.0)),
        )
        self.assertIsNone(start_revision.round_budget)
        with self.assertRaisesRegex(ValueError, "saturated campaign"):
            extend_campaign_project(project, exhausted, new_start_signatures=(_signature_with_density(2.0),))

    def test_sqlite_campaign_store_persists_generation_and_isolates_coverage(self) -> None:
        plan = _plan()
        project = CampaignProject(
            plan, "case.yaml", "catalog.yaml", 1, None, None, None,
            "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
        )
        state = initialize_campaign(plan)
        result = _simulation(plan.initial_parent, plan.exploration_seed, 5.0)
        simulation_fingerprint = "a" * 64

        with TemporaryDirectory() as directory:
            database = Path(directory) / "campaign.sqlite"
            store = SQLiteCampaignStore(database)
            store.save_revision(project)
            store.create_generation(
                plan.campaign_id, "generation-one", 1,
                simulation_fingerprint, state,
            )
            store.save_generation_simulation(
                plan.campaign_id, "generation-one", simulation_fingerprint,
                1, result,
            )
            self.assertEqual(
                store.load_generation_simulation(
                    plan.campaign_id, "generation-one", simulation_fingerprint,
                    result.signature_id, result.seed,
                ),
                result,
            )
            self.assertEqual(
                store.generation_covered_bins(
                    plan.campaign_id, "generation-one", plan.grid,
                ),
                frozenset({1}),
            )

            store.create_generation(
                plan.campaign_id, "generation-two", 1,
                "b" * 64, state,
            )
            self.assertEqual(
                store.generation_covered_bins(
                    plan.campaign_id, "generation-two", plan.grid,
                ),
                frozenset(),
            )
            store.close()

            reopened = SQLiteCampaignStore(database)
            self.assertEqual(reopened.load_revision(plan.campaign_id, 1), project)
            self.assertEqual(
                reopened.load_generation_state(
                    plan.campaign_id, "generation-one", 1,
                ),
                state,
            )
            self.assertEqual(
                reopened.generation_round_count(plan.campaign_id, "generation-one"),
                0,
            )
            reopened.close()

    def test_revision_runner_resumes_extends_and_keeps_generations_isolated(self) -> None:
        plan = _plan()
        project = CampaignProject(
            plan, "case.yaml", "catalog.yaml", 1, None, None, 1,
            "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
        )
        simulator = _FingerprintFlatSimulator()

        with TemporaryDirectory() as directory:
            store = SQLiteCampaignStore(Path(directory) / "campaign.sqlite")
            first = run_campaign_project(
                project, simulator, NormalizedGradientUpdateRule(), store,
            )
            self.assertEqual(first.state.status, "round_budget_exhausted")
            self.assertEqual(len(first.rounds), 1)
            generation_id = first.run_generation_id
            self.assertIsNotNone(generation_id)
            calls_after_first_round = len(simulator.calls)

            resumed = run_campaign_project(
                project, simulator, NormalizedGradientUpdateRule(), store,
            )
            self.assertEqual(resumed.run_generation_id, generation_id)
            self.assertEqual(resumed.rounds, ())
            self.assertEqual(len(simulator.calls), calls_after_first_round)

            extended_project = extend_campaign_project(
                project, first.state, additional_rounds=1,
            )
            extended = run_campaign_project(
                extended_project,
                simulator,
                NormalizedGradientUpdateRule(),
                store,
                source_generation_id=generation_id,
                run_generation_id=generation_id,
            )
            self.assertEqual(extended.run_generation_id, generation_id)
            self.assertEqual(len(extended.rounds), 1)
            self.assertEqual(
                store.generation_round_count(plan.campaign_id, generation_id),
                2,
            )

            saturated_plan = replace(plan, campaign_id="saturation-campaign")
            saturated_project = replace(
                project, plan=saturated_plan, round_budget=None,
            )
            saturated = run_campaign_project(
                saturated_project,
                simulator,
                NormalizedGradientUpdateRule(),
                store,
                run_generation_id="saturated-generation",
            )
            self.assertEqual(saturated.state.status, "all_lineages_saturated")
            self.assertEqual(len(saturated.rounds), 3)
            start_extension = extend_campaign_project(
                saturated_project,
                saturated.state,
                new_start_signatures=(_signature_with_density(2.0),),
            )
            continued = run_campaign_project(
                start_extension,
                simulator,
                NormalizedGradientUpdateRule(),
                store,
                source_generation_id="saturated-generation",
                run_generation_id="saturated-generation",
            )
            self.assertEqual(continued.state.status, "all_lineages_saturated")
            self.assertEqual(len(continued.rounds), 3)
            self.assertEqual(
                store.generation_round_count(
                    saturated_plan.campaign_id, "saturated-generation",
                ),
                6,
            )

            fresh = run_campaign_project(
                start_extension,
                simulator,
                NormalizedGradientUpdateRule(),
                store,
                source_generation_id="saturated-generation",
                run_generation_id="fresh-generation",
                force_from_scratch=True,
            )
            self.assertEqual(fresh.run_generation_id, "fresh-generation")
            self.assertEqual(fresh.state.status, "all_lineages_saturated")
            self.assertEqual(len(fresh.rounds), 6)
            self.assertEqual(
                store.generation_round_count(
                    saturated_plan.campaign_id, "saturated-generation",
                ),
                6,
            )
            self.assertEqual(
                store.generation_round_count(
                    saturated_plan.campaign_id, "fresh-generation",
                ),
                6,
            )
            self.assertEqual(
                store.generation_covered_bins(
                    saturated_plan.campaign_id, "fresh-generation",
                    saturated_plan.grid,
                ),
                frozenset({1}),
            )
            store.close()

    def test_rule_change_revision_skips_number_and_starts_fresh_generation(self) -> None:
        plan = _plan()
        project = CampaignProject(
            plan, "case.yaml", "catalog.yaml", 1, None, None, 1,
            "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
        )
        simulator = _FingerprintFlatSimulator()

        with TemporaryDirectory() as directory:
            store = SQLiteCampaignStore(Path(directory) / "campaign.sqlite")
            previous = run_campaign_project(
                project, simulator, NormalizedGradientUpdateRule(), store,
            )
            previous_generation = previous.run_generation_id
            self.assertIsNotNone(previous_generation)

            v3_plan = replace(
                plan,
                update_rule_id=DensityExplorationUpdateRule().rule_id,
            )
            v3_project = replace(
                project,
                plan=v3_plan,
                plan_revision=3,
                parent_revision=1,
                parent_plan_fingerprint=_plan_fingerprint(plan),
            )
            revised = run_campaign_project(
                v3_project,
                simulator,
                DensityExplorationUpdateRule(),
                store,
            )

            self.assertEqual(revised.run_generation_id, store.latest_generation(
                plan.campaign_id, 3,
            ))
            self.assertNotEqual(revised.run_generation_id, previous_generation)
            self.assertEqual(revised.state.status, "round_budget_exhausted")
            self.assertEqual(store.load_revision(plan.campaign_id, 2), None)
            self.assertEqual(store.load_revision(plan.campaign_id, 3), v3_project)
            self.assertEqual(
                store.generation_round_count(plan.campaign_id, previous_generation),
                1,
            )

            resumed = run_campaign_project(
                v3_project,
                simulator,
                DensityExplorationUpdateRule(),
                store,
            )
            self.assertEqual(resumed.run_generation_id, revised.run_generation_id)
            self.assertEqual(resumed.rounds, ())
            store.close()

    def test_detached_revision_three_can_be_saved_as_a_fresh_campaign_root(self) -> None:
        plan = _plan()
        plan = replace(
            plan,
            update_rule_id=DensityExplorationUpdateRule().rule_id,
        )
        project = CampaignProject(
            plan, "case.yaml", "catalog.yaml", 3, None, None, 1,
            "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
        )

        with TemporaryDirectory() as directory:
            store = SQLiteCampaignStore(Path(directory) / "campaign.sqlite")
            result = run_campaign_project(
                project,
                _FingerprintFlatSimulator(),
                DensityExplorationUpdateRule(),
                store,
                run_generation_id="fresh-root-generation",
            )

            self.assertEqual(result.run_generation_id, "fresh-root-generation")
            self.assertEqual(store.load_revision(plan.campaign_id, 3), project)
            self.assertIsNone(store.load_revision(plan.campaign_id, 1))
            store.close()


if __name__ == "__main__":
    unittest.main()
