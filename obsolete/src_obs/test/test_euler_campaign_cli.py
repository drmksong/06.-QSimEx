from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
import unittest

from src.euler_campaign.campaign import CampaignState
from src.euler_campaign.cli import (
    _clear_campaign_artifacts,
    _ProgressSimulator,
    _resolve_run_ids,
    _validate_generation_id,
    build_parser,
)
from src.euler_campaign.config import CampaignProject


class _GenerationStore:
    def __init__(self) -> None:
        self.campaign_id = "campaign-a"
        self.latest: dict[int, str] = {}
        self.generations: set[str] = set()
        self.states: set[tuple[str, int]] = set()
        self.revisions: dict[int, CampaignProject] = {}

    def load_revision(
        self, campaign_id: str, revision: int,
    ) -> CampaignProject | None:
        if campaign_id != self.campaign_id:
            return None
        return self.revisions.get(revision)

    def latest_generation(self, campaign_id: str, revision: int) -> str | None:
        if campaign_id != self.campaign_id:
            return None
        return self.latest.get(revision)

    def generation_exists(self, campaign_id: str, generation_id: str) -> bool:
        if campaign_id != self.campaign_id:
            return False
        return generation_id in self.generations

    def load_generation_state(
        self, campaign_id: str, generation_id: str, revision: int,
    ) -> CampaignState | None:
        if campaign_id != self.campaign_id:
            return None
        if generation_id in self.generations and (generation_id, revision) in self.states:
            return cast(CampaignState, object())
        return None


def _project(
    revision: int,
    *,
    parent_revision: int | None = None,
    update_rule_id: str = "normalized-gradient-gap-v2",
) -> CampaignProject:
    return cast(
        CampaignProject,
        SimpleNamespace(
            plan=SimpleNamespace(
                campaign_id="campaign-a",
                update_rule_id=update_rule_id,
            ),
            plan_revision=revision,
            parent_revision=parent_revision,
        ),
    )


