from __future__ import annotations

from types import SimpleNamespace
from typing import cast
import unittest

from src.euler_campaign.campaign import CampaignState
from src.euler_campaign.cli import (
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


def _project(revision: int) -> CampaignProject:
    return cast(
        CampaignProject,
        SimpleNamespace(
            plan=SimpleNamespace(campaign_id="campaign-a"),
            plan_revision=revision,
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
        store.latest[1] = "run-source"
        store.generations.add("run-source")
        store.states.add(("run-source", 1))

        generation_id, source_generation_id = _resolve_run_ids(
            store, _project(2), None, None, False,
        )

        self.assertEqual(generation_id, "run-source")
        self.assertEqual(source_generation_id, "run-source")

    def test_resume_after_extension_uses_generation_at_current_revision(self) -> None:
        store = _GenerationStore()
        store.latest[2] = "run-extended"
        store.generations.add("run-extended")
        store.states.add(("run-extended", 2))

        generation_id, source_generation_id = _resolve_run_ids(
            store, _project(2), None, None, False,
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