class TestEulerCampaignCli(unittest.TestCase):
    def test_parser_exposes_project_resume_and_force_options(self) -> None:
        args = build_parser().parse_args(
            [
                "--project", "campaign.yaml",
                "--run-generation-id", "run-42",
                "--source-generation-id", "run-41",
                "--force-from-scratch",
            ],
        )

        self.assertEqual(str(args.project), "campaign.yaml")
        self.assertEqual(args.run_generation_id, "run-42")
        self.assertEqual(args.source_generation_id, "run-41")
        self.assertTrue(args.force_from_scratch)

    def test_simulation_completion_log_includes_qprime_summary(self) -> None:
        def interval(start: float, end: float, value: float) -> SimpleNamespace:
            return SimpleNamespace(
                start=start,
                end=end,
                qprime=SimpleNamespace(value=value),
            )

        result = SimpleNamespace(
            signature_id="a" * 64,
            domain_id="b" * 64,
            seed=42,
            boreholes=(
                SimpleNamespace(
                    borehole=SimpleNamespace(borehole_id="bh-1"),
                    intervals=(interval(0.0, 1.0, 2.0), interval(1.0, 3.0, 5.0)),
                ),
            ),
            tunnel=SimpleNamespace(intervals=(interval(0.0, 2.0, 8.0),)),
        )

        class Simulator:
            backend = "test"
            runtime_info = ()
            execution_fingerprint = "test-fingerprint"

            def evaluate(self, signature, seed):
                return result

        progress = _ProgressSimulator(
            cast(Any, Simulator()),
            SimpleNamespace(grid_id="grid", edges=(0.0, 1.0)),
        )

        with self.assertLogs("qsimex.euler_campaign", level="INFO") as captured:
            progress.evaluate(
                cast(Any, SimpleNamespace(signature_id="c" * 64)),
                42,
            )

        completed = next(
            message for message in captured.output
            if "simulation #1 completed" in message
        )
        self.assertIn("Q-prime", completed)
        self.assertIn("bh-1:n=2,min=2,mean=4,max=5", completed)
        self.assertIn("face[n=1,min=8,mean=8,max=8]", completed)

    def test_generation_id_rejects_path_components(self) -> None:
        for invalid in ("", "../run", "run/child", "run id", "é"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                _validate_generation_id(invalid, "run_generation_id")

    def test_default_run_resumes_current_generation(self) -> None:
        store = _GenerationStore()
        store.latest[1] = "run-existing"
        store.generations.add("run-existing")
        store.states.add(("run-existing", 1))

        generation_id, source_generation_id = _resolve_run_ids(
            store, _project(1), None, None, False,
        )

        self.assertEqual(generation_id, "run-existing")
        self.assertIsNone(source_generation_id)

    def test_revision_extension_continues_its_predecessor_generation(self) -> None:
        store = _GenerationStore()
        store.revisions[1] = _project(1)
        store.latest[1] = "run-source"
        store.generations.add("run-source")
        store.states.add(("run-source", 1))

        generation_id, source_generation_id = _resolve_run_ids(
            store, _project(2, parent_revision=1), None, None, False,
        )

        self.assertEqual(generation_id, "run-source")
        self.assertEqual(source_generation_id, "run-source")

    def test_skipped_revision_with_rule_change_uses_parent_and_new_generation(self) -> None:
        store = _GenerationStore()
        store.revisions[1] = _project(1)
        store.latest[1] = "run-v2"
        store.generations.add("run-v2")
        store.states.add(("run-v2", 1))

        generation_id, source_generation_id = _resolve_run_ids(
            store,
            _project(
                3,
                parent_revision=1,
                update_rule_id="normalized-gradient-density-exploration-v3",
            ),
            None,
            None,
            False,
        )

        self.assertNotEqual(generation_id, "run-v2")
        self.assertEqual(source_generation_id, "run-v2")
        self.assertNotIn(generation_id, store.generations)

    def test_resume_after_extension_uses_generation_at_current_revision(self) -> None:
        store = _GenerationStore()
        store.latest[2] = "run-extended"
        store.generations.add("run-extended")
        store.states.add(("run-extended", 2))
        store.revisions[2] = _project(2)

        generation_id, source_generation_id = _resolve_run_ids(
            store, _project(2, parent_revision=1), None, None, False,
        )

        self.assertEqual(generation_id, "run-extended")
        self.assertEqual(source_generation_id, "run-extended")

    def test_force_from_scratch_allocates_a_new_generation(self) -> None:
        store = _GenerationStore()
        store.latest[1] = "run-existing"
        store.generations.add("run-existing")
        store.states.add(("run-existing", 1))

        generation_id, source_generation_id = _resolve_run_ids(
            store, _project(1), None, None, True,
        )

        self.assertNotEqual(generation_id, "run-existing")
        self.assertNotIn("/", generation_id)
        self.assertIsNone(source_generation_id)

    def test_force_root_plan_allocates_generation_without_predecessor(self) -> None:
        generation_id, source_generation_id = _resolve_run_ids(
            _GenerationStore(), _project(3), None, None, True,
        )

        self.assertTrue(generation_id)
        self.assertIsNone(source_generation_id)

    def test_detached_root_revision_resumes_its_generation(self) -> None:
        store = _GenerationStore()
        store.latest[3] = "root-run"
        store.generations.add("root-run")
        store.states.add(("root-run", 3))

        generation_id, source_generation_id = _resolve_run_ids(
            store, _project(3), None, None, False,
        )

        self.assertEqual(generation_id, "root-run")
        self.assertEqual(source_generation_id, "root-run")

    def test_force_cleanup_removes_only_campaign_generation_outputs_and_database(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_file = root / "campaign.yaml"
            project_file.write_text("project", encoding="utf-8")
            output = (
                root / "results" / "euler_campaigns" / "campaign-a"
                / "runs" / "old-run"
            )
            output.mkdir(parents=True)
            (output / "run_summary.json").write_text("{}", encoding="utf-8")
            orphan_output = output.parent / "orphan-run"
            orphan_output.mkdir()
            (orphan_output / "partial.txt").write_text("partial", encoding="utf-8")
            database = (
                root / "results" / "euler_campaigns" / "campaign-a"
                / "campaign.sqlite3"
            )
            database.parent.mkdir(parents=True, exist_ok=True)
            database.write_text("sqlite", encoding="utf-8")
            Path(f"{database}-wal").write_text("wal", encoding="utf-8")
            unrelated = root / "results" / "euler_campaigns" / "other-campaign"
            unrelated.mkdir(parents=True)
            (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

            _clear_campaign_artifacts(
                project_file,
                "campaign-a",
                database,
                "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
                ("old-run",),
            )

            self.assertFalse(output.exists())
            self.assertFalse(orphan_output.exists())
            self.assertFalse(database.exists())
            self.assertFalse(Path(f"{database}-wal").exists())
            self.assertTrue((unrelated / "keep.txt").exists())

    def test_fresh_generation_requires_force_after_campaign_has_started(self) -> None:
        store = _GenerationStore()
        store.latest[1] = "run-existing"
        store.generations.add("run-existing")
        store.states.add(("run-existing", 1))

        with self.assertRaisesRegex(ValueError, "force-from-scratch"):
            _resolve_run_ids(
                store, _project(1), "run-new", None, False,
            )


if __name__ == "__main__":
    unittest.main()
